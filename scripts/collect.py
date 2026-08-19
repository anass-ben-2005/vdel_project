"""Run the GitHub collector against every repo in config/roster.yaml.

Prints the API-call counters, which is what makes BUILD_PLAN 1.4 ("confirm the second
run makes almost no API calls") answerable with numbers rather than an impression.

FIXED (2026-08-19, spec-verifier): this used to import a `collect(token, targets)`
function that never existed anywhere in the repo -- collectors/collect_github.py only
ever defined collect_repo(conn, ...) / collect_all(conn, repos), matching
VDEL_Modules_1_2_Build.md Part D exactly (spec-verifier: MATCH). `dags/vdel_pipeline.py`
already wires roster.yaml to collect_all(conn, repos) correctly; this script now mirrors
that same pattern instead of the drifted one.

Run:  python -m scripts.collect
"""

from __future__ import annotations

import os
import sys

from collectors.collect_github import collect_all
from scripts.seed_data import load_roster
from system import db


def main() -> int:
    if not os.environ.get("GITHUB_TOKEN"):
        sys.exit("GITHUB_TOKEN is not set. See .env.example.")

    roster = load_roster()
    repos = [
        {"owner": a["owner"], "repo": a["repo"],
         "student_id": a["student_id"], "assignment_id": a["assignment_id"]}
        for a in roster.get("assignments", [])
    ]
    if not repos:
        sys.exit("No assignments in config/roster.yaml.")

    print(f"collecting {len(repos)} repo(s)")
    with db.connect() as conn:
        result = collect_all(conn, repos)

    print(f"\n{result['stats']}")

    if result["failed"]:
        print(f"\n{len(result['failed'])} repo(s) failed:")
        for f in result["failed"]:
            print(f"  {f['repo']}: {f['error']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
