"""D-104 -- the hardened Code Agent wired into the after_grade hook, behind `--with-code-agent`.

Fake LLM only. Every provider handler raises unless a `FakeLLM` is installed, GitHub is the fake
layer of tests/test_run_cycle.py, nothing is posted except to a recording issue client, and the
database is the throwaway test one in a rolled-back transaction (the D-064 counter at the end of a
run says 0 connections to `vdel`). The real grader runs (a pytest subprocess) on a SOLVED file (all
checks pass: the Code Agent's case) or an UNSOLVED one (a check fails: the Feedback Agent's case).
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents import code_agent
from agents import fake_llm as fl
from agents.budget import UsageLedger
from assessment.gap_parser import render_student_file
from memory.memory import Memory
from scripts import code_agent_report as report
from scripts import grade_collected as gc
from scripts import post_feedback as pf
from scripts import run_cycle as rc
from scripts import run_hourly as rh
from system import db
from system import llm as gateway
from tests.test_code_agent_hardening import submission_of
from tests.test_run_cycle import (
    ASSIGNMENT,
    FakeGitHub,
    fingerprint,
    insert_commit,
    make_student,
    roster_for,
)
from tests.test_template_commit import ASG as TPL_ASG
from tests.test_template_commit import S as TPL_STUDENT
from tests.test_template_commit import delivered
from tests.test_with_llm import (
    SUMMARY,
    RecordingIssues,
    UnsolvedGitHub,
    coach_traces,
    cycle,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

ROOT = Path(__file__).resolve().parent.parent
SECRET = "CODE-AGENT-SECRET-TEXT"
SHA_FAIL, SHA_PASS = "a" * 40, "e" * 40
PROVIDER_ENV = {"LLM_PROVIDER": "openai"}
FEEDBACK = json.dumps({"summary": SUMMARY, "what_to_check_next": ["Read the TODO comments again."],
                       "cited_tests": [], "cited_concepts": [], "resource_id": None,
                       "confidence": "medium"})


@pytest.fixture
def conn():
    try:
        c = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    yield c
    c.rollback()
    c.close()


def both_agents(*, approach: int = 2, quote: str | None = None):
    """A fake that answers the Code Agent's prompt (it holds the submission fence) with a
    verdict for exactly the criteria that prompt asks, and any other prompt with a valid
    feedback reply."""
    def answer(prompt: str) -> str:
        if "<<<BEGIN SUBMISSION>>>" not in prompt:
            return FEEDBACK
        used = ["correctness", "approach", "readability"]
        if '"idiomatic"' in prompt:
            used.append("idiomatic")
        lines = [ln.strip() for ln in submission_of(prompt).splitlines()
                 if ln.strip() and not ln.strip().startswith("[...")]
        chosen = quote if quote is not None else max(lines, key=len)
        scores = {"llm_correctness_opinion": 2, "approach": approach, "readability": 4,
                  "idiomatic": 2}
        keep = {("llm_correctness_opinion" if c == "correctness" else c) for c in used}
        return json.dumps({
            "evidence": {c: [{"quote": chosen, "why": "w"}] for c in used},
            "scores": {k: v for k, v in scores.items() if k in keep},
            "misconceptions": [], "feedback_for_student": SECRET, "confidence": "low"})
    return fl.FakeLLM(default=answer)


class SolvedGitHub(FakeGitHub):
    """The checkout holds the finished file, without the author's marker lines."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        master = (self.root / "weather_etl" / "transform.py").read_text(encoding="utf-8")
        self.solved = render_student_file(master, hide_gap_ids=[])

    def checkout(self, owner, repo, sha, dest):
        super().checkout(owner, repo, sha, dest)
        (Path(dest) / "weather_etl" / "transform.py").write_text(self.solved, encoding="utf-8")


