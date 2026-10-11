"""tests/test_demo.py -- scripts/demo.py's own orchestration logic, isolated from the
seven beats it sequences.

No DB, no LLM key needed: `_run_beat`'s catch-and-continue isolation and `BeatResult`
are pure control flow around whatever function they're handed -- exercised here with
stub functions, not the real beats (those are exercised live, by hand, each rehearsal;
see docs/DECISIONS.md for the real runs' evidence). This is exactly the gap flagged
after the per-beat isolation was added: previously a beat's own logic and demo.py's
sequencing were both only ever exercised together, live.
"""
from __future__ import annotations

import pytest

from scripts import demo
from scripts.demo import BeatResult, _run_beat, grade_without_persisting, mastery_line


def test_run_beat_returns_the_stubbed_result_on_success():
    def ok():
        return BeatResult(passed=True, evidence="fine")

    result = _run_beat(1, "a beat that succeeds", ok)
    assert result == BeatResult(passed=True, evidence="fine")


def test_run_beat_isolates_an_exception_into_a_failed_result():
    def boom():
        raise ValueError("something real broke")

    result = _run_beat(2, "a beat that raises", boom)
    assert result.passed is False
    assert "ValueError" in result.evidence
    assert "something real broke" in result.evidence


def test_run_beat_never_propagates_the_exception():
    """The whole point of this wrapper: one beat raising must never crash the caller,
    or the isolation this was built for (a live 222s Beat 6 delay killing the entire
    rehearsal) is not actually fixed."""
    def boom():
        raise RuntimeError("boom")

    # If this raised, the test itself would fail with RuntimeError, not an assertion.
    _run_beat(3, "a beat that raises, again", boom)


def test_run_beat_passes_positional_args_through_to_the_beat_function():
    def echoes(flag):
        return BeatResult(passed=flag, evidence=f"flag was {flag}")

    assert _run_beat(4, "a beat with an argument", echoes, True) == \
        BeatResult(True, "flag was True")
    assert _run_beat(4, "a beat with an argument", echoes, False) == \
        BeatResult(False, "flag was False")


def test_two_beats_run_in_sequence_both_report_even_if_the_first_fails():
    """The actual scenario this session's live run surfaced: one beat failing (or
    taking a long time) must not prevent the NEXT beat from running and reporting its
    own real result."""
    def fails():
        raise RuntimeError("beat A is down")

    def succeeds():
        return BeatResult(passed=True, evidence="beat B is fine")

    first = _run_beat(1, "beat A", fails)
    second = _run_beat(2, "beat B", succeeds)

    assert first.passed is False
    assert second.passed is True
    assert second.evidence == "beat B is fine"


class _FakeConn:
    def __init__(self):
        self.calls = []

    def commit(self):
        self.calls.append("commit")

    def rollback(self):
        self.calls.append("rollback")

    def close(self):
        self.calls.append("close")


def test_beat3_grading_is_rolled_back_and_never_committed(monkeypatch):
    """D-076: Beat 3 hands grade_attempt a connection and rolls it back, whatever happens.
    (The end-to-end proof is the baseline --full hash taken before and after two real runs.)"""
    conn = _FakeConn()
    monkeypatch.setattr(demo.db, "_open", lambda: conn)
    seen = {}

    def fake_grade(project, assignment, repo_dir, attempt_id, *, conn=None):
        seen["conn"] = conn
        return "result"

    assert grade_without_persisting(fake_grade, "p", "a", "dir", 7) == "result"
    assert seen["conn"] is conn                       # the caller's transaction is joined
    assert conn.calls == ["rollback", "close"]        # and "commit" never appears


def test_beat3_grading_is_rolled_back_even_when_grading_raises(monkeypatch):
    conn = _FakeConn()
    monkeypatch.setattr(demo.db, "_open", lambda: conn)

    def boom(*a, **k):
        raise RuntimeError("grading failed")

    with pytest.raises(RuntimeError):
        grade_without_persisting(boom, "p", "a", "dir", 7)
    assert conn.calls == ["rollback", "close"]


def test_beat5_marks_low_data_below_three_observations():
    base = {"p_mastery": 0.776, "ci90": [0.2, 0.9], "trend": "up"}
    assert "low data" in mastery_line("py.x", {**base, "n": 1})
    assert "low data" in mastery_line("py.x", {**base, "n": 2})
    assert "low data" not in mastery_line("py.x", {**base, "n": 3})
    # the flag sits right next to p, not at the end of the line
    assert "p_mastery=0.776  low data  n=1" in mastery_line("py.x", {**base, "n": 1})
