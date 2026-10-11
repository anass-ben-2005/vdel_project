"""The OpenAI provider branch of system/llm.py, with NO network and no real key.

The real `openai` SDK runs, but its HTTP client is swapped for an `httpx.MockTransport`, so these
tests exercise the SDK's own request building, response parsing and exception classes (a real
`RateLimitError` for a 429, and so on) one layer below `_call_openai`, exactly where a mistake
would hide. Every socket connect is also forbidden for the duration of each test.

The model ids used here ("test-model-default" / "test-model-cheap") are made up for the tests and
are NOT claims about OpenAI's catalogue; the real `MODEL_TIERS` entries are still TODO(verify).
"""
from __future__ import annotations

import json
import socket
import time

import httpx
import openai
import pytest
from pydantic import BaseModel

from system import llm
from system.llm import Provider, SchemaValidationError, generate, judge

SECRET = "sk-test-SECRET-do-not-print-0123456789"
DEFAULT_ID, CHEAP_ID = "test-model-default", "test-model-cheap"


class Verdict(BaseModel):
    score: int
    note: str


VALID = '{"score": 4, "note": "ok"}'
INVALID = "not json at all"


def completion(text: str | None, prompt_tokens: int = 11, completion_tokens: int = 7) -> dict:
    return {"id": "chatcmpl-test", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "total_tokens": prompt_tokens + completion_tokens}}


def error_body(message: str, code: str | None = None, typ: str = "error") -> dict:
    return {"error": {"message": message, "type": typ, "code": code, "param": None}}


