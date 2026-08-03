"""V1 -- Concept mastery: BKT + KT-IDEM difficulty conditioning + Beta posterior.

Why BKT and not EWMA or DKT (CLAUDE.md section 8): BKT yields a calibrated probability
that predicts next-attempt correctness, so it is falsifiable. It models guess and slip,
so a single failure at high mastery bends the belief instead of breaking it. DKT was
rejected as uninterpretable, which auditability does not permit.

References:
  Corbett & Anderson (1995)  -- Bayesian Knowledge Tracing.
  Pardos & Heffernan (2011)  -- KT-IDEM: item difficulty effect model.
  Beck & Chang (2007)        -- identifiability; guess and slip must stay below 0.5.

`update()` is a pure function of (state, outcome, difficulty, params) with no I/O, so
the formulas are unit-testable in isolation (BUILD_PLAN 1.6).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from scipy.stats import beta as beta_dist

# Ceiling from Beck & Chang (2007). At or above 0.5 the model stops being identifiable:
# "always guessing" and "always knowing" fit the data equally well.
IDENTIFIABILITY_CEILING = 0.49

# Mastery is never allowed to reach exactly 0 or 1.
#
# Not cosmetic. p_new = posterior + (1 - posterior) * p_t drives p towards 1, and in
# floating point it arrives: after eight consecutive passes p_mastery was exactly
# 1.0000. At p = 1 the incorrect-branch posterior is p*slip / (p*slip + 0) = 1, so the
# state becomes absorbing -- no future failure can ever move it. An unfalsifiable belief
# is precisely what BKT was chosen over DKT to avoid. With guess and slip above zero the
# model can never justify certainty anyway, so the bound states what the maths already
# implies.
MASTERY_FLOOR = 0.001
MASTERY_CEILING = 0.999

# TODO(verify): CLAUDE.md gives p_l0=0.30 and p_t=0.15 but no guess/slip values.
# These are placeholders until VDEL_Modules_1_2_Build.md is available. They are the
# single definition point -- sql/03 leaves kt_params.p_guess/p_slip nullable so the
# unknown lives here and nowhere else.
DEFAULT_GUESS = 0.20
DEFAULT_SLIP = 0.10


@dataclass(frozen=True)
class BKTParams:
    """The four BKT parameters for one concept."""

    p_l0: float = 0.30      # prior probability the concept is already known
    p_t: float = 0.15       # probability of learning it at each opportunity
    p_guess: float = DEFAULT_GUESS   # answering correctly without knowing
    p_slip: float = DEFAULT_SLIP     # answering incorrectly while knowing

    def __post_init__(self) -> None:
        object.__setattr__(self, "p_guess", min(self.p_guess, IDENTIFIABILITY_CEILING))
        object.__setattr__(self, "p_slip", min(self.p_slip, IDENTIFIABILITY_CEILING))

    def for_difficulty(self, difficulty: float) -> BKTParams:
        """KT-IDEM: condition guess and slip on item difficulty.

        Difficulty conditions guess/slip, not p_t -- that is what makes this KT-IDEM
        rather than plain BKT with a fudge factor. A hard item is harder to fluke
        (lower guess) and easier to trip over (higher slip).

        TODO(verify): the linear mapping below is a placeholder. Pardos & Heffernan fit
        per-item guess/slip from data; CLAUDE.md does not specify the interim mapping.
        Confined to this one method so it can be swapped without touching update().
        """
        d = max(0.0, min(1.0, difficulty))
        return replace(
            self,
            p_guess=self.p_guess * (1.0 - d),
            p_slip=min(self.p_slip * (1.0 + d), IDENTIFIABILITY_CEILING),
        )


@dataclass(frozen=True)
class MasteryState:
    """The belief about one concept, plus the counts that quantify its uncertainty."""

    p_mastery: float
    n_correct: int = 0
    n_incorrect: int = 0
    previous_p: float | None = None
    param_set: str = "bkt_v1"

    @property
    def n(self) -> int:
        """Observation count. Invariant 8: never ship a mastery estimate without it."""
        return self.n_correct + self.n_incorrect

    def p_correct_next(self, params: BKTParams) -> float:
        """P(correct on the next attempt) -- the falsifiable prediction."""
        return self.p_mastery * (1 - params.p_slip) + (1 - self.p_mastery) * params.p_guess

    def ci90(self) -> tuple[float, float]:
        """90% credible interval from a Beta posterior over the success rate.

        Beta(1 + correct, 1 + incorrect): a uniform prior updated by the observations.

        TODO(verify): CLAUDE.md section 8 shows n=3 -> ci90 [0.18, 0.71]. This
        parameterisation gives [0.10, 0.75] for one correct and two incorrect. The
        documented interval is narrower than any uniform-prior Beta at n=3 (it implies
        about 6 pseudo-observations), so the source document uses a stronger prior that
        the example alone does not determine. tests/test_documented_vectors.py holds the
        documented numbers as a pending check.
        """
        if self.n == 0:
            return (0.0, 1.0)
        a, b = 1 + self.n_correct, 1 + self.n_incorrect
        # float() is load-bearing: scipy returns numpy scalars and psycopg2 cannot adapt
        # numpy types to JSONB. Casting at the boundary keeps numpy out of the database.
        return (
            round(float(beta_dist.ppf(0.05, a, b)), 4),
            round(float(beta_dist.ppf(0.95, a, b)), 4),
        )

    def confidence(self) -> float:
        """How much the estimate should be trusted: narrow interval means confident.

        Derived from the interval rather than picked, so it moves with the evidence.
        TODO(verify) against the documented example (n=3 -> 0.31; this gives 0.35).
        """
        lo, hi = self.ci90()
        return round(1.0 - (hi - lo), 4)

    def trend(self, epsilon: float = 0.05) -> str:
        """Direction of the last update. epsilon is a reporting threshold, not a model
        parameter: below it, movement is noise and should not be shown to a student."""
        if self.previous_p is None:
            return "stable"
        delta = self.p_mastery - self.previous_p
        if delta > epsilon:
            return "up"
        if delta < -epsilon:
            return "down"
        return "stable"

    def to_dict(self, params: BKTParams | None = None) -> dict:
        """The stored shape from CLAUDE.md section 8."""
        params = params or BKTParams()
        return {
            "p_mastery": round(self.p_mastery, 4),
            "p_correct_next": round(self.p_correct_next(params), 4),
            "n": self.n,
            "confidence": self.confidence(),
            "ci90": list(self.ci90()),
            "trend": self.trend(),
            "param_set": self.param_set,
        }


def initial(params: BKTParams | None = None, param_set: str = "bkt_v1") -> MasteryState:
    """A student we have never observed on this concept."""
    params = params or BKTParams()
    return MasteryState(p_mastery=params.p_l0, param_set=param_set)


def update(
    state: MasteryState,
    correct: bool,
    difficulty: float = 0.5,
    params: BKTParams | None = None,
) -> MasteryState:
    """One BKT step. Pure: no I/O, no globals, same inputs give the same output.

    Two stages, in this order:
      1. Evidence. Bayes' rule, conditioned on which outcome was observed.
      2. Learning. The attempt itself was a chance to learn, so p_t is applied after.

    The evidence stage is where the previous implementation was wrong: it used the
    correct-answer numerator for both outcomes, so passing and failing produced the
    identical posterior (0.30 -> 0.825 either way). Both branches are needed.
    """
    params = (params or BKTParams()).for_difficulty(difficulty)
    p = state.p_mastery

    if correct:
        # P(knew | answered correctly)
        numerator = p * (1 - params.p_slip)
        denominator = numerator + (1 - p) * params.p_guess
    else:
        # P(knew | answered incorrectly) -- knowing it but slipping
        numerator = p * params.p_slip
        denominator = numerator + (1 - p) * (1 - params.p_guess)

    posterior = numerator / denominator if denominator > 0 else p

    # Learning happens whether or not the attempt succeeded.
    p_new = posterior + (1 - posterior) * params.p_t

    return MasteryState(
        p_mastery=min(MASTERY_CEILING, max(MASTERY_FLOOR, p_new)),
        n_correct=state.n_correct + (1 if correct else 0),
        n_incorrect=state.n_incorrect + (0 if correct else 1),
        previous_p=p,
        param_set=state.param_set,
    )


def replay(
    outcomes: list[bool],
    difficulty: float = 0.5,
    params: BKTParams | None = None,
    param_set: str = "bkt_v1",
) -> MasteryState:
    """Fold a whole attempt sequence into one state.

    Event sourcing in miniature: the state is always a function of the ordered events,
    never something accumulated in place, so it can always be rebuilt.
    """
    state = initial(params, param_set)
    for correct in outcomes:
        state = update(state, correct, difficulty, params)
    return state
