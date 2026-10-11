"""D-073 -- scope_check wired into grading: attempts.out_of_scope_lines (V9), fail-open.

Real grader, real hidden tests, the test database, one rolled-back transaction per test."""

from __future__ import annotations

import logging
import os

import pytest

from assessment import test_runner as tr
from assessment.gap_parser import render_student_file, render_student_file_with_ranges
from system import db
from tests.support import ensure_variant
from tests.test_grading_sandbox import MASTER_LOAD, PROJECT, make_repo

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

STUDENT = "_scope_student"
MASTER = MASTER_LOAD.read_text(encoding="utf-8")
SOLVED = render_student_file(MASTER, hide_gap_ids=[])          # master without the markers
BOTH_GAPS = ["g_ld_insert", "g_ld_select"]


@pytest.fixture
def world():
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (STUDENT, STUDENT))
    variant_id = ensure_variant(cur, "weather_etl_load")
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl','weather_etl_load',1,%s,1)"
                " RETURNING attempt_id", (STUDENT, variant_id))
    attempt_id = cur.fetchone()[0]
    for sha in ("_sc_sha_1", "_sc_sha_2"):
        cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                    " VALUES (%s,%s,'weather_etl_load','2026-08-25 01:00+00')", (sha, STUDENT))
    yield conn, cur, attempt_id, variant_id
    conn.rollback()
    conn.close()


def grade(conn, attempt_id, repo, sha="_sc_sha_1"):
    return tr.grade_attempt(PROJECT, "weather_etl_load", repo, attempt_id,
                            commit_sha=sha, conn=conn)


def column(cur, attempt_id):
    cur.execute("SELECT out_of_scope_lines, submitted_at IS NOT NULL FROM attempts"
                " WHERE attempt_id=%s", (attempt_id,))
    return cur.fetchone()


def test_the_ranges_are_in_released_file_coordinates():
    released, ranges = render_student_file_with_ranges(MASTER, BOTH_GAPS)
    lines = released.splitlines()
    assert len(ranges) == 2
    for start, end in ranges:
        assert end == start + 1
        assert lines[start - 1].lstrip().startswith("#")
        assert lines[end - 1].strip() == "raise NotImplementedError()"
    assert render_student_file(MASTER, BOTH_GAPS) == released


def test_a_solved_file_edited_only_inside_the_gaps_is_zero(world, tmp_path):
    conn, cur, attempt_id, _ = world
    result = grade(conn, attempt_id, make_repo(tmp_path / "r", load_py=SOLVED))
    assert result.frozen is True
    assert column(cur, attempt_id) == (0, True)


def test_an_edit_outside_the_gaps_is_counted(world, tmp_path):
    conn, cur, attempt_id, _ = world
    grade(conn, attempt_id, make_repo(tmp_path / "r", load_py="# touched\n" + SOLVED))
    assert column(cur, attempt_id)[0] == 1


def test_fail_open_a_missing_file_leaves_null_and_grading_still_records(world, tmp_path,
                                                                        caplog):
    conn, cur, attempt_id, _ = world
    with caplog.at_level(logging.WARNING, logger="assessment.test_runner"):
        result = grade(conn, attempt_id, make_repo(tmp_path / "r", load_py=None))
    assert result.tests_total == 2 and result.frozen is False          # grading was not blocked
    assert column(cur, attempt_id) == (None, False)
    assert any("scope check skipped" in r.message for r in caplog.records)


def test_fail_open_a_changed_master_version_leaves_null(world, tmp_path):
    conn, cur, attempt_id, variant_id = world
    cur.execute("UPDATE variants SET master_version = %s WHERE variant_id = %s",
                ("0" * 40, variant_id))
    grade(conn, attempt_id, make_repo(tmp_path / "r", load_py=SOLVED))
    assert column(cur, attempt_id)[0] is None                          # invariant 15


def test_after_the_freeze_a_later_commit_cannot_overwrite_the_value(world, tmp_path):
    conn, cur, attempt_id, _ = world
    grade(conn, attempt_id, make_repo(tmp_path / "a", load_py=SOLVED), sha="_sc_sha_1")
    assert column(cur, attempt_id) == (0, True)
    grade(conn, attempt_id, make_repo(tmp_path / "b", load_py="# x\n# y\n" + SOLVED),
          sha="_sc_sha_2")
    assert column(cur, attempt_id) == (0, True)                        # the frozen commit's value


def test_before_the_freeze_the_latest_graded_commit_wins(world, tmp_path):
    conn, cur, attempt_id, _ = world
    grade(conn, attempt_id, make_repo(tmp_path / "a", load_py="# x\n" + tr_stub()),
          sha="_sc_sha_1")
    first = column(cur, attempt_id)[0]
    grade(conn, attempt_id, make_repo(tmp_path / "b", load_py="# x\n# y\n" + tr_stub()),
          sha="_sc_sha_2")
    assert (first, column(cur, attempt_id)[0]) == (1, 2)


def tr_stub():
    """The released file with both gaps still hidden (the student changed nothing in them)."""
    return render_student_file(MASTER, BOTH_GAPS)
