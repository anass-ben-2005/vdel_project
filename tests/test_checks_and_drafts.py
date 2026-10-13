"""D-107 -- config/checks.yaml, the judging statement and the rule that a DRAFT reaches nothing.

The two files ship with entries an assistant drafted from the hidden tests and the master files; a
person has not read them. These tests pin the mechanism, not the current status of the shipped
entries (a reviewer changing `draft` to `reviewed` must not have to edit a test): an entry is
visible if and only if it is `reviewed`, and a draft statement never reaches the task text the Code
Agent is given.
"""

import os

import pytest

from config import checks, judging
from system import db

REVIEWED = """
version: 1
assignments:
  a_one:
    - test: tests/hidden/test_one.py::test_alpha
      gap: g_a
      description: When the input is empty the function returns an empty list.
      status: reviewed
    - test: tests/hidden/test_one.py::test_beta
      gap: g_b
      description: When a value is missing the function raises a ValueError.
      status: draft
"""


@pytest.fixture
def path(tmp_path):
    p = tmp_path / "checks.yaml"
    p.write_text(REVIEWED, encoding="utf-8")
    checks._load.cache_clear()
    yield p
    checks._load.cache_clear()


# --- checks.yaml: a draft is invisible ------------------------------------------------------------


def test_a_draft_entry_is_ignored_unless_asked_for_by_name(path):
    visible = checks.entries("a_one", path=path)
    assert [c.test for c in visible] == ["tests/hidden/test_one.py::test_alpha"]
    both = checks.entries("a_one", include_drafts=True, path=path)
    assert [c.status for c in both] == ["reviewed", "draft"]
    assert [c.test for c in checks.entries(path=path)] == ["tests/hidden/test_one.py::test_alpha"]


def test_description_for_returns_text_only_for_a_reviewed_entry(path):
    assert (
        checks.description_for("a_one", "tests/hidden/test_one.py::test_alpha", path=path)
        == "When the input is empty the function returns an empty list."
    )
    assert checks.description_for("a_one", "tests/hidden/test_one.py::test_beta", path=path) is None
    assert checks.description_for("a_one", "tests/hidden/test_one.py::missing", path=path) is None
    assert (
        checks.description_for("no_such", "tests/hidden/test_one.py::test_alpha", path=path) is None
    )


def test_the_shipped_file_obeys_the_rule_whatever_its_statuses():
    shipped = checks.entries(include_drafts=True)
    assert len(shipped) == 15  # the four weather_etl assignments
    visible = {c.test for c in checks.entries()}
    for c in shipped:
        assert (c.test in visible) == c.reviewed
        assert (checks.description_for(c.assignment_id, c.test) is not None) == c.reviewed


HEAD = "version: 1\nassignments:\n  a:\n"
OK_ENTRY = "    - {test: 'tests/hidden/t.py::x', gap: g, description: d, status: draft}\n"


@pytest.mark.parametrize(
    "body, needle",
    [
        ("version: 2\n", "version must be 1"),
        (HEAD + "    - {test: nope, gap: g, description: d, status: draft}\n", "tests/hidden/"),
        (HEAD + OK_ENTRY.replace("status: draft", "status: maybe"), "status must be"),
        (HEAD + OK_ENTRY.replace("gap: g, ", ""), "gap is required"),
        (HEAD + OK_ENTRY.replace("}", ", extra: 1}"), "unknown key"),
        (HEAD + OK_ENTRY + OK_ENTRY.replace("description: d", "description: e"), "listed twice"),
    ],
)
def test_a_malformed_file_fails_loudly(tmp_path, body, needle):
    p = tmp_path / "c.yaml"
    p.write_text(body, encoding="utf-8")
    checks._load.cache_clear()
    with pytest.raises(checks.ChecksError, match=needle):
        checks.entries(path=p)
    checks._load.cache_clear()


@pytest.mark.parametrize(
    "text",
    [
        "```python\nassert f(1) == 2\n```",
        "assert result == 3",
        "the result == 3",
        "def test_x(): pass",
        "pytest.raises(ValueError)",
        "x" * 401,
        "",
        "   ",
        None,
    ],
)
def test_a_description_that_is_code_or_empty_or_too_long_is_refused(text):
    assert checks.description_problems(text)


