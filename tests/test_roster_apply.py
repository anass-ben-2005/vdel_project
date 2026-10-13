"""D-105 -- scripts/roster_apply.py, the delivery hint, and the roster warning of the cycle.

The roster tests work on temporary copies only: the real config/roster.yaml is never opened. No
network, no GITHUB_TOKEN. The cycle-warning tests use the throwaway test database.
"""

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from scripts import deliver_next_attempt as dna
from scripts import roster_apply as ra
from scripts import run_cycle as rc
from system import db
from tests.support import ensure_variant

OLD = "vdel-weather-etl-gapfill-anas-extract-attempt2"
NEW = "vdel-weather-etl-gapfill-anas-extract-attempt3"
NOW = datetime(2026, 10, 13, 9, 30, 0, tzinfo=UTC)

ROSTER = f"""# my roster -- hand edited, comments must survive
students:
  - student_id: anas
    github_username: anas-gh      # real login
    cohort: vdel-2026
assignments:
  - assignment_id: weather_etl_extract
    owner: anas-gh
    repo: {OLD}    # attempt 2
    student_id: anas
    released_at: 2026-10-01T00:00:00Z
    due_at: null
    concepts: []
  - assignment_id: weather_etl_load
    owner: anas-gh
    repo: vdel-weather-etl-gapfill-anas-load
    student_id: anas
    released_at: 2026-10-02T00:00:00Z
    due_at: null
    concepts: []
"""


@pytest.fixture(autouse=True)
def _nothing_leaves_the_machine(monkeypatch):
    import requests

    def boom(*a, **k):
        raise AssertionError("no network in these tests")

    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(requests, "request", boom)
    monkeypatch.setattr(requests.Session, "request", boom)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_THISMUSTNEVERBEWRITTEN0123456789")


@pytest.fixture
def roster(tmp_path):
    path = tmp_path / "roster.yaml"
    path.write_bytes(ROSTER.encode("utf-8"))
    return path


def go(roster, **kw):
    lines: list[str] = []
    args = {
        "student": "anas",
        "assignment": "weather_etl_extract",
        "owner": "anas-gh",
        "repo": NEW,
        "roster_path": roster,
        "now": NOW,
        "out": lines.append,
    }
    args.update(kw)
    return ra.run(**args), "\n".join(lines)


def siblings(roster):
    return sorted(p.name for p in roster.parent.iterdir())


# --- refuses without --yes ------------------------------------------------------------------------


def test_without_yes_it_shows_the_diff_and_writes_nothing(roster):
    before = roster.read_bytes()
    code, out = go(roster)
    assert code == ra.EXIT_REFUSED
    assert f"-    repo: {OLD}" in out and f"+    repo: {NEW}" in out  # a real unified diff
    assert "--yes was not given" in out
    assert roster.read_bytes() == before and siblings(roster) == ["roster.yaml"]  # no backup either


# --- applies with --yes: backup, comments, the other rows ----------------------------------------


def test_with_yes_it_backs_up_then_changes_only_that_row(roster):
    before = roster.read_text(encoding="utf-8")
    code, out = go(roster, yes=True)
    assert code == ra.EXIT_OK, out
    backup = roster.parent / "roster.yaml.20261013T093000Z.bak"
    assert backup.read_text(encoding="utf-8") == before  # the exact old bytes
    after = roster.read_text(encoding="utf-8")
    assert "# my roster -- hand edited, comments must survive" in after and "# real login" in after
    rows = {r["assignment_id"]: r for r in yaml.safe_load(after)["assignments"]}
    assert rows["weather_etl_extract"]["repo"] == NEW
    assert (
        rows["weather_etl_extract"]["released_at"]
        == yaml.safe_load(before)["assignments"][0]["released_at"]
    )  # never moved
    assert rows["weather_etl_load"] == yaml.safe_load(before)["assignments"][1]  # untouched
    assert not (roster.parent / "roster.yaml.tmp").exists()


