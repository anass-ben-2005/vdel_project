"""Run the GitHub collector against every repo in config/roster.yaml.

Prints the API-call counters, which is what makes BUILD_PLAN 1.4 answerable: run once to
backfill, run again, and compare. The second run should make almost no detail calls.

Run:  python -m scripts.collect
"""

from __future__ import annotations

import os
import sys

from collectors.collect_github import collect
from scripts.seed_data import load_roster


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set. See .env.example.")

    roster = load_roster()
    targets = [
        (a["owner"], a["repo"], a["student_id"], a["assignment_id"])
        for a in roster.get("assignments", [])
    ]
    if not targets:
        sys.exit("No assignments in config/roster.yaml.")

    print(f"collecting {len(targets)} repo(s)")
    stats = collect(token, targets)
    print(f"\n{stats.summary()}")

    if stats.errors:
        print(f"\n{len(stats.errors)} repo(s) failed:")
        for message in stats.errors:
            print(f"  {message}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
