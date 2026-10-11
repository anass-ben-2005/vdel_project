"""scripts/run_cycle.py -- one idempotent command that runs the whole student-side pipeline.

    python -m scripts.run_cycle [--student X] [--roster PATH] [--dry-run]
                                [--skip-network] [--with-llm]

For every student in the roster (or just --student), in this order, each stage a separate
unit of work:

    1. collect     GitHub -> raw_commits / raw_workflow_runs      (collect_all, network)
    2. grade       ungraded commits -> test_results, traces       (grade_collected.run, network)
    3. features    learner_features, only for students whose latest event has no row yet
    4. profile     Memory.sync_features_ref, only when features_ref is stale
    5. llm         off by default; `--with-llm` reports "not wired" (see below)

It reuses the existing functions and reimplements none of them (D-071). Idempotent: a second
run with nothing new on GitHub writes nothing -- the collector skips what it stored, the
grader skips commits that already have test_results, features are computed only when the
student's watermark has no row, and the profile pointer is synced only when stale.

Guarantees (each is a test in tests/test_run_cycle.py):
  - ONE cycle at a time: a Postgres advisory lock. A second cycle exits at once with code 3.
  - DB down: exits at once with code 2 and a plain message, before doing anything.
  - ISOLATION: a failure for one student (an exception in any stage, or a failed repo) is
    recorded and printed; the other students still run. Exit code 1 if any student failed.
  - `--dry-run`: reads only. No network, no INSERT/UPDATE/DELETE, no commit. It says what a
    cycle would do today. (The advisory lock is taken: it is not a table write.)
  - `--skip-network`: stages 1 and 2 are skipped (grading fetches the commit from GitHub);
    features and profile are computed from what the database already holds.

`--with-llm` is a stub: the Code Agent needs a rendered checkout of the student's repo and a
billed call per attempt, which is more than a pipeline stage; it is not wired here, and the
cycle says so rather than pretending.

Exit codes: 0 all students ok (or dry-run); 1 some student failed; 2 database unreachable;
3 another cycle holds the lock.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from dataclasses import dataclass, field

from assessment.test_runner import grade_attempt
from collectors.collect_github import collect_all
from features import compute_features as cf
from memory.memory import Memory
from scripts import grade_collected as gc
from scripts.seed_data import load_roster, roster_repo_for, roster_repos
from system import db

ADVISORY_LOCK_KEY = 640_201_071       # arbitrary constant: "one vdel cycle at a time"
EXIT_OK, EXIT_STUDENT_FAILED, EXIT_DB_DOWN, EXIT_LOCKED = 0, 1, 2, 3


@dataclass
class StudentResult:
    student_id: str
    commits_added: int = 0
    runs_added: int = 0
    graded: int = 0
    frozen: int = 0
    pending: int = 0
    post_freeze_skipped: int = 0
    features: str = "-"
    profile: str = "-"
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class CycleResult:
    exit_code: int
    students: list[StudentResult] = field(default_factory=list)
    message: str = ""


# --- plumbing ---------------------------------------------------------------------------------

@contextlib.contextmanager
def _unit(conn, name: str):
    """One stage of one student as an atomic unit of work.

    Production (`conn is None`): its own connection, committed on success, rolled back on
    error. Tests pass a `conn`: the unit is a SAVEPOINT inside that one transaction, so a
    failing stage is undone without losing the stages before it, and the whole test can still
    be rolled back at the end (traces are append-only; rollback is the only cleanup)."""
    if conn is None:
        with db.connect() as c:
            yield c
        return
    savepoint = f"cycle_{name}"
    cur = conn.cursor()
    cur.execute(f"SAVEPOINT {savepoint}")
    try:
        yield conn
    except Exception:
        cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        raise
    else:
        cur.execute(f"RELEASE SAVEPOINT {savepoint}")


def _count(cur, table: str, student_id: str) -> int:
    assert table in ("raw_commits", "raw_workflow_runs")
    cur.execute(f"SELECT count(*) FROM {table} WHERE student_id = %s", (student_id,))
    return cur.fetchone()[0]


def _needs_features(cur, student_id: str) -> bool:
    """True when the student has activity and no learner_features row sits at its watermark.

    Whatever the row's formula_ver: a v2/v3 row at the same watermark means "already
    computed" (write_features never overwrites another version -- D-063), so the cycle does
    not retry it every time."""
    mark = cf.watermark(cur, student_id)
    if mark is None:
        return False
    cur.execute("SELECT 1 FROM learner_features WHERE student_id = %s AND computed_at = %s",
                (student_id, mark))
    return cur.fetchone() is None


# --- the stages -------------------------------------------------------------------------------

def _stage_collect(res, sid, repos, conn, collect, dry_run, out):
    if dry_run:
        out(f"  collect   WOULD collect {len(repos)} roster row(s) from GitHub (dry-run: "
            "no network, nothing written)")
        return
    with _unit(conn, "collect") as c:
        cur = c.cursor()
        before = (_count(cur, "raw_commits", sid), _count(cur, "raw_workflow_runs", sid))
        outcome = collect(c, repos)
        after = (_count(cur, "raw_commits", sid), _count(cur, "raw_workflow_runs", sid))
    res.commits_added, res.runs_added = after[0] - before[0], after[1] - before[1]
    for failed in outcome.get("failed", []):
        res.errors.append(f"collect {failed['repo']}: {failed['error']}")
    out(f"  collect   +{res.commits_added} commit(s), +{res.runs_added} run(s)"
        + (f", {len(outcome.get('failed', []))} repo(s) FAILED" if outcome.get("failed") else ""))


def _stage_grade(res, sid, repo_for, conn, checkout, grade, dry_run, out):
    with _unit(conn, "grade") as c:
        summary = gc.run(student=sid, dry_run=dry_run, repo_for=repo_for,
                         checkout=checkout, grade=grade, conn=c)
    res.pending = summary["pending"]
    res.post_freeze_skipped = summary["post_freeze_commits_skipped"]
    if dry_run:
        out(f"  grade     WOULD grade {len(summary['would_grade'])} commit(s)"
            f" ({summary['unattributed_commits']} unattributed, "
            f"{summary['post_freeze_commits_skipped']} after a freeze, not graded)")
        return
    res.graded = len(summary["graded"])
    res.frozen = sum(1 for g in summary["graded"] if g[4])
    for label, err in summary["failed"]:
        res.errors.append(f"grade {label}: {err}")
    out(f"  grade     {res.graded} graded, {res.frozen} attempt(s) frozen, "
        f"{len(summary['failed'])} failed, {len(summary['no_repo'])} without a repo, "
        f"{res.post_freeze_skipped} after a freeze (not graded)")


def _stage_features(res, sid, conn, dry_run, out):
    with _unit(conn, "features") as c:
        cur = c.cursor()
        if not _needs_features(cur, sid):
            res.features = "up to date"
            out("  features up to date (a row already sits at the watermark, or no activity)")
            return
        if dry_run:
            res.features = "would compute"
            out("  features WOULD compute a learner_features row")
            return
        cur.execute("SELECT count(*) FROM learner_features WHERE student_id = %s", (sid,))
        before = cur.fetchone()[0]
        cf.run(only=[sid], conn=c)
        cur.execute("SELECT count(*) FROM learner_features WHERE student_id = %s", (sid,))
        res.features = "written" if cur.fetchone()[0] > before else "skipped"
    out(f"  features {res.features}")


def _stage_profile(res, sid, mem, conn, dry_run, out):
    with _unit(conn, "profile") as c:
        if not mem.features_ref_is_stale(sid, conn=c):
            res.profile = "current"
            out("  profile   features_ref current")
            return
        if dry_run:
            res.profile = "would sync"
            out("  profile   WOULD sync features_ref")
            return
        mem.sync_features_ref(sid, conn=c)
        res.profile = "synced"
    out("  profile   features_ref synced")


# --- the cycle --------------------------------------------------------------------------------

def run_cycle(roster: dict, *, student: str | None = None, dry_run: bool = False,
              skip_network: bool = False, with_llm: bool = False, conn=None,
              collect=collect_all, checkout=gc.checkout_commit, grade=grade_attempt,
              out=print) -> CycleResult:
    """Run one cycle over `roster`. Never raises for a single student's failure.

    `conn`: tests only (see `_unit`). `collect` / `checkout` / `grade` are injectable so the
    tests use a fake GitHub layer: no network is needed to exercise the whole cycle."""
    lock_conn = None
    try:
        lock_conn = db._open()                  # also the fail-fast "is the database there?"
        lock_conn.autocommit = True
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
            acquired = cur.fetchone()[0]
    except Exception as exc:  # noqa: BLE001 -- any failure to connect is the same message
        if lock_conn is not None:
            lock_conn.close()
        msg = f"DATABASE UNREACHABLE: {type(exc).__name__}: {str(exc).strip()[:200]}"
        out(msg)
        return CycleResult(EXIT_DB_DOWN, message=msg)
    if not acquired:
        lock_conn.close()
        msg = ("ANOTHER CYCLE IS RUNNING (advisory lock held): exiting without doing "
               "anything. Wait for it to finish.")
        out(msg)
        return CycleResult(EXIT_LOCKED, message=msg)

    try:
        return _run_locked(roster, student, dry_run, skip_network, with_llm, conn,
                           collect, checkout, grade, out)
    finally:
        lock_conn.close()                 # closing the session releases the advisory lock


def _run_student(sid, repos, repo_for, mem, conn, skip_network, dry_run,
                 collect, checkout, grade, out) -> StudentResult:
    """All stages for ONE student. An exception in a stage is recorded on the result and the
    next stage still runs; nothing here can stop another student."""
    out(f"[{sid}]")
    res = StudentResult(sid)
    stages = []
    if not skip_network:
        stages.append(("collect", lambda: _stage_collect(
            res, sid, repos, conn, collect, dry_run, out)))
        stages.append(("grade", lambda: _stage_grade(
            res, sid, repo_for, conn, checkout, grade, dry_run, out)))
    else:
        out("  collect/grade skipped (--skip-network)")
    stages.append(("features", lambda: _stage_features(res, sid, conn, dry_run, out)))
    stages.append(("profile", lambda: _stage_profile(res, sid, mem, conn, dry_run, out)))
    for name, stage in stages:
        try:
            stage()
        except Exception as exc:  # noqa: BLE001 -- isolation: record and carry on
            res.errors.append(f"{name}: {type(exc).__name__}: {str(exc).strip()[:300]}")
            out(f"  {name:<9} FAILED: {type(exc).__name__}: {str(exc).strip()[:300]}")
    return res


def _run_locked(roster, student, dry_run, skip_network, with_llm, conn,
                collect, checkout, grade, out) -> CycleResult:
    all_repos = roster_repos(roster)
    repo_for = roster_repo_for(roster)
    student_ids = list(dict.fromkeys(r["student_id"] for r in all_repos))
    if student is not None:
        student_ids = [s for s in student_ids if s == student]
        if not student_ids:
            msg = f"student {student!r} is not in the roster"
            out(msg)
            return CycleResult(EXIT_STUDENT_FAILED, message=msg)

    mode = "DRY-RUN (reads only)" if dry_run else "LIVE"
    out(f"cycle: {len(student_ids)} student(s), {mode}"
        + (", network skipped" if skip_network else ""))
    if with_llm:
        out("llm: NOT WIRED in run_cycle (the Code Agent needs a rendered checkout and a "
            "billed call per attempt); skipped")

    mem = Memory()
    results = [_run_student(sid, [r for r in all_repos if r["student_id"] == sid], repo_for,
                            mem, conn, skip_network, dry_run, collect, checkout, grade, out)
               for sid in student_ids]

    out("")
    out(f"{'student':<14}{'+commits':>9}{'+runs':>7}{'graded':>8}{'frozen':>8}"
        f"  {'features':<14}{'profile':<12}status")
    for r in results:
        out(f"{r.student_id:<14}{r.commits_added:>9}{r.runs_added:>7}{r.graded:>8}"
            f"{r.frozen:>8}  {r.features:<14}{r.profile:<12}{'ok' if r.ok else 'FAILED'}")
        for e in r.errors:
            out(f"    ! {e}")
    failed = [r for r in results if not r.ok]
    code = EXIT_STUDENT_FAILED if failed else EXIT_OK
    out(f"cycle done: {len(results) - len(failed)} ok, {len(failed)} failed -> exit {code}")
    return CycleResult(code, results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--student", help="only this student_id")
    parser.add_argument("--roster", default=None,
                        help="roster file (default config/roster.yaml)")
    parser.add_argument("--dry-run", action="store_true",
                        help="read only: say what a cycle would do, write nothing")
    parser.add_argument("--skip-network", action="store_true",
                        help="skip collect and grade (both need GitHub)")
    parser.add_argument("--with-llm", action="store_true",
                        help="stub: reports 'not wired'")
    args = parser.parse_args(argv)
    result = run_cycle(load_roster(args.roster), student=args.student, dry_run=args.dry_run,
                       skip_network=args.skip_network, with_llm=args.with_llm)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
