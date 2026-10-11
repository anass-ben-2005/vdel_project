"""agents/budget.py -- hard caps on LLM calls, so a loop or a misconfigured run cannot spend.

Counts PROVIDER calls, because that is what costs money and what quotas are measured in. One
logical `llm.judge()` is one provider call, or two if the first reply fails validation and the
gateway's corrective retry fires (D-022), or zero if the reply came from the cache. The caller
therefore reserves the worst case before the call and settles afterwards:

    budget.charge(WORST_CASE_CALLS_PER_JUDGE)          # raises BudgetExceeded BEFORE any call
    try:
        obj, record = client.judge(...)
    except SchemaValidationError as err:
        budget.settle(WORST_CASE_CALLS_PER_JUDGE, err.records); raise
    except Exception:
        budget.settle_unknown(WORST_CASE_CALLS_PER_JUDGE); raise   # how many reached a provider
                                                                    # is unknown: count them all
    budget.settle(WORST_CASE_CALLS_PER_JUDGE, [record])

so a cap is never exceeded, not even by a retry. `BudgetExceeded` is raised before the provider is
reached, so an over-budget run makes zero further calls.

Three limits, all optional except the first:
  - PER RUN  `max_calls` (default `DEFAULT_MAX_CALLS_PER_RUN`): one `CallBudget` object = one run.
  - PER DAY  `day_cap`, counted in a `UsageLedger` shared by every run of the day.
  - PER MODEL PER DAY  `model_day_caps={"model-id": n}`: the model is only known after a call, so
    this refuses when a capped model has ALREADY reached its cap today (conservative).
Usage is counted by model (`by_model` for the run, `UsageLedger.day_by_model` for the day).

THE LEDGER is memory-only by default (`UsageLedger(path=None)`), or a small JSON file of COUNTS
(no prompt, no reply, no student data) at `.vdel/llm_usage.json`, a path `.gitignore` excludes.
It fails closed: an unreadable file raises `LedgerCorrupt` rather than being treated as "no usage
yet", because forgetting what was spent is the unsafe direction.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# A judge() that fails validation once makes one more call (the gateway's single corrective
# retry). That is the whole worst case; the gateway never retries more than once.
WORST_CASE_CALLS_PER_JUDGE = 2

# "Default small" (the brief). One Code Agent grade is at most 2 calls and one Feedback Agent
# run at most 4 (two judge() calls, one corrective rewrite after a rejected answer), so 6 covers
# one full pipeline run for one commit. A design choice, not a measurement.
DEFAULT_MAX_CALLS_PER_RUN = 6

DEFAULT_LEDGER_PATH = Path(".vdel") / "llm_usage.json"
LEDGER_VERSION = 1


class BudgetExceeded(RuntimeError):
    """A call was refused because it could push usage over a cap. No provider was reached."""

    def __init__(self, message: str, *, cap: str, limit: int, used: int, wanted: int) -> None:
        super().__init__(message)
        self.cap = cap                  # "run" | "day" | "model"
        self.limit = limit
        self.used = used
        self.wanted = wanted


class LedgerCorrupt(RuntimeError):
    """The usage file exists but cannot be read. Fails closed: spending is not allowed on top
    of a history that is unknown."""


def model_counts(records: Iterable) -> Counter:
    """Provider calls per model that a set of `CallRecord`s stands for. Cache hits cost nothing.

    `llm.judge()` returns only the record of the call that SUCCEEDED, so a success after the
    corrective retry arrives as a single record with `attempt == 2` whose failed first attempt
    is not in the list: that stands for two calls on that model. A `SchemaValidationError`
    carries both attempts' records, so each counts once.
    """
    live = [r for r in records if not getattr(r, "cache_hit", False)]
    counts: Counter = Counter(getattr(r, "model", "unknown") for r in live)
    attempts = {getattr(r, "attempt", 1) for r in live}
    if 2 in attempts and 1 not in attempts:
        second = next(r for r in live if getattr(r, "attempt", 1) == 2)
        counts[getattr(second, "model", "unknown")] += 1
    return counts


def calls_made(records: Iterable) -> int:
    return sum(model_counts(records).values())


class UsageLedger:
    """Per-day call counts, by model. In memory, or in a small JSON file (see module docstring).

    `clock` returns today's date (injectable for tests). The file holds only
    `{"version": 1, "days": {"YYYY-MM-DD": {"total": n, "by_model": {model: n}}}}`.
    """

    def __init__(self, path: str | Path | None = None, *,
                 clock: Callable[[], date] = date.today) -> None:
        self.path = Path(path) if path is not None else None
        self._clock = clock
        self._days: dict[str, dict] = {}
        if self.path is not None and self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._days = {
                    day: {"total": int(v["total"]),
                          "by_model": {m: int(n) for m, n in v["by_model"].items()}}
                    for day, v in data["days"].items()}
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                raise LedgerCorrupt(
                    f"{self.path} exists but cannot be read ({type(exc).__name__}); "
                    "fix or delete it deliberately: usage is unknown, so spending is refused"
                ) from None

    def today(self) -> str:
        return self._clock().isoformat()

    def day_total(self, day: str | None = None) -> int:
        return self._days.get(day or self.today(), {}).get("total", 0)

    def day_by_model(self, day: str | None = None) -> dict[str, int]:
        return dict(self._days.get(day or self.today(), {}).get("by_model", {}))

    def add(self, counts: Mapping[str, int]) -> None:
        """Add calls to today's totals and persist (atomically, if there is a file)."""
        counts = {m: n for m, n in counts.items() if n > 0}
        if not counts:
            return
        day = self._days.setdefault(self.today(), {"total": 0, "by_model": {}})
        for model, n in counts.items():
            day["total"] += n
            day["by_model"][model] = day["by_model"].get(model, 0) + n
        self._save()

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        body = json.dumps({"version": LEDGER_VERSION, "days": self._days},
                          indent=2, sort_keys=True)
        tmp.write_text(body + "\n", encoding="utf-8")
        os.replace(tmp, self.path)           # atomic on the same filesystem


