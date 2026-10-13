"""D-110 -- pilot preparation: the database role (static), the student data notice, the per-student
opt-out, and the `--ab-llm` experiment.

The role file is only READ here: a role belongs to the whole Postgres server, so applying it from
a test would change the real server. Everything else uses the fake LLM, every provider handler
raises, and the database is the throwaway test one in a rolled-back transaction.
"""

import inspect
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agents import ab, prompts
from agents import fake_llm as fl
from agents import feedback_prompts as fp
from agents import feedback_v2 as fv2
from agents.budget import UsageLedger
from scripts import ab_report
from scripts import post_feedback as pf
from scripts import render_student_repo as rsr
from scripts import run_cycle as rc
from scripts import run_hourly as rh
from scripts.init_db import ORDER
from scripts.prove_event_sourcing import prove
from system import db
from tests import test_agents_feedback as base
from tests.test_feedback_v2 import AttemptedGitHub
from tests.test_run_cycle import ASSIGNMENT, make_student, roster_for
from tests.test_with_code_agent import SolvedGitHub, TwoCommitGitHub
from tests.test_with_llm import RecordingIssues, UnsolvedGitHub, coach_traces, scripted

ROOT = Path(__file__).resolve().parent.parent
ROLE = ROOT / "sql" / "pilot" / "vdel_cycle_role.sql"
needs_db = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; needs the test DB"
)


@pytest.fixture(autouse=True)
def no_live_provider(monkeypatch, tmp_path):
    from system import llm as gateway

    def blocked(*args, **kwargs):
        raise AssertionError("LIVE PROVIDER CALL attempted in a test")

    for provider in list(gateway._PROVIDER_HANDLERS):
        monkeypatch.setitem(gateway._PROVIDER_HANDLERS, provider, blocked)
    monkeypatch.setattr(rc, "DEFAULT_LEDGER_PATH", tmp_path / "default_llm_usage.json")
    monkeypatch.delenv(pf.GITHUB_WRITE_ENV_VAR, raising=False)


@pytest.fixture
def conn():
    try:
        c = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    yield c
    c.rollback()
    c.close()


# --- 1. the database role: static checks only ------------------------------------------------


def role_text() -> str:
    return re.sub(r"--[^\n]*", "", ROLE.read_text(encoding="utf-8"))


def grants() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for privs, tables in re.findall(
        r"GRANT\s+([A-Z, ]+?)\s+ON\s+(?!ALL|SCHEMA|DATABASE|SEQUENCE)"
        r"([\w, ]+?)\s+TO\s+vdel_cycle",
        role_text(),
    ):
        for table in re.split(r"\s*,\s*", tables.strip()):
            out.setdefault(table, set()).update(p.strip() for p in privs.split(","))
    return out


CYCLE_MODULES = [
    "collectors/collect_github.py",
    "features/compute_features.py",
    "memory/memory.py",
    "scripts/run_cycle.py",
    "scripts/run_hourly.py",
    "scripts/grade_collected.py",
    "scripts/post_feedback.py",
    "scripts/code_agent_report.py",
    "scripts/baseline.py",
    "scripts/doctor.py",
    "scripts/ab_report.py",
] + [
    p.relative_to(ROOT).as_posix()
    for d in ("assessment", "agents", "system")
    for p in (ROOT / d).glob("*.py")
]


def derived_writes() -> dict[str, set[str]]:
    """The INSERT / UPDATE (including ON CONFLICT DO UPDATE) the modules the role runs can issue."""
    writes: dict[str, set[str]] = {}
    for rel in CYCLE_MODULES:
        text = " ".join((ROOT / rel).read_text(encoding="utf-8").split())
        for m in re.finditer(r"INSERT INTO (\w+)", text):
            writes.setdefault(m.group(1), set()).add("INSERT")
            rest = text[m.end() : m.end() + 1200]
            cut = re.search(r"INSERT INTO |SELECT |UPDATE \w+ SET|DELETE ", rest)
            if "DO UPDATE" in (rest[: cut.start()] if cut else rest):
                writes[m.group(1)].add("UPDATE")
        for m in re.finditer(r"UPDATE (\w+) SET", text):
            writes.setdefault(m.group(1), set()).add("UPDATE")
    return writes


