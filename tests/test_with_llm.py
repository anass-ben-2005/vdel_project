"""D-099 -- `--with-llm` in run_cycle / run_hourly, with the FAKE provider (agents/fake_llm.py).

No live call, no network, no GitHub write: the gateway is `FakeLLM`, GitHub is the fake layer of
tests/test_run_cycle.py and a recording issue client. Everything else is the real code: the real
grader (a pytest subprocess on the UNSOLVED file, so there are failing checks to explain), the real
agents, the real Memory. One rolled-back transaction per test, on the throwaway test database.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents import fake_llm as fl
from agents import pipeline as agents_pipeline
from agents.budget import UsageLedger
from agents.code_agent import CRITERIA
from assessment.gap_parser import render_student_file
from memory.memory import Memory
from scripts import grade_collected as gc
from scripts import post_feedback as pf
from scripts import run_cycle as rc
from scripts import run_hourly as rh
from scripts.prove_event_sourcing import prove
from scripts.seed_data import roster_repo_for
from system import db
from tests.support import vdel_dir_state
from tests.test_run_cycle import ASSIGNMENT, FakeGitHub, insert_commit, make_student, roster_for
from tests.test_template_commit import ASG as TPL_ASG
from tests.test_template_commit import S as TPL_STUDENT
from tests.test_template_commit import delivered

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

USER = "llm-student"
WINDOWS = Path(__file__).resolve().parent.parent / "scripts" / "windows"
SUMMARY = "Two checks stopped on NotImplementedError, so start with the TODO parts of your file."


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(pf.GITHUB_WRITE_ENV_VAR, raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token-value")


@pytest.fixture(autouse=True)
def no_live_provider(monkeypatch, tmp_path):
    """No test in this module can reach a real provider, even one that forgets `llm=`.

    Why it exists: the old `test_with_llm_is_reported_as_not_wired` called
    `run_cycle(with_llm=True)` with no fake; harmless while the flag was a stub, a LIVE billed
    call once it was wired (2 calls were made and recorded in .vdel/llm_usage.json). Every
    provider handler is replaced by one that raises; `FakeLLM.installed()` swaps its own in and
    restores these. The default ledger file is redirected to a temp path so nothing is written
    under the repository's .vdel/."""
    from system import llm as gateway

    def blocked(*args, **kwargs):
        raise AssertionError("LIVE PROVIDER CALL attempted in a test")

    for provider in list(gateway._PROVIDER_HANDLERS):
        monkeypatch.setitem(gateway._PROVIDER_HANDLERS, provider, blocked)
    monkeypatch.setattr(rc, "DEFAULT_LEDGER_PATH", tmp_path / "default_llm_usage.json")


@pytest.fixture
def conn():
    try:
        c = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    yield c
    c.rollback()
    c.close()


class UnsolvedGitHub(FakeGitHub):
    """Like the cycle's fake, but the checkout holds a half-done file: two gaps are still stubs
    (so there are failing checks to explain) and the timestamp gap is solved (so something was
    attempted and mastery moves; a file with nothing attempted records no mastery at all)."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        master = (self.root / "weather_etl" / "transform.py").read_text(encoding="utf-8")
        self.unsolved = render_student_file(master, hide_gap_ids=["g_tf_clean", "g_tf_convert"])

    def checkout(self, owner, repo, sha, dest):
        super().checkout(owner, repo, sha, dest)
        (Path(dest) / "weather_etl" / "transform.py").write_text(self.unsolved, encoding="utf-8")

    @property
    def quote(self) -> str:
        return next(line for line in self.unsolved.splitlines() if line.startswith("def "))


def scripted(quote: str, *, feedback: dict | None = None):
    """A `FakeLLM` that answers by prompt: the Code Agent's prompt holds the submission fence."""
    code = {"evidence": {c: [{"quote": quote, "why": "a stub"}] for c in CRITERIA},
            "scores": {"llm_correctness_opinion": 0, "approach": 0, "readability": 2,
                       "idiomatic": 2},
            "misconceptions": [], "feedback_for_student": "Fill in the marked parts.",
            "confidence": "high"}
    fb = feedback or {"summary": SUMMARY, "what_to_check_next": ["Read the TODO comments again."],
                      "cited_tests": [], "cited_concepts": [], "resource_id": None,
                      "confidence": "medium"}

    def answer(prompt: str) -> str:
        return json.dumps(code if "<<<BEGIN SUBMISSION>>>" in prompt else fb)
    return fl.FakeLLM(default=answer)


