"""V4 -- Learning pace: released -> first commit -> first pass, censoring-aware.

"Censored" means the student has not passed yet, so their time-to-pass is unknown --
but not uninformative. Someone eight days into a ten-day window with no pass has a
time-to-pass of at least eight days, which bounds their score from above. Reporting that
bound is honest; the previous version invented `pass_rate * 1.2` for censored cases,
which is a fabricated point estimate for a quantity that has not been observed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from variables import clamp01

# Fallback window when an assignment has no due date. TODO(verify).
DEFAULT_WINDOW_DAYS = 14.0


def _utc(ts: datetime) -> datetime:
    """Force timezone-awareness.

    The previous version mixed naive datetime.utcnow() with timezone-aware TIMESTAMPTZ
    values from the database, which raises TypeError on subtraction at runtime.
    """
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def learning_pace(
    released_at: datetime,
    due_at: datetime | None,
    first_commit_at: datetime | None,
    first_pass_at: datetime | None,
    attempts: int,
    now: datetime | None = None,
) -> dict:
    """V4 for one assignment.

    The score is elapsed time to first pass as a fraction of the assignment's own
    window, so the yardstick is the real released->due interval rather than a constant
    someone picked.
    """
    released_at = _utc(released_at)
    now = _utc(now or datetime.now(UTC))

    window_days = (
        (_utc(due_at) - released_at).total_seconds() / 86400 if due_at else DEFAULT_WINDOW_DAYS
    )
    window_days = max(window_days, 0.5)  # a zero-length window would divide by zero

    def days_since_release(ts: datetime) -> float:
        return max(0.0, (_utc(ts) - released_at).total_seconds() / 86400)

    result: dict = {
        "n": attempts,
        "window_days": round(window_days, 2),
        "days_to_first_commit": (
            round(days_since_release(first_commit_at), 3) if first_commit_at else None
        ),
    }

    if first_pass_at:
        days = days_since_release(first_pass_at)
        result |= {
            "censored": False,
            "days_to_first_pass": round(days, 3),
            "score": round(clamp01(1 - days / window_days), 4),
        }
    else:
        # Not passed yet. Time-to-pass exceeds the elapsed time, so the score it would
        # eventually earn cannot be higher than the score for the time already spent.
        elapsed = days_since_release(now)
        result |= {
            "censored": True,
            "days_elapsed": round(elapsed, 3),
            "score": None,
            "score_upper_bound": round(clamp01(1 - elapsed / window_days), 4),
        }

    return result
