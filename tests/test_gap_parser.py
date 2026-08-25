"""assessment/gap_parser.py tests. CLAUDE.md 5 / VDEL_REDESIGN.md 8.3.

Concept ids used below are real (config/concepts.yaml): py.errors_debugging, py.testing,
airflow.idempotency. The task description's own example (`python.control_flow`,
`api.retry`) does not exist in the real taxonomy and would fail parse_master's own
concept-existence check -- using it here would test nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from assessment.gap_parser import Gap, GapParseError, parse_master, render_student_file

KNOWN = {"py.errors_debugging", "py.testing", "airflow.idempotency"}


def write_master(tmp_path, text):
    path = tmp_path / "master.py"
    path.write_text(text, encoding="utf-8")
    return path


# ---------- indentation preserved, at increasing depth ----------

def test_indentation_preserved_at_module_level():
    master = (
        "# @gap:id=g_top concepts=[py.testing] difficulty=0.5\n"
        "# @instruct: Assign the retry count.\n"
        "retries = MAX_ATTEMPTS\n"
        "# @endgap\n"
    )
    rendered = render_student_file(master, hide_gap_ids=["g_top"])
    assert rendered == (
        "# Assign the retry count.\n"
        "raise NotImplementedError()\n"
    )


def test_indentation_preserved_inside_a_function():
    master = (
        "def run():\n"
        "    # @gap:id=g_fn concepts=[py.testing] difficulty=0.5\n"
        "    # @instruct: Return the retry count.\n"
        "    return retries\n"
        "    # @endgap\n"
    )
    rendered = render_student_file(master, hide_gap_ids=["g_fn"])
    assert rendered == (
        "def run():\n"
        "    # Return the retry count.\n"
        "    raise NotImplementedError()\n"
    )


def test_indentation_preserved_inside_a_nested_block():
    master = (
        "def run():\n"
        "    if True:\n"
        "        # @gap:id=g_block concepts=[py.testing] difficulty=0.5\n"
        "        # @instruct: Return the retry count.\n"
        "        return retries\n"
        "        # @endgap\n"
    )
    rendered = render_student_file(master, hide_gap_ids=["g_block"])
    assert rendered == (
        "def run():\n"
        "    if True:\n"
        "        # Return the retry count.\n"
        "        raise NotImplementedError()\n"
    )


# ---------- nested-function gap ----------

def test_gap_inside_a_nested_function_definition(tmp_path):
    """A gap whose surrounding CODE is a function defined inside another function --
    distinct from a nested @gap MARKER (that's a parse error, tested below). Real
    nested-def shape, 8-space indentation, exercised through parse_master end to end."""
    master_text = (
        "def outer():\n"
        "    def inner():\n"
        "        # @gap:id=g_inner concepts=[py.testing] difficulty=0.4\n"
        "        # @instruct: Return the number of retries attempted.\n"
        "        return retries\n"
        "        # @endgap\n"
        "    return inner\n"
    )
    path = write_master(tmp_path, master_text)

    [gap] = parse_master(path, known_concepts=KNOWN)
    assert gap.gap_id == "g_inner"
    assert gap.line_start == 5 and gap.line_end == 5
    assert gap.body == "        return retries"

    rendered = render_student_file(master_text, hide_gap_ids=["g_inner"])
    assert rendered == (
        "def outer():\n"
        "    def inner():\n"
        "        # Return the number of retries attempted.\n"
        "        raise NotImplementedError()\n"
        "    return inner\n"
    )


# ---------- duplicate id ----------

def test_duplicate_gap_id_raises(tmp_path):
    master = (
        "# @gap:id=g_a concepts=[py.testing] difficulty=0.5\n"
        "# @instruct: First.\n"
        "x = 1\n"
        "# @endgap\n"
        "# @gap:id=g_a concepts=[py.testing] difficulty=0.5\n"
        "# @instruct: Second, same id.\n"
        "y = 2\n"
        "# @endgap\n"
    )
    path = write_master(tmp_path, master)
    with pytest.raises(GapParseError, match="duplicate gap id 'g_a'"):
        parse_master(path, known_concepts=KNOWN)


# ---------- unknown concept ----------

def test_unknown_concept_raises(tmp_path):
    master = (
        "# @gap:id=g_a concepts=[python.control_flow] difficulty=0.5\n"
        "# @instruct: Do the thing.\n"
        "x = 1\n"
        "# @endgap\n"
    )
    path = write_master(tmp_path, master)
    with pytest.raises(GapParseError, match="unknown concept"):
        parse_master(path, known_concepts=KNOWN)


def test_unknown_concept_check_uses_the_real_taxonomy_by_default(tmp_path):
    """No known_concepts override -- confirms config.concepts.load() is really wired in,
    not just the injectable test seam."""
    master = (
        "# @gap:id=g_a concepts=[definitely.not.a.real.concept] difficulty=0.5\n"
        "# @instruct: Do the thing.\n"
        "x = 1\n"
        "# @endgap\n"
    )
    path = write_master(tmp_path, master)
    with pytest.raises(GapParseError, match="unknown concept"):
        parse_master(path)


# ---------- round-trip ----------

def test_round_trip_with_no_hidden_gaps_returns_master_minus_marker_lines():
    master = (
        "import sys\n"
        "\n"
        "# @gap:id=g_a concepts=[py.testing] difficulty=0.5\n"
        "# @instruct: Assign x.\n"
        "x = 1\n"
        "# @endgap\n"
        "\n"
        "def run():\n"
        "    # @gap:id=g_b concepts=[airflow.idempotency] difficulty=0.6\n"
        "    # @instruct: Return x doubled.\n"
        "    return x * 2\n"
        "    # @endgap\n"
    )
    expected = (
        "import sys\n"
        "\n"
        "x = 1\n"
        "\n"
        "def run():\n"
        "    return x * 2\n"
    )
    assert render_student_file(master, hide_gap_ids=[]) == expected


def test_round_trip_is_the_same_as_hiding_nothing_explicitly():
    """hide_gap_ids=[] and hide_gap_ids naming no real gap are the same request."""
    master = (
        "# @gap:id=g_a concepts=[py.testing] difficulty=0.5\n"
        "# @instruct: Assign x.\n"
        "x = 1\n"
        "# @endgap\n"
    )
    assert render_student_file(master, []) == render_student_file(master, set())


def test_trailing_newline_is_preserved_not_silently_dropped():
    """`str.splitlines()` + `"\\n".join(...)` loses the master's own trailing newline by
    construction (join never emits a separator after the last element) -- a generated
    file silently losing it would produce a noisy diff on every file this function ever
    touches, unrelated to what was actually hidden. Checked at both one trailing newline
    and a genuine trailing blank line (two newlines), plus the no-trailing-newline case,
    so the fix isn't just tuned to the one case that was checked by eye."""
    master_one_newline = (
        "def outer():\n"
        "    def inner():\n"
        "        # @gap:id=g_inner concepts=[py.testing] difficulty=0.4\n"
        "        # @instruct: Return the number of retries attempted.\n"
        "        return retries\n"
        "        # @endgap\n"
        "    return inner\n"
    )
    rendered = render_student_file(master_one_newline, hide_gap_ids=["g_inner"])
    assert rendered.endswith("\n") and not rendered.endswith("\n\n")

    master_blank_trailing_line = master_one_newline + "\n"   # a real trailing blank line
    rendered_blank = render_student_file(master_blank_trailing_line, hide_gap_ids=["g_inner"])
    assert rendered_blank == rendered + "\n"

    master_no_trailing_newline = master_one_newline.rstrip("\n")
    rendered_none = render_student_file(master_no_trailing_newline, hide_gap_ids=["g_inner"])
    assert not rendered_none.endswith("\n")


# ---------- other fail-loudly cases the implementation commits to ----------

def test_nested_gap_marker_raises(tmp_path):
    master = (
        "# @gap:id=g_outer concepts=[py.testing] difficulty=0.5\n"
        "# @instruct: Outer.\n"
        "# @gap:id=g_inner concepts=[py.testing] difficulty=0.5\n"
        "# @instruct: Inner.\n"
        "x = 1\n"
        "# @endgap\n"
        "# @endgap\n"
    )
    path = write_master(tmp_path, master)
    with pytest.raises(GapParseError, match="nested"):
        parse_master(path, known_concepts=KNOWN)


def test_unclosed_gap_raises(tmp_path):
    master = (
        "# @gap:id=g_a concepts=[py.testing] difficulty=0.5\n"
        "# @instruct: Never closed.\n"
        "x = 1\n"
    )
    path = write_master(tmp_path, master)
    with pytest.raises(GapParseError, match="unclosed"):
        parse_master(path, known_concepts=KNOWN)


def test_orphan_endgap_raises(tmp_path):
    master = "# @endgap\n"
    path = write_master(tmp_path, master)
    with pytest.raises(GapParseError, match="no matching @gap"):
        parse_master(path, known_concepts=KNOWN)


def test_hiding_an_unknown_gap_id_raises():
    master = (
        "# @gap:id=g_a concepts=[py.testing] difficulty=0.5\n"
        "# @instruct: Assign x.\n"
        "x = 1\n"
        "# @endgap\n"
    )
    with pytest.raises(GapParseError, match="unknown gap id"):
        render_student_file(master, hide_gap_ids=["g_typo"])


def test_gaps_not_in_hide_gap_ids_keep_their_original_body():
    master = (
        "# @gap:id=g_a concepts=[py.testing] difficulty=0.5\n"
        "# @instruct: Assign x.\n"
        "x = 1\n"
        "# @endgap\n"
        "# @gap:id=g_b concepts=[py.testing] difficulty=0.5\n"
        "# @instruct: Assign y.\n"
        "y = 2\n"
        "# @endgap\n"
    )
    rendered = render_student_file(master, hide_gap_ids=["g_a"])
    assert rendered == (
        "# Assign x.\n"
        "raise NotImplementedError()\n"
        "y = 2\n"
    )


def test_difficulty_defaults_to_the_schemas_own_default(tmp_path):
    """sql/06_assessment_tables.sql: `gaps.difficulty REAL NOT NULL DEFAULT 0.5`."""
    master = (
        "# @gap:id=g_a concepts=[py.testing]\n"
        "# @instruct: Assign x.\n"
        "x = 1\n"
        "# @endgap\n"
    )
    path = write_master(tmp_path, master)
    [gap] = parse_master(path, known_concepts=KNOWN)
    assert gap.difficulty == 0.5


def test_missing_instruct_raises(tmp_path):
    master = (
        "# @gap:id=g_a concepts=[py.testing] difficulty=0.5\n"
        "x = 1\n"
        "# @endgap\n"
    )
    path = write_master(tmp_path, master)
    with pytest.raises(GapParseError, match="no @instruct"):
        parse_master(path, known_concepts=KNOWN)


def test_concept_ids_and_line_range_are_captured_correctly(tmp_path):
    master = (
        "# @gap:id=g_multi concepts=[py.testing,airflow.idempotency] difficulty=0.7\n"
        "# @instruct: Do two things.\n"
        "a = 1\n"
        "b = 2\n"
        "# @endgap\n"
    )
    path = write_master(tmp_path, master)
    [gap] = parse_master(path, known_concepts=KNOWN)
    assert gap == Gap(
        gap_id="g_multi",
        concept_ids=("py.testing", "airflow.idempotency"),
        line_start=3,
        line_end=4,
        instruction="Do two things.",
        difficulty=0.7,
        body="a = 1\nb = 2",
    )


def test_multiline_instruction_via_plain_comment_continuation(tmp_path):
    """Found necessary from real content (curriculum/master/weather_etl/extract.py):
    a sentence too long for one line continues on plain `#` comment lines with no
    `@instruct:` marker of their own, rather than repeating the marker on every line."""
    master = (
        "def run():\n"
        "    # @gap:id=g_a concepts=[py.testing] difficulty=0.5\n"
        "    # @instruct: First part of the sentence,\n"
        "    #            second part of the sentence,\n"
        "    #            and the third part.\n"
        "    return 1\n"
        "    # @endgap\n"
    )
    path = write_master(tmp_path, master)
    [gap] = parse_master(path, known_concepts=KNOWN)
    assert gap.instruction == (
        "First part of the sentence, second part of the sentence, and the third part."
    )
    assert gap.line_start == 6 and gap.line_end == 6   # comment lines are NOT the body
    assert gap.body == "    return 1"


def test_render_strips_continuation_lines_not_just_the_first_instruct_line():
    """The actual regression: render_student_file used to re-derive "is this a marker
    line" from its own copy of the marker regexes, which had no idea about plain-comment
    continuation lines -- they leaked into the rendered file verbatim, ahead of the
    injected replacement, caught only by reading a real rendered file by eye (every
    prior test's instruction fit on one line). Both functions now share
    _parse_gap_structure's own returned marker_lines, so there is no second definition
    left to go stale."""
    master = (
        "def run():\n"
        "    # @gap:id=g_a concepts=[py.testing] difficulty=0.5\n"
        "    # @instruct: First part of the sentence,\n"
        "    #            second part,\n"
        "    #            and the third part.\n"
        "    return 1\n"
        "    # @endgap\n"
    )
    rendered = render_student_file(master, hide_gap_ids=["g_a"])
    assert rendered == (
        "def run():\n"
        "    # First part of the sentence, second part, and the third part.\n"
        "    raise NotImplementedError()\n"
    )


# ---------- real curriculum content: Project 2 (sales_analyzer) ----------
# VDEL_TEN_PROJECT_CURRICULUM.md §3. Reuses this file's existing harness (parse_master
# against a real path) rather than a parallel test file -- same pattern §0's own
# "author Project 1 fully, then scale" instruction implies for verification too.

_SALES_ANALYZER_ROOT = (
    Path(__file__).resolve().parent.parent
    / "curriculum" / "master" / "sales_analyzer" / "sales_analyzer"
)


def test_sales_analyzer_ingest_parses_its_two_real_gaps():
    gaps = parse_master(_SALES_ANALYZER_ROOT / "ingest.py")
    assert [g.gap_id for g in gaps] == ["g_ing_dtype", "g_ing_malformed"]
    assert gaps[0].concept_ids == ("py.pandas",)
    assert gaps[1].concept_ids == ("py.errors_debugging",)


def test_sales_analyzer_clean_parses_its_two_real_gaps():
    gaps = parse_master(_SALES_ANALYZER_ROOT / "clean.py")
    assert [g.gap_id for g in gaps] == ["g_cl_dedupe", "g_cl_fillna"]
    assert all(g.concept_ids == ("py.pandas",) for g in gaps)


def test_sales_analyzer_aggregate_parses_its_two_real_gaps():
    gaps = parse_master(_SALES_ANALYZER_ROOT / "aggregate.py")
    assert [g.gap_id for g in gaps] == ["g_ag_revenue", "g_ag_top"]
    assert gaps[0].concept_ids == ("sql.aggregation",)
    assert gaps[1].concept_ids == ("py.data_structures",)


def test_sales_analyzer_load_parses_its_one_real_gap():
    [gap] = parse_master(_SALES_ANALYZER_ROOT / "load.py")
    assert gap.gap_id == "g_ld_write"
    assert gap.concept_ids == ("sql.select_filter",)


def test_sales_analyzer_concept_tally_matches_vdel_ten_project_curriculum_section_3():
    """§3's own stated tally: py.pandas x3, py.errors_debugging x1,
    py.data_structures x1, sql.aggregation x1, sql.select_filter x1."""
    all_gaps = [
        g
        for f in ("ingest.py", "clean.py", "aggregate.py", "load.py")
        for g in parse_master(_SALES_ANALYZER_ROOT / f)
    ]
    assert len(all_gaps) == 7
    tally: dict[str, int] = {}
    for g in all_gaps:
        for c in g.concept_ids:
            tally[c] = tally.get(c, 0) + 1
    assert tally == {
        "py.pandas": 3,
        "py.errors_debugging": 1,
        "py.data_structures": 1,
        "sql.aggregation": 1,
        "sql.select_filter": 1,
    }


def test_a_comment_with_no_instruct_marker_at_all_still_raises(tmp_path):
    """A plain comment continuation is only recognised AFTER a real @instruct: has
    already opened -- a gap with no @instruct: at all must still raise, not silently
    treat its first comment as the instruction."""
    master = (
        "# @gap:id=g_a concepts=[py.testing] difficulty=0.5\n"
        "# just a comment, no marker\n"
        "x = 1\n"
        "# @endgap\n"
    )
    path = write_master(tmp_path, master)
    with pytest.raises(GapParseError, match="no @instruct"):
        parse_master(path, known_concepts=KNOWN)
