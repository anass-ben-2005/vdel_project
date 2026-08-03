"""V2-V6: the contract every variable must honour, and the behaviours that matter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from variables.error_frequency import error_frequency
from variables.error_response import error_response
from variables.habits import effort_regulation, engineering_discipline
from variables.pace import learning_pace

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def every_variable():
    """One representative result from each of V2-V6."""
    return [
        engineering_discipline(2, 500, True, True),
        effort_regulation([NOW + timedelta(hours=i) for i in range(6)]),
        learning_pace(NOW - timedelta(days=5), NOW + timedelta(days=5), NOW, NOW, 3, now=NOW),
        error_response([(NOW, False, "sql.joins"), (NOW + timedelta(hours=1), True, "sql.joins")]),
        error_frequency(10, 3),
    ]


@pytest.mark.parametrize("result", every_variable())
def test_contract(result):
    """CLAUDE.md section 8: scaled to [0, 1], higher is better, and carries its n."""
    assert "n" in result and isinstance(result["n"], int)
    assert "score" in result
    if result["score"] is not None:
        assert 0.0 <= result["score"] <= 1.0


def test_unmeasured_is_none_not_zero():
    """0.0 means "measured, bad"; None means "not observed".

    The previous version collapsed the two by inventing inputs (lint findings derived
    from commit count, tests_present hardcoded True), which wrote fiction into the
    database and made an unmeasured variable indistinguishable from a terrible one.
    """
    assert engineering_discipline(None, None, None, None)["score"] is None
    assert error_frequency(0, 0)["score"] is None
    assert effort_regulation([])["score"] is None


def test_discipline_rewards_clean_tested_code():
    clean = engineering_discipline(1, 1000, True, True)["score"]
    # 150 findings over 1000 lines is 15 per 100 LOC, past LINT_ZERO_AT_PER_100_LOC.
    messy = engineering_discipline(150, 1000, False, False)["score"]
    assert clean > messy
    assert clean == pytest.approx(1.0, abs=0.05)
    assert messy == pytest.approx(0.0)


def test_effort_prefers_steady_work_to_cramming():
    steady = [NOW + timedelta(hours=6 * i) for i in range(8)]
    # Nothing for a fortnight, then everything in one night.
    crammed = [NOW, NOW + timedelta(days=14)] + [
        NOW + timedelta(days=14, minutes=10 * i) for i in range(1, 7)
    ]
    assert effort_regulation(steady)["score"] > effort_regulation(crammed)["score"]


def test_effort_needs_enough_gaps_to_have_dispersion():
    """Two commits give one gap, and one gap has no variance to measure."""
    assert effort_regulation([NOW, NOW + timedelta(hours=1)])["score"] is None


def test_pace_is_censored_when_the_student_has_not_passed_yet():
    """A censored observation gets a bound, never an invented point estimate."""
    result = learning_pace(
        released_at=NOW - timedelta(days=3), due_at=NOW + timedelta(days=7),
        first_commit_at=NOW - timedelta(days=3), first_pass_at=None, attempts=9, now=NOW,
    )
    assert result["censored"] is True
    assert result["score"] is None
    assert 0.0 <= result["score_upper_bound"] <= 1.0


def test_pace_rewards_passing_early_in_the_assignment_window():
    window = {"released_at": NOW, "due_at": NOW + timedelta(days=10), "attempts": 2}
    fast = learning_pace(first_commit_at=NOW, first_pass_at=NOW + timedelta(days=1),
                         now=NOW, **window)
    slow = learning_pace(first_commit_at=NOW, first_pass_at=NOW + timedelta(days=9),
                         now=NOW, **window)
    assert fast["score"] > slow["score"]


def test_pace_survives_naive_timestamps():
    """The previous version mixed naive utcnow() with timezone-aware TIMESTAMPTZ values
    and raised TypeError on subtraction at runtime."""
    naive = datetime(2026, 6, 1, 12, 0)  # noqa: DTZ001 -- naive is the point
    result = learning_pace(naive, None, naive, naive + timedelta(days=1), 1, now=NOW)
    assert result["score"] is not None


def test_error_response_measures_recovery_not_failure_count():
    """V5 is a behaviour, V6 is a rate. Same failures, different responses."""
    fixes = [(NOW + timedelta(hours=i), i % 2 == 1, "sql.joins") for i in range(8)]
    never = [(NOW + timedelta(hours=i), False, "sql.joins") for i in range(8)]
    assert error_response(fixes)["score"] > error_response(never)["score"]


def test_wheel_spinning_is_detected_per_concept():
    """Beck & Gong (2013): sustained practice without reaching mastery."""
    stuck = [(NOW + timedelta(hours=i), False, "spark.joins") for i in range(12)]
    assert error_response(stuck)["wheel_spinning_concepts"] == ["spark.joins"]


def test_no_failures_means_nothing_to_respond_to():
    passing = [(NOW + timedelta(hours=i), True, "testing") for i in range(5)]
    assert error_response(passing)["score"] is None


def test_error_frequency_is_normalised_by_opportunity():
    """Ten failures in 200 attempts is not ten failures in twelve."""
    assert error_frequency(200, 10)["score"] > error_frequency(12, 10)["score"]
