"""scripts/validate_master.py -- check a master project before a student is issued it (D-107).

    python -m scripts.validate_master [PROJECT ...] [--require-reviewed]
                                      [--curriculum DIR] [--checks FILE] [--judging FILE]
                                      [--resources FILE]

Read-only: it reads files under `curriculum/master/` and `config/` and touches no database and no
network. For each project (default: every directory under `curriculum/master/`) and each stage file
`<project>/<stage>.py` it checks the following and prints `ERROR` / `WARN` / `INFO` lines:

  1. MARKER SYNTAX   the file parses with `assessment.gap_parser.parse_master` (nesting, a missing
                     id or concepts, an unclosed gap, no `@instruct`, an empty body ...). One
                     message per file, because the parser stops at the first problem.
  2. GAP IDS UNIQUE  across the WHOLE curriculum, not one file: `gaps.gap_id` is the table's primary
                     key and the seeder's `ON CONFLICT (gap_id) DO UPDATE` would silently re-point a
                     gap of another stage (D-106 finding (a)).
  3. CONCEPTS EXIST  every concept id of a marker is in the taxonomy (the parser's check, reported
                     here).
  4. GAP COVERED     every gap is named by `@pytest.mark.gap("<id>")` on at least one hidden test.
  5. TEST HAS A GAP  a hidden test with no gap marker is attributed to no concept (WARN); a marker
                     naming a gap the stage does not define is an ERROR.
  6. CHECKS ENTRY    every hidden test has an entry in `config/checks.yaml` whose `gap` agrees with
                     the test's marker, and no entry names a test that does not exist.
  7. JUDGING ENTRY   the assignment has an entry in `config/judging.yaml`. Without one it is judged
                     on all four criteria, including "Idiomatic Spark/SQL", which a plain-Python
                     stage cannot satisfy.
  8. RESOURCES       every concept the project's gaps use has at least one row in
                     `config/resources.csv`.

`draft` entries (checks and judging statements) are reported as INFO: they exist but are not used.
`--require-reviewed` turns them into ERRORs, for the check before a pilot.

Exit code: 0 when there is no ERROR, 1 otherwise, 2 for a usage problem (no such project).
A hidden test is found by reading the file with `ast`; nothing is imported or run.
"""

from __future__ import annotations

import argparse
import ast
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from assessment.gap_parser import GapParseError, parse_master
from config import checks as checks_cfg
from config import concepts as taxonomy
from config import judging as judging_cfg

REPO = Path(__file__).resolve().parent.parent
CURRICULUM = REPO / "curriculum" / "master"
RESOURCES_CSV = REPO / "config" / "resources.csv"

ERROR, WARN, INFO = "ERROR", "WARN", "INFO"


@dataclass(frozen=True)
class Finding:
    level: str
    where: str  # "project/stage" or "project" or "curriculum"
    message: str

    def line(self) -> str:
        return f"{self.level:<5} {self.where:<28} {self.message}"


@dataclass(frozen=True)
class HiddenTest:
    stored_name: str  # tests/hidden/<file>.py::<test> (the form test_results holds)
    gap: str | None


def stages_of(project_dir: Path) -> list[str]:
    """The stage names of a project: the `.py` files of its package, minus `__init__`."""
    package = project_dir / project_dir.name
    if not package.is_dir():
        return []
    return sorted(p.stem for p in package.glob("*.py") if not p.name.startswith("_"))


def hidden_tests(test_file: Path) -> list[HiddenTest]:
    """The test functions of a hidden test file and the gap each is marked with, read with `ast`."""
    tree = ast.parse(test_file.read_text(encoding="utf-8"))
    rel = f"tests/hidden/{test_file.name}"
    found: list[HiddenTest] = []

    def gap_of(fn: ast.FunctionDef) -> str | None:
        for dec in fn.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "gap"
                and dec.args
                and isinstance(dec.args[0], ast.Constant)
                and isinstance(dec.args[0].value, str)
            ):
                return dec.args[0].value
        return None

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
            found.append(HiddenTest(f"{rel}::{node.name}", gap_of(node)))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for sub in node.body:
                if isinstance(sub, ast.FunctionDef) and sub.name.startswith("test"):
                    found.append(HiddenTest(f"{rel}::{node.name}::{sub.name}", gap_of(sub)))
    return found


