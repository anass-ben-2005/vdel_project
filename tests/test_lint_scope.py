"""D-088 -- gap-scoped lint counts for V2 (formula v7). vdel_test, one rolled-back transaction.

The linters are the real ruff / sqlfluff (static); nothing runs the student's code here."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

import pytest

from agents.tools import STATUS_UNAVAILABLE, ToolReport
from assessment import lint_scope
from assessment.gap_parser import render_student_file_with_ranges
from assessment.scope_check import in_gap_submitted_ranges
from features import compute_features as cf
from scripts import grade_collected as gc
from system import db
from tests.support import ensure_variant
from tests.test_grading_sandbox import MASTER_LOAD, PROJECT, make_repo

MASTER = MASTER_LOAD.read_text(encoding="utf-8")
BOTH = ["g_ld_insert", "g_ld_select"]
RELEASED, RANGES = render_student_file_with_ranges(MASTER, BOTH)
STUB = "    raise NotImplementedError()\n"
SOLUTION = (
    "    unused = 1\n"
    '    cur = conn.executemany("INSERT INTO readings (temp) VALUES (:temp)", records)\n'
    "    conn.commit()\n"
    "    return cur.rowcount\n"
)
# a violation INSIDE the first gap (F841) and one OUTSIDE every gap (F401, master territory)
SUBMITTED = "import os\n" + RELEASED.replace(STUB, SOLUTION, 1)

needs_db = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)


# --- pure: the coordinates and the count ---------------------------------------------------------

def test_the_gap_ranges_follow_the_student_lines_into_the_submitted_file():
    ranges = in_gap_submitted_ranges(RELEASED, SUBMITTED, RANGES)
    lines = SUBMITTED.splitlines()
    # the student's four lines sit one line lower (the inserted import) than the stub did
    ((start, end),) = ranges
    assert (end - start + 1) == 4
    assert lines[start - 1].strip() == "unused = 1"
    assert lines[end - 1].strip() == "return cur.rowcount"


def test_only_findings_on_lines_the_student_wrote_inside_a_gap_are_counted():
    measured = lint_scope.measure(RELEASED, SUBMITTED, RANGES, "weather_etl/load.py")
    assert measured is not None
    assert (measured.violations, measured.changed_loc, measured.tool) == (1, 4, "ruff")


def test_a_clean_solution_counts_zero_violations_not_none():
    clean = RELEASED.replace(STUB, SOLUTION.replace("    unused = 1\n", ""), 1)
    measured = lint_scope.measure(RELEASED, clean, RANGES, "weather_etl/load.py")
    assert (measured.violations, measured.changed_loc) == (0, 3)


def test_a_linter_that_cannot_run_or_no_linter_at_all_means_not_measured(monkeypatch):
    monkeypatch.setattr(lint_scope, "lint_submission",
                        lambda path: [ToolReport("ruff", STATUS_UNAVAILABLE, detail="x")])
    assert lint_scope.measure(RELEASED, SUBMITTED, RANGES, "weather_etl/load.py") is None
    assert lint_scope.measure(RELEASED, SUBMITTED, RANGES, "notes.txt") is None   # no linter


def test_the_file_is_linted_from_a_private_copy_so_student_config_cannot_switch_rules_off(
        monkeypatch, tmp_path):
    seen = {}

    def spy(path):
        seen["dir"] = Path(path).parent
        seen["siblings"] = sorted(p.name for p in Path(path).parent.iterdir())
        return [ToolReport("ruff", "ok", findings=[])]

    monkeypatch.setattr(lint_scope, "lint_submission", spy)
    lint_scope.measure(RELEASED, SUBMITTED, RANGES, "weather_etl/load.py")
    assert seen["siblings"] == ["load.py"]            # nothing else: no pyproject, no ruff.toml
    assert not seen["dir"].exists()                   # and it was removed afterwards


def test_sql_files_go_to_sqlfluff(monkeypatch):
    released = "SELECT 1\nFROM t;\n-- gap\nSELECT 2;\n"
    submitted = "SELECT 1\nFROM t;\n-- gap\nSELECT 2 ,3;\n"
    findings = [{"code": "LT01", "message": "x", "line": 4, "column": 9, "severity": "error"},
                {"code": "LT09", "message": "y", "line": 1, "column": 1, "severity": "error"}]
    monkeypatch.setattr(lint_scope, "lint_submission",
                        lambda path: [ToolReport("sqlfluff", "ok", findings=findings)])
    measured = lint_scope.measure(released, submitted, [(4, 4)], "queries/top.sql")
    assert (measured.violations, measured.tool) == (1, "sqlfluff")     # line 1 is master code


def test_the_real_sqlfluff_runs_on_a_sql_file():
    pytest.importorskip("sqlfluff")
    released = "SELECT a FROM t\n-- gap\nSELECT 1\n"
    submitted = "SELECT a FROM t\n-- gap\nselect 1,2\n"
    measured = lint_scope.measure(released, submitted, [(3, 3)], "q.sql")
    assert measured is not None and measured.tool == "sqlfluff"


# --- stored on the attempt -----------------------------------------------------------------------

@pytest.fixture
def world():
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = conn.cursor()
    student = "_lint_student"
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (student, student))
    variant = ensure_variant(cur, "weather_etl_load")
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl','weather_etl_load',1,%s,1)"
                " RETURNING attempt_id", (student, variant))
    attempt_id = cur.fetchone()[0]
    for sha in ("_lint_sha_1", "_lint_sha_2"):
        cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                    " VALUES (%s,%s,'weather_etl_load','2026-08-25 01:00+00')", (sha, student))
    yield conn, cur, attempt_id, student
    conn.rollback()
    conn.close()


def columns(cur, attempt_id):
    cur.execute("SELECT lint_violations, lint_changed_loc, lint_tool FROM attempts"
                " WHERE attempt_id = %s", (attempt_id,))
    return cur.fetchone()


def record(cur, attempt_id, repo, sha="_lint_sha_1", status="ok"):
    return lint_scope.record(cur, project_id=PROJECT, assignment_id="weather_etl_load",
                             attempt_id=attempt_id, commit_sha=sha, repo_dir=repo, status=status)


@needs_db
def test_the_counts_are_stored_on_the_attempt(world, tmp_path):
    _, cur, attempt_id, _ = world
    record(cur, attempt_id, make_repo(tmp_path / "r", load_py=SUBMITTED))
    assert columns(cur, attempt_id) == (1, 4, "ruff")


@needs_db
def test_a_commit_that_does_not_load_is_not_measured(world, tmp_path):
    _, cur, attempt_id, _ = world
    for status in ("collection_error", "timeout"):
        assert record(cur, attempt_id, make_repo(tmp_path / status, load_py="def broken(:\n"),
                      status=status) is None
    assert columns(cur, attempt_id) == (None, None, None)


@needs_db
def test_before_the_freeze_the_latest_commit_wins_after_it_the_frozen_one_stays(world, tmp_path):
    _, cur, attempt_id, _ = world
    clean = RELEASED.replace(STUB, SOLUTION.replace("    unused = 1\n", ""), 1)
    record(cur, attempt_id, make_repo(tmp_path / "a", load_py=SUBMITTED), sha="_lint_sha_1")
    record(cur, attempt_id, make_repo(tmp_path / "b", load_py=clean), sha="_lint_sha_2")
    assert columns(cur, attempt_id) == (0, 3, "ruff")                  # the later commit
    cur.execute("UPDATE attempts SET submitted_at = now(), commit_sha = '_lint_sha_2'"
                " WHERE attempt_id = %s", (attempt_id,))
    record(cur, attempt_id, make_repo(tmp_path / "c", load_py=SUBMITTED), sha="_lint_sha_1")
    assert columns(cur, attempt_id) == (0, 3, "ruff")                  # frozen value kept


@needs_db
def test_fail_open_a_missing_file_leaves_the_columns_and_the_transaction_usable(
        world, tmp_path, caplog):
    _, cur, attempt_id, _ = world
    with caplog.at_level(logging.WARNING, logger="assessment.lint_scope"):
        assert record(cur, attempt_id, make_repo(tmp_path / "r", load_py=None)) is None
    assert columns(cur, attempt_id) == (None, None, None)              # same cursor still works
    assert any("lint scope skipped" in r.message for r in caplog.records)


@needs_db
def test_fail_open_when_the_columns_are_not_migrated_yet(world, tmp_path):
    """The real database gets sql/08 by hand; until then grading must not fail."""
    _, cur, attempt_id, _ = world
    cur.execute("ALTER TABLE attempts DROP COLUMN lint_tool")      # transactional DDL, rolled back
    assert record(cur, attempt_id, make_repo(tmp_path / "r", load_py=SUBMITTED)) is None
    cur.execute("SELECT 1")                                         # the transaction is alive
    assert cur.fetchone() == (1,)


@needs_db
def test_grade_collected_records_the_counts_after_grading(world, tmp_path):
    from assessment.test_runner import grade_attempt

    conn, cur, attempt_id, student = world
    prepared = make_repo(tmp_path / "prepared", load_py=SUBMITTED)

    def fake_checkout(owner, repo, sha, dest):
        shutil.copytree(prepared, dest)

    summary = gc.run(student=student, repo_for={(student, "weather_etl_load"): ("o", "r")},
                     checkout=fake_checkout, grade=grade_attempt, conn=conn)
    assert len(summary["graded"]) == 2 and not summary["failed"]
    assert columns(cur, attempt_id) == (1, 4, "ruff")


# --- V2 in the features (formula v7) --------------------------------------------------------------

@needs_db
def test_v7_cleanliness_uses_the_stored_counts_and_older_versions_keep_the_zeros(world):
    _, cur, attempt_id, student = world
    cur.execute("UPDATE attempts SET lint_violations = 1, lint_changed_loc = 100,"
                " lint_tool = 'ruff' WHERE attempt_id = %s", (attempt_id,))
    v7 = cf._discipline(cur, student, "v7")
    assert v7["cleanliness"] == 0.9
    assert v7["lint"] == {"violations": 1, "changed_loc": 100, "attempts_measured": 1}
    v6 = cf._discipline(cur, student, "v6")
    assert v6["cleanliness"] is None and "lint" not in v6              # v6 stays reproducible


@needs_db
def test_v7_with_nothing_measured_is_not_measured_not_perfect(world):
    _, cur, _, student = world
    assert cf._discipline(cur, student, "v7")["cleanliness"] is None


@needs_db
def test_v7_survives_unmigrated_columns(world):
    _, cur, _, student = world
    cur.execute("ALTER TABLE attempts DROP COLUMN lint_violations")
    assert cf._discipline(cur, student, "v7")["cleanliness"] is None


def test_the_version_switch():
    assert [cf._measures_lint(v) for v in ("v2", "v3", "v4", "v5", "v6", "v7")] == \
        [False, False, False, False, False, True]
    assert cf.FORMULA_VER == "v8" and cf.LINT_MEASURED_FROM == "v7"
