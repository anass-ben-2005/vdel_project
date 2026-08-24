"""
features/compute_features.py — turn raw tables into the seven variables.

Optimization (Flaw 5): only recompute students with NEW activity since the last run.
Unchanged inputs produce unchanged features, so recomputing them is pure waste.

Based on VDEL_Modules_1_2_Build.md Part C. That version is explicitly a skeleton --
"Query details elided for brevity ... call the respective Module-1 functions with
queried inputs" -- with only mastery and effort implemented. This file fills in the
elided queries for all seven variables. Every variable function is called with the
document's signature; none of the formulas live here.

Two reconciliations, both flagged where they occur:
  1. computed_at is set from the student's data watermark instead of defaulting to
     now(), because the M1 DoD requires "a deliberate re-run changes nothing" and a
     now() default makes every re-run a new row by construction.
  2. Inputs M1 cannot measure (lint counts, cohort statistics) are passed as the
     documented "absent" values rather than invented. See each call site.

Run:  python -m features.compute_features
"""
import os
from statistics import median

from psycopg2.extras import Json

from memory.memory import Memory
from system import db
from variables.error_frequency import error_frequency
from variables.error_response import error_response
from variables.habits import effort_regulation, engineering_discipline
from variables.mastery import MasteryEstimator
from variables.pace import learning_pace

WINDOW_DAYS = int(os.environ.get("FEATURE_WINDOW_DAYS", "14"))

# KT-IDEM item difficulty is 1 - Beta-smoothed COHORT pass rate (mastery.py,
# DifficultyEstimator). With one student there is no cohort, so the document's own
# neutral default stands in. Recompute from `items` once a cohort exists.
NEUTRAL_DIFFICULTY = 0.5


def dirty_students(cur, last_run_iso):
    """Flaw 5: who actually did something since the last feature run?"""
    cur.execute("""
        SELECT DISTINCT student_id FROM raw_commits WHERE committed_at > %s
        UNION
        SELECT DISTINCT student_id FROM raw_workflow_runs WHERE started_at > %s
    """, (last_run_iso, last_run_iso))
    return [r[0] for r in cur.fetchall()]


def watermark(cur, student_id):
    """The student's most recent raw event.

    Reconciliation 1: used as computed_at so that re-running with no new activity
    targets the same primary key and rewrites identical values. Ties the feature row to
    the exact data that produced it, which is also what makes the row reproducible.
    """
    cur.execute("""
        SELECT max(ts) FROM (
            SELECT max(committed_at) AS ts FROM raw_commits       WHERE student_id=%s
            UNION ALL
            SELECT max(started_at)   AS ts FROM raw_workflow_runs WHERE student_id=%s
        ) e
    """, (student_id, student_id))
    return cur.fetchone()[0]


def _item_difficulty(cur, concept_id):
    """Cohort-derived difficulty for the concept, or the neutral default."""
    cur.execute("""
        SELECT avg(difficulty) FROM items
        WHERE %s = ANY(concept_ids) AND n_cohort_obs > 0
    """, (concept_id,))
    row = cur.fetchone()[0]
    return float(row) if row is not None else NEUTRAL_DIFFICULTY


