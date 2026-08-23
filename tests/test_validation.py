"""agents/validation.py — M4 task 4.4, the evidence check.

The test that matters most here is `test_fabricated_quote_is_caught`. Invariant 6 says a
fabricated quote rejects the verdict, and the entire defence against a hallucinating judge
is that one string comparison. If it silently stopped working, every downstream number would
still look plausible — which is the exact profile of the three drift incidents in
`DEVELOPMENT_MAP.md` §0.

**No database and no provider key.** `validation.py` is a pure function of `(verdict, code)`,
so unlike `tests/test_echo_agent.py` and `tests/test_memory.py` there is no `PG_DSN` skip
guard: these tests run everywhere, always, including in CI before any credential exists.
That is a deliberate property of the module, and `test_module_imports_no_database` pins it.
"""
import re
from pathlib import Path

import pytest

from agents.validation import (
    CRITERIA,
    MATCH_EXACT,
    MATCH_WHITESPACE,
    MISSING_EVIDENCE,
    UNKNOWN_CRITERION,
    UNMATCHED_QUOTE,
    evidence_report,
    rejects_verdict,
    validate_evidence,
)

# A submission with the features that break naive matching: an indented block, a line
# containing " + " (which D.5's split would truncate), and a string literal.
CODE = '''
import pandas as pd


def load_sales(path):
    df = pd.read_csv(path)
    df = df.dropna(subset=["order_id"])
    return df


def total_revenue(df):
    total = df["qty"] + df["price"] + df["tax"]
    return total.sum()
'''


def _verdict(evidence):
    """A minimal duck-typed verdict. `validate_evidence` reads only `.evidence`."""
    class V:
        pass

    v = V()
    v.evidence = evidence
    return v


def _all_criteria(quote):
    """Evidence that gives every criterion the same real quote — the fully-evidenced case."""
    return {criterion: [quote] for criterion in CRITERIA}


# ---- The one that matters ----------------------------------------------------------------

def test_fabricated_quote_is_caught():
    """A quote that is nowhere in the submission fails, and the failure rejects the verdict."""
    evidence = _all_criteria("df = pd.read_csv(path)")
    evidence["correctness"] = ['df.groupBy("region").agg(sum("total"))']

    failures = validate_evidence(_verdict(evidence), CODE)

    fabrications = [f for f in failures if f["kind"] == UNMATCHED_QUOTE]
    assert len(fabrications) == 1
    assert fabrications[0]["criterion"] == "correctness"
    assert fabrications[0]["unmatched_quote"] == 'df.groupBy("region").agg(sum("total"))'
    assert rejects_verdict(failures) is True


def test_fully_evidenced_verdict_has_no_failures():
    """The honest case must be clean, or the check is useless noise."""
    failures = validate_evidence(_verdict(_all_criteria("df = pd.read_csv(path)")), CODE)
    assert failures == []
    assert rejects_verdict(failures) is False


# ---- Deviation 1: the "quote + why" string form, and " + " inside code --------------------

def test_quote_plus_why_string_form_is_parsed():
    """D.5's `"quoted line + why"` convention still validates unchanged."""
    evidence = _all_criteria(
        'df = df.dropna(subset=["order_id"]) + drops rows with no order id'
    )
    assert validate_evidence(_verdict(evidence), CODE) == []


def test_code_containing_plus_is_not_truncated_into_a_false_pass():
    """The deviation-1 case: a quoted line whose own text contains `" + "`.

    D.5's `q.split(" + ")[0]` shortens this to `total = df["qty"]`, which happens to be in
    the code, so D.5 passes it — but it verified a fragment, not the quote. Whole-string-first
    matching verifies the entire line, and `evidence_report` shows it matched exactly.
    """
    quote = 'total = df["qty"] + df["price"] + df["tax"]'
    report = evidence_report(_verdict(_all_criteria(quote)), CODE)

    correctness = [r for r in report if r["criterion"] == "correctness"]
    assert correctness[0]["quote"] == quote           # the whole line, not a fragment
    assert correctness[0]["match_level"] == MATCH_EXACT


def test_dict_evidence_form_needs_no_parsing():
    """The `{"quote": ..., "why": ...}` form removes the ambiguity entirely."""
    entry = {"quote": 'total = df["qty"] + df["price"] + df["tax"]',
             "why": "sums the three columns"}
    evidence = {criterion: [entry] for criterion in CRITERIA}
    assert validate_evidence(_verdict(evidence), CODE) == []


def test_dict_form_still_catches_fabrication():
    """The structured form must not become an escape hatch from the check."""
    evidence = _all_criteria("df = pd.read_csv(path)")
    evidence["readability"] = [{"quote": "def nonexistent_helper():", "why": "invented"}]

    failures = validate_evidence(_verdict(evidence), CODE)
    assert any(f["kind"] == UNMATCHED_QUOTE and f["criterion"] == "readability"
               for f in failures)
    assert rejects_verdict(failures) is True


# ---- Deviation 2: silence is a failure ---------------------------------------------------

def test_scored_criterion_with_no_evidence_is_reported():
    """D.5 returns no failures for an empty list. Invariant 6 says every score is evidenced.

    This is the hole deviation 2 closes: without it a judge can score 4/4 across the board,
    quote nothing at all, and pass the evidence check untouched.
    """
    evidence = _all_criteria("df = pd.read_csv(path)")
    evidence["idiomatic"] = []

    failures = validate_evidence(_verdict(evidence), CODE)
    missing = [f for f in failures if f["kind"] == MISSING_EVIDENCE]
    assert len(missing) == 1
    assert missing[0]["criterion"] == "idiomatic"


