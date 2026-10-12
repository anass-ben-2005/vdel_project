"""scripts/run_hourly.py -- the one command the hourly Windows task runs (D-091).

    python -m scripts.run_hourly [--roster PATH] [--dry-run] [--skip-network]
                                 [--lookback-hours N] [--with-llm]
                                 [--llm-run-cap N] [--llm-daily-cap N]

Two phases, in order, under one lock:

  1. `run_cycle` for every student in the roster: collect, grade, features, profile (D-071).
  2. feedback by GitHub issue (D-089) for the commits graded in the last `--lookback-hours` (default
     48) that have no comment yet. The lookback is what keeps the backlog quiet: commits graded
     long ago are never posted by the task (post them by hand with `post_feedback --issue`), while
     a post that failed this hour is retried for two days.

AGENTS (D-099). `--with-llm` is OFF by default and is NOT in the scheduled task's command: the task
runs exactly what it ran before. When given, phase 1 calls the agents on each commit it grades
(see `run_cycle`, with the same `--llm-run-cap` / `--llm-daily-cap`), and phase 2 ADDS the stored
LLM paragraph under the deterministic comment, never in place of it. No stored paragraph, or one
that would leak hidden test source, means the deterministic text alone.

GITHUB WRITES. Phase 2 writes to GitHub ONLY when the environment variable
`VDEL_ALLOW_GITHUB_WRITE=1` is set in the task's environment (and `--dry-run` is not given).
Without it the task still collects, grades and computes, and the log says how many comments WOULD
have been posted. The flag is therefore the single switch between "observe" and "talk to students".
A placeholder `github_username` is refused by the posting code (D-089).

LOCKS. `run_hourly` takes its own Postgres advisory lock for the whole run, so two hourly tasks
never overlap (the second exits with code 3 at once); `run_cycle` takes its own lock inside, so a
manual `run_cycle` started while the task runs is also refused rather than interleaved.

LOGS. `logs/run_hourly-YYYY-MM-DD.log` (gitignored), one file per day, appended; files older than
14 days are deleted at the start of each run. Everything printed also goes to the console.

EXIT CODES. 0 ok; 1 some student or some post failed (the log says which); 2 the database is
unreachable (a plain `DATABASE UNREACHABLE` line, nothing else is attempted); 3 another run holds
the lock. The task scheduler shows a non-zero code as a failed run.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agents.pipeline import find_feedback_addendum
from scripts import run_cycle as rc
from scripts.post_feedback import (
    GITHUB_WRITE_ENV_VAR,
    HiddenSourceLeak,
    plan_issue_post,
    post_issue_feedback,
    recent_unposted,
)
from scripts.seed_data import load_roster, roster_repo_for, roster_repos
from system import db

HOURLY_LOCK_KEY = 640_201_072          # next to run_cycle's 640_201_071: "one hourly run at a time"
LOG_KEEP_DAYS = 14
DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
DEFAULT_LOOKBACK_HOURS = 48
EXIT_OK, EXIT_FAILED, EXIT_DB_DOWN, EXIT_LOCKED = 0, 1, 2, 3


class Tee:
    """Print to the console and append to today's log file, each line timestamped in the file."""

    def __init__(self, log_dir: Path, now: datetime):
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / f"run_hourly-{now:%Y-%m-%d}.log"
        self._fh = self.path.open("a", encoding="utf-8")

    def __call__(self, text: str = "") -> None:
        print(text)
        stamp = datetime.now(UTC).strftime("%H:%M:%S")
        for line in str(text).splitlines() or [""]:
            self._fh.write(f"{stamp} {line}\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def rotate_logs(log_dir: Path, now: datetime, keep_days: int = LOG_KEEP_DAYS) -> list[str]:
    """Delete `run_hourly-YYYY-MM-DD.log` files older than `keep_days`. Judged by the date in the
    NAME (not the modification time, which a copy or a restore changes); other files are never
    touched. Returns the names removed."""
    removed = []
    cutoff = (now - timedelta(days=keep_days)).date()
    for path in sorted(log_dir.glob("run_hourly-*.log")):
        try:
            day = datetime.strptime(  # noqa: DTZ007 -- a calendar date from a file name
                path.stem.removeprefix("run_hourly-"), "%Y-%m-%d").date()
        except ValueError:
            continue
        if day < cutoff:
            path.unlink()
            removed.append(path.name)
    return removed


def _plan(cur, attempt_id: int, sha: str, repo_for: dict, *, with_llm: bool, out):
    """The post plan: deterministic text, plus the stored LLM paragraph under it when `with_llm`.
    Any problem with the paragraph (none stored, hidden source in it, a read error) gives the
    deterministic plan alone; the LLM text can add to a comment, never remove or block one."""
    if with_llm:
        try:
            addendum = find_feedback_addendum(cur, attempt_id, sha)
            if addendum:
                return plan_issue_post(cur, attempt_id, sha, repo_for, addendum=addendum)
        except HiddenSourceLeak:
            out(f"    llm paragraph for attempt {attempt_id} commit {sha[:10]} dropped (it held "
                "hidden test source); posting the deterministic text alone")
    return plan_issue_post(cur, attempt_id, sha, repo_for)


def _feedback_phase(roster: dict, *, write: bool, lookback_hours: int, gh, out,
                    conn=None, with_llm: bool = False) -> int:
    """Comment on the recently graded commits. Returns the number of failures. `conn`: a caller's
    transaction (tests), never committed, rolled back or closed here."""
    repo_for = roster_repo_for(roster)
    students = list(dict.fromkeys(r["student_id"] for r in roster_repos(roster)))
    failures = 0
    own = conn is None
    if own:
        conn = db._open()
    try:
        cur = conn.cursor()
        for student in students:
            todo = recent_unposted(cur, student, lookback_hours)
            if not todo:
                out(f"[{student}] feedback: nothing new in the last {lookback_hours} h")
                continue
            for attempt_id, sha in todo:
                plan = _plan(cur, attempt_id, sha, repo_for, with_llm=with_llm, out=out)
                label =f"[{student}] attempt {attempt_id} commit {sha[:10]} -> " \
                        f"{plan.owner}/{plan.repo}"
                if not write:
                    note = f" (would be refused: {'; '.join(plan.problems)})" if plan.refused \
                        else ""
                    out(f"{label}: WOULD POST (writes are off: {GITHUB_WRITE_ENV_VAR} is not "
                        f"1){note}")
                    continue
                outcome = post_issue_feedback(cur, plan, apply=True, gh=gh)
                out(f"{label}: {outcome.status} {outcome.detail} {outcome.comment_url or ''}")
                if outcome.status in ("posted", "recovered"):
                    if own:
                        conn.commit()
                else:
                    if own:
                        conn.rollback()
                    if outcome.status in ("failed", "refused"):
                        failures += 1
    finally:
        if own:
            conn.rollback()
            conn.close()
    return failures


def run(*, roster_path: str | Path | None = None, dry_run: bool = False,
        skip_network: bool = False, lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
        log_dir: Path | None = None, now: datetime | None = None, gh=None,
        collect=None, checkout=None, grade=None, out=None, conn=None,
        with_llm: bool = False, llm_run_cap: int = rc.DEFAULT_LLM_RUN_CAP,
        llm_daily_cap: int = rc.DEFAULT_LLM_DAILY_CAP, llm=None, ledger=None) -> int:
    """One hourly run. `collect` / `checkout` / `grade` / `gh` / `out` / `conn` are injectable for
    tests (`conn`: one caller-owned transaction used by the cycle and the feedback phase); so are
    `llm` and `ledger` (a `FakeLLM`, an in-memory `UsageLedger`)."""
    now = now or datetime.now(UTC)
    log_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
    tee = None
    if out is None:
        tee = Tee(log_dir, now)
        out = tee
    try:
        # D-095: the very first line, before rotation, the lock or the database, so a run that
        # dies early still leaves a trace (an empty log used to be the only symptom).
        out(f"run_hourly START pid={os.getpid()} cwd={Path.cwd()} python={sys.executable}")
        for name in rotate_logs(log_dir, now):
            out(f"log rotation: removed {name}")
        out(f"run_hourly {now:%Y-%m-%d %H:%M} UTC  {'DRY-RUN' if dry_run else 'LIVE'}"
            f"{', network skipped' if skip_network else ''}")

        try:
            lock_conn = db._open()
            lock_conn.autocommit = True
            with lock_conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (HOURLY_LOCK_KEY,))
                acquired = cur.fetchone()[0]
        except Exception as exc:  # noqa: BLE001 -- any connection failure is the same message
            out(f"DATABASE UNREACHABLE: {type(exc).__name__}: {str(exc).strip()[:200]}")
            out("Is Docker running? `docker compose up -d` in the project folder, then wait for "
                "the container to be healthy.")
            return EXIT_DB_DOWN
        if not acquired:
            lock_conn.close()
            out("ANOTHER run_hourly IS RUNNING (advisory lock held): exiting without doing "
                "anything.")
            return EXIT_LOCKED

        try:
            try:
                roster = load_roster(roster_path)
            except SystemExit as exc:
                out(f"ROSTER PROBLEM: {exc}")
                return EXIT_FAILED
            injected = {k: v for k, v in (("collect", collect), ("checkout", checkout),
                                          ("grade", grade)) if v is not None}
            cycle = rc.run_cycle(roster, dry_run=dry_run, skip_network=skip_network, out=out,
                                 conn=conn, with_llm=with_llm, llm_run_cap=llm_run_cap,
                                 llm_daily_cap=llm_daily_cap, llm=llm, ledger=ledger,
                                 **injected)
            if cycle.exit_code in (rc.EXIT_DB_DOWN, rc.EXIT_LOCKED):
                return EXIT_DB_DOWN if cycle.exit_code == rc.EXIT_DB_DOWN else EXIT_LOCKED

            write = os.environ.get(GITHUB_WRITE_ENV_VAR) == "1" and not dry_run
            out("")
            out(f"feedback by issue: {'WRITES ON' if write else 'writes off'}")
            failures = _feedback_phase(roster, write=write, lookback_hours=lookback_hours, gh=gh,
                                       out=out, conn=conn, with_llm=with_llm)
            code = EXIT_FAILED if (cycle.exit_code or failures) else EXIT_OK
            out(f"run_hourly done: cycle exit {cycle.exit_code}, feedback failures {failures} "
                f"-> exit {code}")
            return code
        finally:
            lock_conn.close()             # closing the session releases the advisory lock
    finally:
        if tee is not None:
            tee.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--roster", default=None, help="roster file (default config/roster.yaml)")
    ap.add_argument("--dry-run", action="store_true",
                    help="run_cycle dry-run and no GitHub write whatever the environment says")
    ap.add_argument("--skip-network", action="store_true",
                    help="skip collect and grade (the feedback phase still runs)")
    ap.add_argument("--lookback-hours", type=int, default=DEFAULT_LOOKBACK_HOURS,
                    help="only comment on commits graded in the last N hours (default 48)")
    rc.add_llm_arguments(ap)
    args = ap.parse_args(argv)
    with contextlib.suppress(AttributeError):
        sys.stdout.reconfigure(line_buffering=True)
    return run(roster_path=args.roster, dry_run=args.dry_run, skip_network=args.skip_network,
               lookback_hours=args.lookback_hours, with_llm=args.with_llm,
               llm_run_cap=args.llm_run_cap, llm_daily_cap=args.llm_daily_cap)


if __name__ == "__main__":
    sys.exit(main())