def cycle(conn, gh, sid, *, fake, ledger=None, out=None, **kw):
    lines = [] if out is None else out
    result = rc.run_cycle(roster_for(sid), student=sid, conn=conn, collect=gh.collect,
                          checkout=gh.checkout, out=lines.append, llm=fake,
                          ledger=ledger if ledger is not None else UsageLedger(), **kw)
    return result, lines


def coach_traces(conn, sid):
    cur = conn.cursor()
    cur.execute("SELECT trace_id, payload FROM traces WHERE student_id = %s"
                " AND actor = 'coach' AND kind = 'intervention' ORDER BY trace_id", (sid,))
    return cur.fetchall()


def trace_kinds(conn, sid) -> Counter:
    cur = conn.cursor()
    cur.execute("SELECT actor, kind FROM traces WHERE student_id = %s", (sid,))
    return Counter(cur.fetchall())


# --- OFF is the default and writes nothing ---------------------------------------------------

def test_off_by_default_calls_no_agent_and_writes_no_coach_trace(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)
    fake = scripted(gh.quote)

    result, lines = cycle(conn, gh, "_cyc_a", fake=fake)             # with_llm not given

    assert result.exit_code == 0 and result.students[0].graded == 1
    assert fake.call_count == 0 and coach_traces(conn, "_cyc_a") == []
    assert not any("llm" in line.lower() for line in lines)          # not even a mention
    assert ("coach", "intervention") not in trace_kinds(conn, "_cyc_a")


def test_the_defaults_are_off_and_ten_and_twenty():
    import argparse
    parser = argparse.ArgumentParser()
    rc.add_llm_arguments(parser)
    args = parser.parse_args([])
    assert (args.with_llm, args.llm_run_cap, args.llm_daily_cap) == (False, 10, 20)
    assert (rc.DEFAULT_LLM_RUN_CAP, rc.DEFAULT_LLM_DAILY_CAP) == (10, 20)
    for fn in (rc.run_cycle, rh.run):
        import inspect
        assert inspect.signature(fn).parameters["with_llm"].default is False


def test_the_scheduled_task_command_is_unchanged():
    """The hourly task runs `python -m scripts.run_hourly` with no switch unless it was registered
    with -WithLlm (D-104), a switch of register_task.ps1 that is off by default: nothing in the
    files that build the command turns the agents on by itself, so --with-llm can only come from
    a person."""
    task = (WINDOWS / "task_command.ps1").read_text(encoding="utf-8")
    register = (WINDOWS / "register_task.ps1").read_text(encoding="utf-8")
    for text in (task, register):
        assert "[switch]$WithLlm" in text and "[switch]$WithCodeAgent" in text
        assert "$WithLlm = $true" not in text and "$WithCodeAgent = $true" not in text
    assert "$agentArgs = " in task and "-m scripts.run_hourly$agentArgs 2>&1" in task
    assert "llm" not in (WINDOWS / "unregister_task.ps1").read_text(encoding="utf-8").lower()


# --- ON: one coach/intervention trace per (attempt, commit), none on a second cycle ----------

def test_on_writes_exactly_one_coach_intervention_trace_and_none_on_a_second_cycle(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)
    fake = scripted(gh.quote)
    ledger = UsageLedger()

    first, lines = cycle(conn, gh, "_cyc_a", fake=fake, ledger=ledger, with_llm=True)

    assert first.exit_code == 0 and first.students[0].graded == 1
    ((trace_id, payload),) = coach_traces(conn, "_cyc_a")
    assert payload["agent"] == "feedback_agent_v1" and payload["source"] == "llm"
    assert payload["commit_sha"] == "a" * 40 and payload["status"] == "ok"
    assert SUMMARY in payload["addendum_markdown"]
    assert payload["addendum_markdown"].startswith("**More detail**")
    assert "checks passed" not in payload["addendum_markdown"]       # the model's part only
    calls = fake.call_count
    assert calls == 1 and ledger.day_total() == calls               # the Feedback Agent only
    assert not any("<<<BEGIN SUBMISSION>>>" in prompt for prompt in fake.prompts)   # no Code Agent
    text = "\n".join(lines)
    assert "llm: ON, run cap 10, daily cap 20" in text
    assert f"coach trace {trace_id}" in text and "code_agent=skipped" in text

    second, _ = cycle(conn, gh, "_cyc_a", fake=fake, ledger=ledger, with_llm=True)

    assert second.exit_code == 0 and second.students[0].graded == 0   # nothing new to grade
    assert len(coach_traces(conn, "_cyc_a")) == 1                     # still one
    assert fake.call_count == calls                                   # and no new call


