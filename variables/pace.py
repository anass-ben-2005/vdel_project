"""Learning pace (V4): censoring-aware time to mastery."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class PaceState:
    """Learning pace metrics."""
    days_since_release: float = 0.0  # Days elapsed since assignment released
    days_to_first_commit: float = 0.0  # Time to first attempt
    days_to_first_pass: float = 0.0  # Time to first success
    pass_rate: float = 0.0  # Successes / attempts
    is_censored: bool = False  # True if still in progress (no pass yet)
    n: int = 0


def compute_pace(
    released_at: datetime,
    due_at: Optional[datetime],
    first_commit_at: Optional[datetime],
    first_pass_at: Optional[datetime],
    total_attempts: int,
    total_passes: int,
    current_time: datetime = None,
) -> PaceState:
    """
    Compute pace metrics: time-to-mastery with censoring.

    "Censoring" means: if student hasn't passed yet, we don't know their time-to-pass.
    A censored observation is still informative (e.g., 3 days in, 0 passes yet = struggling).

    Args:
        released_at: Assignment release date
        due_at: Assignment due date (optional)
        first_commit_at: Timestamp of first commit (optional)
        first_pass_at: Timestamp of first passing run (optional)
        total_attempts: Total workflow runs
        total_passes: Total passing runs
        current_time: Current time (defaults to now)

    Returns:
        PaceState
    """
    if current_time is None:
        current_time = datetime.utcnow()

    days_since_release = (current_time - released_at).total_seconds() / (24 * 3600)

    # Time to first commit
    if first_commit_at:
        days_to_first_commit = (first_commit_at - released_at).total_seconds() / (24 * 3600)
    else:
        days_to_first_commit = None

    # Time to first pass
    if first_pass_at:
        days_to_first_pass = (first_pass_at - released_at).total_seconds() / (24 * 3600)
        is_censored = False
    else:
        days_to_first_pass = None
        is_censored = True  # Still waiting for first pass

    # Pass rate
    if total_attempts > 0:
        pass_rate = total_passes / total_attempts
    else:
        pass_rate = 0.0

    return PaceState(
        days_since_release=max(0, days_since_release),
        days_to_first_commit=days_to_first_commit or 0.0,
        days_to_first_pass=days_to_first_pass or 0.0,
        pass_rate=pass_rate,
        is_censored=is_censored,
        n=total_attempts,
    )


def pace_score(state: PaceState) -> float:
    """
    Aggregate pace into [0, 1] score (higher = faster learning).

    For censored observations, we estimate based on pass rate.
    For uncensored: reward quick time-to-pass.
    """
    if state.n == 0:
        return 0.5  # Neutral

    if not state.is_censored:
        # Uncensored: reward quick pass (< 1 day = 1.0, > 7 days = 0.3)
        days = max(0, state.days_to_first_pass)
        if days < 1:
            return 1.0
        elif days > 7:
            return 0.3
        else:
            return 1.0 - (0.7 * (days - 1) / 6)
    else:
        # Censored: use pass rate as proxy for learning speed
        # 80%+ pass rate on censored = fast learner
        # 0% pass rate = struggling
        return min(1.0, state.pass_rate * 1.2)
