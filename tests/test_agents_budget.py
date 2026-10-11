"""Stage 8 -- agents/budget.py: run cap, day cap, per-model counting, the JSON ledger.

No database, no network. The ledger file lives in pytest's tmp_path; nothing is written to the
repository (the real default path `.vdel/llm_usage.json` is only checked, never created).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents import fake_llm as fl
from agents.budget import (
    DEFAULT_LEDGER_PATH,
    DEFAULT_MAX_CALLS_PER_RUN,
    WORST_CASE_CALLS_PER_JUDGE,
    BudgetExceeded,
    CallBudget,
    LedgerCorrupt,
    UsageLedger,
    calls_made,
    model_counts,
)
from system import llm

REPO = Path(__file__).resolve().parent.parent


def rec(model="m1", attempt=1, cache_hit=False):
    return SimpleNamespace(model=model, attempt=attempt, cache_hit=cache_hit)


# ---- counting records ---------------------------------------------------------------------

def test_model_counts_rules():
    assert model_counts([rec()]) == {"m1": 1}
    assert model_counts([rec(cache_hit=True)]) == {}
    assert model_counts([rec(attempt=2)]) == {"m1": 2}              # success after the retry
    assert model_counts([rec(attempt=1), rec(attempt=2)]) == {"m1": 2}   # both attempts known
    assert model_counts([rec("a"), rec("b", attempt=2)]) == {"a": 1, "b": 1}
    assert model_counts([]) == {}
    assert calls_made([rec(attempt=2)]) == 2


# ---- the per-run cap ----------------------------------------------------------------------

def test_default_is_small_and_covers_one_pipeline_run():
    assert CallBudget().max_calls == DEFAULT_MAX_CALLS_PER_RUN == 6
    assert DEFAULT_MAX_CALLS_PER_RUN >= 3 * WORST_CASE_CALLS_PER_JUDGE


def test_run_cap_refuses_before_reserving_anything():
    b = CallBudget(max_calls=3)
    b.charge(2)
    with pytest.raises(BudgetExceeded) as err:
        b.charge(2, what="the test call")
    assert b.used == 2 and err.value.cap == "run" and err.value.limit == 3
    assert "the test call" in str(err.value) and "No call was made" in str(err.value)


def test_settle_refunds_what_was_not_used_and_counts_by_model():
    b = CallBudget(max_calls=6)
    b.charge(2)
    assert b.settle(2, [rec("m1")]) == 1
    assert (b.used, b.remaining, dict(b.by_model)) == (1, 5, {"m1": 1})


def test_settle_never_goes_below_what_was_reserved_when_calls_exceed_it():
    b = CallBudget(max_calls=6)
    b.charge(1)
    b.settle(1, [rec(attempt=2)])                 # reality: 2 calls against a 1-call reservation
    assert b.used == 1                             # the run cap is a reservation cap; day ledger
    assert dict(b.by_model) == {"m1": 2}           # still records the true count


def test_settle_unknown_keeps_the_reservation_and_counts_it_as_unknown():
    b = CallBudget(max_calls=6)
    b.charge(2)
    b.settle_unknown(2)
    assert b.used == 2 and dict(b.by_model) == {"unknown": 2}


# ---- the day cap and the ledger -----------------------------------------------------------

def test_day_cap_is_shared_by_every_run_through_the_ledger():
    ledger = UsageLedger()
    first = CallBudget(max_calls=10, day_cap=3, ledger=ledger)
    first.charge(2)
    first.settle(2, [rec(), rec()])                         # 2 calls spent today
    second = CallBudget(max_calls=10, day_cap=3, ledger=ledger)   # a later run
    with pytest.raises(BudgetExceeded) as err:
        second.charge(2)
    assert err.value.cap == "day" and err.value.used == 2 and err.value.limit == 3
    second.charge(1)                                         # 2 + 1 == 3: allowed


def test_day_cap_counts_reservations_that_are_not_settled_yet():
    ledger = UsageLedger()
    b = CallBudget(max_calls=10, day_cap=3, ledger=ledger)
    b.charge(2)
    with pytest.raises(BudgetExceeded) as err:
        b.charge(2)                                          # 0 settled + 2 reserved + 2 > 3
    assert err.value.cap == "day"


def test_day_rolls_over_with_the_clock():
    today = {"d": date(2026, 10, 11)}
    ledger = UsageLedger(clock=lambda: today["d"])
    b = CallBudget(max_calls=10, day_cap=2, ledger=ledger)
    b.charge(2)
    b.settle(2, [rec(), rec()])
    with pytest.raises(BudgetExceeded):
        CallBudget(max_calls=10, day_cap=2, ledger=ledger).charge(1)
    today["d"] += timedelta(days=1)
    CallBudget(max_calls=10, day_cap=2, ledger=ledger).charge(2)    # a new day, a new allowance
    assert ledger.day_total("2026-10-11") == 2


def test_a_day_cap_without_a_ledger_gets_a_memory_ledger():
    b = CallBudget(day_cap=1)
    assert isinstance(b.ledger, UsageLedger) and b.ledger.path is None
    with pytest.raises(BudgetExceeded):
        b.charge(2)


def test_zero_day_cap_blocks_everything():
    with pytest.raises(BudgetExceeded):
        CallBudget(day_cap=0).charge(1)


def test_negative_caps_are_rejected():
    with pytest.raises(ValueError):
        CallBudget(max_calls=-1)
    with pytest.raises(ValueError):
        CallBudget(day_cap=-1)


def test_per_model_day_cap_refuses_once_that_model_has_reached_it():
    ledger = UsageLedger()
    ledger.add({"m1": 3, "m2": 1})
    b = CallBudget(max_calls=10, ledger=ledger, model_day_caps={"m1": 3, "m2": 5})
    with pytest.raises(BudgetExceeded) as err:
        b.charge(1)
    assert err.value.cap == "model" and err.value.used == 3
    ok = CallBudget(max_calls=10, ledger=ledger, model_day_caps={"m1": 4, "m2": 5})
    ok.charge(1)


def test_ledger_counts_by_model_and_day():
    ledger = UsageLedger(clock=lambda: date(2026, 1, 2))
    ledger.add({"a": 2, "b": 1})
    ledger.add({"a": 1})
    ledger.add({"c": 0})                                     # zero is ignored
    assert ledger.day_total() == 4 and ledger.day_by_model() == {"a": 3, "b": 1}
    assert ledger.day_total("2026-01-01") == 0


# ---- persistence --------------------------------------------------------------------------

def test_ledger_persists_counts_only_and_reloads(tmp_path):
    path = tmp_path / "sub" / "usage.json"
    clock = lambda: date(2026, 10, 11)  # noqa: E731
    UsageLedger(path, clock=clock).add({"claude-x": 2})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"version": 1, "days": {"2026-10-11": {"by_model": {"claude-x": 2},
                                                          "total": 2}}}
    again = UsageLedger(path, clock=clock)
    assert again.day_total() == 2
    again.add({"claude-x": 1})
    assert UsageLedger(path, clock=clock).day_by_model() == {"claude-x": 3}
    assert [p.name for p in path.parent.iterdir()] == ["usage.json"]       # no temp file left


def test_missing_file_means_no_usage_yet(tmp_path):
    ledger = UsageLedger(tmp_path / "nope.json")
    assert ledger.day_total() == 0
    assert not (tmp_path / "nope.json").exists()                  # reading creates nothing


@pytest.mark.parametrize("content", ["not json", "[]", '{"days": 3}', '{"days": {"d": {}}}', ""])
def test_unreadable_ledger_fails_closed(tmp_path, content):
    path = tmp_path / "usage.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(LedgerCorrupt):
        UsageLedger(path)


def test_two_budget_objects_over_one_file_share_the_day(tmp_path):
    path = tmp_path / "usage.json"
    a = CallBudget(max_calls=6, day_cap=3, ledger=UsageLedger(path))
    a.charge(2)
    a.settle(2, [rec(), rec()])
    b = CallBudget(max_calls=6, day_cap=3, ledger=UsageLedger(path))      # a new process, say
    with pytest.raises(BudgetExceeded):
        b.charge(2)


def test_the_default_ledger_path_is_gitignored_and_nothing_was_created_there():
    assert Path(".vdel") / "llm_usage.json" == DEFAULT_LEDGER_PATH
    lines = {ln.strip() for ln in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert ".vdel/" in lines
    assert not (REPO / ".vdel").exists()


def test_summary_is_json():
    b = CallBudget(max_calls=6, day_cap=9)
    b.charge(2)
    b.settle(2, [rec()])
    out = b.summary()
    json.dumps(out)
    assert out["used"] == 1 and out["day"]["total"] == 1 and out["day"]["cap"] == 9


# ---- wired into the agents ----------------------------------------------------------------

def test_a_provider_failure_is_counted_in_full_in_the_ledger():
    from agents.feedback_agent import FeedbackInput, run_feedback_agent
    data = json.loads((REPO / "tests" / "fixtures" / "agents" / "real" /
                       "student2__weather_etl_extract__a82__128da3e9__ok.json").read_text("utf-8"))
    ledger = UsageLedger()
    budget = CallBudget(max_calls=6, day_cap=10, ledger=ledger)
    fake = fl.FakeLLM([fl.provider_error(sticky=True)])
    run_feedback_agent(FeedbackInput.from_fixture(data), fake, budget, hidden=frozenset(),
                       fallback_markdown=lambda: "v0")
    assert ledger.day_by_model() == {"unknown": WORST_CASE_CALLS_PER_JUDGE}
    assert budget.used == WORST_CASE_CALLS_PER_JUDGE


def test_a_day_cap_stops_the_feedback_agent_with_a_fallback():
    from agents.feedback_agent import SOURCE_FALLBACK, FeedbackInput, run_feedback_agent
    data = json.loads((REPO / "tests" / "fixtures" / "agents" / "real" /
                       "student2__weather_etl_extract__a82__128da3e9__ok.json").read_text("utf-8"))
    ledger = UsageLedger()
    ledger.add({"claude-x": 5})
    budget = CallBudget(max_calls=6, day_cap=5, ledger=ledger)
    fake = fl.FakeLLM()
    res = run_feedback_agent(FeedbackInput.from_fixture(data), fake, budget, hidden=frozenset(),
                             fallback_markdown=lambda: "v0")
    assert res.source == SOURCE_FALLBACK and fake.call_count == 0
    assert res.reasons[0].startswith("budget_exceeded: day cap 5")


def test_a_real_success_is_counted_under_the_model_that_served_it():
    from agents.code_agent import CRITERIA, grade
    code = REPO / "tests" / "fixtures" / "agents" / "code" / "extract_retry_ok.py"
    body = {"evidence": {c: [{"quote": "for attempt in range(MAX_ATTEMPTS):", "why": "x"}]
                         for c in CRITERIA},
            "scores": {"llm_correctness_opinion": 2, "approach": 2, "readability": 2,
                       "idiomatic": 2},
            "feedback_for_student": "ok", "confidence": "low"}
    mem = SimpleNamespace(get_profile=lambda s, conn=None: {"mastery": {}, "weaknesses": []},
                          log_trace=lambda *a, **k: 1, update_mastery=lambda *a, **k: None)
    ledger = UsageLedger()
    budget = CallBudget(max_calls=6, day_cap=6, ledger=ledger)
    fake = fl.FakeLLM([fl.invalid_json(), fl.valid_json(body)])
    grade(mem, "s", {"assignment_id": "a", "task": "t", "concepts": []}, str(code),
          llm_client=fake, budget=budget)
    cheap_or_default = llm.MODEL_TIERS["default"][llm.Provider.ANTHROPIC]
    assert ledger.day_by_model() == {cheap_or_default: 2} and budget.used == 2
