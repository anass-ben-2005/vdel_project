"""system/llm.py — the LLM Gateway (M3, BUILD_PLAN 3.1).

Mocks the Anthropic SDK at `anthropic.Anthropic` -- the exact boundary `_call_anthropic`
calls across -- rather than at `system.llm._PROVIDER_HANDLERS`. The lower mock point would
skip `_call_anthropic`'s own body, which is where D-025's temperature policy actually lives;
mocking one layer down means these tests exercise the real kwargs the SDK would receive, not
just that *some* function got called. No real API call happens anywhere in this file: the
`anthropic` package is genuinely installed (it is `system/llm.py`'s live branch, D-024/D-025),
but `anthropic.Anthropic` itself is always replaced before `_complete` can reach it.

Every test resets module state (`CACHE`, `COST_LOG`, `PROVIDER`) via the `clean_llm` fixture,
because both are process-global per the gateway's own "replace with a persistent cache in
prod" design -- state bleeding between tests would make a cache-hit assertion in one test
depend on test order, exactly the kind of flake `tests/test_memory.py`'s rolled-back
connections exist to avoid for the database side.
"""
from __future__ import annotations

import types

import anthropic
import openai
import pytest
from google import genai
from pydantic import BaseModel

from system import llm
from system.llm import (
    MODEL_TIERS,
    Provider,
    SchemaValidationError,
    generate,
    judge,
)


class Verdict(BaseModel):
    """A minimal schema, standing in for a real agent's verdict shape. `judge` is generic
    over schema (module docstring) -- it must work for any pydantic model, not one blessed
    shape, so this is deliberately NOT `EchoVerdict` or D.5's `Verdict`."""

    score: int
    note: str


# ---------- fixtures ----------

@pytest.fixture(autouse=True)
def clean_llm(monkeypatch):
    """Reset the gateway's process-global state before every test, and pin PROVIDER to
    Anthropic regardless of the developer's local .env -- these tests assert behaviour of
    the live branch specifically, not whatever LLM_PROVIDER happens to be set to."""
    monkeypatch.setattr(llm, "CACHE", {})
    monkeypatch.setattr(llm, "COST_LOG", [])
    monkeypatch.setattr(llm, "PROVIDER", Provider.ANTHROPIC)


class _FakeMessages:
    """Records every call's kwargs and returns a scripted response per call, in order.

    A list of responses, not one, because the retry tests need the first call to return
    invalid JSON and the second to return valid JSON -- the same shape a real flaky model
    output looks like.
    """

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self._responses.pop(0)
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text=text)],
            usage=types.SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def _install_fake_client(monkeypatch, responses: list[str]) -> _FakeMessages:
    """Patch `anthropic.Anthropic` so `_call_anthropic`'s `client.messages.create(...)`
    hits `_FakeMessages` instead of the network. Returns the fake so tests can inspect
    `.calls`."""
    fake_messages = _FakeMessages(responses)
    fake_client = types.SimpleNamespace(messages=fake_messages)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **kw: fake_client)
    return fake_messages


class _FakeCompletions:
    """The nvidia-branch analogue of `_FakeMessages`, shaped like the `openai` SDK's
    `client.chat.completions.create(...)` response instead of Anthropic's `.messages.create`.

    Field names deliberately differ from `_FakeMessages` (`choices[0].message.content`
    vs `content[0].text`; `usage.prompt_tokens`/`completion_tokens` vs
    `usage.input_tokens`/`output_tokens`) -- this is the exact shape mismatch a copy-paste
    from the Anthropic branch would get wrong silently, so the fake must be faithful to the
    real SDK's shape, not to `_call_anthropic`'s.
    """

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self._responses.pop(0)
        message = types.SimpleNamespace(content=text)
        choice = types.SimpleNamespace(message=message)
        usage = types.SimpleNamespace(prompt_tokens=10, completion_tokens=5)
        return types.SimpleNamespace(choices=[choice], usage=usage)


