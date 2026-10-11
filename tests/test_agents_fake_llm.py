"""Stage 2 -- the fake LLM harness (agents/fake_llm.py) tests itself.

These run the REAL `system.llm.judge` on top of scripted provider replies, so they also pin the
gateway behaviours the agents rely on (fence stripping, one corrective retry, the fallback chain,
the timeout). No network, no SDK, no database.
"""
from __future__ import annotations

import time

import pytest
from pydantic import BaseModel

from agents import fake_llm as fl
from system import llm


class Reply(BaseModel):
    answer: str
    n: int


GOOD = {"answer": "ok", "n": 1}


def test_valid_json_one_call():
    fake = fl.FakeLLM([fl.valid_json(GOOD)])
    obj, record = fake.judge("p", Reply)
    assert obj == Reply(answer="ok", n=1)
    assert (fake.call_count, fake.judge_count) == (1, 1)
    assert record.attempt == 1 and record.schema_valid
    fake.assert_exhausted()


def test_pydantic_model_can_be_scripted():
    fake = fl.FakeLLM([fl.valid_json(Reply(answer="m", n=2))])
    assert fake.judge("p", Reply)[0].n == 2


def test_fenced_json_is_stripped_and_costs_one_call():
    fake = fl.FakeLLM([fl.fenced_json(GOOD)])
    obj, _ = fake.judge("p", Reply)
    assert obj.answer == "ok"
    assert fake.call_count == 1


def test_untagged_fence_is_stripped_too():
    fake = fl.FakeLLM([fl.fenced_json(GOOD, tag="")])
    assert fake.judge("p", Reply)[0].n == 1


def test_invalid_then_valid_uses_the_one_corrective_retry():
    fake = fl.FakeLLM([fl.invalid_json(), fl.valid_json(GOOD)])
    obj, record = fake.judge("p", Reply)
    assert obj.n == 1
    assert (fake.call_count, fake.judge_count) == (2, 1)
    assert record.attempt == 2
    assert fake.prompts[1].startswith("p") and "did not parse" in fake.prompts[1]
    assert [r.schema_valid for r in fake.cost_log] == [False, True]


def test_invalid_twice_raises_and_never_defaults():
    fake = fl.FakeLLM([fl.invalid_json("nope one"), fl.invalid_json("nope two")])
    with pytest.raises(llm.SchemaValidationError) as err:
        fake.judge("p", Reply)
    assert fake.call_count == 2
    assert err.value.raw_prefixes == ["nope one", "nope two"]
    assert fake.cost_log[-1].flagged is True


def test_schema_mismatch_counts_as_invalid():
    fake = fl.FakeLLM([fl.valid_json({"answer": "x"}), fl.valid_json({"wrong": 1})])
    with pytest.raises(llm.SchemaValidationError):
        fake.judge("p", Reply)


def test_unclosed_fence_is_not_stripped():
    fake = fl.FakeLLM([fl.truncated_fence(GOOD), fl.truncated_fence(GOOD)])
    with pytest.raises(llm.SchemaValidationError):
        fake.judge("p", Reply)


def test_callable_reply_sees_the_prompt():
    fake = fl.FakeLLM([fl.text(lambda prompt: f'{{"answer": "{prompt.upper()}", "n": 3}}')])
    assert fake.judge("abc", Reply)[0].answer == "ABC"


def test_script_exhausted_fails_loudly_and_is_not_wrapped():
    fake = fl.FakeLLM([fl.valid_json(GOOD)])
    fake.judge("p", Reply)
    with pytest.raises(fl.ScriptExhausted):
        fake.judge("another prompt", Reply)


def test_default_responder_serves_unscripted_calls():
    fake = fl.FakeLLM(default=lambda prompt: '{"answer": "d", "n": 0}')
    assert fake.judge("a", Reply)[0].answer == "d"
    assert fake.judge("b", Reply)[0].answer == "d"
    assert fake.call_count == 2


def test_transient_error_falls_through_to_the_next_model():
    fake = fl.FakeLLM([fl.provider_error(), fl.valid_json(GOOD)])
    _, record = fake.judge("p", Reply)
    assert fake.call_count == 2
    assert record.model == llm.MODEL_TIERS["cheap"][llm.Provider.ANTHROPIC]
    assert fake.calls[0].model == llm.MODEL_TIERS["default"][llm.Provider.ANTHROPIC]


def test_provider_down_raises_the_chain_error():
    fake = fl.FakeLLM([fl.provider_error(sticky=True)])
    with pytest.raises(RuntimeError, match="fallback chain failed"):
        fake.judge("p", Reply)
    assert fake.call_count == 2           # both models of the anthropic chain, nothing else


