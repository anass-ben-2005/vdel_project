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
import contextlib
import os
from statistics import median

from psycopg2.extras import Json

from assessment.test_runner import TestOutcome, gap_observation
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

# D-063. formula_ver is what a learner_features row was computed with. v2 = every run in
# raw_workflow_runs counts. v3 = two kinds of run are filtered out, for two different
# reasons that are kept SEPARATE on purpose:
#
#   (a) TOOLING failures -- a run that failed because the repo's CI could not run (the old
#       template never installed ruff, D-060), not because of anything the student did.
#       Excluded from the OUTCOME features only (V1, V5, V6). They stay in V2 and V4: the
#       student really did push, and that is real activity.
#   (b) SYNC-TRIGGERED runs -- a run whose head commit is a `scripts/sync_template.py`
#       commit. It re-evaluates code the student had already pushed, so it is not a
#       student action at all. Excluded from EVERYTHING that reads raw_workflow_runs.
#       The failure such a run reports can be perfectly real (a SyntaxError that was
#       already in the repo); it is excluded because it is not a NEW student action.
#       The sync COMMIT itself is excluded for the same reason (_commit_scope): from V3's
#       commit gaps, V6's changed_loc, and the commit side of the watermark and the
#       active-student list. Rule (a) never applies to commits.
#
# (a) is an explicit list, because those runs' logs are gone and nothing in the row says
# why they failed. (b) is a rule: head_sha joined to raw_commits.message. A run with no
# head_sha (collected before D-063, not yet backfilled) or whose commit is not in
# raw_commits is treated as a student run -- it fails OPEN, never excludes by guess.
#
# D-069 (v4). Two more changes, both for FUTURE rows only (v2/v3 rows stay readable):
#   (c) the INITIAL TEMPLATE COMMIT ("Initial commit: ..." with no assignment, written by
#       scripts/publish_repo.py) and the CI run on it are not student actions either. They are
#       treated exactly like a sync commit / sync-triggered run (rule b), same fail-open test.
#   (d) V1 is no longer computed here: it is `Memory.replay_mastery`, the same trace replay
#       the profile uses (one implementation, D-068 option a). Raw CI runs feed NO
#       concept-level mastery any more; they still feed V5 and V6.
#
# D-079 (v5). The scoping rules are v4's; what changed is what V1 replays: one
# `mastery_observation` per (attempt, GAP) instead of one `test_result` per test (see
# memory.MASTERY_TRACE_KINDS). Because V1 is `Memory.replay_mastery`, a "v4" computation made
# today already uses the new observations: the old per-test V1 is not reproducible from the log
# any more (v2/v3 still are, they read test_result_history). Stored v4 rows are left as they are.
#
# D-084 (v6). The scoping and V1 are v5's; V5/V6 additionally leave out the outcomes of an
# unattempted stub gap (`UNATTEMPTED_EXCLUDED_FROM` below). Stored v2..v5 rows are not touched
# and those versions stay computable.

# D-088 (v7). V2's cleanliness is measured: the gap-scoped ruff / sqlfluff counts stored on
# `attempts` (sql/08) replace the fixed `lint_violations = 0, changed_loc = 0` of v2..v6, so a
# student with measured attempts gets a cleanliness score. Versions up to v6 keep the old
# zeros, so their stored rows stay reproducible; the v6 row a student may already have would be
# recomputed differently, which is why this is a new version.
LINT_MEASURED_FROM = "v7"

# D-098 (v8). The template push of a DELIVERED repo (attempt >= 2, one assignment: D-090) is not a
# student action. v4's rule (c) only saw it when it touched no assignment (`assignment_id IS NULL`),
# which holds for the four-assignment attempt-1 repo but not for a one-assignment repo, where the
# collector gives every commit that assignment. From v8 on, "Initial commit:" also matches when the
# commit is the earliest commit graded under its (attempt >= 2) attempt, i.e. the first of its repo.
# `raw_commits` has no repo column, so the repo is read through `test_results.attempt_id`; a commit
# that was never graded, or whose order cannot be established, stays a student commit (fail open).
# Versions up to v7 keep the old rule, so their stored rows stay reproducible and are not touched.
INITIAL_COMMIT_BY_ATTEMPT_FROM = "v8"
FORMULA_VER = "v8"

