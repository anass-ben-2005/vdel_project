"""Error frequency (V6): opportunity-normalised error rate."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ErrorFrequencyState:
    """Error frequency metrics."""
    total_attempts: int = 0
    total_failures: int = 0
    error_rate: float = 0.0  # failures / attempts
    error_rate_normalized: float = 0.0  # Accounting for concept difficulty
    n: int = 0


def compute_error_frequency(
    total_attempts: int,
    total_failures: int,
    concept_difficulty: Optional[float] = None,
    time_window_days: int = 14,
) -> ErrorFrequencyState:
    """
    Compute error frequency (V6): how often errors occur.

    Normalized by: concept difficulty + time window (avoid penalizing early attempts).

    **Important boundary (CLAUDE.md §8):**
    - Error frequency = how often errors happen (a rate)
    - Error response = what student does about them (a behaviour)

    High frequency + high engagement = learning by experimentation, not struggling.

    Args:
        total_attempts: Total workflow runs attempted
        total_failures: Workflow runs that failed
        concept_difficulty: Difficulty of concepts tested (0-1, affects baseline)
        time_window_days: Observation window (affects interpretation)

    Returns:
        ErrorFrequencyState
    """
    if total_attempts == 0:
        return ErrorFrequencyState()

    # Raw error rate
    error_rate = total_failures / total_attempts

    # Normalize by difficulty: harder concepts = more errors expected
    # Difficulty 0.5 (medium) = baseline; 0.8 (hard) = higher baseline acceptable
    if concept_difficulty is not None:
        # Baseline error rate for this difficulty
        baseline = 0.3 + (0.4 * concept_difficulty)  # 0.3-0.7 range
        normalized_rate = error_rate / (baseline + 1e-6)
    else:
        normalized_rate = error_rate

    return ErrorFrequencyState(
        total_attempts=total_attempts,
        total_failures=total_failures,
        error_rate=error_rate,
        error_rate_normalized=normalized_rate,
        n=total_attempts,
    )


def error_frequency_score(state: ErrorFrequencyState) -> float:
    """
    Aggregate error frequency into [0, 1] score (higher = better).

    Rules:
    - 0% error rate: perfect, but suspicious if only 1 attempt
    - ~30% error rate: healthy learning rate
    - >70% error rate: struggling
    - Adjustment: few attempts = higher uncertainty
    """
    if state.n == 0:
        return 0.5  # Neutral

    # Invert error rate (higher error_rate = lower score)
    # 0% errors = 1.0, 50% errors = 0.5, 100% errors = 0.0
    base_score = 1.0 - state.error_rate

    # Adjust for observation count: high variance with few attempts
    # Confidence increases with sqrt(n)
    import math
    confidence_factor = min(1.0, math.sqrt(state.n) / math.sqrt(20))

    # Confidence-weighted score
    neutral_baseline = 0.5
    adjusted_score = neutral_baseline + (base_score - neutral_baseline) * confidence_factor

    return adjusted_score
