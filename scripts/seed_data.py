"""Seed reference data from config/roster.yaml, and derived data from the taxonomy.

Refuses to invent anything. If roster.yaml is missing it says so and stops, rather than
filling the Pace clock with plausible-looking timestamps nobody chose -- released_at is
the zero point for Learning Pace (sql/01, "start clock for Pace").

Run:  python -m scripts.seed_data
"""

from __future__ import annotations

import datetime as dt
import hashlib
import subprocess
import sys
from pathlib import Path

import yaml
from psycopg2.extras import execute_values

from assessment.gap_parser import parse_master
from config import concepts as taxonomy
from system import db

ROSTER = Path(__file__).resolve().parent.parent / "config" / "roster.yaml"

CURRICULUM_ROOT = Path(__file__).resolve().parent.parent / "curriculum" / "master"

# Fixed pipeline order, not alphabetical -- `seq` must reflect the DAG (extract before
# transform before load before quality), and alphabetical order would put load/quality
# before transform. Named explicitly per VDEL_REDESIGN.md's own extract/transform/load/
# quality structure, not discovered by globbing.
PIPELINE_STAGES = ("extract", "transform", "load", "quality")


def _tree_version(files: list[Path]) -> str:
    """A content-derived version identifier for `master_version`, built from real
    `git hash-object` blob hashes -- NOT `git rev-parse HEAD:<path>` of a committed tree,
    because `curriculum/` has no commit yet (checked: `git status --short curriculum/`
    reports it `??`, untracked). `git hash-object` is read-only -- no staging, no commit,
    no working-tree side effect -- and gives a REAL git content hash per file, not an
    invented version string. sha1 of the sorted "filename:blobhash" pairs changes exactly
    when the files change, the same property a commit-tree sha would have, and this
    becomes directly replaceable by `git rev-parse HEAD:curriculum/master/<project>` the
    moment the directory is actually committed.
    """
    entries = []
    for path in sorted(files):
        blob_sha = subprocess.run(
            ["git", "hash-object", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        entries.append(f"{path.name}:{blob_sha}")
    return hashlib.sha1("\n".join(entries).encode()).hexdigest()


def seed_curriculum(cur, project_id: str) -> dict[str, int]:
    """Seed `projects`/`assignments`/`gaps` for one curriculum project from
    `curriculum/master/<project_id>/`. Independent of config/roster.yaml -- this is
    curriculum structure, not student data, so it must not be gated on a roster existing.

    Gaps are never hand-written: `assessment.gap_parser.parse_master` is the one and only
    source (D-007's argument -- one implementation, not a second one that could drift).
    `assignments.concepts[]` is the union of that file's own parsed gaps' concept_ids,
    never hand-authored, per VDEL_REDESIGN.md C7 ("tags live on the gap, not the
    assignment... assignments.concepts[] becomes the derived union").

    Placeholders flagged, not silently invented:
      - `released_at` is `now()` at seed time. Real value TBD when this project is
        actually assigned to a cohort -- deliberately NOT in the ON CONFLICT UPDATE
        clause below, so a re-run never moves an already-set Pace-clock zero point
        (config/roster.example.yaml's own rule, applied here).
      - `repo_prefix` is `curriculum/<project_id>` -- a real, traceable local path, not a
        fabricated GitHub owner/repo. This curriculum has not been distributed to any
        student repo yet; there is no real prefix to put here until it has.
      - `projects.title` is derived by formatting `project_id` ("weather_etl" ->
        "Weather Etl") -- a formatting choice, not invented content.

    Idempotent (invariant 9): every statement is INSERT ... ON CONFLICT DO UPDATE, keyed
    on each table's real primary key, so a second run updates rows in place rather than
    duplicating them.
    """
    # The master tree MIRRORS the student repo: <project_dir> is the repo root and
    # <project_dir>/<project_id>/ is the importable package inside it. That mirroring is
    # what lets one `file_path` value ('weather_etl/extract.py') be simultaneously correct
    # as a path under the master tree, a path in the rendered student repo, and the string
    # GitHub reports in a commit's `files[].filename` -- which is exactly what D-043's
    # per-file attribution matches assignments.file_path against. A flat master would need
    # three different spellings of the same file and a translation step between each.
    project_dir = CURRICULUM_ROOT / project_id
    package_dir = project_dir / project_id
    stage_files = [
        package_dir / f"{stage}.py" for stage in PIPELINE_STAGES
        if (package_dir / f"{stage}.py").exists()
    ]
    # _tree_version hashes each file's CONTENT keyed by its basename, so moving the stage
    # files into the package directory does not move master_version -- the gaps already
    # seeded against it keep their pinned line ranges (invariant 15).
    master_version = _tree_version(stage_files)

    cur.execute(
        "INSERT INTO projects (project_id, repo_prefix, title, released_at, master_version)"
        " VALUES (%(pid)s, %(prefix)s, %(title)s, now(), %(mv)s)"
        " ON CONFLICT (project_id) DO UPDATE SET"
        "   repo_prefix = EXCLUDED.repo_prefix, title = EXCLUDED.title,"
        "   master_version = EXCLUDED.master_version",
        {
            "pid": project_id,
            "prefix": f"curriculum/{project_id}",
            "title": project_id.replace("_", " ").title(),
            "mv": master_version,
        },
    )

    assignments_written = 0
    gaps_written = 0
    for seq, stage in enumerate(PIPELINE_STAGES, start=1):
        path = package_dir / f"{stage}.py"
        if not path.exists():
            continue

        assignment_id = f"{project_id}_{stage}"
        gaps = parse_master(path)   # raises GapParseError loudly on any bad marker
        concept_ids = sorted({c for gap in gaps for c in gap.concept_ids})

        cur.execute(
            "INSERT INTO assignments"
            "   (assignment_id, repo_prefix, released_at, concepts,"
            "    project_id, file_path, seq)"
            " VALUES (%(aid)s, %(prefix)s, now(), %(concepts)s, %(pid)s, %(fp)s, %(seq)s)"
            " ON CONFLICT (assignment_id) DO UPDATE SET"
            "   project_id = EXCLUDED.project_id, file_path = EXCLUDED.file_path,"
            "   seq = EXCLUDED.seq, concepts = EXCLUDED.concepts,"
            "   repo_prefix = EXCLUDED.repo_prefix",
            # released_at is deliberately absent from this UPDATE SET -- it starts the
            # Pace clock (CLAUDE.md 6) and must never be moved by a re-run once set.
            {
                "aid": assignment_id, "prefix": f"curriculum/{project_id}",
                "concepts": concept_ids, "pid": project_id,
                # Package-qualified, not a bare basename -- see the mirroring note above.
                "fp": f"{project_id}/{stage}.py", "seq": seq,
            },
        )
        assignments_written += 1

        for gap in gaps:
            cur.execute(
                "INSERT INTO gaps"
                "   (gap_id, assignment_id, concept_ids, line_start, line_end,"
                "    instruction, difficulty, master_version)"
                " VALUES (%(gid)s, %(aid)s, %(concepts)s, %(ls)s, %(le)s,"
                "         %(instr)s, %(diff)s, %(mv)s)"
                " ON CONFLICT (gap_id) DO UPDATE SET"
                "   assignment_id = EXCLUDED.assignment_id,"
                "   concept_ids = EXCLUDED.concept_ids,"
                "   line_start = EXCLUDED.line_start, line_end = EXCLUDED.line_end,"
                "   instruction = EXCLUDED.instruction, difficulty = EXCLUDED.difficulty,"
                "   master_version = EXCLUDED.master_version",
                {
                    "gid": gap.gap_id, "aid": assignment_id,
                    "concepts": list(gap.concept_ids), "ls": gap.line_start,
                    "le": gap.line_end, "instr": gap.instruction,
                    "diff": gap.difficulty, "mv": master_version,
                },
            )
            gaps_written += 1

    return {
        "projects": 1, "assignments": assignments_written, "gaps": gaps_written,
        "master_version": master_version,
    }


def load_roster() -> dict:
    if not ROSTER.exists():
        sys.exit(
            f"{ROSTER} not found.\n"
            "Copy config/roster.example.yaml to config/roster.yaml and fill in your real\n"
            "GitHub username, repos and start dates. There is no default: released_at\n"
            "starts the Learning Pace clock and a made-up date makes V4 meaningless."
        )
    return yaml.safe_load(ROSTER.read_text(encoding="utf-8")) or {}


def _released_at_problems(aid: str, released_at) -> list[str]:
    """`released_at` must be a real timestamp, and this is the only place that is checked.

    Not just a truthiness check, which is what this used to be. `released_at` starts the
    Learning Pace clock (sql/01), and config/roster.example.yaml tells the author in as
    many words not to invent a date -- so the honest thing an author does when they don't
    yet know it is leave a note in the field. That note is a non-empty string, so it passed
    the old `if not a.get(...)` check, reached the INSERT, and surfaced as
    `psycopg2.errors.InvalidDatetimeFormat: invalid input syntax for type timestamp with
    time zone: "<first-commit timestamp, once pushed ...>"` -- a Postgres type error naming
    a column, several layers below the roster file the author actually needs to edit.

    Found by running the seeder rather than by reading it. PyYAML already parses a real
    ISO timestamp into a `datetime`, so "still a string here" is precisely the signal that
    what is in the file is prose, not a date. The whole point of `validate` is to report
    every problem at once against the source file; a check that lets one class of bad value
    through to the driver defeats that for the one field where it matters most.
    """
    if not released_at:
        return [f"assignment {aid}: released_at is required (starts the Pace clock)"]
    if isinstance(released_at, (dt.datetime, dt.date)):
        return []
    try:
        dt.datetime.fromisoformat(str(released_at).replace("Z", "+00:00"))
    except ValueError:
        return [
            f"assignment {aid}: released_at is not a timestamp -- got {released_at!r}. "
            "It starts the Pace clock, so it must be the real date the work began "
            "(first commit, or when the assignment was set). Leave the assignment out "
            "of roster.yaml until that date is known rather than writing a placeholder."
        ]
    return []


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
        problems.extend(_released_at_problems(aid, a.get("released_at")))
        for cid in a.get("concepts") or []:
            if cid not in known:
                problems.append(f"assignment {aid}: {cid!r} is not in config/concepts.yaml")
    return problems


def main() -> int:
    # Curriculum seeding runs in its OWN transaction, before roster loading, and does not
    # depend on config/roster.yaml existing -- projects/assignments/gaps are curriculum
    # structure, not student data. Committed here (db.cursor()'s own context manager
    # commits on a clean exit) so a later sys.exit() from a missing/invalid roster cannot
    # undo it -- SystemExit is not an Exception, so db.connect()'s `except Exception:
    # rollback` would not even be the mechanism at risk, but keeping the two concerns in
    # separate transactions makes that irrelevant rather than merely untested.
    with db.cursor() as cur:
        result = seed_curriculum(cur, "weather_etl")
    print(f"seeded curriculum: {result['projects']} project(s), "
          f"{result['assignments']} assignment(s), {result['gaps']} gap(s) "
          f"(master_version {result['master_version'][:12]})")

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
