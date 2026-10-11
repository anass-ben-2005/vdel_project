"""scripts/render_student_repo.py -- materialise one student's variant as a real repo.

VDEL_REDESIGN.md 8.3: "A generated ASSIGNMENT.md per attempt listing each gap, its file,
its line, and what to implement" + "Visible smoke tests the student can run locally...
while hidden tests stay hidden." This is the delivery step: gap_parser (D-035) turns a
master file into gap specs; gap_generator (C2/C3) picks, deterministically, which gaps
THIS student's THIS attempt hides; this module writes the resulting file tree to disk.

Persists into `variants` (ON CONFLICT DO NOTHING -- variant_id is already a content hash,
so an existing row with the same id already has identical content) and `attempts` (ON
CONFLICT on the table's own UNIQUE (student_id, assignment_id, attempt_no), DO UPDATE
guarded to only fire while the attempt is still unsubmitted -- see
`_upsert_attempt`'s docstring). `commit_sha`/`submitted_at` are written as NULL: nothing
has been pushed to GitHub for a curriculum attempt yet, and this project's own rule
(config/roster.example.yaml: no invented placeholder dates) forbids inventing either just
to satisfy a constraint -- sql/06 was revised to make both columns nullable for exactly
this reason. Real values land later, once collect_github has a matching raw_commits row.
"""

from __future__ import annotations

import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

from assessment.gap_generator import compute_seed, select_variant
from assessment.gap_parser import Gap, render_student_file
from memory.memory import Memory
from system import db

CURRICULUM_ROOT = Path(__file__).resolve().parent.parent / "curriculum" / "master"


@contextmanager
def _cursor(conn):
    """The caller's transaction when `conn` is given (never committed here), else the
    usual own-transaction `db.cursor()`. Exists so scripts/publish_repo.py --dry-run can
    render for real -- and show the real tree -- inside a transaction it then rolls back,
    instead of leaving a variants/attempts row behind for a repo that was never published."""
    if conn is None:
        with db.cursor() as cur:
            yield cur
    else:
        with conn.cursor() as cur:
            yield cur


def _load_project(cur, project_id: str) -> dict:
    """Assignments and gaps for one project, straight from the DB (sql/06) -- the
    authoritative source for instruction text/line ranges/concepts, as opposed to
    re-parsing the master file a second time for that information."""
    cur.execute(
        "SELECT assignment_id, file_path, seq, master_version"
        " FROM assignments a JOIN projects p USING (project_id)"
        " WHERE a.project_id = %s ORDER BY seq",
        (project_id,),
    )
    assignment_rows = cur.fetchall()
    if not assignment_rows:
        raise ValueError(f"no assignments found for project_id={project_id!r}")

    assignments = []
    for assignment_id, file_path, seq, master_version in assignment_rows:
        cur.execute(
            "SELECT gap_id, concept_ids, line_start, line_end, instruction, difficulty"
            " FROM gaps WHERE assignment_id = %s ORDER BY gap_id",
            (assignment_id,),
        )
        gap_rows = cur.fetchall()
        # `body` is empty here, deliberately -- the `gaps` table does not store it (only
        # WHERE a gap is, not its literal text), and select_variant only ever reads
        # gap_id/concept_ids. Rendering re-derives real body text from the actual master
        # file text via render_student_file's own parse, never from these DB-sourced
        # placeholder Gap objects -- using one for the other would be a real, silent bug.
        gaps = [
            Gap(gap_id=gid, concept_ids=tuple(cids), line_start=ls, line_end=le,
                instruction=instr, difficulty=diff, body="")
            for gid, cids, ls, le, instr, diff in gap_rows
        ]
        assignments.append({
            "assignment_id": assignment_id, "file_path": file_path,
            "seq": seq, "master_version": master_version, "gaps": gaps,
        })
    return {"assignments": assignments}


def _mastery_maps(student_id: str, conn=None) -> tuple[dict[str, float], dict[str, int]]:
    """The student's current belief state, reshaped for select_variant's two mappings.
    A concept absent from the profile (no observations yet) is simply absent from both
    dicts -- select_variant's own `.get(c, 0.0)`/`.get(c, 0)` already treat that as the
    correct cold-start default; duplicating the default here would be a second place it
    could drift from select_variant's."""
    mastery = Memory().get_profile(student_id, conn=conn)["mastery"]
    mastery_by_concept = {c: v["p_mastery"] for c, v in mastery.items()}
    n_obs_by_concept = {c: v["n"] for c, v in mastery.items()}
    return mastery_by_concept, n_obs_by_concept


