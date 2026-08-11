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


# ---------- the replayed trace-kind set ----------

def test_every_kind_is_classified_as_mastery_bearing_or_not():
    """The guard against silence. A kind added to KINDS but classified in neither set
    would be a trace nobody decided about -- which for a mastery-bearing kind means a
    profile that is quietly wrong while still looking reconstructible."""
    assert mm.MASTERY_TRACE_KINDS | set(mm.NON_MASTERY_KINDS) == mm.KINDS
    assert mm.MASTERY_TRACE_KINDS & set(mm.NON_MASTERY_KINDS) == set()


def test_every_exclusion_states_a_reason():
    """An unexplained exclusion is indistinguishable from an oversight."""
    assert all(len(reason) > 20 for reason in mm.NON_MASTERY_KINDS.values())


def test_verdict_is_excluded_pending_m4():
    """Pins today's decision so M4 cannot start feeding verdicts into mastery without
    this test failing and forcing the rubric-score-to-BKT-outcome mapping to be decided."""
    assert "verdict" in mm.NON_MASTERY_KINDS
    assert "verdict" not in mm.MASTERY_TRACE_KINDS


# ---------- update_mastery: the replay ----------

def ci_run(mem, conn, concept, conclusion, difficulty=0.5, assignment_id=ASSIGNMENT,
          error_class=None):
    """Log one assessed attempt. Returns its trace_id.

    Defaults `assignment_id` to the fixture's ASSIGNMENT: mastery replay doesn't care about
    it, but `apply_recurrence_rule`'s window does ("within one assignment"), so a trace
    with no assignment_id would silently never match its `WHERE assignment_id = %s`.

    `error_class` defaults to None -- mastery replay never reads it; only recurrence tests
    pass one, mirroring `classify_error()`'s real return shape (error_class, concept).

    Replay order is (ts, trace_id); traces logged in sequence here share a ts to the
    microsecond only rarely, and trace_id breaks the tie deterministically either way.
    """
    payload = {"conclusion": conclusion, "item_difficulty": difficulty,
              "error_class": error_class}
    return mem.log_trace(STUDENT, "system", "ci_run", payload,
                         concept_ids=[concept], assignment_id=assignment_id, conn=conn)


def test_one_pass_reproduces_the_hand_computed_bkt_update(mem, conn):
    """Worked example, difficulty 0.5, prior p_l0 = 0.30:
        for_item(0.5): guess = 0.20*(1-0.5) = 0.10 ; slip = 0.10 + (0.40-0.10)*0.5*0.5 = 0.175
        correct:  num = 0.30*(1-0.175) = 0.2475
                  den = 0.2475 + (1-0.30)*0.10 = 0.3175
                  post = 0.2475/0.3175 = 0.779527
        learning: 0.779527 + (1-0.779527)*0.15 = 0.812598 -> 0.8126
    """
    ci_run(mem, conn, "spark.joins", "success")
    shape = mem.update_mastery(STUDENT, "spark.joins", conn=conn)
    assert shape["p_mastery"] == 0.8126
    assert shape["n"] == 1
    assert shape["param_set"] == "bkt_v1"
    assert "p_correct_next" in shape       # the falsifiable quantity (CLAUDE.md 8)


def test_confidence_grows_with_evidence(mem, conn):
    """The D-007 regression test.

    B.5 restored p_mastery and n_obs but not the Beta posterior, so confidence sat at
    0.286 forever: n was carried while the interval that gives n its meaning was not,
    structurally violating invariant 8. Replay keeps the full state, so confidence has to
    rise as observations accumulate.
    """
    ci_run(mem, conn, "sql.joins", "success")
    first = mem.update_mastery(STUDENT, "sql.joins", conn=conn)

    for _ in range(4):
        ci_run(mem, conn, "sql.joins", "success")
    fifth = mem.update_mastery(STUDENT, "sql.joins", conn=conn)

    assert first["n"] == 1 and fifth["n"] == 5
    assert first["confidence"] == 0.286        # the frozen value, correct at n=1
    assert fifth["confidence"] > first["confidence"]
    assert fifth["confidence"] == 0.702        # and it is this, not 0.286
    assert fifth["ci90"] != first["ci90"]      # the interval moves too