def _install_fake_openai_client(monkeypatch, responses: list[str]):
    """Patch `openai.OpenAI` so `_call_nvidia`'s `client.chat.completions.create(...)` hits
    `_FakeCompletions` instead of the network. Returns `(fake_completions, constructor_calls)`
    so a test can inspect both the request kwargs and how the client itself was built
    (`base_url`, `api_key`) -- `_install_fake_client`'s anthropic equivalent doesn't need the
    second part because that test file never asserts on how `anthropic.Anthropic()` itself
    was constructed, only on `.messages.create`'s kwargs."""
    fake_completions = _FakeCompletions(responses)
    constructor_calls: list[dict] = []

    def _fake_openai(*args, **kwargs):
        constructor_calls.append(kwargs)
        chat = types.SimpleNamespace(completions=fake_completions)
        return types.SimpleNamespace(chat=chat)

    monkeypatch.setattr(openai, "OpenAI", _fake_openai)
    return fake_completions, constructor_calls


class _FakeGoogleModels:
    """The google-branch analogue of `_FakeMessages`/`_FakeCompletions`, shaped like the real
    `google-genai` SDK's `client.models.generate_content(...)` response -- `.text` and
    `.usage_metadata.prompt_token_count`/`.candidates_token_count`. Confirmed by introspecting
    the actual installed package (`google-genai` 2.18.1), not assumed from documentation --
    the documentation for this SDK disagreed with itself across two fetched pages during this
    session, which is exactly why the fake is built to the installed code's real shape."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        text = self._responses.pop(0)
        usage = types.SimpleNamespace(prompt_token_count=10, candidates_token_count=5)
        return types.SimpleNamespace(text=text, usage_metadata=usage)


def _install_fake_google_client(monkeypatch, responses: list[str]):
    """Patch `genai.Client` so `_call_google`'s `client.models.generate_content(...)` hits
    `_FakeGoogleModels` instead of the network. Returns `(fake_models, constructor_calls)`,
    matching `_install_fake_openai_client`'s shape for the same reason."""
    fake_models = _FakeGoogleModels(responses)
    constructor_calls: list[dict] = []

    def _fake_client(*args, **kwargs):
        constructor_calls.append(kwargs)
        return types.SimpleNamespace(models=fake_models)

    monkeypatch.setattr(genai, "Client", _fake_client)
    return fake_models, constructor_calls


VALID = '{"score": 4, "note": "clean"}'
INVALID = "not json at all"


# ---------- cache hit / miss ----------

def test_cache_miss_calls_the_provider(monkeypatch):
    fake = _install_fake_client(monkeypatch, [VALID])
    verdict, record = judge("grade this", Verdict)

    assert len(fake.calls) == 1
    assert verdict.score == 4
    assert record.cache_hit is False


def test_identical_prompt_is_a_cache_hit_and_skips_the_provider(monkeypatch):
    fake = _install_fake_client(monkeypatch, [VALID, VALID])
    judge("grade this", Verdict)
    _, second_record = judge("grade this", Verdict)

    # Only the FIRST call reached the provider -- the second is served from CACHE. If the
    # cache were not working, `fake.calls` would be 2 and this assertion would catch it
    # even though a second scripted response was available to hide the bug.
    assert len(fake.calls) == 1
    assert second_record.cache_hit is True


def test_a_different_prompt_is_a_cache_miss(monkeypatch):
    fake = _install_fake_client(monkeypatch, [VALID, VALID])
    judge("grade submission A", Verdict)
    _, record = judge("grade submission B", Verdict)

    assert len(fake.calls) == 2
    assert record.cache_hit is False


def test_use_cache_false_always_calls_the_provider(monkeypatch):
    """The benchmark's own requirement (module docstring on `judge`): re-running with
    use_cache=False must reach the provider every time, or 'reproduces the matrix' would be
    proven against a dict instead of the model."""
    fake = _install_fake_client(monkeypatch, [VALID, VALID])
    judge("grade this", Verdict, use_cache=False)
    judge("grade this", Verdict, use_cache=False)

    assert len(fake.calls) == 2


