"""D-055: `test_results.test_name` must not depend on the directory a repo is graded from.

Three layers, cheapest first:
  - `normalise_test_name` as a pure function (no DB);
  - the real regression: grade ONE commit from two directories -- one outside the project
    tree, one inside it, which is exactly where pytest's rootdir (and so the JUnit
    classname) differs -- and prove the second run adds nothing;
  - `scripts/normalise_test_names.py` against synthetic old-style rows.

DB tests run inside one transaction that is rolled back (`traces` is append-only, so
rollback is the only cleanup -- see tests/test_test_runner.py's docstring), and skip when
no database is reachable.
"""
import shutil
import uuid
from pathlib import Path

import pytest

from assessment import test_runner as tr
from assessment.test_runner import TestRunnerError, normalise_test_name
from scripts import normalise_test_names as mig
from system import db

STUDENT = "_test_runner_v3"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CURRICULUM_ROOT = PROJECT_ROOT / "curriculum" / "master"


# --- pure function ---------------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    # the two shapes the bug produced for the SAME test
    ("renders.anas_attempt1.tests.hidden.test_extract::test_a",
     "tests/hidden/test_extract.py::test_a"),
    ("tests.hidden.test_extract::test_a", "tests/hidden/test_extract.py::test_a"),
    # any depth of prefix
    ("a.b.c.d.tests.hidden.test_extract::test_a", "tests/hidden/test_extract.py::test_a"),
    # idempotent: already normalised passes through
    ("tests/hidden/test_extract.py::test_a", "tests/hidden/test_extract.py::test_a"),
    # a test class survives as a node-id segment
    ("x.tests.hidden.test_extract.TestRetry::test_a",
     "tests/hidden/test_extract.py::TestRetry::test_a"),
    # dots and brackets in a parametrised name are left alone
    ("x.tests.hidden.test_extract::test_a[1.5-ok]",
     "tests/hidden/test_extract.py::test_a[1.5-ok]"),
])
def test_normalise_is_path_independent_and_idempotent(raw, expected):
    assert normalise_test_name(raw) == expected
    assert normalise_test_name(expected) == expected


@pytest.mark.parametrize("raw", [
    "some.other.module::test_a",             # no tests.hidden segment
    "tests.hidden::test_a",                  # no module after it
    "no_separator_at_all",
])
def test_normalise_refuses_rather_than_storing_a_path_dependent_name(raw):
    with pytest.raises(TestRunnerError):
        normalise_test_name(raw)


# --- DB fixtures -----------------------------------------------------------------------

@pytest.fixture
def txn():
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    conn.cursor().execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (STUDENT, STUDENT))
    yield conn
    conn.rollback()
    conn.close()


def _make_attempt(conn, assignment_id: str, hidden_gap_ids: list[str]) -> int:
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT master_version FROM gaps WHERE assignment_id=%s", (assignment_id,))
    (master_version,) = cur.fetchone()
    variant_id = f"_test_runner_v3_variant_{assignment_id}"
    cur.execute(
        "INSERT INTO variants (variant_id, assignment_id, gap_ids, master_version)"
        " VALUES (%s,%s,%s,%s)", (variant_id, assignment_id, hidden_gap_ids, master_version),
    )
    cur.execute(
        "INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
        "  variant_id, gap_seed) VALUES (%s,'weather_etl',%s,1,%s,1) RETURNING attempt_id",
        (STUDENT, assignment_id, variant_id),
    )
    return cur.fetchone()[0]


def _solved_transform_repo(dest: Path) -> Path:
    src = CURRICULUM_ROOT / "weather_etl" / "weather_etl"
    (dest / "weather_etl").mkdir(parents=True)
    shutil.copyfile(src / "transform.py", dest / "weather_etl" / "transform.py")
    shutil.copyfile(src / "__init__.py", dest / "weather_etl" / "__init__.py")
    return dest


# --- the regression --------------------------------------------------------------------