def test_a_second_apply_is_a_no_op_and_a_second_backup_never_overwrites_the_first(roster):
    go(roster, yes=True)
    code, out = go(roster, yes=True)
    assert code == ra.EXIT_OK and "already up to date" in out
    assert len([n for n in siblings(roster) if n.endswith(".bak")]) == 1
    # a different change at the same second gets its own backup name
    go(roster, yes=True, repo="another-repo")
    baks = [n for n in siblings(roster) if n.endswith(".bak")]
    assert len(baks) == 2 and len(set(baks)) == 2


def test_crlf_line_endings_are_kept(roster):
    roster.write_bytes(ROSTER.replace("\n", "\r\n").encode("utf-8"))
    code, _ = go(roster, yes=True)
    assert code == ra.EXIT_OK
    data = roster.read_bytes()
    assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b"")


# --- refuses an ambiguous target ------------------------------------------------------------------


def test_two_rows_for_the_same_student_and_assignment_is_ambiguous(roster):
    text = (
        ROSTER
        + f"""  - assignment_id: weather_etl_extract
    owner: anas-gh
    repo: {OLD}
    student_id: anas
    released_at: 2026-10-05T00:00:00Z
    concepts: []
"""
    )
    roster.write_bytes(text.encode("utf-8"))
    before = roster.read_bytes()
    code, out = go(roster, yes=True)
    assert code == ra.EXIT_REFUSED and "2 rows for (anas, weather_etl_extract)" in out
    assert roster.read_bytes() == before and siblings(roster) == ["roster.yaml"]


def test_a_row_with_two_repo_lines_or_none_is_ambiguous(roster):
    doubled = ROSTER.replace(
        f"    repo: {OLD}    # attempt 2\n", f"    repo: {OLD}\n    repo: {OLD}x\n"
    )
    roster.write_bytes(doubled.encode("utf-8"))
    code, out = go(roster, yes=True)
    assert code == ra.EXIT_REFUSED and "2 `repo:` line(s)" in out
    missing = ROSTER.replace(f"    repo: {OLD}    # attempt 2\n", "")
    roster.write_bytes(missing.encode("utf-8"))
    code, out = go(roster, yes=True)
    assert code == ra.EXIT_REFUSED and "0 `repo:` line(s)" in out


def test_a_student_listed_twice_and_a_broken_file_are_refused_and_so_is_an_inline_list(
    roster,
):
    twice = ROSTER.replace(
        "assignments:",
        """  - student_id: anas
    github_username: other
    cohort: x
assignments:""",
        1,
    )
    roster.write_bytes(twice.encode("utf-8"))
    assert "appears 2 times" in go(roster, yes=True)[1]
    roster.write_bytes(b"students: [\n")
    code, out = go(roster, yes=True)
    assert code == ra.EXIT_REFUSED and "does not parse" in out
    roster.write_bytes(b"students: []\nassignments: []\n")
    code, out = go(
        roster,
        yes=True,
        assignment="weather_etl_extract",
        released_at="2026-10-13T00:00:00Z",
        github_username="anas-gh",
    )
    assert code == ra.EXIT_REFUSED and "inline value" in out   # block-style lists only
    assert roster.read_bytes() == b"students: []\nassignments: []\n"        # untouched


def test_a_missing_roster_is_refused(tmp_path):
    code, out = go(tmp_path / "nope.yaml", yes=True)
    assert code == ra.EXIT_REFUSED and "not found" in out


# --- a new row needs a real date ------------------------------------------------------------------


def test_a_new_row_needs_released_at_and_never_invents_one(roster):
    code, out = go(roster, assignment="weather_etl_transform", yes=True)
    assert code == ra.EXIT_REFUSED and "--released-at" in out
    code, out = go(
        roster, assignment="weather_etl_transform", yes=True, released_at="2026-10-13T08:00:00Z"
    )
    assert code == ra.EXIT_OK, out
    rows = {r["assignment_id"]: r for r in yaml.safe_load(roster.read_text("utf-8"))["assignments"]}
    assert rows["weather_etl_transform"]["repo"] == NEW


