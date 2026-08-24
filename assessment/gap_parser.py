"""assessment/gap_parser.py -- turn a marked-up master file into gap specs and student files.

CLAUDE.md 5 names this file (`assessment/gap_parser.py`, "@gap: markers -> student file +
gaps rows") as the first piece of the completion-problem redesign (DECISIONS.md D-035).
VDEL_REDESIGN.md 8.3 specifies the marker convention as nbgrader-style -- "`# @gap:`
markers with instruction text, nbgrader-style" -- deliberately copying a convention that
already exists rather than inventing a new one:

    # @gap:id=g_retry_loop concepts=[py.errors_debugging] difficulty=0.5
    # @instruct: Loop over attempt numbers from 1 to MAX_ATTEMPTS inclusive. Each
    #            attempt: sleep, then retry; on the last attempt, let it raise.
    for attempt in range(1, MAX_ATTEMPTS + 1):
        ...
    # @endgap

An instruction may continue onto further plain `#` comment lines with no marker of their
own (as above) -- found necessary from real curriculum content
(curriculum/master/weather_etl/extract.py), not written into any spec beforehand: a
sentence too long for one line continues aligned underneath rather than repeating
`@instruct:` on every line. Only recognised once a real `@instruct:` has already opened
the instruction -- a lone comment with no marker at all still fails to parse (see
GapParseError below), which is what stops a forgotten marker from silently becoming
"the instruction" instead of raising.

Two public functions, matching VDEL_REDESIGN.md 5/A3's split of concerns:

  parse_master(path)          -- the AUTHORING side. Reads one master file, returns the
                                  gap specs that seed the `gaps` table (sql/06). The one
                                  function in this module allowed to do I/O beyond the
                                  master file itself: concept ids are checked against
                                  config/concepts.yaml, because a gap tagged with a concept
                                  that doesn't exist would silently never update mastery
                                  for anyone (the same silent-corruption failure mode
                                  invariant 10 already guards for classified errors).

  render_student_file(...)    -- the DELIVERY side. Pure: text in, text out, zero I/O.
                                  Takes the ALREADY-READ master text so it can be unit
                                  tested without a filesystem and reused by whatever
                                  eventually writes the per-student repo.

Both call the same private line-by-line parser, `_parse_gap_structure` -- one
implementation of "what is a gap", not two that could silently disagree (the same
argument DECISIONS.md D-007 makes for mastery: replay once, not fold-and-recompute
twice). `parse_master` layers concept-existence validation on top of it; that check needs
config/concepts.yaml, which `render_student_file` has no reason to ever touch.

Line ranges matter beyond bookkeeping: CLAUDE.md invariant 14 ("all static analysis is
GAP-SCOPED; findings outside gap line ranges are never attributed to the student") is the
reason `Gap.line_start`/`line_end` bound only the gap's BODY -- the student-editable
region -- and never the `# @gap:`/`# @instruct:`/`# @endgap` marker lines themselves.
`assessment/scope_check.py` is the function that actually consumes this boundary (it takes
`gap_ranges` as `(line_start, line_end)` pairs straight from these Gap objects); getting it
right here is what makes that function correct, rather than a second place the boundary
could be redefined and disagree.

Fails loudly by design, not by accident: a mis-parsed gap -- an id typo that silently
opens a second gap instead of erroring, a concept id that doesn't exist and so never
feeds BKT -- corrupts every downstream artifact (gaps rows, variants, mastery estimates)
without ever raising an exception anywhere near the mistake. Every error below names the
line number and the specific rule broken, per CLAUDE.md 10's "stop and ask" instinct
applied to a parser instead of a person.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from pathlib import Path

from config import concepts as concepts_module

_GAP_START = re.compile(r"^\s*#\s*@gap:(.*)$")
_INSTRUCT = re.compile(r"^\s*#\s*@instruct:\s?(.*)$")
_GAP_END = re.compile(r"^\s*#\s*@endgap\s*$")
_CONCEPTS_FIELD = re.compile(r"concepts=\[([^\]]*)\]")
# A plain comment line, no marker of its own -- CONTINUATION of an already-open
# @instruct:, found from real curriculum content (curriculum/master/weather_etl/
# extract.py), not from any written spec: a sentence too long for one line continues as
# `#            more text`, aligned under the `@instruct:` text rather than repeating the
# marker on every line. Deliberately generic (matches ANY `#...` line) rather than
# requiring specific alignment -- callers only reach this regex once `@gap:`/`@endgap`
# have already been ruled out for the same line, and only while still inside the
# instruction-collecting phase (before any real code line has been seen).
_COMMENT_CONTINUATION = re.compile(r"^\s*#\s?(.*)$")

# VDEL_REDESIGN.md 11: `gaps.difficulty REAL NOT NULL DEFAULT 0.5`. A marker that omits
# difficulty= gets the same cold-start seed the database column itself would apply --
# one default, not a second one that could drift from the schema's.
_DEFAULT_DIFFICULTY = 0.5


class GapParseError(ValueError):
    """A master file's @gap markup is malformed. Never recoverable at runtime -- fix the
    source file. Named after config/concepts.py's TaxonomyError -- same role, same
    "this is a fatal authoring mistake, not a runtime condition" signal.
    """


@dataclass(frozen=True)
class Gap:
    """One `# @gap: ... # @endgap` block. Mirrors sql/06_assessment_tables.sql's `gaps`
    table columns (gap_id, concept_ids, line_start, line_end, instruction, difficulty)
    plus `body`, which the table doesn't store -- the table only needs to know WHERE the
    gap is (line_start/line_end, valid for one master_version); `body` is kept here
    because `render_student_file` needs the original text to derive indentation from,
    and returning it avoids a second file read to get it back.
    """

    gap_id: str
    concept_ids: tuple[str, ...]
    line_start: int      # 1-indexed, first line of the BODY (never a marker line)
    line_end: int         # 1-indexed, last line of the BODY (never a marker line)
    instruction: str
    difficulty: float
    body: str


def _parse_gap_header(line: str, lineno: int) -> tuple[str, tuple[str, ...], float]:
    """Extract id=/concepts=[...]/difficulty= from one `# @gap:` line.

    Field order is not fixed by the regex on purpose -- `concepts=[...]` is pulled out
    first because it is the one field that can itself contain no further structure to
    misparse (a bracketed list), then whatever remains is split as generic key=value
    tokens. A brittle fixed-order parser would break the moment someone reorders
    `difficulty=` before `concepts=`, which is a real risk given VDEL_REDESIGN.md 11's
    own examples don't fix an order either.
    """
    body = _GAP_START.match(line).group(1).strip()

    concepts_match = _CONCEPTS_FIELD.search(body)
    if concepts_match is None:
        raise GapParseError(f"line {lineno}: @gap: missing concepts=[...]")
    concept_ids = tuple(
        c.strip() for c in concepts_match.group(1).split(",") if c.strip()
    )
    remainder = body[: concepts_match.start()] + body[concepts_match.end():]

    fields = dict(tok.split("=", 1) for tok in remainder.split() if "=" in tok)
    gap_id = fields.get("id")
    if not gap_id:
        raise GapParseError(f"line {lineno}: @gap: missing id=")

    if "difficulty" in fields:
        try:
            difficulty = float(fields["difficulty"])
        except ValueError as exc:
            raise GapParseError(
                f"line {lineno}: @gap: difficulty={fields['difficulty']!r} is not a number"
            ) from exc
    else:
        difficulty = _DEFAULT_DIFFICULTY

    return gap_id, concept_ids, difficulty


def _parse_gap_structure(text: str) -> tuple[list[Gap], frozenset[int]]:
    """The one implementation of "find every gap in this text." No I/O, no concept
    validation -- both callers (parse_master, render_student_file) need this; only
    parse_master needs the I/O-bearing concept check layered on top.

    Returns `(gaps, marker_lines)`. `marker_lines` is every 1-indexed line number that is
    NOT body -- `@gap:`, `@instruct:`, a plain-comment instruction continuation, or
    `@endgap` -- so a caller that needs to strip all non-body lines (render_student_file)
    has one authoritative set to check against, rather than re-deriving "is this a marker
    line" from its own copy of the marker regexes. That second copy is exactly what went
    stale here once: `render_student_file` originally re-checked
    `_GAP_START`/`_INSTRUCT`/`_GAP_END` on its own, which was correct until multi-line
    instruction continuation was added to THIS function and never propagated there --
    continuation lines leaked into rendered student files verbatim, caught only by
    actually reading a real rendered file, not by any test written before that (every
    test instruction happened to fit on one line). One returned set closes that gap by
    construction: there is no second definition of "marker line" left to drift.
    """
    lines = text.splitlines()
    gaps: list[Gap] = []
    seen_ids: set[str] = set()
    marker_lines: set[int] = set()
    current: dict | None = None

    for lineno, line in enumerate(lines, start=1):
        gap_start = _GAP_START.match(line)
        if gap_start is not None:
            if current is not None:
                raise GapParseError(
                    f"line {lineno}: @gap nested inside gap '{current['gap_id']}' "
                    f"(opened line {current['start_line']}, not yet closed)"
                )
            gap_id, concept_ids, difficulty = _parse_gap_header(line, lineno)
            if gap_id in seen_ids:
                raise GapParseError(f"line {lineno}: duplicate gap id '{gap_id}'")
            current = {
                "gap_id": gap_id, "concept_ids": concept_ids, "difficulty": difficulty,
                "start_line": lineno, "instruct_lines": [],
                "body_lines": [], "body_start": None,
            }
            marker_lines.add(lineno)
            continue

        if current is not None and current["body_start"] is None:
            instruct = _INSTRUCT.match(line)
            if instruct is not None:
                current["instruct_lines"].append(instruct.group(1))
                marker_lines.add(lineno)
                continue
            # A continuation line is only valid AFTER a real @instruct: has already been
            # seen (current["instruct_lines"] non-empty) -- otherwise a plain comment
            # with no marker at all would silently become "the instruction" and the
            # missing-@instruct check below would never fire, which is exactly the
            # silent-mis-parse this module exists to prevent. _GAP_END is excluded here
            # so `# @endgap` itself is never swallowed as continuation text.
            if current["instruct_lines"] and _GAP_END.match(line) is None:
                continuation = _COMMENT_CONTINUATION.match(line)
                if continuation is not None:
                    current["instruct_lines"].append(continuation.group(1).strip())
                    marker_lines.add(lineno)
                    continue

        if _GAP_END.match(line) is not None:
            if current is None:
                raise GapParseError(f"line {lineno}: @endgap with no matching @gap")
            if not current["instruct_lines"]:
                raise GapParseError(
                    f"line {lineno}: gap '{current['gap_id']}' has no @instruct line"
                )
            if not current["body_lines"]:
                raise GapParseError(
                    f"line {lineno}: gap '{current['gap_id']}' has an empty body"
                )
            gaps.append(Gap(
                gap_id=current["gap_id"],
                concept_ids=current["concept_ids"],
                line_start=current["body_start"],
                line_end=lineno - 1,
                instruction=" ".join(current["instruct_lines"]).strip(),
                difficulty=current["difficulty"],
                body="\n".join(current["body_lines"]),
            ))
            seen_ids.add(current["gap_id"])
            marker_lines.add(lineno)
            current = None
            continue

        if current is not None:
            if current["body_start"] is None:
                current["body_start"] = lineno
            current["body_lines"].append(line)

    if current is not None:
        raise GapParseError(
            f"line {current['start_line']}: unclosed @gap '{current['gap_id']}' "
            f"-- no @endgap found before end of file"
        )
    return gaps, frozenset(marker_lines)


def parse_master(
    path: str | Path, *, known_concepts: Collection[str] | None = None
) -> list[Gap]:
    """Read one master file and return its gap specs, validated.

    `known_concepts` defaults to `config.concepts.load()` (real taxonomy, cached) --
    overridable so tests can check the "unknown concept" failure mode without depending
    on config/concepts.yaml's exact contents staying stable. This is the only I/O this
    module does beyond the master file itself, and only here: `render_student_file`
    never needs to know what a valid concept is, only where a gap's text is.

    Raises GapParseError on: a duplicate gap_id, an unclosed @gap, a nested @gap, or any
    concept_id not present in the known taxonomy -- CLAUDE.md 10's "never invent
    structure" instinct applied to input: a gap tagged with a concept nobody defined
    would silently never contribute to that concept's mastery (no different, functionally,
    from invariant 10's unclassified-error case).
    """
    if known_concepts is None:
        known_concepts = set(concepts_module.load())

    text = Path(path).read_text(encoding="utf-8")
    gaps, _marker_lines = _parse_gap_structure(text)

    for gap in gaps:
        unknown = [c for c in gap.concept_ids if c not in known_concepts]
        if unknown:
            raise GapParseError(
                f"gap '{gap.gap_id}': unknown concept id(s) {unknown} -- "
                f"not present in config/concepts.yaml"
            )
    return gaps


def render_student_file(master_text: str, hide_gap_ids: Iterable[str]) -> str:
    """Produce the file a student actually receives: pure text transform, zero I/O.

    Marker lines (`# @gap:`, `# @instruct:` and its plain-comment continuation lines,
    `# @endgap`) are always stripped -- they are authoring metadata, never meant to reach
    a student's editor. Determined from `_parse_gap_structure`'s own returned
    `marker_lines`, not a second, local re-check of the marker regexes -- see that
    function's docstring for the actual bug this avoided repeating. For each gap_id in
    `hide_gap_ids`, its body is replaced by the instruction as one comment line plus
    `raise NotImplementedError()`, both at the SAME INDENTATION as the body's own first
    line -- nbgrader does exactly this (VDEL_REDESIGN.md 8.3), and getting the
    indentation wrong is not cosmetic: a dedented `raise` inside an indented block is a
    Python file that will not parse, which is the one failure this function exists to
    prevent. Gaps not named in `hide_gap_ids` keep their original body untouched, so an
    empty `hide_gap_ids` reproduces the master with only the markers removed -- that
    equivalence is `parse_master`'s and this function's shared correctness proof, the
    same "wipe and replay, get the same thing back" argument CLAUDE.md 4 makes for
    `traces`, applied here to a file instead of a database row.

    Raises GapParseError if `hide_gap_ids` names a gap that doesn't exist in
    `master_text` -- silently no-op'ing a typo'd id would leak that gap's real
    implementation to every student, which is worse than failing loudly.
    """
    hide = set(hide_gap_ids)
    gaps, marker_lines = _parse_gap_structure(master_text)
    gaps_by_id = {gap.gap_id: gap for gap in gaps}

    unknown_hides = hide - gaps_by_id.keys()
    if unknown_hides:
        raise GapParseError(
            f"hide_gap_ids names unknown gap id(s): {sorted(unknown_hides)}"
        )

    # Which gap (if any) owns each line number, precomputed once rather than rescanned
    # per line -- the body ranges never overlap (nesting is a parse error), so this is a
    # total, unambiguous map.
    owner_by_line: dict[int, Gap] = {
        lineno: gap
        for gap in gaps_by_id.values()
        for lineno in range(gap.line_start, gap.line_end + 1)
    }

    lines = master_text.splitlines()
    out: list[str] = []

    for lineno, line in enumerate(lines, start=1):
        if lineno in marker_lines:
            continue

        gap = owner_by_line.get(lineno)
        if gap is not None and gap.gap_id in hide:
            if lineno == gap.line_start:
                indent = re.match(r"[ \t]*", gap.body.splitlines()[0]).group(0)
                out.append(f"{indent}# {gap.instruction}")
                out.append(f"{indent}raise NotImplementedError()")
            continue

        out.append(line)

    # `str.splitlines()` discards the significance of a trailing "\n" -- it becomes
    # indistinguishable from "no trailing newline" once `"\n".join` puts the lines back
    # together, since join never emits a separator after the last element. Restored
    # explicitly rather than left to accident: a generated file silently losing its
    # trailing newline produces a noisy diff (most editors/git add one back) on every
    # single file this function ever touches, for no reason connected to gap hiding.
    rendered = "\n".join(out)
    if master_text.endswith("\n"):
        rendered += "\n"
    return rendered
