"""scripts/ab_report.py -- commits-to-pass per arm of the `--ab-llm` experiment, read-only (D-110).

    python -m scripts.ab_report [--student X]

For every failing commit that was assigned an arm (`agents/ab.py`), the outcome is how many
further graded pushes the student needed on that attempt until it froze (until all its hidden
checks passed):

  * the attempt is frozen -> commits_to_pass = the number of graded commits of that attempt pushed
    AFTER the assigned one, up to and including the commit that froze it; * the attempt is not
    frozen yet -> censored: the student has not passed so far, and the number of pushes since is
    shown, but it is not a commits-to-pass.

Per arm it prints the number of assigned commits, how many passed and how many are censored, and
the mean and median commits-to-pass among those that passed. That is all. It is DESCRIPTIVE: no
p-value, no confidence interval, no claim that one arm is better. The unit is the commit, one
attempt can sit in both arms, the exercise matters as much as the note, and the numbers will be
small (see agents/ab.py).

Read-only by construction: the session is opened `readonly=True`, so Postgres itself refuses any
write, and it is rolled back at the end. No LLM, no network.
"""
from __future__ import annotations

import argparse
import statistics
import sys

from system import db

LABEL = "DESCRIPTIVE ONLY: NOT A SIGNIFICANCE TEST, NOT A GRADE, NOT FOR STUDENTS"
CAVEATS = (
    "The unit is the commit: one attempt can be in both arms, so a student may see both kinds "
    "of note.",
    "Commits-to-pass depends on the exercise at least as much as on the note; compare like with "
    "like.",
    "With few students every difference here is within noise. Do not decide on it.",
)


def assigned_commits(cur, student: str | None = None) -> list[dict]:
    """Every assigned commit with what is needed to score it. Read-only."""
    sql = ("SELECT t.student_id, (t.payload->>'attempt_id')::bigint, t.payload->>'commit_sha',"
           "       t.payload->>'arm', c.committed_at, a.commit_sha, a.submitted_at"
           " FROM traces t JOIN raw_commits c ON c.sha = t.payload->>'commit_sha'"
           " JOIN attempts a ON a.attempt_id = (t.payload->>'attempt_id')::bigint"
           " WHERE t.actor = 'coach' AND t.kind = 'intervention'"
           " AND t.payload->>'agent' = 'ab_assignment'")
    args: tuple = ()
    if student:
        sql += " AND t.student_id = %s"
        args = (student,)
    cur.execute(sql + " ORDER BY t.trace_id", args)
    out = []
    for student_id, attempt_id, sha, arm, committed_at, frozen_sha, submitted_at in cur.fetchall():
        cur.execute("SELECT DISTINCT t.commit_sha, c.committed_at FROM test_results t"
                    " JOIN raw_commits c ON c.sha = t.commit_sha"
                    " WHERE t.attempt_id = %s AND t.status = 'ok' ORDER BY c.committed_at",
                    (attempt_id,))
        graded = cur.fetchall()
        later = [(s, at) for s, at in graded if at > committed_at]
        frozen = frozen_sha is not None and submitted_at is not None
        to_pass = None
        if frozen:
            freeze_at = next((at for s, at in graded if s == frozen_sha), None)
            if freeze_at is not None and freeze_at > committed_at:
                to_pass = sum(1 for _, at in later if at <= freeze_at)
        out.append({"student": student_id, "attempt_id": attempt_id, "commit": sha, "arm": arm,
                    "commits_to_pass": to_pass, "pushes_since": len(later)})
    return out


def summarise(rows: list[dict]) -> dict[str, dict]:
    """Per arm: n, passed, censored, mean and median commits-to-pass among those that passed."""
    out: dict[str, dict] = {}
    for arm in ("llm", "control"):
        mine = [r for r in rows if r["arm"] == arm]
        passed = [r["commits_to_pass"] for r in mine if r["commits_to_pass"] is not None]
        out[arm] = {
            "n": len(mine), "passed": len(passed), "censored": len(mine) - len(passed),
            "mean": statistics.fmean(passed) if passed else None,
            "median": statistics.median(passed) if passed else None,
            "attempts": len({r["attempt_id"] for r in mine}),
        }
    return out


def render(rows: list[dict], database: str) -> list[str]:
    lines = [f"*** {LABEL} ***", f"database: {database}   assigned commits: {len(rows)}", ""]
    header = (f"{'arm':<9}{'commits':>8}{'attempts':>9}{'passed':>8}{'censored':>9}"
              f"{'mean':>8}{'median':>8}")
    lines += [header, "-" * len(header)]
    for arm, s in summarise(rows).items():
        mean = "-" if s["mean"] is None else f"{s['mean']:.2f}"
        median = "-" if s["median"] is None else f"{s['median']:g}"
        lines.append(f"{arm:<9}{s['n']:>8}{s['attempts']:>9}{s['passed']:>8}{s['censored']:>9}"
                     f"{mean:>8}{median:>8}")
    lines += ["", "mean / median: commits-to-pass among the commits whose attempt has since "
                  "frozen. "
                  "'censored': the attempt has not frozen yet.", ""]
    lines += [f"- {c}" for c in CAVEATS]
    lines += [f"*** {LABEL} ***"]
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--student", help="only this student_id")
    args = parser.parse_args(argv)
    conn = db._open()
    conn.set_session(readonly=True)
    try:
        cur = conn.cursor()
        cur.execute("SELECT current_database()")
        database = cur.fetchone()[0]
        for line in render(assigned_commits(cur, args.student), database):
            print(line)
    finally:
        conn.rollback()
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