def _mastery(cur, student_id):
    """V1 — replay classified pass/fails through BKT.

    Two evidence sources, merged CHRONOLOGICALLY into one replay -- BKT is order-
    dependent, so replaying source A fully then source B fully would not reproduce the
    real interleaved sequence of observations, and D-007's whole argument is that replay
    order must match reality, not code layout:
      - raw_workflow_runs: real CI telemetry (collect_github.py) -- the original
        source, still real evidence for repos outside the gap-based curriculum model
        (e.g. Anas's own Kaggle-pipeline repos).
      - test_result traces (D-045/D-046, EXECUTION.md Stage C1): every hidden-test
        outcome test_runner.py logs, read through `memory.Memory.test_result_history`
        ONLY -- never a second raw SQL query against `traces` from outside memory.py
        (invariant 2).

    'unclassified' is excluded for raw_workflow_runs (error_classifier.py, invariant
    10). test_result traces carry no such sentinel -- a test with no gap_id was already
    excluded at the point test_runner.py decided whether to log a trace at all
    (`_log_mastery_traces`'s own filter), so every test_result trace that exists already
    carries a real, resolved concept.

    A trace tagged with SEVERAL concept_ids contributes to EACH of them -- the same
    containment semantics `memory.py::_replay_concept`'s `concept_ids @> ARRAY[concept]`
    already gives every other MASTERY_TRACE_KINDS member; one gap can exercise two
    concepts, and the same pass/fail is real evidence about both.
    """
    cur.execute("""
        SELECT started_at, concept_id, conclusion FROM raw_workflow_runs
        WHERE student_id=%s AND concept_id IS NOT NULL AND concept_id <> 'unclassified'
    """, (student_id,))
    ci_rows = cur.fetchall()

    events = [
        (ts, concept_id, conclusion == "success", _item_difficulty(cur, concept_id))
        for ts, concept_id, conclusion in ci_rows
    ]

    for result in Memory().test_result_history(student_id):
        if result["passed"] is None:
            continue
        difficulty = (result["item_difficulty"] if result["item_difficulty"] is not None
                      else NEUTRAL_DIFFICULTY)
        for concept_id in result["concept_ids"]:
            events.append((result["ts"], concept_id, result["passed"], difficulty))

    events.sort(key=lambda e: e[0])

    est = MasteryEstimator()
    for _, concept_id, correct, difficulty in events:
        est.update(concept_id, correct=correct, item_difficulty=difficulty)
    return est


def _effort(cur, student_id):
    """V3 — inter-commit gaps, plus release-to-first-commit as a tracked (unscored) lag."""
    cur.execute("""
        SELECT committed_at FROM raw_commits
        WHERE student_id=%s ORDER BY committed_at
    """, (student_id,))
    commits = [r[0] for r in cur.fetchall()]
    gaps = [(commits[i] - commits[i - 1]).total_seconds() / 3600
            for i in range(1, len(commits))]

    cur.execute("""
        SELECT EXTRACT(EPOCH FROM (min(c.committed_at) - min(a.released_at)))/3600
        FROM raw_commits c JOIN assignments a USING (assignment_id)
        WHERE c.student_id=%s
    """, (student_id,))
    lag = cur.fetchone()[0]
    return effort_regulation(gaps, release_to_first_commit_h=float(lag or 0.0))


def _discipline(cur, student_id):
    """V2 — cleanliness needs lint counts over changed LOC; testing needs CI wiring.

    Reconciliation 2: M1 never checks out the student's code, so ruff/sqlfluff cannot
    run and lint_violations is genuinely unmeasured. changed_loc=0 makes cleanliness()
    return None by the document's own guard, which is the correct representation of
    "not measured" -- distinct from "measured, zero". Wire this to the Code Agent's
    deterministic tools in M4.

    tests_state IS measurable now: a repo with workflow runs has CI wired.
    """
    cur.execute("SELECT count(*) FROM raw_workflow_runs WHERE student_id=%s", (student_id,))
    tests_state = "wired" if cur.fetchone()[0] > 0 else "absent"

    # cohort_alpha stays None: Cronbach's alpha needs >=10 students (habits.py), so the
    # composite gate cannot open for a cohort of one. Components are reported instead.
    return engineering_discipline(lint_violations=0, changed_loc=0,
                                  tests_state=tests_state, cohort_alpha=None).to_dict()