class TwoCommitGitHub(SolvedGitHub):
    """One attempt, two pushes: the first leaves two gaps unfilled (a check fails), the second
    is the finished file (all pass)."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        master = (self.root / "weather_etl" / "transform.py").read_text(encoding="utf-8")
        self.unsolved = render_student_file(master, hide_gap_ids=["g_tf_clean", "g_tf_convert"])

    def collect(self, c, repos):
        sid = repos[0]["student_id"]
        self.collect_calls.append(sid)
        for sha, at in ((SHA_FAIL, "2026-08-25 02:00+00"), (SHA_PASS, "2026-08-25 03:00+00")):
            c.cursor().execute(
                "INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at, additions,"
                " deletions, files_changed, message) VALUES (%s,%s,%s,%s,9,1,1,'work')"
                " ON CONFLICT (sha) DO NOTHING", (sha, sid, ASSIGNMENT, at))
        return {"ok": 1, "failed": [], "stats": "fake"}

    def checkout(self, owner, repo, sha, dest):
        FakeGitHub.checkout(self, owner, repo, sha, dest)
        text = self.solved if sha == SHA_PASS else self.unsolved
        (Path(dest) / "weather_etl" / "transform.py").write_text(text, encoding="utf-8")


def verdicts(conn, sid):
    cur = conn.cursor()
    cur.execute("SELECT trace_id, payload FROM traces WHERE student_id = %s"
                " AND actor = 'code_agent' AND kind = 'verdict' ORDER BY trace_id", (sid,))
    return cur.fetchall()


def text_of(lines) -> str:
    return "\n".join(lines)


def prompts_of_code_agent(fake) -> list[str]:
    return [p for p in fake.prompts if "<<<BEGIN SUBMISSION>>>" in p]


# --- the flags -----------------------------------------------------------------------------------

def test_the_flags_are_off_by_default_and_the_code_agent_needs_with_llm():
    import argparse
    parser = argparse.ArgumentParser()
    rc.add_llm_arguments(parser)
    args = parser.parse_args([])
    assert (args.with_llm, args.with_code_agent, args.code_agent_max_chars) == (
        False, False, rc.DEFAULT_CODE_PROMPT_CAP)
    for fn in (rc.run_cycle, rh.run):
        import inspect
        assert inspect.signature(fn).parameters["with_code_agent"].default is False


def test_with_code_agent_without_with_llm_is_refused_before_any_work(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = SolvedGitHub(tmp_path)
    fake = both_agents()
    before = fingerprint(conn, ["_cyc_a"])
    lines: list[str] = []
    result = rc.run_cycle(roster_for("_cyc_a"), student="_cyc_a", conn=conn, collect=gh.collect,
                          checkout=gh.checkout, out=lines.append, llm=fake, with_code_agent=True)
    assert result.exit_code == rc.EXIT_REFUSED == 4 and result.students == []
    assert "REFUSED: --with-code-agent runs only together with --with-llm" in text_of(lines)
    assert gh.collect_calls == [] and gh.checkout_calls == [] and fake.call_count == 0
    assert fingerprint(conn, ["_cyc_a"]) == before


@pytest.fixture
def roster_file(tmp_path):
    path = tmp_path / "roster.yaml"
    path.write_text(f"assignments:\n  - assignment_id: {ASSIGNMENT}\n    owner: o\n"
                    "    repo: repo-_cyc_a\n    student_id: _cyc_a\n", encoding="utf-8")
    return path


def hourly(conn, tmp_path, roster, gh, *, fake, monkeypatch=None, issues=None, env=None, **flags):
    lines: list[str] = []
    code = rh.run(roster_path=roster, log_dir=tmp_path / "logs", now=datetime.now(UTC), conn=conn,
                  collect=gh.collect, checkout=gh.checkout, grade=None, gh=issues,
                  out=lines.append, llm=fake, ledger=UsageLedger(),
                  env=PROVIDER_ENV if env is None else env, **flags)
    return code, text_of(lines)


def test_run_hourly_refuses_to_start_without_llm_provider_and_does_no_work(conn, tmp_path,
                                                                           roster_file):
    make_student(conn, "_cyc_a")
    gh = SolvedGitHub(tmp_path)
    fake = both_agents()
    before = fingerprint(conn, ["_cyc_a"])
    for flags in ({"with_llm": True}, {"with_llm": True, "with_code_agent": True}):
        code, log = hourly(conn, tmp_path, roster_file, gh, fake=fake, env={}, **flags)
        assert code == rh.EXIT_REFUSED == 4, log
        assert "REFUSED: --with-llm needs LLM_PROVIDER to be set" in log
        assert "Nothing was collected, graded or posted in this run" in log
    code, log = hourly(conn, tmp_path, roster_file, gh, fake=fake, env={"LLM_PROVIDER": "  "},
                       with_llm=True)
    assert code == 4 and "LLM_PROVIDER" in log
    assert gh.collect_calls == [] and fake.call_count == 0
    # no grading was skipped: none ran
    assert fingerprint(conn, ["_cyc_a"]) == before


def test_run_hourly_refuses_the_code_agent_without_with_llm(conn, tmp_path, roster_file):
    make_student(conn, "_cyc_a")
    gh = SolvedGitHub(tmp_path)
    code, log = hourly(conn, tmp_path, roster_file, gh, fake=both_agents(), with_code_agent=True)
    assert code == 4 and "--with-code-agent runs only together with --with-llm" in log
    assert gh.collect_calls == []


def test_run_hourly_with_a_provider_set_runs_both_agents(conn, tmp_path, roster_file):
    make_student(conn, "_cyc_a")
    gh = SolvedGitHub(tmp_path)
    code, log = hourly(conn, tmp_path, roster_file, gh, fake=both_agents(), with_llm=True,
                       with_code_agent=True)
    assert code == 0, log
    assert "agents ON + Code Agent" in log and "code_agent stored trace" in log
    assert len(verdicts(conn, "_cyc_a")) == 1


# --- flags off: nothing new ----------------------------------------------------------------------

def test_flags_off_write_no_agent_trace_and_print_nothing_about_agents(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = SolvedGitHub(tmp_path)
    fake = both_agents()
    result, lines = cycle(conn, gh, "_cyc_a", fake=fake)
    assert result.exit_code == 0 and result.students[0].graded == 1
    assert fake.call_count == 0 and verdicts(conn, "_cyc_a") == []
    assert coach_traces(conn, "_cyc_a") == []
    assert not any("llm" in line.lower() for line in lines)


def test_feedback_only_never_runs_the_code_agent(conn, tmp_path):
    make_student(conn, "_cyc_a")
    # all checks pass: nothing for the Feedback Agent
    gh = SolvedGitHub(tmp_path)
    fake = both_agents()
    result, lines = cycle(conn, gh, "_cyc_a", fake=fake, with_llm=True)
    assert result.exit_code == 0 and fake.call_count == 0
    assert verdicts(conn, "_cyc_a") == [] and coach_traces(conn, "_cyc_a") == []
    assert "code_agent stored" not in text_of(lines) and "Code Agent off" in text_of(lines)
    failing = UnsolvedGitHub(tmp_path / "u")
    make_student(conn, "_cyc_b")
    fake2 = both_agents()
    # a failing commit: Feedback only
    cycle(conn, failing, "_cyc_b", fake=fake2, with_llm=True)
    assert len(coach_traces(conn, "_cyc_b")) == 1 and verdicts(conn, "_cyc_b") == []
    assert not prompts_of_code_agent(fake2)


# --- both agents ---------------------------------------------------------------------------------

def test_a_passing_commit_gets_one_code_agent_trace_and_a_second_cycle_makes_no_call(
        conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = SolvedGitHub(tmp_path)
    fake = both_agents()
    ledger = UsageLedger()

    first, lines = cycle(conn, gh, "_cyc_a", fake=fake, ledger=ledger, with_llm=True,
                         with_code_agent=True)

    assert first.exit_code == 0 and first.students[0].graded == 1 and first.students[0].ok
    ((trace_id, payload),) = verdicts(conn, "_cyc_a")
    cur = conn.cursor()
    cur.execute("SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a'")
    assert payload["attempt_id"] == cur.fetchone()[0] and payload["commit_sha"] == "a" * 40
    # weather_etl: no idiomatic
    assert payload["criteria"] == ["correctness", "approach", "readability"]
    assert payload["scores"]["idiomatic"] is None and payload["scope"]["mode"] == "gap_lines"
    assert payload["prompt_version"] == "v3" and payload["rejected"] is False
    assert f"code_agent stored trace {trace_id}" in text_of(lines)
    # a passing commit: no feedback
    assert coach_traces(conn, "_cyc_a") == []
    calls = fake.judge_count
    assert calls == 1 and ledger.day_total() >= 1
    (code_prompt,) = prompts_of_code_agent(fake)
    assert "Idiomatic Spark/SQL" not in code_prompt and "## What you are shown" in code_prompt

    second, _ = cycle(conn, gh, "_cyc_a", fake=fake, ledger=ledger, with_llm=True,
                      with_code_agent=True)
    assert second.exit_code == 0 and second.students[0].graded == 0
    assert len(verdicts(conn, "_cyc_a")) == 1 and fake.judge_count == calls     # nothing, no call


def test_one_attempt_two_commits_each_agent_writes_one_trace_for_its_commit(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = TwoCommitGitHub(tmp_path)
    fake = both_agents()
    ledger = UsageLedger()

    result, lines = cycle(conn, gh, "_cyc_a", fake=fake, ledger=ledger, with_llm=True,
                          with_code_agent=True)

    assert result.exit_code == 0 and result.students[0].graded == 2, text_of(lines)
    ((_, coach),) = coach_traces(conn, "_cyc_a")
    ((_, verdict),) = verdicts(conn, "_cyc_a")
    assert coach["commit_sha"] == SHA_FAIL and verdict["commit_sha"] == SHA_PASS
    assert coach["attempt_id"] == verdict["attempt_id"]
    # the failing commit never reached the Code Agent, and says why
    assert "code_agent skipped, " in text_of(lines) and "check(s) failed" in text_of(lines)
    assert "a failing commit gets the Feedback Agent, never the Code Agent" in text_of(lines)
    assert len(prompts_of_code_agent(fake)) == 1                         # only the passing commit
    calls = fake.judge_count

    again, _ = cycle(conn, gh, "_cyc_a", fake=fake, ledger=ledger, with_llm=True,
                     with_code_agent=True)
    assert again.students[0].graded == 0 and fake.judge_count == calls
    assert len(coach_traces(conn, "_cyc_a")) == 1 and len(verdicts(conn, "_cyc_a")) == 1


def test_a_failing_commit_does_not_reach_the_code_agent(conn, tmp_path):
    make_student(conn, "_cyc_a")
    fake = both_agents()
    result, lines = cycle(conn, UnsolvedGitHub(tmp_path), "_cyc_a", fake=fake, with_llm=True,
                          with_code_agent=True)
    assert result.exit_code == 0
    assert verdicts(conn, "_cyc_a") == [] and not prompts_of_code_agent(fake)
    assert "code_agent skipped, " in text_of(lines) and "check(s) failed" in text_of(lines)
    assert len(coach_traces(conn, "_cyc_a")) == 1                        # the Feedback Agent did


def test_no_judgeable_file_or_no_extractable_lines_is_skipped_with_a_reason(
        conn, tmp_path, monkeypatch):
    make_student(conn, "_cyc_a")
    gh = SolvedGitHub(tmp_path)
    fake = both_agents()
    real = rc.agents_pipeline.load_assignment_inputs
    monkeypatch.setattr(rc.agents_pipeline, "load_assignment_inputs",
                        lambda cur, aid: (real(cur, aid)[0], None))
    _, lines = cycle(conn, gh, "_cyc_a", fake=fake, with_llm=True, with_code_agent=True)
    assert ("code_agent skipped, the assignment has no judgeable file (no file_path)"
            in text_of(lines))
    monkeypatch.undo()
    make_student(conn, "_cyc_b")
    monkeypatch.setattr(rc.scope_mod, "scope_spec_for_attempt",
                        lambda cur, aid: (_ for _ in ()).throw(rc.scope_mod.ScopeUnavailable("no")))
    _, lines = cycle(conn, SolvedGitHub(tmp_path / "b"), "_cyc_b", fake=fake, with_llm=True,
                     with_code_agent=True)
    assert "code_agent skipped, gap lines cannot be extracted: no" in text_of(lines)
    assert verdicts(conn, "_cyc_a") == [] and verdicts(conn, "_cyc_b") == []
    assert fake.call_count == 0


def test_a_stub_left_unchanged_has_no_gap_lines_and_is_skipped(conn, tmp_path):
    """All checks 'pass' only if the file is solved, so simulate an unextractable file directly: the
    student's file equals the released one (nothing to judge)."""
    make_student(conn, "_cyc_a")
    cur = conn.cursor()
    cur.execute("SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a'")
    (attempt_id,) = cur.fetchone()
    insert_commit(conn, "_cyc_a")
    gh = FakeGitHub(tmp_path)
    master = (gh.root / "weather_etl" / "transform.py").read_text(encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / "weather_etl").mkdir(parents=True)
    all_gaps = ["g_tf_clean", "g_tf_convert", "g_tf_timestamp"]
    (repo / "weather_etl" / "transform.py").write_text(
        render_student_file(master, all_gaps), encoding="utf-8")
    lines: list[str] = []
    fake = both_agents()
    hook = rc.AgentsHook(fake, rc.CallBudget(max_calls=10, day_cap=20, ledger=UsageLedger()),
                         Memory(), lines.append, 20, code_agent=True)
    pending = gc.Pending(attempt_id, "_cyc_a", "weather_etl", ASSIGNMENT, 1, "a" * 40,
                         datetime.now(UTC), "o", "r")
    hook.bind(conn)(pending, repo, SimpleNamespace(tests_total=5, tests_passed=5, frozen=True,
                                                   status="ok"))
    assert "code_agent skipped, gap lines cannot be extracted" in text_of(lines)
    assert "differs from the released file" in text_of(lines) and fake.call_count == 0


