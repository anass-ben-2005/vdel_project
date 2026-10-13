"""scripts/code_agent_report.py -- the stored Code Agent verdicts, read-only (D-104).

    python -m scripts.code_agent_report [--student X] [--limit N] [--rejected | --accepted]

UNMEASURED JUDGE, INTERNAL USE ONLY, NEVER SHOWN TO STUDENTS. The Code Agent has not been measured
against labels on `weather_etl` (there are none), its score `llm_correctness_opinion` is the
model's reading of the code and not a test result (D-036), and no feature, mastery value, flag or
posted text reads a verdict (D-103). This report exists so a human can look at what it said, next
to what the tests said, and decide whether it is worth anything. Do not paste it to a student, do
not post it, do not average it.

One row per stored `code_agent`/`verdict` trace, newest first: the trace, the student, the attempt
and commit (the verdicts written before D-103 have neither: shown as `-`), the assignment, the
score per criterion (`-` where the assignment does not use that criterion; the first score is the
judge's opinion about correctness), `rejected` (any evidence failure) and the tests of that commit.
A row is MARKED `tests pass, approach <= 2` when every check of that commit passed and the judge
scored the approach 2 or lower: working code the judge finds weak. Those rows are the ones worth
reading first, and also the first place to look for a judge that is wrong.

Read-only by construction: the session is opened `readonly=True`, so Postgres itself refuses any
write, and it is rolled back at the end. No LLM, no network. It uses `system.db._open`, like
everything else, so it reports on the database `PG_DSN` points at (the first line says which).
"""
from __future__ import annotations

import argparse
import sys

from system import db

LABEL = "UNMEASURED JUDGE, INTERNAL USE ONLY, NEVER SHOWN TO STUDENTS"
MARK = "tests pass, approach <= 2"
SCORE_KEYS = (("correctness*", "llm_correctness_opinion"), ("approach", "approach"),
              ("readability", "readability"), ("idiomatic", "idiomatic"))


def _score(scores: dict, key: str) -> str:
    value = (scores or {}).get(key)
    return "-" if value is None else str(value)


def _tests(cur, attempt_id, commit_sha) -> tuple[int, int] | None:
    """(passed, total) of the checks the commit was graded on, or None if the verdict names no
    commit or the commit has no result rows. Tooling rows are not checks (status 'tooling')."""
    if attempt_id is None or not commit_sha:
        return None
    cur.execute("SELECT count(*) FILTER (WHERE passed), count(*) FROM test_results"
                " WHERE attempt_id = %s AND commit_sha = %s AND status <> 'tooling'",
                (int(attempt_id), commit_sha))
    passed, total = cur.fetchone()
    return (passed, total) if total else None


def _approach_note(payload: dict) -> str | None:
    """The judge's first quote and reason for the approach score, shortened. Internal use only."""
    items = ((payload.get("evidence") or {}).get("approach") or [])
    if not items or not isinstance(items[0], dict):
        return None
    quote, why = str(items[0].get("quote", "")).strip(), str(items[0].get("why", "")).strip()
    return f"{quote[:80]!r}: {why[:140]}" if (quote or why) else None


def rows(cur, *, student: str | None = None, limit: int = 50,
         rejected: bool | None = None) -> list[dict]:
    """The report rows, newest first. `rejected`: True/False to filter, None for all."""
    where, args = ["actor = 'code_agent'", "kind = 'verdict'"], []
    if student:
        where.append("student_id = %s")
        args.append(student)
    cur.execute("SELECT trace_id, ts, student_id, assignment_id, payload FROM traces WHERE "
                + " AND ".join(where) + " ORDER BY trace_id DESC", tuple(args))
    out = []
    for trace_id, ts, student_id, assignment_id, payload in cur.fetchall():
        is_rejected = payload.get("rejected")
        if rejected is not None and bool(is_rejected) is not rejected:
            continue
        attempt_id, sha = payload.get("attempt_id"), payload.get("commit_sha")
        tests = _tests(cur, attempt_id, sha)
        scores = payload.get("scores") or {}
        approach = scores.get("approach")
        all_pass = tests is not None and tests[1] > 0 and tests[0] == tests[1]
        out.append({
            "trace_id": trace_id, "ts": ts, "student": student_id, "assignment": assignment_id,
            "attempt_id": attempt_id, "commit": (sha or "")[:10] or None, "scores": scores,
            "rejected": is_rejected, "tests": tests,
            "prompt_version": payload.get("prompt_version"),
            "model": payload.get("model"),
            "approach_note": _approach_note(payload),
            "marked": bool(all_pass and approach is not None and approach <= 2),
        })
        if len(out) >= limit:
            break
    return out