def test_update_mastery_is_idempotent(mem, conn):
    """A pure function of the log: recomputing does not count as another attempt.
    This is the property an outcome-taking signature cannot have."""
    ci_run(mem, conn, "spark.aggregation", "failure")
    ci_run(mem, conn, "spark.aggregation", "success")

    once = mem.update_mastery(STUDENT, "spark.aggregation", conn=conn)
    twice = mem.update_mastery(STUDENT, "spark.aggregation", conn=conn)
    assert once == twice
    assert once["n"] == 2


def test_order_matters_and_follows_the_log(mem, conn):
    """BKT is order-dependent, so fail-then-pass must not equal pass-then-fail."""
    ci_run(mem, conn, "py.testing", "failure")
    ci_run(mem, conn, "py.testing", "success")
    fail_then_pass = mem.update_mastery(STUDENT, "py.testing", conn=conn)

    ci_run(mem, conn, "py.pandas", "success")
    ci_run(mem, conn, "py.pandas", "failure")
    pass_then_fail = mem.update_mastery(STUDENT, "py.pandas", conn=conn)

    assert fail_then_pass["p_mastery"] != pass_then_fail["p_mastery"]


def test_item_difficulty_is_read_from_the_payload(mem, conn):
    """KT-IDEM conditioning. B.5's rebuild replayed at a hardcoded 0.5, so any attempt
    logged at another difficulty made the rebuild disagree with the live update."""
    ci_run(mem, conn, "spark.partitioning", "failure", difficulty=0.9)
    ci_run(mem, conn, "spark.partitioning", "success", difficulty=0.9)
    hard = mem.update_mastery(STUDENT, "spark.partitioning", conn=conn)

    ci_run(mem, conn, "sql.aggregation", "failure", difficulty=0.1)
    ci_run(mem, conn, "sql.aggregation", "success", difficulty=0.1)
    easy = mem.update_mastery(STUDENT, "sql.aggregation", conn=conn)

    # Passing a hard item is stronger evidence of mastery than passing an easy one.
    assert hard["p_mastery"] > easy["p_mastery"]
    assert (hard["p_mastery"], easy["p_mastery"]) == (0.9313, 0.6163)


@pytest.mark.parametrize("conclusion", ["cancelled", "skipped", "timed_out", "neutral"])
def test_non_assessed_conclusions_are_not_evidence(mem, conn, conclusion):
    """A cancelled CI run says something about infrastructure, not about the student.
    B.5's `== "success"` would have scored every one of these as a failure."""
    ci_run(mem, conn, "airflow.idempotency", "success")
    baseline = mem.update_mastery(STUDENT, "airflow.idempotency", conn=conn)

    ci_run(mem, conn, "airflow.idempotency", conclusion)
    after = mem.update_mastery(STUDENT, "airflow.idempotency", conn=conn)
    assert after == baseline


def test_non_mastery_kinds_are_not_replayed(mem, conn):
    """A commit tagged with a concept is activity, not an assessed attempt."""
    mem.log_trace(STUDENT, "system", "commit", {"conclusion": "success"},
                  concept_ids=["py.data_structures"], conn=conn)
    assert mem.update_mastery(STUDENT, "py.data_structures", conn=conn) is None


def test_unclassified_updates_no_mastery(mem, conn):
    """Invariant 10, at the door rather than only at the classifier."""
    ci_run(mem, conn, "unclassified", "failure")
    assert mem.update_mastery(STUDENT, "unclassified", conn=conn) is None


def test_no_evidence_leaves_the_profile_untouched(mem, conn):
    assert mem.update_mastery(STUDENT, "spark.df_basics", conn=conn) is None
    assert mem.get_profile(STUDENT, conn=conn)["mastery"] == {}


