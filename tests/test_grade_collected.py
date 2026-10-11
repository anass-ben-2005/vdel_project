"""scripts/grade_collected.py -- the bridge from collected commits to graded attempts.

Real `grade_attempt` (real pytest subprocess, real hidden tests, real freeze rule) is used
throughout; only the GitHub checkout is replaced by a fake that copies a prepared directory,
because a test must not need the network or a student's repo. The one test that DOES run
real git (`checkout_commit`) points it at a local repository instead.

Every DB test runs inside ONE transaction that is rolled back (`run(conn=...)` passes it
through to `grade_attempt`): `traces` is append-only, so rollback is the only cleanup.
Skips when no database is reachable.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from assessment.gap_parser import render_student_file
from scripts import grade_collected as gc
from system import db

STUDENT = "_gc_test"
OTHER = "_gc_other"
ASSIGNMENT = "weather_etl_transform"
CURRICULUM_ROOT = Path(__file__).resolve().parent.parent / "curriculum" / "master"
PKG = CURRICULUM_ROOT / "weather_etl" / "weather_etl"
ALL_GAPS = ["g_tf_clean", "g_tf_convert", "g_tf_timestamp"]

SHA_UNSOLVED = "a" * 40      # older commit: student has not done the work
SHA_SOLVED = "b" * 40        # newer commit: full solution -> 5/5 -> freezes
SHA_AMBIGUOUS = "c" * 40     # touched several files -> raw_commits.assignment_id NULL
SHA_OTHER = "d" * 40         # a different student's commit

REPO_FOR = {(STUDENT, ASSIGNMENT): ("some-owner", "some-repo")}


@pytest.fixture
def txn():
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    yield conn
    conn.rollback()
    conn.close()


def _variant(cur) -> str:
    cur.execute("SELECT DISTINCT master_version FROM gaps WHERE assignment_id=%s", (ASSIGNMENT,))
    (mv,) = cur.fetchone()
    cur.execute(
        "INSERT INTO variants (variant_id, assignment_id, gap_ids, master_version)"
        " VALUES ('_gc_variant', %s, %s, %s)", (ASSIGNMENT, ALL_GAPS, mv),
    )
    return "_gc_variant"


def _attempt(cur, student: str, attempt_no: int, variant_id: str, frozen=False) -> int:
    cur.execute(
        "INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no, variant_id,"
        "  gap_seed, submitted_at) VALUES (%s,'weather_etl',%s,%s,%s,1,%s) RETURNING attempt_id",
        (student, ASSIGNMENT, attempt_no, variant_id, "2026-01-01" if frozen else None),
    )
    return cur.fetchone()[0]


def _commit(cur, sha: str, student: str, assignment, when: str) -> None:
    cur.execute(
        "INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
        " VALUES (%s,%s,%s,%s)", (sha, student, assignment, when),
    )


@pytest.fixture
def world(txn, tmp_path):
    """Two students, one attempt for STUDENT, four collected commits, and two prepared
    'checkouts': an unsolved repo and a fully solved one."""
    cur = txn.cursor()
    for s in (STUDENT, OTHER):
        cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (s, s))
    variant_id = _variant(cur)
    attempt_id = _attempt(cur, STUDENT, 1, variant_id)
    _attempt(cur, OTHER, 1, variant_id)
    _commit(cur, SHA_UNSOLVED, STUDENT, ASSIGNMENT, "2026-08-25 01:00:00+00")
    _commit(cur, SHA_SOLVED, STUDENT, ASSIGNMENT, "2026-08-25 02:00:00+00")
    _commit(cur, SHA_AMBIGUOUS, STUDENT, None, "2026-08-25 03:00:00+00")
    _commit(cur, SHA_OTHER, OTHER, ASSIGNMENT, "2026-08-25 04:00:00+00")

    master = (PKG / "transform.py").read_text(encoding="utf-8")
    repos = {}
    for sha, text in ((SHA_UNSOLVED, render_student_file(master, hide_gap_ids=ALL_GAPS)),
                      (SHA_SOLVED, master)):
        root = tmp_path / f"prepared_{sha[0]}"
        (root / "weather_etl").mkdir(parents=True)
        (root / "weather_etl" / "transform.py").write_text(text, encoding="utf-8")
        shutil.copyfile(PKG / "__init__.py", root / "weather_etl" / "__init__.py")
        repos[sha] = root

    calls = []

    def fake_checkout(owner, repo, sha, dest):
        calls.append((owner, repo, sha))
        shutil.copytree(repos[sha], dest)

    return txn, attempt_id, fake_checkout, calls


def _graded_rows(conn, attempt_id):
    cur = conn.cursor()
    cur.execute(
        "SELECT commit_sha, count(*), count(*) FILTER (WHERE passed) FROM test_results"
        " WHERE attempt_id=%s GROUP BY commit_sha ORDER BY commit_sha", (attempt_id,),
    )
    return cur.fetchall()


# --- behaviour ---------------------------------------------------------------------------

def test_grades_every_ungraded_commit_oldest_first_and_freezes_only_on_the_passing_one(world):
    conn, attempt_id, fake_checkout, calls = world

    summary = gc.run(student=STUDENT, repo_for=REPO_FOR, checkout=fake_checkout, conn=conn)

    assert [sha for _, sha, *_ in summary["graded"]] == [SHA_UNSOLVED, SHA_SOLVED]  # oldest first
    assert calls == [("some-owner", "some-repo", SHA_UNSOLVED),
                     ("some-owner", "some-repo", SHA_SOLVED)]
    assert summary["failed"] == [] and summary["no_repo"] == []
    assert summary["unattributed_commits"] == 1          # the NULL-assignment commit, reported
    assert SHA_AMBIGUOUS not in {c[2] for c in calls}    # ... and never graded
    assert SHA_OTHER not in {c[2] for c in calls}        # other student excluded by --student

    # both commits' outcomes are kept (D-045c): 0/5 then 5/5
    assert _graded_rows(conn, attempt_id) == [(SHA_UNSOLVED, 5, 0), (SHA_SOLVED, 5, 5)]

    cur = conn.cursor()
    cur.execute("SELECT commit_sha, submitted_at IS NOT NULL, tests_passed, tests_total"
                " FROM attempts WHERE attempt_id=%s", (attempt_id,))
    assert cur.fetchone() == (SHA_SOLVED, True, 5, 5)    # froze on the commit that earned it


def test_a_second_run_grades_nothing(world):
    conn, attempt_id, fake_checkout, calls = world
    gc.run(student=STUDENT, repo_for=REPO_FOR, checkout=fake_checkout, conn=conn)
    before = (_graded_rows(conn, attempt_id), len(calls))

    again = gc.run(student=STUDENT, repo_for=REPO_FOR, checkout=fake_checkout, conn=conn)

    assert again["pending"] == 0 and again["graded"] == []
    assert (_graded_rows(conn, attempt_id), len(calls)) == before     # no rows, no checkouts
    cur = conn.cursor()
    cur.execute(
        "SELECT count(*) FROM traces WHERE student_id=%s AND kind='test_result'", (STUDENT,)
    )
    assert cur.fetchone()[0] == 10          # 5 + 5, not doubled


def test_a_commit_after_the_freeze_is_collected_but_not_graded(world):
    """D-069 (1d): the attempt froze at SHA_SOLVED. A later push stays in raw_commits but gets
    no test_results row and no mastery observation; it is counted in the summary instead."""
    conn, attempt_id, fake_checkout, calls = world
    gc.run(student=STUDENT, repo_for=REPO_FOR, checkout=fake_checkout, conn=conn)
    cur = conn.cursor()
    late = "e" * 40
    _commit(cur, late, STUDENT, ASSIGNMENT, "2026-08-25 09:00:00+00")
    cur.execute("SELECT count(*) FROM traces WHERE student_id=%s AND kind='test_result'",
                (STUDENT,))
    traces_before = cur.fetchone()[0]
    n_calls = len(calls)

    again = gc.run(student=STUDENT, repo_for=REPO_FOR, checkout=fake_checkout, conn=conn)

    assert again["pending"] == 0 and again["graded"] == []
    assert again["post_freeze_commits_skipped"] == 1
    assert len(calls) == n_calls                          # not even checked out
    assert late not in {r[0] for r in _graded_rows(conn, attempt_id)}
    cur.execute("SELECT count(*) FROM traces WHERE student_id=%s AND kind='test_result'",
                (STUDENT,))
    assert cur.fetchone()[0] == traces_before
    cur.execute("SELECT commit_sha FROM attempts WHERE attempt_id=%s", (attempt_id,))
    assert cur.fetchone()[0] == SHA_SOLVED                # the freeze did not move


def test_dry_run_fetches_and_writes_nothing(world):
    conn, attempt_id, fake_checkout, calls = world

    summary = gc.run(student=STUDENT, dry_run=True, repo_for=REPO_FOR,
                     checkout=fake_checkout, conn=conn)

    assert len(summary["would_grade"]) == 2 and summary["graded"] == []
    assert calls == [] and _graded_rows(conn, attempt_id) == []


def test_latest_only_grades_just_the_newest_commit(world):
    conn, attempt_id, fake_checkout, _ = world

    summary = gc.run(student=STUDENT, latest_only=True, repo_for=REPO_FOR,
                     checkout=fake_checkout, conn=conn)

    assert [sha for _, sha, *_ in summary["graded"]] == [SHA_SOLVED]
    assert _graded_rows(conn, attempt_id) == [(SHA_SOLVED, 5, 5)]


def test_assignment_filter_excludes_other_assignments(world):
    conn, _, fake_checkout, calls = world
    summary = gc.run(student=STUDENT, assignment="weather_etl_extract", repo_for=REPO_FOR,
                     checkout=fake_checkout, conn=conn)
    assert summary["pending"] == 0 and calls == []


def test_one_failing_checkout_does_not_stop_the_rest(world):
    conn, _, fake_checkout, _ = world

    def flaky(owner, repo, sha, dest):
        if sha == SHA_UNSOLVED:
            raise RuntimeError("git fetch failed: simulated")
        fake_checkout(owner, repo, sha, dest)

    summary = gc.run(student=STUDENT, repo_for=REPO_FOR, checkout=flaky, conn=conn)

    assert len(summary["failed"]) == 1 and "simulated" in summary["failed"][0][1]
    assert [sha for _, sha, *_ in summary["graded"]] == [SHA_SOLVED]
    # the failed commit left nothing behind, so a later run retries it (not silently lost)
    assert gc.run(student=STUDENT, dry_run=True, repo_for=REPO_FOR, conn=conn)["would_grade"]


def test_an_attempt_with_no_roster_entry_is_reported_not_graded(world):
    conn, _, fake_checkout, calls = world
    summary = gc.run(student=STUDENT, repo_for={}, checkout=fake_checkout, conn=conn)
    assert len(summary["no_repo"]) == 2 and calls == [] and summary["graded"] == []


def test_commits_belong_to_the_open_attempt_not_a_frozen_one(world):
    conn, attempt_1, _, _ = world
    cur = conn.cursor()
    cur.execute("UPDATE attempts SET submitted_at = now() WHERE attempt_id=%s", (attempt_1,))
    attempt_2 = _attempt(cur, STUDENT, 2, "_gc_variant")      # open

    pending, _ = gc.find_pending(cur, REPO_FOR, student=STUDENT)

    assert {p.attempt_id for p in pending} == {attempt_2}


# --- real git, local remote --------------------------------------------------------------

def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def test_checkout_commit_fetches_exactly_the_requested_sha_and_cleanup_survives_readonly(tmp_path):
    try:
        _git(tmp_path, "--version")
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("git not available")

    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "-q")
    _git(remote, "config", "user.email", "t@example.com")
    _git(remote, "config", "user.name", "t")
    _git(remote, "config", "uploadpack.allowAnySHA1InWant", "true")
    (remote / "f.txt").write_text("first")
    _git(remote, "add", ".")
    _git(remote, "commit", "-q", "-m", "one")
    first = _git(remote, "rev-parse", "HEAD")
    (remote / "f.txt").write_text("second")
    _git(remote, "commit", "-qam", "two")                      # HEAD has moved on

    dest = tmp_path / "work" / "repo"
    dest.parent.mkdir()
    gc.checkout_commit(None, None, first, dest, remote_url=remote.as_uri())

    assert (dest / "f.txt").read_text() == "first"             # the commit asked for, not HEAD
    assert _git(dest, "rev-parse", "HEAD") == first

    gc._remove_tree(dest.parent)                                # git's object files are read-only
    assert not dest.parent.exists()