def _pace(cur, student_id):
    """V4 — per assignment, censoring-aware.

    cohort_median_h is the median time-to-pass over PASSERS on the assignment. With one
    student that median is the student's own time, so ratio=1.0 and score=0.5 by
    definition. Labelled `cohort_n` in the output so a reader can see the score is
    structural rather than measured.
    """
    cur.execute("""
        SELECT a.assignment_id, a.released_at,
               min(r.completed_at) FILTER (WHERE r.conclusion='success') AS first_pass,
               max(r.completed_at) AS last_run
        FROM assignments a
        JOIN raw_workflow_runs r ON r.assignment_id=a.assignment_id AND r.student_id=%s
        GROUP BY a.assignment_id, a.released_at
    """, (student_id,))

    out = {}
    for assignment_id, released_at, first_pass, last_run in cur.fetchall():
        # Cohort median over passers on this assignment.
        cur.execute("""
            SELECT EXTRACT(EPOCH FROM (min(r.completed_at) - a.released_at))/3600 AS h
            FROM raw_workflow_runs r JOIN assignments a USING (assignment_id)
            WHERE r.assignment_id=%s AND r.conclusion='success'
            GROUP BY r.student_id, a.released_at
        """, (assignment_id,))
        passer_hours = [float(r[0]) for r in cur.fetchall() if r[0] is not None]
        cohort_median_h = median(passer_hours) if passer_hours else None

        if cohort_median_h is None or cohort_median_h <= 0:
            out[assignment_id] = {"score": None, "cohort_n": len(passer_hours),
                                  "note": "no cohort passers yet; pace undefined"}
            continue

        if first_pass:
            ttp = (first_pass - released_at).total_seconds() / 3600
            result = learning_pace(ttp, cohort_median_h, censored=False)
        else:
            elapsed = (last_run - released_at).total_seconds() / 3600
            result = learning_pace(None, cohort_median_h, elapsed_h=elapsed, censored=True)
        out[assignment_id] = result | {"cohort_n": len(passer_hours)}
    return out


def _error_stats(cur, student_id, est):
    """V5 and V6 — both read the sequential run history, so they share one pass.

    Merges the same two sources `_mastery` does (real CI telemetry +
    `memory.Memory.test_result_history`, invariant 2), but keeps TWO views rather than
    one flattened list, deliberately:

      `runs`           one entry per real OBSERVATION -- a single CI run or a single
                       hidden-test result, however many concepts its gap tags. Feeds
                       total_runs/failures/time-to-fix, which must count what actually
                       happened, not inflate because one observation happened to be
                       evidence for two concepts.
      `concept_events` the SAME evidence, fanned out per concept it is evidence for --
                       feeds by_concept and opportunities only, mirroring memory.py's
                       own `_replay_concept` semantics (one trace, several concepts,
                       real evidence for each).

    Flattening both into one list, as an earlier draft of this function did, would have
    double-counted every multi-concept test_result observation in total_runs/errors --
    a real distortion of V6's aggregate rate, caught before it shipped, not after.
    """
    cur.execute("""
        SELECT completed_at, conclusion, concept_id, error_class
        FROM raw_workflow_runs
        WHERE student_id=%s AND completed_at IS NOT NULL
    """, (student_id,))
    ci_rows = list(cur.fetchall())

    test_results = [r for r in Memory().test_result_history(student_id)
                    if r["passed"] is not None]

    runs = [(ts, conclusion) for ts, conclusion, _, _ in ci_rows]
    runs += [(r["ts"], "success" if r["passed"] else "failure") for r in test_results]
    runs.sort(key=lambda r: r[0])

    concept_events = [(ts, conclusion, concept_id)
                      for ts, conclusion, concept_id, _ in ci_rows if concept_id]
    for r in test_results:
        conclusion = "success" if r["passed"] else "failure"
        concept_events += [(r["ts"], conclusion, c) for c in r["concept_ids"]]
    concept_events.sort(key=lambda e: e[0])

    total_runs = len(runs)
    failures = [r for r in runs if r[1] == "failure"]

    # Time-to-fix: hours from each failure to the next passing run (concept-agnostic --
    # "did something pass after this failure", the original semantics, unchanged).
    ttfs, resolved = [], 0
    for ts, _ in failures:
        nxt = next((r[0] for r in runs if r[1] == "success" and r[0] > ts), None)
        if nxt:
            resolved += 1
            ttfs.append((nxt - ts).total_seconds() / 3600)
    median_ttf_h = median(ttfs) if ttfs else 0.0

    by_concept = {}
    for _, conclusion, concept_id in concept_events:
        if conclusion == "failure":
            by_concept[concept_id] = by_concept.get(concept_id, 0) + 1

    # Wheel-spinning inputs are per the worst concept: the one with most opportunities.
    snapshot = est.snapshot()
    worst = max(by_concept, key=by_concept.get) if by_concept else None
    worst_state = snapshot.get(worst, {}) if worst else {}
    opportunities = sum(1 for _, _, c in concept_events if c == worst) if worst else 0
    slope = _mastery_slope(est, worst)

    v5 = error_response(
        median_ttf_h=median_ttf_h,
        resolved_errors=resolved,
        total_errors=len(failures),
        concept_opportunities=opportunities,
        current_mastery=worst_state.get("p_mastery", 1.0),
        mastery_slope=slope,
    )

    cur.execute("""
        SELECT coalesce(sum(additions + deletions), 0) FROM raw_commits
        WHERE student_id=%s
    """, (student_id,))
    changed_loc = int(cur.fetchone()[0] or 0)

    v6 = error_frequency(
        failed_runs=len(failures), total_runs=total_runs,
        errors=len(failures), changed_loc=changed_loc,
        by_concept=by_concept,
        weekly_slope=0.0,   # needs >=2 weeks of history; flat until then
    )
    return v5, v6