# --- the size cap --------------------------------------------------------------------------------

def test_judged_text_above_the_cap_is_skipped_with_a_reason_and_no_call(conn, tmp_path):
    make_student(conn, "_cyc_a")
    fake = both_agents()
    result, lines = cycle(conn, SolvedGitHub(tmp_path), "_cyc_a", fake=fake, with_llm=True,
                          with_code_agent=True, code_prompt_cap=10)
    assert result.exit_code == 0 and result.students[0].ok
    assert "code_agent skipped, the judged text is " in text_of(lines)
    assert "characters, above the cap of 10" in text_of(lines)
    assert verdicts(conn, "_cyc_a") == [] and fake.call_count == 0


def test_the_proposed_cap_is_well_above_every_excerpt_in_the_curriculum():
    from agents import scope
    from assessment.gap_parser import parse_master
    biggest = 0
    for project, stages in (("weather_etl", ("extract", "transform", "load", "quality")),
                            ("sales_analyzer", ("ingest", "clean", "aggregate", "load"))):
        for stage in stages:
            path = ROOT / "curriculum" / "master" / project / project / f"{stage}.py"
            master = path.read_text(encoding="utf-8")
            gaps = parse_master(path)
            excerpt = scope.judged_excerpt(scope.ScopeSpec(master, tuple(g.gap_id for g in gaps)),
                                           render_student_file(master, []))
            biggest = max(biggest, len(excerpt.text))
    assert biggest > 0 and 4 * biggest <= rc.DEFAULT_CODE_PROMPT_CAP            # room to spare


