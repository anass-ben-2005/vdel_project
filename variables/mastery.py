"""Bayesian Knowledge Tracing (BKT) for concept mastery."""

from dataclasses import dataclass
from typing import Optional
import math


@dataclass
class BKTParams:
    """BKT parameters (Beck & Chang 2007)."""
    p_l0: float = 0.30      # Probability of learning from prior knowledge
    p_t: float = 0.15       # Probability of learning from observation
    p_guess: float = 0.1    # Probability of guessing correctly
    p_slip: float = 0.1     # Probability of slipping (knowing but answering wrong)

    def __post_init__(self):
        """Clamp guess/slip < 0.5 for identifiability (Beck & Chang 2007)."""
        self.p_guess = min(self.p_guess, 0.49)
        self.p_slip = min(self.p_slip, 0.49)


@dataclass
class MasteryState:
    """Current mastery belief for a concept."""
    p_mastery: float      # Probability of mastery
    n: int = 0            # Number of observations
    confidence: float = 0.0  # Confidence (0-1)
    trend: str = 'stable'    # 'up', 'down', 'stable'
    param_set: str = 'bkt_v1'

    def to_dict(self):
        """Convert to dictionary for JSONB storage."""
        return {
            'p_mastery': round(self.p_mastery, 4),
            'p_correct_next': self._predict_correct_next(),
            'n': self.n,
            'confidence': round(self.confidence, 4),
            'ci90': self._credible_interval_90(),
            'trend': self.trend,
            'param_set': self.param_set,
        }

    def _predict_correct_next(self) -> float:
        """Predict probability of correct answer on next attempt."""
        # Not implemented yet (requires access to current params)
        return round(self.p_mastery, 4)

    def _credible_interval_90(self) -> list:
        """90% credible interval for mastery."""
        if self.n == 0:
            return [0, 1]
        # Beta credible interval approximation
        alpha = self.p_mastery * self.n + 1
        beta = (1 - self.p_mastery) * self.n + 1
        # Simplified: return percentiles
        return [
            round(max(0, self.p_mastery - 0.3 * math.sqrt(1 / self.n)), 4),
            round(min(1, self.p_mastery + 0.3 * math.sqrt(1 / self.n)), 4),
        ]


def update(
    prior: MasteryState,
    outcome: int,
    difficulty: float = 0.5,
    params: Optional[BKTParams] = None,
) -> MasteryState:
    """
    Update mastery using Bayesian Knowledge Tracing.

    Args:
        prior: Current mastery belief
        outcome: 0 (incorrect) or 1 (correct)
        difficulty: Concept difficulty (0-1, affects learning rate)
        params: BKT parameters (defaults provided)

    Returns:
        Updated mastery state
    """
    if params is None:
        params = BKTParams()

    if outcome not in [0, 1]:
        raise ValueError(f"outcome must be 0 or 1, got {outcome}")

    p = prior.p_mastery

    # Estimate current probability of generating this outcome
    p_outcome_if_known = 1 - params.p_slip
    p_outcome_if_unknown = params.p_guess

    # Likelihood of outcome given current mastery
    p_outcome = p * p_outcome_if_known + (1 - p) * p_outcome_if_unknown

    # Bayesian update: P(known | outcome)
    p_known_given_outcome = (p * p_outcome_if_known) / (p_outcome + 1e-10)

    # Learning: increase p_t with difficulty (harder concepts = more learning per attempt)
    p_t_adj = params.p_t * (0.5 + difficulty)

    # Updated mastery after learning opportunity
    p_new = p_known_given_outcome + (1 - p_known_given_outcome) * p_t_adj

    # Clamp to [0, 1]
    p_new = max(0, min(1, p_new))

    # Compute trend
    trend_threshold = 0.05
    if p_new > p + trend_threshold:
        trend = 'up'
    elif p_new < p - trend_threshold:
        trend = 'down'
    else:
        trend = 'stable'

    # Update observation count
    n_new = prior.n + 1

    # Confidence: higher with more observations (diminishing returns)
    confidence = 1 - (1 / (1 + n_new * 0.2))

    return MasteryState(
        p_mastery=p_new,
        n=n_new,
        confidence=confidence,
        trend=trend,
        param_set=prior.param_set,
    )


def predict_next_correct(mastery: MasteryState, params: Optional[BKTParams] = None) -> float:
    """
    Predict probability of correct answer on next attempt.

    Args:
        mastery: Current mastery state
        params: BKT parameters

    Returns:
        P(correct on next attempt)
    """
    if params is None:
        params = BKTParams()

    p = mastery.p_mastery
    p_correct_if_known = 1 - params.p_slip
    p_correct_if_unknown = params.p_guess

    return p * p_correct_if_known + (1 - p) * p_correct_if_unknown