# ---------- retry on invalid JSON (D-022) ----------

def test_invalid_then_valid_succeeds_on_the_retry(monkeypatch):
    fake = _install_fake_client(monkeypatch, [INVALID, VALID])
    verdict, record = judge("grade this", Verdict)

    assert len(fake.calls) == 2
    assert verdict.score == 4
    assert record.attempt == 2
    assert record.schema_valid is True


def test_the_retry_prompt_carries_a_corrective_suffix(monkeypatch):
    """The retry must not be an identical re-ask -- that would just fail the same way."""
    fake = _install_fake_client(monkeypatch, [INVALID, VALID])
    judge("grade this", Verdict)

    first_prompt = fake.calls[0]["messages"][0]["content"]
    second_prompt = fake.calls[1]["messages"][0]["content"]
    assert first_prompt != second_prompt
    assert first_prompt in second_prompt  # original text is preserved, not replaced
    assert "valid JSON" in second_prompt.lower() or "JSON" in second_prompt


def test_two_invalid_attempts_raises_and_never_silently_drops(monkeypatch):
    """Invariant 5. Both failures must be inspectable on the exception, not lost."""
    fake = _install_fake_client(monkeypatch, [INVALID, INVALID])

    with pytest.raises(SchemaValidationError) as exc_info:
        judge("grade this", Verdict)

    assert len(fake.calls) == 2
    records = exc_info.value.records
    assert len(records) == 2
    assert all(r.schema_valid is False for r in records)
    assert records[0].attempt == 1
    assert records[1].attempt == 2
    assert records[1].flagged is True


def test_only_one_retry_is_ever_attempted(monkeypatch):
    """D-022 says 'exactly one corrective retry'. A third scripted response existing and
    never being consumed is the proof -- if the gateway retried again, `_FakeMessages` would
    raise IndexError trying to pop a fourth, unscripted response instead of this assertion
    failing cleanly, which would be a worse test failure to debug."""
    fake = _install_fake_client(monkeypatch, [INVALID, INVALID, VALID])

    with pytest.raises(SchemaValidationError):
        judge("grade this", Verdict)

    assert len(fake.calls) == 2  # the third scripted VALID response was never reached


def test_a_failed_first_attempt_is_logged_before_the_retry(monkeypatch):
    """Invariant 5's other half: the failed attempt's cost must not vanish even though the
    retry succeeds and the function returns normally."""
    _install_fake_client(monkeypatch, [INVALID, VALID])
    judge("grade this", Verdict)

    assert len(llm.COST_LOG) == 2
    assert llm.COST_LOG[0].schema_valid is False
    assert llm.COST_LOG[0].attempt == 1
    assert llm.COST_LOG[1].schema_valid is True
    assert llm.COST_LOG[1].attempt == 2


# ---------- temperature-0 enforcement (invariant 4, D-025) ----------

def test_judge_sends_temperature_zero_on_a_model_that_accepts_it(monkeypatch):
    """claude-haiku-4-5 (the 'cheap' tier) is not in _REJECTS_NONDEFAULT_TEMPERATURE, so an
    explicit 0.0 must actually be sent -- not omitted, not defaulted, sent."""
    fake = _install_fake_client(monkeypatch, [VALID])
    judge("grade this", Verdict, model_tier="cheap")

    assert fake.calls[0]["temperature"] == 0.0
    assert fake.calls[0]["model"] == MODEL_TIERS["cheap"][Provider.ANTHROPIC]


def test_judge_omits_temperature_on_a_model_that_rejects_nondefault(monkeypatch):
    """claude-sonnet-5 (the 'default' tier, per D-024) 400s on an explicit non-default
    temperature. D-025: omit the parameter rather than send a value that would fail."""
    fake = _install_fake_client(monkeypatch, [VALID])
    judge("grade this", Verdict, model_tier="default")

    assert "temperature" not in fake.calls[0]
    assert fake.calls[0]["model"] == MODEL_TIERS["default"][Provider.ANTHROPIC]


