"""scripts/prove_event_sourcing.py -- the event-sourcing proof (BUILD_PLAN 2.6).

The proof's whole value is that it FAILS when the profile has drifted from its log, so most
of what is tested here is its ability to fail: a tampered mastery value, an invented
weakness, and a vacuous run against an empty database must each be caught. A proof that
always prints IDENTICAL proves nothing.

`prove()` neither commits nor rolls back, which is what lets these tests drive it on a
connection they roll back themselves -- so nothing here leaves residue, and in particular
nothing commits a trace (which could not be deleted afterwards; sql/05's RULEs make DELETE
a silent no-op).
"""
import json
import os

import pytest

from memory.memory import Memory
from scripts.prove_event_sourcing import (
    _ABSENT,
    diff_values,
    main,
    prove,
    read_profiles,
)
from system import db

STUDENT = "_test_pes"
ASSIGNMENT = "_test_pes_a1"

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; the proof needs a database"
)


# ---------- diff_values: pure, no database ----------

def test_identical_structures_produce_no_differences():
    profile = {"mastery": {"sql.joins": {"p_mastery": 0.4, "n": 2}}, "weaknesses": []}
    assert list(diff_values(profile, profile)) == []


def test_a_differing_scalar_is_reported_with_its_value():
    assert list(diff_values({"n": 2}, {"n": 3})) == [("n", 2, 3)]


def test_a_nested_difference_reports_the_full_path():
    before = {"mastery": {"sql.joins": {"p_mastery": 0.41}}}
    after = {"mastery": {"sql.joins": {"p_mastery": 0.99}}}
    assert list(diff_values(before, after)) == [("mastery.sql.joins.p_mastery", 0.41, 0.99)]


def test_a_key_present_on_only_one_side_is_reported_as_absent():
    assert list(diff_values({}, {"trend": "up"})) == [("trend", _ABSENT, "up")]
    assert list(diff_values({"trend": "up"}, {})) == [("trend", "up", _ABSENT)]


def test_a_list_length_difference_is_reported():
    differences = list(diff_values({"w": [1, 2]}, {"w": [1]}))
    assert ("w[length]", 2, 1) in differences


def test_a_list_element_difference_is_reported_by_index():
    before = {"w": [{"status": "open"}, {"status": "open"}]}
    after = {"w": [{"status": "open"}, {"status": "closed"}]}
    assert list(diff_values(before, after)) == [("w[1].status", "open", "closed")]


def test_a_container_against_a_scalar_differs():
    assert list(diff_values({"m": {"a": 1}}, {"m": 7})) == [("m", {"a": 1}, 7)]


def test_equal_values_of_different_shape_are_not_silently_equal():
    """[] and {} are both empty and both falsy; they are not the same stored value."""
    assert list(diff_values({"x": []}, {"x": {}})) == [("x", [], {})]


# ---------- prove(): against the database ----------

@pytest.fixture
def conn():
    try:
        connection = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    try:
        with connection.cursor() as cur:
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
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def mem():
    return Memory()


def _profiles_exist() -> bool:
    """Is `learner_profile` non-empty in the shared dev database right now?

    Moved above its first use (originally only guarded the CLI-level vacuous test) because
    D-034 exposed the same problem one level down: once a real student (`anas`) has a real,
    permanently committed profile, `learner_profile` is never globally empty in this shared
    dev database again, no matter what a test's own STUDENT fixture does or rolls back. Any
    test whose premise is "nothing exists yet" needs this guard now, not just the CLI test.

    Evaluated at COLLECTION time by each `skipif` below, so it must never raise. `pytestmark`
    does not protect a decorator argument -- that is evaluated while the module is being
    imported, before any marker is consulted. An unguarded version of this function once
    aborted the ENTIRE suite with `RuntimeError: PG_DSN is not set` during collection instead
    of skipping, for anyone without a configured .env.
    """
    if not os.environ.get("PG_DSN"):
        return False
    try:
        with db.cursor() as cur:
            cur.execute("SELECT count(*) FROM learner_profile")
            return cur.fetchone()[0] > 0
    except Exception:  # noqa: BLE001 -- unreachable DB means "cannot know", and the
        return False   # module-level skipif will skip this test anyway


def faithful_history(mem, conn):
    """Profile state written entirely through the fast path, so the log fully justifies it."""
    def ci_run(concept, conclusion, error_class=None, difficulty=0.5):
        return mem.log_trace(
            STUDENT, "system", "ci_run",
            {"conclusion": conclusion, "item_difficulty": difficulty,
             "error_class": error_class},
            concept_ids=[concept], assignment_id=ASSIGNMENT, conn=conn,
        )

    ci_run("spark.joins", "failure", "ambiguous column")
    ci_run("spark.joins", "failure", "ambiguous column")
    mem.update_mastery(STUDENT, "spark.joins", conn=conn)
    weakness_id = mem.apply_recurrence_rule(
        STUDENT, ASSIGNMENT, "ambiguous column", "spark.joins", conn=conn)
    hint = mem.log_trace(STUDENT, "coach", "intervention", {"hint": "check the key"},
                         conn=conn)
    mem.link_intervention(STUDENT, weakness_id, hint, conn=conn)
    ci_run("sql.joins", "success", difficulty=0.8)
    mem.update_mastery(STUDENT, "sql.joins", conn=conn)
    return weakness_id


