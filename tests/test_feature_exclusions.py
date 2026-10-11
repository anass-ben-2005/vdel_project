"""D-063 -- the two run-exclusion rules in features/compute_features.py, tested SEPARATELY.

  (a) tooling failures (an explicit run-id list): excluded from the OUTCOME features only --
      V1 (mastery) and V5/V6 (error response / frequency). NOT from V2 (discipline) or V4
      (pace): the student really pushed, so those runs are real activity.
  (b) sync-triggered runs (head_sha joined to raw_commits.message): excluded from
      EVERYTHING that reads raw_workflow_runs -- outcome AND pace/discipline AND the
      "who is active" list AND the watermark.

Every test runs inside one transaction that is always rolled back, against the real schema,
so nothing is left behind. Skips when no database is reachable, like the other DB tests.
"""

import os
from contextlib import contextmanager

import pytest

from features import compute_features as cf
from memory.memory import Memory
from scripts.render_student_repo import TEMPLATE_FILES
from system import db

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

SYNC_SHA = "5" * 40       # a template-sync commit
WORK_SHA = "a" * 40       # an ordinary student commit
UNKNOWN_SHA = "e" * 40    # a commit that is not in raw_commits at all
SYNC_MSG = "ci: sync template (D-060)"

# run ids are far from any real GitHub run id so a stray collision is impossible
R_FAIL, R_PASS, R_TOOL, R_SYNC = 9_800_001, 9_800_002, 9_800_003, 9_800_004
CONCEPT = "py.testing"


@pytest.fixture
def cur():
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    c = conn.cursor()
    yield c
    conn.rollback()
    conn.close()


def make_world(cur, student, runs, *, commits=True, assignment="_ex_A"):
    """One student, one assignment, optional sync+work commits, and the given runs.

    runs: (run_id, conclusion, started_at, head_sha). Commits are dated well BEFORE every
    run so the watermark and the active-student list are driven by the runs alone."""
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (student, student))
    cur.execute("INSERT INTO assignments VALUES (%s,'org/a','2026-01-01 00:00+00',"
                "'2026-02-01 00:00+00', ARRAY[%s])", (assignment, CONCEPT))
    if commits:
        # as the collector stores them: a sync commit touches no assignment file -> NULL
        for sha, msg, asg in ((SYNC_SHA, SYNC_MSG, None), (WORK_SHA, "my work", assignment)):
            cur.execute("INSERT INTO raw_commits VALUES (%s,%s,%s,'2026-01-01 08:00+00',"
                        "1,0,1,%s)", (sha, student, asg, msg))
    for run_id, conclusion, started, head in runs:
        cur.execute(
            "INSERT INTO raw_workflow_runs (run_id, student_id, assignment_id, status,"
            " conclusion, started_at, completed_at, duration_s, error_class, concept_id,"
            " head_sha) VALUES (%s,%s,%s,'completed',%s,%s,%s::timestamptz + interval '3 min',"
            " 60,%s,%s,%s)",
            (run_id, student, assignment, conclusion, started, started,
             None if conclusion == "success" else "AssertionError", CONCEPT, head))


@pytest.fixture
def tooling(monkeypatch):
    """Patch the explicit list so the tests do not depend on the real run ids."""
    monkeypatch.setattr(cf, "TOOLING_FAILURE_RUNS", {R_TOOL: "test: failed before pytest"})


def _n(payload):
    return payload["mastery"][CONCEPT]["n"]


STUDENT_RUNS = [
    (R_FAIL, "failure", "2026-01-02 10:00+00", WORK_SHA),
    (R_PASS, "success", "2026-01-02 11:00+00", WORK_SHA),
]


# --- rule (a): tooling failures -- outcome features only --------------------------------------

def test_rule_a_tooling_run_is_excluded_from_v1_v5_v6(cur, tooling):
    make_world(cur, "_ex_a", [*STUDENT_RUNS, (R_TOOL, "failure", "2026-01-02 12:00+00", None)])
    v2 = cf.compute_for_student(cur, "_ex_a", "v2")
    v3 = cf.compute_for_student(cur, "_ex_a", "v3")
    assert _n(v2) == 3 and _n(v3) == 2                       # V1
    assert v2["error_frequency"]["fail_ratio"] == pytest.approx(2 / 3, abs=1e-3)    # V6
    assert v3["error_frequency"]["fail_ratio"] == pytest.approx(1 / 2, abs=1e-3)
    assert v3["error_frequency"]["by_concept"] == {CONCEPT: 1}
    assert v3["error_frequency"]["excluded_runs"] == {"tooling": 1, "sync_triggered": 0}
    assert "excluded_runs" not in v2["error_frequency"]       # v2 output is unchanged
    assert v3["error_response"]["resolution_ratio"] == 1.0    # V5: the one failure was fixed