# D-084. From this formula version on, V5/V6 leave out a hidden-test outcome of a gap that was
# an unattempted NotImplementedError stub in that commit (`gap_observation`, the D-079
# definition). Versions up to v5 count it as a failure, exactly as their stored rows did, so
# they stay reproducible. FORMULA_VER became "v6" for exactly this reason: the v5 rows already
# stored would be recomputed differently.
UNATTEMPTED_EXCLUDED_FROM = "v6"
SYNC_COMMIT_PREFIX = "ci: sync template"
INITIAL_COMMIT_PREFIX = "Initial commit:"
TOOLING_FAILURE_RUNS = {
    32752484942: "old CI template, ruff never installed (D-060); failed before pytest",
    32798574508: "old CI template, ruff never installed (D-060); failed before pytest",
    32798808645: "old CI template, ruff never installed (D-060); failed before pytest",
    32799183586: "old CI template, ruff never installed (D-060); failed before pytest",
}


# A template-sync commit is recognised by THREE stored facts together, not the message alone:
#   - the message starts with SYNC_COMMIT_PREFIX;
#   - assignment_id IS NULL -- the collector sets it when a commit touches no assignment
#     file, and a sync commit only ever touches template files;
#   - files_changed <= SYNC_MAX_FILES -- scripts/sync_template.py manages len(TEMPLATE_FILES)
#     files, so a bigger commit is not one.
# A NULL files_changed or message is unknown, and unknown means "not a sync commit"
# (fail-open). KNOWN HOLE (D-063): a legacy single-assignment repo gives EVERY commit an
# assignment_id (D-043), so a sync commit pushed there is not recognised -- the safe
# direction. UPGRADE TRIGGER: store the commit's file list, or a "touches only
# TEMPLATE_FILES" flag, at collection time and test that instead.
SYNC_MAX_FILES = 2    # == len(scripts.render_student_repo.TEMPLATE_FILES), asserted by a test


def sync_commit_sql(alias="c"):
    """SQL condition: `alias` (a raw_commits row) is a template-sync commit.

    One definition, used by the run join (rule b on runs), the commit filter (rule b on
    commits) and scripts/backfill_head_sha.py's report, so they cannot disagree."""
    assert "'" not in SYNC_COMMIT_PREFIX
    return (f"(COALESCE(starts_with({alias}.message, '{SYNC_COMMIT_PREFIX}'), false) "
            f"AND {alias}.assignment_id IS NULL "
            f"AND COALESCE({alias}.files_changed <= {SYNC_MAX_FILES}, false))")


def _first_commit_of_delivered_repo_sql(alias):
    """SQL condition (D-098): `alias` is the earliest commit graded under an attempt >= 2.

    A delivered repo (D-090) holds one assignment and belongs to exactly one `attempts` row, so
    that row stands for the repo. "Earliest" is by `committed_at`, ties by sha. Fail open: a
    commit with no graded result (unknown repo) never matches, and neither does one that has an
    earlier graded commit in the same attempt."""
    return (
        f"EXISTS (SELECT 1 FROM test_results t0"
        f" JOIN attempts att0 ON att0.attempt_id = t0.attempt_id"
        f" WHERE t0.commit_sha = {alias}.sha AND att0.attempt_no >= 2"
        f" AND NOT EXISTS (SELECT 1 FROM test_results t1"
        f" JOIN raw_commits c1 ON c1.sha = t1.commit_sha"
        f" WHERE t1.attempt_id = t0.attempt_id AND t1.commit_sha <> {alias}.sha"
        f" AND (c1.committed_at < {alias}.committed_at"
        f" OR (c1.committed_at = {alias}.committed_at AND c1.sha < {alias}.sha))))")


