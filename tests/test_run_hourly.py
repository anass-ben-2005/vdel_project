"""D-091 -- scripts/run_hourly.py: the lock, a database that is down, the GitHub-write switch, the
log and its rotation. A fake GitHub layer for the cycle (as in test_run_cycle) and a fake issue
client for the feedback phase; no network. One rolled-back transaction per test."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import psycopg2
import pytest

from scripts import post_feedback as pf
from scripts import run_hourly as rh
from system import db
from tests.support import ensure_variant
from tests.test_run_cycle import FakeGitHub as CycleGitHub

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

S, USER, ASG = "_cyc_a", "hourly-student", "weather_etl_transform"
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(pf.GITHUB_WRITE_ENV_VAR, raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token-value")


@pytest.fixture
def conn():
    try:
        c = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = c.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, USER))
    variant = ensure_variant(cur, ASG)
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl',%s,1,%s,1)", (S, ASG, variant))
    yield c
    c.rollback()
    c.close()


class FakeIssues:
    def __init__(self):
        self.calls = []

    def find_issue(self, owner, repo, title, **kw):
        self.calls.append("find_issue")
        return None

    def create_issue(self, owner, repo, title, body):
        self.calls.append("create_issue")
        return {"number": 5, "html_url": "https://x/5"}

    def issue_comments(self, owner, repo, number, **kw):
        self.calls.append("issue_comments")
        return []

    def create_issue_comment(self, owner, repo, number, body):
        self.calls.append("create_issue_comment")
        return {"html_url": "https://x/c"}


@pytest.fixture
def roster_file(tmp_path):
    path = tmp_path / "roster.yaml"
    path.write_text(
        f"assignments:\n  - assignment_id: {ASG}\n    owner: o\n    repo: repo-{S}\n"
        f"    student_id: {S}\n", encoding="utf-8")
    return path


_CYCLE_GH: dict = {}


def hourly(conn, tmp_path, roster_file, gh_issues=None, **kw):
    # one fake collection layer per test: it builds its checkout directory under tmp_path once
    if tmp_path not in _CYCLE_GH:
        _CYCLE_GH[tmp_path] = CycleGitHub(tmp_path)
    cycle_gh = _CYCLE_GH[tmp_path]
    lines: list[str] = []
    code = rh.run(roster_path=roster_file, log_dir=tmp_path / "logs", now=NOW, conn=conn,
                  collect=cycle_gh.collect, checkout=cycle_gh.checkout, grade=None,
                  gh=gh_issues, out=lines.append, **kw)
    return code, "\n".join(lines), cycle_gh


# --- the database and the lock ----------------------------------

def test_a_database_that_is_down_ends_with_a_plain_line_and_exit_2(monkeypatch, tmp_path,
                                                                   roster_file):
    def down():
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr(rh.db, "_open", down)
    lines: list[str] = []
    code = rh.run(roster_path=roster_file, log_dir=tmp_path / "logs", now=NOW, out=lines.append)
    assert code == rh.EXIT_DB_DOWN == 2
    assert any(line.startswith("DATABASE UNREACHABLE") for line in lines)
    assert any("docker compose up -d" in line for line in lines)      # what to do about it


def test_a_second_run_while_the_first_holds_the_lock_exits_3_and_does_nothing(
        conn, tmp_path, roster_file):
    holder = db._open()
    holder.autocommit = True
    try:
        with holder.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (rh.HOURLY_LOCK_KEY,))
        code, out, gh = hourly(conn, tmp_path, roster_file)
        assert code == rh.EXIT_LOCKED == 3 and "ANOTHER run_hourly IS RUNNING" in out
        assert gh.collect_calls == []                                  # nothing was collected
    finally:
        holder.close()                                                 # releases the lock
    code, out, _ = hourly(conn, tmp_path, roster_file)
    assert code == 0, out                                              # and then it runs


def test_the_lock_is_released_when_the_run_ends(conn, tmp_path, roster_file):
    assert hourly(conn, tmp_path, roster_file)[0] == 0
    probe = db._open()
    probe.autocommit = True
    try:
        with probe.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (rh.HOURLY_LOCK_KEY,))
            assert cur.fetchone()[0] is True
    finally:
        probe.close()


# --- GitHub writes ----------------------------------

def test_without_the_flag_nothing_is_written_to_github(conn, tmp_path, roster_file):
    gh = FakeIssues()
    code, out, _ = hourly(conn, tmp_path, roster_file, gh)
    assert code == 0, out
    assert gh.calls == []
    assert "writes off" in out and "WOULD POST" in out
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM feedback_posts")
    assert cur.fetchone()[0] == 0


def test_a_dry_run_never_writes_even_with_the_flag(conn, tmp_path, roster_file, monkeypatch):
    monkeypatch.setenv(pf.GITHUB_WRITE_ENV_VAR, "1")
    gh = FakeIssues()
    code, out, _ = hourly(conn, tmp_path, roster_file, gh, dry_run=True)
    assert code == 0 and gh.calls == [] and "writes off" in out


def test_with_the_flag_the_new_commit_is_commented_once_and_not_again(conn, tmp_path,
                                                                     roster_file, monkeypatch):
    monkeypatch.setenv(pf.GITHUB_WRITE_ENV_VAR, "1")
    gh = FakeIssues()
    code, out, _ = hourly(conn, tmp_path, roster_file, gh)
    assert code == 0, out
    assert "WRITES ON" in out and "posted" in out
    assert gh.calls.count("create_issue_comment") == 1 and gh.calls.count("create_issue") == 1
    again, out2, _ = hourly(conn, tmp_path, roster_file, gh)
    assert again == 0 and gh.calls.count("create_issue_comment") == 1   # nothing new
    assert "nothing new" in out2


def test_a_commit_graded_long_ago_is_not_posted_by_the_task(conn, tmp_path, roster_file,
                                                           monkeypatch):
    hourly(conn, tmp_path, roster_file)                                 # grades the commit
    cur = conn.cursor()
    cur.execute("UPDATE test_results SET ran_at = now() - interval '10 days'"
                " WHERE attempt_id IN (SELECT attempt_id FROM attempts WHERE student_id = %s)",
                (S,))
    monkeypatch.setenv(pf.GITHUB_WRITE_ENV_VAR, "1")
    gh = FakeIssues()
    code, out, _ = hourly(conn, tmp_path, roster_file, gh)
    assert code == 0 and gh.calls == [] and "nothing new" in out


def test_a_github_failure_is_a_failed_run_but_does_not_crash(conn, tmp_path, roster_file,
                                                            monkeypatch):
    from scripts.publish_repo import GitHubHTTPError

    class Broken(FakeIssues):
        def create_issue(self, owner, repo, title, body):
            raise GitHubHTTPError(403, "creating: forbidden")

    monkeypatch.setenv(pf.GITHUB_WRITE_ENV_VAR, "1")
    code, out, _ = hourly(conn, tmp_path, roster_file, Broken())
    assert code == rh.EXIT_FAILED and "failed" in out and "forbidden" in out


def test_a_placeholder_username_is_refused_by_the_task(conn, tmp_path, roster_file, monkeypatch):
    conn.cursor().execute("UPDATE students SET github_username = 'x-placeholder-y'"
                          " WHERE student_id = %s", (S,))
    monkeypatch.setenv(pf.GITHUB_WRITE_ENV_VAR, "1")
    gh = FakeIssues()
    code, out, _ = hourly(conn, tmp_path, roster_file, gh)
    assert code == rh.EXIT_FAILED and gh.calls == [] and "refused" in out


# --- the log and its rotation ----------------------------------

def test_the_run_writes_a_dated_log_file_with_timestamps(conn, tmp_path, roster_file):
    cycle_gh = CycleGitHub(tmp_path)
    code = rh.run(roster_path=roster_file, log_dir=tmp_path / "logs", now=NOW, conn=conn,
                  collect=cycle_gh.collect, checkout=cycle_gh.checkout)
    assert code == 0
    log = tmp_path / "logs" / "run_hourly-2026-10-12.log"
    text = log.read_text(encoding="utf-8")
    assert "run_hourly 2026-10-12 09:00 UTC  LIVE" in text and "cycle done" in text
    assert "secret-token-value" not in text
    assert all(line[2] == ":" for line in text.splitlines())            # "HH:MM:SS ..."


def test_the_first_line_of_the_log_is_written_before_anything_else(monkeypatch, tmp_path,
                                                                   roster_file):
    """D-095: even a run that dies at once (database down) leaves a START line first."""
    def down():
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr(rh.db, "_open", down)
    assert rh.run(roster_path=roster_file, log_dir=tmp_path / "logs", now=NOW) == 2
    first = (tmp_path / "logs" / "run_hourly-2026-10-12.log").read_text(encoding="utf-8")
    first = first.splitlines()[0]
    assert "run_hourly START pid=" in first and "cwd=" in first and "python=" in first


def test_logs_older_than_14_days_are_deleted_and_nothing_else(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    names = {"run_hourly-2026-09-27.log": True,    # 15 days old: removed
             "run_hourly-2026-09-28.log": False,   # exactly 14 days: kept
             "run_hourly-2026-10-12.log": False,   # today
             "run_hourly-notadate.log": False,     # not ours to judge
             "other.log": False}
    for name in names:
        (logs / name).write_text("x", encoding="utf-8")
    removed = rh.rotate_logs(logs, NOW)
    assert removed == ["run_hourly-2026-09-27.log"]
    assert sorted(p.name for p in logs.iterdir()) == sorted(n for n, gone in names.items()
                                                            if not gone)


def test_the_roster_missing_is_a_failed_run_with_a_message_not_a_traceback(tmp_path, conn):
    lines: list[str] = []
    code = rh.run(roster_path=tmp_path / "nope.yaml", log_dir=tmp_path / "logs", now=NOW,
                  conn=conn, out=lines.append)
    assert code == rh.EXIT_FAILED and any("ROSTER PROBLEM" in line for line in lines)


def test_the_recent_window_is_inclusive_and_per_student(conn, tmp_path, roster_file):
    hourly(conn, tmp_path, roster_file)
    cur = conn.cursor()
    assert len(pf.recent_unposted(cur, S, 1)) == 1
    cur.execute("UPDATE test_results SET ran_at = now() - interval '47 hours'"
                " WHERE attempt_id IN (SELECT attempt_id FROM attempts"
                " WHERE student_id = %s)", (S,))
    assert len(pf.recent_unposted(cur, S, 48)) == 1
    assert pf.recent_unposted(cur, S, 24) == []
    assert pf.recent_unposted(cur, "nobody", 48) == []
    _ = timedelta  # (kept: the window is expressed in hours throughout)


def test_the_task_scripts_keep_writes_off_by_default():
    from pathlib import Path

    folder = Path(__file__).resolve().parent.parent / "scripts" / "windows"
    register = (folder / "task_command.ps1").read_text(encoding="utf-8")   # D-095: the builder
    unregister = (folder / "unregister_task.ps1").read_text(encoding="utf-8")
    assert "[switch]$AllowGitHubWrite" in register
    assert "[switch]$AllowGitHubWrite" in (folder / "register_task.ps1").read_text(encoding="utf-8")
    # the flag is SET in exactly one place: the line of the AllowGitHubWrite branch
    setters = [ln for ln in register.splitlines() if "VDEL_ALLOW_GITHUB_WRITE = '1'" in ln]
    assert len(setters) == 1 and "if ($AllowGitHubWrite)" in setters[0]
    registration = (folder / "register_task.ps1").read_text(encoding="utf-8")
    assert "SupportsShouldProcess" in registration and "SupportsShouldProcess" in unregister
    assert "-MultipleInstances IgnoreNew" in registration and "ExecutionTimeLimit" in registration