# ---------- update_mastery: what it writes ----------

def test_update_mastery_writes_a_profile_update_trace_with_parentage(mem, conn):
    """Memory records its own changes, so "why did this number move?" has an answer."""
    run_id = ci_run(mem, conn, "spark.joins", "success")
    shape = mem.update_mastery(STUDENT, "spark.joins", parent_trace_id=run_id, conn=conn)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT actor, concept_ids, payload, parent_trace_id FROM traces"
            " WHERE student_id = %s AND kind = 'profile_update'",
            (STUDENT,),
        )
        actor, concept_ids, payload, parent = cur.fetchone()
    assert (actor, concept_ids, parent) == ("system", ["spark.joins"], run_id)
    assert payload["p_mastery"] == shape["p_mastery"]


def test_mastery_merges_without_clobbering_other_concepts(mem, conn):
    """The write is a jsonb merge in SQL, not a read-modify-write of the whole object."""
    ci_run(mem, conn, "spark.joins", "success")
    mem.update_mastery(STUDENT, "spark.joins", conn=conn)
    ci_run(mem, conn, "sql.joins", "failure")
    mem.update_mastery(STUDENT, "sql.joins", conn=conn)

    mastery = mem.get_profile(STUDENT, conn=conn)["mastery"]
    assert set(mastery) == {"spark.joins", "sql.joins"}


def test_profile_write_and_its_trace_are_atomic(mem, conn):
    """Neither survives a rollback -- so a belief can never exist without its audit
    record. This is what the optional conn was built for."""
    ci_run(mem, conn, "spark.joins", "success")
    mem.update_mastery(STUDENT, "spark.joins", conn=conn)
    conn.rollback()

    with db.connect() as other, other.cursor() as cur:
        cur.execute("SELECT count(*) FROM learner_profile WHERE student_id = %s", (STUDENT,))
        profiles = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM traces WHERE student_id = %s AND kind = 'profile_update'",
            (STUDENT,),
        )
        traces = cur.fetchone()[0]
    assert (profiles, traces) == (0, 0)


# ---------- rebuild: the event-sourcing proof, mastery half ----------

def test_rebuild_reproduces_what_the_fast_path_cached(mem, conn):
    """The M2 DoD in miniature: wipe the cache, replay the log, get the same numbers.
    It holds by construction here -- both paths are the same function."""
    ci_run(mem, conn, "spark.joins", "failure")
    ci_run(mem, conn, "spark.joins", "success")
    ci_run(mem, conn, "sql.joins", "success", difficulty=0.8)
    for concept in ("spark.joins", "sql.joins"):
        mem.update_mastery(STUDENT, concept, conn=conn)

    before = mem.get_profile(STUDENT, conn=conn)["mastery"]

    with conn.cursor() as cur:
        cur.execute("DELETE FROM learner_profile WHERE student_id = %s", (STUDENT,))
    assert mem.get_profile(STUDENT, conn=conn)["mastery"] == {}

    rebuilt = mem.rebuild_mastery_from_traces(STUDENT, conn=conn)
    assert rebuilt == before
    assert mem.get_profile(STUDENT, conn=conn)["mastery"] == before


def test_rebuild_writes_no_profile_update_traces(mem, conn):
    """A rebuild recomputes what the log implies; it is not new evidence. Logging one
    would make the proof grow the log every time it was run."""
    ci_run(mem, conn, "spark.joins", "success")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM traces WHERE student_id = %s AND kind = 'profile_update'",
            (STUDENT,),
        )
        before = cur.fetchone()[0]

    mem.rebuild_mastery_from_traces(STUDENT, conn=conn)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM traces WHERE student_id = %s AND kind = 'profile_update'",
            (STUDENT,),
        )
        assert cur.fetchone()[0] == before


def test_rebuild_skips_unclassified(mem, conn):
    ci_run(mem, conn, "unclassified", "failure")
    ci_run(mem, conn, "spark.joins", "success")
    assert set(mem.rebuild_mastery_from_traces(STUDENT, conn=conn)) == {"spark.joins"}


