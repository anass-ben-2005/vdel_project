"""assessment/scope_check.py -- classify every changed line as in-gap or out-of-scope.

VDEL_REDESIGN.md 8.2: "You hold the released student file. The student commits a file.
Diff them. Any changed line outside a gap region is an out-of-scope edit, and you now
know exactly which lines." Detection, not prevention -- the underlying worry (a student
editing outside their assigned region) doesn't need preventing, it needs knowing about,
because an out-of-scope edit is sometimes a real bug fix (praiseworthy) and sometimes an
integrity signal, and either way it's information the whole-file approach threw away.

CITATION CORRECTION: this is CLAUDE.md invariant **14** ("All static analysis is
GAP-SCOPED. Findings outside gap line ranges are never attributed to the student"), not
13 -- 13 is "Correctness is decided by EXECUTED TESTS," unrelated. The instruction that
asked for this file named 13; checked against the live file before writing anything,
same as every other citation this session. VDEL_REDESIGN.md's OWN 12.2 also numbers this
12-15 before CLAUDE.md's actual invariant 12 ("no agent executes submitted code") forced
a renumber to 13-16 earlier this session -- the off-by-one is old and already fixed
everywhere else; this is one more place it could have silently regressed if untraced.

`filter_lint_findings` is C4's other half ("Same for the changed_loc denominator... Run
linters on the full file... then filter findings to line ranges inside gap regions"):
the master's own code, present in every submission, must never inflate a student's V2 --
a linter finding is only evidence about the STUDENT if it sits inside a gap.

DIVERGENCE from the spec's literal signature, recorded rather than left silent:
VDEL_REDESIGN.md 8.2 writes `def scope_check(released, submitted, gap_ranges) -> dict`.
This returns a frozen `ScopeReport` dataclass instead. The field names -- and therefore
what any caller actually reads -- are unchanged; what changes is that a typo'd key now
fails at the attribute access instead of returning `None` and quietly becoming a zero in
a V2 denominator. Deliberate, and a strictly narrower contract than `dict`, so no caller
the spec anticipated is excluded. Flagged here because "returns dict" is the kind of
detail a later reader would otherwise assume this file simply got wrong.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ScopeReport:
    """`in_gap_lines_changed`/`changed_loc_in_gap` are the same count under two names,
    deliberately: the first pairs naturally with `out_of_scope_lines_changed` (the
    integrity-signal framing, VDEL_REDESIGN.md A5/V9); the second is named to match
    `variables/habits.py`'s existing `changed_loc` parameter exactly, so a call site
    updating V2/V6 to the gap-scoped denominator (C4) can find the field by the name
    it's already looking for, without having to know it's the same number as the other
    one. C4: "Same for the changed_loc denominator" -- this field IS that denominator,
    the only one V2/V6 may use going forward.
    """

    in_gap_lines_changed: int
    out_of_scope_lines_changed: int
    out_of_scope_line_numbers: tuple[int, ...]
    changed_loc_in_gap: int


def _to_half_open_zero_indexed(gap_ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """gap_ranges arrive 1-indexed inclusive (line_start, line_end) -- gap_parser.Gap's own
    convention (assessment/gap_parser.py). difflib's opcodes are 0-indexed half-open.
    Converted once, here, rather than re-derived at every comparison site."""
    return [(start - 1, end) for start, end in gap_ranges]


def _opcode_is_in_gap(i1: int, i2: int, gaps_0idx: list[tuple[int, int]]) -> bool:
    """i1, i2: the RELEASED-side half-open range difflib reports for one changed block.

    difflib.SequenceMatcher aligns released and submitted lines by CONTENT (a longest-
    matching-blocks algorithm), not by position -- this is what makes line-number drift a
    non-problem rather than something to correct for after the fact. When a 1-line gap is
    replaced by 4 submitted lines, the opcode for that change reports i1:i2 = the ORIGINAL
    1 released line, and every 'equal' block after it realigns automatically to whatever
    submitted line number the unchanged content now sits at -- there is no separate
    "shift by 3" step anywhere in this module, because there is nothing to shift: i1/i2
    are always released-file coordinates, which never move, and gap_ranges are ALSO
    released-file coordinates. The two were never in different coordinate systems to begin
    with. Only `out_of_scope_line_numbers` (reported in the SUBMITTED file's numbering,
    since that's what a student or a CI message points at) uses j1/j2, and it uses them
    per-opcode, never as an assumption that submitted line N corresponds to released line N.

    A pure insert has i1 == i2 (a zero-width point in the released file: "insert here,
    between these two released lines"). Treated as inside a gap if that point sits ANYWHERE
    within the gap's span, inclusive of both edges -- an insert exactly at a gap's boundary
    is still an edit made while working inside that gap, not a separate out-of-scope act.

    MIXED blocks -- an opcode whose released range covers BOTH gap and non-gap lines --
    are classified as OUT-OF-SCOPE, not split proportionally, and not credited as in-gap.
    This is a real, checked, un-worked-around limitation, not an oversight: when an
    out-of-scope edit sits on a line directly adjacent to a gap (no unchanged line between
    them), difflib merges both into ONE opcode, because attributing which specific new
    lines correspond to which specific old lines within a block whose line COUNTS differ
    on each side is genuinely undecidable from a line diff alone -- there is no correct
    finer answer to compute, only an invented-looking one. Treating the whole merged block
    as out-of-scope is the conservative reading of invariant 14 ("findings outside gap
    line ranges are never attributed to the student"): an edit this module cannot verify
    stayed entirely within the gap is not credited as if it did. A clean edit with even
    one unchanged line separating it from its neighbours splits into separate opcodes
    automatically and is attributed precisely; this only bites truly adjacent edits.
    """
    if i1 == i2:
        return any(start <= i1 <= end for start, end in gaps_0idx)
    return any(start <= i1 and i2 <= end for start, end in gaps_0idx)


def scope_check(
    released_text: str, submitted_text: str, gap_ranges: Iterable[tuple[int, int]]
) -> ScopeReport:
    """Diff `released_text` against `submitted_text`; classify every changed block as
    in-gap or out-of-scope. Pure: no I/O, no DB -- same discipline as variables/*.py and
    assessment/gap_parser.py's render_student_file.

    `difflib.SequenceMatcher(autojunk=False)` -- NOT the default. Autojunk treats a line
    that recurs "too often" (its own heuristic: >1% of a sequence longer than 200 lines)
    as noise and excludes it from the matching blocks it looks for. Source code is full of
    exactly the kind of repetition (blank lines, `    return result`, close braces) that
    heuristic was written for prose, not code, to ignore -- left at its default, it can
    silently misalign matches in a file with enough boilerplate. Off, unconditionally.

    "Lines changed" per opcode: `j2 - j1` (the submitted-side span) for insert/replace,
    `i2 - i1` (the released-side span) for a pure delete -- a pure deletion has nothing on
    the submitted side to count, so the released side is what was actually removed.
    `out_of_scope_line_numbers` reports submitted-file line numbers (1-indexed) for
    insert/replace blocks; a pure out-of-scope DELETION has no submitted line number to
    report at all (the content is simply gone) -- it still counts toward
    `out_of_scope_lines_changed`, honestly, rather than being silently dropped or
    attributed to a line number that doesn't exist in what the student actually submitted.
    """
    released_lines = released_text.splitlines()
    submitted_lines = submitted_text.splitlines()
    gaps_0idx = _to_half_open_zero_indexed(gap_ranges)

    matcher = difflib.SequenceMatcher(a=released_lines, b=submitted_lines, autojunk=False)

    in_gap = 0
    out_of_scope = 0
    out_of_scope_lines: list[int] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        count = (i2 - i1) if tag == "delete" else (j2 - j1)
        if _opcode_is_in_gap(i1, i2, gaps_0idx):
            in_gap += count
        else:
            out_of_scope += count
            if tag != "delete":
                out_of_scope_lines.extend(range(j1 + 1, j2 + 1))

    return ScopeReport(
        in_gap_lines_changed=in_gap,
        out_of_scope_lines_changed=out_of_scope,
        out_of_scope_line_numbers=tuple(out_of_scope_lines),
        changed_loc_in_gap=in_gap,
    )


def filter_lint_findings(
    findings: Iterable[Mapping], gap_ranges: Iterable[tuple[int, int]]
) -> list[Mapping]:
    """C4: findings outside gap regions are never attributed to the student -- the
    master's own code is present in every submission, and its violations are not evidence
    about what the student wrote. Matches `agents/tools.py`'s real finding shape
    (`run_ruff`/`run_sqlfluff`: `{"code", "message", "line", "column", "severity"}`) --
    checked against the live file rather than inventing a shape.

    A finding with `line` missing or `None` (a file-level or unlocatable finding, which
    both linters can emit) is EXCLUDED, not included-by-default: invariant 14 says
    findings outside gap ranges are never attributed to the student, and a finding this
    module cannot place anywhere is, from here, indistinguishable from one outside every
    gap -- "we don't know" must not silently become "assume it's the student's."
    """
    ranges = list(gap_ranges)
    return [
        f for f in findings
        if f.get("line") is not None
        and any(start <= f["line"] <= end for start, end in ranges)
    ]