def render(report_rows: list[dict], database: str) -> list[str]:
    lines = [f"*** {LABEL} ***", f"database: {database}   rows: {len(report_rows)}", ""]
    header = (f"{'trace':>7}  {'student':<12}{'attempt':>8}  {'commit':<11}{'assignment':<22}"
              + "".join(f"{name:>13}" for name, _ in SCORE_KEYS)
              + f"  {'rejected':<9}{'tests':<9}mark")
    lines += [header, "-" * len(header)]
    for r in report_rows:
        tests = "-" if r["tests"] is None else f"{r['tests'][0]}/{r['tests'][1]}"
        rejected = "-" if r["rejected"] is None else str(bool(r["rejected"])).lower()
        lines.append(
            f"{r['trace_id']:>7}  {r['student']:<12}{r['attempt_id'] or '-'!s:>8}  "
            f"{r['commit'] or '-'!s:<11}{r['assignment'] or '-'!s:<22}"
            + "".join(f"{_score(r['scores'], key):>13}" for _, key in SCORE_KEYS)
            + f"  {rejected:<9}{tests:<9}{MARK if r['marked'] else ''}")
    lines += ["", "* correctness is the judge's OPINION (llm_correctness_opinion), not a test "
                  "result.",
              f"mark '{MARK}': every check of the commit passed and the judge scored the approach "
              "2 or lower. '-' = not applicable / not recorded.",
              f"*** {LABEL} ***"]
    return lines


INSTRUCTOR_TITLE = "CORRECT BUT APPROACH <= 2"


def instructor_section(report_rows: list[dict]) -> list[str]:
    """For the instructor (D-109): working code the judge finds weak, one entry each, with the
    judge's own reason. Only rows where every check of the commit passed, the approach is 2 or lower
    AND no evidence failure was found; a rejected row is counted, not shown (its quotes did not
    check out). Still an unmeasured judge: a list of places to LOOK, not a mark for anyone."""
    marked = [r for r in report_rows if r["marked"]]
    shown = [r for r in marked if not r["rejected"]]
    lines = ["", f"=== {INSTRUCTOR_TITLE} (instructor only: working code the judge finds weak; "
                 "read these first) ==="]
    if not shown:
        lines.append("none" + (f" ({len(marked)} rejected row(s) not listed)" if marked else ""))
    for r in shown:
        s = r["scores"]
        lines.append(f"- trace {r['trace_id']}  {r['student']}  {r['assignment']}  attempt "
                     f"{r['attempt_id'] or '-'}  commit {r['commit'] or '-'}  approach "
                     f"{_score(s, 'approach')}  readability {_score(s, 'readability')}  tests "
                     f"{r['tests'][0]}/{r['tests'][1]}  prompt {r['prompt_version'] or '-'}")
        if r.get("approach_note"):
            lines.append(f"    judge: {r['approach_note']}")
    if shown and len(marked) > len(shown):
        lines.append(f"({len(marked) - len(shown)} rejected row(s) not listed)")
    lines.append(f"=== end of {INSTRUCTOR_TITLE} ===")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--student", help="only this student_id")
    parser.add_argument("--limit", type=int, default=50, help="most rows to show (default 50)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--rejected", action="store_true", help="only rejected verdicts")
    group.add_argument("--accepted", action="store_true", help="only verdicts with no failure")
    args = parser.parse_args(argv)
    conn = db._open()
    conn.set_session(readonly=True)
    try:
        cur = conn.cursor()
        cur.execute("SELECT current_database()")
        database = cur.fetchone()[0]
        flag = True if args.rejected else (False if args.accepted else None)
        found = rows(cur, student=args.student, limit=args.limit, rejected=flag)
        for line in render(found, database):
            print(line)
        for line in instructor_section(found):
            print(line)
    finally:
        conn.rollback()
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
