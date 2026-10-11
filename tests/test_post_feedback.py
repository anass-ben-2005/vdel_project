"""D-074 -- scripts/post_feedback.py: the text it builds, the hidden-code guard, the marker, and
the fact that nothing can reach GitHub. Test database, one rolled-back transaction per test."""

from __future__ import annotations

import os

import pytest

from scripts import post_feedback as pf
from system import db
from tests.support import ensure_variant

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

S, ASG = "_fb_student", "weather_etl_extract"
SHA1, SHA2 = "1" * 40, "2" * 40
T_RETRY = "tests/hidden/test_extract.py::test_fetch_weather_retries_then_succeeds"
T_PARSE = "tests/hidden/test_extract.py::test_parse_response_missing_key_returns_none"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Belt and braces: if anything in this module tried a real POST, the test fails."""
    import requests

    def boom(*a, **k):
        raise AssertionError("a test reached requests.post")
    monkeypatch.setattr(requests, "post", boom)
    monkeypatch.delenv(pf.POST_ENV_VAR, raising=False)


@pytest.fixture
def world():
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, S))
    variant = ensure_variant(cur, ASG)
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl',%s,1,%s,1) RETURNING attempt_id",
                (S, ASG, variant))
    attempt_id = cur.fetchone()[0]
    for i, sha in enumerate((SHA1, SHA2)):
        cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                    " VALUES (%s,%s,%s,%s)", (sha, S, ASG, f"2026-08-25 0{i + 1}:00+00"))
    yield conn, cur, attempt_id
    conn.rollback()
    conn.close()


def result(cur, attempt_id, sha, name, gap, passed, message=None, status="ok"):
    cur.execute("INSERT INTO test_results (attempt_id, commit_sha, test_name, gap_id, passed,"
                " message, status) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (attempt_id, sha, name, gap, passed, message, status))


def test_a_failing_check_is_named_with_its_assertion_message_only(world):
    _, cur, aid = world
    result(cur, aid, SHA1, T_RETRY, "g_ext_retry", False,
           "AssertionError: assert 1 == 3\n + where 1 = len([1])\n  def test_x():\n    foo()")
    result(cur, aid, SHA1, T_PARSE, "g_ext_parse", True)
    fb = pf.build_feedback(cur, aid, SHA1)
    assert (fb.passed, fb.total, fb.status) == (1, 2, "ok")
    assert "**1 of 2** checks passed" in fb.markdown
    assert "`test_fetch_weather_retries_then_succeeds (test_extract.py)`: assert 1 == 3" \
        in fb.markdown
    assert "where" not in fb.markdown and "def test_x" not in fb.markdown   # first line only
    assert "tests/hidden" not in fb.markdown


def test_it_cannot_be_made_to_leak_hidden_test_code(world):
    """The leak test: the stored failure message contains real hidden source lines, as a pytest
    traceback would. None of them may reach the output."""
    _, cur, aid = world
    hidden = pf.hidden_source_lines("weather_etl")
    assert len(hidden) > 20
    longest = sorted(hidden, key=len)[-1]
    body_lines = [ln for ln in hidden if ln.startswith("assert ")][:3]
    message = "AssertionError: " + longest + "\n" + "\n".join(body_lines)
    result(cur, aid, SHA1, T_RETRY, "g_ext_retry", False, message)
    fb = pf.build_feedback(cur, aid, SHA1)
    for line in hidden:
        assert line not in fb.markdown, f"hidden line leaked: {line!r}"
    assert "[removed]" in fb.markdown                         # it was redacted, not just absent
    pf.assert_no_hidden_source(fb.markdown, hidden)


def test_the_final_guard_raises_if_a_hidden_line_gets_through():
    hidden = pf.hidden_source_lines("weather_etl")
    leaked = "your answer was compared with: " + sorted(hidden, key=len)[-1]
    with pytest.raises(pf.HiddenSourceLeak):
        pf.assert_no_hidden_source(leaked, hidden)
    assert pf.assert_no_hidden_source("3 of 4 checks passed", hidden) is None
    assert pf.redact(leaked, hidden).endswith("[removed]")


def test_a_collection_error_is_explained_in_plain_words(world):
    _, cur, aid = world
    msg = "collection error: IndentationError at weather_etl/extract.py:11: expected an indent"
    result(cur, aid, SHA1, T_RETRY, "g_ext_retry", False, msg, "collection_error")
    result(cur, aid, SHA1, T_PARSE, "g_ext_parse", False, msg, "collection_error")
    fb = pf.build_feedback(cur, aid, SHA1)
    assert fb.status == "collection_error" and (fb.passed, fb.total) == (0, 2)
    assert "could not be loaded" in fb.markdown and "IndentationError" in fb.markdown
    assert "not counted as a wrong answer" in fb.markdown
    assert "Checks that failed" not in fb.markdown            # no list of "failing" tests


def test_a_timeout_and_a_tooling_marker_are_explained_without_blame(world):
    _, cur, aid = world
    result(cur, aid, SHA1, T_RETRY, "g_ext_retry", False, "timeout: x", "timeout")
    fb = pf.build_feedback(cur, aid, SHA1)
    assert fb.status == "timeout" and "did not finish in time" in fb.markdown
    result(cur, aid, SHA2, "tests/hidden/test_extract.py::<collection>", None, False,
           "ImportError: our side", "tooling")
    tooling = pf.build_feedback(cur, aid, SHA2)
    assert tooling.status == "tooling" and "problem on our side" in tooling.markdown
    assert "does **not** count against you" in tooling.markdown and tooling.total == 0


def test_recurrence_and_the_weakest_concept_come_from_diagnose(world):
    _, cur, aid = world
    for sha in (SHA1, SHA2):
        result(cur, aid, sha, T_RETRY, "g_ext_retry", False, "assert False")
    fb = pf.build_feedback(cur, aid, SHA2)
    assert "Keeps failing across several pushes: `g_ext_retry`" in fb.markdown
    assert "Concept to practise next: `" in fb.markdown


def test_a_passing_commit_and_a_load_error_get_no_history_lines(world):
    _, cur, aid = world
    for sha in (SHA1, SHA2):
        result(cur, aid, sha, T_RETRY, "g_ext_retry", False, "assert False")
    cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                " VALUES (%s,%s,%s,'2026-08-25 05:00+00')", ("3" * 40, S, ASG))
    result(cur, aid, "3" * 40, T_RETRY, "g_ext_retry", True)
    passing = pf.build_feedback(cur, aid, "3" * 40)
    assert "all done for this file" in passing.markdown
    assert "Keeps failing" not in passing.markdown and "practise" not in passing.markdown
    cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                " VALUES (%s,%s,%s,'2026-08-25 06:00+00')", ("4" * 40, S, ASG))
    result(cur, aid, "4" * 40, T_RETRY, "g_ext_retry", False, "collection error: X",
           "collection_error")
    broken = pf.build_feedback(cur, aid, "4" * 40)
    assert "could not be loaded" in broken.markdown
    assert "Keeps failing" not in broken.markdown and "practise" not in broken.markdown


def test_the_marker_makes_it_idempotent_and_a_missing_table_means_not_posted(world):
    _, cur, aid = world
    result(cur, aid, SHA1, T_RETRY, "g_ext_retry", True)
    assert pf.already_posted(cur, aid, SHA1) is False
    cur.execute("INSERT INTO feedback_posts (attempt_id, commit_sha, body_sha256)"
                " VALUES (%s,%s,'abc')", (aid, SHA1))
    assert pf.already_posted(cur, aid, SHA1) is True
    assert pf.already_posted(cur, aid, SHA2) is False
    cur.execute("SAVEPOINT s")
    cur.execute("DROP TABLE feedback_posts")                  # the migration "not applied"
    assert pf.already_posted(cur, aid, SHA1) is False
    cur.execute("ROLLBACK TO SAVEPOINT s")


def test_graded_commits_lists_them_oldest_first(world):
    _, cur, aid = world
    result(cur, aid, SHA2, T_RETRY, "g_ext_retry", True)
    result(cur, aid, SHA1, T_RETRY, "g_ext_retry", False)
    assert pf.graded_commits(cur, S) == [(aid, SHA1), (aid, SHA2)]
    assert pf.graded_commits(cur, S, commit="2222") == [(aid, SHA2)]
    assert pf.graded_commits(cur, S, assignment_id="weather_etl_load") == []


def test_posting_is_refused_unless_the_flag_and_the_env_var_are_both_set(monkeypatch):
    with pytest.raises(pf.FeedbackPostingNotEnabled):
        pf.post_comment("o", "r", "sha", "body")                       # neither
    with pytest.raises(pf.FeedbackPostingNotEnabled):
        pf.post_comment("o", "r", "sha", "body", enabled=True)         # flag only
    monkeypatch.setenv(pf.POST_ENV_VAR, "1")
    with pytest.raises(pf.FeedbackPostingNotEnabled):
        pf.post_comment("o", "r", "sha", "body")                       # env var only
    monkeypatch.delenv(pf.POST_ENV_VAR)
    with pytest.raises(pf.FeedbackPostingNotEnabled):
        pf.main(["--student", "x", "--post"])                          # the CLI flag alone
    # (the combination that would post is deliberately never exercised here)
