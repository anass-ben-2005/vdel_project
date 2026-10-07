"""scripts/normalise_test_names.py -- one-off migration for D-055.

Before D-055, `test_results.test_name` carried whatever JUnit classname pytest produced,
which included the directory the repo happened to be graded from
(`renders.anas_attempt1.tests.hidden.test_extract::t`). The new grader stores
`tests/hidden/test_extract.py::t` instead (`assessment.test_runner.normalise_test_name`).
Left alone, the old rows would never match the new names, so re-grading a commit that was
first graded before the fix -- `scripts/demo.py` re-grades `renders/anas_attempt1` every run
-- would insert a "new" copy of every row and log a second set of BKT observations.

What this does, per (attempt_id, commit_sha, normalised name) group:
  - one row, already normalised: left alone.
  - one row, old style: renamed in place.
  - several rows (the SAME test stored under two directory-dependent names -- exactly the
    duplication the bug caused): the most recently run row survives, renamed; the older
    duplicates are deleted. These are exact duplicates of one test's outcome, not distinct
    evidence.

What it does NOT do: touch `traces`. That table is append-only (invariant 1), and a
`test_result` trace's payload holds no test name, so the traces the bug already logged
cannot be identified, let alone corrected, from here. Their effect on mastery is recorded in
D-055 as a known, forward-only limit.

DRY RUN BY DEFAULT: prints exactly what would change and exits without writing. `--apply`
performs it in ONE transaction (deletes first, then renames, so the unique indexes in
sql/06 are never violated mid-way). Idempotent (invariant 9): a second `--apply` finds
nothing to do.
"""

from __future__ import annotations

import sys
from collections import defaultdict

from assessment.test_runner import TestRunnerError, normalise_test_name
from system import db


def plan(cur) -> dict:
    """Read every test_results row and decide its fate. Pure read."""
    cur.execute(
        "SELECT attempt_id, commit_sha, test_name, ran_at FROM test_results"
    )
    groups: dict[tuple, list[tuple]] = defaultdict(list)
    unrecognised = []
    for attempt_id, commit_sha, test_name, ran_at in cur.fetchall():
        try:
            target = normalise_test_name(test_name)
        except TestRunnerError:
            unrecognised.append((attempt_id, commit_sha, test_name))
            continue
        groups[(attempt_id, commit_sha, target)].append((test_name, ran_at))

    renames, deletes = [], []
    for (attempt_id, commit_sha, target), rows in groups.items():
        rows.sort(key=lambda r: r[1], reverse=True)       # newest first
        survivor_name = rows[0][0]
        for dup_name, _ in rows[1:]:
            deletes.append((attempt_id, commit_sha, dup_name))
        if survivor_name != target:
            renames.append((attempt_id, commit_sha, survivor_name, target))
    return {"renames": renames, "deletes": deletes, "unrecognised": unrecognised}


def _where_commit(commit_sha) -> tuple[str, tuple]:
    # `= NULL` is never true in SQL; the two partial unique indexes make NULL a real case.
    return ("commit_sha IS NULL", ()) if commit_sha is None else ("commit_sha = %s", (commit_sha,))


def apply(cur, p: dict) -> None:
    for attempt_id, commit_sha, name in p["deletes"]:
        clause, extra = _where_commit(commit_sha)
        cur.execute(
            f"DELETE FROM test_results WHERE attempt_id = %s AND test_name = %s AND {clause}",
            (attempt_id, name, *extra),
        )
    for attempt_id, commit_sha, old, new in p["renames"]:
        clause, extra = _where_commit(commit_sha)
        cur.execute(
            f"UPDATE test_results SET test_name = %s"
            f" WHERE attempt_id = %s AND test_name = %s AND {clause}",
            (new, attempt_id, old, *extra),
        )


def main(argv: list[str] | None = None) -> int:
    do_apply = "--apply" in (argv if argv is not None else sys.argv[1:])
    with db.connect() as conn, conn.cursor() as cur:
        p = plan(cur)
        print(f"rows to rename : {len(p['renames'])}")
        print(f"duplicate rows to delete (older copy of the same test): {len(p['deletes'])}")
        print(f"rows with an unrecognised name (left untouched): {len(p['unrecognised'])}")
        for attempt_id, commit_sha, old, new in p["renames"]:
            print(f"  RENAME attempt={attempt_id} commit={commit_sha}\n    {old}\n -> {new}")
        for attempt_id, commit_sha, name in p["deletes"]:
            print(f"  DELETE attempt={attempt_id} commit={commit_sha}  {name}")
        for attempt_id, commit_sha, name in p["unrecognised"]:
            print(f"  SKIP   attempt={attempt_id} commit={commit_sha}  {name}")
        if not do_apply:
            print("\nDRY RUN -- nothing written. Re-run with --apply to perform it.")
            conn.rollback()
            return 0
        apply(cur, p)
        print("\nAPPLIED in one transaction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