def test_grading_one_commit_from_two_directories_adds_nothing_the_second_time(
    txn, tmp_path
):
    conn = txn
    attempt_id = _make_attempt(
        conn, "weather_etl_transform", ["g_tf_clean", "g_tf_convert", "g_tf_timestamp"]
    )
    conn.cursor().execute(
        "INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at, additions,"
        "  deletions, files_changed, message) VALUES ('_v3_same_sha', %s,"
        "  'weather_etl_transform', now(), 1, 0, 1, 'x')", (STUDENT,),
    )

    # Same content, two locations. tmp_path has no pyproject.toml above it, so pytest's
    # rootdir is the repo itself ("tests.hidden.test_transform"); `inside` sits under this
    # project's pyproject.toml, so the classname gains a "renders._pytest_..." prefix.
    outside = _solved_transform_repo(tmp_path / "outside")
    inside = PROJECT_ROOT / "renders" / f"_pytest_pathindep_{uuid.uuid4().hex[:8]}"
    try:
        _solved_transform_repo(inside)

        def counts():
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM test_results WHERE attempt_id=%s", (attempt_id,))
            rows = cur.fetchone()[0]
            cur.execute(
                "SELECT count(*) FROM traces WHERE student_id=%s AND kind='test_result'",
                (STUDENT,),
            )
            return rows, cur.fetchone()[0]

        tr.grade_attempt("weather_etl", "weather_etl_transform", outside, attempt_id,
                         commit_sha="_v3_same_sha", conn=conn)
        first = counts()
        assert first == (5, 5)

        tr.grade_attempt("weather_etl", "weather_etl_transform", inside, attempt_id,
                         commit_sha="_v3_same_sha", conn=conn)
        assert counts() == first          # zero new test_results rows, zero new traces
    finally:
        shutil.rmtree(inside, ignore_errors=True)

    cur = conn.cursor()
    cur.execute("SELECT DISTINCT test_name FROM test_results WHERE attempt_id=%s", (attempt_id,))
    assert all(n.startswith("tests/hidden/test_transform.py::") for (n,) in cur.fetchall())


# --- the migration ---------------------------------------------------------------------

def test_migration_renames_dedupes_and_is_idempotent(txn):
    conn = txn
    attempt_id = _make_attempt(conn, "weather_etl_transform", ["g_tf_clean"])
    cur = conn.cursor()
    ins = ("INSERT INTO test_results (attempt_id, commit_sha, test_name, passed, ran_at)"
           " VALUES (%s,%s,%s,true,%s)")
    rows = [
        # collision: the SAME test stored under two directory-dependent names (local run)
        (attempt_id, None, "renders.old.tests.hidden.test_transform::t1", "2026-08-01"),
        (attempt_id, None, "tests.hidden.test_transform::t1", "2026-08-02"),
        # rename only
        (attempt_id, None, "renders.old.tests.hidden.test_transform::t2", "2026-08-01"),
        # a pushed-commit row: same test name as a local one is NOT a collision
        (attempt_id, "_v3_sha", "renders.old.tests.hidden.test_transform::t1", "2026-08-03"),
        # already normalised: untouched
        (attempt_id, None, "tests/hidden/test_transform.py::t3", "2026-08-01"),
    ]
    cur.executemany(ins, rows)

    p = mig.plan(cur)
    mine = lambda items: [i for i in items if i[0] == attempt_id]  # noqa: E731
    assert len(mine(p["deletes"])) == 1          # the older of the t1 pair
    assert len(mine(p["renames"])) == 3          # surviving t1, t2, and the pushed t1
    assert mine(p["unrecognised"]) == []

    mig.apply(cur, p)
    cur.execute(
        "SELECT commit_sha, test_name FROM test_results WHERE attempt_id=%s"
        " ORDER BY commit_sha NULLS FIRST, test_name", (attempt_id,),
    )
    assert cur.fetchall() == [
        (None, "tests/hidden/test_transform.py::t1"),
        (None, "tests/hidden/test_transform.py::t2"),
        (None, "tests/hidden/test_transform.py::t3"),
        ("_v3_sha", "tests/hidden/test_transform.py::t1"),
    ]

    again = mig.plan(cur)                         # idempotent: nothing left to do
    assert mine(again["renames"]) == [] and mine(again["deletes"]) == []
