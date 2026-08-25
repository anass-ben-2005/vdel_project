"""assessment/diagnose.py -- VDEL_REDESIGN.md C10's deterministic diagnosis function.

C10: "'Analysis Agent' -> 'Feedback Agent' fed a pre-computed diagnosis... A
deterministic diagnosis function produces {weakest_concept, attempts_per_stage,
recurrence_flags, failing_tests}; the LLM receives that plus the code and writes only
the explanation... Four of its seven listed jobs are GROUP BY. Your own invariant:
never pay an LLM for what a free tool does perfectly."

Everything here reads data that already exists -- `test_results` (Stage B),
`attempts`, `gaps`, `raw_commits`, `assignments` -- confirmed against the live schema
(`\\d test_results` etc.) before writing a line, not assumed. No new table, no new
column, no LLM call anywhere in this file.

Scope: this is the diagnosis half of C10 only. The "Feedback Agent" that would
consume this output and write the explanation is M5/M6-era (CLAUDE.md's scope table:
M5 dropped, M6 needs >=2 agents to aggregate) and out of scope here -- this module
produces the auditable `{weakest_concept, attempts_per_stage, recurrence_flags,
failing_tests}` tuple and stops.

Natural key: `attempt_id`, not `(student_id, assignment_id)`. `test_results` FKs
directly to `attempts.attempt_id` (the real unique row), and `(student_id,
assignment_id)` alone is ambiguous across `attempt_no` -- `attempts` own UNIQUE
constraint is `(student_id, assignment_id, attempt_no)`, three columns, not two.
`student_id`/`assignment_id`/`project_id` are looked up from the attempt itself.

Takes a cursor, not a connection or a student_id/assignment_id pair with its own
`db.cursor()` -- matches `assessment/scope_check.py`'s and `test_runner.py::_session`'s
own testability discipline: the caller controls the transaction, so a test can pass a
cursor from a transaction it rolls back afterward and this function never has to know
the difference between a real request and a test.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

# A gap recurs once it has failed under this many DISTINCT commits -- 2 is the
# smallest number that means "more than once," not a tuned threshold. Named so a
# future change to it is a one-line, reviewable decision, not a buried literal.
RECURRENCE_MIN_COMMITS = 2


@dataclass(frozen=True)
class FailingTest:
    """One currently-failing test, from the most recent commit's `test_results` rows
    (or the most recent local run, if that is more recent than any push)."""

    test_name: str
    message: str | None
    gap_id: str | None


@dataclass(frozen=True)
class Diagnosis:
    """C10's `{weakest_concept, attempts_per_stage, recurrence_flags, failing_tests}`,
    named exactly as C10 names them.

    `attempts_per_stage`: {assignment_id: commit_count} for every assignment (stage,
    one per file) in this attempt's project -- real per-file attribution from
    `raw_commits.assignment_id` (D-043), not derived or invented. An assignment the
    student has never pushed to appears with count 0, not omitted, so a caller can
    tell "never touched" apart from "not part of this project."

    `recurrence_flags`: {gap_id: bool} -- True if that gap has a failing
    `test_results` row under 2+ DISTINCT commits (not just 2+ rows on the same
    commit, which would just be re-grading the same push), for every gap that has
    failed at least once. Computed over this attempt's FULL test_results history,
    not just the latest commit -- "recurrence" is meaningless looking at one snapshot.

    `failing_tests`: only the LATEST commit's snapshot (or the latest local run, if
    more recent) -- "currently failing," the complement of `recurrence_flags`, which
    deliberately looks at history instead.

    `weakest_concept`: the concept_id with the lowest pass rate across this attempt's
    FULL test_results history (more observations, same reasoning as BKT's own
    preference for more evidence), restricted to gaps with a real `concept_ids` entry
    (a `test_results.gap_id` that doesn't resolve to a row in `gaps` contributes
    nothing here, same as it contributes nothing to `memory.py`'s mastery wiring).
    `None` if there is no test_results evidence at all, or if every concept touched
    is already at a 100% pass rate -- "weakest concept" should mean a real weakness,
    not "the least perfect one when everything is perfect."
    """

    weakest_concept: str | None
    attempts_per_stage: dict[str, int]
    recurrence_flags: dict[str, bool]
    failing_tests: tuple[FailingTest, ...]


def diagnose(cur, attempt_id: int) -> Diagnosis:
    """The one function this module exists to provide. Deterministic, no LLM, no
    write -- three SELECTs and GROUP BY-shaped Python, exactly C10's own diagnosis
    ("four of its seven listed jobs are GROUP BY").
    """
    cur.execute(
        "SELECT student_id, assignment_id, project_id FROM attempts WHERE attempt_id = %s",
        (attempt_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no attempt with attempt_id={attempt_id!r}")
    student_id, assignment_id, project_id = row

    weakest_concept = _weakest_concept(cur, attempt_id)
    recurrence_flags = _recurrence_flags(cur, attempt_id)
    failing_tests = _failing_tests(cur, attempt_id)
    attempts_per_stage = _attempts_per_stage(cur, student_id, assignment_id, project_id)

    return Diagnosis(
        weakest_concept=weakest_concept,
        attempts_per_stage=attempts_per_stage,
        recurrence_flags=recurrence_flags,
        failing_tests=failing_tests,
    )


def _weakest_concept(cur, attempt_id: int) -> str | None:
    cur.execute(
        """SELECT tr.passed, g.concept_ids
           FROM test_results tr
           JOIN gaps g ON g.gap_id = tr.gap_id
           WHERE tr.attempt_id = %s""",
        (attempt_id,),
    )
    pass_count: Counter[str] = Counter()
    total_count: Counter[str] = Counter()
    for passed, concept_ids in cur.fetchall():
        for concept_id in concept_ids or ():
            total_count[concept_id] += 1
            if passed:
                pass_count[concept_id] += 1

    if not total_count:
        return None
    rates = {c: pass_count[c] / total_count[c] for c in total_count}
    weakest_rate = min(rates.values())
    if weakest_rate >= 1.0:
        return None
    # Deterministic tie-break: alphabetically first concept_id at the minimum rate --
    # a real tie is possible (two concepts both at 0%) and must not depend on
    # dict/query row order, which Postgres does not guarantee absent an ORDER BY.
    return min(c for c, r in rates.items() if r == weakest_rate)


def _recurrence_flags(cur, attempt_id: int) -> dict[str, bool]:
    cur.execute(
        """SELECT gap_id, commit_sha, passed
           FROM test_results
           WHERE attempt_id = %s AND gap_id IS NOT NULL""",
        (attempt_id,),
    )
    failed_commits: dict[str, set] = defaultdict(set)
    for gap_id, commit_sha, passed in cur.fetchall():
        if not passed:
            failed_commits[gap_id].add(commit_sha)   # None is a valid set member (local run)
    return {gap_id: len(commits) >= RECURRENCE_MIN_COMMITS
            for gap_id, commits in failed_commits.items()}


def _failing_tests(cur, attempt_id: int) -> tuple[FailingTest, ...]:
    cur.execute(
        """SELECT test_name, passed, message, gap_id, commit_sha
           FROM test_results
           WHERE attempt_id = %s
           ORDER BY ran_at DESC""",
        (attempt_id,),
    )
    rows = cur.fetchall()
    if not rows:
        return ()
    # The most recently-run test's commit_sha is "the current state" -- may be NULL
    # (a local run more recent than any push), handled the same way either way.
    latest_commit_sha = rows[0][4]
    return tuple(
        FailingTest(test_name=test_name, message=message, gap_id=gap_id)
        for test_name, passed, message, gap_id, commit_sha in rows
        if commit_sha == latest_commit_sha and not passed
    )


def _attempts_per_stage(cur, student_id: str, assignment_id: str,
                         project_id: str | None) -> dict[str, int]:
    # project_id is nullable (sql/01: legacy pre-D-035 assignments have none) -- an
    # attempt on one of those has no sibling assignments to group across, so it falls
    # back to just its own one assignment rather than matching every other
    # project_id-less assignment via a NULL = NULL comparison that SQL would never
    # make true anyway.
    if project_id is not None:
        cur.execute(
            """SELECT a.assignment_id, count(rc.sha)
               FROM assignments a
               LEFT JOIN raw_commits rc
                 ON rc.assignment_id = a.assignment_id AND rc.student_id = %s
               WHERE a.project_id = %s
               GROUP BY a.assignment_id""",
            (student_id, project_id),
        )
    else:
        cur.execute(
            """SELECT a.assignment_id, count(rc.sha)
               FROM assignments a
               LEFT JOIN raw_commits rc
                 ON rc.assignment_id = a.assignment_id AND rc.student_id = %s
               WHERE a.assignment_id = %s
               GROUP BY a.assignment_id""",
            (student_id, assignment_id),
        )
    return dict(cur.fetchall())
