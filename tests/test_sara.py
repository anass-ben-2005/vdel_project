"""Test against Sara: synthetic worked example for validation."""

import pytest
from datetime import datetime, timedelta
from variables.mastery import update as bkt_update, MasteryState
from variables.habits import compute_discipline, discipline_score, compute_effort, effort_score
from variables.pace import compute_pace, pace_score
from variables.error_response import compute_error_response, error_response_score
from variables.error_frequency import compute_error_frequency, error_frequency_score


class TestSara:
    """
    Sara is a hand-computed synthetic example.
    These tests validate that the formulas produce expected output.

    If these fail, a formula was mistyped or misunderstood.
    """

    def test_sara_mastery_bkt(self):
        """Test BKT mastery update with Sara's sequence: fail, pass, pass."""
        prior = MasteryState(p_mastery=0.3, n=0)

        # Attempt 1: fail (outcome=0)
        prior = bkt_update(prior, 0, difficulty=0.5)
        assert prior.p_mastery < 0.3, "Failure should decrease mastery belief"
        assert prior.n == 1

        # Attempt 2: pass (outcome=1)
        prior = bkt_update(prior, 1, difficulty=0.5)
        assert prior.p_mastery > 0.2, "Success should increase mastery belief"
        assert prior.n == 2

        # Attempt 3: pass (outcome=1)
        prior = bkt_update(prior, 1, difficulty=0.5)
        assert prior.p_mastery > prior.n >= 2, "Multiple successes = higher confidence"
        assert prior.n == 3

    def test_sara_discipline(self):
        """Test discipline scoring: low violations, tests present and passing."""
        state = compute_discipline(
            commit_messages=['fix bug', 'add feature', 'refactor'],
            files_modified=3,
            code_lines=500,
            linter_violations=5,  # 1 per 100 LOC
            tests_exist=True,
            tests_passing=True,
        )

        score = discipline_score(state)
        assert 0.7 < score <= 1.0, f"Expected high discipline score, got {score}"

    def test_sara_low_discipline(self):
        """Test discipline scoring: high violations, no tests."""
        state = compute_discipline(
            commit_messages=['code'],
            files_modified=1,
            code_lines=200,
            linter_violations=50,  # 25 per 100 LOC (bad)
            tests_exist=False,
            tests_passing=False,
        )

        score = discipline_score(state)
        assert 0.0 <= score < 0.3, f"Expected low discipline score, got {score}"

    def test_sara_effort_steady(self):
        """Test effort scoring: steady commits = low burstiness."""
        now = datetime.utcnow()
        timestamps = [
            now - timedelta(hours=24),
            now - timedelta(hours=23),
            now - timedelta(hours=22),
            now - timedelta(hours=21),
        ]

        state = compute_effort(timestamps)
        score = effort_score(state)
        assert score > 0.7, f"Expected high effort score for steady work, got {score}"

    def test_sara_effort_bursty(self):
        """Test effort scoring: bursty commits = high variance."""
        now = datetime.utcnow()
        timestamps = [
            now - timedelta(days=5),   # 5 days ago
            now - timedelta(days=4, hours=23),  # Almost a day later
            now - timedelta(hours=2),   # Then nothing for ~5 days
            now,  # Sudden burst at the end
        ]

        state = compute_effort(timestamps)
        score = effort_score(state)
        assert score < 0.4, f"Expected low effort score for bursty work, got {score}"

    def test_sara_pace_quick(self):
        """Test pace scoring: quick time to first pass."""
        released = datetime(2024, 1, 1, 0, 0)
        first_pass = datetime(2024, 1, 1, 12, 0)  # 0.5 days

        state = compute_pace(
            released_at=released,
            due_at=None,
            first_commit_at=released,
            first_pass_at=first_pass,
            total_attempts=2,
            total_passes=1,
        )

        score = pace_score(state)
        assert score > 0.8, f"Expected high pace score for quick success, got {score}"

    def test_sara_pace_slow(self):
        """Test pace scoring: slow time to first pass."""
        released = datetime(2024, 1, 1)
        first_pass = datetime(2024, 1, 9)  # 8 days

        state = compute_pace(
            released_at=released,
            due_at=None,
            first_commit_at=released,
            first_pass_at=first_pass,
            total_attempts=20,
            total_passes=1,
        )

        score = pace_score(state)
        assert score < 0.5, f"Expected low pace score for slow success, got {score}"

    def test_sara_error_response_good(self):
        """Test error response: good fix rate after errors."""
        state = compute_error_response(
            failure_events=[
                {'timestamp': datetime.utcnow() - timedelta(hours=i), 'error_class': 'syntax'}
                for i in range(5)
            ],
            success_events=[
                {'timestamp': datetime.utcnow()}
                for _ in range(4)
            ],
        )

        score = error_response_score(state)
        assert score > 0.6, f"Expected good error response score, got {score}"

    def test_sara_error_response_wheel_spin(self):
        """Test error response: wheel spin (many fails, no fix)."""
        state = compute_error_response(
            failure_events=[
                {'timestamp': datetime.utcnow() - timedelta(hours=i)}
                for i in range(10)
            ],
            success_events=[],  # No successes
        )

        score = error_response_score(state)
        # Wheel spin should lower the score significantly
        assert score < 0.3, f"Expected low score for wheel spin, got {score}"

    def test_sara_error_frequency_low(self):
        """Test error frequency: few errors."""
        state = compute_error_frequency(
            total_attempts=20,
            total_failures=2,  # 10% error rate
            concept_difficulty=0.5,
        )

        score = error_frequency_score(state)
        assert score > 0.7, f"Expected high error frequency score for low error rate, got {score}"

    def test_sara_error_frequency_high(self):
        """Test error frequency: many errors."""
        state = compute_error_frequency(
            total_attempts=10,
            total_failures=9,  # 90% error rate
            concept_difficulty=0.5,
        )

        score = error_frequency_score(state)
        assert score < 0.2, f"Expected low error frequency score for high error rate, got {score}"
