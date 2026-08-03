"""Seed reference data from config/roster.yaml, and derived data from the taxonomy.

Refuses to invent anything. If roster.yaml is missing it says so and stops, rather than
filling the Pace clock with plausible-looking timestamps nobody chose.

Run:  python -m scripts.seed_data
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from psycopg2.extras import execute_values

from config import concepts as taxonomy
from system import db
from variables.mastery import BKTParams

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
        if "CHANGE_ME" in str(student.values()):
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
    defaults = BKTParams()

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

        # Derived from the taxonomy, not invented: KT-IDEM reads item difficulty.
        execute_values(
            cur,
            "INSERT INTO items (concept_id, difficulty) VALUES %s"
            " ON CONFLICT (concept_id) DO UPDATE SET difficulty = EXCLUDED.difficulty",
            [(c.id, c.difficulty) for c in concepts.values()],
        )

        execute_values(
            cur,
            "INSERT INTO kt_params (param_set, concept_id, p_l0, p_t, p_guess, p_slip)"
            " VALUES %s ON CONFLICT (param_set, concept_id) DO NOTHING",
            [
                ("bkt_v1", c.id, defaults.p_l0, defaults.p_t, defaults.p_guess, defaults.p_slip)
                for c in concepts.values()
            ],
        )

    print(f"seeded {len(roster['students'])} student(s), "
          f"{len(roster['assignments'])} assignment(s), {len(concepts)} concepts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
