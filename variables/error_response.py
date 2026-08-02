"""Error response (V5): Jadud/Watwin + wheel-spin detection."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class ErrorResponseState:
    """Error response behavior."""
    successes_after_fail: int = 0  # Fixes that work
    failures_after_fail: int = 0   # Attempts that still fail
    time_to_fix_hours: float = 0.0  # Median time from fail to next pass
    wheel_spin_detected: bool = False  # > 5 fails without a pass
    n: int = 0  # Total error events


def detect_wheel_spin(
    failure_events: List[dict],
    success_events: List[dict],
    max_fails_before_fix: int = 5,
    time_window_hours: int = 24,
) -> bool:
    """
    Detect "wheel-spin": attempting same fix repeatedly without success.

    Wheel-spin = >N failures in time_window without a pass.
    Indicates student is stuck, not learning from errors.
    """
    if not failure_events:
        return False

    # Count consecutive failures without intervening success
    # (simplified: just check density in time window)
    recent_fails = [
        e for e in failure_events
        if (datetime.utcnow() - e['timestamp']).total_seconds() / 3600 < time_window_hours
    ]

    return len(recent_fails) >= max_fails_before_fix


def compute_error_response(
    failure_events: List[dict],  # Each: {timestamp, concept_id, error_class}
    success_events: List[dict],  # Each: {timestamp, concept_id}
    failure_timestamps: Optional[List[datetime]] = None,
    success_timestamps: Optional[List[datetime]] = None,
) -> ErrorResponseState:
    """
    Compute error response behavior (V5).

    Jadud/Watwin framework: measures what student does AFTER an error.
    - Good response: attempts fix, passes on next try
    - Poor response: repeats same attempt, doesn't debug

    Args:
        failure_events: List of failed workflow runs
        success_events: List of successful runs
        failure_timestamps: Timestamps of failures (for time analysis)
        success_timestamps: Timestamps of successes

    Returns:
        ErrorResponseState
    """
    if not failure_events:
        return ErrorResponseState()

    wheel_spin = detect_wheel_spin(failure_events, success_events)

    # Count successes/failures after each error
    successes_after_fail = len(success_events)
    failures_after_fail = max(0, len(failure_events) - 1)  # -1 for the first error

    # Time-to-fix: median time from fail to next pass
    if failure_timestamps and success_timestamps and success_events:
        time_diffs = []
        for fail_ts in failure_timestamps:
            # Find first success after this failure
            next_successes = [s for s in success_timestamps if s > fail_ts]
            if next_successes:
                time_to_fix = (next_successes[0] - fail_ts).total_seconds() / 3600
                time_diffs.append(time_to_fix)

        time_to_fix_median = (
            sorted(time_diffs)[len(time_diffs) // 2] if time_diffs else 0
        )
    else:
        time_to_fix_median = 0

    return ErrorResponseState(
        successes_after_fail=successes_after_fail,
        failures_after_fail=failures_after_fail,
        time_to_fix_hours=time_to_fix_median,
        wheel_spin_detected=wheel_spin,
        n=len(failure_events),
    )


def error_response_score(state: ErrorResponseState) -> float:
    """
    Aggregate error response into [0, 1] score (higher = better).

    Rules:
    - High success rate after failures: good response
    - Quick time-to-fix: good response
    - Wheel-spin detected: poor response (penalize heavily)
    """
    if state.n == 0:
        return 0.5  # Neutral

    # Success ratio after failures
    total_after_fail = state.successes_after_fail + state.failures_after_fail
    if total_after_fail > 0:
        success_ratio = state.successes_after_fail / total_after_fail
    else:
        success_ratio = 0.5

    # Time-to-fix component (reward quick fixes)
    # < 1 hour = 1.0, > 24 hours = 0.2
    if state.time_to_fix_hours < 1:
        time_score = 1.0
    elif state.time_to_fix_hours > 24:
        time_score = 0.2
    else:
        time_score = 1.0 - (0.8 * (state.time_to_fix_hours - 1) / 23)

    # Combine
    score = 0.6 * success_ratio + 0.4 * time_score

    # Penalize wheel-spin heavily
    if state.wheel_spin_detected:
        score *= 0.5

    return score
