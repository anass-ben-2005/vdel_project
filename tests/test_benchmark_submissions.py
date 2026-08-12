"""tests/test_benchmark_submissions.py — BUILD_PLAN 3.2.

A syntax smoke check, not a correctness check: `subtly_wrong.py` and `broken.py` are
*supposed* to give the wrong answer, and `broken.py` is supposed to fail at runtime.
What this file proves instead: every submission is present, is valid Python (so the M4
tool stage can run ruff over it and get real findings rather than a crash), and exposes
the one shared entry point `benchmark/run_benchmark.py` (3.3) will call on all five.
"""

import ast
from pathlib import Path

import pytest

SUBMISSIONS_DIR = Path(__file__).resolve().parent.parent / "benchmark" / "submissions"
EXPECTED = [
    "clean.py",
    "subtly_wrong.py",
    "inefficient.py",
    "copy_paste.py",
    "broken.py",
]
ENTRY_POINT = "compute_monthly_revenue"


@pytest.mark.parametrize("filename", EXPECTED)
def test_submission_exists_and_parses(filename):
    path = SUBMISSIONS_DIR / filename
    assert path.exists(), f"missing benchmark submission: {filename}"
    source = path.read_text(encoding="utf-8")
    ast.parse(source, filename=filename)  # raises SyntaxError if the file isn't valid Python


def test_no_extra_or_missing_submissions():
    actual = {p.name for p in SUBMISSIONS_DIR.glob("*.py")}
    assert actual == set(EXPECTED)


@pytest.mark.parametrize("filename", EXPECTED)
def test_each_submission_defines_the_shared_entry_point(filename):
    """Same interface, five different implementations -- so 3.3's harness can call
    every submission the same way regardless of archetype."""
    source = (SUBMISSIONS_DIR / filename).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=filename)
    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert ENTRY_POINT in names, f"{filename} must define {ENTRY_POINT}(orders) -> DataFrame"


def test_task_spec_exists():
    assert (SUBMISSIONS_DIR / "TASK.md").exists(), "TASK.md documents the shared task once"