@dataclass
class CallBudget:
    """One run's budget. See the module docstring for the three limits."""

    max_calls: int = DEFAULT_MAX_CALLS_PER_RUN
    day_cap: int | None = None
    ledger: UsageLedger | None = None
    model_day_caps: Mapping[str, int] | None = None
    used: int = 0
    by_model: Counter = field(default_factory=Counter)
    _reserved: int = 0

    def __post_init__(self) -> None:
        if self.max_calls < 0 or (self.day_cap is not None and self.day_cap < 0):
            raise ValueError("caps must be >= 0")
        if (self.day_cap is not None or self.model_day_caps) and self.ledger is None:
            self.ledger = UsageLedger()          # memory only: a cap needs something to count in

    @property
    def remaining(self) -> int:
        return self.max_calls - self.used

    def charge(self, n: int = WORST_CASE_CALLS_PER_JUDGE, *, what: str = "llm call") -> None:
        """Reserve `n` calls. Raises `BudgetExceeded` (and reserves nothing) if they do not fit
        under the run cap, the day cap or a model's day cap."""
        if n > self.remaining:
            raise BudgetExceeded(
                f"LLM call budget exceeded for this run: {what} needs up to {n} call(s), "
                f"{self.used} of {self.max_calls} already used. No call was made.",
                cap="run", limit=self.max_calls, used=self.used, wanted=n)
        if self.day_cap is not None:
            today = self.ledger.day_total() + self._reserved
            if today + n > self.day_cap:
                raise BudgetExceeded(
                    f"LLM daily cap exceeded: {what} needs up to {n} call(s), {today} of "
                    f"{self.day_cap} already used today. No call was made.",
                    cap="day", limit=self.day_cap, used=today, wanted=n)
        for model, cap in (self.model_day_caps or {}).items():
            done = self.ledger.day_by_model().get(model, 0)
            if done >= cap:
                raise BudgetExceeded(
                    f"LLM daily cap for model {model!r} reached ({done} of {cap}). "
                    "No call was made.", cap="model", limit=cap, used=done, wanted=n)
        self.used += n
        self._reserved += n

    def settle(self, reserved: int, records: Iterable) -> int:
        """Replace a reservation by what really happened. Returns the calls actually made."""
        counts = model_counts(records)
        made = sum(counts.values())
        self.used -= max(0, reserved - made)
        self._reserved -= reserved
        self.by_model.update(counts)
        if self.ledger is not None:
            self.ledger.add(counts)
        return made

    def settle_unknown(self, reserved: int) -> None:
        """A call failed in a way that hides how many attempts reached a provider (a transport
        error, a timeout). Count the whole reservation, under the model name `unknown`."""
        self._reserved -= reserved
        self.by_model["unknown"] += reserved
        if self.ledger is not None:
            self.ledger.add({"unknown": reserved})

    def summary(self) -> dict:
        out = {"max_calls": self.max_calls, "used": self.used, "remaining": self.remaining,
               "by_model": dict(self.by_model)}
        if self.ledger is not None:
            out["day"] = {"date": self.ledger.today(), "total": self.ledger.day_total(),
                          "cap": self.day_cap, "by_model": self.ledger.day_by_model()}
        return out
