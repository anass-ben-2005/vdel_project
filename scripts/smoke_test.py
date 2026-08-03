"""The crudest possible regression net: does the DB connect, does the schema exist,
and does the one invariant the whole design rests on actually hold?

Run:  python -m scripts.smoke_test
"""

from __future__ import annotations

import sys

from system import db

EXPECTED_TABLES = [
    "students",
    "assignments",
    "raw_commits",
    "raw_workflow_runs",
    "learner_features",
    "kt_params",
    "items",
    "traces",
    "sessions",
    "learner_profile",
]


def check_tables(cur) -> list[str]:
    """Return the list of failures (empty means pass)."""
    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    present = {row[0] for row in cur.fetchall()}
    missing = [t for t in EXPECTED_TABLES if t not in present]
    return [f"missing table: {t}" for t in missing]


def check_traces_append_only(cur) -> list[str]:
    """traces must reject UPDATE and DELETE (invariant 1).

    Done inside a transaction that is rolled back, so the smoke test leaves no rows
    behind and can run against a populated database.
    """
    cur.execute(
        "INSERT INTO students (student_id, github_username, cohort)"
        " VALUES ('_smoke', '_smoke', '_smoke') RETURNING student_id"
    )
    cur.execute(
        "INSERT INTO traces (student_id, actor, kind, payload)"
        " VALUES ('_smoke', 'system', 'error_event', '{\"v\": 1}') RETURNING trace_id"
    )
    trace_id = cur.fetchone()[0]

    failures = []

    cur.execute("UPDATE traces SET payload = '{\"v\": 2}' WHERE trace_id = %s", (trace_id,))
    cur.execute("SELECT payload FROM traces WHERE trace_id = %s", (trace_id,))
    if cur.fetchone()[0] != {"v": 1}:
        failures.append("traces accepted an UPDATE (invariant 1 violated)")

    cur.execute("DELETE FROM traces WHERE trace_id = %s", (trace_id,))
    cur.execute("SELECT count(*) FROM traces WHERE trace_id = %s", (trace_id,))
    if cur.fetchone()[0] != 1:
        failures.append("traces accepted a DELETE (invariant 1 violated)")

    return failures


def main() -> int:
    failures: list[str] = []
    with db.dry_run_cursor() as cur:  # never commits
        failures += check_tables(cur)
        if not failures:
            failures += check_traces_append_only(cur)

    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        return 1

    print(f"OK    {len(EXPECTED_TABLES)} tables present")
    print("OK    traces rejects UPDATE and DELETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