def _initial_commit_by_attempt(formula_ver):
    """True for formula versions that also recognise the template push of a delivered repo."""
    return formula_ver not in ("v2", "v3", "v4", "v5", "v6", "v7")


def initial_commit_sql(alias="c", formula_ver=FORMULA_VER):
    """SQL condition: `alias` (a raw_commits row) is the initial template commit (D-069, D-098).

    Same shape as `sync_commit_sql` and the same fail-open stance: a NULL message means "not
    the initial commit", so an unknown value KEEPS the row. Up to v7 the commit must also carry
    no assignment (`assignment_id IS NULL`). From v8 it may instead be the first commit of its
    delivered repo (`_first_commit_of_delivered_repo_sql`): a one-assignment repo gives its
    template push that assignment (D-043), so the NULL test alone never saw it."""
    assert "'" not in INITIAL_COMMIT_PREFIX
    prefix = f"COALESCE(starts_with({alias}.message, '{INITIAL_COMMIT_PREFIX}'), false)"
    if not _initial_commit_by_attempt(formula_ver):
        return f"({prefix} AND {alias}.assignment_id IS NULL)"
    return (f"({prefix} AND ({alias}.assignment_id IS NULL "
            f"OR {_first_commit_of_delivered_repo_sql(alias)}))")


def template_commit_sql(alias="c"):
    """SQL condition: `alias` is the template push that no feedback is ever built for (D-098).
    Always the current definition: feedback has no formula version."""
    return initial_commit_sql(alias, INITIAL_COMMIT_BY_ATTEMPT_FROM)


def _not_student_commit_sql(formula_ver, alias):
    """SQL: `alias` is a commit that is NOT a student action under `formula_ver`
    (v3: a sync commit; v4: a sync commit or the initial template commit; v8: also the template
    push of a delivered repo)."""
    if formula_ver == "v3":
        return sync_commit_sql(alias)
    return f"({sync_commit_sql(alias)} OR {initial_commit_sql(alias, formula_ver)})"


def _run_scopes(formula_ver, alias="r"):
    """(activity, outcome): SQL conditions on `alias`, a raw_workflow_runs row.

    `activity` drops rule (b) only; `outcome` drops (a) and (b). v2 drops nothing, so a v2
    computation is exactly the pre-D-063 behaviour and the two versions can be compared.
    """
    if formula_ver == "v2":
        return "TRUE", "TRUE"
    sync = (f"NOT EXISTS (SELECT 1 FROM raw_commits sc WHERE sc.sha = {alias}.head_sha "
            f"AND {_not_student_commit_sql(formula_ver, 'sc')})")
    ids = ",".join(str(int(i)) for i in TOOLING_FAILURE_RUNS)
    tooling = f"{alias}.run_id <> ALL(ARRAY[{ids}]::bigint[])"
    return sync, f"({sync} AND {tooling})"


def _commit_scope(formula_ver, alias="c"):
    """SQL condition on `alias`, a raw_commits row: rule (b) applied to COMMITS.

    A template-sync commit is not a student action either, so under v3 it is out of V3's
    commit gaps, V6's changed_loc, and the commit side of the watermark / active list.
    Rule (a) (tooling failures) is about runs and has no meaning here. What counts as a sync
    commit is `sync_commit_sql` (message prefix AND no assignment AND few files). Fail-open:
    every term is a definite true/false (COALESCEd), so an unknown value KEEPS the commit
    rather than letting a NULL silently drop the row from a WHERE."""
    if formula_ver == "v2":
        return "TRUE"
    return f"NOT {_not_student_commit_sql(formula_ver, alias)}"