def test_an_unknown_student_needs_a_github_username(roster):
    code, out = go(roster, student="bea", yes=True, released_at="2026-10-13T08:00:00Z")
    assert code == ra.EXIT_REFUSED and "--github-username" in out


# --- never a token --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "github_pat_11ABCDEFG0abcdefghijklmnop",
        "sk-abcdefghijklmnopqrstuvwxyz",
        "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ",
    ],
)
def test_a_credential_in_any_argument_is_refused_and_nothing_is_written(roster, secret):
    before = roster.read_bytes()
    for field in ("repo", "owner"):
        code, out = go(roster, yes=True, **{field: secret})
        assert code == ra.EXIT_REFUSED and "credential" in out
        assert secret not in out  # not even echoed back
    assert roster.read_bytes() == before and siblings(roster) == ["roster.yaml"]


def test_a_repo_name_that_merely_contains_sk_dash_is_not_taken_for_a_secret(roster):
    code, out = go(roster, yes=True, repo="vdel-task-sk-etl-attempt3")
    assert code == ra.EXIT_OK, out


def test_the_environment_token_never_reaches_the_roster_or_the_output(roster):
    code, out = go(roster, yes=True)
    assert code == ra.EXIT_OK
    token = os.environ["GITHUB_TOKEN"]
    assert token not in out and token not in roster.read_text("utf-8")
    assert all(token not in p.read_text("utf-8") for p in roster.parent.iterdir())


def test_the_source_reads_no_environment_file_and_makes_no_network_call():
    lines = Path(ra.__file__).read_text(encoding="utf-8").splitlines()
    code = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))
    body = code.split('"""', 2)[2]  # after the module docstring
    for needle in (
        "os.environ",
        "getenv",
        "dotenv",
        "import requests",
        "urllib",
        "socket",
        "GITHUB_TOKEN",
    ):
        assert needle not in body, needle


def test_main_parses_the_flags(roster, capsys):
    lines: list[str] = []
    code = ra.main(
        [
            "--student",
            "anas",
            "--assignment",
            "weather_etl_extract",
            "--owner",
            "anas-gh",
            "--repo",
            NEW,
            "--roster",
            str(roster),
        ],
        out=lines.append,
    )
    assert code == ra.EXIT_REFUSED and any("--yes was not given" in ln for ln in lines)
    assert (
        ra.main(
            [
                "--student",
                "anas",
                "--assignment",
                "weather_etl_extract",
                "--owner",
                "anas-gh",
                "--repo",
                NEW,
                "--roster",
                str(roster),
                "--yes",
            ],
            out=lines.append,
        )
        == 0
    )


# --- the "Next:" hint -----------------------------------------------------------------------------


def make_plan(**kw):
    base = {
        "student": "anas",
        "assignment": "weather_etl_extract",
        "project_id": "weather_etl",
        "username": "anas-gh",
        "current_attempt_id": 1,
        "current_no": 2,
        "next_no": 3,
        "resume": False,
        "repo_name": NEW,
        "old_owner": "anas-gh",
        "old_repo": OLD,
        "refusals": [],
        "decision_message": "",
    }
    base.update(kw)
    return dna.Plan(**base)


def test_the_delivery_hint_points_to_roster_apply_then_the_task_never_to_grade_collected():
    text = dna.next_hint(make_plan(), "anas-gh")
    assert "scripts.roster_apply --student anas --assignment weather_etl_extract" in text
    assert f"--owner anas-gh --repo {NEW} --yes" in text
    assert "VDEL hourly" in text and "VDEL_GRADING_SANDBOX=docker" in text
    assert (
        "grade_collected --student" not in text and "python -m scripts.grade_collected" not in text
    )


def test_the_default_publish_hint_no_longer_sends_the_reader_to_grade_collected():
    src = Path(dna.pr.__file__).read_text(encoding="utf-8")
    assert "scripts.grade_collected --student" not in src
    assert "never run grade_collected by hand outside" in src


