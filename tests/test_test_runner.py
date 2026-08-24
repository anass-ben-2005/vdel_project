"""Live D-045/D-047(mastery-wiring) demonstration: assessment/test_runner.py against the
real weather_etl curriculum (real assignments, real variants, real hidden tests),
proving the freeze rule AND the test_result -> memory.py mastery wiring end to end
rather than by inspection:

  - a LOCAL run (no commit_sha) writes test_results but never freezes, even at 100% pass
    -- there is no real commit yet to record as the one that froze the attempt.
  - a PUSHED run (real commit_sha, present in raw_commits) at 100% pass DOES freeze:
    attempts.commit_sha/submitted_at/tests_passed/tests_total all get written.
  - re-grading an ALREADY-frozen attempt against a DIFFERENT commit does not move the
    freeze -- commit_sha stays on the first commit that earned it -- but the second
    commit's own results still land in test_results, AND its own test_result traces are
    still logged (D-045c/EXECUTION.md Stage C1: every commit is a real BKT observation,
    frozen or not).
  - re-grading the SAME commit a second time does NOT log a second set of traces (the
    `xmax = 0` new-row check) -- BKT's observation count must not inflate just because
    grading ran twice against evidence it already has.

ROLLBACK, NOT DELETE, for cleanup -- and this is not a style choice, it is required.
`traces` is append-only at the database level (a Postgres RULE makes DELETE silently
affect 0 rows -- confirmed live before this file was written this way, not assumed), so
once `grade_attempt` logs a real `test_result` trace there is no SQL that can remove it.
The whole scenario -- setup, both `grade_attempt` calls, and every assertion -- therefore
runs inside ONE transaction on a connection this file opens itself and never commits;
`grade_attempt`'s `conn=` parameter exists for exactly this caller. Reads see the
transaction's own uncommitted writes (ordinary read-your-own-writes), so assertions work
identically to the old commit-then-DELETE version; only the teardown mechanism differs.

`_test_runner_v2`, not `_test_runner`: an earlier version of this file used
DELETE-based teardown, which silently failed once `test_result` traces existed (the
DELETE affected 0 rows, discovered live, not assumed) and left a permanent orphaned
`_test_runner` row (5 real traces, un-deletable by design) in the dev DB. That row is
harmless and stays -- deleting it would mean fighting invariant 1, which this project
does not do even for test hygiene. This file uses a different identity so the fixture's
own INSERT does not collide with that permanent leftover.

Skips when no database is reachable, matching tests/test_pipeline_integration.py's and
tests/test_collect_attribution.py's own convention.
"""
import os
import shutil
from pathlib import Path

import pytest

from assessment import test_runner as tr
from system import db

STUDENT = "_test_runner_v2"
CURRICULUM_ROOT = Path(__file__).resolve().parent.parent / "curriculum" / "master"


@pytest.fixture
def solved_transform_repo(tmp_path):
    """A repo whose transform.py is the real, unmodified master solution -- standing in
    for "a student who passed everything," without hand-writing a fixture that could
    drift from the real hidden tests' actual expectations. The `# @gap:` marker comments
    stay in (this is the literal master file, not a rendered one); they are comments and
    do not affect behaviour, and using the render pipeline here would be testing the
    renderer again, not the test runner.
    """
    src_dir = CURRICULUM_ROOT / "weather_etl" / "weather_etl"
    dest_dir = tmp_path / "weather_etl"
    dest_dir.mkdir()
    shutil.copyfile(src_dir / "transform.py", dest_dir / "transform.py")
    shutil.copyfile(src_dir / "__init__.py", dest_dir / "__init__.py")
    return tmp_path


@pytest.fixture
def freeze_scenario(solved_transform_repo):
    """Yields (conn, attempt_id, repo_dir). `conn` is the SAME connection every
    `grade_attempt` call and every assertion in the test must use -- passing it through
    is what keeps everything, including the traces `grade_attempt` logs, inside the one
    transaction this fixture rolls back at teardown.
    """
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")

    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (STUDENT, STUDENT))
    cur.execute(
        "SELECT variant_id FROM variants WHERE assignment_id=%s", ("weather_etl_transform",)
    )
    variant_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
        "  variant_id, gap_seed) VALUES (%s,'weather_etl','weather_etl_transform',1,%s,1)"
        " RETURNING attempt_id",
        (STUDENT, variant_id),
    )
    attempt_id = cur.fetchone()[0]
    cur.executemany(
        "INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at,"
        "  additions, deletions, files_changed, message)"
        " VALUES (%s,%s,'weather_etl_transform', now(), 1, 0, 1, 'test commit')",
        [("_test_runner_v2_sha_1", STUDENT), ("_test_runner_v2_sha_2", STUDENT)],
    )
    # NOT committed -- everything from here stays inside this one transaction.

    yield conn, attempt_id, solved_transform_repo

    conn.rollback()
    conn.close()


pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)


