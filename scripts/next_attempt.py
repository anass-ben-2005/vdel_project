"""scripts/next_attempt.py -- start the next attempt of ONE assignment for ONE student.

    python -m scripts.next_attempt --student X --assignment Y [--force] [--dry-run]
                                   [--out-dir DIR]

The rule (D-072): a new attempt is allowed only when the student's CURRENT attempt (the
highest attempt_no) is FROZEN -- its hidden tests reached 100% on a pushed commit
(test_runner._maybe_freeze) -- or when the instructor passes `--force`. Otherwise it refuses,
says why, and writes nothing.

When allowed it (1) computes the next variant with `select_variant` from the student's
CURRENT mastery (the profile), (2) renders it into a scratch directory by reusing
`render_student_repo(..., only_assignment=Y)`, and (3) records the attempt row (and the
variant row) in the same transaction. Nothing goes to GitHub: publishing the rendered tree is
a separate, explicit step (scripts/publish_repo.py).

`--dry-run` runs the same code inside a transaction that is rolled back, so it prints the real
variant and the real file list and leaves no row behind (the trick publish_repo --dry-run uses).

HOW A STALE OPEN ATTEMPT IS CLOSED when the next one starts (design note, D-072). It is NOT
closed in v1: `attempts` has no column for it, and adding one is a schema change. With `--force`
the old attempt keeps `submitted_at IS NULL` and `commit_sha IS NULL`; it is *superseded by
number* (a higher attempt_no exists for the same student and assignment). One interaction to
know about: `grade_collected._target_attempts` lets an OPEN attempt beat a FROZEN one regardless
of number, so a stale open attempt 1 would keep receiving commits that belong to a frozen
attempt 2. The proposed fix, listed under "later" and not built tonight, is an additive nullable
`attempts.closed_at` / `closed_reason` ('superseded' | 'abandoned') written here at `--force`
time and honoured by `_target_attempts`. Until then `--force` on an open attempt prints this
warning and leaves the old row exactly as it was (the safest direction: no existing row changes).

Exit codes: 0 allowed (or dry-run allowed); 1 refused; 2 nothing to start from.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from scripts.render_student_repo import render_student_repo
from system import db

EXIT_OK, EXIT_REFUSED, EXIT_NO_ATTEMPT = 0, 1, 2


def decide(cur, student_id: str, assignment_id: str, force: bool) -> dict:
    """Read-only: may the next attempt start? Returns a dict with `allowed` and `message`."""
    cur.execute(
        "SELECT attempt_id, project_id, attempt_no, submitted_at, commit_sha FROM attempts"
        " WHERE student_id = %s AND assignment_id = %s ORDER BY attempt_no DESC LIMIT 1",
        (student_id, assignment_id))
    row = cur.fetchone()
    if row is None:
        return {"allowed": False, "code": EXIT_NO_ATTEMPT,
                "message": f"no attempt exists for {student_id}/{assignment_id}: the first "
                           "attempt is created by render_student_repo / publish_repo"}
    attempt_id, project_id, attempt_no, submitted_at, commit_sha = row
    info = {"attempt_id": attempt_id, "project_id": project_id, "attempt_no": attempt_no,
            "next_no": attempt_no + 1, "frozen": submitted_at is not None,
            "commit_sha": commit_sha}
    if submitted_at is not None:
        return {**info, "allowed": True, "forced": False,
                "message": f"attempt {attempt_no} is frozen"
                           f" (commit {str(commit_sha)[:10]}): attempt {attempt_no + 1} may start"}
    if force:
        return {**info, "allowed": True, "forced": True,
                "message": f"FORCED: attempt {attempt_no} is still open (its hidden tests never "
                           "reached 100%). It is left as it is -- superseded by number, not "
                           "closed (see this script's docstring: a stale open attempt still "
                           "wins in grade_collected until a closed_at column exists)"}
    return {**info, "allowed": False, "code": EXIT_REFUSED,
            "message": f"REFUSED: attempt {attempt_no} of {student_id}/{assignment_id} is "
                       "still open (not frozen: its hidden tests have not reached 100%). The "
                       "instructor can pass --force"}


def next_attempt(student_id: str, assignment_id: str, *, force: bool = False,
                 dry_run: bool = False, out_dir: str | Path | None = None, conn=None,
                 out=print) -> dict:
    """Decide, and if allowed render + record. `conn`: a caller's transaction (tests); it is
    never committed here, and a dry-run inside it is undone with a savepoint."""
    own = conn is None
    if own:
        conn = db._open()
    cur = conn.cursor()
    scratch = None
    try:
        decision = decide(cur, student_id, assignment_id, force)
        out(decision["message"])
        if not decision["allowed"]:
            return {**decision, "wrote": False}

        if out_dir is None or dry_run:       # a dry-run never writes into a chosen directory
            scratch = Path(tempfile.mkdtemp(prefix="vdel_next_attempt_"))
            target = scratch / "repo"
        else:
            target = Path(out_dir)
        cur.execute("SAVEPOINT next_attempt")
        rendered = render_student_repo(
            decision["project_id"], student_id, decision["next_no"], target, conn=conn,
            only_assignment=assignment_id)
        cur.execute(
            "SELECT a.attempt_id, a.variant_id, v.gap_ids FROM attempts a"
            " JOIN variants v USING (variant_id)"
            " WHERE a.student_id = %s AND a.assignment_id = %s AND a.attempt_no = %s",
            (student_id, assignment_id, decision["next_no"]))
        new_attempt_id, variant_id, gap_ids = cur.fetchone()
        files = sorted(p.relative_to(target).as_posix() for p in target.rglob("*")
                       if p.is_file())
        out(f"next attempt {decision['next_no']}: variant {variant_id[:12]}, hidden gaps "
            f"{', '.join(gap_ids)}")
        out(f"rendered {len(files)} file(s) into {target}"
            + ("  (dry-run: removed again)" if dry_run else ""))
        for f in files:
            out(f"    {f}")

        if dry_run:
            cur.execute("ROLLBACK TO SAVEPOINT next_attempt")
            out("DRY-RUN: nothing recorded (the attempt and variant rows were rolled back)")
        else:
            cur.execute("RELEASE SAVEPOINT next_attempt")
            if own:
                conn.commit()
            out(f"recorded attempt_id={new_attempt_id} (student {student_id}, "
                f"{assignment_id}, attempt_no={decision['next_no']})")
        return {**decision, "wrote": not dry_run, "variant_id": variant_id,
                "gap_ids": list(gap_ids), "files": files, "rendered": rendered,
                "attempt_id": None if dry_run else new_attempt_id,
                "out_dir": str(target)}
    except Exception:
        if own:
            conn.rollback()
        raise
    finally:
        if own:
            conn.close()
        if scratch is not None and dry_run:  # a real run keeps its scratch dir: it IS the output
            shutil.rmtree(scratch, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--student", required=True)
    parser.add_argument("--assignment", required=True)
    parser.add_argument("--force", action="store_true",
                        help="instructor override: start even if the current attempt is open")
    parser.add_argument("--dry-run", action="store_true",
                        help="render in a rolled-back transaction; record nothing")
    parser.add_argument("--out-dir", default=None,
                        help="where to render (default: a scratch dir, kept unless --dry-run)")
    args = parser.parse_args(argv)
    result = next_attempt(args.student, args.assignment, force=args.force,
                          dry_run=args.dry_run, out_dir=args.out_dir)
    if result["allowed"]:
        return EXIT_OK
    return result.get("code", EXIT_REFUSED)


if __name__ == "__main__":
    sys.exit(main())