def _assert_no_hidden_tests_leaked(out_dir: Path) -> None:
    """The one invariant this whole module exists to guarantee. A real filesystem walk,
    not a "we only ever copy tests/visible so this can't happen" comment -- the
    difference between a comment and a check is exactly what this project's own history
    (D-007, the BKT bug that ran fine and looked correct) says not to trust by inspection
    alone. Matches on the directory name `hidden` anywhere under `out_dir`, not just the
    one expected path, so a future change that restructures tests/ still gets caught.
    """
    leaks = [p for p in out_dir.rglob("hidden") if p.is_dir()]
    if leaks:
        raise RuntimeError(
            f"tests/hidden leaked into the student repo: {[str(p) for p in leaks]}. "
            "This must never happen -- refusing to return a repo in this state."
        )


def _upsert_variant(cur, variant_id: str, assignment_id: str,
                    gap_ids: tuple[str, ...], master_version: str) -> None:
    """ON CONFLICT DO NOTHING, matching this codebase's own established idempotent-insert
    idiom (scripts/seed_data.py's kt_params/items inserts) -- NOT a pattern from
    gap_generator.py itself, which has no database code at all (checked; it is a pure
    computation module by design). Safe as DO NOTHING rather than DO UPDATE because
    `variant_id` is already a content hash of (assignment_id, gap_ids, master_version) --
    two rows with the same id necessarily already have identical content, so there is
    nothing to update.
    """
    cur.execute(
        "INSERT INTO variants (variant_id, assignment_id, gap_ids, master_version)"
        " VALUES (%s, %s, %s, %s) ON CONFLICT (variant_id) DO NOTHING",
        (variant_id, assignment_id, list(gap_ids), master_version),
    )


def _upsert_attempt(cur, student_id: str, project_id: str, assignment_id: str,
                    attempt_no: int, variant_id: str, gap_seed: int) -> None:
    """One row per (student_id, assignment_id, attempt_no) -- the table's own UNIQUE
    constraint (sql/06). `commit_sha`/`submitted_at` are left NULL: nothing has reached
    GitHub yet for a curriculum attempt (this module's own docstring explains why the
    schema was revised to allow that).

    ON CONFLICT DO UPDATE, guarded by `WHERE attempts.submitted_at IS NULL`: re-rendering
    the SAME still-unsubmitted attempt (e.g. the student's mastery moved between renders)
    is expected and should refresh variant_id/gap_seed -- but once submitted_at is real
    (a later step fills it in from collect_github), a re-render must never silently
    rewrite which variant a real submission was actually graded against. The guard makes
    that the database's own behaviour, not a rule this function has to remember to obey.
    """
    cur.execute(
        "INSERT INTO attempts"
        "   (student_id, project_id, assignment_id, attempt_no, variant_id, gap_seed)"
        " VALUES (%s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (student_id, assignment_id, attempt_no) DO UPDATE SET"
        "   variant_id = EXCLUDED.variant_id, gap_seed = EXCLUDED.gap_seed"
        " WHERE attempts.submitted_at IS NULL",
        (student_id, project_id, assignment_id, attempt_no, variant_id, gap_seed),
    )


# D-060. Two things the first published repo showed (CI run failed with `ruff: command not
# found`, exit 127, and `pytest tests/visible` never ran):
#   - the tools the workflow itself runs are installed BY THE WORKFLOW, in their own step --
#     not smuggled in through the student's requirements.txt, which lists the project's
#     runtime dependencies and nothing else.
#   - the ruff step is `continue-on-error: true`. Lint is a signal, not a correctness gate
#     (invariants 12, 13: correctness comes from executed tests), and a freshly rendered
#     repo is full of things ruff will flag that are not the student's fault yet -- stubs,
#     and imports that become unused the moment a gap is hidden. Lint must never be able
#     to stop pytest from running. Note the consequence (observed on a real run, not assumed):
#     the failing ruff step exits 1 and logs an error, but GitHub's API reports that step's
#     conclusion as "success" -- lint failures are visible only in the step's log, never in
#     the step list or in raw_workflow_runs.conclusion, which now reflects pytest alone.
#   - pytest runs as `python -m pytest`, not the bare `pytest` console script. Found by
#     running the workflow's commands locally on a fresh render: bare `pytest tests/visible`
#     fails at collection with `ModuleNotFoundError: No module named 'weather_etl'` (the
#     console script does not put the repo root on sys.path; `-m` does), so every visible
#     test would error in CI whatever the student wrote. The same bare command is what the
#     visible tests' docstrings tell a student to run locally, so the render also ships a
#     root conftest.py (_ROOT_CONFTEST) that makes the bare form work too; `python -m` is
#     kept in CI anyway as the form that needs nothing from the repo layout.
_CI_WORKFLOW = """\
name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: pip install ruff pytest
      - run: ruff check .
        continue-on-error: true
      - run: python -m pytest tests/visible
"""