def test_persisting_the_same_result_twice_writes_one_row(conn, tmp_path):
    """The idempotence is the function's own, not only a consequence of grading once."""
    make_student(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)
    cycle(conn, gh, "_cyc_a", fake=scripted(gh.quote), with_llm=True)
    cur = conn.cursor()
    cur.execute("SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a'")
    (aid,) = cur.fetchone()
    from agents import feedback_agent as fa
    result = fa.build_feedback_with_llm(cur, aid, "a" * 40, scripted(gh.quote), None,
                                        profile={"mastery": {}}, candidates=[])
    assert result.used_llm
    assert agents_pipeline.persist_feedback(Memory(), cur, "_cyc_a", ASSIGNMENT, result) is None
    assert len(coach_traces(conn, "_cyc_a")) == 1


def test_a_rejected_or_failed_llm_answer_writes_no_trace(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)
    rejected = scripted(gh.quote, feedback={
        "summary": "Your code is wrong.", "what_to_check_next": ["Look again."],
        "cited_tests": [], "cited_concepts": [], "resource_id": None, "confidence": "low"})

    result, lines = cycle(conn, gh, "_cyc_a", fake=rejected, with_llm=True)

    assert result.exit_code == 0
    assert coach_traces(conn, "_cyc_a") == []                         # fell back: nothing to log
    assert any("feedback_agent=ok" in line and "no trace" in line for line in lines)


def test_mastery_and_the_event_sourcing_proof_are_unchanged_by_the_agents(conn, tmp_path):
    """Same student data, one cycle with the agents and one without: the same mastery, the same
    traces apart from the one coach/intervention row, and the wipe-and-replay still matches."""
    for sid in ("_cyc_a", "_cyc_b"):
        make_student(conn, sid)
    gh = UnsolvedGitHub(tmp_path)
    cycle(conn, gh, "_cyc_a", fake=scripted(gh.quote), with_llm=True)
    cycle(conn, gh, "_cyc_b", fake=scripted(gh.quote))

    mem = Memory()
    on, off = mem.get_profile("_cyc_a", conn=conn), mem.get_profile("_cyc_b", conn=conn)
    assert on["mastery"] == off["mastery"] and on["mastery"]          # non-empty AND equal
    assert on["weaknesses"] == off["weaknesses"]
    extra = trace_kinds(conn, "_cyc_a") - trace_kinds(conn, "_cyc_b")
    assert extra == Counter({("coach", "intervention"): 1})
    assert not (trace_kinds(conn, "_cyc_b") - trace_kinds(conn, "_cyc_a"))

    proof = prove(conn)                                               # Beat 7, on the test database
    mine = [d for d in proof.differences if d.student_id in ("_cyc_a", "_cyc_b")]
    assert mine == [] and {"_cyc_a", "_cyc_b"} <= set(proof.compared) | set(proof.created)
    assert proof.rows_after_wipe == 0


# --- the caps and the failures: the cycle always finishes ------------------------------------

def test_the_daily_cap_stops_the_calls_and_the_cycle_still_finishes(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)
    fake = scripted(gh.quote)
    ledger = UsageLedger()
    ledger.add({"some-model": 20})                                    # today's 20 are spent

    result, lines = cycle(conn, gh, "_cyc_a", fake=fake, ledger=ledger, with_llm=True)

    assert result.exit_code == 0 and result.students[0].ok and result.students[0].graded == 1
    assert fake.call_count == 0 and coach_traces(conn, "_cyc_a") == []
    assert any("calls today: 20/20" in line for line in lines)
    assert any("cycle done: 1 ok, 0 failed" in line for line in lines)
    assert result.students[0].features == "written"                   # later stages still ran


def test_the_run_cap_counts_provider_calls_and_zero_means_none(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)
    fake = scripted(gh.quote)
    result, _ = cycle(conn, gh, "_cyc_a", fake=fake, with_llm=True, llm_run_cap=0)
    assert result.exit_code == 0 and fake.call_count == 0


