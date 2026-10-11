"""D-069 -- formula v4 (items 1a and 1b of the overnight batch), on the throwaway test DB.

  1a  the initial template commit ("Initial commit: ...", no assignment) and the CI run on it
      are not student actions: out of V3, V6 changed_loc, the effort baseline, the watermark,
      and the V5/V6 run history. Same fail-open test as the sync rule. v3 is unchanged.
  1b  V1 in learner_features is `Memory.replay_mastery` -- the profile's own replay. Raw CI runs
      feed no concept-level mastery; they still feed V5/V6.

Every test runs in one transaction that is rolled back (traces are append-only).
"""
import os
from datetime import UTC, datetime

import pytest

from features import compute_features as cf
from memory.memory import Memory
from system import db

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

S = "_d069"
ASG = "_d069_A"
INIT, WORK = "1" * 40, "2" * 40
CONCEPT = "py.testing"


@pytest.fixture
def conn():
    try:
        c = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    yield c
    c.rollback()
    c.close()


def world(conn, *, init_msg="Initial commit: weather_etl gapfill for _d069"):
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, S))
    cur.execute("INSERT INTO assignments VALUES (%s,'org/a','2026-01-01 00:00+00',NULL,"
                "ARRAY[%s])", (ASG, CONCEPT))
    # the initial commit: 14 files, 197 lines, no assignment (the collector stores it so)
    cur.execute("INSERT INTO raw_commits VALUES (%s,%s,NULL,'2026-01-02 08:00+00',197,0,14,%s)",
                (INIT, S, init_msg))
    cur.execute("INSERT INTO raw_commits VALUES (%s,%s,%s,'2026-01-02 10:00+00',5,1,1,'work')",
                (WORK, S, ASG))
    for run_id, head, started in ((9_700_001, INIT, "2026-01-02 08:05+00"),
                                  (9_700_002, WORK, "2026-01-02 10:05+00")):
        cur.execute(
            "INSERT INTO raw_workflow_runs (run_id, student_id, assignment_id, status,"
            " conclusion, started_at, completed_at, duration_s, error_class, concept_id,"
            " head_sha) VALUES (%s,%s,%s,'completed','failure',%s,%s::timestamptz + interval"
            " '3 min',60,'AssertionError',%s,%s)", (run_id, S, ASG, started, started,
                                                    CONCEPT, head))
    return cur


# --- 1a ----------------------------------------------------------------------------------------

def test_1a_the_initial_template_commit_and_its_run_are_not_student_activity(conn):
    cur = world(conn)
    cur.execute("INSERT INTO raw_commits VALUES (%s,%s,%s,'2026-01-02 15:00+00',5,1,1,'more')",
                ("3" * 40, S, ASG))
    v3 = cf.compute_for_student(cur, S, "v3")
    v4 = cf.compute_for_student(cur, S, "v4")

    # v3 still counts them (unchanged, readable): 3 commits, 2 failed runs
    assert v3["error_frequency"]["fail_ratio"] == 1.0
    assert v3["error_frequency"]["by_concept"] == {CONCEPT: 2}
    # v4 leaves out the initial commit's run and its LOC
    assert v4["error_frequency"]["by_concept"] == {CONCEPT: 1}
    assert v4["error_frequency"]["excluded_runs"]["sync_triggered"] == 1
    assert v4["error_frequency"]["excluded_commits"] == 1
    # effort: under v3 the initial commit adds a 2h gap (gaps 2h, 5h); under v4 only 5h remains
    assert v3["effort_regulation"] != v4["effort_regulation"]
    # watermark: v4 ignores the initial commit's timestamp as an event
    assert cf.watermark(cur, S, "v4") == cf.watermark(cur, S, "v3")   # the last event is a run


def test_1a_fail_open_a_message_without_the_prefix_or_with_an_assignment_is_kept(conn):
    cur = world(conn, init_msg="my first commit")                      # prefix absent
    assert cf.compute_for_student(cur, S, "v4")["error_frequency"]["excluded_commits"] == 0
    cur.execute("UPDATE raw_commits SET message='Initial commit: x', assignment_id=%s "
                "WHERE sha=%s", (ASG, INIT))                           # touches an assignment
    assert cf.compute_for_student(cur, S, "v4")["error_frequency"]["excluded_commits"] == 0
    cur.execute("UPDATE raw_commits SET message=NULL, assignment_id=NULL WHERE sha=%s", (INIT,))
    assert cf.compute_for_student(cur, S, "v4")["error_frequency"]["excluded_commits"] == 0


def test_1a_a_student_with_only_the_initial_commit_is_not_dirty_under_v4(conn):
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, S))
    cur.execute("INSERT INTO raw_commits VALUES (%s,%s,NULL,'2026-01-02 08:00+00',197,0,14,"
                "'Initial commit: weather_etl gapfill for _d069')", (INIT, S))
    assert S in cf.dirty_students(cur, "2026-01-01T00:00:00Z", "v3")
    assert S not in cf.dirty_students(cur, "2026-01-01T00:00:00Z", "v4")
    assert cf.watermark(cur, S, "v4") is None


def test_1a_publish_repo_still_writes_the_prefix():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "scripts" / "publish_repo.py").read_text(
        encoding="utf-8")
    assert f'f"{cf.INITIAL_COMMIT_PREFIX} {{project_id}}' in src


# --- 1b ----------------------------------------------------------------------------------------

def _log(mem, conn, passed, ts_offset):
    """One graded outcome, as D-079 writes it: the `test_result` evidence (V5/V6, v3) AND the
    `mastery_observation` that v4/v5 replay, for a distinct gap each call."""
    mem.log_trace(S, "system", "test_result",
                  {"conclusion": "success" if passed else "failure", "item_difficulty": 0.35},
                  assignment_id=ASG, concept_ids=[CONCEPT], conn=conn)
    _log.n = getattr(_log, "n", 0) + 1
    return mem.record_mastery_observation(
        S, attempt_id=1, assignment_id=ASG, gap_id=f"g_obs_{_log.n}", concept_ids=[CONCEPT],
        passed=passed, item_difficulty=0.35, commit_sha=f"sha{_log.n}",
        observed_at=datetime(2026, 9, 1, 10, _log.n, tzinfo=UTC), conn=conn)


def test_1b_features_v1_is_the_profiles_trace_replay_and_ci_runs_feed_no_concept(conn):
    cur = world(conn)
    mem = Memory()
    for passed in (False, True, True):
        _log(mem, conn, passed, 0)
        mem.update_mastery(S, CONCEPT, conn=conn)

    profile = mem.get_profile(S, conn=conn)["mastery"]
    v4 = cf.compute_for_student(cur, S, "v4")["mastery"]
    assert v4 == profile                                      # identical, n included
    assert v4[CONCEPT]["n"] == 3                              # CI runs add none; n = observations
    # v3 (the CI-driven path) disagrees by construction -- that is D-068
    assert cf.compute_for_student(cur, S, "v3")["mastery"][CONCEPT]["n"] == 5


def test_1b_the_replay_is_read_only(conn):
    world(conn)
    mem = Memory()
    _log(mem, conn, True, 0)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM traces WHERE student_id=%s", (S,))
    before = cur.fetchone()[0]
    shapes, est = mem.replay_mastery(S, conn=conn)
    cur.execute("SELECT count(*) FROM traces WHERE student_id=%s", (S,))
    assert cur.fetchone()[0] == before and CONCEPT in shapes and CONCEPT in est.states
    assert mem.get_profile(S, conn=conn)["mastery"] == {}      # the profile was not touched