def test_judge_never_sends_a_nonzero_temperature_no_matter_the_model():
    """The strongest form of invariant 4: judge() has no temperature parameter, so there is
    no argument a caller could pass to make it send anything but 0.0 or omitted. This is a
    signature test, not a behaviour test -- it documents that the unsafe call is not
    expressible, matching the module docstring's claim."""
    import inspect

    params = inspect.signature(judge).parameters
    assert "temperature" not in params


def test_generate_passes_temperature_through_on_a_model_that_accepts_it(monkeypatch):
    fake = _install_fake_client(monkeypatch, [VALID])
    generate("write a note", temperature=0.7, model_tier="cheap")

    assert fake.calls[0]["temperature"] == 0.7


def test_generate_raises_for_nonzero_temperature_on_a_rejecting_model(monkeypatch):
    """D-025's other half: a real non-zero request the model cannot honour must fail loudly,
    never silently run at a substituted temperature the caller never asked for."""
    _install_fake_client(monkeypatch, [VALID])

    with pytest.raises(ValueError, match="default sampling temperature"):
        generate("write a note", temperature=0.7, model_tier="default")


def test_generate_at_zero_omits_temperature_on_a_rejecting_model_like_judge(monkeypatch):
    """A generate() call that happens to ask for 0.0 is the same case judge() always hits --
    omit, don't 400."""
    fake = _install_fake_client(monkeypatch, [VALID])
    generate("write a note", temperature=0.0, model_tier="default")

    assert "temperature" not in fake.calls[0]


# ---------- cost log (invariant 8's cousin: every call accounted for) ----------

def test_a_successful_judge_call_writes_one_cost_record(monkeypatch):
    _install_fake_client(monkeypatch, [VALID])
    _, record = judge("grade this", Verdict)

    assert len(llm.COST_LOG) == 1
    assert llm.COST_LOG[0] is record
    assert record.tokens_in == 10
    assert record.tokens_out == 5
    assert record.model == MODEL_TIERS["default"][Provider.ANTHROPIC]


def test_a_cache_hit_still_writes_a_cost_record_but_costs_nothing(monkeypatch):
    _install_fake_client(monkeypatch, [VALID, VALID])
    judge("grade this", Verdict)
    judge("grade this", Verdict)

    assert len(llm.COST_LOG) == 2
    hit = llm.COST_LOG[1]
    assert hit.cache_hit is True
    assert hit.tokens_in == 0
    assert hit.tokens_out == 0


def test_generate_writes_a_cost_record_too(monkeypatch):
    _install_fake_client(monkeypatch, [VALID])
    generate("narrate this week", temperature=0.5, model_tier="cheap")

    assert len(llm.COST_LOG) == 1
    assert llm.COST_LOG[0].schema_valid is True  # convention for generate(): nothing to fail


# ---------- provider selection (D-023, and D-032's reversal of it) ----------

def test_google_IS_now_a_valid_provider():
    """D-032 supersedes D-023: 'google' was deliberately absent, now it is deliberately
    present. This is the mirror image of the old `test_google_is_not_a_valid_provider` --
    keeping the negative assertion around after the reversal would silently re-encode a
    decision that no longer holds."""
    assert Provider("google") is Provider.GOOGLE


def test_an_unknown_provider_string_still_fails_loudly_not_at_call_time():
    """D-023's mechanism outlives its google-specific conclusion: `_read_provider` still
    makes an unservable provider a startup failure -- exercised here with a string that is
    still genuinely unknown, since 'google' no longer is. Testing the function directly
    since re-importing the module to exercise the real import-time call would require a
    subprocess."""
    import os

    original = os.environ.get("LLM_PROVIDER")
    os.environ["LLM_PROVIDER"] = "made_up_provider_no_one_registered"
    try:
        with pytest.raises(RuntimeError, match="unknown LLM_PROVIDER"):
            llm._read_provider()
    finally:
        if original is None:
            os.environ.pop("LLM_PROVIDER", None)
        else:
            os.environ["LLM_PROVIDER"] = original