def test_a_failing_agent_never_fails_the_grading(conn, tmp_path, monkeypatch):
    make_student(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("the agents exploded")
    monkeypatch.setattr(rc.agents_pipeline, "run_agents_for_commit", boom)

    result, lines = cycle(conn, gh, "_cyc_a", fake=scripted(gh.quote), with_llm=True)

    assert result.exit_code == 0 and result.students[0].ok
    assert result.students[0].graded == 1 and result.students[0].features == "written"
    assert any("AGENT ERROR" in line and "the agents exploded" in line for line in lines)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM test_results WHERE attempt_id IN"
                " (SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a')")
    assert cur.fetchone()[0] > 0                                      # the grading is kept


def test_a_database_error_inside_the_agents_is_rolled_back_to_a_savepoint(conn, tmp_path,
                                                                           monkeypatch):
    """A SQL failure aborts a Postgres transaction. The hook's SAVEPOINT must undo only itself,
    or the grading (same transaction) and every later stage would die with it."""
    make_student(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)

    def bad_sql(mem, cur, *a, **k):
        cur.execute("SELECT * FROM a_table_that_does_not_exist")

    monkeypatch.setattr(rc.agents_pipeline, "persist_feedback", bad_sql)

    result, lines = cycle(conn, gh, "_cyc_a", fake=scripted(gh.quote), with_llm=True)

    assert result.exit_code == 0 and result.students[0].ok and result.students[0].graded == 1
    assert any("AGENT ERROR" in line for line in lines)


def test_a_provider_outage_is_reported_and_the_cycle_finishes(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)
    down = fl.FakeLLM([fl.provider_error(sticky=True)])

    result, lines = cycle(conn, gh, "_cyc_a", fake=down, with_llm=True)

    assert result.exit_code == 0 and result.students[0].ok
    assert coach_traces(conn, "_cyc_a") == []
    assert any(line.lstrip().startswith("llm") and "_cyc_a" in line for line in lines)


def test_a_corrupt_usage_ledger_disables_the_agents_instead_of_spending(conn, tmp_path,
                                                                        monkeypatch):
    make_student(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)
    broken = tmp_path / "llm_usage.json"
    broken.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(rc, "DEFAULT_LEDGER_PATH", broken)
    fake = scripted(gh.quote)
    lines: list[str] = []
    result = rc.run_cycle(roster_for("_cyc_a"), student="_cyc_a", conn=conn, collect=gh.collect,
                          checkout=gh.checkout, out=lines.append, llm=fake, with_llm=True)
    assert result.exit_code == 0 and fake.call_count == 0
    assert any("DISABLED" in line and "LedgerCorrupt" in line for line in lines)


def test_forgetting_the_fake_cannot_reach_a_provider_in_this_module(conn, tmp_path):
    """The regression for the live call described in `no_live_provider`: with the real gateway
    and the flag on, the call is stopped at the provider handler, the cycle still finishes, and
    nothing is written to the repository's .vdel/."""
    from system import llm as gateway
    vdel_before = vdel_dir_state()
    for handler in gateway._PROVIDER_HANDLERS.values():
        with pytest.raises(AssertionError, match="LIVE PROVIDER CALL"):
            handler("prompt", 0.0, "model")
    make_student(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)
    lines: list[str] = []
    result = rc.run_cycle(roster_for("_cyc_a"), student="_cyc_a", conn=conn, collect=gh.collect,
                          checkout=gh.checkout, out=lines.append, with_llm=True)   # no llm=
    assert result.exit_code == 0 and result.students[0].graded == 1
    assert coach_traces(conn, "_cyc_a") == []
    assert vdel_dir_state() == vdel_before


def test_dry_run_and_skip_network_call_no_agent(conn, tmp_path):
    make_student(conn, "_cyc_a")
    insert_commit(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)
    fake = scripted(gh.quote)
    _, dry = cycle(conn, gh, "_cyc_a", fake=fake, with_llm=True, dry_run=True)
    _, skip = cycle(conn, gh, "_cyc_a", fake=fake, with_llm=True, skip_network=True)
    assert fake.call_count == 0 and coach_traces(conn, "_cyc_a") == []
    assert any("dry-run, no agent" in line for line in dry)
    assert any("--skip-network" in line for line in skip)


# --- the template push never reaches an agent ------------------------------------------------

@pytest.fixture
def delivered_repo(conn):
    conn.cursor().execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')",
                          (TPL_STUDENT, TPL_STUDENT))
    return delivered(conn.cursor())