def test_the_role_file_is_a_proposal_nothing_applies():
    assert ROLE.exists() and ROLE.parent.name == "pilot"
    assert ROLE.name not in ORDER and not (ROOT / "sql" / ROLE.name).exists()
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", ".venv", "venv/", "build/")) or "site-packages" in rel:
            continue
        assert "vdel_cycle_role" not in path.read_text(encoding="utf-8"), rel
    tests_touching = [
        p.name
        for p in (ROOT / "tests").glob("*.py")
        if "vdel_cycle_role.sql" in p.read_text(encoding="utf-8")
    ]
    assert tests_touching == ["test_pilot.py"]  # this file only reads it


def test_the_role_is_not_a_superuser_and_cannot_create_anything():
    text = role_text()
    assert "CREATE ROLE vdel_cycle LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION" in text
    assert "NOBYPASSRLS" in text and "CONNECTION LIMIT" in text
    assert not re.search(
        r"(?<!NO)SUPERUSER|(?<!NO)CREATEDB|(?<!NO)CREATEROLE|(?<!NO)REPLICATION", text
    )
    assert "REVOKE CREATE ON SCHEMA public FROM vdel_cycle" in text
    assert not re.search(r"GRANT\s+ALL", text, re.I)
    assert not re.search(r"\b(DELETE|TRUNCATE|REFERENCES|TRIGGER)\b", text)


def test_the_password_is_never_in_the_file():
    text = role_text()
    assert "PASSWORD :pw;" in text and not re.search(r"PASSWORD\s+'", text)
    assert ':"dbname"' in text  # the database name is a psql variable


def test_traces_stay_append_only_for_the_role():
    assert grants()["traces"] == {"INSERT"}
    assert "SELECT ON ALL TABLES IN SCHEMA public TO vdel_cycle" in role_text()
    assert "GRANT USAGE, SELECT ON SEQUENCE traces_trace_id_seq TO vdel_cycle" in role_text()


def test_the_grants_are_exactly_what_the_code_on_the_cycle_path_writes():
    """Drift either way fails: a new write the role cannot do would stop the pilot with 'permission
    denied'; a grant nothing needs is more power than the role should have."""
    derived = derived_writes()
    assert grants() == derived, {"granted": grants(), "needed": derived}


def test_nothing_on_the_cycle_path_deletes_or_truncates():
    for rel in CYCLE_MODULES:
        text = " ".join((ROOT / rel).read_text(encoding="utf-8").split())
        assert not re.search(r"\bDELETE FROM \w+|\bTRUNCATE\b", text), rel


def test_every_table_in_the_schema_is_readable_by_the_role_in_one_statement():
    from scripts import doctor

    tables = {t for wants in doctor.expected_schema().values() for t in wants["tables"]}
    assert "traces" in tables and len(tables) >= 19
    assert "ALL TABLES IN SCHEMA public" in role_text()  # so a new table needs no edit to be read


def test_the_pilot_instructions_exist_and_say_the_file_is_not_applied():
    doc = (ROOT / "docs" / "PILOT.md").read_text(encoding="utf-8")
    assert "vdel_cycle_role.sql" in doc and "not applied" in doc.lower()
    assert "pw=" in doc and "-v dbname=" in doc and "PG_DSN" in doc


# --- 2. the student data notice ---------------------------------------------------------------


def test_the_notice_is_part_of_every_rendered_assignment_file():
    assert "assignment_md.append(DATA_NOTICE)" in inspect.getsource(rsr.render_student_repo)
    notice = rsr.DATA_NOTICE
    assert "external AI service provider" in notice and "To opt out" in notice
    assert "lines of your own code" in notice and "three lines of context" in notice
    assert "does **not** receive your name" in notice
    for line in notice.splitlines():
        assert len(line) <= 100


def test_the_three_lines_of_context_in_the_notice_are_the_ones_the_code_sends():
    from agents import scope

    assert scope.CONTEXT_LINES == 3