def test_timeout_exception_is_a_transient_failure():
    fake = fl.FakeLLM([fl.timeout(sticky=True)])
    with pytest.raises(RuntimeError, match="fallback chain failed"):
        fake.judge("p", Reply)


def test_real_thread_timeout_path_fires():
    fake = fl.FakeLLM([fl.slow(0.6), fl.valid_json(GOOD)])
    start = time.time()
    obj, record = fake.judge("p", Reply)
    assert obj.n == 1
    assert time.time() - start < 0.55                 # did not wait for the slow call
    assert record.model == llm.MODEL_TIERS["cheap"][llm.Provider.ANTHROPIC]


def test_cache_hit_costs_no_provider_call():
    fake = fl.FakeLLM([fl.valid_json(GOOD)])
    fake.judge("same", Reply)
    _, record = fake.judge("same", Reply)
    assert fake.call_count == 1 and fake.judge_count == 2
    assert record.cache_hit is True


def test_use_cache_false_calls_again():
    fake = fl.FakeLLM([fl.valid_json(GOOD), fl.valid_json(GOOD)])
    fake.judge("same", Reply, use_cache=False)
    fake.judge("same", Reply, use_cache=False)
    assert fake.call_count == 2


def test_every_call_is_temperature_zero():
    fake = fl.FakeLLM([fl.invalid_json(), fl.valid_json(GOOD)])
    fake.judge("p", Reply)
    assert {c.temperature for c in fake.calls} == {0.0}


def test_generate_is_forbidden():
    with pytest.raises(fl.GenerateForbidden):
        fl.FakeLLM().generate("p", temperature=0.7)


def test_installed_replaces_every_handler_and_restores_state(monkeypatch):
    before = (dict(llm._PROVIDER_HANDLERS), llm.CACHE, llm.COST_LOG, llm.PROVIDER,
              llm._providers_with_real_keys, llm._PROVIDER_CALL_TIMEOUT_S)
    fake = fl.FakeLLM()
    with fake.installed():
        for provider in llm.Provider:
            assert llm._PROVIDER_HANDLERS[provider] is not before[0][provider]
        assert llm._providers_with_real_keys() == []
        assert llm.PROVIDER is llm.Provider.ANTHROPIC
        with fake.installed():                         # re-entrant
            pass
        assert llm.CACHE is fake._cache                 # inner exit did not restore early
    after = (dict(llm._PROVIDER_HANDLERS), llm.CACHE, llm.COST_LOG, llm.PROVIDER,
             llm._providers_with_real_keys, llm._PROVIDER_CALL_TIMEOUT_S)
    assert after == before


def test_state_is_restored_even_when_the_call_raises():
    before = dict(llm._PROVIDER_HANDLERS)
    fake = fl.FakeLLM([fl.provider_error(sticky=True)])
    with pytest.raises(RuntimeError):
        fake.judge("p", Reply)
    assert before == llm._PROVIDER_HANDLERS


def test_api_keys_in_the_environment_cannot_cause_a_real_fallback(monkeypatch):
    """The reason the harness replaces all handlers: with keys set, the gateway would walk to
    other providers after a failure. Here every provider is the fake, and only anthropic's chain
    is tried because key discovery is disabled."""
    for var in ("ANTHROPIC_API_KEY", "NVIDIA_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.setenv(var, "sk-not-real")
    fake = fl.FakeLLM([fl.provider_error(sticky=True)])
    with pytest.raises(RuntimeError):
        fake.judge("p", Reply)
    assert {c.provider for c in fake.calls} == {"anthropic"}


def test_no_real_handler_runs_while_installed(monkeypatch):
    """If a real handler were reachable, this sentinel would trip."""
    def boom(*a, **k):
        raise AssertionError("a real provider handler was called")
    monkeypatch.setattr(llm, "_call_anthropic", boom)
    monkeypatch.setattr(llm, "_call_google", boom)
    monkeypatch.setattr(llm, "_call_nvidia", boom)
    fake = fl.FakeLLM([fl.valid_json(GOOD)])
    assert fake.judge("p", Reply)[0].n == 1


def test_installed_context_lets_direct_gateway_callers_use_the_fake():
    fake = fl.FakeLLM([fl.valid_json(GOOD)])
    with fake.installed():
        obj, _ = llm.judge("p", Reply)           # the path the Code Agent / benchmark use
    assert obj.n == 1 and fake.call_count == 1
