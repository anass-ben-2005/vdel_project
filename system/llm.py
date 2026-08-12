"""system/llm.py — the LLM Gateway (M3, BUILD_PLAN 3.1).

Transcribed from `VDEL_Modules_3_9_Build.md` Part H (1700-1783), with five deliberate
divergences, each recorded rather than silent. The full verbatim contract this was designed
against is in `docs/reading/2026-08-12-llm-gateway-spec.md`.

**One door, two verbs (invariants 3 and 4).** H's design is a single
`llm_call(prompt, temperature=0.0, ...)`. That satisfies invariant 3 (every LLM call goes
through one place) but only *discourages* invariant 4 (temperature 0 for judging) -- a free
float parameter with a good default is one keystroke from `temperature=0.9` in a grading
path, and nothing would catch it. So the call is split by purpose instead:

  - `judge()`   has NO temperature parameter. Temperature 0 is not the default, it is the
                only representable value. Violating invariant 4 while judging is not
                discouraged, it is unsayable.
  - `generate()` takes a temperature, and exists for the non-judging calls that legitimately
                need one -- `reflection.py`'s weekly narrative, and the coach if it is ever
                built.

The split makes the invariant *checkable*: `generate` appearing anywhere under `agents/` is
a grep away, and belongs in a test, the same way `memory.py`'s `_require` makes an unknown
actor a raised error rather than a convention. Both funnel through one private `_complete`,
so there is still exactly one place a provider SDK is touched -- enforced at lint time too,
see `pyproject.toml`'s `flake8-tidy-imports.banned-api`.

**D-022 -- validation and the corrective retry live HERE, not in the caller.** This is a
deliberate divergence from H's *executable code*, which retries inside
`agents/code_agent.py` (D.5, 922-929) by calling `llm_call` twice. The module document
disagrees with itself: its own gateway docstring (1707) claims "one corrective retry on
invalid JSON" as a gateway responsibility, and `BUILD_PLAN` 3.1 puts the "pydantic
validation + single corrective retry policy" in this file. Because the document's prose and
its code conflict, CLAUDE.md's "the documents win" tiebreak does not resolve it -- so it was
decided rather than inherited. Gateway-side, because caller-side means every agent
reimplements invariant 5 by hand and the first one to forget breaks it silently.

**Generic over schema; agents own their verdict shape.** `judge` takes the pydantic model as
an argument and returns an instance of it. The gateway validates; it never defines what a
verdict looks like. Three reasons, and the third is the load-bearing one:
  1. `Modules_3_9` 1929-1931 specifies "pydantic **per agent**".
  2. D.5 defines `Verdict` in `agents/code_agent.py`, not here.
  3. `agents/echo_agent.py` already owns `EchoVerdict` -- live, committed, and carrying an
     `evidence_failures` field D.5's `Verdict` lacks (added because M6's Reviewer reads it).
     A gateway-owned verdict would have to know about that field, which is an M6 concern
     reaching two layers down into transport. Generic-over-schema keeps Echo's contract --
     the M2 seam M4 must preserve -- untouched by anything M3 does.

**D-025 -- `temperature=0` is not representable on every model, so it is sent only where the
provider accepts it.** Claude Sonnet 5 -- `MODEL_TIERS`'s corrected default (D-024) -- and
every model 4.7-and-later reject an explicit non-default `temperature` with a 400; only
omitting the parameter (or passing the provider's own default) is accepted. Sending a
hardcoded `temperature=0.0` unconditionally, as D.5 does, would 400 on exactly the model this
gateway defaults to. So `_call_anthropic` sends `temperature=0.0` where the provider allows
it and OMITS the parameter where it does not, for a `0.0` request specifically -- `judge()`
always asks for `0.0`, so this never weakens invariant 4, it widens what satisfies it: the
rule becomes "never send a non-default sampling parameter", which is what actually holds
across the whole model family, not "always send a literal 0" which no longer typechecks
against half the catalog. A `generate()` call asking for a genuine non-zero temperature on a
rejecting model raises instead of silently substituting a different value -- omission is an
acceptable stand-in for "as close to greedy as this model allows", never for "the caller
asked for 0.7 and got something else with no error."

Evidence validation is NOT here: `validate_evidence` string-matches quotes against the
submission and belongs to `agents/validation.py` (BUILD_PLAN 4.4). This gateway knows about
transport, schemas, cost and caching. It knows nothing about rubrics.

**One provider live, two stubbed.** Anthropic is real -- it is `.env.example`'s documented
default and the only provider this repo has credentials for. OpenAI and the local-Qwen path
are structural stubs: their branch exists in `_PROVIDER_HANDLERS` so the dispatch is real
(selecting "openai" routes to OpenAI-shaped code, not a silent no-op or an "unknown
provider" error), but calling either raises `NotImplementedError` until BUILD_PLAN 3.2's
benchmark actually names a second candidate. `google` is not a branch at all -- see D-023.

Known gaps and open questions, none silent:
  - **D-020 (OPEN)** -- four sources disagree on what `_cache_key` keys on. `_cache_key` is
    implemented against the code's literal formula (the document's own stated "safer
    default"), because a cache with no body cannot be tested and this file's callers need
    one -- but that is still a default, not a ratified decision. Revisit before M4.
  - `cohort_cost` is NOT in this module. It lives in `benchmark/run_benchmark.py` (H, 689),
    importing `judge`/`generate` rather than being part of the gateway.
  - Nothing enforces that `generate` stays out of `agents/` beyond the lint ban on importing
    provider SDKs directly. A grep-based test is still worth writing once the first
    LLM-backed agent lands.
  - `_REJECTS_NONDEFAULT_TEMPERATURE` is a maintained set sourced from documented per-model
    breaking changes, not a live capability query. It must be re-checked whenever
    `MODEL_TIERS` gains a model id this file has not seen before.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from enum import StrEnum
from typing import NoReturn, TypeVar

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

load_dotenv()

# ---- Providers ---------------------------------------------------------------------------
#
# D-023: an enum, not a bare string, and **`google` is deliberately absent**. The document's
# MODEL_TIERS (1719-1729) declares four providers while `llm_call`'s if/elif chain
# (1753-1778) serves three -- setting LLM_PROVIDER=google selects a model id successfully and
# then dies on `raise ValueError(f"unknown LLM_PROVIDER {PROVIDER}")` at call time, after the
# prompt is assembled. Typing the provider makes that a startup failure instead of a runtime
# one, which is the same argument the `judge`/`generate` split makes for temperature: a
# constraint the type system can hold should not be left to a runtime branch.
#
# Consequence to carry, not to hide: Google is therefore NOT a benchmark candidate.
# `benchmark/RECOMMENDATION.md` must name it as a candidate that was not evaluated -- an
# unevaluated option named is defensible, an option silently dropped is not.


class Provider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    QWEN_LOCAL = "qwen_local"


def _read_provider() -> Provider:
    """Read LLM_PROVIDER and validate it, at import time, so a typo fails the process
    rather than the twentieth grading call (D-023)."""
    raw = os.environ.get("LLM_PROVIDER", "anthropic")
    try:
        return Provider(raw)
    except ValueError:
        allowed = ", ".join(p.value for p in Provider)
        raise RuntimeError(
            f"unknown LLM_PROVIDER {raw!r}. Allowed: {allowed}. D-023: an unservable "
            "provider is a startup failure, not a runtime one."
        ) from None


PROVIDER: Provider = _read_provider()

# ---- Model tiers (D-024) ------------------------------------------------------------------
#
# **These ids are NOT verified and must not be treated as measured.** BUILD_PLAN 3.4 scopes
# the research explicitly -- "current model versions only -- the method is fixed, only the
# contestants change" -- and until that runs, this table is a shape with placeholders in it.
#
# Two entries are current as of 2026-08-12 and were corrected against the stale values in
# the source document:
#   - "claude-sonnet-5"  supersedes the document's "claude-sonnet-4-5"
#   - "claude-haiku-4-5" is unchanged -- still current
# The rest are TODO(verify) rather than guesses, per CLAUDE.md §10's rule against invented
# versions. A wrong model id here does not fail loudly: it 404s at the first real call, or
# worse, silently benchmarks a model nobody chose.
MODEL_TIERS: dict[str, dict[Provider, str]] = {
    "default": {
        Provider.ANTHROPIC: "claude-sonnet-5",
        Provider.OPENAI: "TODO(verify)",
        Provider.QWEN_LOCAL: "TODO(verify)",
    },
    "cheap": {
        Provider.ANTHROPIC: "claude-haiku-4-5",
        Provider.OPENAI: "TODO(verify)",
        Provider.QWEN_LOCAL: "TODO(verify)",
    },
}

# In-process, per the document's own "replace with a persistent cache in prod". Fine for M3:
# the benchmark runs in one process, and the one place caching must NOT apply is stated at
# `judge` -- the benchmark passes `use_cache=False` so "re-running reproduces the matrix"
# measures the model, not a dict.
CACHE: dict[str, str] = {}

# Append-only record of every call, including failed and retried ones -- see CallRecord for
# why the failures are the point rather than noise.
COST_LOG: list[CallRecord] = []

T = TypeVar("T", bound=BaseModel)


class CallRecord(BaseModel):
    """What one provider call cost, and whether it worked.

    Richer than H's `_log_cost` (1737-1740), which records ts/model/tokens/elapsed and
    nothing about success. The three added fields exist for one reason, and it is a
    requirement, not bookkeeping:

    **`cohort_cost` takes `json_retry_rate=0.05` as a defaulted parameter** (H, 691). That
    default is an invented number, and BUILD_PLAN 3.1 is explicit that the retry rate belongs
    *in the formula* because "a cheap-per-call model with high JSON breakage can be more
    expensive end to end" -- which is the whole cost argument M3 exists to make. A defaulted
    retry rate cannot make that argument; a measured one can. Nothing in H's `_log_cost` can
    produce that measurement, so `attempt` and `schema_valid` are what make it derivable:
    retry rate = (records with attempt == 2) / (records with attempt == 1).

    **This is a stated requirement on `benchmark/run_benchmark.py`, not a note (D-024):** it
    must compute `json_retry_rate` from COST_LOG and pass it to `cohort_cost` explicitly.
    Calling `cohort_cost` on its default is a fabricated number in a deliverable whose entire
    purpose is measurement.

    `cache_hit` is separate from `attempt` because a cached response costs nothing and must
    not dilute either the cost totals or the retry rate.

    `schema_valid` is meaningless for a `generate()` call -- there is no schema to fail
    against -- and is set `True` there by convention ("nothing invalidated it"), not because
    anything was checked. Only `judge()`'s records carry a schema-validation verdict that
    means what it says.
    """

    ts: float
    model: str
    temperature: float
    tokens_in: int
    tokens_out: int
    elapsed_s: float
    cache_hit: bool
    attempt: int
    schema_valid: bool
    flagged: bool


class SchemaValidationError(RuntimeError):
    """Both attempts failed to produce output matching the schema.

    Raised rather than returned, so invariant 5's "never silently drop" is structural: a
    caller cannot accidentally treat an unvalidated response as a verdict, because there is
    no value to treat. Carries the `CallRecord`s from both attempts so the cost of a failed
    grading is still accounted for -- a failure that vanishes from COST_LOG would understate
    exactly the model whose JSON breaks most, which is the comparison M3 is built to make.
    """

    def __init__(self, message: str, records: list[CallRecord]) -> None:
        super().__init__(message)
        self.records = records


# ---- The two doors -------------------------------------------------------------------------

_CORRECTIVE_SUFFIX = (
    "\n\nYour previous response did not parse as valid JSON matching the required schema. "
    "Return ONLY the corrected JSON matching the schema exactly, with no additional text."
)


def judge(prompt: str, schema: type[T], *,
          model_tier: str = "default",
          model: str | None = None,
          use_cache: bool = True) -> tuple[T, CallRecord]:
    """One judging call at temperature 0, validated against `schema`. The only door agents use.

    **There is no `temperature` parameter, deliberately** -- see the module docstring.
    Invariant 4 is not enforced here by a default; it is enforced by the absence of a way to
    say anything else.

    Validates the response against `schema`, and on failure issues exactly ONE corrective
    retry before raising `SchemaValidationError` (D-022, invariant 5). The retry is this
    function's job, not the caller's, so no agent has to remember to implement it.

    Returns the validated model instance *and* its `CallRecord`, rather than logging the cost
    silently to COST_LOG alone. The caller needs the record to attribute cost to a student, an
    assignment or a benchmark run; a global append-only log alone cannot answer "what did
    grading this submission cost".

    **`use_cache=False` is required for the benchmark, and the reason is the DoD.** M3's DoD
    is "re-running the benchmark reproduces the matrix". With the cache on, a re-run replays
    stored strings and reproduces *by construction* -- proving that a dict is deterministic,
    not that the model is stable. That is the same vacuous pass `scripts/prove_event_sourcing`
    already refuses to print when the database is empty. `benchmark/run_benchmark.py` must
    pass `use_cache=False`; the default stays True because everywhere else caching an
    identical prompt is free money.
    """
    resolved_model = _resolve_model(model, model_tier)

    raw, first = _complete(prompt, 0.0, resolved_model, use_cache)
    try:
        validated = schema.model_validate_json(raw)
    except ValidationError:
        pass
    else:
        first = first.model_copy(update={"schema_valid": True})
        _log_cost(first)
        return validated, first

    # First attempt failed validation. Log it before retrying -- invariant 5 again: a failed
    # attempt that never reaches COST_LOG because the function kept going is a silent drop
    # by another name.
    failed_first = first.model_copy(update={"schema_valid": False})
    _log_cost(failed_first)

    raw2, second = _complete(prompt + _CORRECTIVE_SUFFIX, 0.0, resolved_model, use_cache)
    second = second.model_copy(update={"attempt": 2})
    try:
        validated = schema.model_validate_json(raw2)
    except ValidationError:
        flagged = second.model_copy(update={"schema_valid": False, "flagged": True})
        _log_cost(flagged)
        raise SchemaValidationError(
            f"two attempts, both invalid against {schema.__name__} -- flagged for review, "
            "never silently dropped (invariant 5). See .records for both attempts' cost.",
            [failed_first, flagged],
        ) from None

    second = second.model_copy(update={"schema_valid": True})
    _log_cost(second)
    return validated, second


def generate(prompt: str, *, temperature: float,
             model_tier: str = "default",
             model: str | None = None,
             use_cache: bool = True) -> tuple[str, CallRecord]:
    """One NON-judging call, at a temperature the caller chooses. Returns raw text.

    For the calls where a temperature above 0 is legitimate: `memory/reflection.py`'s weekly
    narrative (the slow path), and the coach if M7 is ever built. Returns `str`, not a
    validated model -- callers that need structure should be using `judge`.

    **This function must never appear under `agents/`.** That is what makes the
    `judge`/`generate` split enforcement rather than advice: an agent reaching for a
    temperature is a visible, greppable act in a diff, not a defaulted argument nobody reads.
    Worth a test once the first LLM-backed agent lands.

    A non-zero temperature on a model that only accepts its own default (D-025) raises from
    inside `_call_anthropic` rather than silently running at whatever temperature the model
    actually used -- the caller asked for a specific value and either gets it or gets told
    why not, never a substitution with no error.
    """
    resolved_model = _resolve_model(model, model_tier)
    text, record = _complete(prompt, temperature, resolved_model, use_cache)
    _log_cost(record)
    return text, record


def _resolve_model(model: str | None, model_tier: str) -> str:
    """An explicit `model` always wins; otherwise look up `model_tier` for `PROVIDER`."""
    if model is not None:
        return model
    try:
        return MODEL_TIERS[model_tier][PROVIDER]
    except KeyError:
        allowed = sorted(MODEL_TIERS)
        raise ValueError(
            f"unknown model_tier {model_tier!r} for provider {PROVIDER.value!r}. "
            f"Allowed tiers: {allowed}."
        ) from None


# ---- Internals ------------------------------------------------------------------------------


def _complete(prompt: str, temperature: float, model: str,
              use_cache: bool) -> tuple[str, CallRecord]:
    """The single place a provider SDK is called. Invariant 3's actual choke point.

    `judge` and `generate` are the two doors agents see; this is the one room behind both, so
    the provider branch, the cache lookup and the cost log each exist exactly once. Knows
    nothing about schemas or retries -- those are `judge`'s, one layer up -- so every
    `CallRecord` it builds carries `attempt=1` and `schema_valid=True` (D-022's default of
    "nothing invalidated it yet"); `judge` overrides both fields with `model_copy` once it
    knows better.
    """
    key = _cache_key(prompt, model, temperature)
    if use_cache and key in CACHE:
        record = CallRecord(
            ts=time.time(), model=model, temperature=temperature,
            tokens_in=0, tokens_out=0, elapsed_s=0.0, cache_hit=True,
            attempt=1, schema_valid=True, flagged=False,
        )
        return CACHE[key], record

    t0 = time.time()
    handler = _PROVIDER_HANDLERS[PROVIDER]
    text, tokens_in, tokens_out = handler(prompt, temperature, model)
    elapsed = time.time() - t0

    if use_cache:
        CACHE[key] = text

    record = CallRecord(
        ts=t0, model=model, temperature=temperature,
        tokens_in=tokens_in, tokens_out=tokens_out, elapsed_s=elapsed,
        cache_hit=False, attempt=1, schema_valid=True, flagged=False,
    )
    return text, record


def _cache_key(prompt: str, model: str, temperature: float) -> str:
    """**D-020 (OPEN) -- four sources disagree on what this keys on.**

    | source | claimed key |
    |---|---|
    | `Modules_3_9` 1709 (docstring) | `(submission_hash, prompt_version, model)` |
    | `Modules_3_9` 1732-1734 (code)  | `sha256(f"{model}:{temperature}:{prompt}")` |
    | `VDEL_v1_Execution_Plan` 155    | `(prompt_hash, model, temperature)` |
    | `BUILD_PLAN` 190               | "keyed by prompt hash" |

    Implemented against the code's literal formula, because the code is what runs and the
    Execution Plan agrees with its shape -- but that is still a default, not a ratified
    decision, unlike D-007/D-008 where a live implementation existed to defer to. Settle
    D-020 before M4 depends on cache behaviour more than "it works for now".

    One constraint holds under every candidate and is why `temperature` is a key input at
    all: without it, a `judge` result at 0 and a `generate` result at 0.9 for the same prompt
    and model collide, and the judging path would silently serve a sampled response.
    """
    return hashlib.sha256(f"{model}:{temperature}:{prompt}".encode()).hexdigest()


def _log_cost(record: CallRecord) -> None:
    """Append to COST_LOG. Records failures and retries too -- see CallRecord for why."""
    COST_LOG.append(record)


# ---- Provider handlers ----------------------------------------------------------------------
#
# One function per provider, same signature, dispatched by PROVIDER. The dispatch existing
# (not an else-raise on an unrecognised provider) is what makes the abstraction real: adding
# OpenAI or Qwen for real later means filling in one function, not restructuring how any of
# this is called.

_MAX_TOKENS = 1500  # matches H's llm_call (1756); unexamined, carried across unchanged.

# Models that reject an explicit non-default `temperature`/`top_p`/`top_k` (D-025). Current
# as of 2026-08-12, sourced from documented per-model breaking changes -- not a live
# capability query, so this set must be re-checked by hand whenever MODEL_TIERS gains a model
# id this file has not seen before.
_REJECTS_NONDEFAULT_TEMPERATURE = frozenset({
    "claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-mythos-5",
    "claude-opus-4-8", "claude-opus-4-7",
})


def _call_anthropic(prompt: str, temperature: float, model: str) -> tuple[str, int, int]:
    """The one live branch. `import anthropic` is local, matching H's own pattern (1754) --
    no other module in this repo needs the SDK installed, only this function.

    Builds `temperature` into the request only where `model` accepts a non-default value
    (D-025). For a `temperature == 0.0` request (every `judge()` call, or a greedy
    `generate()`) on a rejecting model, the parameter is omitted rather than sent, which the
    provider treats as "use your own default" -- the closest available approximation. For a
    genuinely non-zero request the model cannot honour, this raises rather than silently
    running at whatever temperature the model actually used.
    """
    import anthropic

    client = anthropic.Anthropic()
    kwargs: dict[str, object] = {
        "model": model,
        "max_tokens": _MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }
    if model not in _REJECTS_NONDEFAULT_TEMPERATURE:
        kwargs["temperature"] = temperature
    elif temperature != 0.0:
        raise ValueError(
            f"{model} accepts only its own default sampling temperature (D-025) and cannot "
            f"honour an explicit temperature={temperature!r}. Choose a pre-4.7 model for a "
            "generate() call that needs real sampling variance."
        )
    # else: temperature == 0.0 was requested and this model rejects an explicit 0 --
    # omit the parameter and use the model's calibrated default, per D-025.

    response = client.messages.create(**kwargs)
    text = next(block.text for block in response.content if block.type == "text")
    return text, response.usage.input_tokens, response.usage.output_tokens


def _stub_provider(provider: Provider) -> NoReturn:
    """Shared body for a provider whose dispatch branch exists but is not wired up.

    BUILD_PLAN 3.1 says "two providers behind llm.py (one hosted, one open/Kaggle path)"
    without naming either beyond Anthropic being the one this repo has credentials for.
    Raising here -- rather than the branch not existing -- is what proves the dispatch is
    real: selecting "openai" routes to OpenAI-shaped code and fails there, not at an
    `unknown provider` check that would fire for a typo just the same.
    """
    raise NotImplementedError(
        f"the {provider.value} provider is a structural stub: BUILD_PLAN 3.2's benchmark "
        "has not named it a candidate yet. Implement this branch when it does."
    )


def _call_openai(prompt: str, temperature: float, model: str) -> tuple[str, int, int]:
    _stub_provider(Provider.OPENAI)


def _call_qwen_local(prompt: str, temperature: float, model: str) -> tuple[str, int, int]:
    _stub_provider(Provider.QWEN_LOCAL)


_PROVIDER_HANDLERS: dict[Provider, Callable[[str, float, str], tuple[str, int, int]]] = {
    Provider.ANTHROPIC: _call_anthropic,
    Provider.OPENAI: _call_openai,
    Provider.QWEN_LOCAL: _call_qwen_local,
}
