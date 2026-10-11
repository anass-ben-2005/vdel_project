"""D-072 -- scripts/next_attempt.py on the throwaway test database.

One transaction per test, rolled back at the end (`conn=` is passed through; the script never
commits a caller's transaction)."""
import os

import pytest

from scripts import next_attempt as na
from system import db
from tests.support import ensure_variant

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

S = "_na_student"
ASG = "weather_etl_extract"
OTHER_ASG = "weather_etl_transform"


@pytest.fixture
def conn():
    try:
        c = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    yield c
    c.rollback()
    c.close()


def world(conn, *, frozen):
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, S))
    for asg in (ASG, OTHER_ASG):
        variant = ensure_variant(cur, asg)
        cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                    " variant_id, gap_seed, submitted_at) VALUES (%s,'weather_etl',%s,1,%s,1,%s)",
                    (S, asg, variant, "2026-08-25 02:00+00" if frozen and asg == ASG else None))
    return cur


def snapshot(cur):
    cur.execute("SELECT (SELECT count(*) FROM attempts), (SELECT count(*) FROM variants),"
                " (SELECT md5(string_agg(a::text, '|' ORDER BY a::text)) FROM attempts a"
                "  WHERE student_id = %s)", (S,))
    return cur.fetchone()


def run(conn, tmp_path, **kw):
    lines = []
    result = na.next_attempt(S, ASG, conn=conn, out=lines.append, out_dir=tmp_path / "out", **kw)
    return result, lines


def test_an_open_attempt_refuses_and_writes_nothing(conn, tmp_path):
    cur = world(conn, frozen=False)
    before = snapshot(cur)
    result, lines = run(conn, tmp_path)
    assert result["allowed"] is False and result["wrote"] is False
    assert result["code"] == na.EXIT_REFUSED
    assert any("REFUSED" in line and "--force" in line for line in lines)
    assert snapshot(cur) == before and not (tmp_path / "out").exists()


def test_a_frozen_attempt_allows_the_next_one_and_records_only_this_assignment(conn, tmp_path):
    cur = world(conn, frozen=True)
    result, _ = run(conn, tmp_path)
    assert result["allowed"] and result["wrote"] and result["next_no"] == 2
    cur.execute("SELECT assignment_id, attempt_no, variant_id FROM attempts"
                " WHERE student_id=%s ORDER BY assignment_id, attempt_no", (S,))
    rows = cur.fetchall()
    assert [(a, n) for a, n, _ in rows] == [(ASG, 1), (ASG, 2), (OTHER_ASG, 1)]   # transform: no #2
    assert rows[1][2] == result["variant_id"]
    cur.execute("SELECT gap_ids FROM variants WHERE variant_id=%s", (result["variant_id"],))
    assert cur.fetchone()[0] == result["gap_ids"] and result["gap_ids"]
    files = result["files"]
    assert "weather_etl/extract.py" in files and "ASSIGNMENT.md" in files
    assert "weather_etl/transform.py" not in files                   # only this assignment
    assert not any("hidden" in f for f in files)                     # hidden tests never leak
    assert (tmp_path / "out" / "weather_etl" / "extract.py").exists()


def test_force_starts_over_an_open_attempt_and_leaves_the_old_row_untouched(conn, tmp_path):
    cur = world(conn, frozen=False)
    cur.execute("SELECT attempt_id, student_id, variant_id, gap_seed, submitted_at, commit_sha"
                " FROM attempts WHERE student_id=%s AND assignment_id=%s AND attempt_no=1",
                (S, ASG))
    old = cur.fetchone()
    result, lines = run(conn, tmp_path, force=True)
    assert result["allowed"] and result["forced"] and result["next_no"] == 2
    assert any("FORCED" in line for line in lines)
    cur.execute("SELECT attempt_id, student_id, variant_id, gap_seed, submitted_at, commit_sha"
                " FROM attempts WHERE student_id=%s AND assignment_id=%s AND attempt_no=1",
                (S, ASG))
    assert cur.fetchone() == old                                      # superseded, not modified


def test_dry_run_shows_the_variant_and_the_files_but_records_nothing(conn, tmp_path):
    cur = world(conn, frozen=True)
    before = snapshot(cur)
    result, lines = run(conn, tmp_path, dry_run=True)
    assert result["allowed"] and result["wrote"] is False and result["attempt_id"] is None
    assert result["variant_id"] and result["files"]
    assert snapshot(cur) == before                                   # rows rolled back
    assert not (tmp_path / "out").exists()                           # dry-run used a scratch dir
    assert any("DRY-RUN" in line for line in lines)
    again, _ = run(conn, tmp_path, dry_run=True)
    assert again["variant_id"] == result["variant_id"]               # deterministic


def test_the_new_attempt_is_itself_open_so_a_third_needs_a_freeze_or_force(conn, tmp_path):
    world(conn, frozen=True)
    run(conn, tmp_path)
    second, lines = run(conn, tmp_path)
    assert second["allowed"] is False and second["attempt_no"] == 2
    assert any("attempt 2" in line and "REFUSED" in line for line in lines)


def test_no_attempt_at_all_is_a_different_refusal(conn, tmp_path):
    conn.cursor().execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, S))
    result, lines = run(conn, tmp_path)
    assert result["allowed"] is False and result["code"] == na.EXIT_NO_ATTEMPT
    assert any("no attempt exists" in line for line in lines)