def test_grade_skips_above_the_cap_by_itself(tmp_path):
    path = tmp_path / "a.py"
    path.write_text("x = 1\n" * 100, encoding="utf-8")
    fake = both_agents()
    with pytest.raises(code_agent.SubmissionSkipped, match="above the cap of 50"):
        code_agent.grade(SimpleNamespace(), "s", {"assignment_id": "a", "task": "t"}, str(path),
                         llm_client=fake, profile_snapshot={}, max_prompt_chars=50)
    assert fake.call_count == 0


# --- calls: both agents, one budget --------------------------------------------------------------

def test_both_agents_draw_on_the_same_run_cap(conn, tmp_path):
    """Run cap 2: the Feedback Agent on the failing commit reserves 2 and uses 1; the Code Agent
    on the passing one then needs 2 more, 1 + 2 > 2, and is refused before any call."""
    make_student(conn, "_cyc_a")
    fake = both_agents()
    result, lines = cycle(conn, TwoCommitGitHub(tmp_path), "_cyc_a", fake=fake, with_llm=True,
                          with_code_agent=True, llm_run_cap=2)
    assert result.exit_code == 0 and result.students[0].graded == 2
    assert len(coach_traces(conn, "_cyc_a")) == 1 and verdicts(conn, "_cyc_a") == []
    assert "code_agent skipped, the run call cap is reached" in text_of(lines)
    assert not prompts_of_code_agent(fake)


