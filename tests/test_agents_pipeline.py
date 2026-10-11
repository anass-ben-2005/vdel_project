"""Stage 7 -- agents/pipeline.py: fixed order, failure isolation, no persistence, shared budget.

Test database (one rolled-back transaction per test) and the scripted fake provider. No live
call; the real database is never connected to.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agents import fake_llm as fl
from agents import pipeline as pl
from agents.budget import BudgetExceeded, CallBudget
from agents.code_agent import CRITERIA
from system import db

pytestmark = pytest.mark.skipif(not os.environ.get("PG_DSN"), reason="PG_DSN not set")

CODE = Path(__file__).resolve().parent / "fixtures" / "agents" / "code" / "extract_retry_ok.py"
S, ASG = "_pipe_student", "weather_etl_extract"
SHA = "d" * 40
T_RETRY = "tests/hidden/test_extract.py::test_fetch_weather_retries_then_succeeds"
ASSIGNMENT = {"assignment_id": ASG, "concepts": ["py.errors_debugging"],
              "task": "Fetch the weather with a bounded retry loop."}


def verdict_reply():
    return {"evidence": {c: [{"quote": "for attempt in range(MAX_ATTEMPTS):", "why": "loop"}]
                         for c in CRITERIA},
            "scores": {"llm_correctness_opinion": 4, "approach": 4, "readability": 2,
                       "idiomatic": 2},
            "misconceptions": [], "feedback_for_student": "Bounded loop.", "confidence": "high"}


def feedback_reply():
    return {"summary": "The retry check failed with a ConnectionError; start there.",
            "what_to_check_next": ["Re-read the retry instruction in your file."],
            "cited_tests": ["test_fetch_weather_retries_then_succeeds"],
            "cited_concepts": ["py.errors_debugging"], "resource_id": None,
            "confidence": "medium"}


@pytest.fixture
def world():
    from tests.support import ensure_variant
    conn = db._open()
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, S))
    variant = ensure_variant(cur, ASG)
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl',%s,1,%s,1) RETURNING attempt_id",
                (S, ASG, variant))
    aid = cur.fetchone()[0]
    cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                " VALUES (%s,%s,%s,'2026-08-25 01:00+00')", (SHA, S, ASG))
    cur.execute("INSERT INTO test_results (attempt_id, commit_sha, test_name, gap_id, passed,"
                " message, status) VALUES (%s,%s,%s,'g_ext_retry',false,'AssertionError: x','ok')",
                (aid, SHA, T_RETRY))
    yield conn, cur, aid
    conn.rollback()
    conn.close()


class NoProfileMemory:
    """Reads only; an unknown student has an empty profile."""

    def get_profile(self, student_id, *, conn=None):
        return {"mastery": {}, "weaknesses": []}


def run(cur, aid, fake, budget=None, **kw):
    kw.setdefault("code_path", CODE)
    kw.setdefault("assignment", ASSIGNMENT)
    return pl.run_agents_for_commit(S, aid, SHA, llm=fake, budget=budget, cur=cur,
                                    memory=NoProfileMemory(), **kw)


def counts(cur):
    out = {}
    for table in ("traces", "test_results", "learner_profile", "attempts", "feedback_posts",
                  "resources"):
        cur.execute(f"SELECT count(*) FROM {table}")
        out[table] = cur.fetchone()[0]
    return out


def test_both_agents_run_in_the_fixed_order(world):
    _, cur, aid = world
    fake = fl.FakeLLM([fl.valid_json(verdict_reply()), fl.valid_json(feedback_reply())])
    summary = run(cur, aid, fake)
    assert list(summary.steps) == list(pl.ORDER) == [pl.CODE_AGENT, pl.FEEDBACK_AGENT]
    assert summary.ok and all(s.status == pl.OK for s in summary.steps.values())
    assert "<<<BEGIN SUBMISSION>>>" in fake.prompts[0]          # the Code Agent went first
    assert "Facts (computed by the system" in fake.prompts[1]
    assert summary.feedback_markdown and "checks passed" in summary.feedback_markdown
    assert summary.persisted is False


def test_persist_true_is_refused_before_anything_runs(world):
    _, cur, aid = world
    fake = fl.FakeLLM([fl.valid_json(verdict_reply())])
    with pytest.raises(pl.IntegrationPending, match="IR-3"):
        run(cur, aid, fake, persist=True)
    assert fake.call_count == 0 and fake.judge_count == 0


def test_nothing_is_written_and_would_be_writes_are_only_recorded(world):
    _, cur, aid = world
    before = counts(cur)
    fake = fl.FakeLLM([fl.valid_json(verdict_reply()), fl.valid_json(feedback_reply())])
    summary = run(cur, aid, fake)
    assert counts(cur) == before
    kinds = [(t.get("actor"), t.get("kind"), t.get("would")) for t in summary.dry_run_traces]
    assert ("code_agent", "verdict", None) in kinds
    assert (None, None, "update_mastery") in kinds


def test_a_failing_code_agent_does_not_stop_the_feedback_agent(world):
    _, cur, aid = world
    fake = fl.FakeLLM([fl.invalid_json(), fl.invalid_json(), fl.valid_json(feedback_reply())])
    summary = run(cur, aid, fake)
    code, feedback = summary.steps[pl.CODE_AGENT], summary.steps[pl.FEEDBACK_AGENT]
    assert code.status == pl.FAILED and code.error.startswith("SchemaValidationError")
    assert feedback.status == pl.OK and feedback.result.used_llm
    assert summary.ok is False


def test_a_failing_feedback_agent_does_not_lose_the_code_agent_result(world):
    _, cur, aid = world
    fake = fl.FakeLLM([fl.valid_json(verdict_reply())])
    summary = pl.run_agents_for_commit(S, aid + 9999, SHA, llm=fake, budget=None, cur=cur,
                                       memory=NoProfileMemory(), code_path=CODE,
                                       assignment=ASSIGNMENT)
    assert summary.steps[pl.CODE_AGENT].status == pl.OK
    assert summary.steps[pl.FEEDBACK_AGENT].status == pl.FAILED
    assert summary.steps[pl.FEEDBACK_AGENT].error.startswith("ValueError")


def test_both_failing_still_returns_a_summary_and_does_not_raise(world):
    _, cur, aid = world
    fake = fl.FakeLLM([fl.provider_error(sticky=True)])
    summary = pl.run_agents_for_commit(S, aid + 9999, SHA, llm=fake, budget=None, cur=cur,
                                       memory=NoProfileMemory(), code_path=CODE,
                                       assignment=ASSIGNMENT)
    assert [s.status for s in summary.steps.values()] == [pl.FAILED, pl.FAILED]
    assert not summary.ok
    json.dumps(summary.to_dict())


def test_code_agent_is_skipped_without_its_inputs_and_feedback_still_runs(world):
    _, cur, aid = world
    fake = fl.FakeLLM([fl.valid_json(feedback_reply())])
    summary = run(cur, aid, fake, code_path=None, assignment=None)
    assert summary.steps[pl.CODE_AGENT].status == pl.SKIPPED
    assert "assignment['task']" in summary.steps[pl.CODE_AGENT].detail
    assert summary.steps[pl.FEEDBACK_AGENT].status == pl.OK and summary.ok
    no_task = run(cur, aid, fl.FakeLLM([fl.valid_json(feedback_reply())]),
                  assignment={"assignment_id": ASG, "task": "   "})
    assert no_task.steps[pl.CODE_AGENT].status == pl.SKIPPED


def test_the_budget_is_shared_and_reported(world):
    _, cur, aid = world
    fake = fl.FakeLLM([fl.valid_json(verdict_reply()), fl.valid_json(feedback_reply())])
    budget = CallBudget(max_calls=6)
    summary = run(cur, aid, fake, budget)
    assert budget.used == 2 and summary.budget["used"] == 2
    assert [s.provider_calls for s in summary.steps.values()] == [1, 1]


def test_budget_runs_out_for_the_second_agent_and_feedback_falls_back(world):
    _, cur, aid = world
    fake = fl.FakeLLM([fl.valid_json(verdict_reply()), fl.valid_json(feedback_reply())])
    summary = run(cur, aid, fake, CallBudget(max_calls=2))   # code uses 1; 1 left < the 2 needed
    assert summary.steps[pl.CODE_AGENT].status == pl.OK
    feedback = summary.steps[pl.FEEDBACK_AGENT]
    assert feedback.status == pl.OK and not feedback.result.used_llm
    assert any("budget_exceeded" in r for r in feedback.result.reasons)
    assert fake.call_count == 1


def test_a_budget_too_small_for_the_first_agent_is_reported_as_that_agents_failure(world):
    _, cur, aid = world
    fake = fl.FakeLLM()
    summary = run(cur, aid, fake, CallBudget(max_calls=1))
    assert summary.steps[pl.CODE_AGENT].error.startswith("BudgetExceeded")
    assert fake.call_count == 0
    assert isinstance(BudgetExceeded("x", cap="run", limit=1, used=0, wanted=2), RuntimeError)


def test_without_a_cursor_it_opens_and_closes_its_own_read_only_session(world):
    """The world is uncommitted, so a second session cannot see the attempt: the Feedback step
    fails cleanly, which also shows the session was really separate and was cleaned up."""
    _, _, aid = world
    fake = fl.FakeLLM()
    summary = pl.run_agents_for_commit(S, aid, SHA, llm=fake, budget=None,
                                       memory=NoProfileMemory())
    assert summary.steps[pl.FEEDBACK_AGENT].status == pl.FAILED
    assert summary.steps[pl.CODE_AGENT].status == pl.SKIPPED


def test_dry_run_memory_returns_negative_ids_and_delegates_reads():
    sink = []
    mem = pl.DryRunMemory(NoProfileMemory(), sink)
    assert mem.get_profile("x")["mastery"] == {}
    assert mem.log_trace("x", "code_agent", "verdict", {"a": 1}, conn=object()) == -1
    assert mem.log_trace("x", "code_agent", "verdict", {"a": 2}) == -2
    assert "conn" not in sink[0]


def test_load_assignment_inputs_builds_the_code_agent_inputs_read_only(world):
    _, cur, _ = world
    before = counts(cur)
    assignment, file_path = pl.load_assignment_inputs(cur, ASG)
    assert assignment["assignment_id"] == ASG
    assert assignment["task"].strip() and assignment["concepts"]
    assert file_path and file_path.endswith(".py")
    assert counts(cur) == before
    with pytest.raises(ValueError):
        pl.load_assignment_inputs(cur, "no_such_assignment")