# `tests/hidden/` is never written here (see `_assert_no_hidden_tests_leaked` below) --
# but `assessment/test_runner.py` used to copy the one hidden test a grading run needs
# straight into this same out_dir and never clean up after itself. Left untracked, that copy
# was one `git add .` away from being pushed to the student's real GitHub repo, which is
# exactly the leak render_student_repo.py otherwise refuses to allow. Since D-065 the grader
# works on a throwaway COPY and leaves the directory untouched, so this is now a second line
# of defence rather than the only one: it still covers a hidden test copied in by hand or by
# an older grader, on top of the runtime check that guards rendering itself.
_GITIGNORE = """\
tests/hidden/
__pycache__/
*.pyc
.pytest_cache/
"""

# D-060. A conftest.py at the repo root makes pytest put the repo root on sys.path, so
# `from weather_etl.extract import ...` resolves under BOTH `pytest tests/visible` (the
# command the visible tests' docstrings and VDEL_REDESIGN.md 8.3 tell a student to run) and
# `python -m pytest tests/visible` (what the CI workflow runs). Without it the bare console
# script cannot import the project and every visible test errors at collection. Comment-only
# on purpose: no fixtures, no hooks, nothing that could differ from one student's repo to
# another's. It does not interact with the hidden suite's own tests/hidden/conftest.py
# (assessment/test_runner.py injects that one separately, in a different directory).
_ROOT_CONFTEST = """\
# Intentionally empty of code.
#
# Its presence is the point: pytest adds this directory (the repo root) to sys.path when it
# finds a conftest.py here, which is what lets `pytest tests/visible` import the
# `weather_etl` package. Please leave it in place.
"""

# D-062. The files that are TEMPLATE, not student work: the same bytes in every student's
# repo, so a template change (D-060) can be re-applied to repos already published.
# render_student_repo writes exactly these, and scripts/sync_template.py is allowed to
# touch exactly these -- one mapping, so the path and the content cannot drift apart.
TEMPLATE_FILES = {
    ".github/workflows/ci.yml": _CI_WORKFLOW,
    "conftest.py": _ROOT_CONFTEST,
}


