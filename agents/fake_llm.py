"""agents/fake_llm.py -- a scripted, deterministic stand-in for the provider layer.

WHY IT EXISTS. Every agent test used to fake `llm.judge` itself, which skips exactly the code
that decides what a bad model reply does: fence stripping, schema validation, the corrective
retry, the cost log, the fallback chain and the timeout. This harness fakes one level lower, the
provider handlers (`llm._PROVIDER_HANDLERS`, signature `(prompt, temperature, model) -> (text,
tokens_in, tokens_out)`), so the REAL `system/llm.py` runs on top of scripted raw text.

HOW IT IS INJECTED, WITHOUT EDITING ANY FILE OWNED BY THE OTHER BRANCH. Two ways, same fake:
  - pass a `FakeLLM` to an agent that takes an `llm` argument (`FakeLLM.judge` has the same
    signature as `system.llm.judge`);
  - wrap any code that calls `system.llm.judge` directly (the Code Agent's default path, the
    benchmark) in `with fake.installed():`.

SAFETY (the reason for the odd-looking bits):
  - ALL five provider handlers are replaced, not just the configured one. The gateway's layer 2
    fallback walks to any other provider that has an API key in the environment; with only the
    primary faked, a scripted provider error would reach a REAL provider whenever a key is in
    `.env`. `_providers_with_real_keys` is also forced to `[]`.
  - `PROVIDER` is pinned to anthropic while installed, so a developer's `LLM_PROVIDER` cannot
    change which model ids the chain resolves.
  - `FakeLLM.generate` raises: agents must never call `generate` (llm.py's own rule).
  - No network, no SDK import. The live LLM call count of this module is zero by construction.

SCRIPT MODEL. A script is a list of steps, consumed one per PROVIDER CALL (a `judge` that retries
consumes two; a transient failure consumes one per model in the fallback chain, so a provider
that is down for a whole `judge` needs `provider_error(sticky=True)`). A step is:
  - `text(str | callable(prompt) -> str)`    raw reply text (JSON, fenced JSON, garbage ...)
  - `fail(exc, sticky=False)`                the handler raises `exc`
  - `slow(seconds)`                          the handler sleeps; with the harness timeout
                                             ceiling this exercises the real D-051 path
When the script is empty and no `default` is given, the next call raises `ScriptExhausted`
(a ValueError, which the gateway never retries or wraps), so a test that makes more calls than
it scripted fails loudly instead of hanging or silently reusing a reply.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from system import llm

T = TypeVar("T", bound=BaseModel)

# The ceiling the harness puts around each fake provider call while installed. The real value is
# 30 s (D-051); a test cannot wait that long. 0.2 s is a harness choice, not a measurement.
HARNESS_TIMEOUT_S = 0.2


class ScriptExhausted(ValueError):
    """The code under test made more provider calls than the test scripted."""


class GenerateForbidden(AssertionError):
    """An agent called `generate`. Agents judge at temperature 0 through `judge` only."""


# ---- Steps -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Step:
    kind: str                                   # "text" | "fail" | "slow"
    payload: Any = None
    sticky: bool = False                        # a sticky step is never consumed


def text(value: str | Callable[[str], str]) -> Step:
    """A raw reply. A callable receives the prompt and returns the reply (used when the reply
    must quote something from the prompt, e.g. a line of the submission)."""
    return Step("text", value)


def valid_json(obj: Any) -> Step:
    """A well-formed JSON reply. `obj` may be a dict/list or a pydantic model."""
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return text(json.dumps(obj))


def fenced_json(obj: Any, tag: str = "json") -> Step:
    """The same JSON wrapped in ONE markdown code fence (D-059), as models do in practice."""
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return text(f"```{tag}\n{json.dumps(obj, indent=2)}\n```")


def invalid_json(raw: str = "Sure! Here is my answer: it looks fine to me.") -> Step:
    """A reply that is not JSON at all."""
    return text(raw)


def truncated_fence(obj: Any) -> Step:
    """A fence that is never closed (a truncated reply). The gateway must NOT strip it."""
    return text("```json\n" + json.dumps(obj))


def fail(exc: BaseException, *, sticky: bool = False) -> Step:
    return Step("fail", exc, sticky)


def provider_error(message: str = "503 service unavailable, model overloaded",
                   *, sticky: bool = False) -> Step:
    """A transient provider failure (classified `transient` by the gateway: next model, then
    other providers; with no keys the chain ends in the gateway's RuntimeError)."""
    return fail(RuntimeError(message), sticky=sticky)


def timeout(*, sticky: bool = False) -> Step:
    """The gateway's own call-timeout exception, raised directly (fast). For the real thread
    timeout path use `slow()`."""
    return fail(llm._ProviderCallTimeout("scripted timeout"), sticky=sticky)


def slow(seconds: float = 1.0) -> Step:
    """Sleep long enough to exceed `HARNESS_TIMEOUT_S`, so the gateway's real timeout fires."""
    return Step("slow", seconds)


# ---- The fake ----------------------------------------------------------------------------

@dataclass(frozen=True)
class FakeCall:
    """One PROVIDER call that reached the fake."""

    prompt: str
    model: str
    temperature: float
    provider: str


@dataclass
class FakeLLM:
    """Scripted gateway. See the module docstring.

    Counters: `call_count` = provider calls (what costs money), `judge_count` = logical
    `judge()` calls (what an agent asked for). A clean reply is 1 and 1; a corrective retry is
    2 and 1.
    """

    script: Sequence[Step] = ()
    default: Callable[[str], str | Step] | None = None
    calls: list[FakeCall] = field(default_factory=list)
    judge_count: int = 0

    def __post_init__(self) -> None:
        self._steps: list[Step] = list(self.script)
        self._cache: dict[str, str] = {}
        self.cost_log: list[llm.CallRecord] = []
        self._depth = 0
        self._saved: dict[str, Any] = {}
        self._lock = threading.Lock()

    # ---- scripting ----
    def push(self, *steps: Step) -> FakeLLM:
        self._steps.extend(steps)
        return self

    @property
    def remaining(self) -> int:
        return len(self._steps)

    def assert_exhausted(self) -> None:
        assert not self._steps, f"{len(self._steps)} scripted step(s) were never used"

    # ---- counters ----
    @property
    def call_count(self) -> int:
        return len(self.calls)

    @property
    def prompts(self) -> list[str]:
        return [c.prompt for c in self.calls]

    # ---- the handler the gateway calls ----
    def _next_step(self, prompt: str) -> Step:
        with self._lock:
            if self._steps:
                step = self._steps[0]
                if not step.sticky:
                    self._steps.pop(0)
                return step
        if self.default is not None:
            produced = self.default(prompt)
            return produced if isinstance(produced, Step) else text(produced)
        raise ScriptExhausted(
            f"provider call #{len(self.calls)} was not scripted (script is empty and no default)")

    def _handler(self, provider: llm.Provider) -> Callable[[str, float, str], tuple[str, int, int]]:
        def handler(prompt: str, temperature: float, model: str) -> tuple[str, int, int]:
            with self._lock:
                self.calls.append(FakeCall(prompt, model, temperature, provider.value))
            step = self._next_step(prompt)
            if step.kind == "fail":
                raise step.payload
            if step.kind == "slow":
                time.sleep(step.payload)
                return "{}", 0, 0
            body = step.payload(prompt) if callable(step.payload) else step.payload
            # Deterministic fake token counts: a rough size, not a measurement.
            return body, len(prompt) // 4, len(body) // 4
        return handler

    # ---- injection ----
    @contextlib.contextmanager
    def installed(self) -> Iterator[FakeLLM]:
        """Route `system.llm` to this fake for the duration. Re-entrant. Always restores."""
        if self._depth == 0:
            self._saved = {
                "handlers": dict(llm._PROVIDER_HANDLERS),
                "cache": llm.CACHE,
                "cost_log": llm.COST_LOG,
                "keys": llm._providers_with_real_keys,
                "provider": llm.PROVIDER,
                "timeout": llm._PROVIDER_CALL_TIMEOUT_S,
            }
            for provider in llm.Provider:
                llm._PROVIDER_HANDLERS[provider] = self._handler(provider)
            llm.CACHE = self._cache
            llm.COST_LOG = self.cost_log
            llm._providers_with_real_keys = lambda: []
            llm.PROVIDER = llm.Provider.ANTHROPIC
            llm._PROVIDER_CALL_TIMEOUT_S = HARNESS_TIMEOUT_S
        self._depth += 1
        try:
            yield self
        finally:
            self._depth -= 1
            if self._depth == 0:
                llm._PROVIDER_HANDLERS.clear()
                llm._PROVIDER_HANDLERS.update(self._saved["handlers"])
                llm.CACHE = self._saved["cache"]
                llm.COST_LOG = self._saved["cost_log"]
                llm._providers_with_real_keys = self._saved["keys"]
                llm.PROVIDER = self._saved["provider"]
                llm._PROVIDER_CALL_TIMEOUT_S = self._saved["timeout"]

    # ---- the interface agents use (same as system.llm) ----
    def judge(self, prompt: str, schema: type[T], *, model_tier: str = "default",
              model: str | None = None, use_cache: bool = True) -> tuple[T, llm.CallRecord]:
        self.judge_count += 1
        with self.installed():
            return llm.judge(prompt, schema, model_tier=model_tier, model=model,
                             use_cache=use_cache)

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        raise GenerateForbidden("agents must not call generate(); use judge() at temperature 0")