def resource_concepts(path: Path) -> set[str]:
    """Concept ids that have at least one real (non-EXAMPLE) resource row."""
    if not path.exists():
        return set()
    out: set[str] = set()
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("resource_id") or "").startswith("EXAMPLE"):
                continue
            out.update(c.strip() for c in (row.get("concept_ids") or "").split("|") if c.strip())
    return out


def validate(
    projects: list[str] | None = None,
    *,
    curriculum: Path = CURRICULUM,
    checks_path: Path = checks_cfg.CHECKS_PATH,
    judging_path: Path = judging_cfg.JUDGING_PATH,
    resources_path: Path = RESOURCES_CSV,
    require_reviewed: bool = False,
) -> list[Finding]:
    """Every finding for the given projects (default all), in a stable order."""
    names = projects if projects else sorted(p.name for p in curriculum.iterdir() if p.is_dir())
    out: list[Finding] = []
    gap_homes: dict[str, list[str]] = defaultdict(list)  # gap_id -> ["project/stage", ...]
    covered_concepts = resource_concepts(resources_path)

    try:
        checks_all = checks_cfg.entries(include_drafts=True, path=checks_path)
        checks_ok = True
    except (checks_cfg.ChecksError, OSError, ValueError) as exc:
        out.append(Finding(ERROR, "config/checks.yaml", f"cannot be read: {exc}"))
        checks_all, checks_ok = [], False
    try:
        _, judging_entries = judging_cfg.load(judging_path)
        judging_ok = True
    except (judging_cfg.JudgingError, OSError, ValueError) as exc:
        out.append(Finding(ERROR, "config/judging.yaml", f"cannot be read: {exc}"))
        judging_entries, judging_ok = {}, False
    draft_level = ERROR if require_reviewed else INFO

    for project in names:
        pdir = curriculum / project
        if not pdir.is_dir():
            out.append(Finding(ERROR, project, f"no such project under {curriculum}"))
            continue
        stages = stages_of(pdir)
        if not stages:
            out.append(Finding(ERROR, project, f"no stage files in {project}/{project}/"))
        project_concepts: set[str] = set()
        for stage in stages:
            aid = f"{project}_{stage}"
            where = f"{project}/{stage}"
            master = pdir / project / f"{stage}.py"

            # 1, 3: marker syntax and concept existence (parse_master does both, one error per file)
            gaps = None
            try:
                gaps = parse_master(master)
            except GapParseError as exc:
                out.append(Finding(ERROR, where, f"{master.name}: {exc}"))
            except (OSError, UnicodeDecodeError) as exc:
                out.append(Finding(ERROR, where, f"{master.name}: cannot be read: {exc}"))
            gap_ids = {g.gap_id for g in gaps} if gaps is not None else set()
            if gaps is not None:
                if not gaps:
                    out.append(Finding(WARN, where, "no gaps: nothing to grade in this stage"))
                for g in gaps:
                    gap_homes[g.gap_id].append(where)
                    project_concepts.update(g.concept_ids)

            # 4, 5: hidden tests and their gap markers
            test_file = pdir / "tests" / "hidden" / f"test_{stage}.py"
            tests: list[HiddenTest] = []
            if not test_file.exists():
                out.append(
                    Finding(ERROR, where, f"no hidden test file {test_file.relative_to(pdir)}")
                )
            else:
                try:
                    tests = hidden_tests(test_file)
                except SyntaxError as exc:
                    out.append(Finding(ERROR, where, f"{test_file.name} does not parse: {exc.msg}"))
            if gaps is not None and test_file.exists():
                marked = {t.gap for t in tests if t.gap}
                for gid in sorted(gap_ids - marked):
                    out.append(
                        Finding(
                            ERROR,
                            where,
                            f"gap {gid} is covered by no hidden test (@pytest.mark.gap)",
                        )
                    )
                for t in tests:
                    if t.gap is None:
                        out.append(
                            Finding(
                                WARN,
                                where,
                                f"{t.stored_name} has no gap marker: it is "
                                "attributed to no concept",
                            )
                        )
                    elif t.gap not in gap_ids:
                        out.append(
                            Finding(
                                ERROR,
                                where,
                                f"{t.stored_name} names gap {t.gap}, which "
                                f"{master.name} does not define",
                            )
                        )

            # 6: checks.yaml
            if checks_ok:
                entries = {c.test: c for c in checks_all if c.assignment_id == aid}
                known = {t.stored_name: t for t in tests}
                for name in sorted(set(known) - set(entries)):
                    out.append(Finding(ERROR, where, f"{name} has no entry in config/checks.yaml"))
                for name in sorted(set(entries) - set(known)):
                    if test_file.exists():
                        out.append(
                            Finding(
                                ERROR,
                                where,
                                f"config/checks.yaml lists {name}, which "
                                "is not a hidden test of this stage",
                            )
                        )
                for name in sorted(set(known) & set(entries)):
                    if known[name].gap != entries[name].gap:
                        out.append(
                            Finding(
                                ERROR,
                                where,
                                f"{name}: checks.yaml says gap "
                                f"{entries[name].gap}, the test is marked "
                                f"{known[name].gap}",
                            )
                        )
                drafts = sorted(c.test for c in entries.values() if not c.reviewed)
                if drafts:
                    out.append(
                        Finding(
                            draft_level,
                            where,
                            f"{len(drafts)} of {len(entries)} check "
                            "description(s) are still draft: not used until reviewed",
                        )
                    )

            # 7: judging.yaml
            if judging_ok:
                entry = judging_entries.get(aid)
                if entry is None:
                    out.append(
                        Finding(
                            ERROR,
                            where,
                            f"no entry for {aid} in config/judging.yaml: it "
                            "would be judged on all four criteria, with no "
                            "task statement",
                        )
                    )
                elif entry.statement_status == "draft":
                    out.append(
                        Finding(
                            draft_level,
                            where,
                            "judging statement is still draft: not used until reviewed",
                        )
                    )
                elif entry.statement is None:
                    out.append(Finding(WARN, where, "judging entry has no task statement"))

        # 8: resources, per project (the concepts its gaps use)
        for concept in sorted(project_concepts):
            if concept not in taxonomy.ids():
                continue  # already an ERROR from the parser
            if concept not in covered_concepts:
                out.append(
                    Finding(
                        ERROR,
                        project,
                        f"concept {concept} has no resource in {resources_path.name}",
                    )
                )

    # 2: gap ids unique across the curriculum
    for gid, homes in sorted(gap_homes.items()):
        if len(homes) > 1:
            out.append(
                Finding(
                    ERROR,
                    "curriculum",
                    f"gap id {gid} is defined in {len(homes)} places: {', '.join(homes)}",
                )
            )
    order = {ERROR: 0, WARN: 1, INFO: 2}
    return sorted(out, key=lambda f: (order[f.level], f.where, f.message))


