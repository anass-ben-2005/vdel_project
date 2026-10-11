"""D-071 -- scripts/run_cycle.py, on the throwaway test database with a FAKE GitHub layer.

No network: `collect` inserts the rows a real collection would, `checkout` copies a prepared
directory. Everything else is the real code: the real grader (a real pytest subprocess), the
real feature computation, the real Memory. One transaction per test, rolled back at the end
(`conn=` makes the cycle's stages savepoints inside it; traces are append-only).
"""
import os
import shutil
from pathlib import Path

import psycopg2
import pytest

from assessment.gap_parser import render_student_file
from scripts import run_cycle as rc
from system import db
from tests.support import ensure_variant

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

ASSIGNMENT = "weather_etl_transform"
CURRICULUM = Path(__file__).resolve().parent.parent / "curriculum" / "master" / "weather_etl"
SHA = {"_cyc_a": "a" * 40, "_cyc_b": "b" * 40, "_cyc_c": "c" * 40}
NOT_SOLVED_GAPS = ["g_tf_clean", "g_tf_convert", "g_tf_timestamp"]


@pytest.fixture
def conn():
    try:
        c = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    yield c
    c.rollback()
    c.close()


def make_student(conn, sid):
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (sid, sid))
    variant = ensure_variant(cur, ASSIGNMENT)
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl',%s,1,%s,1)",
                (sid, ASSIGNMENT, variant))


def roster_for(*sids):
    return {"assignments": [{"owner": "o", "repo": f"repo-{s}", "student_id": s,
                             "assignment_id": ASSIGNMENT} for s in sids]}


def insert_commit(conn, sid):
    conn.cursor().execute(
        "INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at, additions,"
        " deletions, files_changed, message) VALUES (%s,%s,%s,'2026-08-25 02:00+00',9,1,1,'work')"
        " ON CONFLICT (sha) DO NOTHING", (SHA[sid], sid, ASSIGNMENT))


class FakeGitHub:
    """What a collection would add, and the checkout of the solved file."""

    def __init__(self, tmp_path, fail_for=()):
        self.fail_for, self.collect_calls, self.checkout_calls = set(fail_for), [], []
        master = (CURRICULUM / "weather_etl" / "transform.py").read_text(encoding="utf-8")
        self.root = tmp_path / "solved"
        (self.root / "weather_etl").mkdir(parents=True)
        (self.root / "weather_etl" / "transform.py").write_text(master, encoding="utf-8")
        shutil.copyfile(CURRICULUM / "weather_etl" / "__init__.py",
                        self.root / "weather_etl" / "__init__.py")
        self.unsolved = render_student_file(master, hide_gap_ids=NOT_SOLVED_GAPS)

    def collect(self, c, repos):
        sid = repos[0]["student_id"]
        self.collect_calls.append(sid)
        if sid in self.fail_for:
            raise RuntimeError(f"simulated GitHub outage for {sid}")
        insert_commit(c, sid)
        return {"ok": 1, "failed": [], "stats": "fake"}

    def checkout(self, owner, repo, sha, dest):
        self.checkout_calls.append(sha)
        shutil.copytree(self.root, dest)


def fingerprint(conn, sids):
    """Row count + content hash of everything a cycle can write, for these students."""
    cur = conn.cursor()
    out = {}
    for table, where in (
            ("raw_commits", "student_id = ANY(%s)"),
            ("raw_workflow_runs", "student_id = ANY(%s)"),
            ("attempts", "student_id = ANY(%s)"),
            ("test_results", "attempt_id IN (SELECT attempt_id FROM attempts"
                             " WHERE student_id = ANY(%s))"),
            ("traces", "student_id = ANY(%s)"),
            ("learner_features", "student_id = ANY(%s)"),
            ("learner_profile", "student_id = ANY(%s)")):
        cur.execute(f"SELECT count(*), md5(coalesce(string_agg(t::text, '|' ORDER BY t::text),"
                    f" '')) FROM {table} t WHERE {where}", (list(sids),))
        out[table] = cur.fetchone()
    return out


def cycle(conn, gh, sids, **kw):
    lines = []
    result = rc.run_cycle(roster_for(*sids), conn=conn, collect=gh.collect,
                          checkout=gh.checkout, out=lines.append, **kw)
    return result, lines


