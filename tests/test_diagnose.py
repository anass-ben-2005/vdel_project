"""assessment/diagnose.py tests -- C10's deterministic diagnosis function.

Real curriculum data, synthetic student/attempt/telemetry: reuses `weather_etl`'s real
`gaps`/`variants` (g_tf_clean, g_tf_convert -> py.data_structures; g_tf_timestamp ->
py.errors_debugging) rather than fabricating a parallel assignment/gap schema --
`tests/test_test_runner.py::freeze_scenario`'s own pattern, reused directly rather than
writing a parallel one.

ROLLBACK, NOT DELETE, matching `test_test_runner.py`'s own reasoning and
`benchmark/run_benchmark.py`'s isolation discipline: everything below runs inside ONE
transaction opened by this file and never committed. `diagnose()` only ever reads, so
there is nothing here `traces`' append-only rule could even be at risk from -- but the
same rollback discipline is used anyway, on principle, matching this session's own
lesson (a `_test_sara`-style permanent leftover is exactly the failure mode a shared,
uncontrolled transaction produces).

Skips when no database is reachable, matching every other DB-touching test in this repo.
"""
import os
from datetime import UTC, datetime, timedelta

import pytest

from assessment.diagnose import diagnose
from system import db

STUDENT = "_test_diagnose"
PROJECT = "weather_etl"
ASSIGNMENT = "weather_etl_transform"

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

_T0 = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def diagnose_scenario():
    """Yields (cur, attempt_id). Three real commits against the real
    `weather_etl_transform` gaps, a fourth against `weather_etl_extract` (to prove
    `attempts_per_stage` counts across sibling assignments in the same project, not
    just this one), and a designed pass/fail pattern across all three of
    `weather_etl_transform`'s real gaps so every Diagnosis field has one unambiguous,
    hand-computed expected value:

      c1 (earliest): g_tf_clean=FAIL  g_tf_convert=PASS  g_tf_timestamp=PASS
      c2:            g_tf_clean=FAIL  g_tf_convert=PASS  g_tf_timestamp=FAIL
      c3 (latest):   g_tf_clean=PASS  g_tf_convert=PASS  g_tf_timestamp=FAIL

    py.data_structures (g_tf_clean + g_tf_convert, 6 observations, 4 passes) -> 0.667.
    py.errors_debugging (g_tf_timestamp, 3 observations, 1 pass) -> 0.333 -- weakest.
    g_tf_clean failed on 2 distinct commits (c1, c2) -> recurrence True.
    g_tf_timestamp failed on 2 distinct commits (c2, c3) -> recurrence True.
    g_tf_convert never failed -> absent from recurrence_flags entirely.
    Only c3 (the latest) is "currently failing": g_tf_timestamp only.
    """
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")

    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (STUDENT, STUDENT))
    cur.execute("SELECT variant_id FROM variants WHERE assignment_id=%s", (ASSIGNMENT,))
    variant_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
        "  variant_id, gap_seed) VALUES (%s,%s,%s,1,%s,1) RETURNING attempt_id",
        (STUDENT, PROJECT, ASSIGNMENT, variant_id),
    )
    attempt_id = cur.fetchone()[0]

    commits = [
        ("_diag_c1", ASSIGNMENT, _T0),
        ("_diag_c2", ASSIGNMENT, _T0 + timedelta(hours=1)),
        ("_diag_c3", ASSIGNMENT, _T0 + timedelta(hours=2)),
        ("_diag_c4", "weather_etl_extract", _T0 + timedelta(hours=3)),
    ]
    cur.executemany(
        "INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at,"
        "  additions, deletions, files_changed, message)"
        " VALUES (%s,%s,%s,%s,1,0,1,'test commit')",
        [(sha, STUDENT, aid, ts) for sha, aid, ts in commits],
    )

    # (commit_sha, gap_id, test_name, passed, ran_at)
    results = [
        ("_diag_c1", "g_tf_clean", "test_clean", False, _T0),
        ("_diag_c1", "g_tf_convert", "test_convert", True, _T0),
        ("_diag_c1", "g_tf_timestamp", "test_timestamp", True, _T0),
        ("_diag_c2", "g_tf_clean", "test_clean", False, _T0 + timedelta(hours=1)),
        ("_diag_c2", "g_tf_convert", "test_convert", True, _T0 + timedelta(hours=1)),
        ("_diag_c2", "g_tf_timestamp", "test_timestamp", False, _T0 + timedelta(hours=1)),
        ("_diag_c3", "g_tf_clean", "test_clean", True, _T0 + timedelta(hours=2)),
        ("_diag_c3", "g_tf_convert", "test_convert", True, _T0 + timedelta(hours=2)),
        ("_diag_c3", "g_tf_timestamp", "test_timestamp", False, _T0 + timedelta(hours=2)),
    ]
    cur.executemany(
        "INSERT INTO test_results (attempt_id, commit_sha, test_name, gap_id, passed, ran_at)"
        " VALUES (%s,%s,%s,%s,%s,%s)",
        [(attempt_id, sha, name, gap_id, passed, ran_at)
         for sha, gap_id, name, passed, ran_at in results],
    )
    # NOT committed -- everything from here stays inside this one transaction.

    yield cur, attempt_id

    conn.rollback()
    conn.close()