def test_the_daily_cap_stops_the_code_agent_and_the_cycle_finishes(conn, tmp_path):
    make_student(conn, "_cyc_a")
    fake = both_agents()
    ledger = UsageLedger()
    ledger.add({"some-model": 20})
    result, lines = cycle(conn, SolvedGitHub(tmp_path), "_cyc_a", fake=fake, ledger=ledger,
                          with_llm=True, with_code_agent=True)
    assert result.exit_code == 0 and result.students[0].ok
    assert result.students[0].features == "written"
    assert fake.call_count == 0 and verdicts(conn, "_cyc_a") == []
    assert "code_agent skipped, the day call cap is reached (20/20)" in text_of(lines)
    assert "cycle done: 1 ok, 0 failed" in text_of(lines)


def test_the_cap_holds_at_the_provider_handler_when_the_provider_keeps_failing(conn, tmp_path):
    """The budget counts answers; a failing provider walks the gateway's model chain without
    one. The handler ceiling (cap 1) must stop that at one real call."""
    make_student(conn, "_cyc_a")
    down = fl.FakeLLM([fl.provider_error(sticky=True)])
    with down.installed():                                  # real gateway, fake handlers
        result, lines = cycle(conn, UnsolvedGitHub(tmp_path), "_cyc_a", fake=gateway,
                              with_llm=True, with_code_agent=True, llm_run_cap=1)
    assert result.exit_code == 0 and result.students[0].ok
    assert down.call_count <= 1
    assert "real provider call(s) this run" in text_of(lines)


def test_the_per_commit_maximum_and_the_plan_say_which_agent_costs_what():
    assert rc.FEEDBACK_MAX_CALLS == 4 and rc.CODE_AGENT_MAX_CALLS == 2
    assert (rc.DEFAULT_LLM_RUN_CAP, rc.DEFAULT_LLM_DAILY_CAP) == (10, 20)     # unchanged (CONFIRM)


# --- failures never fail the grading -------------------------------------------------------------

def test_a_failing_code_agent_never_fails_the_grading(conn, tmp_path, monkeypatch):
    make_student(conn, "_cyc_a")

    def boom(*args, **kwargs):
        raise RuntimeError("the code agent exploded")

    monkeypatch.setattr(rc.code_agent, "grade", boom)
    result, lines = cycle(conn, SolvedGitHub(tmp_path), "_cyc_a", fake=both_agents(), with_llm=True,
                          with_code_agent=True)
    assert result.exit_code == 0 and result.students[0].ok and result.students[0].graded == 1
    assert result.students[0].features == "written"
    assert any("AGENT ERROR" in line and "the code agent exploded" in line for line in lines)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM test_results WHERE attempt_id IN"
                " (SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a')")
    assert cur.fetchone()[0] > 0


def test_a_sql_error_inside_the_code_agent_is_rolled_back_to_its_own_savepoint(conn, tmp_path,
                                                                                 monkeypatch):
    make_student(conn, "_cyc_a")

    def bad_sql(mem, student, assignment, path, *, conn, **kwargs):
        conn.cursor().execute("SELECT * FROM a_table_that_does_not_exist")

    monkeypatch.setattr(rc.code_agent, "grade", bad_sql)
    result, lines = cycle(conn, SolvedGitHub(tmp_path), "_cyc_a", fake=both_agents(), with_llm=True,
                          with_code_agent=True)
    assert result.exit_code == 0 and result.students[0].ok and result.students[0].graded == 1
    assert any("AGENT ERROR" in line for line in lines)


def test_an_invalid_judge_answer_is_a_skipped_line_not_an_error(conn, tmp_path):
    make_student(conn, "_cyc_a")
    junk = fl.FakeLLM(default=lambda prompt: "not json at all")
    result, lines = cycle(conn, SolvedGitHub(tmp_path), "_cyc_a", fake=junk, with_llm=True,
                          with_code_agent=True)
    assert result.exit_code == 0 and verdicts(conn, "_cyc_a") == []
    assert "code_agent skipped, the judge's answer was not valid twice" in text_of(lines)
    assert not any("AGENT ERROR" in line for line in lines)


# --- the template push ---------------------------------------------------------------------------

def test_the_template_push_reaches_no_agent_but_the_students_own_commit_does(conn, tmp_path):
    conn.cursor().execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')",
                          (TPL_STUDENT, TPL_STUDENT))
    attempt_id, template, first, _second = delivered(conn.cursor())
    master = (ROOT / "curriculum/master/weather_etl/weather_etl/extract.py").read_text("utf-8")
    repo = tmp_path / "repo"
    (repo / "weather_etl").mkdir(parents=True)
    (repo / "weather_etl" / "extract.py").write_text(render_student_file(master, []),
                                                     encoding="utf-8")
    result = SimpleNamespace(tests_total=2, tests_passed=2, frozen=True, status="ok")
    lines: list[str] = []
    fake = both_agents()
    hook = rc.AgentsHook(fake, rc.CallBudget(max_calls=20, day_cap=40, ledger=UsageLedger()),
                         Memory(), lines.append, 40, code_agent=True)

    def pending(sha):
        cur = conn.cursor()
        cur.execute("SELECT committed_at FROM raw_commits WHERE sha = %s", (sha,))
        return gc.Pending(attempt_id, TPL_STUDENT, "weather_etl", TPL_ASG, 2, sha,
                          cur.fetchone()[0], "o", "r")

    hook.bind(conn)(pending(template), repo, result)
    assert fake.call_count == 0 and verdicts(conn, TPL_STUDENT) == []
    assert coach_traces(conn, TPL_STUDENT) == []
    assert "template push, no agent" in text_of(lines)

    hook.bind(conn)(pending(first), repo, result)                        # the contrast
    assert len(verdicts(conn, TPL_STUDENT)) == 1 and len(prompts_of_code_agent(fake)) == 1
    assert verdicts(conn, TPL_STUDENT)[0][1]["commit_sha"] == first


