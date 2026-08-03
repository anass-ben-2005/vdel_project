"""Error classifier — the rule table from VDEL_Modules_1_2_Build.md Part C.

The classifier is called "the load-bearing risk" in the document because it feeds three
variables (Mastery, Error Response, Error Frequency), so a misclassification silently
corrupts mastery. These tests weight false positives accordingly: an unmatched error
costs one observation, a wrong match costs a mastery score for a concept the student
never touched.
"""
import pytest

from collectors.error_classifier import RULES, classify_error, match_rate
from config import concepts


@pytest.mark.parametrize(
    "log,expected",
    [
        ("AnalysisException: Reference 'id' is ambiguous column", "spark.joins"),
        ("cannot resolve 'amt' given input columns: [a, b]", "spark.df_basics"),
        ("AnalysisException: expression not in group by", "spark.aggregation"),
        ("column 'x' is neither present in the group by", "sql.aggregation"),
        ("Detected implicit cartesian product for INNER join", "spark.joins"),
        ("java.lang.OutOfMemoryError: GC overhead limit exceeded", "spark.partitioning"),
        ("KeyError: 'customer_id'", "py.data_structures"),
        ("SettingWithCopyWarning: A value is trying to be set on a copy", "py.pandas"),
        ("  File 'etl.py', line 2\nSyntaxError: invalid syntax", "py.errors_debugging"),
        ("E   AssertionError: assert 3 == 4", "py.testing"),
    ],
)
def test_each_documented_rule_fires(log, expected):
    _, concept = classify_error(log)
    assert concept == expected


def test_unmatched_is_unclassified_and_never_guessed():
    """'NEVER force a wrong guess: an unmatched error updates NO mastery.'"""
    error_class, concept = classify_error("Cleaning up orphan processes")
    assert concept == "unclassified"
    assert error_class == "unmatched"


def test_empty_log_is_distinguishable_from_unmatched():
    """Different causes get different error_class values, so the coverage report can
    tell 'we had no log' apart from 'we had a log and no rule fit'."""
    assert classify_error("") == ("empty", "unclassified")
    assert classify_error(None) == ("empty", "unclassified")


def test_first_match_wins():
    """Rule order is part of the specification. A log matching two rules must resolve to
    the earlier one, deterministically."""
    both = "ambiguous column and also a KeyError here"
    assert classify_error(both)[1] == "spark.joins"


def test_unclassified_errors_are_excluded_from_mastery_by_the_query():
    """Invariant 10 is enforced in SQL, not by convention. If this literal disappears
    from the query, unclassified errors start moving mastery scores silently."""
    from pathlib import Path
    source = Path("features/compute_features.py").read_text(encoding="utf-8")
    assert "concept_id <> 'unclassified'" in source


def test_every_rule_maps_to_a_concept_in_the_taxonomy():
    """The classifier and concepts.yaml drift apart silently otherwise: a typo'd id
    would route errors into a bucket nothing else in the system knows about."""
    known = concepts.ids()
    unknown = sorted({c for _, c in RULES if c not in known})
    assert not unknown, f"rules reference concepts absent from concepts.yaml: {unknown}"


def test_match_rate_is_reportable():
    """BUILD_PLAN 1.5 requires the match rate to be logged."""
    assert match_rate([("x", "spark.joins"), ("unmatched", "unclassified")]) == 0.5
    assert match_rate([]) == 0.0