def test_local_run_never_freezes_even_at_100_percent(freeze_scenario, capsys):
    conn, attempt_id, repo_dir = freeze_scenario

    result = tr.grade_attempt(
        "weather_etl", "weather_etl_transform", repo_dir, attempt_id,
        commit_sha=None, conn=conn,
    )
    print(f"\nD-045 local run: {result.tests_passed}/{result.tests_total} "
          f"frozen={result.frozen}")

    assert result.tests_total == 5
    assert result.tests_passed == 5          # the real master solution passes everything
    assert result.frozen is False             # but there is no real commit to freeze on

    # D-046: every outcome carries the gap_id its @pytest.mark.gap(...) declared -- read
    # from RunResult directly, not only from the DB, so a failure here points at the
    # marker/conftest mechanism itself rather than only at the write path.
    gap_ids_seen = {o.gap_id for o in result.outcomes}
    assert gap_ids_seen == {"g_tf_clean", "g_tf_convert", "g_tf_timestamp"}
    assert all(o.gap_id is not None for o in result.outcomes)

    cur = conn.cursor()
    cur.execute("SELECT commit_sha FROM attempts WHERE attempt_id=%s", (attempt_id,))
    assert cur.fetchone()[0] is None
    cur.execute(
        "SELECT count(*) FROM test_results"
        " WHERE attempt_id=%s AND commit_sha IS NULL AND gap_id IS NOT NULL",
        (attempt_id,),
    )
    assert cur.fetchone()[0] == 5

    # Stage C1 mastery wiring: a LOCAL run is still a real observation (D-045a's freeze
    # gate is about attempts.commit_sha, not about what counts as BKT evidence) -- five
    # test_result traces, one per outcome, all logged even though nothing froze.
    cur.execute(
        "SELECT count(*) FROM traces WHERE student_id=%s AND kind='test_result'",
        (STUDENT,),
    )
    assert cur.fetchone()[0] == 5


def test_pushed_run_at_100_percent_freezes_and_re_grading_does_not_move_it(
    freeze_scenario, capsys
):
    conn, attempt_id, repo_dir = freeze_scenario

    first = tr.grade_attempt(
        "weather_etl", "weather_etl_transform", repo_dir, attempt_id,
        commit_sha="_test_runner_v2_sha_1", conn=conn,
    )
    assert first.frozen is True

    cur = conn.cursor()
    cur.execute(
        "SELECT commit_sha, submitted_at IS NOT NULL, tests_passed, tests_total"
        " FROM attempts WHERE attempt_id=%s", (attempt_id,),
    )
    frozen_state = cur.fetchone()
    print(f"\nD-045 pushed run: {frozen_state}")
    assert frozen_state == ("_test_runner_v2_sha_1", True, 5, 5)

    # A second, later commit is graded too -- re-grading an ALREADY-frozen attempt.
    second = tr.grade_attempt(
        "weather_etl", "weather_etl_transform", repo_dir, attempt_id,
        commit_sha="_test_runner_v2_sha_2", conn=conn,
    )
    assert second.frozen is False        # guarded: already frozen, does not move

    cur.execute("SELECT commit_sha FROM attempts WHERE attempt_id=%s", (attempt_id,))
    # still the FIRST commit -- the freeze never moved to the second.
    assert cur.fetchone()[0] == "_test_runner_v2_sha_1"

    # D-045c: BOTH commits' results survive as separate rows, not one overwriting
    # the other -- this is the entire point of keying test_results by commit.
    cur.execute(
        "SELECT commit_sha, count(*) FROM test_results WHERE attempt_id=%s"
        " GROUP BY commit_sha ORDER BY commit_sha", (attempt_id,),
    )
    by_commit = dict(cur.fetchall())
    print(f"D-045 pushed run: test_results per commit = {by_commit}")
    assert by_commit == {"_test_runner_v2_sha_1": 5, "_test_runner_v2_sha_2": 5}

    # Stage C1: BOTH commits' outcomes are BKT observations -- 5 + 5 = 10 test_result
    # traces, not 5. Grading a later commit must not overwrite or shadow the earlier
    # commit's evidence, mirroring test_results' own D-045c guarantee at the trace layer.
    cur.execute(
        "SELECT count(*) FROM traces WHERE student_id=%s AND kind='test_result'",
        (STUDENT,),
    )
    assert cur.fetchone()[0] == 10


def test_re_grading_the_same_commit_does_not_double_log_traces(freeze_scenario):
    """The `xmax = 0` new-row check, proven directly: grading the same commit twice
    must log five traces total, not ten -- re-running grading against evidence already
    recorded must not inflate BKT's observation count (invariant 8)."""
    conn, attempt_id, repo_dir = freeze_scenario

    tr.grade_attempt(
        "weather_etl", "weather_etl_transform", repo_dir, attempt_id,
        commit_sha="_test_runner_v2_sha_1", conn=conn,
    )
    tr.grade_attempt(
        "weather_etl", "weather_etl_transform", repo_dir, attempt_id,
        commit_sha="_test_runner_v2_sha_1", conn=conn,
    )

    cur = conn.cursor()
    cur.execute(
        "SELECT count(*) FROM traces WHERE student_id=%s AND kind='test_result'",
        (STUDENT,),
    )
    assert cur.fetchone()[0] == 5
