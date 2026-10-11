"""scripts/backfill_mastery_observations.py -- D-079 for the history already in the database.

    python -m scripts.backfill_mastery_observations [--student anas --student student2]
    python -m scripts.backfill_mastery_observations --apply --backup backups/vdel_before_d079.sql

WHY IT EXISTS. From formula v5 on, mastery is replayed from `mastery_observation` traces, one per
(attempt, GAP), instead of one `test_result` per test. Grading writes those traces from now on;
this script writes the ones the already-graded history would have produced, by running the SAME
rule (`assessment.test_runner.gap_observation`) over the stored `test_results`: for every
(attempt, hidden gap), the first pushed commit (non-null commit_sha, status ok) in which the gap
was attempted. Until it is applied, replaying the real log yields only the legacy CI trace, so a
`scripts.demo` Beat 7 against the real database would report DIFFERENT.

DRY-RUN BY DEFAULT. With no flag it reads only (the session is opened read-only, Postgres
rejects any write) and prints exactly which traces it would append, then the profile each student
would have next to the stored one. The "would have" side is `Memory.replay_mastery_with`, the same
fold as the real replay, so it is a prediction, not a re-implementation.

--apply writes, and refuses unless `--backup PATH` names a file that already exists (take the
backup first, by hand). One transaction: the missing observation traces, then
`Memory.rebuild_from_traces` for each student, so the stored learner_profile equals the replay
(Beat 7 stays IDENTICAL). Idempotent: an (attempt, gap) that already has an observation is
skipped, so a second run appends nothing.

NOT TOUCHED: students whose id starts with "_" (test fixtures such as `_test_runner`), and the
legacy `ci_run` trace 28797 ("legacy, never written again": it stays in the log and keeps feeding
py.testing). No trace is ever updated or deleted.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime

from assessment.test_runner import TestOutcome, gap_observation
from memory.memory import Memory
from system import db

DEFAULT_STUDENTS = ("anas", "student2")


@dataclass(frozen=True)
class Planned:
    student_id: str
    attempt_id: int
    assignment_id: str
    attempt_no: int
    gap_id: str
    concepts: tuple[str, ...]
    commit_sha: str
    observed_at: datetime
    passed: bool
    difficulty: float
    present: bool           # an observation for this (attempt, gap) already exists

    @property
    def concept(self) -> str:
        return self.concepts[0]

    def payload(self) -> dict:
        """The what-if payload `Memory.replay_mastery_with` folds."""
        return {"concept": self.concept,
                "conclusion": "success" if self.passed else "failure",
                "item_difficulty": self.difficulty,
                "observed_at": self.observed_at.isoformat()}


def build_plan(cur, students) -> list[Planned]:
    """The observations the stored history implies, oldest commit first within each (attempt,
    gap). Read-only. Students starting with "_" are never planned."""
    students = [s for s in students if not s.startswith("_")]
    cur.execute(
        """
        SELECT a.student_id, a.attempt_id, a.assignment_id, a.attempt_no, t.gap_id,
               g.concept_ids, g.difficulty, t.commit_sha, c.committed_at,
               t.test_name, t.passed, t.message, t.status
        FROM test_results t
        JOIN attempts a USING (attempt_id)
        JOIN variants v ON v.variant_id = a.variant_id
        JOIN gaps g ON g.gap_id = t.gap_id
        JOIN raw_commits c ON c.sha = t.commit_sha
        WHERE t.commit_sha IS NOT NULL AND t.status = 'ok' AND t.gap_id = ANY(v.gap_ids)
          AND a.student_id = ANY(%s)
        ORDER BY a.student_id, a.attempt_id, t.gap_id, c.committed_at, t.commit_sha,
                 t.test_name
        """, (students,))
    # (student, attempt, gap) -> commit key -> its outcomes, in commit order
    grouped: dict[tuple, dict[tuple, list[TestOutcome]]] = {}
    meta: dict[tuple, tuple] = {}
    for (sid, att, asg, ano, gap, concepts, diff, sha, at,
         name, passed, message, status) in cur.fetchall():
        key = (sid, att, gap)
        meta[key] = (asg, ano, tuple(concepts), float(diff))
        grouped.setdefault(key, {}).setdefault((at, sha), []).append(
            TestOutcome(name, passed, message, gap, status))

    mem = Memory()
    plan: list[Planned] = []
    for key in sorted(grouped):
        sid, att, gap = key
        for (at, sha), outs in grouped[key].items():          # insertion order = commit order
            passed = gap_observation(outs)
            if passed is None:
                continue                                       # not attempted in this commit
            asg, ano, concepts, diff = meta[key]
            present = mem.has_mastery_observation(sid, att, gap, conn=cur.connection)
            plan.append(Planned(sid, att, asg, ano, gap, concepts, sha, at, passed, diff,
                                present))
            break                                              # the FIRST attempted commit only
    return plan


def predict(conn, plan, students) -> dict[str, dict]:
    """The mastery each student would have once the not-yet-present observations exist."""
    mem = Memory()
    return {s: mem.replay_mastery_with(
                s, [p.payload() for p in plan if p.student_id == s and not p.present], conn=conn)
            for s in students}


def _fmt(m: dict | None) -> str:
    if m is None:
        return "-"
    return f"p={m['p_mastery']:.4f} n={m['n']} ci90={m['ci90']}"


def show(conn, plan, students, out=print) -> None:
    new = [p for p in plan if not p.present]
    out(f"{len(new)} mastery_observation trace(s) would be appended "
        f"({len(plan) - len(new)} already present):")
    out(f"  {'student':9s} {'attempt':>7s} {'gap':15s} {'concept':20s} {'commit':10s} "
        f"{'outcome':8s} observed_at")
    for p in plan:
        out(f"  {p.student_id:9s} {p.attempt_id:>7d} {p.gap_id:15s} {p.concept:20s} "
            f"{p.commit_sha[:10]:10s} {'success' if p.passed else 'failure':8s} "
            f"{p.observed_at.isoformat()}" + ("   (already present)" if p.present else "")
            + (f"   [informational: {', '.join(p.concepts[1:])}]" if len(p.concepts) > 1 else ""))
    out("not touched: students starting with '_' (fixtures); the legacy ci_run trace 28797 "
        "(kept, never written again)")
    after = predict(conn, plan, students)
    mem = Memory()
    for s in students:
        stored = mem.get_profile(s, conn=conn)["mastery"]
        out(f"\nprofile of {s}  (stored today  ->  after the backfill)")
        for concept in sorted(set(stored) | set(after[s])):
            out(f"  {concept:22s} {_fmt(stored.get(concept)):52s} -> {_fmt(after[s].get(concept))}")


def apply_plan(conn, plan, students) -> int:
    """Append the missing observations, then rebuild each student's stored profile from the
    log. Joins the caller's transaction (main commits). Returns the number appended."""
    mem = Memory()
    written = 0
    for p in plan:
        if p.present:
            continue
        trace_id = mem.record_mastery_observation(
            p.student_id, attempt_id=p.attempt_id, assignment_id=p.assignment_id,
            gap_id=p.gap_id, concept_ids=list(p.concepts), passed=p.passed,
            item_difficulty=p.difficulty, commit_sha=p.commit_sha, observed_at=p.observed_at,
            conn=conn)
        if trace_id is not None:
            written += 1
    for s in sorted({p.student_id for p in plan} & set(students)):
        mem.rebuild_from_traces(s, conn=conn)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--student", action="append",
                        help=f"repeatable; default {' and '.join(DEFAULT_STUDENTS)}")
    parser.add_argument("--apply", action="store_true",
                        help="really write (needs --backup PATH to an existing file)")
    parser.add_argument("--backup", help="path of the backup you took before --apply")
    args = parser.parse_args(argv)
    students = args.student or list(DEFAULT_STUDENTS)

    fixtures = [s for s in students if s.startswith("_")]
    if fixtures:
        print(f"refused: {fixtures} are fixtures, never backfilled")
        return 2
    if args.apply and not (args.backup and os.path.isfile(args.backup)):
        print("refused: --apply needs --backup PATH naming a backup file that already exists "
              "(take the backup first, then pass its path)")
        return 2

    conn = db._open()
    try:
        if not args.apply:
            conn.set_session(readonly=True)              # Postgres itself rejects any write
        cur = conn.cursor()
        cur.execute("SELECT current_database()")
        print(f"database: {cur.fetchone()[0]}   "
              f"mode: {'APPLY' if args.apply else 'DRY-RUN (read-only)'}")
        plan = build_plan(cur, students)
        show(conn, plan, students)
        if not args.apply:
            print("\nDRY-RUN: nothing was written. Run with --apply --backup PATH to write.")
            conn.rollback()
            return 0
        written = apply_plan(conn, plan, students)
        conn.commit()
        print(f"\nAPPLIED: {written} trace(s) appended; profiles rebuilt from the log "
              f"(backup was {args.backup}).")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
