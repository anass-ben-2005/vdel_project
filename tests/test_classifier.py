"""Classifier tests, weighted towards false positives.

A miss costs one observation (invariant 10: no concept means no mastery update). A false
positive moves a mastery score for a concept the student never touched, and mastery
scores are what a grade is defended with. The tests are asymmetric for the same reason
the rules are.
"""

from __future__ import annotations

import pytest

from collectors.error_classifier import UNCLASSIFIED, classify, classify_run, match_rate

# A perfectly ordinary Actions log. Contains "action" and ".join(" -- the two substrings
# the previous rule set matched on, which would have labelled this spark.dataframe.
BENIGN_LOG = """
Run actions/checkout@v4
  with:
    repository: student/kaggle-pipeline
Requested labels: ubuntu-latest
  path = os.sep.join(parts)
Cleaning up orphan processes
"""


def test_benign_log_is_not_classified():
    assert classify(BENIGN_LOG) == (UNCLASSIFIED, None)


@pytest.mark.parametrize(
    "log,expected_concept",
    [
        ('Traceback (most recent call last):\n  x = d["k"]\nKeyError: \'k\'',
         "python.control_flow"),
        ("  import pandas\nModuleNotFoundError: No module named 'pandas'", "python.basics"),
        ("  File \"a.py\", line 2\nSyntaxError: invalid syntax", "python.basics"),
        ('psycopg2.errors.UndefinedColumn: column "custmer_id" does not exist', "sql.joins"),
        ("ERROR: syntax error at or near \"SELCT\"", "sql.select"),
        ("pyspark.sql.utils.AnalysisException: cannot resolve 'amt'", "spark.dataframe"),
        ("psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint",
         "airflow.idempotency"),
        ("E       assert 3 == 4\nAssertionError", "testing"),
    ],
)
def test_real_errors_map_to_a_concept(log, expected_concept):
    error_class, concept_id = classify(log)
    assert concept_id == expected_concept
    assert error_class != UNCLASSIFIED


def test_the_word_join_alone_does_not_imply_sql():
    assert classify("result = ','.join(names)") == (UNCLASSIFIED, None)


def test_the_word_action_alone_does_not_imply_spark():
    assert classify("Every action has a reaction") == (UNCLASSIFIED, None)


def test_success_is_not_an_error():
    assert classify_run("success", None) == (None, None)


def test_infrastructure_outcomes_blame_no_concept():
    """A cancelled run is not the student's doing and must not move a mastery score."""
    for conclusion in ("cancelled", "skipped", "stale"):
        _, concept_id = classify_run(conclusion, "AssertionError: boom")
        assert concept_id is None


def test_unclassified_failure_yields_no_concept():
    """Invariant 10, at its source."""
    _, concept_id = classify_run("failure", BENIGN_LOG)
    assert concept_id is None


def test_match_rate_ignores_runs_nobody_could_classify():
    results = [
        ("python_type", "python.functions"),
        (UNCLASSIFIED, None),
        ("cancelled", None),   # excluded from the denominator
        (None, None),          # a success, also excluded
    ]
    assert match_rate(results) == 0.5


def test_every_rule_points_at_a_real_concept():
    """The taxonomy and the classifier drift apart silently otherwise: a typo'd concept
    id would classify errors into a bucket nothing else knows about."""
    from collectors.error_classifier import RULES
    from config import concepts

    known = concepts.ids()
    unknown = sorted({cid for _, cid, _ in RULES if cid not in known})
    assert not unknown, f"rules reference concepts absent from concepts.yaml: {unknown}"