def test_plain_prose_is_accepted():
    assert (
        checks.description_problems(
            "When every request fails, fetch_weather lets the connection error reach the caller."
        )
        == []
    )


def test_every_shipped_description_is_prose_in_words():
    for c in checks.entries(include_drafts=True):
        assert checks.description_problems(c.description) == [], c.test


# --- judging.yaml: a draft statement is invisible -------------------------------------------------


def write_judging(tmp_path, statement_yaml):
    p = tmp_path / "judging.yaml"
    p.write_text(
        "version: 1\ndefault: {criteria: [correctness, approach]}\nassignments:\n"
        f"  a_one:\n    criteria: [correctness]\n    statement: {statement_yaml}\n",
        encoding="utf-8",
    )
    judging._load.cache_clear()
    return p


def test_a_draft_statement_is_kept_aside_and_never_becomes_the_statement(tmp_path):
    p = write_judging(tmp_path, "{text: 'Draft words.', status: draft}")
    j = judging.for_assignment("a_one", p)
    assert j.statement is None and j.statement_status == "draft"
    assert j.draft_statement == "Draft words."
    assert judging.compose_task(j.statement, ["Do it."]) == "Do it."  # as if it did not exist
    judging._load.cache_clear()


def test_a_reviewed_statement_and_a_plain_string_are_used(tmp_path):
    p = write_judging(tmp_path, "{text: 'Reviewed words.', status: reviewed}")
    j = judging.for_assignment("a_one", p)
    assert (j.statement, j.statement_status, j.draft_statement) == (
        "Reviewed words.",
        "reviewed",
        None,
    )
    p = write_judging(tmp_path, "'Plain words.'")
    assert judging.for_assignment("a_one", p).statement == "Plain words."  # the pre-D-107 form
    p = write_judging(tmp_path, "null")
    j = judging.for_assignment("a_one", p)
    assert (j.statement, j.statement_status, j.draft_statement) == (None, None, None)
    judging._load.cache_clear()


@pytest.mark.parametrize(
    "statement, needle",
    [
        ("{text: 'x', status: maybe}", "status must be"),
        ("{text: '', status: draft}", "non-empty"),
        ("{text: 'x'}", "null, a string or"),
        ("{text: 'x', status: draft, extra: 1}", "null, a string or"),
        ("''", "non-empty"),
        ("[1]", "null, a string or"),
    ],
)
def test_a_malformed_statement_fails_loudly(tmp_path, statement, needle):
    p = write_judging(tmp_path, statement)
    with pytest.raises(judging.JudgingError, match=needle):
        judging.load(p)
    judging._load.cache_clear()


@pytest.mark.skipif(not os.environ.get("PG_DSN"), reason="PG_DSN not set; needs the test database")
def test_a_draft_statement_never_reaches_the_task_text_the_code_agent_is_given(
    tmp_path, monkeypatch
):
    from agents import pipeline

    p = write_judging(tmp_path, "{text: 'SECRET DRAFT STATEMENT', status: draft}")
    real = judging.for_assignment  # pipeline.judging_config IS this module: keep the original
    monkeypatch.setattr(pipeline.judging_config, "for_assignment", lambda aid: real("a_one", p))
    conn = db._open()
    try:
        assignment, _ = pipeline.load_assignment_inputs(conn.cursor(), "weather_etl_transform")
    finally:
        conn.rollback()
        conn.close()
    assert "SECRET DRAFT STATEMENT" not in assignment["task"]
    assert assignment["task"].startswith("Return only records")  # the gap instructions only
    judging._load.cache_clear()


def test_the_shipped_judging_file_never_exposes_a_draft_as_the_statement():
    _, entries = judging.load()
    for aid, j in entries.items():
        assert (j.statement is not None) == (j.statement_status == "reviewed"), aid
        assert j.draft_statement is None or j.statement is None, aid