SECRET_STUDENT = "SECRET_STUDENT_ID_7"


def test_no_prompt_carries_the_students_identity():
    v1 = base.inp()
    values = {k: getattr(v1, k) for k in v1.__dataclass_fields__}
    values["student_id"] = SECRET_STUDENT
    inp1 = type(v1)(**values)
    assert SECRET_STUDENT not in fp.build_feedback_prompt(inp1)
    v2_values = {
        **values,
        "recurrence": {},
        "descriptions": {},
        "focus_check": None,
        "hint_level": 1,
        "excerpt": "x = 1\n",
        "excerpt_matchable": "x = 1\n",
        "excerpt_note": "",
        "excerpt_reason": None,
        "master_bodies": {},
    }
    inp2 = fv2.FeedbackInputV2(**v2_values)
    assert SECRET_STUDENT not in fp.build_feedback_prompt_v2(inp2)
    code_prompt = prompts.build_grading_prompt(
        "A task.", "x = 1\n", criteria=("approach",), production=True
    )
    assert SECRET_STUDENT not in code_prompt
    for prompt in (fp.build_feedback_prompt(inp1), fp.build_feedback_prompt_v2(inp2), code_prompt):
        assert not re.search(r"@\w+\.\w+", prompt) and "github_username" not in prompt.lower()


def test_the_notice_matches_what_the_feedback_prompt_lists():
    prompt = fp.build_feedback_prompt_v2(make_v2_input())
    for fact in (
        "Failed checks",
        "public description",
        "failed on",
        "Student context",
        "The student's own lines",
    ):
        assert fact in prompt
    notice = rsr.DATA_NOTICE
    for claim in (
        "names and error types",
        "short description",
        "how many pushes",
        "a number per related topic",
    ):
        assert claim in notice


def make_v2_input():
    v1 = base.inp()
    values = {k: getattr(v1, k) for k in v1.__dataclass_fields__}
    return fv2.FeedbackInputV2(
        **values,
        recurrence={},
        descriptions={},
        focus_check=None,
        hint_level=1,
        excerpt="x = 1\n",
        excerpt_matchable="x = 1\n",
        excerpt_note="n",
        excerpt_reason=None,
        master_bodies={},
    )


# --- 3. the per-student opt-out ---------------------------------------------------------------


def test_the_opt_out_fails_closed():
    roster = {
        "students": [
            {"student_id": "on_explicit", "ai_notes": True},
            {"student_id": "silent"},
            {"student_id": "off_bool", "ai_notes": False},
            {"student_id": "off_word", "ai_notes": "off"},
            {"student_id": "off_zero", "ai_notes": 0},
            {"student_id": "off_null", "ai_notes": None},
            {"student_id": "off_text", "ai_notes": "no"},
            "not a mapping",
            {"ai_notes": False},
        ]
    }
    assert rc.ai_opt_out(roster) == {"off_bool", "off_word", "off_zero", "off_null", "off_text"}
    assert rc.ai_opt_out({}) == frozenset() and rc.ai_opt_out({"students": None}) == frozenset()


def cycle(conn, gh, sid, *, fake, roster=None, **kw):
    lines: list[str] = []
    result = rc.run_cycle(
        roster or roster_for(sid),
        student=sid,
        conn=conn,
        collect=gh.collect,
        checkout=gh.checkout,
        out=lines.append,
        llm=fake,
        ledger=UsageLedger(),
        with_llm=True,
        **kw,
    )
    return result, lines


@needs_db
def test_an_opted_out_student_gets_no_agent_and_no_provider_call(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)
    fake = scripted(gh.quote)
    roster = roster_for("_cyc_a")
    roster["students"] = [{"student_id": "_cyc_a", "github_username": "x", "ai_notes": False}]

    result, lines = cycle(conn, gh, "_cyc_a", fake=fake, roster=roster)

    assert result.exit_code == 0 and result.students[0].graded == 1
    assert fake.call_count == 0 and coach_traces(conn, "_cyc_a") == []
    text = "\n".join(lines)
    assert "student opted out of AI notes" in text and "opted out: _cyc_a" in text


