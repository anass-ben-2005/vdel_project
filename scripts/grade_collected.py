"""scripts/grade_collected.py -- grade the commits collect_github.py has collected.

The gap this closes: `collectors/collect_github.py` lands pushes in `raw_commits` and
deliberately writes nothing about test outcomes (D-045a), and `assessment/test_runner.py`
can grade a commit and freeze an attempt (D-045a/c) -- but nothing connected the two, so no
collected commit was ever graded and no attempt could freeze from a real push. This script
is that connection: for each attempt, find the commits attributed to it that have no
`test_results` rows yet, fetch EXACTLY that commit from the student's GitHub repo into a
throwaway directory, call `grade_attempt(..., commit_sha=sha)`, and delete the directory.

Choices made here that the request left open (stated, not hidden):

  - EVERY ungraded commit is graded, oldest first -- not only the newest. D-045c makes each
    commit's outcomes separate BKT observations and the raw material for V5/V6 (a student's
    failing history); grading only the latest would leave an earlier commit "ungraded" for
    ever, or grade it out of order on a later run. Oldest-first keeps the fail->pass
    sequence BKT replays in the order it happened. `--latest-only` gives the literal
    "newest commit only" behaviour; either way a second run grades nothing new.
  - WHICH attempt a commit belongs to: `raw_commits` carries no attempt_no, so this mirrors
    collect_github's own rule -- the highest-numbered attempt of that (student, assignment)
    that is still open (`submitted_at IS NULL`), else the highest-numbered overall. With one
    attempt per assignment (today) there is no ambiguity; with several, commits cannot be
    told apart by attempt and this rule is a stated assumption, not a fact.
  - Commits collect_github could not attribute to ONE assignment (`assignment_id IS NULL`,
    e.g. a 12-file initial commit) are not graded: there is no single hidden test file that
    applies to them. They are counted and reported.
  - A commit that yields ZERO test rows (every test skipped) leaves nothing for the
    "already graded" check to find, so it would be retried on every run. Reported as a
    warning; not papered over.

Auth: a GitHub token is passed to git through GIT_CONFIG_* environment variables, never on
the command line (visible in process listings) and never in a URL (written into
.git/config). The clone lives in a temp directory removed in a `finally`.

Idempotent (invariant 9): "already graded" is read from `test_results` itself, so a second
run finds nothing to do. No agent is involved and this module imports nothing from
`agents/` or `system/llm.py` (invariant 13): it only runs the test runner.
"""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from assessment.test_runner import grade_attempt
from system import db

_GIT_TIMEOUT_S = 180


@dataclass(frozen=True)
class Pending:
    """One commit that needs grading, with everything required to do it."""

    attempt_id: int
    student_id: str
    project_id: str
    assignment_id: str
    attempt_no: int
    sha: str
    committed_at: object
    owner: str | None
    repo: str | None


# --- what needs grading ------------------------------------------------------------------

def _target_attempts(cur, student: str | None,
                     assignment: str | None = None) -> dict[tuple[str, str], tuple]:
    """(student, assignment) -> (attempt_id, project_id, attempt_no), by the rule in the
    module docstring: highest open attempt_no, else highest attempt_no overall."""
    conds, args = [], []
    for column, value in (("student_id", student), ("assignment_id", assignment)):
        if value is not None:
            conds.append(f"{column} = %s")
            args.append(value)
    where = f" WHERE {' AND '.join(conds)}" if conds else ""
    cur.execute("SELECT attempt_id, student_id, project_id, assignment_id, attempt_no,"
                "       submitted_at IS NULL FROM attempts" + where + " ORDER BY attempt_no",
                tuple(args))
    chosen: dict[tuple[str, str], tuple] = {}
    for attempt_id, student_id, project_id, assignment_id, attempt_no, is_open in cur.fetchall():
        key = (student_id, assignment_id)
        prior = chosen.get(key)
        # rows arrive in ascending attempt_no, so a later row is "higher"; an open attempt
        # beats a frozen one regardless of number.
        if prior is None or is_open or not prior[3]:
            chosen[key] = (attempt_id, project_id, attempt_no, is_open)
    return {k: v[:3] for k, v in chosen.items()}


def find_pending(
    cur, repo_for: dict, *, student: str | None = None,
    assignment: str | None = None, latest_only: bool = False,
) -> tuple[list[Pending], dict]:
    """Every (attempt, commit) with no test_results row yet, oldest commit first within
    an attempt. Returns (pending, skipped_counts)."""
    pending: list[Pending] = []
    for (student_id, assignment_id), (attempt_id, project_id, attempt_no) in sorted(
        _target_attempts(cur, student, assignment).items(), key=lambda kv: kv[1][0]
    ):
        cur.execute(
            "SELECT c.sha, c.committed_at FROM raw_commits c"
            " WHERE c.student_id = %s AND c.assignment_id = %s"
            "   AND NOT EXISTS (SELECT 1 FROM test_results t"
            "                   WHERE t.attempt_id = %s AND t.commit_sha = c.sha)"
            " ORDER BY c.committed_at, c.sha",
            (student_id, assignment_id, attempt_id),
        )
        rows = cur.fetchall()
        if latest_only:
            rows = rows[-1:]
        owner, repo = repo_for.get((student_id, assignment_id), (None, None))
        pending.extend(
            Pending(attempt_id, student_id, project_id, assignment_id, attempt_no,
                    sha, committed_at, owner, repo)
            for sha, committed_at in rows
        )

    ambiguous_sql = "SELECT count(*) FROM raw_commits WHERE assignment_id IS NULL"
    ambiguous_args: tuple = ()
    if student is not None:
        ambiguous_sql += " AND student_id = %s"
        ambiguous_args = (student,)
    cur.execute(ambiguous_sql, ambiguous_args)
    return pending, {"unattributed_commits": cur.fetchone()[0]}