def pending_for(conn, attempt_id, sha):
    cur = conn.cursor()
    cur.execute("SELECT committed_at FROM raw_commits WHERE sha = %s", (sha,))
    return gc.Pending(attempt_id, TPL_STUDENT, "weather_etl", TPL_ASG, 2, sha,
                      cur.fetchone()[0], "o", "r")


def test_the_template_push_of_a_delivered_repo_never_reaches_an_agent(conn, delivered_repo,
                                                                      tmp_path):
    attempt_id, template, first, _second = delivered_repo
    fake = fl.FakeLLM(default=lambda prompt: "{}")
    lines: list[str] = []
    hook = rc.AgentsHook(fake, rc.CallBudget(max_calls=10, day_cap=20, ledger=UsageLedger()),
                         Memory(), lines.append, 20)
    result = SimpleNamespace(tests_total=2, tests_passed=0, frozen=False, status="ok")

    hook.bind(conn)(pending_for(conn, attempt_id, template), tmp_path, result)

    assert fake.call_count == 0 and coach_traces(conn, TPL_STUDENT) == []
    assert any("template push, no agent" in line for line in lines)

    # the contrast: the student's own commit in the same attempt DOES reach the Feedback Agent
    student_fake = scripted("x")
    hook2 = rc.AgentsHook(student_fake, rc.CallBudget(max_calls=10, ledger=UsageLedger()),
                          Memory(), lines.append, 20)
    hook2.bind(conn)(pending_for(conn, attempt_id, first), tmp_path, result)
    assert student_fake.call_count >= 1
    ((_, payload),) = coach_traces(conn, TPL_STUDENT)
    assert payload["commit_sha"] == first


# --- the hook in grade_collected -------------------------------------------------------------

def run_gc(conn, tmp_path, *, grade_status="ok", after_grade=None):
    make_student(conn, "_cyc_a")
    insert_commit(conn, "_cyc_a")
    gh = FakeGitHub(tmp_path)

    def fake_grade(project, assignment, repo_dir, attempt_id, *, commit_sha, conn):
        return SimpleNamespace(tests_passed=1, tests_total=2, frozen=False, status=grade_status,
                               detail=None)

    return gc.run(student="_cyc_a", repo_for=roster_repo_for(roster_for("_cyc_a")),
                  checkout=gh.checkout, grade=fake_grade, conn=conn, after_grade=after_grade)


def test_after_grade_runs_before_the_checkout_is_deleted(conn, tmp_path):
    seen, dirs = [], []

    def hook(p, repo_dir, result):
        dirs.append(repo_dir)
        seen.append((p.sha, (repo_dir / "weather_etl" / "transform.py").is_file()))

    summary = run_gc(conn, tmp_path, after_grade=hook)

    assert seen == [("a" * 40, True)] and len(summary["graded"]) == 1   # the file was there
    assert summary["agent_errors"] == []
    assert not dirs[0].exists()                                         # and is gone afterwards


def test_after_grade_is_skipped_for_a_commit_that_did_not_grade_ok(conn, tmp_path):
    seen = []
    summary = run_gc(conn, tmp_path, grade_status="collection_error",
                     after_grade=lambda *a: seen.append(a))
    assert seen == [] and len(summary["graded"]) == 1


def test_a_raising_after_grade_is_recorded_and_the_grading_stands(conn, tmp_path):
    def hook(p, repo_dir, result):
        raise ValueError("no")

    summary = run_gc(conn, tmp_path, after_grade=hook)

    assert summary["failed"] == [] and len(summary["graded"]) == 1
    assert len(summary["agent_errors"]) == 1 and "ValueError: no" in summary["agent_errors"][0][1]


def test_grade_collected_still_imports_nothing_from_agents_or_the_gateway():
    """Invariant 13: the module that runs the tests is not an agent. The hook is the caller's."""
    source = Path(gc.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"^\s*(from|import)\s+(agents|system\.llm)\b", code, re.MULTILINE)
    assert not re.search(r"from system import .*\bllm\b", code)


# --- the GitHub text: the deterministic base stays, the LLM paragraph goes UNDER it ----------

class RecordingIssues:
    def __init__(self):
        self.bodies = []

    def find_issue(self, owner, repo, title, **kw):
        return None

    def create_issue(self, owner, repo, title, body):
        return {"number": 5, "html_url": "https://x/5"}

    def issue_comments(self, owner, repo, number, **kw):
        return []

    def create_issue_comment(self, owner, repo, number, body):
        self.bodies.append(body)
        return {"html_url": "https://x/c"}