def test_a_second_cycle_writes_nothing(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = FakeGitHub(tmp_path)

    first, _ = cycle(conn, gh, ["_cyc_a"])
    (a,) = first.students
    assert first.exit_code == 0 and a.ok
    assert (a.commits_added, a.graded, a.frozen) == (1, 1, 1)
    assert (a.features, a.profile) == ("written", "current")      # run() already synced it
    after_first = fingerprint(conn, ["_cyc_a"])
    assert after_first["traces"][0] > 0 and after_first["learner_features"][0] == 1

    second, lines = cycle(conn, gh, ["_cyc_a"])
    (a2,) = second.students
    assert second.exit_code == 0
    assert (a2.commits_added, a2.graded, a2.frozen) == (0, 0, 0)
    assert (a2.features, a2.profile) == ("up to date", "current")
    assert fingerprint(conn, ["_cyc_a"]) == after_first              # counts AND hashes
    assert len(gh.checkout_calls) == 1                               # the commit is not re-fetched
    assert any("cycle done: 1 ok, 0 failed" in line for line in lines)


def test_one_students_failure_never_stops_the_others(conn, tmp_path):
    for sid in ("_cyc_a", "_cyc_b"):
        make_student(conn, sid)
    gh = FakeGitHub(tmp_path, fail_for={"_cyc_a"})

    result, lines = cycle(conn, gh, ["_cyc_a", "_cyc_b"])

    a, b = result.students
    assert result.exit_code == 1                                     # non-zero: someone failed
    assert not a.ok and any(e.startswith("collect:") for e in a.errors)
    assert b.ok and (b.commits_added, b.graded, b.frozen) == (1, 1, 1)
    assert b.features == "written"
    assert gh.collect_calls == ["_cyc_a", "_cyc_b"]                  # b ran after a failed
    assert any("collect" in line and "FAILED" in line for line in lines)
    assert any("_cyc_a" in line and "FAILED" in line for line in lines)      # the summary row
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM raw_commits WHERE student_id = '_cyc_a'")
    assert cur.fetchone()[0] == 0                                    # a's failed unit left nothing


def test_the_student_option_restricts_the_cycle(conn, tmp_path):
    for sid in ("_cyc_a", "_cyc_b"):
        make_student(conn, sid)
    gh = FakeGitHub(tmp_path)
    lines = []
    result = rc.run_cycle(roster_for("_cyc_a", "_cyc_b"), student="_cyc_b", conn=conn,
                          collect=gh.collect, checkout=gh.checkout, out=lines.append)
    assert [s.student_id for s in result.students] == ["_cyc_b"]
    assert gh.collect_calls == ["_cyc_b"]
    missing = rc.run_cycle(roster_for("_cyc_a"), student="_nobody", conn=conn,
                           collect=gh.collect, checkout=gh.checkout, out=lines.append)
    assert missing.exit_code == 1


def test_a_second_cycle_cannot_overlap_the_first(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = FakeGitHub(tmp_path)
    other = db._open()                       # stands in for "a cycle is already running"
    other.autocommit = True
    other.cursor().execute("SELECT pg_advisory_lock(%s)", (rc.ADVISORY_LOCK_KEY,))
    try:
        before = fingerprint(conn, ["_cyc_a"])
        result, lines = cycle(conn, gh, ["_cyc_a"])
        assert result.exit_code == rc.EXIT_LOCKED and result.students == []
        assert any("ANOTHER CYCLE IS RUNNING" in line for line in lines)
        assert gh.collect_calls == [] and fingerprint(conn, ["_cyc_a"]) == before
    finally:
        other.close()                        # releases the lock
    again, _ = cycle(conn, gh, ["_cyc_a"])   # ... and the lock is free again afterwards
    assert again.exit_code == 0


def test_the_lock_is_released_after_a_cycle(conn, tmp_path):
    make_student(conn, "_cyc_a")
    cycle(conn, FakeGitHub(tmp_path), ["_cyc_a"])
    probe = db._open()
    probe.autocommit = True
    cur = probe.cursor()
    cur.execute("SELECT pg_try_advisory_lock(%s)", (rc.ADVISORY_LOCK_KEY,))
    assert cur.fetchone()[0] is True
    probe.close()


def test_dry_run_writes_nothing_and_never_touches_github(conn, tmp_path):
    make_student(conn, "_cyc_a")
    insert_commit(conn, "_cyc_a")            # collected earlier, not graded yet
    gh = FakeGitHub(tmp_path)
    before = fingerprint(conn, ["_cyc_a"])

    result, lines = cycle(conn, gh, ["_cyc_a"], dry_run=True)

    assert result.exit_code == 0
    assert gh.collect_calls == [] and gh.checkout_calls == []
    assert fingerprint(conn, ["_cyc_a"]) == before                   # counts and hashes
    text = "\n".join(lines)
    assert "WOULD grade 1 commit(s)" in text and "WOULD compute" in text
    assert "DRY-RUN" in text


def test_skip_network_skips_collect_and_grade_but_not_features(conn, tmp_path):
    make_student(conn, "_cyc_a")
    insert_commit(conn, "_cyc_a")
    gh = FakeGitHub(tmp_path)
    result, _ = cycle(conn, gh, ["_cyc_a"], skip_network=True)
    (a,) = result.students
    assert gh.collect_calls == [] and gh.checkout_calls == []
    assert a.graded == 0 and a.features == "written"


def test_with_llm_is_reported_as_not_wired(conn, tmp_path):
    make_student(conn, "_cyc_a")
    _, lines = cycle(conn, FakeGitHub(tmp_path), ["_cyc_a"], with_llm=True)
    assert any("NOT WIRED" in line for line in lines)


def test_an_unreachable_database_exits_at_once_with_a_clear_message(monkeypatch, tmp_path):
    def down():
        raise psycopg2.OperationalError("could not connect to server: Connection refused")
    monkeypatch.setattr(rc.db, "_open", down)
    lines = []
    result = rc.run_cycle(roster_for("_cyc_a"), out=lines.append)
    assert result.exit_code == rc.EXIT_DB_DOWN and result.students == []
    assert any("DATABASE UNREACHABLE" in line and "Connection refused" in line
               for line in lines)