def test_empty_evidence_reports_every_criterion():
    """A verdict quoting nothing fails once per criterion, not once in total."""
    failures = validate_evidence(_verdict({}), CODE)
    assert len(failures) == len(CRITERIA)
    assert {f["criterion"] for f in failures} == set(CRITERIA)
    assert all(f["kind"] == MISSING_EVIDENCE for f in failures)


def test_missing_evidence_flags_but_does_not_reject():
    """The deliberate asymmetry: fabrication rejects, silence flags. See the module docstring."""
    failures = validate_evidence(_verdict({}), CODE)
    assert failures                      # it is reported
    assert rejects_verdict(failures) is False   # but it is not a rejection


# ---- Deviation 3: the match ladder -------------------------------------------------------

def test_reindented_quote_matches_at_the_whitespace_level():
    """An LLM re-indenting a quoted line has not fabricated anything."""
    evidence = _all_criteria('df   =    pd.read_csv(path)')
    report = evidence_report(_verdict(evidence), CODE)

    assert validate_evidence(_verdict(evidence), CODE) == []
    assert all(r["match_level"] == MATCH_WHITESPACE for r in report)


def test_multiline_quote_with_normalised_indentation_matches():
    """The realistic re-indentation case: two real lines, quoted without their leading spaces."""
    evidence = _all_criteria(
        'df = pd.read_csv(path)\ndf = df.dropna(subset=["order_id"])'
    )
    assert validate_evidence(_verdict(evidence), CODE) == []


def test_case_is_not_folded():
    """Identifiers are case-sensitive: `DF` is not `df`, and must not be normalised into it."""
    evidence = _all_criteria("DF = PD.READ_CSV(PATH)")
    failures = validate_evidence(_verdict(evidence), CODE)
    assert rejects_verdict(failures) is True


def test_operator_is_not_normalised_away():
    """`!=` is not `==`. A fabricated comparison must not match its opposite."""
    evidence = _all_criteria('df = df.dropna(subset=["order_id"])')
    evidence["approach"] = ['if df["qty"] != 0:']
    failures = validate_evidence(_verdict(evidence), CODE)
    assert any(f["kind"] == UNMATCHED_QUOTE for f in failures)


# ---- Shape and contract ------------------------------------------------------------------

def test_criteria_match_echo():
    """One source of truth for the four criteria and their order.

    `validation.py` declares `CRITERIA` locally rather than importing it, to stay free of the
    database layer (see its module docstring). This test is what makes that copy safe: if
    Echo's tuple ever changes, this fails rather than the two drifting apart in silence.
    """
    from agents.echo_agent import CRITERIA as ECHO_CRITERIA
    assert CRITERIA == ECHO_CRITERIA


def test_accepts_a_plain_dict_verdict():
    """The audit path reads verdicts back out of trace payloads as dicts, not models."""
    payload = {"evidence": _all_criteria("df = pd.read_csv(path)"), "confidence": "high"}
    assert validate_evidence(payload, CODE) == []


def test_unknown_criterion_is_reported():
    """Evidence filed under a name that is not one of the four answers an unasked question."""
    evidence = _all_criteria("df = pd.read_csv(path)")
    evidence["elegance"] = ["df = pd.read_csv(path)"]

    failures = validate_evidence(_verdict(evidence), CODE)
    unknown = [f for f in failures if f["kind"] == UNKNOWN_CRITERION]
    assert len(unknown) == 1
    assert unknown[0]["criterion"] == "elegance"


def test_failure_records_keep_d5_keys():
    """D.5's readers destructure `criterion` and `unmatched_quote`; additions never replace."""
    evidence = _all_criteria("nonexistent_function()")
    for failure in validate_evidence(_verdict(evidence), CODE):
        assert "criterion" in failure
        assert "unmatched_quote" in failure
        assert "kind" in failure


def test_lone_entry_where_a_list_was_expected():
    """A model emitting a bare string instead of a one-element list is a schema slip, not a
    fabrication, and must not be reported as one."""
    evidence = dict.fromkeys(CRITERIA, "df = pd.read_csv(path)")
    assert validate_evidence(_verdict(evidence), CODE) == []


@pytest.mark.parametrize("junk", [None, 42, [], {}, [None], [42]])
def test_malformed_evidence_never_raises(junk):
    """Malformed evidence is a flagged verdict, never a crash in the grading pipeline."""
    evidence = dict.fromkeys(CRITERIA, junk)
    failures = validate_evidence(_verdict(evidence), CODE)
    assert isinstance(failures, list)


def test_module_imports_no_database():
    """`validation.py` must stay free of the DB layer, or its tests stop running without one.

    Checked by reading the source rather than by import side effects, because `memory.memory`
    may already be imported by another test module in the same session.
    """
    source = Path(__file__).resolve().parents[1] / "agents" / "validation.py"
    text = source.read_text(encoding="utf-8")
    imports = re.findall(r"^\s*(?:from|import)\s+(\S+)", text, re.MULTILINE)
    assert not any(m.startswith(("memory", "system", "psycopg2")) for m in imports), imports