@needs_db
def test_another_student_in_the_same_roster_is_not_opted_out(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = UnsolvedGitHub(tmp_path)
    fake = scripted(gh.quote)
    roster = roster_for("_cyc_a")
    roster["students"] = [
        {"student_id": "_cyc_a", "ai_notes": True},
        {"student_id": "someone_else", "ai_notes": False},
    ]
    cycle(conn, gh, "_cyc_a", fake=fake, roster=roster)
    assert fake.call_count == 1 and len(coach_traces(conn, "_cyc_a")) == 1


def hourly(conn, tmp_path, gh, *, fake, monkeypatch, roster_yaml, issues, **flags):
    monkeypatch.setenv(pf.GITHUB_WRITE_ENV_VAR, "1")
    path = tmp_path / "roster.yaml"
    path.write_text(roster_yaml, encoding="utf-8")
    lines: list[str] = []
    code = rh.run(
        roster_path=path,
        log_dir=tmp_path / "logs",
        now=datetime.now(UTC),
        conn=conn,
        collect=gh.collect,
        checkout=gh.checkout,
        grade=None,
        gh=issues,
        out=lines.append,
        llm=fake,
        ledger=UsageLedger(),
        env={"LLM_PROVIDER": "openai"},
        **flags,
    )
    return code, "\n".join(lines)


ROSTER_ROWS = (
    "assignments:\n  - assignment_id: " + ASSIGNMENT + "\n    owner: o\n"
    "    repo: repo-_cyc_a\n    student_id: _cyc_a\n"
)


@needs_db
def test_a_stored_paragraph_is_not_posted_for_a_student_who_has_since_opted_out(
    conn, tmp_path, monkeypatch
):
    make_student(conn, "_cyc_a")
    conn.cursor().execute(
        "UPDATE students SET github_username = 'llm-student' WHERE student_id = '_cyc_a'"
    )
    gh = UnsolvedGitHub(tmp_path)
    cycle(conn, gh, "_cyc_a", fake=scripted(gh.quote))  # the paragraph is stored
    ((_, payload),) = coach_traces(conn, "_cyc_a")
    assert payload["addendum_markdown"]
    issues = RecordingIssues()
    off = (
        "students:\n  - student_id: _cyc_a\n    github_username: llm-student\n"
        "    cohort: vdel-2026\n    ai_notes: false\n" + ROSTER_ROWS
    )
    code, out = hourly(
        conn,
        tmp_path,
        gh,
        fake=fl.FakeLLM([]),
        monkeypatch=monkeypatch,
        roster_yaml=off,
        issues=issues,
        with_llm=True,
        skip_network=True,
    )
    assert code == 0, out
    (body,) = issues.bodies
    assert "More detail" not in body and payload["addendum_markdown"] not in body


# --- 4. --ab-llm -----------------------------------------------------------------------------


def test_the_arm_is_a_stable_function_of_the_attempt_and_the_commit():
    assert ab.arm_for(7, "a" * 40) == ab.arm_for(7, "a" * 40)
    pinned = {(1, "a" * 40): ab.arm_for(1, "a" * 40), (2, "b" * 40): ab.arm_for(2, "b" * 40)}
    for (attempt, sha), arm in pinned.items():
        assert arm in ab.ARMS and ab.arm_for(attempt, sha) == arm
    assert ab.arm_for(1, "a" * 40, salt="other") in ab.ARMS


def test_the_arms_are_balanced_over_many_pairs_and_depend_on_both_inputs():
    arms = [ab.arm_for(i, f"{i:040x}") for i in range(2000)]
    share = arms.count(ab.LLM) / len(arms)
    assert 0.45 <= share <= 0.55
    assert len({ab.arm_for(1, f"{i:040x}") for i in range(50)}) == 2  # the commit matters
    assert len({ab.arm_for(i, "c" * 40) for i in range(50)}) == 2  # the attempt matters


def force(monkeypatch, arm):
    monkeypatch.setattr(ab, "arm_for", lambda attempt_id, commit_sha, salt=ab.SALT: arm)


def assignments(conn, sid):
    cur = conn.cursor()
    cur.execute(
        "SELECT payload FROM traces WHERE student_id = %s AND actor = 'coach' AND "
        "kind = 'intervention' AND payload->>'agent' = 'ab_assignment' ORDER BY trace_id",
        (sid,),
    )
    return [p for (p,) in cur.fetchall()]


def feedback_traces(conn, sid):
    return [(i, p) for i, p in coach_traces(conn, sid) if p.get("agent") != "ab_assignment"]


@needs_db
def test_the_control_arm_gets_the_deterministic_text_alone_and_the_record_is_stored_once(
    conn, tmp_path, monkeypatch
):
    make_student(conn, "_cyc_a")
    force(monkeypatch, ab.CONTROL)
    gh = AttemptedGitHub(tmp_path)
    fake = scripted("    return records")

    result, lines = cycle(conn, gh, "_cyc_a", fake=fake, ab_llm=True)

    assert result.exit_code == 0 and fake.call_count == 0
    ((record,),) = [(r,) for r in assignments(conn, "_cyc_a")]
    assert record["arm"] == "control" and record["salt"] == ab.SALT
    assert record["commit_sha"] == "a" * 40 and feedback_traces(conn, "_cyc_a") == []
    assert "ab arm=control" in "\n".join(lines)
    cycle(conn, gh, "_cyc_a", fake=fake, ab_llm=True)  # nothing new to grade
    assert len(assignments(conn, "_cyc_a")) == 1


@needs_db
def test_the_llm_arm_runs_the_agent_as_without_the_experiment(conn, tmp_path, monkeypatch):
    make_student(conn, "_cyc_a")
    force(monkeypatch, ab.LLM)
    gh = UnsolvedGitHub(tmp_path)
    fake = scripted(gh.quote)
    cycle(conn, gh, "_cyc_a", fake=fake, ab_llm=True)
    assert fake.call_count == 1
    ((record,),) = [(r,) for r in assignments(conn, "_cyc_a")]
    assert record["arm"] == "llm"
    ((_, payload),) = feedback_traces(conn, "_cyc_a")
    assert payload["agent"] == "feedback_agent_v1" and payload["source"] == "llm"


@needs_db
def test_an_llm_commit_is_recorded_even_when_the_answer_is_rejected(conn, tmp_path, monkeypatch):
    make_student(conn, "_cyc_a")
    force(monkeypatch, ab.LLM)
    gh = UnsolvedGitHub(tmp_path)
    wrong = json.dumps(
        {
            "summary": "Your code is wrong.",
            "what_to_check_next": ["Look."],
            "cited_tests": [],
            "cited_concepts": [],
            "resource_id": None,
            "confidence": "low",
        }
    )
    fake = fl.FakeLLM(default=lambda prompt: wrong)
    cycle(conn, gh, "_cyc_a", fake=fake, ab_llm=True)
    assert len(assignments(conn, "_cyc_a")) == 1 and feedback_traces(conn, "_cyc_a") == []


@needs_db
def test_a_commit_with_no_failing_check_is_not_part_of_the_experiment(conn, tmp_path, monkeypatch):
    make_student(conn, "_cyc_a")
    force(monkeypatch, ab.CONTROL)
    cycle(conn, SolvedGitHub(tmp_path), "_cyc_a", fake=fl.FakeLLM([]), ab_llm=True)
    assert assignments(conn, "_cyc_a") == []


@needs_db
def test_a_stored_assignment_wins_over_a_later_change_of_the_rule(conn, tmp_path, monkeypatch):
    from memory.memory import Memory

    make_student(conn, "_cyc_a")
    force(monkeypatch, ab.CONTROL)
    cycle(conn, UnsolvedGitHub(tmp_path), "_cyc_a", fake=fl.FakeLLM([]), ab_llm=True)
    cur = conn.cursor()
    cur.execute("SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a'")
    (attempt_id,) = cur.fetchone()
    force(monkeypatch, ab.LLM)  # the rule now says llm
    arm = ab.record_arm(Memory(), cur, "_cyc_a", ASSIGNMENT, attempt_id, "a" * 40)
    assert arm == "control" and len(assignments(conn, "_cyc_a")) == 1


@needs_db
def test_the_experiment_does_not_disturb_the_replay_proof_or_mastery(conn, tmp_path, monkeypatch):
    make_student(conn, "_cyc_a")
    force(monkeypatch, ab.CONTROL)
    cycle(conn, UnsolvedGitHub(tmp_path), "_cyc_a", fake=fl.FakeLLM([]), ab_llm=True)
    proof = prove(conn)
    assert [d for d in proof.differences if d.student_id == "_cyc_a"] == []


def test_the_flag_is_off_by_default_and_refused_without_with_llm():
    import argparse

    parser = argparse.ArgumentParser()
    rc.add_llm_arguments(parser)
    assert parser.parse_args([]).ab_llm is False and parser.parse_args(["--ab-llm"]).ab_llm
    lines: list[str] = []
    res = rc.run_cycle({"assignments": []}, ab_llm=True, with_llm=False, out=lines.append)
    assert res.exit_code == rc.EXIT_REFUSED and "--ab-llm runs only together" in lines[0]
    assert "--ab-llm" in rh._refusal(False, False, {"LLM_PROVIDER": "openai"}, False, True)
    assert rh._refusal(True, False, {"LLM_PROVIDER": "openai"}, False, True) is None
    for fn in (rc.run_cycle, rh.run):
        assert inspect.signature(fn).parameters["ab_llm"].default is False
    windows = ROOT / "scripts" / "windows"
    assert all("ab-llm" not in p.read_text(encoding="utf-8") for p in windows.glob("*.ps1"))


# --- the report -------------------------------------------------------------------------------


def test_the_summary_counts_passed_and_censored_and_takes_the_mean_and_median():
    rows = [
        {"arm": "llm", "attempt_id": 1, "commits_to_pass": 1},
        {"arm": "llm", "attempt_id": 2, "commits_to_pass": 3},
        {"arm": "llm", "attempt_id": 2, "commits_to_pass": None},
        {"arm": "control", "attempt_id": 3, "commits_to_pass": 2},
        {"arm": "control", "attempt_id": 4, "commits_to_pass": None},
    ]
    s = ab_report.summarise(rows)
    assert s["llm"] == {
        "n": 3,
        "passed": 2,
        "censored": 1,
        "mean": 2.0,
        "median": 2.0,
        "attempts": 2,
    }
    assert s["control"]["n"] == 2 and s["control"]["passed"] == 1 and s["control"]["mean"] == 2.0
    empty = ab_report.summarise([])
    assert empty["llm"]["mean"] is None and empty["control"]["n"] == 0
    text = "\n".join(ab_report.render(rows, "vdel_test"))
    assert ab_report.LABEL in text and "NOT A SIGNIFICANCE TEST" in text
    assert "one attempt can be in both arms" in text


@needs_db
def test_the_report_scores_an_assigned_commit_by_the_pushes_until_the_attempt_froze(
    conn, tmp_path, monkeypatch
):
    make_student(conn, "_cyc_a")
    force(monkeypatch, ab.CONTROL)
    gh = TwoCommitGitHub(tmp_path)  # push 1 fails, push 2 passes every check (freezes)
    fake = fl.FakeLLM([])
    cycle(conn, gh, "_cyc_a", fake=fake, ab_llm=True)
    rows = ab_report.assigned_commits(conn.cursor(), "_cyc_a")
    assert [(r["arm"], r["commit"], r["commits_to_pass"]) for r in rows] == [
        ("control", "a" * 40, 1)
    ]
    assert ab_report.summarise(rows)["control"]["mean"] == 1.0
    source = (ROOT / "scripts" / "ab_report.py").read_text(encoding="utf-8")
    code = re.sub(r'"""(?:.|\n)*?"""', "", source)
    assert "readonly=True" in code and "rollback()" in code
    for forbidden in (
        r"\bINSERT\b",
        r"\bUPDATE\b",
        r"\bDELETE\b",
        r"\.commit\(",
        r"log_trace",
        r"requests",
        r"system\.llm",
    ):
        assert not re.search(forbidden, code), forbidden