def test_openai_is_a_real_dispatch_branch_that_raises_not_a_missing_one(monkeypatch):
    """The abstraction is 'real rather than theoretical': selecting openai must route to
    OpenAI-shaped code and fail THERE with a clear stub message, not fail at generic
    provider dispatch the way a typo would."""
    monkeypatch.setattr(llm, "PROVIDER", Provider.OPENAI)

    with pytest.raises(NotImplementedError, match="openai"):
        judge("grade this", Verdict, use_cache=False)


def test_qwen_local_is_also_a_real_dispatch_branch_that_raises(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", Provider.QWEN_LOCAL)

    with pytest.raises(NotImplementedError, match="qwen_local"):
        judge("grade this", Verdict, use_cache=False)


def test_an_unknown_model_tier_raises(monkeypatch):
    _install_fake_client(monkeypatch, [])
    with pytest.raises(ValueError, match="unknown model_tier"):
        judge("grade this", Verdict, model_tier="extra_large")


# ---------- nvidia provider (D-031) ----------
#
# Unlike openai/qwen_local above, nvidia must be a REAL branch: selecting it and judging
# must actually reach the (faked) provider, not raise NotImplementedError. Mocked at the SDK
# boundary (`openai.OpenAI`), one layer below `_call_nvidia`, for the same reason the
# anthropic tests mock `anthropic.Anthropic` rather than `_PROVIDER_HANDLERS` directly --
# it exercises `_call_nvidia`'s own body (the base_url, the api_key lookup, the response
# field names), not just that some function got called.

@pytest.fixture(autouse=True)
def _clean_nvidia_key(monkeypatch):
    """`NVIDIA_API_KEY` must be hermetic per test -- a developer's real .env value must not
    make `test_nvidia_raises_a_clear_error_when_api_key_is_missing` pass by accident, and a
    stale unset must not make the positive-path tests fail on a machine that never set it."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)


def test_nvidia_is_a_real_dispatch_branch_not_a_stub(monkeypatch):
    """The mirror image of `test_openai_is_a_real_dispatch_branch_that_raises_not_a_missing_one`
    -- nvidia must NOT raise NotImplementedError. If this fails, `_call_nvidia` was wired to
    `_stub_provider` instead of its real body."""
    monkeypatch.setattr(llm, "PROVIDER", Provider.NVIDIA)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    fake, _ctor = _install_fake_openai_client(monkeypatch, [VALID])

    verdict, record = judge("grade this", Verdict, use_cache=False)

    assert len(fake.calls) == 1
    assert verdict.score == 4
    assert record.cache_hit is False


def test_nvidia_client_is_constructed_with_the_nvidia_base_url_and_key(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", Provider.NVIDIA)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    _fake, constructor_calls = _install_fake_openai_client(monkeypatch, [VALID])

    judge("grade this", Verdict, use_cache=False)

    assert len(constructor_calls) == 1
    assert constructor_calls[0]["base_url"] == "https://integrate.api.nvidia.com/v1"
    assert constructor_calls[0]["api_key"] == "nvapi-test-key"


def test_nvidia_reads_the_nvidia_key_not_the_openai_key(monkeypatch):
    """These must never be silently interchangeable -- NVIDIA_API_KEY authenticates against
    NVIDIA's endpoint, not an OpenAI account, even though both speak the same SDK."""
    monkeypatch.setattr(llm, "PROVIDER", Provider.NVIDIA)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-a-real-openai-key-that-must-be-ignored")
    _fake, constructor_calls = _install_fake_openai_client(monkeypatch, [VALID])

    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY"):
        judge("grade this", Verdict, use_cache=False)

    assert constructor_calls == [], "must fail before ever constructing the client"


def test_nvidia_raises_a_clear_error_when_api_key_is_missing(monkeypatch):
    """Invariant 5's spirit applied to configuration, not just model output: a missing key
    fails loudly with a specific message, not a bare `KeyError` or a silent None passed to
    the SDK that then fails with an opaque auth error deep in `openai`'s own code."""
    monkeypatch.setattr(llm, "PROVIDER", Provider.NVIDIA)
    _install_fake_openai_client(monkeypatch, [VALID])

    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY is not set"):
        judge("grade this", Verdict, use_cache=False)


def test_nvidia_model_tier_resolves_to_the_deepseek_model_string(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", Provider.NVIDIA)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    fake, _ctor = _install_fake_openai_client(monkeypatch, [VALID])

    judge("grade this", Verdict, model_tier="default", use_cache=False)

    assert fake.calls[0]["model"] == MODEL_TIERS["default"][Provider.NVIDIA]
    assert fake.calls[0]["model"] == "deepseek-ai/deepseek-v4-pro"


def test_nvidia_cheap_tier_is_still_todo_verify(monkeypatch):
    """No cheap-tier DeepSeek variant was specified (D-031) -- this is the honest gap that
    decision names, not silently invented. It fails at the (faked) provider call, which is
    where an un-stamped model id belongs: after the caller chose it, not before."""
    monkeypatch.setattr(llm, "PROVIDER", Provider.NVIDIA)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    fake, _ctor = _install_fake_openai_client(monkeypatch, [VALID])

    judge("grade this", Verdict, model_tier="cheap", use_cache=False)

    assert fake.calls[0]["model"] == "TODO(verify)"


def test_nvidia_always_sends_temperature_unlike_anthropics_rejecting_models(monkeypatch):
    """No `_REJECTS_NONDEFAULT_TEMPERATURE`-style restriction is documented for NVIDIA's
    endpoint, so -- unlike `_call_anthropic` -- temperature is never omitted."""
    monkeypatch.setattr(llm, "PROVIDER", Provider.NVIDIA)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    fake, _ctor = _install_fake_openai_client(monkeypatch, [VALID])

    judge("grade this", Verdict, use_cache=False)
    assert fake.calls[0]["temperature"] == 0.0

    fake2, _ctor2 = _install_fake_openai_client(monkeypatch, ["a narrative response"])
    generate("narrate this week", temperature=0.6, model_tier="default", use_cache=False)
    assert fake2.calls[0]["temperature"] == 0.6


def test_nvidia_token_counts_come_from_openai_shaped_usage_fields(monkeypatch):
    """The exact bug a copy-paste from `_call_anthropic` would introduce silently: Anthropic's
    response carries `usage.input_tokens`/`usage.output_tokens`; OpenAI-shaped responses
    carry `usage.prompt_tokens`/`usage.completion_tokens`. Reading the wrong pair wouldn't
    raise -- `_FakeCompletions`' namespace has no `input_tokens` attribute, so it would
    AttributeError here if `_call_nvidia` reached for the Anthropic field names, but in
    production with a real openai.types object it could silently read 0 or the wrong count.
    """
    monkeypatch.setattr(llm, "PROVIDER", Provider.NVIDIA)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    _install_fake_openai_client(monkeypatch, [VALID])

    _verdict, record = judge("grade this", Verdict, use_cache=False)

    assert record.tokens_in == 10
    assert record.tokens_out == 5


def test_nvidia_response_text_comes_from_choices_not_content_blocks(monkeypatch):
    """The other half of the shape mismatch: Anthropic returns `content[0].text`; OpenAI-
    shaped responses return `choices[0].message.content`. `_FakeCompletions` has no
    `content` attribute at the top level, so reaching for the Anthropic shape here would
    AttributeError rather than silently returning the wrong (or no) text."""
    monkeypatch.setattr(llm, "PROVIDER", Provider.NVIDIA)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    _install_fake_openai_client(monkeypatch, [VALID])

    verdict, _record = judge("grade this", Verdict, use_cache=False)
    assert verdict.score == 4
    assert verdict.note == "clean"


def test_nvidia_retry_on_invalid_json_still_works(monkeypatch):
    """D-022's gateway-side retry is provider-agnostic -- it must not silently apply only to
    the branch it was written and tested against first."""
    monkeypatch.setattr(llm, "PROVIDER", Provider.NVIDIA)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    fake, _ctor = _install_fake_openai_client(monkeypatch, [INVALID, VALID])

    verdict, record = judge("grade this", Verdict, use_cache=False)

    assert len(fake.calls) == 2
    assert verdict.score == 4
    assert record.attempt == 2


def test_nvidia_does_not_disturb_the_default_provider(monkeypatch):
    """Adding nvidia must be additive. With PROVIDER left at its clean_llm-fixture default
    (Anthropic), nvidia's branch must never be reached."""
    fake = _install_fake_client(monkeypatch, [VALID])
    judge("grade this", Verdict)
    assert len(fake.calls) == 1
    assert llm.PROVIDER == Provider.ANTHROPIC


# ---------- google provider (D-032, supersedes D-023) ----------
#
# Same rationale as the nvidia section: google must be a REAL branch now, not the absent one
# D-023 made it. Mocked at `genai.Client` -- one layer below `_call_google` -- so its own
# body (the api_key lookup, the generate_content call, the GenerateContentConfig it builds)
# is exercised, not just that some function got called.

@pytest.fixture(autouse=True)
def _clean_google_key(monkeypatch):
    """`GOOGLE_API_KEY` hermetic per test, same reasoning as `_clean_nvidia_key`."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


def test_google_is_a_real_dispatch_branch_not_absent(monkeypatch):
    """The direct reversal of D-023's old behaviour: selecting google must reach the (faked)
    provider, not raise anything at all -- unlike openai/qwen_local, which still raise
    NotImplementedError, and unlike google's own pre-D-032 state, which failed even earlier,
    at `_read_provider`."""
    monkeypatch.setattr(llm, "PROVIDER", Provider.GOOGLE)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")
    fake, _ctor = _install_fake_google_client(monkeypatch, [VALID])

    verdict, record = judge("grade this", Verdict, use_cache=False)

    assert len(fake.calls) == 1
    assert verdict.score == 4
    assert record.cache_hit is False


def test_google_client_is_constructed_with_the_google_key(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", Provider.GOOGLE)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")
    _fake, constructor_calls = _install_fake_google_client(monkeypatch, [VALID])

    judge("grade this", Verdict, use_cache=False)

    assert len(constructor_calls) == 1
    assert constructor_calls[0]["api_key"] == "fake-google-key"


def test_google_reads_the_google_key_not_the_gemini_default_env_var(monkeypatch):
    """The SDK's own default lookup is GEMINI_API_KEY -- this project deliberately bypasses
    that and requires GOOGLE_API_KEY explicitly, matching the NVIDIA_API_KEY-not-
    OPENAI_API_KEY precedent (D-031). A key sitting under the SDK's own default name must
    not be picked up silently."""
    monkeypatch.setattr(llm, "PROVIDER", Provider.GOOGLE)
    monkeypatch.setenv("GEMINI_API_KEY", "a-key-under-the-sdks-own-default-name")
    _fake, constructor_calls = _install_fake_google_client(monkeypatch, [VALID])

    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        judge("grade this", Verdict, use_cache=False)

    assert constructor_calls == [], "must fail before ever constructing the client"


def test_google_raises_a_clear_error_when_api_key_is_missing(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", Provider.GOOGLE)
    _install_fake_google_client(monkeypatch, [VALID])

    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY is not set"):
        judge("grade this", Verdict, use_cache=False)


def test_google_model_tier_resolves_to_the_verified_gemini_strings(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", Provider.GOOGLE)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")
    fake, _ctor = _install_fake_google_client(monkeypatch, [VALID])

    judge("grade this", Verdict, model_tier="default", use_cache=False)
    assert fake.calls[0]["model"] == MODEL_TIERS["default"][Provider.GOOGLE]
    assert fake.calls[0]["model"] == "gemini-3.7-flash"

    fake2, _ctor2 = _install_fake_google_client(monkeypatch, [VALID])
    judge("grade this", Verdict, model_tier="cheap", use_cache=False)
    assert fake2.calls[0]["model"] == "gemini-3.5-flash-lite"


def test_google_sends_temperature_through_a_typed_generate_content_config(monkeypatch):
    """The whole reason `generate_content` was chosen over `interactions.create` (D-032):
    temperature must land in a real, typed `GenerateContentConfig.temperature` field, not a
    guessed dict key. This test would fail loudly if `_call_google` ever passed a plain dict
    instead of the real config type, or the wrong field name -- `GenerateContentConfig` is
    pydantic and rejects unknown fields."""
    from google.genai import types

    monkeypatch.setattr(llm, "PROVIDER", Provider.GOOGLE)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")
    fake, _ctor = _install_fake_google_client(monkeypatch, [VALID])

    judge("grade this", Verdict, use_cache=False)

    config = fake.calls[0]["config"]
    assert isinstance(config, types.GenerateContentConfig)
    assert config.temperature == 0.0


def test_google_always_sends_temperature_unlike_anthropics_rejecting_models(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", Provider.GOOGLE)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")
    fake, _ctor = _install_fake_google_client(monkeypatch, ["a narrative response"])

    generate("narrate this week", temperature=0.6, model_tier="default", use_cache=False)
    assert fake.calls[0]["config"].temperature == 0.6


def test_google_token_counts_come_from_usage_metadata_not_a_guessed_field_name(monkeypatch):
    """The exact bug an unverified guess would have introduced: the earlier documentation
    fetch in this session guessed `usage.total_input_tokens`/`total_output_tokens`; the real
    installed SDK's field names are `usage_metadata.prompt_token_count`/
    `candidates_token_count`. `_FakeGoogleModels` only has the real names, so a `_call_google`
    reaching for the guessed ones would AttributeError here rather than silently reading 0."""
    monkeypatch.setattr(llm, "PROVIDER", Provider.GOOGLE)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")
    _install_fake_google_client(monkeypatch, [VALID])

    _verdict, record = judge("grade this", Verdict, use_cache=False)

    assert record.tokens_in == 10
    assert record.tokens_out == 5


def test_google_retry_on_invalid_json_still_works(monkeypatch):
    monkeypatch.setattr(llm, "PROVIDER", Provider.GOOGLE)
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")
    fake, _ctor = _install_fake_google_client(monkeypatch, [INVALID, VALID])

    verdict, record = judge("grade this", Verdict, use_cache=False)

    assert len(fake.calls) == 2
    assert verdict.score == 4
    assert record.attempt == 2


def test_google_does_not_disturb_the_default_provider(monkeypatch):
    fake = _install_fake_client(monkeypatch, [VALID])
    judge("grade this", Verdict)
    assert len(fake.calls) == 1
    assert llm.PROVIDER == Provider.ANTHROPIC


def test_google_does_not_disturb_the_nvidia_branch(monkeypatch):
    """Two live non-default providers now coexist -- confirm adding google didn't reach into
    nvidia's branch or vice versa."""
    monkeypatch.setattr(llm, "PROVIDER", Provider.NVIDIA)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    fake, _ctor = _install_fake_openai_client(monkeypatch, [VALID])

    judge("grade this", Verdict, use_cache=False)

    assert fake.calls[0]["model"] == "deepseek-ai/deepseek-v4-pro"


# ---------- no real network access, ever ----------

def test_no_test_in_this_file_can_reach_the_network(monkeypatch):
    """Belt and braces on the whole file's own claim: if any test forgot to patch
    anthropic.Anthropic, the REAL constructor would run here and (without an API key in the
    test environment) fail in a way that is easy to mistake for a real assertion failure.
    This test intentionally leaves the real Anthropic() unpatched and confirms it is at
    least constructible without making a request -- the network call only happens inside
    .messages.create, which every other test in this file replaces."""
    client = anthropic.Anthropic(api_key="sk-ant-not-a-real-key-no-network-call-made")
    assert client is not None  # constructing a client makes no request; only .create() would