# --- the verdict is never posted and read by nothing ---------------------------------------------

def test_the_posted_comment_holds_no_code_agent_text(conn, tmp_path, roster_file, monkeypatch):
    make_student(conn, "_cyc_a")
    conn.cursor().execute("UPDATE students SET github_username = 'llm-student'"
                          " WHERE student_id = '_cyc_a'")
    monkeypatch.setenv(pf.GITHUB_WRITE_ENV_VAR, "1")
    issues = RecordingIssues()
    code, log = hourly(conn, tmp_path, roster_file, SolvedGitHub(tmp_path), fake=both_agents(),
                       issues=issues, with_llm=True, with_code_agent=True)
    assert code == 0, log
    ((_, verdict),) = verdicts(conn, "_cyc_a")
    assert verdict["feedback_for_student"] == SECRET                     # it IS stored ...
    # ... and a comment WAS posted
    (body,) = issues.bodies
    assert SECRET not in body and "More detail" not in body
    assert verdict["evidence"]["approach"][0]["quote"] not in body
    cur = conn.cursor()
    cur.execute("SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a'")
    from agents.pipeline import find_feedback_addendum
    assert find_feedback_addendum(cur, cur.fetchone()[0], "a" * 40) is None


def snapshot(conn, cur, sid, attempt_id, sha):
    from agents import feedback_agent as fa
    from assessment.diagnose import diagnose
    from features import compute_features as cf

    profile = Memory().rebuild_from_traces(sid, conn=conn)
    return {
        "features": json.dumps(cf.compute_for_student(cur, sid), sort_keys=True, default=str),
        "mastery": json.dumps(profile["mastery"], sort_keys=True, default=str),
        "weaknesses": json.dumps(profile["weaknesses"], sort_keys=True, default=str),
        "diagnosis": repr(diagnose(cur, attempt_id)),
        "posted_text": pf.build_feedback(cur, attempt_id, sha).markdown,
        "feedback_input": repr(fa.gather_input(cur, attempt_id, sha, profile={"mastery": {}},
                                               candidates=[])),
        "to_post": pf.recent_unposted(cur, sid, 48),
    }


def test_a_stored_verdict_changes_no_feature_mastery_diagnosis_feedback_text_or_post_list(
        conn, tmp_path):
    from scripts.prove_event_sourcing import prove
    make_student(conn, "_cyc_a")
    gh = SolvedGitHub(tmp_path)
    cycle(conn, gh, "_cyc_a", fake=both_agents())                         # graded, flags OFF
    cur = conn.cursor()
    cur.execute("SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a'")
    (attempt_id,) = cur.fetchone()
    assert verdicts(conn, "_cyc_a") == []
    before = snapshot(conn, cur, "_cyc_a", attempt_id, "a" * 40)

    # now the hook runs on that graded commit with the Code Agent ON (the only way to store a
    # verdict through the wired path), and the file is the one the grader saw
    repo = tmp_path / "repo"
    (repo / "weather_etl").mkdir(parents=True)
    (repo / "weather_etl" / "transform.py").write_text(gh.solved, encoding="utf-8")
    lines: list[str] = []
    budget = rc.CallBudget(max_calls=10, day_cap=20, ledger=UsageLedger())
    hook = rc.AgentsHook(both_agents(), budget, Memory(), lines.append, 20, code_agent=True)
    pending = gc.Pending(attempt_id, "_cyc_a", "weather_etl", ASSIGNMENT, 1, "a" * 40,
                         datetime.now(UTC), "o", "r")
    hook.bind(conn)(pending, repo, SimpleNamespace(tests_total=5, tests_passed=5, frozen=True,
                                                   status="ok"))
    ((_, payload),) = verdicts(conn, "_cyc_a")
    assert payload["scores"]["approach"] == 2 and payload["rejected"] is False

    assert snapshot(conn, cur, "_cyc_a", attempt_id, "a" * 40) == before
    proof = prove(conn)                                                   # Beat 7
    assert [d for d in proof.differences if d.student_id == "_cyc_a"] == []
    assert proof.rows_after_wipe == 0


# --- plan mode -----------------------------------------------------------------------------------

