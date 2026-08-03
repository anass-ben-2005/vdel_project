"""Seed reference data from config/roster.yaml, and derived data from the taxonomy.

Refuses to invent anything. If roster.yaml is missing it says so and stops, rather than
filling the Pace clock with plausible-looking timestamps nobody chose -- released_at is
the zero point for Learning Pace (sql/01, "start clock for Pace").

Run:  python -m scripts.seed_data
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from psycopg2.extras import execute_values

from config import concepts as taxonomy
from system import db

ROSTER = Path(__file__).resolve().parent.parent / "config" / "roster.yaml"


def load_roster() -> dict:
    if not ROSTER.exists():
        sys.exit(
            f"{ROSTER} not found.\n"
            "Copy config/roster.example.yaml to config/roster.yaml and fill in your real\n"
            "GitHub username, repos and start dates. There is no default: released_at\n"
            "starts the Learning Pace clock and a made-up date makes V4 meaningless."
        )
    return yaml.safe_load(ROSTER.read_text(encoding="utf-8")) or {}


def validate(roster: dict) -> list[str]:
    """Every problem at once, rather than one per run."""
    problems = []
    known = taxonomy.ids()

    for student in roster.get("students", []):
        if "CHANGE_ME" in str(list(student.values())):
            problems.append(f"student {student.get('student_id')}: CHANGE_ME left in place")

    student_ids = {s["student_id"] for s in roster.get("students", [])}
    for a in roster.get("assignments", []):
        aid = a.get("assignment_id")
        if "CHANGE_ME" in {aid, a.get("owner"), a.get("repo")}:
            problems.append(f"assignment {aid}: CHANGE_ME left in place")
        if a.get("student_id") not in student_ids:
            problems.append(f"assignment {aid}: unknown student_id {a.get('student_id')!r}")
        if not a.get("released_at"):
            problems.append(f"assignment {aid}: released_at is required (starts the Pace clock)")
        for cid in a.get("concepts") or []:
            if cid not in known:
                problems.append(f"assignment {aid}: {cid!r} is not in config/concepts.yaml")
    return problems


def main() -> int:
    roster = load_roster()
    if problems := validate(roster):
        for p in problems:
            print(f"  {p}")
        sys.exit(f"\n{len(problems)} problem(s) in {ROSTER}. Nothing was written.")

    concepts = taxonomy.load()

    with db.cursor() as cur:
        execute_values(
            cur,
            "INSERT INTO students (student_id, github_username, cohort) VALUES %s"
            " ON CONFLICT (student_id) DO UPDATE SET"
            "   github_username = EXCLUDED.github_username, cohort = EXCLUDED.cohort",
            [(s["student_id"], s["github_username"], s["cohort"]) for s in roster["students"]],
        )

        execute_values(
            cur,
            "INSERT INTO assignments (assignment_id, repo_prefix, released_at, due_at, concepts)"
            " VALUES %s ON CONFLICT (assignment_id) DO UPDATE SET"
            "   repo_prefix = EXCLUDED.repo_prefix, released_at = EXCLUDED.released_at,"
            "   due_at = EXCLUDED.due_at, concepts = EXCLUDED.concepts",
            [
                (a["assignment_id"], f"{a['owner']}/{a['repo']}", a["released_at"],
                 a.get("due_at"), a.get("concepts") or [])
                for a in roster["assignments"]
            ],
        )

        # kt_params: one cold-start row per concept. The column defaults in sql/03 are
        # the document's literature-grounded priors, so DEFAULT is used rather than
        # restating the numbers here -- one definition, not two.
        execute_values(
            cur,
            "INSERT INTO kt_params (param_set, concept_id) VALUES %s"
            " ON CONFLICT (param_set, concept_id) DO NOTHING",
            [("bkt_v1", cid) for cid in sorted(concepts)],
        )

        # items: the KT-IDEM item bank. One item per assignment, tagged with the
        # concepts that assignment tests, seeded at the taxonomy's cold-start
        # difficulty. difficulty/n_cohort_obs are then owned by the cohort estimator --
        # DO NOTHING so seeding never overwrites a learned value.
        items = []
        for a in roster["assignments"]:
            cids = a.get("concepts") or []
            if not cids:
                continue
            seed = sum(concepts[c].difficulty for c in cids) / len(cids)
            items.append((a["assignment_id"], cids, round(seed, 3), 0))
        if items:
            execute_values(
                cur,
                "INSERT INTO items (item_id, concept_ids, difficulty, n_cohort_obs)"
                " VALUES %s ON CONFLICT (item_id) DO NOTHING",
                items,
            )

    print(f"seeded {len(roster['students'])} student(s), "
          f"{len(roster['assignments'])} assignment(s), {len(concepts)} concepts, "
          f"{len(items)} item(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
