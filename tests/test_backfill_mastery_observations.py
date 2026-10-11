"""D-079 -- scripts/backfill_mastery_observations.py on vdel_test (one rolled-back transaction).

What matters: the plan is the SAME rule grading uses, the dry-run writes nothing and predicts
exactly what --apply produces, --apply refuses without an existing backup file, appends only the
missing observations (idempotent), and leaves the stored profile equal to the replay so the
event-sourcing proof (Beat 7) stays IDENTICAL."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from memory.memory import Memory
from scripts import backfill_mastery_observations as bf
from scripts.prove_event_sourcing import prove
from system import db
from tests.support import ensure_variant

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

S, ASG = "_bf_student", "weather_etl_extract"
T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
RETRY_T = ("tests/hidden/test_extract.py::test_fetch_weather_retries_then_succeeds",
           "tests/hidden/test_extract.py::test_fetch_weather_raises_after_max_attempts")
PARSE_T = ("tests/hidden/test_extract.py::test_parse_response_missing_key_returns_none",
           "tests/hidden/test_extract.py::test_parse_response_missing_current_key_entirely")


@pytest.fixture
def world(monkeypatch):
    """Student `_bf_student` is a fixture id, so the plan skips it by design; the tests plan
    for a differently named student instead."""
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = conn.cursor()
    student = "bf_student"
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (student, student))
    variant = ensure_variant(cur, ASG)
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl',%s,1,%s,1) RETURNING attempt_id",
                (student, ASG, variant))
    attempt_id = cur.fetchone()[0]
    for n in range(1, 5):
        cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                    " VALUES (%s,%s,%s,%s)", (f"bf_{n}", student, ASG, T0 + timedelta(hours=n)))

    def result(sha, name, gap, passed, message=None, status="ok"):
        cur.execute("INSERT INTO test_results (attempt_id, commit_sha, test_name, gap_id, passed,"
                    " message, status) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (attempt_id, sha, name, gap, passed, message, status))

    # bf_1: collection error (ignored) -- the earliest commit
    for name in RETRY_T + PARSE_T:
        result("bf_1", name, "g_ext_retry" if name in RETRY_T else "g_ext_parse", False,
               "collection error: x", "collection_error")
    # bf_2: parse attempted and passing; retry still a stub
    for name in PARSE_T:
        result("bf_2", name, "g_ext_parse", True)
    for name in RETRY_T:
        result("bf_2", name, "g_ext_retry", False, "NotImplementedError")
    # bf_3: retry attempted, one test fails -> the FIRST attempted commit for retry (failure)
    result("bf_3", RETRY_T[0], "g_ext_retry", True)
    result("bf_3", RETRY_T[1], "g_ext_retry", False, "assert 1 == 2")
    for name in PARSE_T:
        result("bf_3", name, "g_ext_parse", False, "assert 1 == 2")   # a later regression
    # bf_4: everything passes (a later commit: must add nothing)
    for name in RETRY_T:
        result("bf_4", name, "g_ext_retry", True)
    for name in PARSE_T:
        result("bf_4", name, "g_ext_parse", True)
    # a local run (no commit_sha): never counts
    cur.execute("INSERT INTO test_results (attempt_id, test_name, gap_id, passed)"
                " VALUES (%s,%s,'g_ext_retry',true)", (attempt_id, "tests/hidden/x::local"))
    yield conn, cur, student, attempt_id
    conn.rollback()
    conn.close()


def plan_of(world):
    _, cur, student, _ = world
    return bf.build_plan(cur, [student])


def test_the_plan_is_the_first_attempted_pushed_commit_per_gap(world):
    plan = plan_of(world)
    assert [(p.gap_id, p.commit_sha, p.passed, p.concept) for p in plan] == [
        ("g_ext_parse", "bf_2", True, "py.data_structures"),
        ("g_ext_retry", "bf_3", False, "py.errors_debugging"),
    ]
    assert plan[1].concepts == ("py.errors_debugging", "py.data_structures")
    assert all(not p.present for p in plan)


def test_fixture_students_are_never_planned(world):
    _, cur, _, _ = world
    assert bf.build_plan(cur, ["_test_runner", "_bf_student"]) == []


def test_the_dry_run_writes_nothing_and_prints_the_plan_and_both_profiles(world):
    conn, cur, student, _ = world
    cur.execute("SELECT count(*) FROM traces WHERE student_id=%s", (student,))
    before = cur.fetchone()[0]
    lines = []
    plan = plan_of(world)
    bf.show(conn, plan, [student], out=lines.append)
    cur.execute("SELECT count(*) FROM traces WHERE student_id=%s", (student,))
    assert cur.fetchone()[0] == before
    text = "\n".join(lines)
    assert "2 mastery_observation trace(s) would be appended" in text
    assert "bf_2" in text and "bf_3" in text and "failure" in text
    assert "py.errors_debugging" in text and "n=1" in text


def test_apply_appends_the_missing_observations_and_is_idempotent(world):
    conn, cur, student, _ = world
    assert bf.apply_plan(conn, plan_of(world), [student]) == 2
    cur.execute("SELECT payload->>'gap_id', payload->>'commit_sha', payload->>'conclusion'"
                " FROM traces WHERE student_id=%s AND kind='mastery_observation'"
                " ORDER BY trace_id", (student,))
    assert cur.fetchall() == [("g_ext_parse", "bf_2", "success"),
                              ("g_ext_retry", "bf_3", "failure")]
    again = plan_of(world)
    assert all(p.present for p in again)
    assert bf.apply_plan(conn, again, [student]) == 0
    cur.execute("SELECT count(*) FROM traces WHERE student_id=%s AND kind='mastery_observation'",
                (student,))
    assert cur.fetchone()[0] == 2


def test_the_dry_run_predicts_exactly_what_apply_produces(world):
    conn, _, student, _ = world
    plan = plan_of(world)
    predicted = bf.predict(conn, plan, [student])[student]
    bf.apply_plan(conn, plan, [student])
    assert Memory().get_profile(student, conn=conn)["mastery"] == predicted
    assert set(predicted) == {"py.data_structures", "py.errors_debugging"}
    assert predicted["py.errors_debugging"]["n"] == 1


def test_after_apply_the_stored_profile_equals_the_replay_and_beat_7_is_identical(world):
    conn, _, student, _ = world
    bf.apply_plan(conn, plan_of(world), [student])
    mem = Memory()
    assert mem.get_profile(student, conn=conn)["mastery"] == mem.replay_mastery(
        student, conn=conn)[0]
    result = prove(conn)
    assert result.identical and not result.vacuous and result.differences == []
    assert student in result.compared


def test_apply_refuses_without_an_existing_backup_file(tmp_path, capsys, monkeypatch):
    def boom():
        raise AssertionError("the database was opened although the apply was refused")

    monkeypatch.setattr(bf.db, "_open", boom)
    assert bf.main(["--apply"]) == 2
    assert bf.main(["--apply", "--backup", str(tmp_path / "missing.sql")]) == 2
    assert bf.main(["--apply", "--backup", str(tmp_path)]) == 2          # a directory is not a file
    assert "refused" in capsys.readouterr().out
    assert bf.main(["--student", "_test_runner"]) == 2


def test_the_dry_run_session_is_read_only():
    """main() without --apply asks for a read-only session, and in such a session Postgres
    itself rejects a write."""
    import psycopg2

    seen = {}
    real_open = bf.db._open

    class Spy:
        def __init__(self, real):
            self.real = real

        def set_session(self, **kw):
            seen.update(kw)
            self.real.set_session(**kw)

        def __getattr__(self, name):
            return getattr(self.real, name)

    bf.db._open = lambda: Spy(real_open())
    try:
        assert bf.main(["--student", "nobody"]) == 0
    finally:
        bf.db._open = real_open
    assert seen == {"readonly": True}

    conn = real_open()
    try:
        conn.set_session(readonly=True)
        with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
            conn.cursor().execute("INSERT INTO students VALUES ('_ro','_ro','x')")
    finally:
        conn.rollback()
        conn.close()


def test_a_second_apply_leaves_the_profile_row_untouched_but_a_real_change_updates_it(world):
    """The rebuild used to rewrite `updated_at` every time, so a second --apply changed the
    table hash with no change in content. Inside one transaction now() is constant, so the test
    pins `updated_at` to a sentinel and checks it survives the second apply."""
    conn, cur, student, _ = world
    bf.apply_plan(conn, plan_of(world), [student])
    cur.execute("UPDATE learner_profile SET updated_at = '2000-01-01 00:00:00+00'"
                " WHERE student_id = %s", (student,))
    cur.execute("SELECT row(learner_profile.*)::text FROM learner_profile WHERE student_id=%s",
                (student,))
    before = cur.fetchone()[0]

    assert bf.apply_plan(conn, plan_of(world), [student]) == 0          # nothing new to write
    cur.execute("SELECT row(learner_profile.*)::text FROM learner_profile WHERE student_id=%s",
                (student,))
    assert cur.fetchone()[0] == before                                  # byte-identical row

    # a profile that DISAGREES with the log is still repaired, and then updated_at moves
    cur.execute("UPDATE learner_profile SET mastery = '{}'::jsonb WHERE student_id = %s",
                (student,))
    Memory().rebuild_from_traces(student, conn=conn)
    cur.execute("SELECT updated_at > '2000-01-01', mastery <> '{}'::jsonb FROM learner_profile"
                " WHERE student_id = %s", (student,))
    assert cur.fetchone() == (True, True)
    assert prove(conn).identical                                        # Beat 7 unchanged