def test_weakest_concept_is_the_real_lowest_pass_rate(diagnose_scenario):
    cur, attempt_id = diagnose_scenario
    result = diagnose(cur, attempt_id)
    assert result.weakest_concept == "py.errors_debugging"


def test_recurrence_flags_only_the_gaps_that_failed_twice_or_more(diagnose_scenario):
    cur, attempt_id = diagnose_scenario
    result = diagnose(cur, attempt_id)
    assert result.recurrence_flags == {"g_tf_clean": True, "g_tf_timestamp": True}
    assert "g_tf_convert" not in result.recurrence_flags


def test_failing_tests_is_only_the_latest_commit_not_full_history(diagnose_scenario):
    cur, attempt_id = diagnose_scenario
    result = diagnose(cur, attempt_id)
    assert len(result.failing_tests) == 1
    assert result.failing_tests[0].gap_id == "g_tf_timestamp"
    assert result.failing_tests[0].test_name == "test_timestamp"


def test_attempts_per_stage_counts_real_commits_across_sibling_assignments(diagnose_scenario):
    cur, attempt_id = diagnose_scenario
    result = diagnose(cur, attempt_id)
    assert result.attempts_per_stage["weather_etl_transform"] == 3
    assert result.attempts_per_stage["weather_etl_extract"] == 1
    # never touched by this synthetic student -- present with 0, not omitted
    assert result.attempts_per_stage["weather_etl_load"] == 0
    assert result.attempts_per_stage["weather_etl_quality"] == 0


def test_unknown_attempt_id_raises(diagnose_scenario):
    cur, _attempt_id = diagnose_scenario
    with pytest.raises(ValueError, match="no attempt"):
        diagnose(cur, 999_999_999)


def test_an_attempt_with_no_test_results_yet_is_not_an_error(diagnose_scenario):
    """A freshly-rendered, never-graded attempt -- diagnose() must describe "nothing
    to diagnose yet" honestly, not raise, matching how the rest of this codebase
    treats cold-start absence of evidence as a real, valid state."""
    cur, _old_attempt_id = diagnose_scenario
    cur.execute("SELECT variant_id FROM variants WHERE assignment_id=%s", (ASSIGNMENT,))
    variant_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
        "  variant_id, gap_seed) VALUES (%s,%s,%s,2,%s,2) RETURNING attempt_id",
        (STUDENT, PROJECT, ASSIGNMENT, variant_id),
    )
    fresh_attempt_id = cur.fetchone()[0]

    result = diagnose(cur, fresh_attempt_id)
    assert result.weakest_concept is None
    assert result.recurrence_flags == {}
    assert result.failing_tests == ()
    # attempts_per_stage is unaffected by test_results -- it's still real, from
    # raw_commits, even for a never-graded attempt on the same project.
    assert result.attempts_per_stage["weather_etl_transform"] == 3
