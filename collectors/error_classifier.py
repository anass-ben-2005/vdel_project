"""
collectors/error_classifier.py — map a CI failure log to a taxonomy concept.
v1: rule table + explicit 'unclassified' fallback. NEVER force a wrong guess:
an unmatched error updates NO mastery (better to update nothing than the wrong concept).
The low BKT learning rate further limits the damage of any single misclassification.

Transcribed from VDEL_Modules_1_2_Build.md Part C. The rule table is the document's,
including its ordering -- first match wins, so the order is part of the specification.
The document's closing comment ("extend to your ~15 most common real failures") is the
sanctioned extension point; extend from observed logs, not from imagination.
"""
import re

RULES = [
    (r"ambiguous column",                       "spark.joins"),
    (r"cannot resolve .* given input columns",  "spark.df_basics"),
    (r"AnalysisException.*group by",            "spark.aggregation"),
    (r"is neither present in the group by",     "sql.aggregation"),
    (r"cartesian product|cross join",           "spark.joins"),
    (r"OutOfMemory|GC overhead",                "spark.partitioning"),
    (r"KeyError|IndexError",                    "py.data_structures"),
    (r"SettingWithCopyWarning",                 "py.pandas"),
    (r"SyntaxError|IndentationError",           "py.errors_debugging"),
    (r"AssertionError",                         "py.testing"),
    # extend to your ~15 most common real failures
]

UNCLASSIFIED = "unclassified"


def classify_error(log_text: str):
    """Returns (error_class, concept_id). 'unclassified' if no rule fits."""
    if not log_text:
        return ("empty", "unclassified")
    for pattern, concept in RULES:
        if re.search(pattern, log_text, re.IGNORECASE):
            return (pattern, concept)
    return ("unmatched", "unclassified")


def match_rate(classifications) -> float:
    """Share of classified failures that mapped to a real concept.

    BUILD_PLAN 1.5 and the Execution Plan both require the match rate to be logged.
    Added here because the document specifies the measurement but not the helper.
    A low rate is a finding to report, not a number to inflate by loosening rules --
    every rule loosened to raise it buys coverage with misattributed mastery.
    """
    if not classifications:
        return 0.0
    matched = sum(1 for _, concept in classifications if concept != UNCLASSIFIED)
    return round(matched / len(classifications), 3)