def test_plan_mode_lists_what_would_reach_the_hook_and_touches_nothing(conn, tmp_path):
    make_student(conn, "_cyc_a")
    insert_commit(conn, "_cyc_a")                      # collected earlier, not graded yet
    gh = SolvedGitHub(tmp_path)
    fake = both_agents()
    ledger = UsageLedger()
    ledger.add({"m": 7})
    before = fingerprint(conn, ["_cyc_a"])
    lines: list[str] = []

    result = rc.run_cycle(roster_for("_cyc_a"), student="_cyc_a", conn=conn, plan=True,
                          with_llm=True, with_code_agent=True, collect=gh.collect,
                          checkout=gh.checkout, out=lines.append, llm=fake, ledger=ledger,
                          env=PROVIDER_ENV)

    text = text_of(lines)
    assert result.exit_code == 0 and "PLAN (read-only" in text
    assert "--with-llm ON, --with-code-agent ON" in text and "LLM_PROVIDER openai" in text
    assert "used today 7" in text and "run cap 10, daily cap 20" in text
    assert "a FAILING commit -> Feedback Agent, at most 4 budgeted calls" in text
    assert "all-PASSING commit -> Code Agent, at most 2" in text
    assert "never both on one commit" in text
    assert "weather_etl_transform attempt 1  " + "a" * 10 in text
    assert "a check fails       -> Feedback Agent (<= 4 calls)" in text
    assert "all checks pass     -> Code Agent (<= 2 calls), if the gap lines of weather_etl/" \
           "transform.py can be extracted (3 hidden gap(s); criteria: correctness, approach, " \
           "readability)" in text
    assert "1 stored commit(s) would reach the hook" in text
    assert "not listed: commits still on GitHub and not yet collected" in text
    assert gh.collect_calls == [] and gh.checkout_calls == [] and fake.call_count == 0
    assert fingerprint(conn, ["_cyc_a"]) == before                       # nothing written
    assert ledger.day_total() == 7                                       # not even the ledger


def test_plan_mode_with_the_flags_off_says_no_agent_and_refuses_a_lone_code_agent(conn, tmp_path):
    make_student(conn, "_cyc_a")
    insert_commit(conn, "_cyc_a")
    lines: list[str] = []
    rc.run_cycle(roster_for("_cyc_a"), student="_cyc_a", conn=conn, plan=True, out=lines.append,
                 ledger=UsageLedger(), env={})
    assert "graded, then no agent (--with-llm is off)" in text_of(lines)
    assert "LLM_PROVIDER NOT SET" in text_of(lines)
    refused: list[str] = []
    result = rc.run_cycle(roster_for("_cyc_a"), conn=conn, plan=True, with_code_agent=True,
                          out=refused.append)
    assert result.exit_code == rc.EXIT_REFUSED and "REFUSED" in text_of(refused)


def test_plan_mode_opens_a_read_only_session():
    source = (ROOT / "scripts" / "run_cycle.py").read_text(encoding="utf-8")
    plan = source[source.index("def _plan_report"):source.index("def _code_ready")]
    assert "set_session(readonly=True)" in plan and "rollback()" in plan
    for verb in ("INSERT", "UPDATE", "DELETE", ".commit("):
        assert verb not in plan


# --- the report ----------------------------------------------------------------------------------

def test_the_report_marks_working_code_the_judge_finds_weak_and_is_labelled(conn, tmp_path):
    for sid in ("_cyc_a", "_cyc_b", "_cyc_c"):
        make_student(conn, sid)
    cycle(conn, SolvedGitHub(tmp_path / "a"), "_cyc_a", fake=both_agents(approach=2),
          with_llm=True, with_code_agent=True)
    cycle(conn, SolvedGitHub(tmp_path / "b"), "_cyc_b", fake=both_agents(approach=4),
          with_llm=True, with_code_agent=True)
    cycle(conn, SolvedGitHub(tmp_path / "c"), "_cyc_c", fake=both_agents(approach=2, quote="nope"),
          with_llm=True, with_code_agent=True)
    cur = conn.cursor()

    mine = {r["student"]: r for r in report.rows(cur, limit=500)
            if r["student"].startswith("_cyc_")}
    assert mine["_cyc_a"]["marked"] is True and mine["_cyc_a"]["tests"] == (5, 5)
    assert mine["_cyc_b"]["marked"] is False                             # approach 4: not weak
    assert mine["_cyc_c"]["rejected"] is True
    assert mine["_cyc_a"]["scores"]["idiomatic"] is None and mine["_cyc_a"]["commit"] == "a" * 10
    assert [r["student"] for r in report.rows(cur, student="_cyc_a")] == ["_cyc_a"]
    assert all(r["rejected"] for r in report.rows(cur, limit=500, rejected=True)
               if r["student"].startswith("_cyc_"))

    lines = report.render([mine["_cyc_a"], mine["_cyc_b"], mine["_cyc_c"]], "vdel_test")
    label = "*** UNMEASURED JUDGE, INTERNAL USE ONLY, NEVER SHOWN TO STUDENTS ***"
    assert lines[0] == lines[-1] == label
    marked = [ln for ln in lines if ln.rstrip().endswith("tests pass, approach <= 2")]
    # _cyc_a and the rejected _cyc_c (approach 2, tests pass)
    assert len(marked) == 2
    assert any("_cyc_a" in ln for ln in marked) and not any("_cyc_b" in ln for ln in marked)
    assert "judge's OPINION" in "\n".join(lines)