def test_rule_a_tooling_run_is_NOT_excluded_from_pace_discipline_or_activity(cur, tooling):
    """The student really pushed: these runs stay real activity for V2, V4 and the lists."""
    make_world(cur, "_ex_a2", [(R_TOOL, "failure", "2026-01-02 12:00+00", None)])
    v2 = cf.compute_for_student(cur, "_ex_a2", "v2")
    v3 = cf.compute_for_student(cur, "_ex_a2", "v3")
    assert v3["engineering_discipline"] == v2["engineering_discipline"]
    assert v3["engineering_discipline"]["testing"] == 1.0     # CI is wired
    assert "_ex_A" in v3["pace"] and v3["pace"] == v2["pace"]
    assert "_ex_a2" in cf.dirty_students(cur, "2026-01-02T00:00:00Z", "v3")
    assert cf.watermark(cur, "_ex_a2", "v3") == cf.watermark(cur, "_ex_a2", "v2")
    # ...while the same run IS gone from the outcome features
    assert "mastery" in v3 and CONCEPT not in v3["mastery"]
    assert v2["mastery"][CONCEPT]["n"] == 1


# --- rule (b): sync-triggered runs -- everything --------------------------------------------

def test_rule_b_sync_run_is_excluded_from_v1_v5_v6(cur, tooling):
    make_world(cur, "_ex_b", [*STUDENT_RUNS, (R_SYNC, "failure", "2026-01-02 13:00+00", SYNC_SHA)])
    v2 = cf.compute_for_student(cur, "_ex_b", "v2")
    v3 = cf.compute_for_student(cur, "_ex_b", "v3")
    assert _n(v2) == 3 and _n(v3) == 2
    assert v2["error_frequency"]["fail_ratio"] == pytest.approx(2 / 3, abs=1e-3)
    assert v3["error_frequency"]["fail_ratio"] == pytest.approx(1 / 2, abs=1e-3)
    assert v3["error_frequency"]["excluded_runs"] == {"tooling": 0, "sync_triggered": 1}
    # the failure is real, it is just not a NEW student action: v2 saw it unresolved
    assert v2["error_response"]["resolution_ratio"] < 1.0
    assert v3["error_response"]["resolution_ratio"] == 1.0


def test_rule_b_sync_run_is_ALSO_excluded_from_pace_and_discipline(cur, tooling):
    make_world(cur, "_ex_b2", [(R_SYNC, "failure", "2026-01-02 13:00+00", SYNC_SHA)])
    v2 = cf.compute_for_student(cur, "_ex_b2", "v2")
    v3 = cf.compute_for_student(cur, "_ex_b2", "v3")
    assert v2["engineering_discipline"]["testing"] == 1.0     # v2: CI "wired" by a sync run
    assert v3["engineering_discipline"]["testing"] != 1.0     # v3: the student wired nothing
    assert "_ex_A" in v2["pace"] and "_ex_A" not in v3["pace"]


def test_rule_b_sync_run_is_not_student_activity_and_not_the_watermark(cur, tooling):
    make_world(cur, "_ex_b3", [*STUDENT_RUNS, (R_SYNC, "failure", "2026-01-02 13:00+00", SYNC_SHA)])
    assert cf.watermark(cur, "_ex_b3", "v2").hour == 13        # v2: the sync run
    assert cf.watermark(cur, "_ex_b3", "v3").hour == 11        # v3: the last student run
    make_world(cur, "_ex_b4", [(R_SYNC + 1, "failure", "2026-01-02 14:00+00", SYNC_SHA)],
               commits=False, assignment="_ex_B")
    # only a sync-triggered run happened since the threshold -> not dirty under v3
    since = "2026-01-02T00:00:00Z"
    assert "_ex_b4" in cf.dirty_students(cur, since, "v2")
    assert "_ex_b4" not in cf.dirty_students(cur, since, "v3")


# --- fail-open: never exclude by guess --------------------------------------------------------

def test_a_run_without_a_known_sync_commit_is_treated_as_a_student_run(cur, tooling):
    """NULL head_sha (not backfilled yet) and a head_sha whose commit is not in raw_commits
    are both kept -- the rule needs positive evidence to exclude."""
    make_world(cur, "_ex_c", [*STUDENT_RUNS, (R_SYNC, "failure", "2026-01-02 13:00+00", None),
        (R_SYNC + 1, "failure", "2026-01-02 14:00+00", UNKNOWN_SHA)])
    v3 = cf.compute_for_student(cur, "_ex_c", "v3")
    assert _n(v3) == 4
    assert v3["error_frequency"]["excluded_runs"] == {"tooling": 0, "sync_triggered": 0}