def test_a_faithful_profile_proves_identical(mem, conn):
    """The M2 DoD, as the script actually runs it."""
    faithful_history(mem, conn)
    result = prove(conn)
    assert result.differences == []
    assert result.identical
    assert not result.vacuous
    assert STUDENT in result.compared


def test_the_proof_does_not_touch_traces(mem, conn):
    """A proof that modified the log it replays would prove nothing."""
    faithful_history(mem, conn)
    result = prove(conn)
    assert result.traces_after == result.traces_before


def test_the_wipe_actually_empties_the_table(mem, conn):
    """The wipe is observed, not merely performed.

    Mutation testing found that removing the TRUNCATE altogether left every other test
    passing, because `rebuild_from_traces` replaces each column rather than merging -- so
    the rebuild overwrote the profile regardless. The wipe still has to happen: BUILD_PLAN
    2.6 specifies it, it is the demo's core claim, and it is what would expose a future
    rebuild that merged into existing state instead of deriving it. A step nothing checks
    is a step that can silently stop happening.
    """
    faithful_history(mem, conn)
    assert read_profiles(conn) != {}                 # there was something to wipe
    result = prove(conn)
    assert result.rows_after_wipe == 0


def test_a_tampered_mastery_value_is_caught(mem, conn):
    """The proof's reason to exist. A hand-edited belief the log does not justify must be
    named, with its path and both values."""
    faithful_history(mem, conn)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE learner_profile"
            " SET mastery = jsonb_set(mastery, '{spark.joins,p_mastery}', '0.99')"
            " WHERE student_id = %s",
            (STUDENT,),
        )

    result = prove(conn)

    assert not result.identical
    # 0.1931 is what the log actually justifies: two failures at difficulty 0.5 from
    # p_l0=0.30. Hand-derived, with for_item(0.5) giving guess 0.10 / slip 0.175:
    #   fail 1: num = 0.30*0.175 = 0.0525 ; den = 0.0525 + 0.70*0.90 = 0.6825
    #           post = 0.076923 ; +learning -> 0.076923 + 0.923077*0.15 = 0.2154
    #   fail 2: num = 0.2154*0.175 = 0.037692 ; den = 0.037692 + 0.7846*0.90 = 0.743846
    #           post = 0.050672 ; +learning -> 0.050672 + 0.949328*0.15 = 0.1931
    paths = {(d.path, d.snapshot, d.rebuilt) for d in result.differences}
    assert ("mastery.spark.joins.p_mastery", 0.99, 0.1931) in paths


def test_an_invented_weakness_is_caught(mem, conn):
    faithful_history(mem, conn)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE learner_profile SET weaknesses = weaknesses || %s::jsonb"
            " WHERE student_id = %s",
            (json.dumps([{"id": "w-fake", "concept": "py.testing", "status": "open",
                          "note": "invented", "evidence": [], "opened_at": "whenever",
                          "interventions": []}]), STUDENT),
        )

    result = prove(conn)

    assert not result.identical
    assert any(d.path.startswith("weaknesses") for d in result.differences)


def test_a_silently_dropped_intervention_link_is_caught(mem, conn):
    """The subtle case: the weakness still exists and looks right, but the closed loop
    (which hint targeted it) has been broken."""
    faithful_history(mem, conn)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE learner_profile"
            " SET weaknesses = jsonb_set(weaknesses, '{0,interventions}', '[]')"
            " WHERE student_id = %s",
            (STUDENT,),
        )

    result = prove(conn)

    assert not result.identical
    assert any("interventions" in d.path for d in result.differences)


def test_a_student_with_no_prior_profile_is_reported_not_failed(mem, conn):
    """A student whose fast path has not run yet gains a profile from the rebuild. That is
    the rebuild being correct, not a mismatch, so it must not fail the proof.

    Scoped to STUDENT specifically, not to `learner_profile` being globally empty: D-034
    means a real student (`anas`) now has a real, permanently committed profile in the
    shared dev database, so a global `read_profiles(conn) == {}` / `result.vacuous` check
    would fail for a reason unrelated to what this test is actually about.
    """
    mem.log_trace(
        STUDENT, "system", "ci_run",
        {"conclusion": "success", "item_difficulty": 0.5, "error_class": None},
        concept_ids=["spark.joins"], assignment_id=ASSIGNMENT, conn=conn,
    )
    assert STUDENT not in read_profiles(conn)   # nothing called update_mastery for STUDENT

    result = prove(conn)

    assert STUDENT in result.created
    assert STUDENT not in result.compared
    assert not any(d.student_id == STUDENT for d in result.differences)


@pytest.mark.skipif(_profiles_exist(), reason="needs an empty learner_profile to be vacuous "
                                               "-- see D-034: anas's real profile means the "
                                               "shared dev DB is no longer globally empty")
def test_no_profiles_is_vacuous_not_identical(mem, conn):
    """'IDENTICAL' with nothing to compare would be true and worthless."""
    result = prove(conn)
    assert result.vacuous
    assert result.compared == []


# ---------- the CLI ----------
# `_profiles_exist` is defined above, next to `mem` -- both database-emptiness-dependent
# tests need it now (D-034), not just this one.


@pytest.mark.skipif(_profiles_exist(), reason="needs an empty learner_profile to be vacuous")
def test_main_exits_nonzero_on_a_vacuous_proof():
    """So neither CI nor a DoD write-up can mistake an empty database for a passing proof."""
    assert main([]) == 2
