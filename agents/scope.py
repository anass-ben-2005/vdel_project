"""agents/scope.py -- which lines of a submission the Code Agent judges (D-103).

BEFORE this change the whole file went into the prompt: `code_agent.py` read it whole
(`code = path.read_text(...)`, line 167 at commit eb9727c) and `prompts.py` interpolated it whole
(`{code}`, line 233 at the same commit). The master's own code, which is in every student's file,
was therefore judged as if the student had written it, and the linter findings on it were shown as
facts about the student (invariant 14 says they must not be).

NOW, when the caller gives a `ScopeSpec`, only the lines the student wrote INSIDE a gap are judged,
plus `CONTEXT_LINES` lines on each side so the judge can see the function around them. How the lines
are found is the machinery the project already has and trusts for V9 and V2, not a new one:

  1. `assessment.gap_parser.render_student_file_with_ranges(master_text, hide_gap_ids)` gives the
  file
     the student received and the line range of each hidden gap IN THAT FILE;
  2. `assessment.scope_check.in_gap_submitted_ranges(released, submitted, ranges)` maps those ranges
     onto the submitted file with the same line diff `scope_check` uses (a gap that grew or shrank
     shifts every later line, so the released ranges cannot be reused as they are).

If the lines cannot be extracted the Code Agent SKIPS, with a reason, and does not fall back to the
whole file: a wrong scope is worse than no verdict. Reasons: the master's markup does not parse; the
master has no gap; no line of the submission differs inside a gap (the student left the stub, or
deleted the gap); the variant pins another master version (invariant 15); the master is missing.

Pure except `scope_spec_for_attempt`, which reads four tables and the master file.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from assessment.gap_parser import GapParseError, render_student_file_with_ranges
from assessment.scope_check import in_gap_submitted_ranges

# A chosen number, not a measurement: enough to show the def line and a docstring above a gap.
CONTEXT_LINES = 3

CURRICULUM_ROOT = Path(__file__).resolve().parent.parent / "curriculum" / "master"


class ScopeUnavailable(ValueError):
    """The lines to judge cannot be extracted. The message is the plain reason."""


@dataclass(frozen=True)
class ScopeSpec:
    """What is needed to find the student's gap lines: the master file and which gaps the
    student's variant hid (the others keep the master's own body and are not the student's)."""

    master_text: str
    hide_gap_ids: tuple[str, ...]


@dataclass(frozen=True)
class Excerpt:
    text: str                                  # what goes into the prompt
    gap_ranges: tuple[tuple[int, int], ...]    # the student's lines in the submitted file (1-based)
    shown_ranges: tuple[tuple[int, int], ...]  # those plus context, merged
    lines_shown: int
    file_lines: int
    matchable: str = ""                        # the shown lines only, no markers

    @property
    def note(self) -> str:
        return (f"Only part of the file is shown: the lines the student wrote inside the "
                f"exercise gap(s) and {CONTEXT_LINES} lines of context on each side "
                f"({self.lines_shown} of {self.file_lines} lines). A line `[... n line(s) not "
                f"shown ...]` marks lines left out; it is not student text, never quote it. Judge "
                f"only what is shown, and do not guess at the lines you cannot see.")


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def judged_excerpt(spec: ScopeSpec, submitted_text: str, context: int = CONTEXT_LINES) -> Excerpt:
    """The student's gap lines plus context, or `ScopeUnavailable(reason)`."""
    if not spec.hide_gap_ids:
        raise ScopeUnavailable("the student's variant hides no gap, so no line is the student's")
    try:
        released, released_ranges = render_student_file_with_ranges(
            spec.master_text, spec.hide_gap_ids)
    except GapParseError as exc:
        raise ScopeUnavailable(f"the master's gap markup cannot be parsed: {exc}") from None
    if not released_ranges:
        raise ScopeUnavailable("the master has no gap to judge")
    gap_ranges = in_gap_submitted_ranges(released, submitted_text, released_ranges)
    if not gap_ranges:
        raise ScopeUnavailable("no line of the submission differs from the released file inside a "
                               "gap (the stub was left as it was, or the gap was deleted)")

    lines = submitted_text.splitlines()
    total = len(lines)
    shown = _merge([(max(1, start - context), min(total, end + context))
                    for start, end in gap_ranges])
    out: list[str] = []
    kept: list[str] = []
    cursor = 1
    for start, end in shown:
        if start > cursor:
            out.append(f"[... {start - cursor} line(s) not shown ...]")
        out.extend(lines[start - 1:end])
        kept.extend(lines[start - 1:end])
        cursor = end + 1
    if cursor <= total:
        out.append(f"[... {total - cursor + 1} line(s) not shown ...]")
    return Excerpt(
        text="\n".join(out) + "\n",
        gap_ranges=tuple(gap_ranges), shown_ranges=tuple(shown),
        lines_shown=sum(end - start + 1 for start, end in shown), file_lines=total,
        matchable="\n".join(kept) + "\n")


def scope_spec_for_attempt(cur, attempt_id: int) -> ScopeSpec:
    """Read-only. The master text and the hidden gap ids of this attempt's variant, the way
    `assessment.lint_scope.record` reads them. Raises `ScopeUnavailable` for anything missing."""
    cur.execute(
        "SELECT a.project_id, s.file_path, v.gap_ids, v.master_version, p.master_version"
        " FROM attempts a"
        " JOIN assignments s ON s.assignment_id = a.assignment_id"
        " JOIN variants v ON v.variant_id = a.variant_id"
        " JOIN projects p ON p.project_id = a.project_id"
        " WHERE a.attempt_id = %s", (attempt_id,))
    row = cur.fetchone()
    if row is None:
        raise ScopeUnavailable(f"no attempt {attempt_id}, or its assignment, variant or project is "
                               "missing")
    project_id, file_path, gap_ids, variant_master, project_master = row
    if not file_path:
        raise ScopeUnavailable("the assignment has no file_path")
    if variant_master != project_master:
        raise ScopeUnavailable("the variant pins another master version (invariant 15)")
    master = CURRICULUM_ROOT / project_id / file_path
    try:
        master_text = master.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScopeUnavailable(f"the master file cannot be read: {type(exc).__name__}") from None
    return ScopeSpec(master_text, tuple(gap_ids or ()))