def test_v2_is_the_unfiltered_behaviour(cur, tooling):
    make_world(cur, "_ex_d", [*STUDENT_RUNS, (R_TOOL, "failure", "2026-01-02 12:00+00", None),
        (R_SYNC, "failure", "2026-01-02 13:00+00", SYNC_SHA)])
    assert _n(cf.compute_for_student(cur, "_ex_d", "v2")) == 4
    assert _n(cf.compute_for_student(cur, "_ex_d", "v3")) == 2


def test_the_real_tooling_list_is_four_distinct_documented_runs():
    assert len(cf.TOOLING_FAILURE_RUNS) == 4
    assert all(isinstance(k, int) and v for k, v in cf.TOOLING_FAILURE_RUNS.items())
    assert cf.FORMULA_VER == "v5" and cf.SYNC_COMMIT_PREFIX == "ci: sync template"


# --- v3 rows never overwrite v2 rows -----------------------------------------------------------

def _insert_v2_row(cur, student, at):
    cur.execute("INSERT INTO learner_features (student_id, computed_at, mastery,"
                " engineering_discipline, effort_regulation, pace, error_response,"
                " error_frequency, formula_ver) VALUES (%s,%s,'{\"sentinel\":1}','{}','{}','{}',"
                "'{}','{}','v2')", (student, at))


def test_a_v3_write_never_overwrites_a_v2_row_at_the_same_watermark(cur, tooling):
    make_world(cur, "_ex_e", STUDENT_RUNS)
    at = cf.watermark(cur, "_ex_e", "v3")
    _insert_v2_row(cur, "_ex_e", at)
    payload = cf.compute_for_student(cur, "_ex_e", "v3")
    assert cf.write_features(cur, "_ex_e", payload, "v3") is False
    cur.execute("SELECT formula_ver, mastery FROM learner_features WHERE student_id='_ex_e'")
    assert cur.fetchall() == [("v2", {"sentinel": 1})]       # untouched


def test_a_v3_row_is_written_once_and_rerun_updates_only_itself(cur, tooling):
    make_world(cur, "_ex_f", STUDENT_RUNS)
    payload = cf.compute_for_student(cur, "_ex_f", "v3")
    assert cf.write_features(cur, "_ex_f", payload, "v3") is True
    assert cf.write_features(cur, "_ex_f", payload, "v3") is True        # same ver: re-run ok
    cur.execute("SELECT formula_ver FROM learner_features WHERE student_id='_ex_f'")
    assert cur.fetchall() == [("v3",)]                        # one row, not two


# --- rule (b) applied to COMMITS ---------------------------------------------------------------
# A template-sync commit is not a student action either. Under v3 it is out of V3's commit
# gaps, V6's changed_loc, and the commit side of the watermark and the active-student list.
# Rule (a) is about runs and has no meaning for commits.

def add_commit(cur, sha, student, at, additions, message, assignment="_ex_A", files_changed=1):
    cur.execute("INSERT INTO raw_commits VALUES (%s,%s,%s,%s,%s,0,%s,%s)",
                (sha, student, assignment, at, additions, files_changed, message))


def commit_world(cur, student, commits, runs=()):
    """A student with exactly these commits (sha, at, additions, message) and runs."""
    make_world(cur, student, list(runs), commits=False)
    for sha, at, additions, message, *rest in commits:
        add_commit(cur, sha, student, at, additions, message, *rest)


C1, C2, C3 = "c1" * 20, "c2" * 20, "c3" * 20


def test_commit_rule_sync_commit_makes_no_gap_in_v3(cur):
    commit_world(cur, "_ex_g", [
        (C1, "2026-01-01 08:00+00", 50, "first"),
        (C2, "2026-01-01 12:00+00", 50, "second"),                    # gap 4 h
        (C3, "2026-01-01 20:00+00", 5, SYNC_MSG, None)])                    # would be gap 8 h
    v2 = cf.compute_for_student(cur, "_ex_g", "v2")["effort_regulation"]
    v3 = cf.compute_for_student(cur, "_ex_g", "v3")["effort_regulation"]
    assert v2["burstiness"] is not None       # v2: two gaps, enough for burstiness
    assert v3["burstiness"] is None           # v3: one gap (4 h) -- the sync commit is not one