def _mastery_slope(est, concept):
    """Slope over the estimator's retained history window (mastery.py keeps 6)."""
    if not concept or concept not in est.states:
        return 0.0
    h = est.states[concept].history
    return (h[-1] - h[0]) if len(h) >= 2 else 0.0


def compute_for_student(cur, student_id):
    """Pull this student's raw rows, run the Module-1 variable functions, assemble one
    learner_features payload."""
    est = _mastery(cur, student_id)
    v5, v6 = _error_stats(cur, student_id, est)
    return {
        "mastery": est.snapshot(),
        "engineering_discipline": _discipline(cur, student_id),
        "effort_regulation": _effort(cur, student_id),
        "pace": _pace(cur, student_id),
        "error_response": v5,
        "error_frequency": v6,
        "help_seeking": None,   # V7 seam: needs the coach (Module 7)
    }


def run(last_run_iso="1970-01-01T00:00:00Z"):
    """Compute features for every dirty student. Returns the number written."""
    with db.cursor() as cur:
        students = dirty_students(cur, last_run_iso)
        print(f"{len(students)} student(s) with activity since {last_run_iso}")

        for sid in students:
            payload = compute_for_student(cur, sid)
            cur.execute("""
                INSERT INTO learner_features
                  (student_id, computed_at, window_days, mastery, engineering_discipline,
                   effort_regulation, pace, error_response, error_frequency, help_seeking)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (student_id, computed_at) DO UPDATE SET
                  window_days            = EXCLUDED.window_days,
                  mastery                = EXCLUDED.mastery,
                  engineering_discipline = EXCLUDED.engineering_discipline,
                  effort_regulation      = EXCLUDED.effort_regulation,
                  pace                   = EXCLUDED.pace,
                  error_response         = EXCLUDED.error_response,
                  error_frequency        = EXCLUDED.error_frequency,
                  help_seeking           = EXCLUDED.help_seeking
            """, (sid, watermark(cur, sid), WINDOW_DAYS,
                  Json(payload["mastery"]),
                  Json(payload["engineering_discipline"]),
                  Json(payload["effort_regulation"]),
                  Json(payload["pace"]),
                  Json(payload["error_response"]),
                  Json(payload["error_frequency"]),
                  Json(payload["help_seeking"]) if payload["help_seeking"] else None))
            print(f"  {sid}: {len(payload['mastery'])} concept(s) in mastery")
        return len(students)


if __name__ == "__main__":
    run()
