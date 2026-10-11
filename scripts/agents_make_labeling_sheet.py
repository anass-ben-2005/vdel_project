"""scripts/agents_make_labeling_sheet.py -- a CSV for the author to label BY HAND.

    python -m scripts.agents_make_labeling_sheet [--out PATH]
    python -m scripts.agents_make_labeling_sheet --import-sheet FILLED.csv [--ground-truth-out PATH]

The labels are the author's, never a model's (CLAUDE.md §10; benchmark/ground_truth.json is a
template of nulls for that reason). This script only prepares the sheet and, later, converts the
filled sheet into the shape `benchmark/run_benchmark.py` reads.

SHEET: one row per (submission, criterion). Columns:
    submission_id, criterion, my_score, my_note, file
`my_score` is left EMPTY for you: 0, 2 or 4, the anchors of the rubric in `agents/prompts.py`
(`RUBRIC_TABLE`; print them with `--legend`). `file` says which file to read. Rows come from
  - benchmark/submissions/*.py   (id = the file name, e.g. `clean.py`)
  - tests/fixtures/agents/code/*.py (id = `fixture:<file name>`, small synthetic student files)
The sheet holds ids and paths only: no code, no test content, no model output, so it can contain
no hidden test line. Criteria are the rubric's four; for the fixtures the same four apply.

DEFAULT OUTPUT `benchmark/results/labeling_sheet.csv` (gitignored directory; a filled sheet is
personal work, not source). An existing file is never overwritten without `--force`.

IMPORT: validates every `my_score` in {empty, 0, 2, 4}, keeps only benchmark submissions (the only
ones `ground_truth.json` has) and writes JSON in the template's shape. It does NOT overwrite
`benchmark/ground_truth.json`: pass `--ground-truth-out` to choose where it goes, then review and
move it yourself. Rows left empty stay `null`.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from agents.prompts import RUBRIC_TABLE

ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_DIR = ROOT / "benchmark" / "submissions"
FIXTURE_CODE_DIR = ROOT / "tests" / "fixtures" / "agents" / "code"
DEFAULT_OUT = ROOT / "benchmark" / "results" / "labeling_sheet.csv"
GROUND_TRUTH_TEMPLATE = ROOT / "benchmark" / "ground_truth.json"
CRITERIA = ("correctness", "approach", "readability", "idiomatic")
COLUMNS = ("submission_id", "criterion", "my_score", "my_note", "file")
ALLOWED_SCORES = {"0", "2", "4"}
FIXTURE_PREFIX = "fixture:"


def submissions() -> list[tuple[str, Path]]:
    """(submission_id, path), benchmark first, then fixtures; each sorted by name."""
    found = [(p.name, p) for p in sorted(BENCHMARK_DIR.glob("*.py"))]
    found += [(FIXTURE_PREFIX + p.name, p) for p in sorted(FIXTURE_CODE_DIR.glob("*.py"))]
    return found


def sheet_rows() -> list[dict[str, str]]:
    return [{"submission_id": sid, "criterion": criterion, "my_score": "", "my_note": "",
             "file": path.relative_to(ROOT).as_posix()}
            for sid, path in submissions() for criterion in CRITERIA]


def write_sheet(path: Path, *, force: bool = False) -> int:
    if path.exists() and not force:
        raise FileExistsError(f"{path} exists (it may hold your labels); pass --force to replace")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sheet_rows()
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:   # BOM: opens in Excel
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def import_sheet(path: Path) -> tuple[dict, list[str]]:
    """`(ground_truth dict, errors)`. Errors are listed with CSV line numbers."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            return {}, [f"missing column(s): {', '.join(missing)}"]
        rows = list(reader)

    template = json.loads(GROUND_TRUTH_TEMPLATE.read_text(encoding="utf-8"))
    out = {**{k: v for k, v in template.items() if k != "submissions"}, "submissions": {
        name: dict.fromkeys(CRITERIA) for name in template["submissions"]}}
    errors: list[str] = []
    for i, row in enumerate(rows):
        line = i + 2
        sid, criterion = row["submission_id"].strip(), row["criterion"].strip()
        score = (row["my_score"] or "").strip()
        if criterion not in CRITERIA:
            errors.append(f"line {line}: unknown criterion {criterion!r}")
            continue
        if score and score not in ALLOWED_SCORES:
            errors.append(f"line {line}: my_score {score!r} must be empty, 0, 2 or 4")
            continue
        if sid.startswith(FIXTURE_PREFIX) or not score:
            continue                                  # fixtures are not in ground_truth.json
        if sid not in out["submissions"]:
            errors.append(f"line {line}: {sid!r} is not a benchmark submission")
            continue
        out["submissions"][sid][criterion] = int(score)
    return out, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--force", action="store_true", help="replace an existing sheet")
    ap.add_argument("--legend", action="store_true", help="print the 0/2/4 anchors and exit")
    ap.add_argument("--import-sheet", type=Path, help="convert a filled sheet to ground-truth JSON")
    ap.add_argument("--ground-truth-out", type=Path,
                    help="where --import-sheet writes (never benchmark/ground_truth.json itself)")
    args = ap.parse_args(argv)

    if args.legend:
        print(RUBRIC_TABLE)
        return 0
    if args.import_sheet:
        data, errors = import_sheet(args.import_sheet)
        for message in errors:
            print(f"ERROR {message}")
        if errors:
            return 1
        target = args.ground_truth_out
        if target is None:
            print(json.dumps(data, indent=2))
            return 0
        if target.resolve() == GROUND_TRUTH_TEMPLATE.resolve():
            print("refusing to overwrite benchmark/ground_truth.json: review the output first")
            return 2
        target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {target}")
        return 0
    try:
        n = write_sheet(args.out, force=args.force)
    except FileExistsError as exc:
        print(exc)
        return 2
    print(f"wrote {n} rows to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