# ---------- open_weakness: the raw primitive ----------

def test_open_weakness_returns_the_id_of_the_trace_it_writes(mem, conn):
    """w-{trace_id}, not a length-based counter -- collision-free by construction."""
    wid = mem.open_weakness(STUDENT, "spark.joins", "note", [1, 2], conn=conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trace_id FROM traces WHERE student_id = %s AND kind = 'profile_update'"
            " AND payload->>'action' = 'weakness_opened'",
            (STUDENT,),
        )
        trace_id = cur.fetchone()[0]
    assert wid == f"w-{trace_id}"


def test_open_weakness_writes_a_complete_object(mem, conn):
    wid = mem.open_weakness(STUDENT, "spark.joins", "recurring grain errors", [10, 11],
                            conn=conn)
    weaknesses = mem.get_profile(STUDENT, conn=conn)["weaknesses"]
    assert len(weaknesses) == 1
    w = weaknesses[0]
    assert w["id"] == wid
    assert w["concept"] == "spark.joins"
    assert w["status"] == "open"
    assert w["note"] == "recurring grain errors"
    assert w["evidence"] == [10, 11]
    assert w["interventions"] == []
    assert "T" in w["opened_at"]                    # a real ISO timestamp, not "now"


def test_open_weakness_truncates_the_note_to_120_chars(mem, conn):
    wid = mem.open_weakness(STUDENT, "spark.joins", "x" * 200, [1], conn=conn)
    w = mem.get_profile(STUDENT, conn=conn)["weaknesses"][0]
    assert w["id"] == wid
    assert len(w["note"]) == 120


def test_two_opens_do_not_clobber_each_other(mem, conn):
    """The SQL-merge property, for weaknesses instead of mastery."""
    w1 = mem.open_weakness(STUDENT, "spark.joins", "n1", [1], conn=conn)
    w2 = mem.open_weakness(STUDENT, "sql.joins", "n2", [2], conn=conn)
    ids = {w["id"] for w in mem.get_profile(STUDENT, conn=conn)["weaknesses"]}
    assert ids == {w1, w2}


# ---------- apply_recurrence_rule ----------
#
# error_class strings below are chosen to match real collectors/error_classifier.py RULES
# entries (e.g. "ambiguous column" -> spark.joins, "cartesian product|cross join" ->
# spark.joins) for realism, without calling the classifier itself -- that module has its
# own test suite; these tests are about apply_recurrence_rule's logic, not classification.

def test_recurrence_rule_does_nothing_below_threshold(mem, conn):
    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column")
    wid = mem.apply_recurrence_rule(STUDENT, ASSIGNMENT, "ambiguous column", "spark.joins",
                                    conn=conn)
    assert wid is None
    assert mem.get_profile(STUDENT, conn=conn)["weaknesses"] == []


def test_recurrence_rule_opens_on_the_second_occurrence_of_the_same_error_class(mem, conn):
    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column")
    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column")
    wid = mem.apply_recurrence_rule(STUDENT, ASSIGNMENT, "ambiguous column", "spark.joins",
                                    conn=conn)
    assert wid is not None
    w = mem.get_profile(STUDENT, conn=conn)["weaknesses"][0]
    assert w["id"] == wid
    assert w["concept"] == "spark.joins"               # tagged by concept, triggered by error_class
    assert len(w["evidence"]) == 2


def test_two_different_error_classes_on_the_same_concept_do_not_recur(mem, conn):
    """The D-011 regression test. D-009's original (wrong) reading counted by concept, so
    two DIFFERENT error classes mapping to the same concept, once each, would have opened a
    weakness. recurrence_check counts by error_class -- Becker's signal is the SAME mistake
    repeating, not merely the same topic area -- so this must NOT open one."""
    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column")
    ci_run(mem, conn, "spark.joins", "failure", error_class="cartesian product|cross join")
    assert mem.apply_recurrence_rule(
        STUDENT, ASSIGNMENT, "ambiguous column", "spark.joins", conn=conn) is None
    assert mem.apply_recurrence_rule(
        STUDENT, ASSIGNMENT, "cartesian product|cross join", "spark.joins", conn=conn) is None
    assert mem.get_profile(STUDENT, conn=conn)["weaknesses"] == []


