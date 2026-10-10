"""scripts/baseline.py -- a READ-ONLY snapshot of the facts every change must leave alone.

Run it before and after a change and diff the two outputs; identical output is the evidence
that the change did not touch real data. It prints, for the database PG_DSN points at:

  - attempts: count and a content hash (student, assignment, attempt_no, variant, commit,
    tests_passed -- the same definition used in earlier baselines, so numbers compare)
  - variants: count;  projects: master_version per project
  - traces: count and highest trace_id (traces are append-only, so a change here is real)
  - raw_commits / raw_workflow_runs: counts, and the failure/success split of the runs
  - learner_features: every row, with its formula_ver
  - mastery per concept for one student (default anas): p_mastery and n
  - the Beat 2 variant ids (weather_etl_extract, attempt 1, per student)
  - --full: a row-count + content hash of EVERY table, for a change that could touch any

Read-only by construction: the session is opened `readonly=True`, so Postgres itself rejects
any write, and the transaction is rolled back at the end. It uses `system.db._open`, the same
door as everything else, so it reports on the real database unless you point PG_DSN elsewhere
(the first line says which database it connected to).

Run:  python -m scripts.baseline [--student anas] [--full]
"""

from __future__ import annotations

import argparse
import sys

from system import db

# The same definition earlier baselines used for the attempts hash, so a number printed here
# can be compared with one taken before this script existed.
_ATTEMPTS_HASH = (
    "SELECT count(*), md5(coalesce(string_agg(student_id || assignment_id || attempt_no"
    " || variant_id || coalesce(commit_sha, '') || coalesce(tests_passed::text, ''), ','"
    " ORDER BY student_id, assignment_id, attempt_no), '')) FROM attempts"
)


def snapshot(cur, student: str = "anas", *, full: bool = False) -> list[str]:
    """The snapshot as lines of text. `cur` should be on a read-only session."""
    out: list[str] = []

    def one(sql, params=()):
        cur.execute(sql, params)
        return cur.fetchone()

    def many(sql, params=()):
        cur.execute(sql, params)
        return cur.fetchall()

    out.append(f"database          : {one('SELECT current_database()')[0]}")

    n, h = one(_ATTEMPTS_HASH)
    out.append(f"attempts          : {n} rows, hash {h}")
    out.append(f"variants          : {one('SELECT count(*) FROM variants')[0]}")
    for project_id, master in many("SELECT project_id, master_version FROM projects"
                                   " ORDER BY project_id"):
        out.append(f"master_version    : {project_id} {master}")

    n, top = one("SELECT count(*), coalesce(max(trace_id), 0) FROM traces")
    out.append(f"traces            : {n} (highest trace_id {top})")
    out.append(f"raw_commits       : {one('SELECT count(*) FROM raw_commits')[0]}")
    total, fail, ok = one("SELECT count(*), count(*) FILTER (WHERE conclusion = 'failure'),"
                          " count(*) FILTER (WHERE conclusion = 'success')"
                          " FROM raw_workflow_runs")
    out.append(f"raw_workflow_runs : {total} ({fail} failure, {ok} success)")

    rows = many("SELECT student_id, computed_at, formula_ver FROM learner_features"
                " ORDER BY student_id, computed_at")
    out.append(f"learner_features  : {len(rows)} rows")
    for sid, at, ver in rows:
        out.append(f"  {sid:<12} {at:%Y-%m-%d %H:%M:%S%z} {ver}")

    mastery = one("SELECT mastery FROM learner_profile WHERE student_id = %s", (student,))
    out.append(f"mastery ({student})")
    if mastery is None:
        out.append("  (no learner_profile row)")
    else:
        for concept, state in sorted(mastery[0].items()):
            out.append(f"  {concept:<22} p={state.get('p_mastery')} n={state.get('n')}")

    ids = many("SELECT student_id, left(variant_id, 12) FROM attempts"
               " WHERE assignment_id = 'weather_etl_extract' AND attempt_no = 1"
               " ORDER BY student_id")
    out.append("beat 2 variant ids: " + (", ".join(f"{s}={v}" for s, v in ids) or "(none)"))

    if full:
        out.append("all tables (rows, content hash):")
        for (table,) in many("SELECT table_name FROM information_schema.tables"
                             " WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
                             " ORDER BY 1"):
            n, h = one("SELECT count(*), md5(coalesce(string_agg(x::text, '|' ORDER BY x::text),"
                       f" '')) FROM \"{table}\" x")
            out.append(f"  {table:<20} {n:>5}  {h}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--student", default="anas", help="whose mastery to print")
    ap.add_argument("--full", action="store_true", help="also fingerprint every table")
    args = ap.parse_args(argv)

    conn = db._open()
    try:
        conn.set_session(readonly=True)          # Postgres itself now refuses any write
        with conn.cursor() as cur:
            print("\n".join(snapshot(cur, args.student, full=args.full)))
    finally:
        conn.rollback()
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
