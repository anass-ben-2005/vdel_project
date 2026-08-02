"""Classify CI errors to concepts."""

import re
from typing import Optional, Tuple


class ErrorClassifier:
    """Map error messages to error class and concept."""

    # (pattern, error_class, concept_id)
    RULES = [
        # SQL errors
        (r'syntax error|SQL syntax|unexpected token', 'sql_syntax', 'sql.select'),
        (r'JOIN|column.*not found|ambiguous|undefined|table.*does not exist', 'sql_join', 'sql.joins'),
        (r'GROUP BY|HAVING|aggregate', 'sql_aggregation', 'sql.joins'),
        (r'INDEX|performance|slow query|query timeout', 'sql_performance', 'sql.indexing'),

        # Python errors
        (r'SyntaxError|IndentationError|invalid syntax', 'python_syntax', 'python.basics'),
        (r'NameError|undefined.*variable|not defined', 'python_name', 'python.control_flow'),
        (r'TypeError|wrong.*type|expected.*got', 'python_type', 'python.functions'),
        (r'AttributeError|no attribute|object.*has no', 'python_attribute', 'python.functions'),
        (r'IndexError|KeyError|out of range', 'python_access', 'python.control_flow'),
        (r'ImportError|ModuleNotFoundError|cannot import', 'python_import', 'python.basics'),
        (r'ValueError|invalid.*value', 'python_value', 'python.error_handling'),
        (r'ZeroDivisionError|division by zero', 'python_math', 'python.basics'),

        # Spark errors
        (r'DataFrame|RDD|transformation|action', 'spark_dataframe', 'spark.dataframe'),
        (r'shuffle|partition|repartition', 'spark_partition', 'spark.aggregation'),
        (r'join|broadcast|reduce', 'spark_join', 'spark.dataframe'),

        # Airflow errors
        (r'DAG|task|dependency|upstream|downstream', 'airflow_dag', 'airflow.dag'),
        (r'operator|execute|run_task', 'airflow_operator', 'airflow.operators'),
        (r'schedule|cron|interval', 'airflow_schedule', 'airflow.scheduling'),
        (r'idempotent|duplicate|transaction', 'airflow_idempotency', 'airflow.idempotency'),

        # Testing
        (r'AssertionError|assert.*failed|expected.*got', 'test_assertion', 'testing'),
        (r'test.*failed|test.*passed', 'test_general', 'testing'),

        # CI/CD
        (r'build failed|compilation error|link error', 'build_error', 'ci_cd'),
        (r'deployment failed|deploy error', 'deploy_error', 'ci_cd'),
    ]

    @classmethod
    def classify(cls, error_text: str) -> Optional[Tuple[str, str]]:
        """
        Classify an error message.

        Returns:
            (error_class, concept_id) or None if unclassified
        """
        if not error_text:
            return None

        error_text_lower = error_text.lower()

        for pattern, error_class, concept_id in cls.RULES:
            if re.search(pattern, error_text_lower, re.IGNORECASE):
                return (error_class, concept_id)

        return None

    @classmethod
    def classify_workflow_run(cls, run_conclusion: str, error_log: Optional[str] = None) -> Optional[Tuple[str, str]]:
        """
        Classify a workflow run based on conclusion and optional error log.

        Args:
            run_conclusion: 'success', 'failure', 'cancelled', etc.
            error_log: Optional error message text

        Returns:
            (error_class, concept_id) or None
        """
        if run_conclusion == 'success':
            return None

        if run_conclusion == 'failure' and error_log:
            return cls.classify(error_log)

        # Generic error classes for non-failure conclusions
        if run_conclusion == 'cancelled':
            return ('cancelled', None)
        elif run_conclusion == 'timed_out':
            return ('timeout', 'performance')

        return None