# --- the cycle warns about an open attempt the roster cannot reach --------------------------------


def _open_attempt(conn, sid, assignment, attempt_no):
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO students VALUES (%s,%s,'vdel-2026') ON CONFLICT DO NOTHING", (sid, sid)
    )
    cur.execute(
        "INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
        " variant_id, gap_seed) VALUES (%s,'weather_etl',%s,%s,%s,1)",
        (sid, assignment, attempt_no, ensure_variant(cur, assignment)),
    )


@pytest.fixture
def conn():
    if not os.environ.get("PG_DSN"):
        pytest.skip("PG_DSN not set")
    c = db._open()
    yield c
    c.rollback()
    c.close()


def roster_dict(sid, *rows):
    return {
        "assignments": [
            {"owner": "o", "repo": repo, "student_id": sid, "assignment_id": a} for a, repo in rows
        ]
    }


def cycle(conn, roster, sid):
    lines: list[str] = []
    result = rc.run_cycle(roster, student=sid, conn=conn, dry_run=True, out=lines.append)
    return result, [ln for ln in lines if "WARN" in ln]


def test_an_open_attempt_with_no_roster_row_is_warned_about(conn):
    _open_attempt(conn, "_ra_a", "weather_etl_transform", 1)
    roster = roster_dict("_ra_a", ("weather_etl_load", "repo-load"))  # some row, but not this one
    result, warns = cycle(conn, roster, "_ra_a")
    assert result.exit_code == 0  # a report, not a failure
    assert len(warns) == 1
    assert "weather_etl_transform" in warns[0] and "no roster repo" in warns[0]
    assert "roster_apply" in warns[0]


def test_attempt_2_or_later_whose_roster_repo_is_an_earlier_one_is_warned_about(conn):
    _open_attempt(conn, "_ra_b", "weather_etl_transform", 2)
    roster = roster_dict("_ra_b", ("weather_etl_transform", "vdel-weather-etl-gapfill-_ra_b"))
    _, warns = cycle(conn, roster, "_ra_b")
    assert len(warns) == 1 and "the delivery names" in warns[0]
    assert "vdel-weather-etl-gapfill-_ra_b-transform-attempt2" in warns[0]


def test_a_matching_roster_row_and_a_frozen_attempt_give_no_warning(conn):
    _open_attempt(conn, "_ra_c", "weather_etl_transform", 2)
    right = "vdel-weather-etl-gapfill-_ra_c-transform-attempt2"
    _, warns = cycle(conn, roster_dict("_ra_c", ("weather_etl_transform", right)), "_ra_c")
    assert warns == []
    conn.cursor().execute("UPDATE attempts SET submitted_at = now() WHERE student_id = '_ra_c'")
    # frozen (submitted): not open, so even a wrong repo is not reported
    _, warns = cycle(conn, roster_dict("_ra_c", ("weather_etl_transform", "elsewhere")), "_ra_c")
    assert warns == []


def test_attempt_1_is_never_compared_with_the_delivery_name(conn):
    _open_attempt(conn, "_ra_d", "weather_etl_transform", 1)
    _, warns = cycle(
        conn, roster_dict("_ra_d", ("weather_etl_transform", "any-legacy-name")), "_ra_d"
    )
    assert warns == []


def test_the_warning_reaches_the_hourly_log_through_the_same_output(conn, tmp_path):
    from scripts import run_hourly as rh

    _open_attempt(conn, "_ra_e", "weather_etl_transform", 1)
    roster_file = tmp_path / "roster.yaml"
    roster_file.write_text(
        yaml.safe_dump(roster_dict("_ra_e", ("weather_etl_load", "repo-load"))), encoding="utf-8"
    )
    lines: list[str] = []
    rh.run(
        roster_path=roster_file,
        dry_run=True,
        conn=conn,
        out=lines.append,
        env={"LLM_PROVIDER": "openai"},
    )
    assert any("WARN" in ln and "no roster repo" in ln for ln in lines)