class Server:
    """Scripted HTTP endpoint behind the SDK. One response per request, in order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("more HTTP requests than scripted")
        item = self.responses.pop(0)
        if callable(item):
            return item(request)
        status, body = item
        return httpx.Response(status, json=body)

    @property
    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


def ok(text: str, **kw):
    return (200, completion(text, **kw))


@pytest.fixture(autouse=True)
def hermetic(monkeypatch):
    monkeypatch.setattr(llm, "CACHE", {})
    monkeypatch.setattr(llm, "COST_LOG", [])
    monkeypatch.setattr(llm, "PROVIDER", Provider.OPENAI)
    monkeypatch.setattr(llm, "_OPENAI_REJECTS_TEMPERATURE", set())   # run-time state: no leaks
    for var in ("ANTHROPIC_API_KEY", "NVIDIA_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    monkeypatch.setitem(llm.MODEL_TIERS["default"], Provider.OPENAI, DEFAULT_ID)
    monkeypatch.setitem(llm.MODEL_TIERS["cheap"], Provider.OPENAI, CHEAP_ID)

    def no_connect(*a, **k):
        raise AssertionError("a real network connection was attempted")
    monkeypatch.setattr(socket.socket, "connect", no_connect)


@pytest.fixture
def serve(monkeypatch):
    """serve(*responses) -> Server; routes `openai.OpenAI` through the mock transport."""
    real_openai = openai.OpenAI
    constructed: list[dict] = []

    def install(*responses) -> Server:
        server = Server(*responses)

        def factory(*args, **kwargs):
            constructed.append(dict(kwargs))
            kwargs["http_client"] = httpx.Client(transport=httpx.MockTransport(server))
            return real_openai(*args, **kwargs)
        monkeypatch.setattr(openai, "OpenAI", factory)
        server.constructed = constructed
        return server
    return install


# ---- success and the request shape ---------------------------------------------------------

def test_success_returns_the_validated_object_and_the_record(serve):
    server = serve(ok(VALID))
    verdict, record = judge("grade this", Verdict, use_cache=False)
    assert verdict == Verdict(score=4, note="ok")
    assert (record.provider, record.model) == ("openai", DEFAULT_ID)
    assert record.temperature == 0.0 and record.attempt == 1 and record.schema_valid
    assert len(server.requests) == 1


def test_request_shape_is_plain_chat_completions_with_no_native_json_mode(serve):
    server = serve(ok(VALID))
    judge("grade this", Verdict, use_cache=False)
    request, body = server.requests[0], server.bodies[0]
    assert request.url.path.endswith("/chat/completions")
    assert request.headers["authorization"] == f"Bearer {SECRET}"
    assert body["model"] == DEFAULT_ID
    assert body["messages"] == [{"role": "user", "content": "grade this"}]
    assert body["temperature"] == 0.0                       # judge() asks for 0.0
    assert body["max_completion_tokens"] == llm._MAX_TOKENS and "max_tokens" not in body
    for native in ("response_format", "tools", "functions", "tool_choice", "seed", "stream"):
        assert native not in body, f"{native} would make behaviour differ across providers"


def test_sdk_is_built_without_silent_retries(serve):
    server = serve(ok(VALID))
    judge("grade this", Verdict, use_cache=False)
    assert server.constructed[0]["max_retries"] == 0
    assert server.constructed[0]["api_key"] == SECRET


def test_token_counts_come_from_the_usage_fields(serve):
    serve(ok(VALID, prompt_tokens=123, completion_tokens=45))
    _, record = judge("grade this", Verdict, use_cache=False)
    assert (record.tokens_in, record.tokens_out) == (123, 45)


def test_cheap_tier_uses_the_cheap_id(serve):
    server = serve(ok(VALID))
    judge("grade this", Verdict, model_tier="cheap", use_cache=False)
    assert server.bodies[0]["model"] == CHEAP_ID


def test_generate_sends_the_requested_temperature(serve):
    server = serve(ok("a narrative"))
    text, _ = generate("write", temperature=0.7, use_cache=False)
    assert text == "a narrative" and server.bodies[0]["temperature"] == 0.7


def test_null_content_becomes_an_empty_reply_that_fails_validation_not_a_crash(serve):
    serve((200, completion(None)), ok(VALID))
    verdict, record = judge("grade this", Verdict, use_cache=False)
    assert verdict.score == 4 and record.attempt == 2


# ---- the gateway's own parsing: fences and the corrective retry ----------------------------

def test_fenced_reply_is_stripped_by_the_gateway(serve):
    server = serve(ok("```json\n" + VALID + "\n```"))
    verdict, record = judge("grade this", Verdict, use_cache=False)
    assert verdict.score == 4 and record.attempt == 1 and len(server.requests) == 1


def test_invalid_json_recovers_on_the_corrective_retry(serve):
    server = serve(ok(INVALID), ok(VALID))
    verdict, record = judge("grade this", Verdict, use_cache=False)
    assert verdict.score == 4 and record.attempt == 2
    assert len(server.requests) == 2
    assert server.bodies[1]["messages"][0]["content"].startswith("grade this")
    assert "did not parse" in server.bodies[1]["messages"][0]["content"]
    assert [r.schema_valid for r in llm.COST_LOG] == [False, True]


def test_invalid_twice_raises_schema_validation_error(serve):
    serve(ok(INVALID), ok(INVALID))
    with pytest.raises(SchemaValidationError):
        judge("grade this", Verdict, use_cache=False)


# ---- errors: classification and the chain --------------------------------------------------

def test_quota_error_is_classified_quota_billing_and_stops_the_provider(serve, capsys):
    server = serve((429, error_body("You exceeded your current quota, please check your plan "
                                    "and billing details.", "insufficient_quota")))
    with pytest.raises(RuntimeError, match="fallback chain failed") as err:
        judge("grade this", Verdict, use_cache=False)
    assert "quota_billing" in str(err.value) and "RateLimitError" in str(err.value)
    assert len(server.requests) == 1                    # the cheap model is NOT tried
    assert "failed (quota_billing)" in capsys.readouterr().out


def test_classifier_sees_the_real_sdk_exception_types(serve):
    serve((429, error_body("You exceeded your current quota, check billing.")),
          (429, error_body("Rate limit reached, try again later.")),
          (503, error_body("The server is overloaded.")),
          (401, error_body("Incorrect API key provided.", "invalid_api_key")))
    seen = []
    for _ in range(4):
        try:
            openai.OpenAI(api_key=SECRET, max_retries=0).chat.completions.create(
                model="m", messages=[{"role": "user", "content": "x"}])
        except Exception as exc:  # noqa: BLE001
            seen.append(llm._classify_transport_error(exc))
    assert seen == ["quota_billing", "transient", "transient", "unknown"]


def test_transient_error_falls_through_to_the_cheap_model(serve):
    server = serve((503, error_body("The server is overloaded.")), ok(VALID))
    verdict, record = judge("grade this", Verdict, use_cache=False)
    assert verdict.score == 4 and record.model == CHEAP_ID
    assert [b["model"] for b in server.bodies] == [DEFAULT_ID, CHEAP_ID]


def test_rate_limit_without_billing_words_is_transient(serve):
    server = serve((429, error_body("Rate limit reached for requests, try again.")), ok(VALID))
    _, record = judge("grade this", Verdict, use_cache=False)
    assert record.model == CHEAP_ID and len(server.requests) == 2


def test_unauthorized_is_unknown_and_walks_the_models_then_fails(serve):
    server = serve((401, error_body("Incorrect API key provided.", "invalid_api_key")),
                   (401, error_body("Incorrect API key provided.", "invalid_api_key")))
    with pytest.raises(RuntimeError, match="unknown"):
        judge("grade this", Verdict, use_cache=False)
    assert len(server.requests) == 2


def test_timeout_is_enforced_by_the_gateway_ceiling_and_falls_through(serve, monkeypatch):
    monkeypatch.setattr(llm, "_PROVIDER_CALL_TIMEOUT_S", 0.2)

    def slow(request):
        time.sleep(0.6)
        return httpx.Response(200, json=completion(VALID))
    server = serve(slow, ok(VALID))
    start = time.time()
    _, record = judge("grade this", Verdict, use_cache=False)
    assert record.model == CHEAP_ID and time.time() - start < 0.55
    assert len(server.requests) == 2


# ---- the key ------------------------------------------------------------------------------

def test_the_key_is_never_printed_logged_or_put_in_an_error(serve, capsys):
    serve((401, error_body("Incorrect API key provided: sk-test-S****.", "invalid_api_key")),
          (401, error_body("Incorrect API key provided: sk-test-S****.", "invalid_api_key")))
    with pytest.raises(RuntimeError) as err:
        judge("grade this", Verdict, use_cache=False)
    captured = capsys.readouterr()
    assert SECRET not in str(err.value)
    assert SECRET not in captured.out + captured.err
    assert SECRET not in repr(llm.COST_LOG)


def test_missing_key_names_the_variable_and_never_builds_a_client(serve, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    server = serve(ok(VALID))
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        judge("grade this", Verdict, use_cache=False)
    assert server.requests == [] and server.constructed == []


def test_openai_reads_only_its_own_variable(serve, monkeypatch):
    """Called directly: through judge(), the gateway would (correctly) fall back to NVIDIA
    because its key is set, which is not what this test is about."""
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-must-not-be-used")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-must-not-be-used")
    server = serve(ok(VALID))
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm._call_openai("p", 0.0, DEFAULT_ID)
    assert server.constructed == [] and server.requests == []


# ---- model ids: TODO(verify) is refused, temperature rule ---------------------------------

def test_todo_verify_model_is_refused_before_any_request(serve, monkeypatch):
    monkeypatch.setitem(llm.MODEL_TIERS["default"], Provider.OPENAI, "TODO(verify)")
    server = serve(ok(VALID))
    with pytest.raises(ValueError, match=r"TODO\(verify\)"):
        judge("grade this", Verdict, use_cache=False)
    assert server.requests == [] and server.constructed == []


def test_the_shipped_openai_ids_are_written_down():
    """Read from the source text (a module reload would replace the Provider class). The
    author fills the real names in; a TODO(verify) one is refused by the handler (tested
    above), a real one must at least be a non-empty single token."""
    import re
    from pathlib import Path
    source = Path(llm.__file__).read_text(encoding="utf-8")
    ids = re.findall(r'Provider\.OPENAI: "([^"]+)"', source.split("_FALLBACK_KEY_ENV_VARS")[0])
    assert len(ids) == 2 and all(i.strip() and " " not in i for i in ids)


def test_a_model_in_the_rejecting_set_omits_temperature_zero(serve, monkeypatch):
    monkeypatch.setattr(llm, "_OPENAI_REJECTS_TEMPERATURE", frozenset({DEFAULT_ID}))
    server = serve(ok(VALID))
    judge("grade this", Verdict, use_cache=False)
    assert "temperature" not in server.bodies[0]


def test_a_nonzero_temperature_on_a_rejecting_model_raises_instead_of_substituting(
        serve, monkeypatch):
    monkeypatch.setattr(llm, "_OPENAI_REJECTS_TEMPERATURE", frozenset({DEFAULT_ID}))
    server = serve(ok("x"))
    with pytest.raises(ValueError, match="cannot honour"):
        generate("write", temperature=0.7, use_cache=False)
    assert server.requests == []


# ---- selection and discovery --------------------------------------------------------------

def test_llm_provider_openai_selects_the_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    assert llm._read_provider() is Provider.OPENAI


def test_the_handler_is_real_and_in_the_dispatch_table():
    assert llm._PROVIDER_HANDLERS[Provider.OPENAI] is llm._call_openai
    assert llm._FALLBACK_KEY_ENV_VARS[Provider.OPENAI] == "OPENAI_API_KEY"


def test_key_discovery_includes_openai_only_when_the_key_is_set(monkeypatch):
    assert Provider.OPENAI in llm._providers_with_real_keys()
    monkeypatch.delenv("OPENAI_API_KEY")
    assert Provider.OPENAI not in llm._providers_with_real_keys()


def fail_primary(monkeypatch):
    """Make the anthropic primary fail transiently, with no real SDK involved."""
    def down(prompt, temperature, model):
        raise RuntimeError("503 overloaded, try again")
    monkeypatch.setitem(llm._PROVIDER_HANDLERS, Provider.ANTHROPIC, down)
    monkeypatch.setattr(llm, "PROVIDER", Provider.ANTHROPIC)


def test_fallback_skips_openai_when_it_has_no_key(serve, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    server = serve(ok(VALID))
    fail_primary(monkeypatch)
    with pytest.raises(RuntimeError, match="fallback chain failed"):
        judge("grade this", Verdict, use_cache=False)
    assert server.requests == [] and server.constructed == []


def test_fallback_skips_openai_while_its_ids_are_todo_verify(serve, monkeypatch):
    monkeypatch.setitem(llm.MODEL_TIERS["default"], Provider.OPENAI, "TODO(verify)")
    monkeypatch.setitem(llm.MODEL_TIERS["cheap"], Provider.OPENAI, "TODO(verify)")
    server = serve(ok(VALID))
    fail_primary(monkeypatch)
    with pytest.raises(RuntimeError, match="no verified model id"):
        judge("grade this", Verdict, use_cache=False)
    assert server.requests == []


def test_fallback_reaches_openai_when_it_has_a_key_and_verified_ids(serve, monkeypatch):
    server = serve(ok(VALID))
    fail_primary(monkeypatch)
    verdict, record = judge("grade this", Verdict, use_cache=False)
    assert verdict.score == 4 and (record.provider, record.model) == ("openai", DEFAULT_ID)
    assert len(server.requests) == 1


def test_fallback_still_skips_the_other_providers_without_keys(serve, monkeypatch):
    """Only the providers with a key are tried: here openai (key) but not nvidia or google."""
    server = serve(ok(VALID))
    fail_primary(monkeypatch)
    tried = []
    for p in (Provider.NVIDIA, Provider.GOOGLE):
        monkeypatch.setitem(llm._PROVIDER_HANDLERS, p,
                            lambda *a, _p=p: tried.append(_p) or ("{}", 0, 0))
    judge("grade this", Verdict, use_cache=False)
    assert tried == []
    assert len(server.requests) == 1


def test_no_other_provider_handler_is_touched_when_openai_is_primary(serve):
    server = serve(ok(VALID))
    judge("grade this", Verdict, use_cache=False)
    assert len(server.requests) == 1


# ---- a 400 about temperature: learn it, retry once, remember --------------------------------

TEMP_400 = (400, error_body("Unsupported value: 'temperature' does not support 0.0 with this "
                            "model. Only the default (1) value is supported.",
                            "unsupported_value", "invalid_request_error"))


@pytest.fixture
def learned(monkeypatch):
    fresh: set[str] = set()
    monkeypatch.setattr(llm, "_OPENAI_REJECTS_TEMPERATURE", fresh)
    return fresh


def test_a_temperature_400_is_retried_once_without_temperature_and_remembered(serve, learned):
    server = serve(TEMP_400, ok(VALID), ok(VALID))
    verdict, record = judge("grade this", Verdict, use_cache=False)
    assert verdict.score == 4 and record.model == DEFAULT_ID and record.attempt == 1
    assert "temperature" in server.bodies[0] and "temperature" not in server.bodies[1]
    assert learned == {DEFAULT_ID}
    judge("grade this again", Verdict, use_cache=False)         # later calls omit it up front
    assert "temperature" not in server.bodies[2] and len(server.requests) == 3


def test_a_temperature_400_for_a_nonzero_request_raises_instead_of_substituting(serve, learned):
    server = serve(TEMP_400, ok("x"))
    with pytest.raises(ValueError, match="cannot honour"):
        generate("write", temperature=0.7, use_cache=False)
    assert len(server.requests) == 1 and learned == set()


def test_a_400_about_something_else_is_not_retried_inside_the_handler(serve, learned):
    other = (400, error_body("Unsupported parameter: 'max_completion_tokens'.", "x"))
    server = serve(other, other)
    with pytest.raises(RuntimeError, match="BadRequestError"):
        judge("grade this", Verdict, use_cache=False)
    assert len(server.requests) == 2 and learned == set()     # one per model, nothing extra


def test_a_second_temperature_400_after_the_retry_is_an_error_not_a_loop(serve, learned):
    server = serve(TEMP_400, TEMP_400, TEMP_400, TEMP_400)
    with pytest.raises(RuntimeError):
        judge("grade this", Verdict, use_cache=False)
    assert len(server.requests) <= 4


# ---- the failure line says why ---------------------------------------------------------------

def test_failure_line_shows_status_and_the_provider_message(serve, learned, capsys):
    other = (400, error_body("Unsupported parameter: 'max_completion_tokens' is not supported "
                             "with this model.", "unsupported_parameter"))
    serve(other, other)
    with pytest.raises(RuntimeError) as err:
        judge("grade this", Verdict, use_cache=False)
    out = capsys.readouterr().out
    assert "BadRequestError [400]" in out and "max_completion_tokens" in out
    assert "max_completion_tokens" in str(err.value)


def test_describe_error_masks_key_like_strings_and_truncates():
    class E(Exception):
        status_code = 401
        message = "Incorrect API key provided: sk-proj-abcdefghijklmnop1234.\nYou can find it."
    text = llm._describe_error(E())
    assert "sk-proj-abcdefghijklmnop1234" not in text and "[masked]" in text
    assert "\n" not in text and text.startswith("E [401]:")
    assert len(llm._describe_error(Exception("x" * 5000))) < 300
    assert llm._describe_error(Exception("")) == "Exception"
