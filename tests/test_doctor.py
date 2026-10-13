"""D-105 -- scripts/doctor.py: read-only readiness checks, tested with mocks.

No network (the module forbids `requests` outright, so a stray call fails loudly), no Docker, no
PowerShell: every probe is a parameter. The only real thing is the test database, read-only, for the
"migrations current" check against the real `sql/` directory.
"""

import base64
import os
import subprocess
from pathlib import Path

import pytest

from scripts import doctor as dr

TOKEN = "ghp_SECRETSECRETSECRET1234567890"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    import requests

    def boom(*a, **k):
        raise AssertionError("the doctor tests must never reach the network")

    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(requests, "request", boom)
    monkeypatch.setattr(requests.Session, "request", boom)


def cp(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def levels(checks):
    return [c.level for c in checks]


# --- python ---------------------------------------------------------------------------------------


def test_python_version_ok_and_too_old():
    assert dr.check_python((3, 13, 0)).level == dr.OK
    old = dr.check_python((3, 10, 9))
    assert old.level == dr.FAIL and "3.11" in old.detail


# --- docker ---------------------------------------------------------------------------------------


def test_docker_down_is_a_failure_and_asks_nothing_else():
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return cp(1)

    out = dr.check_docker(run, image="img:1")
    assert levels(out) == [dr.FAIL] and len(calls) == 1


def test_docker_up_image_present_and_missing():
    def present(argv, **kw):
        return cp(0, "27.0.1\n")

    out = dr.check_docker(present, image="img:1")
    assert levels(out) == [dr.OK, dr.OK] and "27.0.1" in out[0].detail

    def missing(argv, **kw):
        return cp(0, "27.0.1") if argv[1] == "info" else cp(1)

    out = dr.check_docker(missing, image="img:1")
    assert levels(out) == [dr.OK, dr.WARN]
    assert "vdel-grader" in out[1].detail and "subprocess" in out[1].detail


def test_docker_not_installed():
    def run(argv, **kw):
        raise FileNotFoundError("docker")

    out = dr.check_docker(run, image="img:1")
    assert out[0].level == dr.FAIL and "FileNotFoundError" in out[0].detail


# --- migrations -----------------------------------------------------------------------------------


def test_expected_schema_reads_create_table_and_add_column(tmp_path):
    (tmp_path / "01_a.sql").write_text(
        "-- CREATE TABLE ghost (x int);\nCREATE TABLE IF NOT EXISTS alpha (id int);\n"
        "CREATE TABLE beta (id int);\n"
        "ALTER TABLE alpha\n  ADD COLUMN IF NOT EXISTS c1 int,\n  ADD COLUMN c2 text;\n"
        "CREATE INDEX i ON alpha (id);\n",
        encoding="utf-8",
    )
    got = dr.expected_schema(tmp_path)["01_a.sql"]
    assert got["tables"] == {"alpha", "beta"}  # the commented-out table is ignored
    assert got["columns"] == {"alpha.c1", "alpha.c2"}


class FakeCursor:
    def __init__(self, columns, rows_by_sql=None):
        self.columns, self.rows_by_sql, self._last = columns, rows_by_sql or {}, ""

    def execute(self, sql, params=()):
        self._last = sql

    def fetchall(self):
        if "information_schema" in self._last:
            return self.columns
        for key, rows in self.rows_by_sql.items():
            if key in self._last:
                return rows
        return []


def test_migrations_missing_table_and_column_fail(tmp_path):
    (tmp_path / "01_a.sql").write_text(
        "CREATE TABLE alpha (id int);\nALTER TABLE alpha ADD COLUMN c1 int;\n"
        "CREATE TABLE beta (i int);",
        encoding="utf-8",
    )
    ok = dr.check_migrations(
        FakeCursor([("alpha", "id"), ("alpha", "c1"), ("beta", "i")]), tmp_path
    )
    assert ok.level == dr.OK
    bad = dr.check_migrations(FakeCursor([("alpha", "id")]), tmp_path)
    assert bad.level == dr.FAIL and "2 missing" in bad.detail and "init_db" in bad.detail


@pytest.mark.skipif(not os.environ.get("PG_DSN"), reason="PG_DSN not set; needs the test database")
def test_migrations_current_on_the_test_database():
    from system import db

    conn = db._open()
    try:
        conn.set_session(readonly=True)
        check = dr.check_migrations(conn.cursor())
    finally:
        conn.rollback()
        conn.close()
    assert check.level == dr.OK, check.detail


def test_database_unreachable_is_a_failure_with_the_reason():
    def opener():
        raise RuntimeError("connection refused\nsecond line")

    checks, conn = dr.check_database(opener)
    assert conn is None and levels(checks) == [dr.FAIL]
    assert "connection refused" in checks[0].detail and "second line" not in checks[0].detail


# --- github ---------------------------------------------------------------------------------------


def test_no_token_fails_and_names_the_variable_only():
    out = dr.check_github_token({})
    assert levels(out) == [dr.FAIL] and "GITHUB_TOKEN" in out[0].detail


def test_token_scopes_ok_missing_and_never_printed():
    def get(scopes):
        return lambda url, headers: (200, {"X-OAuth-Scopes": scopes})

    ok = dr.check_github_token({"GITHUB_TOKEN": TOKEN}, get("repo, workflow, read:org"))
    assert levels(ok) == [dr.OK, dr.OK] and "repo, workflow, read:org" in ok[1].detail
    short = dr.check_github_token({"GITHUB_TOKEN": TOKEN}, get("repo"))
    assert short[1].level == dr.WARN and "missing: workflow" in short[1].detail
    for check in ok + short:
        assert TOKEN not in check.line()


def test_token_rejected_fine_grained_and_other_status():
    env = {"GITHUB_TOKEN": TOKEN}
    assert dr.check_github_token(env, lambda u, h: (401, {}))[1].level == dr.FAIL
    fine = dr.check_github_token(env, lambda u, h: (200, {}))[1]
    assert fine.level == dr.WARN and "fine-grained" in fine.detail
    assert dr.check_github_token(env, lambda u, h: (503, {}))[1].level == dr.WARN


def test_a_failing_request_is_a_warning_not_a_crash_and_the_header_is_sent_once():
    seen = []

    def get(url, headers):
        seen.append((url, headers))
        raise OSError("network down")

    out = dr.check_github_token({"GITHUB_TOKEN": TOKEN}, get)
    assert out[1].level == dr.WARN and "OSError" in out[1].detail and TOKEN not in out[1].line()
    assert [u for u, _ in seen] == [dr.GITHUB_USER_URL]


def test_no_network_flag_makes_no_call():
    out = dr.check_github_token({"GITHUB_TOKEN": TOKEN}, None)
    assert out[1].level == dr.WARN and "--no-network" in out[1].detail


# --- roster and open attempts ---------------------------------------------------------------------

ROSTER = """students:
  - student_id: anas
    github_username: anas-gh
    cohort: vdel-2026
assignments:
  - assignment_id: weather_etl_extract
    owner: anas-gh
    repo: vdel-weather-etl-gapfill-anas-extract-attempt2
    student_id: anas
    released_at: 2026-10-01T00:00:00Z
    concepts: []
"""


def test_roster_missing_broken_incomplete_placeholder_and_good(tmp_path):
    assert dr.load_roster_rows(tmp_path / "nope.yaml")[1].level == dr.FAIL
    bad = tmp_path / "bad.yaml"
    bad.write_text("assignments: [", encoding="utf-8")
    assert dr.load_roster_rows(bad)[1].level == dr.FAIL
    inc = tmp_path / "inc.yaml"
    inc.write_text("assignments:\n  - assignment_id: a\n    owner: o\n", encoding="utf-8")
    assert dr.load_roster_rows(inc)[1].level == dr.FAIL
    ph = tmp_path / "ph.yaml"
    ph.write_text(ROSTER.replace("anas-gh\n    repo", "CHANGE_ME\n    repo"), encoding="utf-8")
    assert dr.load_roster_rows(ph)[1].level == dr.WARN
    good = tmp_path / "good.yaml"
    good.write_text(ROSTER, encoding="utf-8")
    roster, check = dr.load_roster_rows(good)
    assert check.level == dr.OK and "1 assignment row" in check.detail and roster["students"]


def test_open_attempt_without_a_roster_repo_and_with_the_wrong_one():
    roster = {
        "assignments": [
            {
                "assignment_id": "weather_etl_extract",
                "owner": "o",
                "repo": "vdel-weather-etl-gapfill-anas-extract-attempt2",
                "student_id": "anas",
            }
        ]
    }
    cur = FakeCursor(
        [],
        {
            "SELECT DISTINCT student_id": [("anas",)],
            "SELECT assignment_id, attempt_no, project_id": [
                ("weather_etl_extract", 3, "weather_etl"),
                ("weather_etl_load", 1, "weather_etl"),
            ],
        },
    )
    out = dr.check_open_attempts(cur, roster)
    assert levels(out) == [dr.WARN, dr.WARN]
    text = " | ".join(c.detail for c in out)
    assert "weather_etl_extract" in text and "attempt3" in text  # roster is one attempt behind
    assert "weather_etl_load has no roster repo" in text


def test_open_attempts_all_reachable_is_ok():
    roster = {
        "assignments": [
            {
                "assignment_id": "weather_etl_extract",
                "owner": "o",
                "repo": "vdel-weather-etl-gapfill-anas-extract-attempt3",
                "student_id": "anas",
            }
        ]
    }
    cur = FakeCursor(
        [],
        {
            "SELECT DISTINCT student_id": [("anas",)],
            "SELECT assignment_id, attempt_no, project_id": [
                ("weather_etl_extract", 3, "weather_etl")
            ],
        },
    )
    assert levels(dr.check_open_attempts(cur, roster)) == [dr.OK]


# --- llm keys -------------------------------------------------------------------------------------


def test_provider_key_names_match_the_gateway():
    from system import llm

    assert {p.value: v for p, v in llm._FALLBACK_KEY_ENV_VARS.items()} == dr.PROVIDER_KEYS


def test_llm_keys_report_names_never_values():
    secret = "sk-SECRETVALUE0123456789"
    out = dr.check_llm_keys({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": secret})
    text = "\n".join(c.line() for c in out)
    assert "OPENAI_API_KEY" in text and secret not in text
    assert dr.WARN not in levels(out)


def test_llm_keys_two_keys_warn_none_is_ok_and_a_typo_fails():
    two = dr.check_llm_keys(
        {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "x", "GOOGLE_API_KEY": "y"}
    )
    assert any(c.level == dr.WARN and "more than one" in c.detail for c in two)
    none = dr.check_llm_keys({})
    assert dr.FAIL not in levels(none) and "no provider key" in none[-1].detail
    assert dr.check_llm_keys({"LLM_PROVIDER": "opnai"})[0].level == dr.FAIL
    wrong = dr.check_llm_keys({"LLM_PROVIDER": "google", "OPENAI_API_KEY": "x"})
    assert any("needs GOOGLE_API_KEY" in c.detail for c in wrong)


# --- scheduled task -------------------------------------------------------------------------------


def encode(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def task_args(script: str) -> str:
    return "-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand " + encode(script)


def test_task_command_decoding_and_flags():
    script = (
        "$env:VDEL_ALLOW_GITHUB_WRITE = '1'\n$env:LLM_PROVIDER = 'openai'\n"
        "& $python -m scripts.run_hourly --with-llm --with-code-agent 2>&1"
    )
    assert dr.decode_task_command(task_args(script)) == script
    f = dr.task_flags(script)
    assert f == {
        "github_write": True,
        "docker_grading": False,
        "with_llm": True,
        "with_code_agent": True,
        "llm_provider": "openai",
    }
    assert dr.task_flags("& $python -m scripts.run_hourly 2>&1") == {
        "github_write": False,
        "docker_grading": False,
        "with_llm": False,
        "with_code_agent": False,
        "llm_provider": "",
    }
    assert dr.decode_task_command("-NoProfile garbage!!") is None


def test_scheduled_task_not_applicable_off_windows_and_never_runs_anything():
    def run(argv, **kw):
        raise AssertionError("must not run anything off Windows")

    out = dr.check_scheduled_task("Linux", run)
    assert levels(out) == [dr.OK] and "cron" in out[0].detail


def test_scheduled_task_registered_decoded_and_warns_without_docker():
    script = "$env:VDEL_GRADING_SANDBOX = 'docker'\n& $python -m scripts.run_hourly 2>&1"

    def run(argv, **kw):
        assert argv[0] == "powershell" and "Get-ScheduledTask" in argv[-1]
        return cp(0, f"STATE=Ready\nARGS={task_args(script)}\n")

    out = dr.check_scheduled_task("Windows", run)
    assert levels(out) == [dr.OK] and "docker grading on" in out[0].detail
    assert "github write off" in out[0].detail

    def no_docker(argv, **kw):
        return cp(0, f"STATE=Ready\nARGS={task_args('& $python -m scripts.run_hourly')}\n")

    out = dr.check_scheduled_task("Windows", no_docker)
    assert levels(out) == [dr.OK, dr.WARN] and "D-086" in out[1].detail


def test_scheduled_task_missing_and_undecodable():
    assert dr.check_scheduled_task("Windows", lambda a, **k: cp(0, ""))[0].level == dr.WARN
    bad = dr.check_scheduled_task("Windows", lambda a, **k: cp(0, "STATE=Ready\nARGS=-Command x\n"))
    assert bad[0].level == dr.WARN and "decoded" in bad[0].detail


# --- the whole run --------------------------------------------------------------------------------


def test_run_checks_only_asks_read_only_questions_and_exit_code(tmp_path, capsys):
    roster = tmp_path / "roster.yaml"
    roster.write_text(ROSTER, encoding="utf-8")
    asked = []

    def run(argv, **kw):
        asked.append(argv)
        if argv[0] == "docker":
            return cp(0, "27.0.1") if argv[1] == "info" else cp(0, "sha256:abc")
        return cp(0, "")  # powershell: no task registered

    def opener():
        raise RuntimeError("down")

    checks = dr.run_checks(
        roster_path=roster,
        env={"GITHUB_TOKEN": TOKEN},
        network=False,
        run=run,
        opener=opener,
        system="Windows",
    )
    verbs = {tuple(a[:2]) for a in asked}
    assert verbs == {("docker", "info"), ("docker", "image"), ("powershell", "-NoProfile")}
    assert all("Get-ScheduledTask" in a[-1] for a in asked if a[0] == "powershell")
    assert not any(
        w in " ".join(" ".join(a) for a in asked)
        for w in (
            "Register-",
            "Set-ScheduledTask",
            "Start-",
            "Enable-",
            "Disable-",
            "Unregister-",
            " run ",
            " build ",
            " start ",
        )
    )
    assert any(c.level == dr.FAIL and c.name == "database" for c in checks)
    assert all(TOKEN not in c.line() for c in checks)


def test_main_prints_one_line_per_check_and_exits_1_on_a_failure(monkeypatch, capsys):
    monkeypatch.setattr(
        dr,
        "run_checks",
        lambda **kw: [
            dr.Check(dr.OK, "python", "3.13.0"),
            dr.Check(dr.WARN, "roster", "w"),
            dr.Check(dr.FAIL, "database", "down"),
        ],
    )
    lines = []
    assert dr.main(["--no-network"], out=lines.append) == 1
    assert lines[0].startswith("OK") and lines[2].startswith("FAIL")
    assert "1 ok, 1 warning(s), 1 failure(s)" in lines[-1]
    monkeypatch.setattr(dr, "run_checks", lambda **kw: [dr.Check(dr.WARN, "x", "y")])
    assert dr.main(["--no-network"], out=lines.append) == 0


def test_the_doctor_source_has_no_write_to_the_database():
    src = Path(dr.__file__).read_text(encoding="utf-8")
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE", ".commit()", "DROP "):
        assert verb not in src