def test_commit_rule_sync_commit_adds_no_changed_loc_to_v6(cur):
    run_pair = [(R_FAIL, "failure", "2026-01-02 10:00+00", WORK_SHA),
                (R_PASS, "success", "2026-01-02 11:00+00", WORK_SHA)]
    commit_world(cur, "_ex_h", [
        (C1, "2026-01-01 08:00+00", 100, "my work"),
        (C2, "2026-01-01 09:00+00", 900, SYNC_MSG, None)], runs=run_pair)
    v2 = cf.compute_for_student(cur, "_ex_h", "v2")["error_frequency"]
    v3 = cf.compute_for_student(cur, "_ex_h", "v3")["error_frequency"]
    # score = 1 - mean(fail_ratio, min(1, errors-per-100-LOC / 5)), fail_ratio = 1/2 in both
    assert v2["score"] == pytest.approx(1 - (0.5 + 0.02) / 2, abs=1e-3)      # 1000 LOC
    assert v3["score"] == pytest.approx(1 - (0.5 + 0.20) / 2, abs=1e-3)      # 100 LOC
    assert v3["excluded_commits"] == 1 and "excluded_commits" not in v2


def test_commit_rule_watermark_ignores_a_later_sync_commit(cur):
    commit_world(cur, "_ex_w", [
        (C1, "2026-01-01 08:00+00", 10, "my work"),
        (C2, "2026-01-03 09:00+00", 5, SYNC_MSG, None)])
    assert cf.watermark(cur, "_ex_w", "v2").day == 3          # v2: the sync commit
    assert cf.watermark(cur, "_ex_w", "v3").day == 1          # v3: the last student commit


def test_commit_rule_sync_commit_alone_does_not_make_a_student_active(cur):
    commit_world(cur, "_ex_i", [(C1, "2026-01-03 09:00+00", 5, SYNC_MSG, None)])
    commit_world(cur, "_ex_j", [(C2, "2026-01-03 09:00+00", 5, "real work")]) \
        if False else None
    since = "2026-01-02T00:00:00Z"
    assert "_ex_i" in cf.dirty_students(cur, since, "v2")
    assert "_ex_i" not in cf.dirty_students(cur, since, "v3")


def test_commit_rule_real_commit_still_makes_a_student_active(cur):
    commit_world(cur, "_ex_k", [(C1, "2026-01-03 09:00+00", 5, "real work")])
    assert "_ex_k" in cf.dirty_students(cur, "2026-01-02T00:00:00Z", "v3")


def test_commit_rule_fails_open_on_a_commit_with_no_message(cur):
    """NOT starts_with(NULL, ..) is NULL; without COALESCE the row would silently vanish."""
    commit_world(cur, "_ex_n", [
        (C1, "2026-01-01 08:00+00", 50, None),
        (C2, "2026-01-01 12:00+00", 50, None),
        (C3, "2026-01-01 20:00+00", 50, None)])
    v3 = cf.compute_for_student(cur, "_ex_n", "v3")
    assert v3["effort_regulation"]["burstiness"] is not None      # all three commits kept
    assert v3["error_frequency"]["excluded_commits"] == 0


# --- what counts as a sync COMMIT: prefix AND no assignment AND few files (D-063) ----------------

def test_sync_max_files_is_the_number_of_template_files():
    assert len(TEMPLATE_FILES) == cf.SYNC_MAX_FILES


@pytest.mark.parametrize("message, assignment, files, excluded", [
    (SYNC_MSG, None, 1, True),                    # exactly what sync_template.py pushes
    (SYNC_MSG, None, 2, True),                    # both template files in one commit
    ("ci: sync template", None, 1, True),         # the bare prefix
    (SYNC_MSG, None, 3, False),                   # too many files to be a template sync
    (SYNC_MSG, None, None, False),                # files unknown -> fail open
    (SYNC_MSG, "_ex_A", 1, False),                # touches an assignment file (the known hole)
    ("fix: sync template", None, 1, False),       # not the prefix
    (None, None, 1, False),                       # no message -> fail open
])
def test_a_commit_is_a_sync_commit_only_when_all_three_facts_agree(
        cur, message, assignment, files, excluded):
    commit_world(cur, "_ex_s", [
        (C1, "2026-01-01 08:00+00", 50, "first"),
        (C2, "2026-01-01 12:00+00", 50, "second"),
        (C3, "2026-01-01 20:00+00", 5, message, assignment, files)])
    v3 = cf.compute_for_student(cur, "_ex_s", "v3")
    # a kept third commit makes a second gap, so burstiness exists; an excluded one does not
    assert (v3["effort_regulation"]["burstiness"] is None) == excluded
    assert v3["error_frequency"]["excluded_commits"] == (1 if excluded else 0)