# --- getting the exact commit -------------------------------------------------------------

def _git_env(url: str) -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://github.com/"):
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {basic}"
    return env


def checkout_commit(owner: str | None, repo: str | None, sha: str, dest: Path,
                    *, remote_url: str | None = None) -> None:
    """Materialise EXACTLY `sha` at `dest`. fetch-by-sha + detached checkout, then verify
    HEAD == sha: a branch name or a symbolic ref could move between collection and grading,
    and grading a different commit than the one recorded would attach test results to the
    wrong row. `remote_url` exists so the test can point at a local repo."""
    url = remote_url or f"https://github.com/{owner}/{repo}.git"
    env = _git_env(url)
    dest.mkdir(parents=True)

    def git(*args: str) -> str:
        try:
            done = subprocess.run(["git", *args], cwd=dest, env=env, check=True,
                                  capture_output=True, text=True, timeout=_GIT_TIMEOUT_S)
        except subprocess.CalledProcessError as exc:
            # stderr only: the command line never contains the token, but be explicit.
            raise RuntimeError(f"git {args[0]} failed: {exc.stderr.strip()}") from None
        return done.stdout.strip()

    git("init", "-q")
    git("fetch", "-q", "--depth", "1", url, sha)
    git("checkout", "-q", "--detach", "FETCH_HEAD")
    head = git("rev-parse", "HEAD")
    if head != sha:
        raise RuntimeError(f"checked out {head}, expected {sha}")


def _remove_tree(path: Path) -> None:
    """rmtree that survives git's read-only object files on Windows."""
    def _retry(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:
        shutil.rmtree(path, onerror=lambda f, p, e: _retry(f, p, e))


# --- the loop -----------------------------------------------------------------------------

def run(
    *, student: str | None = None, assignment: str | None = None,
    dry_run: bool = False, latest_only: bool = False, repo_for: dict,
    checkout=checkout_commit, grade=grade_attempt, conn=None,
) -> dict:
    """Grade everything pending. `conn`: join a caller's transaction (tests; traces are
    append-only so a test must roll back rather than delete); None = production, where
    `grade_attempt` commits per commit. `checkout`/`grade` are injectable for the same
    reason. Returns a summary dict; never raises for a single bad commit (per-commit
    isolation, same stance as collect_github's per-repo isolation)."""
    if conn is None:
        with db.cursor() as cur:
            pending, skipped = find_pending(cur, repo_for, student=student,
                                            assignment=assignment, latest_only=latest_only)
    else:
        pending, skipped = find_pending(conn.cursor(), repo_for, student=student,
                                        assignment=assignment, latest_only=latest_only)

    summary = {"pending": len(pending), "graded": [], "failed": [], "no_repo": [],
               "would_grade": [], **skipped}
    for p in pending:
        label = f"attempt={p.attempt_id} ({p.student_id}/{p.assignment_id}) {p.sha[:10]}"
        if p.owner is None:
            summary["no_repo"].append(label)
            print(f"  NO REPO   {label}: no roster entry for this student/assignment")
            continue
        if dry_run:
            summary["would_grade"].append(label)
            print(f"  WOULD GRADE  {label}  from {p.owner}/{p.repo}  committed {p.committed_at}")
            continue

        tmp = Path(tempfile.mkdtemp(prefix="vdel_grade_"))
        try:
            repo_dir = tmp / "repo"
            checkout(p.owner, p.repo, p.sha, repo_dir)
            result = grade(p.project_id, p.assignment_id, repo_dir, p.attempt_id,
                           commit_sha=p.sha, conn=conn)
            summary["graded"].append((p.attempt_id, p.sha, result.tests_passed,
                                      result.tests_total, result.frozen))
            print(f"  GRADED    {label}: {result.tests_passed}/{result.tests_total} passed"
                  f" frozen={result.frozen}")
            if result.tests_total == 0:
                print("    WARNING: zero test rows -- this commit will be retried next run")
        except Exception as exc:  # noqa: BLE001 -- one bad commit must not stop the rest
            summary["failed"].append((label, f"{type(exc).__name__}: {exc}"))
            print(f"  FAILED    {label}: {type(exc).__name__}: {exc}")
        finally:
            _remove_tree(tmp)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--student", help="only this student_id")
    parser.add_argument("--assignment", help="only this assignment_id")
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be graded; fetch and write nothing")
    parser.add_argument("--latest-only", action="store_true",
                        help="grade only each attempt's newest ungraded commit")
    args = parser.parse_args(argv)

    from scripts.seed_data import load_roster  # the loader collect_github's callers use
    repo_for = {(a["student_id"], a["assignment_id"]): (a["owner"], a["repo"])
                for a in load_roster().get("assignments", [])}

    summary = run(student=args.student, assignment=args.assignment, dry_run=args.dry_run,
                  latest_only=args.latest_only, repo_for=repo_for)
    print(f"\npending={summary['pending']} graded={len(summary['graded'])}"
          f" failed={len(summary['failed'])} no_repo={len(summary['no_repo'])}"
          f" would_grade={len(summary['would_grade'])}"
          f" unattributed_commits_skipped={summary['unattributed_commits']}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