def test_the_report_copes_with_a_verdict_that_has_no_ids_and_writes_nothing(conn):
    conn.cursor().execute("INSERT INTO students VALUES ('_rep','_rep','vdel-2026')")
    Memory().log_trace("_rep", "code_agent", "verdict",
                       {"scores": {"llm_correctness_opinion": 2, "approach": 2}, "evidence": {}},
                       conn=conn)
    cur = conn.cursor()
    before = fingerprint(conn, ["_rep"])
    (row,) = report.rows(cur, student="_rep")
    assert row["attempt_id"] is None and row["tests"] is None and row["marked"] is False
    line = next(ln for ln in report.render([row], "vdel_test") if "_rep" in ln)
    assert " - " in line
    assert fingerprint(conn, ["_rep"]) == before


def test_the_report_script_is_read_only_by_construction():
    import re
    source = (ROOT / "scripts" / "code_agent_report.py").read_text(encoding="utf-8")
    code = re.sub(r'"""(?:.|\n)*?"""', "", source)
    assert "readonly=True" in code and "rollback()" in code
    for forbidden in (r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\.commit\(", r"log_trace",
                      r"requests", r"system\.llm", r"agents\."):
        assert not re.search(forbidden, code), forbidden
    assert "UNMEASURED JUDGE, INTERNAL USE ONLY, NEVER SHOWN TO STUDENTS" in source


def test_nothing_but_the_report_the_agent_and_the_benchmarks_read_the_verdict_payload():
    import re
    allowed = {"agents/code_agent.py", "scripts/code_agent_report.py", "scripts/run_cycle.py",
               "agents/echo_agent.py", "memory/memory.py", "benchmark/run_real_benchmark.py"}
    found = set()
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", ".venv", "venv/", "build/")) or "site-packages" in rel:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"""['"]verdict['"]""", text) or "find_verdict" in text:
            found.add(rel)
    assert found <= allowed, sorted(found - allowed)


def test_calling_the_hook_again_for_the_same_commit_makes_no_second_call(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = SolvedGitHub(tmp_path)
    cycle(conn, gh, "_cyc_a", fake=both_agents())                         # graded, flags off
    cur = conn.cursor()
    cur.execute("SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a'")
    (attempt_id,) = cur.fetchone()
    repo = tmp_path / "repo"
    (repo / "weather_etl").mkdir(parents=True)
    (repo / "weather_etl" / "transform.py").write_text(gh.solved, encoding="utf-8")
    lines: list[str] = []
    fake = both_agents()
    hook = rc.AgentsHook(fake, rc.CallBudget(max_calls=10, day_cap=20, ledger=UsageLedger()),
                         Memory(), lines.append, 20, code_agent=True)
    pending = gc.Pending(attempt_id, "_cyc_a", "weather_etl", ASSIGNMENT, 1, "a" * 40,
                         datetime.now(UTC), "o", "r")
    result = SimpleNamespace(tests_total=5, tests_passed=5, frozen=True, status="ok")

    hook.bind(conn)(pending, repo, result)
    hook.bind(conn)(pending, repo, result)

    assert len(verdicts(conn, "_cyc_a")) == 1 and len(prompts_of_code_agent(fake)) == 1
    assert "code_agent already judged this commit" in text_of(lines) and "no call" in text_of(lines)


def test_a_failing_step_is_rolled_back_alone_and_the_other_steps_trace_survives(conn):
    conn.cursor().execute("INSERT INTO students VALUES ('_sp','_sp','vdel-2026')")

    def writes_a_trace(cur):
        return Memory().log_trace("_sp", "system", "commit", {"note": "first step"},
                                  conn=cur.connection)

    def breaks_in_sql(cur):
        Memory().log_trace("_sp", "system", "commit", {"note": "half of the second step"},
                           conn=cur.connection)
        cur.execute("SELECT * FROM a_table_that_does_not_exist")

    trace_id, error = rc.AgentsHook._guarded(conn, "feedback", writes_a_trace)
    assert error is None and trace_id
    _, error = rc.AgentsHook._guarded(conn, "code_agent", breaks_in_sql)
    assert error is not None                                              # reported, not raised
    cur = conn.cursor()
    cur.execute("SELECT payload->>'note' FROM traces WHERE student_id = '_sp' ORDER BY trace_id")
    # the half-written one is gone
    assert [r[0] for r in cur.fetchall()] == ["first step"]


def test_run_hourly_names_the_provider_and_warns_about_a_second_key_without_printing_a_key(
        conn, tmp_path, roster_file):
    make_student(conn, "_cyc_a")
    env = {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-SECRET-ONE",
           "GOOGLE_API_KEY": "sk-SECRET-TWO"}
    code, log = hourly(conn, tmp_path, roster_file, SolvedGitHub(tmp_path), fake=both_agents(),
                       env=env, with_llm=True)
    assert code == 0, log
    assert "agents: provider openai; provider keys present: GOOGLE_API_KEY, OPENAI_API_KEY" in log
    assert "WARNING: more than one provider key is present" in log
    assert "sk-SECRET" not in log
    one = {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-SECRET-ONE"}
    code, log = hourly(conn, tmp_path, roster_file, SolvedGitHub(tmp_path / "2"),
                       fake=both_agents(), env=one, with_llm=True)
    assert "provider keys present: OPENAI_API_KEY" in log and "WARNING" not in log
