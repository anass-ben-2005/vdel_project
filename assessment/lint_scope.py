"""assessment/lint_scope.py -- gap-scoped lint counts for V2 (D-088).

V2's cleanliness is "lint findings per 100 changed lines". Until D-088 both numbers were fixed
at 0 because nothing checked out the student's code. Grading now has the checkout, so the
numbers can be measured, under three rules:

  * STATIC ONLY. `agents.tools.run_ruff` / `run_sqlfluff` tokenise and parse; they never import
    or run the file (invariant 12). This module therefore lives next to, but outside,
    `test_runner.py`, which must import nothing from `agents/` (invariant 13, checked by grep).
  * GAP-SCOPED (invariant 14, VDEL_REDESIGN.md C4). The linter runs on the whole submitted file
    (parsing needs context) and only findings on lines the student wrote INSIDE a gap count.
    The gap regions are known in the released file's coordinates; `scope_check` maps them to
    the submitted file's coordinates with the same line diff it uses for V9.
  * FAIL-OPEN. Anything that stops a measurement -- a file that does not load (D-085's
    collection_error / timeout), a linter that is not installed or times out, a file type no
    linter covers, a master version that changed (invariant 15) -- yields `None`, stored as NULL
    ("not measured"). A number is never invented.

The file is linted from a private temporary COPY, in a directory with no project files, so a
`pyproject.toml`, `ruff.toml` or `.sqlfluff` inside the student's repo cannot switch rules off:
the rule set is the tools' defaults, the same for every student. That is a choice, not a
measurement: it means V2 cleanliness is "defaults of ruff / sqlfluff", not this repo's stricter
configuration.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from agents.tools import STATUS_OK, lint_submission
from assessment.gap_parser import render_student_file_with_ranges
from assessment.scope_check import (
    filter_lint_findings,
    in_gap_submitted_ranges,
    scope_check,
)
from assessment.test_runner import CURRICULUM_ROOT, NOT_MEASURED_STATUSES

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LintMeasure:
    violations: int          # findings on in-gap lines
    changed_loc: int         # lines changed inside the gaps (the denominator)
    tool: str                # 'ruff' | 'sqlfluff'


def measure(released_text: str, submitted_text: str, gap_ranges, filename: str
            ) -> LintMeasure | None:
    """Count the lint findings on the lines the student wrote inside the gaps, or None.

    Pure apart from the temporary copy it lints. `filename` only supplies the extension that
    chooses the linter."""
    tmp = Path(tempfile.mkdtemp(prefix="vdel_lint_"))
    try:
        copy = tmp / Path(filename).name
        copy.write_text(submitted_text, encoding="utf-8")
        reports = lint_submission(copy)
        if len(reports) != 1 or reports[0].status != STATUS_OK:
            return None                       # no linter, or it could not run: not measured
        report = reports[0]
        ranges = in_gap_submitted_ranges(released_text, submitted_text, gap_ranges)
        counted = filter_lint_findings(report.findings, ranges)
        changed = scope_check(released_text, submitted_text, gap_ranges).changed_loc_in_gap
        return LintMeasure(len(counted), changed, report.tool)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def record(cur, *, project_id: str, assignment_id: str, attempt_id: int, commit_sha: str,
           repo_dir: Path, status: str = "ok") -> LintMeasure | None:
    """Measure the checkout and store the result on the attempt. Fail-open: any problem logs a
    warning and leaves the columns as they were. Runs inside a SAVEPOINT so a failure (for
    example the columns not being migrated yet) cannot abort the caller's transaction.

    Same storage rule as `out_of_scope_lines` (D-073/D-085): the latest graded commit's value
    until the attempt freezes, the frozen commit's value afterwards."""
    if status in NOT_MEASURED_STATUSES:
        return None
    cur.execute("SAVEPOINT lint_scope")
    try:
        cur.execute("SELECT file_path FROM assignments WHERE assignment_id = %s",
                    (assignment_id,))
        row = cur.fetchone()
        if row is None or not row[0]:
            raise ValueError(f"no file_path for assignment {assignment_id!r}")
        file_path = row[0]
        cur.execute(
            "SELECT v.gap_ids, v.master_version, p.master_version FROM attempts a"
            " JOIN variants v USING (variant_id) JOIN projects p ON p.project_id = a.project_id"
            " WHERE a.attempt_id = %s", (attempt_id,))
        gap_ids, variant_master, project_master = cur.fetchone()
        if variant_master != project_master:                       # invariant 15
            raise ValueError("the variant pins another master version")
        master_text = (CURRICULUM_ROOT / project_id / file_path).read_text(encoding="utf-8")
        released, ranges = render_student_file_with_ranges(master_text, gap_ids)
        submitted = (Path(repo_dir) / file_path).read_text(encoding="utf-8")
        measured = measure(released, submitted, ranges, file_path)
        if measured is not None:
            cur.execute(
                "UPDATE attempts SET lint_violations = %s, lint_changed_loc = %s,"
                " lint_tool = %s WHERE attempt_id = %s"
                " AND (submitted_at IS NULL OR commit_sha IS NOT DISTINCT FROM %s)",
                (measured.violations, measured.changed_loc, measured.tool, attempt_id,
                 commit_sha))
        cur.execute("RELEASE SAVEPOINT lint_scope")
        return measured
    except Exception as exc:  # noqa: BLE001 -- fail-open is the contract
        cur.execute("ROLLBACK TO SAVEPOINT lint_scope")
        log.warning("lint scope skipped for attempt %s (columns left as they were): %s: %s",
                    attempt_id, type(exc).__name__, exc)
        return None