def test_recurrence_rule_is_idempotent(mem, conn):
    """Safe to call after every failure, not just the one that crosses the threshold."""
    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column")
    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column")
    first = mem.apply_recurrence_rule(STUDENT, ASSIGNMENT, "ambiguous column", "spark.joins",
                                      conn=conn)

    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column")
    second = mem.apply_recurrence_rule(STUDENT, ASSIGNMENT, "ambiguous column", "spark.joins",
                                       conn=conn)

    assert first is not None
    assert second is None                             # already open -- dedup, not a re-open
    assert len(mem.get_profile(STUDENT, conn=conn)["weaknesses"]) == 1


def test_recurrence_rule_does_not_cross_assignments(mem, conn):
    """"Within one assignment" is the window -- one occurrence in each of two assignments
    must not sum to a recurrence."""
    other_assignment = "_test_mem_a2"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO assignments (assignment_id, repo_prefix, released_at, concepts)"
            " VALUES (%s, 'org/a2', '2026-03-02 09:00+00', ARRAY['spark.joins'])",
            (other_assignment,),
        )

    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column",
          assignment_id=ASSIGNMENT)
    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column",
          assignment_id=other_assignment)

    assert mem.apply_recurrence_rule(
        STUDENT, ASSIGNMENT, "ambiguous column", "spark.joins", conn=conn) is None
    assert mem.apply_recurrence_rule(
        STUDENT, other_assignment, "ambiguous column", "spark.joins", conn=conn) is None
    assert mem.get_profile(STUDENT, conn=conn)["weaknesses"] == []


def test_recurrence_rule_ignores_unclassified(mem, conn):
    ci_run(mem, conn, "unclassified", "failure", error_class="totally unrecognised text")
    ci_run(mem, conn, "unclassified", "failure", error_class="totally unrecognised text")
    assert mem.apply_recurrence_rule(
        STUDENT, ASSIGNMENT, "totally unrecognised text", "unclassified", conn=conn) is None


def test_recurrence_rule_empty_error_class_short_circuits(mem, conn):
    """An empty/falsy error_class is treated like `UNCLASSIFIED`'s guard -- nothing to
    count, so it returns before ever querying."""
    assert mem.apply_recurrence_rule(STUDENT, ASSIGNMENT, "", "spark.joins", conn=conn) is None


def test_ci_run_traces_without_an_error_class_contribute_to_no_count(mem, conn):
    """A ci_run trace logged with no error_class (nothing production writes yet, per the
    module docstring's known gaps) must not silently satisfy a real error_class's count."""
    ci_run(mem, conn, "spark.joins", "failure")   # error_class defaults to None
    ci_run(mem, conn, "spark.joins", "failure")
    wid = mem.apply_recurrence_rule(STUDENT, ASSIGNMENT, "ambiguous column", "spark.joins",
                                    conn=conn)
    assert wid is None


def test_recurrence_rule_reopens_after_a_closed_weakness(mem, conn):
    """Dedup is against OPEN weaknesses only. A concept recurring after its earlier
    weakness closed is new evidence and gets a new weakness, not silence."""
    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column")
    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column")
    first = mem.apply_recurrence_rule(STUDENT, ASSIGNMENT, "ambiguous column", "spark.joins",
                                      conn=conn)

    # No close_weakness() exists yet (piece 4 / the slow path) -- this simulates its
    # eventual effect directly on learner_profile so this test doesn't have to wait for it.
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE learner_profile SET weaknesses = "
            "  jsonb_set(weaknesses, '{0,status}', '\"closed\"')"
            " WHERE student_id = %s",
            (STUDENT,),
        )

    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column")
    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column")
    second = mem.apply_recurrence_rule(STUDENT, ASSIGNMENT, "ambiguous column", "spark.joins",
                                       conn=conn)

    assert second is not None
    assert second != first
    statuses = {w["id"]: w["status"] for w in mem.get_profile(STUDENT, conn=conn)["weaknesses"]}
    assert statuses == {first: "closed", second: "open"}


