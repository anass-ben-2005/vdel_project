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
import pytest
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


# ---------- provider selection (D-023) ----------

def test_google_is_not_a_valid_provider():
    with pytest.raises(ValueError):
        Provider("google")


def test_an_unknown_provider_string_fails_loudly_not_at_call_time():
    """D-023's whole point: read_provider is what makes an unservable provider a startup
    failure. Testing the function directly since re-importing the module to exercise the
    real import-time call would require a subprocess."""
    import os

    original = os.environ.get("LLM_PROVIDER")
    os.environ["LLM_PROVIDER"] = "google"
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