def render_student_repo(
    project_id: str, student_id: str, attempt_no: int, out_dir: str | Path, *, conn=None,
    only_assignment: str | None = None,
) -> dict:
    """Render one student's one attempt at `project_id` into a real repo at `out_dir`.

    Steps, matching the assignment order exactly:
      1-2. Load assignments/gaps from the DB; select_variant per assignment picks THIS
           student's THIS attempt's hidden gap bundle, deterministically (gap_generator).
           The chosen variant is persisted (_upsert_variant/_upsert_attempt) as it's
           resolved, not just used in memory -- an attempt now exists in the DB the
           moment a variant is assigned, before anything reaches GitHub.
      3-4. render_student_file turns each master file into its student-facing version;
           written to out_dir preserving the project's own file layout.
      5.   tests/visible/ copied if present; tests/hidden/ never copied, by construction
           (the loop below only ever walks tests/visible, never tests/hidden at all).
      6.   ASSIGNMENT.md: every hidden gap, its file, its line, its instruction.
      7.   .github/workflows/ci.yml: install, lint (non-blocking), run VISIBLE tests only.
      8.   conftest.py (comment-only) at the repo root, so bare `pytest tests/visible` can
           import the project -- see _ROOT_CONFTEST / D-060.

    `only_assignment` (D-072): render and record the attempt for that ONE assignment only
    (scripts/next_attempt.py). The default, None, is the unchanged whole-project behaviour.

    Idempotent to re-run: `out_dir` is recreated fresh each call (old contents removed
    first) rather than merged into, so a stale prior render can't leave orphaned files
    behind -- a partial merge would be a worse bug than requiring a clean directory.
    """
    project_dir = CURRICULUM_ROOT / project_id
    out_dir = Path(out_dir)

    with _cursor(conn) as cur:
        project = _load_project(cur, project_id)
    mastery_by_concept, n_obs_by_concept = _mastery_maps(student_id, conn)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    assignment_md_entries = []
    with _cursor(conn) as write_cur:
        for assignment in project["assignments"]:
            if only_assignment and assignment["assignment_id"] != only_assignment:
                continue
            file_path = assignment["file_path"]
            master_path = project_dir / file_path
            master_text = master_path.read_text(encoding="utf-8")

            variant_id, hidden_gap_ids = select_variant(
                assignment["gaps"],
                assignment_id=assignment["assignment_id"],
                master_version=assignment["master_version"],
                student_id=student_id,
                attempt_no=attempt_no,
                mastery_by_concept=mastery_by_concept,
                n_obs_by_concept=n_obs_by_concept,
            )

            _upsert_variant(write_cur, variant_id, assignment["assignment_id"],
                            hidden_gap_ids, assignment["master_version"])
            _upsert_attempt(
                write_cur, student_id, project_id, assignment["assignment_id"],
                attempt_no, variant_id,
                compute_seed(student_id, assignment["assignment_id"], attempt_no),
            )

            rendered = render_student_file(master_text, hide_gap_ids=hidden_gap_ids)
            student_path = out_dir / file_path
            student_path.parent.mkdir(parents=True, exist_ok=True)
            student_path.write_text(rendered, encoding="utf-8")

            gaps_by_id = {g.gap_id: g for g in assignment["gaps"]}
            for gid in hidden_gap_ids:
                gap = gaps_by_id[gid]
                assignment_md_entries.append({
                    "file": file_path, "gap_id": gid, "line": gap.line_start,
                    "instruction": gap.instruction, "variant_id": variant_id,
                })

    # Scaffolding: real files in the master tree that carry no gaps and so are copied
    # verbatim rather than rendered. Both are load-bearing, not decoration:
    #   <project_id>/__init__.py  makes the rendered tree an importable PACKAGE, which is
    #       what lets the hidden tests say `from weather_etl.extract import ...` against a
    #       student repo with no sys.path manipulation in the test files.
    #   requirements.txt          the generated ci.yml runs `pip install -r
    #       requirements.txt`; without it CI fails at step one, before reaching any student
    #       code -- every run red for a reason that has nothing to do with the student.
    # Copied through the same loop so a missing one is a visible KeyError-free no-op
    # rather than a silently broken render.
    for rel in (f"{project_id}/__init__.py", "requirements.txt"):
        src = project_dir / rel
        if src.exists():
            dest = out_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)

    # tests/visible copied if present; tests/hidden is NEVER read, let alone copied --
    # not "copied then filtered out", simply never touched by this loop at all.
    visible_src = project_dir / "tests" / "visible"
    if visible_src.exists():
        shutil.copytree(visible_src, out_dir / "tests" / "visible")

    assignment_md = ["# ASSIGNMENT\n", f"Project: `{project_id}` -- attempt {attempt_no}\n"]
    for e in assignment_md_entries:
        assignment_md.append(
            f"\n## `{e['file']}` line {e['line']} (`{e['gap_id']}`)\n\n{e['instruction']}\n"
        )
    (out_dir / "ASSIGNMENT.md").write_text("".join(assignment_md), encoding="utf-8")

    for rel_path, content in TEMPLATE_FILES.items():
        dest = out_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")

    (out_dir / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")

    _assert_no_hidden_tests_leaked(out_dir)

    return {
        "out_dir": str(out_dir),
        "files_rendered": [a["file_path"] for a in project["assignments"]
                           if not only_assignment or a["assignment_id"] == only_assignment],
        "hidden_gap_count": len(assignment_md_entries),
        "visible_tests_copied": visible_src.exists(),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("student_id")
    parser.add_argument("attempt_no", type=int)
    parser.add_argument("out_dir")
    args = parser.parse_args(argv)

    result = render_student_repo(args.project_id, args.student_id, args.attempt_no, args.out_dir)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