def test_known_hole_a_run_on_a_prefixed_commit_that_has_an_assignment_is_kept(cur):
    """Legacy single-assignment repos give EVERY commit an assignment_id (D-043), so a sync
    commit there is not recognised. That is the safe direction: nothing is excluded by guess."""
    make_world(cur, "_ex_t", [*STUDENT_RUNS, (R_SYNC, "failure", "2026-01-02 13:00+00", C3)],
               commits=False)
    add_commit(cur, C3, "_ex_t", "2026-01-01 20:00+00", 5, SYNC_MSG, assignment="_ex_A")
    v3 = cf.compute_for_student(cur, "_ex_t", "v3")
    assert _n(v3) == 3                                        # the run still counts
    assert v3["error_frequency"]["excluded_runs"]["sync_triggered"] == 0


# --- run() keeps learner_profile.features_ref in step with what it writes ----------------------

@pytest.fixture
def in_txn(cur, monkeypatch):
    """Run run() inside the test's own rolled-back transaction: db.connect becomes a
    savepoint that releases on success and rolls back to itself on an exception, which is
    exactly what the real db.connect does with a commit/rollback."""
    @contextmanager
    def connect():
        cur.execute("SAVEPOINT run_sp")
        try:
            yield cur.connection
        except BaseException:
            cur.execute("ROLLBACK TO SAVEPOINT run_sp")
            raise
        else:
            cur.execute("RELEASE SAVEPOINT run_sp")

    monkeypatch.setattr(cf.db, "connect", connect)


def _profile(cur, student):
    cur.execute("SELECT * FROM learner_profile WHERE student_id=%s", (student,))
    return cur.fetchall()


def test_run_points_features_ref_at_the_row_it_wrote_and_a_rebuild_agrees(cur, in_txn):
    make_world(cur, "_ex_r", STUDENT_RUNS)
    cf.run(only=["_ex_r"])
    cur.execute("SELECT computed_at FROM learner_features WHERE student_id='_ex_r'")
    (written,) = cur.fetchone()
    cur.execute("SELECT features_ref FROM learner_profile WHERE student_id='_ex_r'")
    assert cur.fetchone()[0] == written
    rebuilt = Memory().rebuild_from_traces("_ex_r", conn=cur.connection)
    assert rebuilt["features_ref"] == written                  # live == rebuild, by construction


def test_running_run_twice_changes_nothing(cur, in_txn):
    make_world(cur, "_ex_r2", STUDENT_RUNS)
    cf.run(only=["_ex_r2"])
    cur.execute("SELECT * FROM learner_features WHERE student_id='_ex_r2'")
    features_1 = cur.fetchall()
    ref_1 = _profile(cur, "_ex_r2")[0][-1]
    cf.run(only=["_ex_r2"])
    cur.execute("SELECT * FROM learner_features WHERE student_id='_ex_r2'")
    assert cur.fetchall() == features_1 and len(features_1) == 1
    assert _profile(cur, "_ex_r2")[0][-1] == ref_1


def test_a_skipped_write_leaves_an_existing_features_ref_untouched(cur, in_txn):
    make_world(cur, "_ex_r3", STUDENT_RUNS)
    _insert_v2_row(cur, "_ex_r3", cf.watermark(cur, "_ex_r3", "v3"))   # the conflict
    cur.execute("INSERT INTO learner_profile (student_id, features_ref) "
                "VALUES ('_ex_r3', '2000-01-01 00:00+00')")
    before = _profile(cur, "_ex_r3")
    cf.run(only=["_ex_r3"])
    assert _profile(cur, "_ex_r3") == before                   # whole row, updated_at included


def test_a_skipped_write_does_not_create_a_profile(cur, in_txn):
    make_world(cur, "_ex_r4", STUDENT_RUNS)
    _insert_v2_row(cur, "_ex_r4", cf.watermark(cur, "_ex_r4", "v3"))
    cf.run(only=["_ex_r4"])
    assert _profile(cur, "_ex_r4") == []                       # nothing changed for them


def test_a_failing_sync_undoes_the_feature_row_too(cur, in_txn, monkeypatch):
    """Row and pointer are one transaction: if the pointer cannot be written, the row goes."""
    def boom(self, *a, **k):
        raise RuntimeError("sync failed")

    monkeypatch.setattr(cf.Memory, "sync_features_ref", boom)
    make_world(cur, "_ex_r5", STUDENT_RUNS)
    with pytest.raises(RuntimeError, match="sync failed"):
        cf.run(only=["_ex_r5"])
    cur.execute("SELECT count(*) FROM learner_features WHERE student_id='_ex_r5'")
    assert cur.fetchone()[0] == 0 and _profile(cur, "_ex_r5") == []