def hourly(conn, tmp_path, gh, *, fake, with_llm, issues, monkeypatch, sid="_cyc_a"):
    monkeypatch.setenv(pf.GITHUB_WRITE_ENV_VAR, "1")
    roster = tmp_path / "roster.yaml"
    roster.write_text(f"assignments:\n  - assignment_id: {ASSIGNMENT}\n    owner: o\n"
                      f"    repo: repo-{sid}\n    student_id: {sid}\n", encoding="utf-8")
    lines: list[str] = []
    from datetime import UTC, datetime
    code = rh.run(roster_path=roster, log_dir=tmp_path / "logs", now=datetime.now(UTC),
                  conn=conn, collect=gh.collect, checkout=gh.checkout, grade=None, gh=issues,
                  out=lines.append, llm=fake, ledger=UsageLedger(), with_llm=with_llm)
    return code, "\n".join(lines)


def student_with_login(conn):
    make_student(conn, "_cyc_a")
    conn.cursor().execute("UPDATE students SET github_username = %s WHERE student_id = '_cyc_a'",
                          (USER,))


def deterministic_markdown(conn):
    cur = conn.cursor()
    cur.execute("SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a'")
    return pf.build_feedback(cur, cur.fetchone()[0], "a" * 40).markdown


def test_with_llm_the_paragraph_is_added_under_the_deterministic_text(conn, tmp_path,
                                                                      monkeypatch):
    student_with_login(conn)
    gh = UnsolvedGitHub(tmp_path)
    issues = RecordingIssues()

    code, out = hourly(conn, tmp_path, gh, fake=scripted(gh.quote), with_llm=True,
                       issues=issues, monkeypatch=monkeypatch)

    assert code == 0, out
    (body,) = issues.bodies
    base = deterministic_markdown(conn)
    assert base in body                                              # the base is intact
    assert body.index(base) < body.index("More detail") < body.index(SUMMARY)
    assert body.rstrip().endswith("-->")                             # the marker is still last
    assert "checks passed" in body.split("More detail")[0]           # counts live above, not below


def test_without_llm_the_comment_is_the_deterministic_text_alone(conn, tmp_path, monkeypatch):
    student_with_login(conn)
    gh = UnsolvedGitHub(tmp_path)
    issues = RecordingIssues()

    code, out = hourly(conn, tmp_path, gh, fake=scripted(gh.quote), with_llm=False,
                       issues=issues, monkeypatch=monkeypatch)

    assert code == 0, out
    (body,) = issues.bodies
    assert "More detail" not in body and SUMMARY not in body
    assert deterministic_markdown(conn) in body


def test_a_rejected_llm_answer_posts_the_deterministic_text_alone(conn, tmp_path, monkeypatch):
    student_with_login(conn)
    gh = UnsolvedGitHub(tmp_path)
    issues = RecordingIssues()
    rejected = scripted(gh.quote, feedback={
        "summary": "Your code is wrong.", "what_to_check_next": ["Look again."],
        "cited_tests": [], "cited_concepts": [], "resource_id": None, "confidence": "low"})

    code, out = hourly(conn, tmp_path, gh, fake=rejected, with_llm=True, issues=issues,
                       monkeypatch=monkeypatch)

    assert code == 0, out
    (body,) = issues.bodies
    assert "More detail" not in body and "Your code is wrong" not in body
    assert deterministic_markdown(conn) in body


def test_a_paragraph_that_would_leak_hidden_source_is_dropped_not_posted(conn, tmp_path,
                                                                         monkeypatch):
    student_with_login(conn)
    gh = UnsolvedGitHub(tmp_path)
    issues = RecordingIssues()
    hidden_line = sorted(pf.hidden_source_lines("weather_etl"), key=len)[-1]

    def leak_after_grading(cur, attempt_id, sha):
        return f"**More detail**\n\n{hidden_line}\n"

    monkeypatch.setattr(rh, "find_feedback_addendum", leak_after_grading)

    code, out = hourly(conn, tmp_path, gh, fake=scripted(gh.quote), with_llm=True,
                       issues=issues, monkeypatch=monkeypatch)

    assert code == 0, out
    (body,) = issues.bodies
    assert hidden_line not in body and "More detail" not in body
    assert "dropped" in out and deterministic_markdown(conn) in body
