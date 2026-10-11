"""scripts/agents_export_fixtures.py -- export graded commits as JSON fixtures for the agents tests.

    python -m scripts.agents_export_fixtures [--student student2 --student anas] [--out DIR]

READ-ONLY on the database PG_DSN points at (the session is opened `readonly=True`, so Postgres
itself refuses any write; rolled back at the end). It writes only files, by default under
`tests/fixtures/agents/real/`.

WHAT IS STORED, per graded commit (attempt, commit_sha): the status (ok / collection_error /
timeout / tooling), pass counts, each check's test name + gap id + EXCEPTION TYPE ONLY (D-077:
the stored assertion message can state what a hidden test expects, so it is never read into a
fixture), the `assessment.diagnose` output for the attempt, the gap -> concepts map, and the
student's current mastery slice for the concepts involved.

WHAT IS NEVER STORED: hidden test source, assertion messages, tracebacks, student code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from assessment.diagnose import diagnose
from scripts.post_feedback import exception_type
from system import db

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "agents" / "real"
DEFAULT_STUDENTS = ("student2", "anas")


def _status_of(statuses: set[str]) -> str:
    # same precedence as scripts/post_feedback.build_feedback
    if statuses == {"tooling"}:
        return "tooling"
    if "collection_error" in statuses:
        return "collection_error"
    if "timeout" in statuses:
        return "timeout"
    return "ok"


def export_commit(cur, attempt_id: int, commit_sha: str) -> dict | None:
    cur.execute("SELECT student_id, assignment_id, project_id, attempt_no FROM attempts"
                " WHERE attempt_id = %s", (attempt_id,))
    student_id, assignment_id, project_id, attempt_no = cur.fetchone()
    cur.execute("SELECT test_name, passed, message, gap_id, status FROM test_results"
                " WHERE attempt_id = %s AND commit_sha = %s ORDER BY test_name",
                (attempt_id, commit_sha))
    rows = cur.fetchall()
    if not rows:
        return None
    checks = [{"test_name": name, "passed": bool(passed), "gap_id": gap,
               "exception_type": None if passed else exception_type(message)}
              for name, passed, message, gap, status in rows if status != "tooling"]

    diag = diagnose(cur, attempt_id)
    gap_ids = sorted({c["gap_id"] for c in checks if c["gap_id"]}
                     | set(diag.recurrence_flags))
    gap_concepts: dict[str, list[str]] = {}
    if gap_ids:
        cur.execute("SELECT gap_id, concept_ids FROM gaps WHERE gap_id = ANY(%s)", (gap_ids,))
        gap_concepts = {g: list(c) for g, c in cur.fetchall()}
    concepts = sorted({c for cs in gap_concepts.values() for c in cs}
                      | ({diag.weakest_concept} if diag.weakest_concept else set()))

    cur.execute("SELECT mastery FROM learner_profile WHERE student_id = %s", (student_id,))
    row = cur.fetchone()
    mastery_all = (row[0] if row else {}) or {}
    mastery = {c: {"p_mastery": mastery_all[c].get("p_mastery"), "n": mastery_all[c].get("n")}
               for c in concepts if c in mastery_all}

    return {
        "fixture_version": 1,
        "origin": "real",
        "origin_note": ("exported read-only from the project database by "
                        "scripts/agents_export_fixtures.py; exception types only, no messages; "
                        "mastery is the student's profile AT EXPORT TIME, not at the commit"),
        "student_id": student_id,
        "attempt_id": attempt_id,
        "assignment_id": assignment_id,
        "project_id": project_id,
        "attempt_no": attempt_no,
        "commit_sha": commit_sha,
        "status": _status_of({r[4] for r in rows}),
        "passed": sum(1 for c in checks if c["passed"]),
        "total": len(checks),
        "checks": checks,
        "diagnosis": {
            "weakest_concept": diag.weakest_concept,
            "attempts_per_stage": diag.attempts_per_stage,
            "recurrence_flags": diag.recurrence_flags,
            "failing_tests": [{"test_name": f.test_name, "gap_id": f.gap_id}
                              for f in diag.failing_tests],
        },
        "gap_concepts": gap_concepts,
        "mastery": mastery,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--student", action="append", help="repeatable; default student2 and anas")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    students = tuple(args.student or DEFAULT_STUDENTS)

    args.out.mkdir(parents=True, exist_ok=True)
    conn = db._open()
    written = []
    try:
        conn.set_session(readonly=True)            # Postgres itself refuses any write
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT t.attempt_id, t.commit_sha, c.committed_at FROM test_results t"
                " JOIN attempts a USING (attempt_id) JOIN raw_commits c ON c.sha = t.commit_sha"
                " WHERE a.student_id = ANY(%s) AND t.commit_sha IS NOT NULL"
                " ORDER BY c.committed_at, t.commit_sha", (list(students),))
            todo = [(a, s) for a, s, _ in cur.fetchall()]
            for attempt_id, sha in todo:
                data = export_commit(cur, attempt_id, sha)
                if data is None:
                    continue
                name = (f"{data['student_id']}__{data['assignment_id']}__"
                        f"a{attempt_id}__{sha[:8]}__{data['status']}.json")
                (args.out / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                                             encoding="utf-8")
                written.append(name)
    finally:
        conn.rollback()
        conn.close()
    print("\n".join(written) or "nothing to export")
    return 0


if __name__ == "__main__":
    sys.exit(main())