def main(argv: list[str] | None = None, out=print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "projects", nargs="*", help="project ids (default: all under curriculum/master)"
    )
    ap.add_argument(
        "--require-reviewed",
        action="store_true",
        help="treat draft check descriptions and judging statements as ERRORs",
    )
    ap.add_argument("--curriculum", type=Path, default=CURRICULUM)
    ap.add_argument("--checks", type=Path, default=checks_cfg.CHECKS_PATH)
    ap.add_argument("--judging", type=Path, default=judging_cfg.JUDGING_PATH)
    ap.add_argument("--resources", type=Path, default=RESOURCES_CSV)
    args = ap.parse_args(argv)
    missing = [p for p in args.projects if not (args.curriculum / p).is_dir()]
    if missing:
        out(f"no such project(s) under {args.curriculum}: {', '.join(missing)}")
        return 2
    findings = validate(
        args.projects or None,
        curriculum=args.curriculum,
        checks_path=args.checks,
        judging_path=args.judging,
        resources_path=args.resources,
        require_reviewed=args.require_reviewed,
    )
    for f in findings:
        out(f.line())
    n = {lvl: sum(1 for f in findings if f.level == lvl) for lvl in (ERROR, WARN, INFO)}
    out(f"\n{n[ERROR]} error(s), {n[WARN]} warning(s), {n[INFO]} note(s)")
    return 1 if n[ERROR] else 0


if __name__ == "__main__":
    sys.exit(main())
