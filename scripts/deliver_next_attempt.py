"""scripts/deliver_next_attempt.py -- hand attempt N+1 of ONE assignment to ONE student (D-090).

    python -m scripts.deliver_next_attempt --student X --assignment Y [--roster PATH]
                                           [--force --i-understand] [--resume]
                                           [--apply]

The delivery chain, in one command, dry-run by default:

  1. check the student's CURRENT attempt is frozen (its hidden tests reached 100% on a pushed
     commit). `--force` is refused unless `--i-understand` is also given, because D-072's closure
     of a stale attempt (`attempts.closed_at`) does not exist: a forced old attempt stays open, and
     `grade_collected` lets an open attempt win over a frozen higher one.
  2. `next_attempt` records the attempt (variant from the student's current mastery).
  3. `publish_repo` creates a NEW private repo holding only that assignment's stage, named
     `vdel-<project>-gapfill-<student>-<stage>-attempt<n>` (the stage is in the name so attempt 2 of
     two different stages never collide), and pushes the rendered tree.
  4. the student is invited as a collaborator on it.
  5. a comment with the new repo's link is added to the feedback issue of the attempt just
     completed (D-089).
  6. the roster rows to add are PRINTED. `config/roster.yaml` is never edited here: a roster that
     still points at the old repo means the next cycle does not see the new one, and that is the
     last manual step on purpose. The command that applies them is printed too
     (`python -m scripts.roster_apply ... --yes`, D-105): it keeps a backup, shows the diff and
     refuses an ambiguous target; the delivery itself still never touches the roster.

DRY-RUN (the default): reads only. It prints the decision, the variant and file list, the repo
name, the roster lines, and the exact GitHub calls and comment text it would send. It contacts
nothing and records nothing (the database work runs inside rolled-back savepoints).

THE REAL RUN needs `--apply` AND the environment variable `VDEL_ALLOW_GITHUB_WRITE=1`, and refuses
a placeholder `github_username`. Every GitHub step is idempotent so a half-finished delivery can be
finished with `--resume`: an existing repo with commits is not re-published, the invitation is a
PUT (already a collaborator is fine), and the comment carries a marker that is looked for first.

WHY `attempts.started_at` EXISTS (sql/10): attempt N+1 is a new repo but `raw_commits` keeps attempt
N's commits under the same (student, assignment); the grader ignores commits older than the
attempt's start, otherwise it would offer them for attempt N+1 and fail to fetch them every cycle.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from scripts import next_attempt as na
from scripts import publish_repo as pr
from scripts.post_feedback import (
    GITHUB_WRITE_ENV_VAR,
    GitHubWriteNotEnabled,
    ensure_issue,
    is_placeholder_username,
    issue_title,
    require_github_write,
)
from scripts.seed_data import load_roster, roster_repo_for
from system import db


def stage_name(project_id: str, assignment_id: str) -> str:
    return assignment_id.removeprefix(project_id + "_")


def delivery_repo_name(project_id: str, student_id: str, assignment_id: str,
                       attempt_no: int) -> str:
    return (f"{pr.default_repo_name(project_id, student_id)}-"
            f"{stage_name(project_id, assignment_id)}-attempt{attempt_no}")


def delivery_marker(new_attempt_id: int) -> str:
    return f"<!-- vdel:delivery attempt={new_attempt_id} -->"


def delivery_comment(username: str, assignment_id: str, done_no: int, next_no: int,
                     owner: str, repo: str, new_attempt_id: int | None) -> str:
    marker = delivery_marker(new_attempt_id) if new_attempt_id is not None else \
        "<!-- vdel:delivery attempt=<id> -->"
    return (f"@{username} attempt {done_no} of `{assignment_id}` is complete.\n\n"
            f"Attempt {next_no} is ready: https://github.com/{owner}/{repo}\n\n"
            "You have been given access (an invitation to accept if you are not the owner: "
            f"https://github.com/{owner}/{repo}/invitations). Push your work for attempt "
            f"{next_no} to that repository.\n{marker}\n")


def _is_owner(username: str | None, owner: str | None) -> bool:
    """GitHub refuses (422) to invite the owner of a repository as its collaborator; when the
    trusted student is the account that owns the repos, there is nobody to invite."""
    return bool(username and owner and username.lower() == owner.lower())


@dataclass
class Plan:
    student: str
    assignment: str
    project_id: str
    username: str | None
    current_attempt_id: int
    current_no: int
    next_no: int
    resume: bool
    repo_name: str
    old_owner: str | None
    old_repo: str | None
    refusals: list[str]
    decision_message: str

    @property
    def allowed(self) -> bool:
        return not self.refusals


def plan_delivery(cur, student: str, assignment: str, *, force: bool, i_understand: bool,
                  resume: bool, repo_for: dict) -> Plan:
    """Read-only. Everything that could make the delivery wrong is a refusal here."""
    cur.execute("SELECT s.github_username FROM students s WHERE s.student_id = %s", (student,))
    row = cur.fetchone()
    if row is None:
        raise pr.PublishRefused(f"unknown student {student!r}")
    username = row[0]
    decision = na.decide(cur, student, assignment, force=False if resume else force)
    refusals: list[str] = []
    if "attempt_id" not in decision:
        raise pr.PublishRefused(decision["message"])
    current_id, current_no = decision["attempt_id"], decision["attempt_no"]
    next_no = decision["next_no"]

    if resume:
        # finish a delivery whose attempt row exists: the latest attempt must be open, number >= 2
        # and untouched (no graded commit) -- otherwise it is a student's real work, not a leftover.
        cur.execute("SELECT count(*) FROM test_results WHERE attempt_id = %s", (current_id,))
        if current_no < 2 or decision["frozen"] or cur.fetchone()[0] > 0:
            refusals.append(f"--resume: attempt {current_no} is not an undelivered attempt "
                            "(needs number >= 2, open, no graded commit)")
        next_no, current_no = current_no, current_no - 1
        cur.execute("SELECT attempt_id FROM attempts WHERE student_id = %s AND assignment_id = %s"
                    " AND attempt_no = %s", (student, assignment, current_no))
        prev = cur.fetchone()
        if prev is None:
            refusals.append(f"--resume: attempt {current_no} does not exist")
        else:
            current_id = prev[0]
    else:
        if force and not i_understand:
            refusals.append(
                "--force needs --i-understand: D-072's stale-attempt closure (attempts.closed_at) "
                "is missing, so the old attempt stays OPEN, and grade_collected lets an open "
                "attempt win over a frozen higher one")
        elif not decision["allowed"]:
            refusals.append(decision["message"])
    if is_placeholder_username(username):
        refusals.append(f"placeholder github_username {username!r}: nobody to invite or mention")
    old = repo_for.get((student, assignment))
    if old is None:
        refusals.append(f"no roster entry for {student}/{assignment}: the owner is unknown")
    project_id = decision["project_id"]
    return Plan(student, assignment, project_id, username, current_id, current_no, next_no,
                resume, delivery_repo_name(project_id, student, assignment, next_no),
                old[0] if old else None, old[1] if old else None, refusals, decision["message"])


def roster_apply_command(plan: Plan, owner: str) -> str:
    """The exact `scripts.roster_apply` command that records this delivery in the roster."""
    return (f"python -m scripts.roster_apply --student {plan.student} --assignment "
            f"{plan.assignment} --owner {owner} --repo {plan.repo_name} --yes")


def next_hint(plan: Plan, owner: str) -> str:
    """The "Next:" text of a delivery (D-105). It never suggests `grade_collected`: that runs the
    student's code on this PC unless VDEL_GRADING_SANDBOX=docker, and the scheduled task already
    grades with the sandbox it was registered with."""
    return ("\nNext: 1) record the new repo in the roster (without --yes it only shows the "
            "diff):\n"
            f"        {roster_apply_command(plan, owner)}\n"
            "      2) the scheduled task (\"VDEL hourly\") then collects and grades it. To check "
            "now:\n"
            f"        python -m scripts.run_cycle --dry-run --student {plan.student}\n"
            "      (a real run by hand: set VDEL_GRADING_SANDBOX=docker first; never run "
            "grade_collected outside the Docker sandbox)")


def _roster_lines(roster_path: Path, plan: Plan, owner: str) -> list[str]:
    text = roster_path.read_text(encoding="utf-8") if roster_path.exists() else ""
    cohort = "vdel-2026"
    row = {"assignment_id": plan.assignment, "owner": owner, "repo": plan.repo_name,
           "student_id": plan.student, "released_at": "<publish time>", "concepts": []}
    new_text, actions = pr.update_roster_text(
        text, student={"student_id": plan.student, "github_username": plan.username,
                       "cohort": cohort}, rows=[row])
    return actions + [f"      + {ln}" for ln in pr.added_lines(text, new_text)]


def run(*, student: str, assignment: str, apply: bool = False, force: bool = False,
        i_understand: bool = False, resume: bool = False, roster_path: Path | None = None,
        gh=None, remote_base: str | None = None, conn=None, out=print) -> int:
    """Exit codes: 0 done / dry-run, 1 a GitHub or publish step failed (see the message; use
    --resume), 2 refused."""
    roster_path = Path(roster_path) if roster_path else pr.ROSTER
    roster = load_roster(roster_path)
    repo_for = roster_repo_for(roster)
    own = conn is None
    if own:
        conn = db._open()
    try:
        cur = conn.cursor()
        try:
            plan = plan_delivery(cur, student, assignment, force=force,
                                 i_understand=i_understand, resume=resume, repo_for=repo_for)
        except pr.PublishRefused as exc:
            out(f"REFUSED: {exc}")
            return 2
        out(f"student={student} assignment={assignment}  current attempt {plan.current_no} -> "
            f"next {plan.next_no}   {'(--resume)' if resume else ''}")
        out(f"decision : {plan.decision_message}")
        out(f"new repo : {plan.old_owner}/{plan.repo_name}   (private)")
        for refusal in plan.refusals:
            out(f"  {'REFUSED' if apply else 'WOULD REFUSE'}: {refusal}")

        owner = plan.old_owner
        comment = delivery_comment(plan.username or "?", assignment, plan.current_no,
                                   plan.next_no, owner or "<owner>", plan.repo_name, None)
        if not apply:
            if any("placeholder" not in r for r in plan.refusals):
                out("\nDRY-RUN: refused for the reason above; nothing else is shown.")
                return 2
            _dry_run(conn, plan, roster_path, owner, force, resume, out)
            base = f"/repos/{owner}/{plan.repo_name}"
            out("\nGitHub calls a real run would make (after next_attempt and publish_repo, "
                "which create the repo and push):")
            if _is_owner(plan.username, owner):
                out(f"  (no invitation: {plan.username} owns the repository; GitHub refuses to "
                    "invite an owner)")
            else:
                out(f"  PUT  {base}/collaborators/{plan.username}   permission=push")
            out(f"  GET  /repos/{owner}/{plan.old_repo}/issues?state=all  (find "
                f"{issue_title(assignment, plan.current_no)!r}, unless the database knows it)")
            out(f"  GET  /repos/{owner}/{plan.old_repo}/issues/<n>/comments  (look for the marker)")
            out(f"  POST /repos/{owner}/{plan.old_repo}/issues/<n>/comments  (the text below)")
            out("\n" + comment)
            out("DRY-RUN: nothing was created, pushed, invited, commented or recorded.")
            return 0

        try:
            require_github_write(True)
        except GitHubWriteNotEnabled as exc:
            out(f"REFUSED: {exc}")
            return 2
        if plan.refusals:
            return 2
        return _apply(conn, cur, plan, roster_path, owner, force, gh, remote_base, out, own)
    finally:
        if own:
            conn.rollback()
            conn.close()


def _dry_run(conn, plan: Plan, roster_path: Path, owner: str | None, force: bool,
             resume: bool, out) -> None:
    out("\n--- next_attempt (rolled back) ---")
    if not resume:
        na.next_attempt(plan.student, plan.assignment, force=force, dry_run=True, conn=conn,
                        out=out)
    out("\n--- publish_repo (dry-run: renders inside a rolled-back savepoint) ---")
    try:
        pr.run(student=plan.student, attempt_no=plan.next_no, project=plan.project_id,
               repo_name=plan.repo_name, owner=owner, dry_run=True, update_roster=False,
               roster_path=roster_path, conn=conn, only_assignment=plan.assignment)
    except pr.PublishRefused as exc:
        out(f"  (publish dry-run refused: {exc})")
    out("\n--- roster rows to add by hand (config/roster.yaml is never edited here) ---")
    try:
        for line in _roster_lines(roster_path, plan, owner or "<owner>"):
            out(f"  {line}")
    except pr.PublishRefused as exc:
        out(f"  (cannot compute the roster lines: {exc})")
    out(next_hint(plan, owner or "<owner>"))


def _apply(conn, cur, plan: Plan, roster_path: Path, owner: str, force: bool, gh,
           remote_base: str | None, out, owned: bool) -> int:
    """`owned`: the connection was opened by `run` (production), so each step may commit and
    use its own connections; False means a caller's transaction (tests), which is joined and
    never committed or rolled back here."""
    shared = None if owned else conn
    try:
        gh = gh or pr.GitHub(pr._token())
        if not plan.resume:
            out("\n[1] next_attempt: recording the attempt")
            scratch = Path(tempfile.mkdtemp(prefix="vdel_deliver_"))
            try:
                result = na.next_attempt(plan.student, plan.assignment, force=force,
                                         dry_run=False, out_dir=scratch / "repo", out=out,
                                         conn=shared)
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
            if not result.get("wrote"):
                out("REFUSED by next_attempt; nothing else was done")
                return 2
        state = gh.repo_state(owner, plan.repo_name)
        if state == "has_commits":
            out(f"\n[2] publish_repo: {owner}/{plan.repo_name} already has commits; skipped")
        else:
            out("\n[2] publish_repo: creating the private repo and pushing")
            pr.run(student=plan.student, attempt_no=plan.next_no, project=plan.project_id,
                   repo_name=plan.repo_name, owner=owner, update_roster=False,
                   roster_path=roster_path, assume_yes=True, gh=gh, remote_base=remote_base,
                   only_assignment=plan.assignment, conn=shared,
                   next_hint="")             # printed once, at the end, by next_hint()
        if _is_owner(plan.username, owner):
            outcome = "not needed (the student owns the repository)"
        else:
            outcome = gh.invite_collaborator(owner, plan.repo_name, plan.username)
        out(f"\n[3] collaborator {plan.username}: {outcome}")
        if owned:
            conn.rollback()                # see the rows the steps above committed
        cur = conn.cursor()
        cur.execute("SELECT attempt_id FROM attempts WHERE student_id = %s AND assignment_id = %s"
                    " AND attempt_no = %s", (plan.student, plan.assignment, plan.next_no))
        new_id = cur.fetchone()[0]
        number = ensure_issue(cur, gh, plan.current_attempt_id, plan.old_owner, plan.old_repo,
                              issue_title(plan.assignment, plan.current_no),
                              f"@{plan.username} automated feedback for `{plan.assignment}`, "
                              f"attempt {plan.current_no}.")
        if owned:
            conn.commit()
        marker = delivery_marker(new_id)
        if any(marker in (c.get("body") or "")
               for c in gh.issue_comments(plan.old_owner, plan.old_repo, number)):
            out(f"\n[4] the delivery comment is already on {plan.old_repo}#{number}; skipped")
        else:
            body = delivery_comment(plan.username, plan.assignment, plan.current_no, plan.next_no,
                                    owner, plan.repo_name, new_id)
            gh.create_issue_comment(plan.old_owner, plan.old_repo, number, body)
            out(f"\n[4] comment added to {plan.old_repo}#{number}")
        out("\n[5] roster rows to add by hand (config/roster.yaml was NOT edited):")
        for line in _roster_lines(roster_path, plan, owner):
            out(f"  {line}")
        out(next_hint(plan, owner))
        out("\nDONE.")
        return 0
    except (pr.GitHubHTTPError, pr.PublishRefused) as exc:
        out(f"\nFAILED: {exc}\nThe attempt row may already exist; finish with the same command "
            "plus --resume. Every GitHub step is idempotent.")
        return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--student", required=True)
    ap.add_argument("--assignment", required=True)
    ap.add_argument("--roster", type=Path, default=None,
                    help="roster file (default config/roster.yaml)")
    ap.add_argument("--force", action="store_true", help="start the next attempt although the "
                    "current one is not frozen (needs --i-understand)")
    ap.add_argument("--i-understand", action="store_true", dest="i_understand",
                    help="acknowledge that --force leaves the old attempt open (D-072)")
    ap.add_argument("--resume", action="store_true",
                    help="finish a delivery whose attempt row already exists")
    ap.add_argument("--apply", action="store_true",
                    help=f"really write (also needs {GITHUB_WRITE_ENV_VAR}=1 in the environment)")
    args = ap.parse_args(argv)
    return run(student=args.student, assignment=args.assignment, apply=args.apply,
               force=args.force, i_understand=args.i_understand, resume=args.resume,
               roster_path=args.roster)


if __name__ == "__main__":
    sys.exit(main())