def test_recurrence_evidence_is_only_the_matching_error_class(mem, conn):
    """A different error_class on the same concept, and a pass, are both noise here."""
    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column")
    ci_run(mem, conn, "spark.joins", "success", error_class=None)
    ci_run(mem, conn, "spark.joins", "failure", error_class="cartesian product|cross join")
    ci_run(mem, conn, "spark.joins", "failure", error_class="ambiguous column")
    wid = mem.apply_recurrence_rule(STUDENT, ASSIGNMENT, "ambiguous column", "spark.joins",
                                    conn=conn)
    assert wid is not None
    assert len(mem.get_profile(STUDENT, conn=conn)["weaknesses"][0]["evidence"]) == 2


# ---------- link_intervention ----------

def test_link_intervention_appends_the_trace_id(mem, conn):
    wid = mem.open_weakness(STUDENT, "spark.joins", "n", [1], conn=conn)
    hint_id = mem.log_trace(STUDENT, "coach", "intervention", {"hint": "check the join key"},
                            concept_ids=["spark.joins"], conn=conn)

    mem.link_intervention(STUDENT, wid, hint_id, conn=conn)

    w = mem.get_profile(STUDENT, conn=conn)["weaknesses"][0]
    assert w["interventions"] == [hint_id]


def test_link_intervention_is_idempotent(mem, conn):
    wid = mem.open_weakness(STUDENT, "spark.joins", "n", [1], conn=conn)
    hint_id = mem.log_trace(STUDENT, "coach", "intervention", {}, conn=conn)

    mem.link_intervention(STUDENT, wid, hint_id, conn=conn)
    mem.link_intervention(STUDENT, wid, hint_id, conn=conn)

    w = mem.get_profile(STUDENT, conn=conn)["weaknesses"][0]
    assert w["interventions"] == [hint_id]           # not [hint_id, hint_id]


def test_link_intervention_does_not_touch_other_weaknesses(mem, conn):
    w1 = mem.open_weakness(STUDENT, "spark.joins", "n1", [1], conn=conn)
    w2 = mem.open_weakness(STUDENT, "sql.joins", "n2", [2], conn=conn)
    hint_id = mem.log_trace(STUDENT, "coach", "intervention", {}, conn=conn)

    mem.link_intervention(STUDENT, w1, hint_id, conn=conn)

    profile = mem.get_profile(STUDENT, conn=conn)
    weaknesses = {w["id"]: w["interventions"] for w in profile["weaknesses"]}
    assert weaknesses == {w1: [hint_id], w2: []}


def test_link_intervention_raises_on_an_unknown_weakness_id(mem, conn):
    """B.5 silently no-ops here. A hint recorded against a typo'd id is a broken link that
    should fail loudly, immediately -- not days later in the reflection job's validation."""
    with pytest.raises(ValueError, match="unknown weakness_id"):
        mem.link_intervention(STUDENT, "w-does-not-exist", 1, conn=conn)


def test_link_intervention_records_its_own_trace(mem, conn):
    wid = mem.open_weakness(STUDENT, "spark.joins", "n", [1], conn=conn)
    hint_id = mem.log_trace(STUDENT, "coach", "intervention", {}, conn=conn)
    mem.link_intervention(STUDENT, wid, hint_id, conn=conn)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload, parent_trace_id FROM traces WHERE student_id = %s"
            " AND kind = 'profile_update' AND payload->>'action' = 'intervention_linked'",
            (STUDENT,),
        )
        payload, parent = cur.fetchone()
    assert payload["weakness_id"] == wid
    assert payload["intervention_trace_id"] == hint_id
    assert parent == hint_id
