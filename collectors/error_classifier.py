"""Map a CI failure log to (error_class, concept_id).

Precision over recall, deliberately. Invariant 10 says an unclassified error updates no
mastery, which makes a miss cheap: one lost observation. A false positive is expensive:
it moves a mastery score for a concept the student never touched, and mastery scores are
what the grade is defended with.

The previous rule set optimised the wrong way. `r'DataFrame|RDD|transformation|action'`
matches the word "action", which appears in the header of every GitHub Actions log, so
every failure would have been classified as spark.dataframe. A bare `JOIN` matches any
traceback containing str.join(). The match rate would have looked excellent and the
concept mapping would have been noise.

TODO(verify): BUILD_PLAN 1.5 specifies roughly ten rules from
VDEL_Modules_1_2_Build.md. That document is not in the repo, so these are placeholders
built to the right shape. Replace the table, keep the machinery.
"""

from __future__ import annotations

import re

UNCLASSIFIED = "unclassified"


def _rule(error_class: str, concept_id: str, pattern: str, flags: int = re.MULTILINE):
    """One rule. MULTILINE by default so `^` anchors to a line, not to the whole log --
    which is what makes "the line that starts with TypeError:" expressible at all."""
    return (error_class, concept_id, re.compile(pattern, flags))


IGNORE_CASE = re.MULTILINE | re.IGNORECASE

# (error_class, concept_id, pattern). First match wins, so order is meaningful:
# specific patterns precede general ones.
RULES: list[tuple[str, str, re.Pattern[str]]] = [
    # Python exceptions, anchored to the traceback's final line ("SomeError: message"),
    # so the word only counts where the interpreter actually raised it.
    _rule("python_syntax", "python.basics", r"^\s*(SyntaxError|IndentationError|TabError):"),
    _rule("python_import", "python.basics", r"^\s*(ImportError|ModuleNotFoundError):"),
    _rule("python_name", "python.control_flow", r"^\s*NameError:"),
    _rule("python_type", "python.functions", r"^\s*TypeError:"),
    _rule("python_attribute", "python.functions", r"^\s*AttributeError:"),
    _rule("python_key_index", "python.control_flow", r"^\s*(KeyError|IndexError):"),
    _rule("python_value", "python.error_handling", r"^\s*ValueError:"),
    _rule("python_zero_div", "python.basics", r"^\s*ZeroDivisionError:"),

    # SQL. Requires SQL-shaped context, not a bare keyword that appears in prose.
    _rule("sql_syntax", "sql.select", r"syntax error at or near|SQLSyntaxError", IGNORE_CASE),
    _rule("sql_unknown_column", "sql.joins",
          r'column "[^"]+" does not exist|Unknown column', IGNORE_CASE),
    _rule("sql_ambiguous_column", "sql.joins",
          r'column reference "[^"]+" is ambiguous', IGNORE_CASE),
    _rule("sql_grouping", "sql.joins", r"must appear in the GROUP BY clause", IGNORE_CASE),

    # Spark. Anchored to exception class names, never to English words.
    _rule("spark_analysis", "spark.dataframe",
          r"AnalysisException|pyspark\.sql\.utils\.\w*Exception"),
    _rule("spark_shuffle_oom", "spark.performance",
          r"SparkOutOfMemoryError|ExecutorLostFailure"),
    _rule("spark_py4j", "spark.dataframe", r"Py4JJavaError"),

    # Airflow.
    _rule("airflow_import", "airflow.dag",
          r"DagBag import (timeout|error)|Broken DAG", IGNORE_CASE),
    _rule("airflow_dependency", "airflow.dag",
          r"AirflowFailException|Task .* is in the 'upstream_failed'", IGNORE_CASE),
    _rule("airflow_duplicate", "airflow.idempotency",
          r"duplicate key value violates unique constraint", IGNORE_CASE),

    # Tests. Must indicate an actual failure, not merely mention the word "test".
    _rule("test_assertion", "testing", r"^\s*AssertionError\b|^E\s+assert\b"),
    _rule("test_failed", "testing", r"^=+ .*\d+ failed"),

    # Tooling.
    _rule("lint_failed", "documentation",
          r"^\s*(ruff|sqlfluff) (check )?failed|Found \d+ error", IGNORE_CASE),
]


def classify(log_text: str | None) -> tuple[str, str | None]:
    """Return (error_class, concept_id). concept_id is None when unclassified.

    A None concept_id is the signal that no mastery update may follow (invariant 10).
    """
    if not log_text:
        return (UNCLASSIFIED, None)
    for error_class, concept_id, pattern in RULES:
        if pattern.search(log_text):
            return (error_class, concept_id)
    return (UNCLASSIFIED, None)


def classify_run(conclusion: str | None, log_text: str | None) -> tuple[str | None, str | None]:
    """Classify a workflow run. Successful runs are not errors and get no class."""
    if conclusion == "success":
        return (None, None)
    if conclusion in {"cancelled", "skipped", "stale", None}:
        # Not the student's doing -- must not count against a concept.
        return (conclusion or UNCLASSIFIED, None)
    return classify(log_text)


def match_rate(results: list[tuple[str | None, str | None]]) -> float:
    """Share of classified failures that mapped to a concept.

    BUILD_PLAN 1.5 requires this to be logged and reported. It is the honest measure of
    how much of the telemetry the taxonomy actually reaches -- and a low number is a
    finding to report, not a number to inflate by loosening the rules.
    """
    considered = [r for r in results if r[0] not in {None, "cancelled", "skipped", "stale"}]
    if not considered:
        return 0.0
    return round(sum(1 for _, cid in considered if cid) / len(considered), 4)
