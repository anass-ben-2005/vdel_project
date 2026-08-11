"""memory/memory.py piece 1: log_trace, get_profile, snapshot_profile, transactions.

Every test drives its own connection and rolls it back, because `traces` is append-only:
the Postgres RULEs in sql/05 make DELETE a silent no-op, so a test that commits a trace
cannot clean up after itself and would pollute the database permanently. That constraint
is the invariant working as designed, not an inconvenience to route around -- so the
self-managed-transaction path is exercised by substituting the connection rather than by
letting it commit.

Skips when no database is reachable, matching test_pipeline_integration.py.
"""
import json
import os
from contextlib import contextmanager

import pytest

from memory import memory as mm
from memory.memory import Memory
from system import db

STUDENT = "_test_mem"
ASSIGNMENT = "_test_mem_a1"

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; memory tests need a database"
)


@pytest.fixture
def conn():
    """A connection that is always rolled back. Seeds the FK parents traces needs."""
    try:
        c = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    try:
        with c.cursor() as cur:
            cur.execute(
                "INSERT INTO students (student_id, github_username, cohort)"
                " VALUES (%s, %s, 'vdel-2026')",
                (STUDENT, STUDENT),
            )
            cur.execute(
                "INSERT INTO assignments (assignment_id, repo_prefix, released_at, concepts)"
                " VALUES (%s, 'org/a1', '2026-03-02 09:00+00', ARRAY['spark.joins'])",
                (ASSIGNMENT,),
            )
        yield c
    finally:
        c.rollback()
        c.close()


@pytest.fixture
def mem():
    return Memory()


# ---------- log_trace ----------

def test_log_trace_returns_an_id_and_round_trips_every_field(mem, conn):
    trace_id = mem.log_trace(
        STUDENT, "code_agent", "verdict", {"score": 4, "note": "clean"},
        assignment_id=ASSIGNMENT, concept_ids=["spark.joins", "spark.aggregation"],
        conn=conn,
    )
    assert isinstance(trace_id, int)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT student_id, actor, kind, assignment_id, concept_ids, payload,"
            "       parent_trace_id, session_id"
            " FROM traces WHERE trace_id = %s",
            (trace_id,),
        )
        row = cur.fetchone()

    assert row == (
        STUDENT, "code_agent", "verdict", ASSIGNMENT,
        ["spark.joins", "spark.aggregation"], {"score": 4, "note": "clean"},
        None, None,
    )


def test_log_trace_defaults_concept_ids_to_empty_array_not_null(mem, conn):
    """`concept_ids @> ARRAY[...]` on the GIN index must not have to handle NULL."""
    trace_id = mem.log_trace(STUDENT, "system", "commit", {"sha": "abc"}, conn=conn)
    with conn.cursor() as cur:
        cur.execute("SELECT concept_ids FROM traces WHERE trace_id = %s", (trace_id,))
        assert cur.fetchone()[0] == []


def test_log_trace_records_parentage(mem, conn):
    """The causal forest: one nullable column turns a flat log into a tree of causes."""
    parent = mem.log_trace(STUDENT, "system", "ci_run", {"conclusion": "failure"}, conn=conn)
    child = mem.log_trace(
        STUDENT, "system", "profile_update", {"p_mastery": 0.21},
        parent_trace_id=parent, conn=conn,
    )
    with conn.cursor() as cur:
        cur.execute("SELECT parent_trace_id FROM traces WHERE trace_id = %s", (child,))
        assert cur.fetchone()[0] == parent


@pytest.mark.parametrize("actor", ["", "Code_Agent", "ci-runner", "student_agent"])
def test_log_trace_rejects_an_unknown_actor(mem, conn, actor):
    with pytest.raises(ValueError, match="unknown actor"):
        mem.log_trace(STUDENT, actor, "verdict", {}, conn=conn)


@pytest.mark.parametrize("kind", ["", "ci-run", "CI_RUN", "profile_updated"])
def test_log_trace_rejects_an_unknown_kind(mem, conn, kind):
    """The typo that would otherwise insert cleanly and sit outside the replay set."""
    with pytest.raises(ValueError, match="unknown kind"):
        mem.log_trace(STUDENT, "system", kind, {}, conn=conn)


def test_rejected_trace_writes_nothing(mem, conn):
    """Validation happens before the INSERT, not after it."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM traces WHERE student_id = %s", (STUDENT,))
        before = cur.fetchone()[0]
    with pytest.raises(ValueError):
        mem.log_trace(STUDENT, "system", "ci-run", {}, conn=conn)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM traces WHERE student_id = %s", (STUDENT,))
        assert cur.fetchone()[0] == before


# ---------- transactions ----------

def test_a_joined_transaction_leaves_the_commit_to_the_caller(mem, conn):
    """The property the fast path depends on: profile write and trace write can be made
    atomic, so a crash between them cannot leave a belief with no audit record."""
    trace_id = mem.log_trace(STUDENT, "system", "ci_run", {"conclusion": "success"}, conn=conn)
    conn.rollback()

    with db.connect() as other, other.cursor() as cur:
        cur.execute("SELECT count(*) FROM traces WHERE trace_id = %s", (trace_id,))
        assert cur.fetchone()[0] == 0


def test_an_omitted_conn_opens_its_own_transaction(mem, conn, monkeypatch):
    """Exercises the self-managed branch without committing: db.connect is substituted
    with the test's rolled-back connection, so the code path runs and leaves no residue."""

    @contextmanager
    def fake_connect():
        yield conn

    monkeypatch.setattr(mm.db, "connect", fake_connect)

    trace_id = mem.log_trace(STUDENT, "system", "commit", {"sha": "def"})
    with conn.cursor() as cur:
        cur.execute("SELECT student_id FROM traces WHERE trace_id = %s", (trace_id,))
        assert cur.fetchone()[0] == STUDENT


# ---------- get_profile / snapshot_profile ----------

def test_get_profile_of_an_unknown_student_is_empty_not_none(mem, conn):
    """No caller should have to special-case a student's first event."""
    assert mem.get_profile("_test_nobody", conn=conn) == {
        "mastery": {}, "weaknesses": [], "reflections": [], "session_digest": []
    }


def test_get_profile_returns_a_fresh_object_each_call(mem, conn):
    """A shared default would accumulate one student's beliefs into every other's."""
    first = mem.get_profile("_test_nobody", conn=conn)
    first["mastery"]["spark.joins"] = {"p_mastery": 0.9}
    second = mem.get_profile("_test_nobody", conn=conn)
    assert second["mastery"] == {}


def test_get_profile_reads_stored_belief(mem, conn):
    mastery = {"spark.joins": {"p_mastery": 0.412, "n": 3}}
    weaknesses = [{"id": "w-001", "concept": "spark.joins", "status": "open"}]
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO learner_profile (student_id, mastery, weaknesses, session_digest)"
            " VALUES (%s, %s, %s, %s)",
            (STUDENT, json.dumps(mastery), json.dumps(weaknesses), json.dumps([7, 8])),
        )

    profile = mem.get_profile(STUDENT, conn=conn)
    assert profile["mastery"] == mastery
    assert profile["weaknesses"] == weaknesses
    assert profile["session_digest"] == [7, 8]
    assert profile["reflections"] == []       # column default, not written above


def test_snapshot_profile_matches_get_profile(mem, conn):
    """Today they are the same read. The test pins that equivalence so the day
    snapshot_profile stops delegating is a deliberate change, not a drift."""
    assert mem.snapshot_profile(STUDENT, conn=conn) == mem.get_profile(STUDENT, conn=conn)
