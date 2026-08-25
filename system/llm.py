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

**Three providers live, one stubbed.** Anthropic is `.env.example`'s documented default and
the only provider any judged/graded call in this repo has actually exercised. NVIDIA (D-031)
and Google (D-032) are config-switchable live alternatives (`LLM_PROVIDER=nvidia` /
`LLM_PROVIDER=google`), added without touching the default or deleting anything. OpenAI
proper stays a structural stub: the branch exists in `_PROVIDER_HANDLERS` so the dispatch is
real (selecting "openai" routes to OpenAI-shaped code, not a silent no-op or an "unknown
provider" error), but calling it raises `NotImplementedError` until BUILD_PLAN 3.2's
benchmark actually names it a paid candidate. `qwen_local` remains stubbed the same way.

**D-031 -- the NVIDIA branch's model id is user-supplied, not independently verified.**
`deepseek-ai/deepseek-v4-pro` was given directly by Anas as the exact string to use. Unlike
D-024's correction of the Anthropic default, which was checked against verified
documentation before being written in, this session has no way to confirm the id against
NVIDIA's live catalog -- it is recorded as-supplied, not as verified, and
`MODEL_TIERS["cheap"][Provider.NVIDIA]` stays `TODO(verify)` because no cheap-tier
equivalent was specified.

**D-032 -- `google` reinstated; supersedes D-023.** D-023's rejection ("no document asks for
a Google integration") was not wrong when it was written, but Anas asked for it directly this
session, so it is reinstated as a live branch rather than left absent -- see D-032 in
`docs/DECISIONS.md` for the full record, including why D-023's own text stays verbatim rather
than being edited (append-only). `_call_google` uses `client.models.generate_content`, not
the newer-recommended `client.interactions.create` -- both exist on the installed SDK, but
`generate_content`'s `config` parameter is a typed `GenerateContentConfig` with a real
`temperature: float` field, confirmed by introspecting the actual installed package rather
than trusted from documentation prose; `interactions.create`'s real signature is
`(*, request=None, ..., **body: Any)`, an opaque passthrough neither of two fetched
documentation pages fully specified. Model ids `gemini-3.7-flash` (default) and
`gemini-3.5-flash-lite` (cheap) were cross-checked live against ai.google.dev on 2026-08-19,
independently of the SDK-shape verification.

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
# D-023 (historical -- SUPERSEDED by D-032, see docs/DECISIONS.md): an enum, not a bare
# string, was chosen because the document's MODEL_TIERS (1719-1729) declares four providers
# while `llm_call`'s if/elif chain (1753-1778) serves three -- setting LLM_PROVIDER=google
# selected a model id successfully and then died on `raise ValueError(f"unknown
# LLM_PROVIDER {PROVIDER}")` at call time, after the prompt was assembled. Typing the
# provider makes an unservable one a startup failure instead of a runtime one, which is the
# same argument the `judge`/`generate` split makes for temperature: a constraint the type
# system can hold should not be left to a runtime branch. That reasoning is why `Provider`
# is an enum at all, and it still holds -- what changed under D-032 is only that `google` is
# no longer one of the unservable ones. Kept here rather than deleted so the "why an enum"
# reasoning survives; D-023's own removal-of-google reasoning is superseded, not this part.


class Provider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    QWEN_LOCAL = "qwen_local"
    NVIDIA = "nvidia"  # D-031: OpenAI-compatible hosted endpoint, added live, not stubbed
    GOOGLE = "google"  # D-032: reinstated live, supersedes D-023's removal


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
        # D-031: supplied directly by Anas, not independently verified against NVIDIA's
        # live catalog by this session -- see the module docstring.
        Provider.NVIDIA: "deepseek-ai/deepseek-v4-pro",
        # D-032: verified live against ai.google.dev/gemini-api/docs/models on 2026-08-19,
        # cross-checked with two independent fetches -- marked stable/GA, not preview.
        Provider.GOOGLE: "gemini-3.7-flash",
    },
    "cheap": {
        Provider.ANTHROPIC: "claude-haiku-4-5",
        Provider.OPENAI: "TODO(verify)",
        Provider.QWEN_LOCAL: "TODO(verify)",
        Provider.NVIDIA: "TODO(verify)",  # no cheap-tier DeepSeek variant was specified
        Provider.GOOGLE: "gemini-3.5-flash-lite",  # D-032, same live verification as above
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

    `provider` (D-04X, the fallback chain): which provider actually served this call, not
    which one was configured. Before the fallback chain existed, `PROVIDER` was a fixed
    module-level constant for the whole process, so "which provider" was implicit and
    never needed recording per call. Once one call can legitimately be served by a
    DIFFERENT provider than the one `LLM_PROVIDER` names -- a free Gemini key's model
    overloaded, so a fallback model or provider answered instead -- "which provider and
    model actually produced this text" becomes a real auditability fact belonging in
    every trace a verdict is built from, not just an implementation detail.
    """

    ts: float
    provider: str
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

    raw, first = _complete(prompt, 0.0, resolved_model, use_cache, model_tier=model_tier)
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

    raw2, second = _complete(prompt + _CORRECTIVE_SUFFIX, 0.0, resolved_model, use_cache,
                             model_tier=model_tier)
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
    text, record = _complete(prompt, temperature, resolved_model, use_cache,
                             model_tier=model_tier)
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


def _complete(prompt: str, temperature: float, model: str, use_cache: bool, *,
              model_tier: str = "default") -> tuple[str, CallRecord]:
    """The single place a provider SDK is called. Invariant 3's actual choke point.

    `judge` and `generate` are the two doors agents see; this is the one room behind both, so
    the provider branch, the cache lookup and the cost log each exist exactly once. Knows
    nothing about schemas or retries -- those are `judge`'s, one layer up -- so every
    `CallRecord` it builds carries `attempt=1` and `schema_valid=True` (D-022's default of
    "nothing invalidated it yet"); `judge` overrides both fields with `model_copy` once it
    knows better.

    D-04X -- the fallback chain, two layers, walked by `_call_with_fallback` below. This
    function's own job stays cache-then-call for a SINGLE (provider, model): the chain
    logic is a separate, testable function, not folded into this one's control flow.
    """
    provider, resolved_model, text, tokens_in, tokens_out, elapsed, cache_hit = (
        _call_with_fallback(prompt, temperature, PROVIDER, model, model_tier, use_cache)
    )
    record = CallRecord(
        ts=time.time() - elapsed, provider=provider.value, model=resolved_model,
        temperature=temperature, tokens_in=tokens_in, tokens_out=tokens_out,
        elapsed_s=elapsed, cache_hit=cache_hit, attempt=1, schema_valid=True, flagged=False,
    )
    return text, record


# ---- Fallback chain (D-04X) ---------------------------------------------------------------
#
# Built for the free Google AI Studio key's actual failure mode: a free key does not hit
# billing exhaustion (there is no prepayment to deplete), it hits per-model overload --
# "model not available, high traffic" -- which this project has now seen twice, months
# apart, on two different keys. That is a PER-MODEL problem, not a per-account one, so the
# fix that matches it is trying ANOTHER MODEL under the SAME key first (layer 1), not
# jumping providers first. Cross-provider fallback (layer 2) stays as the safety net for
# when a whole provider is down, not the primary response to one overloaded model.
_MAX_MODEL_HOPS_PER_PROVIDER = 2   # up to 2 EXTRA models tried after the first, per provider
_MAX_PROVIDER_HOPS = 2             # up to 2 EXTRA providers tried after the primary

# Providers this fallback chain considers -- deliberately NOT Provider.OPENAI or
# Provider.QWEN_LOCAL, which are structural stubs (`_stub_provider`) with no key to check
# in the first place; falling back TO a stub would just trade one exception for another.
_FALLBACK_KEY_ENV_VARS: dict[Provider, str] = {
    Provider.ANTHROPIC: "ANTHROPIC_API_KEY",
    Provider.NVIDIA: "NVIDIA_API_KEY",
    Provider.GOOGLE: "GOOGLE_API_KEY",
}


def _providers_with_real_keys() -> list[Provider]:
    """Which of the three real providers have a key set RIGHT NOW -- read live from
    `os.environ` every call, never cached or assumed, because the whole point of this
    function existing is that a key can be swapped (a depleted account replaced with a
    fresh one) without restarting the process that reads `MODEL_TIERS`/`PROVIDER` once at
    import time. `PROVIDER` itself IS still fixed at import (D-023's own reasoning: an
    unservable provider should fail at startup) -- this only affects which providers are
    ELIGIBLE as fallback candidates, not which one primary judging calls use by default.
    """
    return [p for p, env_var in _FALLBACK_KEY_ENV_VARS.items() if os.environ.get(env_var)]


def _tier_for_model(provider: Provider, model: str) -> str | None:
    """Which MODEL_TIERS tier `model` came from, for `provider` -- so a fallback to a
    DIFFERENT provider can ask for the same tier's model there, rather than an arbitrary
    one. Returns None if `model` was passed explicitly (judge(model=...)) and does not
    match any tier's id -- in that case cross-provider fallback has no principled
    equivalent model to reach for and falls back to that provider's own 'default' tier.
    """
    for tier, models in MODEL_TIERS.items():
        if models.get(provider) == model:
            return tier
    return None


def _model_chain(provider: Provider, primary_model: str | None, tier: str) -> list[str]:
    """Every real model id worth trying for `provider`, primary first (if this provider
    IS the one `primary_model` was resolved for), then every other tier's id for the SAME
    provider, in a fixed order, deduplicated. `"TODO(verify)"` placeholders (D-024/D-031 --
    ids never confirmed against a live catalog) are filtered out unconditionally: this
    project does not call a model id it has not verified exists, fallback or not.

    Capped at `1 + _MAX_MODEL_HOPS_PER_PROVIDER` -- today that means Google's real chain is
    exactly `["gemini-3.7-flash", "gemini-3.5-flash-lite"]`, the only two ids D-032 actually
    verified live; a third variant is not invented here to hit a round number.
    """
    chain: list[str] = []
    if primary_model:
        chain.append(primary_model)
    for tier_name in ("default", "cheap"):
        candidate = MODEL_TIERS.get(tier_name, {}).get(provider)
        if candidate and candidate != "TODO(verify)" and candidate not in chain:
            chain.append(candidate)
    return chain[:1 + _MAX_MODEL_HOPS_PER_PROVIDER]


def _classify_transport_error(exc: Exception) -> str:
    """`"quota_billing"` | `"transient"` | `"unknown"` -- the distinction that makes this
    a real fallback chain rather than "retry on any exception" (which the task that
    created this function explicitly named as the bug to avoid: retrying a billing
    failure against the SAME account forever accomplishes nothing but burning time).

    No provider SDK is imported here -- classification works off `getattr` and the
    exception's own string form, which is what lets one function serve every provider
    without this module importing three SDKs just to catch their specific error types.

    `quota_billing`: an account-level exhaustion. Retrying a DIFFERENT MODEL under the
    same key cannot help (the constraint is on the account, not the model) -- skip layer 1
    entirely and go straight to layer 2. Detected by a 429-shaped status PLUS a message
    naming credits/billing/quota explicitly (Google's real 429 RESOURCE_EXHAUSTED for a
    depleted prepayment key says "prepayment credits are depleted" -- confirmed live, this
    session's first Beat 6 attempt, not guessed at).

    `transient`: a per-model overload or a bare rate limit -- worth retrying, first against
    another model on the same key (layer 1, the free-tier failure mode this was built for:
    "model not available, high traffic"), then against another provider (layer 2) if every
    model on this provider is also down. Detected by a 503-shaped status, or by overload/
    availability/rate-limit language WITHOUT the billing keywords above.

    `unknown`: neither pattern matched. Not retried within the same provider (a request
    this module cannot explain failing is not one it should silently resend), but still
    eligible for cross-provider fallback -- a different provider's SDK, account and network
    path is unrelated to whatever this unexplained failure was.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    text = str(exc).lower()

    billing_words = ("credit", "billing", "prepayment", "insufficient")
    if status == 429 and any(w in text for w in billing_words):
        return "quota_billing"
    if "quota" in text and any(w in text for w in billing_words):
        return "quota_billing"

    transient_words = ("overloaded", "unavailable", "high traffic", "rate limit",
                       "try again", "temporarily")
    if status == 503 or status == 429 or any(w in text for w in transient_words):
        return "transient"

    return "unknown"


def _call_with_fallback(
    prompt: str, temperature: float, primary_provider: Provider, primary_model: str,
    model_tier: str, use_cache: bool,
) -> tuple[Provider, str, str, int, int, float, bool]:
    """Walk the two-layer chain and return `(provider, model, text, tokens_in, tokens_out,
    elapsed_s, cache_hit)` for whichever (provider, model) actually served the call.

    Layer 1 (primary): every model in `primary_provider`'s own chain, in order --
    matches today's actual failure mode, a free key's per-model overload. Skipped
    entirely for a `quota_billing` classification (retrying a different model under an
    exhausted ACCOUNT cannot help) but walked fully for `transient`.

    Layer 2 (secondary safety net): other providers with a real key set (checked live,
    `_providers_with_real_keys`), each walking ITS OWN model chain the same way. Reached
    when layer 1 is exhausted (every model tried, or skipped for `quota_billing`) --
    never before. If no other provider has a key, this degrades to "nothing left to try"
    and the loop simply ends -- logged, not a crash (the caller's own exception, listing
    every real attempt, is the honest failure mode).

    Both caps (`_MAX_MODEL_HOPS_PER_PROVIDER`, `_MAX_PROVIDER_HOPS`) are enforced by
    `_model_chain`/the provider list slice below -- there is no unbounded loop here.
    """
    tier = _tier_for_model(primary_provider, primary_model) or model_tier

    other_providers = [p for p in _providers_with_real_keys() if p != primary_provider]
    providers_to_try = [primary_provider, *other_providers[:_MAX_PROVIDER_HOPS]]

    attempts: list[str] = []
    for provider in providers_to_try:
        model_source = primary_model if provider == primary_provider else None
        models = _model_chain(provider, model_source, tier)
        if not models:
            attempts.append(f"{provider.value}: no verified model id for tier {tier!r}")
            continue

        for model in models:
            cache_key = _cache_key(prompt, provider, model, temperature)
            if use_cache and cache_key in CACHE:
                # No print here, deliberately -- a cache hit is the ordinary, silent case
                # everywhere else in this file (the original _complete never announced one
                # either); only what's NEW and worth a human's attention prints: a
                # fallback actually being used, a failed attempt, or no fallback existing.
                return provider, model, CACHE[cache_key], 0, 0, 0.0, True

            t0 = time.time()
            try:
                handler = _PROVIDER_HANDLERS[provider]
                text, tokens_in, tokens_out = handler(prompt, temperature, model)
            except (NotImplementedError, ValueError, TypeError):
                # NEVER classified/retried, on purpose -- these are not transport failures.
                # NotImplementedError is a structural STUB (_stub_provider): every model
                # under that provider is equally unimplemented, so trying another one
                # (or silently jumping to a different provider the caller did not ask
                # for) would hide a real "this isn't built yet" signal behind a fallback
                # that appears to work. ValueError/TypeError are CALLER-side mistakes --
                # D-025's temperature-rejection ValueError is the concrete case this
                # guards: the caller asked for something a model cannot honour, and
                # silently retrying against a DIFFERENT model would substitute an answer
                # the caller never agreed to, the exact failure D-025 itself was written
                # to prevent one field over (temperature). Propagates immediately,
                # unwrapped -- the original exception type and message survive.
                raise
            except Exception as exc:  # noqa: BLE001 -- classified immediately, not swallowed
                elapsed = time.time() - t0
                classification = _classify_transport_error(exc)
                attempts.append(
                    f"{provider.value}/{model}: {classification} -- "
                    f"{type(exc).__name__}: {exc}"
                )
                print(f"llm: {provider.value}/{model} failed ({classification}) "
                     f"after {elapsed:.1f}s -- {type(exc).__name__}")
                if classification == "quota_billing":
                    break   # this provider's whole account is exhausted -- stop its chain
                continue    # transient or unknown -- try the next model in this chain

            elapsed = time.time() - t0
            if provider != primary_provider or model != primary_model:
                print(f"llm: fallback served the call -- provider={provider.value} "
                     f"model={model} (primary was {primary_provider.value}/{primary_model})")
            if use_cache:
                CACHE[cache_key] = text
            return provider, model, text, tokens_in, tokens_out, elapsed, False

    if not other_providers:
        print("llm: no fallback provider configured "
             f"(checked {', '.join(v for v in _FALLBACK_KEY_ENV_VARS.values())})")

    raise RuntimeError(
        "every provider/model in the fallback chain failed. Attempts, in order:\n  "
        + "\n  ".join(attempts) if attempts else
        "no provider/model was even attempted -- this should not happen"
    )


def _cache_key(prompt: str, provider: Provider, model: str, temperature: float) -> str:
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

    `provider` joins the key as of D-04X (the fallback chain): before it, `PROVIDER` was
    fixed for the whole process, so it was implicitly constant and adding it to the key
    would have changed nothing. Once a fallback chain can genuinely serve one call from
    Google and a later, identical-looking call from Anthropic, the two providers' answers
    must never collide under one cache entry -- and the KEYING scheme this function uses is
    per-(provider, model) by construction (`_call_with_fallback` looks the cache up once
    per candidate in its chain, not once for the whole call), which is also why a fallback
    response is never cached under the PRIMARY model's key: caching it there would make a
    future request for the primary model silently return an answer a different model gave
    once, during an outage, rather than asking the primary model fresh once it recovers.
    """
    return hashlib.sha256(
        f"{provider.value}:{model}:{temperature}:{prompt}".encode()
    ).hexdigest()


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


def _call_nvidia(prompt: str, temperature: float, model: str) -> tuple[str, int, int]:
    """NVIDIA's hosted inference endpoint (D-031) -- OpenAI-compatible, so this reuses the
    `openai` SDK rather than hand-rolling a raw HTTP client. `import openai` is local,
    matching `_call_anthropic`'s own pattern -- no other module in this repo needs the SDK
    installed, only this function.

    Keyed by `NVIDIA_API_KEY`, deliberately not `OPENAI_API_KEY`: this is NVIDIA's endpoint,
    not an OpenAI account, and the two must never be silently interchangeable.

    Unlike `_call_anthropic` (D-025), temperature is always sent explicitly. No documented
    restriction on NVIDIA's endpoint rejects an explicit value the way Claude 4.7+ models
    do, so there is no `_REJECTS_NONDEFAULT_TEMPERATURE`-style branch here. If that turns out
    to be wrong, the fix is the same one D-025 made for Anthropic, applied here.
    """
    import openai

    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY is not set. LLM_PROVIDER=nvidia requires it -- see .env.example."
        )

    client = openai.OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.choices[0].message.content
    return text, response.usage.prompt_tokens, response.usage.completion_tokens


def _call_google(prompt: str, temperature: float, model: str) -> tuple[str, int, int]:
    """Google AI Studio / Gemini (D-032, supersedes D-023). `import google.genai` is local,
    matching `_call_anthropic`'s and `_call_nvidia`'s own pattern -- no other module in this
    repo needs the SDK installed.

    Uses `client.models.generate_content`, not `client.interactions.create` -- both exist on
    the installed SDK (`google-genai` 2.18.1, checked 2026-08-19), but `generate_content`'s
    `config` parameter is a typed `GenerateContentConfig` with a real `temperature: float`
    field, confirmed by introspecting the actual installed package rather than trusted from
    documentation prose; `interactions.create`'s real signature is
    `(*, request=None, ..., **body: Any)`, an opaque passthrough with no typed parameter
    surface, and two fetched documentation pages both failed to fully specify its body
    schema even though one names it the currently-recommended API. Verifiable beats
    currently-recommended, for a field (temperature) invariant 4 depends on.

    Keyed by GOOGLE_API_KEY, passed explicitly to `genai.Client(api_key=...)` rather than the
    SDK's own default env var lookup (`GEMINI_API_KEY`) -- same reasoning as NVIDIA_API_KEY
    vs OPENAI_API_KEY: an explicit named key, never an ambient default.

    No temperature-rejection carve-out, matching NVIDIA -- no documented restriction was
    found for Gemini models during this session's verification pass.
    """
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY is not set. LLM_PROVIDER=google requires it -- see .env.example."
        )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=temperature),
    )
    usage = response.usage_metadata
    return response.text, usage.prompt_token_count, usage.candidates_token_count


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
    Provider.NVIDIA: _call_nvidia,
    Provider.GOOGLE: _call_google,
}