def dirty_students(cur, last_run_iso, formula_ver=FORMULA_VER):
    """Flaw 5: who actually did something since the last feature run?

    A sync-triggered run or commit is not something the student did (D-063 rule b)."""
    activity, _ = _run_scopes(formula_ver)
    commit_ok = _commit_scope(formula_ver)
    cur.execute(f"""
        SELECT DISTINCT c.student_id FROM raw_commits c
        WHERE c.committed_at > %s AND {commit_ok}
        UNION
        SELECT DISTINCT r.student_id FROM raw_workflow_runs r
        WHERE r.started_at > %s AND {activity}
    """, (last_run_iso, last_run_iso))
    return [r[0] for r in cur.fetchall()]


def watermark(cur, student_id, formula_ver=FORMULA_VER):
    """The student's most recent raw event.

    Reconciliation 1: used as computed_at so that re-running with no new activity
    targets the same primary key and rewrites identical values. Ties the feature row to
    the exact data that produced it, which is also what makes the row reproducible.
    """
    activity, _ = _run_scopes(formula_ver)
    commit_ok = _commit_scope(formula_ver)
    cur.execute(f"""
        SELECT max(ts) FROM (
            SELECT max(c.committed_at) AS ts FROM raw_commits c
            WHERE c.student_id=%s AND {commit_ok}
            UNION ALL
            SELECT max(r.started_at) AS ts FROM raw_workflow_runs r
            WHERE r.student_id=%s AND {activity}
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


def _mastery(cur, student_id, formula_ver=FORMULA_VER):
    """V1 — returns the MasteryEstimator (callers take `.snapshot()`) for v2/v3.

    D-069 (v4): there is no second implementation any more. See `_mastery_v4`, which is a
    thin call into `Memory.replay_mastery`; this function is kept, unchanged, for v2/v3 so
    old formula versions stay computable and comparable.

    V1 under v2/v3 — replay classified pass/fails through BKT.

    D-063: under v3, tooling failures (a) and sync-triggered runs (b) are not evidence.

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
    (`_log_test_result_traces`'s own filter), so every test_result trace that exists already
    carries a real, resolved concept.

    A trace tagged with SEVERAL concept_ids contributes to EACH of them -- the same
    containment semantics `memory.py::_replay_concept`'s `concept_ids @> ARRAY[concept]`
    already gives every other MASTERY_TRACE_KINDS member; one gap can exercise two
    concepts, and the same pass/fail is real evidence about both.
    """
    _, outcome = _run_scopes(formula_ver)
    cur.execute(f"""
        SELECT r.started_at, r.concept_id, r.conclusion FROM raw_workflow_runs r
        WHERE r.student_id=%s AND r.concept_id IS NOT NULL
          AND r.concept_id <> 'unclassified' AND {outcome}
    """, (student_id,))
    ci_rows = cur.fetchall()

    events = [
        (ts, concept_id, conclusion == "success", _item_difficulty(cur, concept_id))
        for ts, concept_id, conclusion in ci_rows
    ]

    for result in Memory().test_result_history(student_id, conn=cur.connection):
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


def _mastery_v4(cur, student_id):
    """V1 for formula v4 (D-069): `(stored-shape vector, estimator)` straight from
    `Memory.replay_mastery`, the same trace replay that builds `learner_profile.mastery`.

    So `learner_features.mastery` and `learner_profile.mastery` carry the SAME numbers for
    the same traces, by construction (D-068 option a). The shape is the profile's
    (p_mastery, p_correct_next, n, confidence, ci90, trend, param_set), not the older
    `snapshot()` shape. Raw CI runs are not read here: a repo-wide CI conclusion cannot be
    attributed to one concept (the student2 clean-room test: a red run caused by untouched
    stubs was charged to py.testing). They still feed V5/V6 in `_error_stats`."""
    return Memory().replay_mastery(student_id, conn=cur.connection)


def _effort(cur, student_id, formula_ver=FORMULA_VER):
    """V3 — inter-commit gaps, plus release-to-first-commit as a tracked (unscored) lag.

    D-063: under v3 a template-sync commit is not a student commit, so it makes no gap."""
    commit_ok = _commit_scope(formula_ver)
    cur.execute(f"""
        SELECT c.committed_at FROM raw_commits c
        WHERE c.student_id=%s AND {commit_ok} ORDER BY c.committed_at
    """, (student_id,))
    commits = [r[0] for r in cur.fetchall()]
    gaps = [(commits[i] - commits[i - 1]).total_seconds() / 3600
            for i in range(1, len(commits))]

    cur.execute(f"""
        SELECT EXTRACT(EPOCH FROM (min(c.committed_at) - min(a.released_at)))/3600
        FROM raw_commits c JOIN assignments a USING (assignment_id)
        WHERE c.student_id=%s AND {commit_ok}
    """, (student_id,))
    lag = cur.fetchone()[0]
    return effort_regulation(gaps, release_to_first_commit_h=float(lag or 0.0))


def _measures_lint(formula_ver):
    """True for formula versions whose V2 reads the stored lint counts (D-088)."""
    return formula_ver not in ("v2", "v3", "v4", "v5", "v6")


def _lint_totals(cur, student_id):
    """(violations, changed_loc, attempts_measured) summed over this student's attempts that
    HAVE a measurement; (0, 0, 0) when none has or the columns are not migrated yet (fail-open:
    the real database gets sql/08 by hand, and until then V2 must keep working)."""
    cur.execute("SAVEPOINT lint_totals")
    try:
        cur.execute(
            "SELECT coalesce(sum(lint_violations), 0), coalesce(sum(lint_changed_loc), 0),"
            " count(*) FROM attempts WHERE student_id = %s AND lint_changed_loc IS NOT NULL",
            (student_id,))
        v, loc, n = cur.fetchone()
        cur.execute("RELEASE SAVEPOINT lint_totals")
        return int(v), int(loc), int(n)
    except Exception:  # noqa: BLE001 -- e.g. the columns do not exist yet
        cur.execute("ROLLBACK TO SAVEPOINT lint_totals")
        return 0, 0, 0


def _discipline(cur, student_id, formula_ver=FORMULA_VER):
    """V2 — cleanliness needs lint counts over changed LOC; testing needs CI wiring.

    D-088 (v7): the counts are real -- gap-scoped ruff / sqlfluff findings and the lines the
    student changed inside the gaps, stored on `attempts` at grading time. Up to v6 they are
    the fixed zeros described below.

    Reconciliation 2: M1 never checks out the student's code, so ruff/sqlfluff cannot
    run and lint_violations is genuinely unmeasured. changed_loc=0 makes cleanliness()
    return None by the document's own guard, which is the correct representation of
    "not measured" -- distinct from "measured, zero". Wire this to the Code Agent's
    deterministic tools in M4.

    tests_state IS measurable now: a repo with workflow runs has CI wired.
    """
    # D-063: a sync-triggered run does not show the STUDENT wired CI (rule b). A tooling
    # failure still does -- the student pushed, and CI ran (rule a does not apply here).
    activity, _ = _run_scopes(formula_ver)
    cur.execute(f"SELECT count(*) FROM raw_workflow_runs r WHERE r.student_id=%s AND {activity}",
                (student_id,))
    tests_state = "wired" if cur.fetchone()[0] > 0 else "absent"

    # cohort_alpha stays None: Cronbach's alpha needs >=10 students (habits.py), so the
    # composite gate cannot open for a cohort of one. Components are reported instead.
    if not _measures_lint(formula_ver):
        return engineering_discipline(lint_violations=0, changed_loc=0,
                                      tests_state=tests_state, cohort_alpha=None).to_dict()
    violations, changed, measured = _lint_totals(cur, student_id)
    result = engineering_discipline(lint_violations=violations, changed_loc=changed,
                                    tests_state=tests_state, cohort_alpha=None).to_dict()
    # the evidence behind the number, so a reader of the row can audit it
    return result | {"lint": {"violations": violations, "changed_loc": changed,
                              "attempts_measured": measured}}


def _pace(cur, student_id, formula_ver=FORMULA_VER):
    """V4 — per assignment, censoring-aware.

    D-063: sync-triggered runs (b) are excluded in both queries below; tooling failures
    (a) are NOT -- the student really pushed, so they still count as activity.

    cohort_median_h is the median time-to-pass over PASSERS on the assignment. With one
    student that median is the student's own time, so ratio=1.0 and score=0.5 by
    definition. Labelled `cohort_n` in the output so a reader can see the score is
    structural rather than measured.
    """
    activity, _ = _run_scopes(formula_ver)
    cur.execute(f"""
        SELECT a.assignment_id, a.released_at,
               min(r.completed_at) FILTER (WHERE r.conclusion='success') AS first_pass,
               max(r.completed_at) AS last_run
        FROM assignments a
        JOIN raw_workflow_runs r ON r.assignment_id=a.assignment_id AND r.student_id=%s
                                AND {activity}
        GROUP BY a.assignment_id, a.released_at
    """, (student_id,))

    out = {}
    for assignment_id, released_at, first_pass, last_run in cur.fetchall():
        # Cohort median over passers on this assignment.
        cur.execute(f"""
            SELECT EXTRACT(EPOCH FROM (min(r.completed_at) - a.released_at))/3600 AS h
            FROM raw_workflow_runs r JOIN assignments a USING (assignment_id)
            WHERE r.assignment_id=%s AND r.conclusion='success' AND {activity}
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


def _excludes_unattempted(formula_ver):
    """True for formula versions that leave unattempted stubs out of V5/V6 (D-084)."""
    return formula_ver not in ("v2", "v3", "v4", "v5")


def _drop_unattempted(cur, results):
    """`results` (test_result_history entries) without those of an unattempted gap (D-084).

    A trace written from D-084 on says so itself (`attempted`). An older trace that still
    names its (attempt, commit, gap) is resolved from that commit's stored `test_results`
    with the same `gap_observation`; a trace that names nothing (written before D-079)
    cannot be resolved and is KEPT -- the safe direction, it is never dropped by guess."""
    cache: dict[tuple, bool] = {}
    kept = []
    for r in results:
        if r["attempted"] is False:
            continue
        if r["attempted"] is None and None not in (r["attempt_id"], r["commit_sha"], r["gap_id"]):
            key = (r["attempt_id"], r["commit_sha"], r["gap_id"])
            if key not in cache:
                cur.execute(
                    "SELECT test_name, passed, message, status FROM test_results"
                    " WHERE attempt_id = %s AND commit_sha = %s AND gap_id = %s", key)
                rows = [TestOutcome(n, p, m, r["gap_id"], st) for n, p, m, st in cur.fetchall()]
                cache[key] = bool(rows) and gap_observation(rows) is None
            if cache[key]:
                continue
        kept.append(r)
    return kept


def _drop_template_commit_results(cur, results):
    """`results` (test_result_history entries) without those graded on a template push (D-098).

    The push is not a student action, so its outcomes are no evidence about the student, exactly
    as its CI run is left out by `_run_scopes`. An entry with no `commit_sha` (older traces) is
    kept: it cannot be placed, and an unknown value is never dropped by guess."""
    shas = sorted({r["commit_sha"] for r in results if r["commit_sha"]})
    if not shas:
        return results
    cur.execute(f"SELECT c.sha FROM raw_commits c WHERE c.sha = ANY(%s) AND "
                f"{template_commit_sql('c')}", (shas,))
    template = {row[0] for row in cur.fetchall()}
    return [r for r in results if r["commit_sha"] not in template]


def _error_stats(cur, student_id, est, formula_ver=FORMULA_VER):
    """V5 and V6 — both read the sequential run history, so they share one pass.

    D-063: under v3 tooling failures (a) and sync-triggered runs (b) are not outcomes of
    anything the student did, so neither enters the run history below.

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
    _, outcome = _run_scopes(formula_ver)
    cur.execute(f"""
        SELECT r.completed_at, r.conclusion, r.concept_id, r.error_class
        FROM raw_workflow_runs r
        WHERE r.student_id=%s AND r.completed_at IS NOT NULL AND {outcome}
    """, (student_id,))
    ci_rows = list(cur.fetchall())

    test_results = [r for r in Memory().test_result_history(student_id, conn=cur.connection)
                    if r["passed"] is not None]
    if _excludes_unattempted(formula_ver):
        test_results = _drop_unattempted(cur, test_results)
    if _initial_commit_by_attempt(formula_ver):
        test_results = _drop_template_commit_results(cur, test_results)

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

    commit_ok = _commit_scope(formula_ver)       # D-063: sync commits add no student LOC
    cur.execute(f"""
        SELECT coalesce(sum(c.additions + c.deletions), 0) FROM raw_commits c
        WHERE c.student_id=%s AND {commit_ok}
    """, (student_id,))
    changed_loc = int(cur.fetchone()[0] or 0)

    v6 = error_frequency(
        failed_runs=len(failures), total_runs=total_runs,
        errors=len(failures), changed_loc=changed_loc,
        by_concept=by_concept,
        weekly_slope=0.0,   # needs >=2 weeks of history; flat until then
    )
    if formula_ver != "v2":
        # Auditability: a reader of the row can see how many runs were left out, and why.
        cur.execute(f"SELECT count(*) FROM raw_commits c WHERE c.student_id=%s "
                    f"AND NOT ({_commit_scope(formula_ver)})", (student_id,))
        excluded_commits = cur.fetchone()[0]     # before _excluded_counts reuses the cursor
        v6 = v6 | {"excluded_runs": _excluded_counts(cur, student_id, formula_ver),
                   "excluded_commits": excluded_commits}
    return v5, v6


def _excluded_counts(cur, student_id, formula_ver=FORMULA_VER):
    """How many of this student's runs v3/v4 leave out, per rule (kept separate, D-063)."""
    sync, _ = _run_scopes(formula_ver)
    cur.execute(f"""
        SELECT count(*) FILTER (WHERE r.run_id = ANY(%s)),
               count(*) FILTER (WHERE NOT ({sync}))
        FROM raw_workflow_runs r WHERE r.student_id=%s
    """, (list(TOOLING_FAILURE_RUNS), student_id))
    tooling, sync_triggered = cur.fetchone()
    return {"tooling": tooling, "sync_triggered": sync_triggered}


def _mastery_slope(est, concept):
    """Slope over the estimator's retained history window (mastery.py keeps 6)."""
    if not concept or concept not in est.states:
        return 0.0
    h = est.states[concept].history
    return (h[-1] - h[0]) if len(h) >= 2 else 0.0


def compute_for_student(cur, student_id, formula_ver=FORMULA_VER):
    """Pull this student's raw rows, run the Module-1 variable functions, assemble one
    learner_features payload.

    `formula_ver` selects which runs count (D-063): 'v2' = all of them (the behaviour
    before D-063, kept computable so v2 and v3 can be compared), 'v3' = the two exclusion
    rules, 'v4' (D-069) = v3 plus the initial-commit rule and the single-source V1, 'v5'
    (D-079) = v4 with V1 observed once per (attempt, gap). The variable formulas themselves
    are identical in all of them."""
    if formula_ver in ("v2", "v3"):
        est = _mastery(cur, student_id, formula_ver)
        mastery = est.snapshot()
    else:
        mastery, est = _mastery_v4(cur, student_id)
    v5, v6 = _error_stats(cur, student_id, est, formula_ver)
    return {
        "mastery": mastery,
        "engineering_discipline": _discipline(cur, student_id, formula_ver),
        "effort_regulation": _effort(cur, student_id, formula_ver),
        "pace": _pace(cur, student_id, formula_ver),
        "error_response": v5,
        "error_frequency": v6,
        "help_seeking": None,   # V7 seam: needs the coach (Module 7)
    }


def write_features(cur, student_id, payload, formula_ver=FORMULA_VER):
    """Insert one learner_features row; True if written, False if skipped.

    (student_id, computed_at) is the primary key and computed_at is the data watermark, so
    a v3 row computed at the watermark of an existing v2 row would collide with it. It must
    NOT overwrite it -- old v2 rows stay valid (D-063) -- so the update branch only fires
    for a row of the SAME formula_ver (that is the M1 "re-run changes nothing" case)."""
    cur.execute("""
        INSERT INTO learner_features
          (student_id, computed_at, window_days, mastery, engineering_discipline,
           effort_regulation, pace, error_response, error_frequency, help_seeking,
           formula_ver)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (student_id, computed_at) DO UPDATE SET
          window_days            = EXCLUDED.window_days,
          mastery                = EXCLUDED.mastery,
          engineering_discipline = EXCLUDED.engineering_discipline,
          effort_regulation      = EXCLUDED.effort_regulation,
          pace                   = EXCLUDED.pace,
          error_response         = EXCLUDED.error_response,
          error_frequency        = EXCLUDED.error_frequency,
          help_seeking           = EXCLUDED.help_seeking
        WHERE learner_features.formula_ver = EXCLUDED.formula_ver
    """, (student_id, watermark(cur, student_id, formula_ver), WINDOW_DAYS,
          Json(payload["mastery"]),
          Json(payload["engineering_discipline"]),
          Json(payload["effort_regulation"]),
          Json(payload["pace"]),
          Json(payload["error_response"]),
          Json(payload["error_frequency"]),
          Json(payload["help_seeking"]) if payload["help_seeking"] else None,
          formula_ver))
    return cur.rowcount == 1


def run(last_run_iso="1970-01-01T00:00:00Z", only=None, formula_ver=FORMULA_VER,
        conn=None):
    """Compute features for every dirty student. Returns the number of students seen.

    `only`: restrict to these student_ids. The default (everyone) is what the pipeline
    wants; tests pass their own student so a test run can never write a feature row for a
    REAL student in the shared dev database (D-063: one did, and broke the event-sourcing
    proof's features_ref check).

    Each row actually written is followed by `Memory.sync_features_ref` IN THE SAME
    TRANSACTION, so `learner_profile.features_ref` never lags the table it points into (the
    D-034 drift; the DAG's update_profiles task did this, but the CLI and any non-Airflow run
    did not). A student whose write was SKIPPED (a row of another formula_ver already sits at
    this watermark) is not synced -- nothing changed for them. Because the sync joins this
    transaction, a failure or a caller's rollback undoes the row and the pointer together.

    `conn` (D-071): join the caller's transaction instead of opening and committing one."""
    mem = Memory()
    with contextlib.ExitStack() as stack:
        if conn is None:                   # D-071: a caller (run_cycle, tests) may pass its own
            conn = stack.enter_context(db.connect())
        cur = stack.enter_context(conn.cursor())
        students = dirty_students(cur, last_run_iso, formula_ver)
        if only is not None:
            students = [s for s in students if s in set(only)]
        print(f"{len(students)} student(s) with activity since {last_run_iso}")

        for sid in students:
            payload = compute_for_student(cur, sid, formula_ver)
            if write_features(cur, sid, payload, formula_ver):
                mem.sync_features_ref(sid, conn=conn)
                print(f"  {sid}: {len(payload['mastery'])} concept(s) in mastery")
            else:
                print(f"  {sid}: SKIPPED -- a row of another formula_ver already exists "
                      f"at this watermark; {formula_ver} never overwrites it")
        return len(students)


if __name__ == "__main__":
    run()
