"""
variables/mastery.py — Concept-mastery estimation for the VDEL Learner Digital Twin.

Model: Bayesian Knowledge Tracing (Corbett & Anderson, 1994)
       + item-difficulty conditioning (KT-IDEM, Pardos & Heffernan, 2011)
       + Beta-Bernoulli companion posterior for calibrated uncertainty.

Design contract:
  - update() is a PURE function of (prior_state, outcome, difficulty, params).
  - p_mastery is a CALIBRATED probability; p_correct_next is externally testable.
  - Identifiability guard (Beck & Chang, 2007): guess, slip clamped < 0.5.

Transcribed from VDEL_Modules_1_2_Build.md, Variable 1. The formulas, constants and
clamps are the document's, not this file's. Nothing here is a design choice; see
BUILD_PLAN.md ("Your job is largely to transcribe... If you believe it needs changing,
stop and ask").
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from math import sqrt

try:
    from scipy.stats import beta as _beta
    _HAVE_SCIPY = True
except ImportError:
    _HAVE_SCIPY = False


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


@dataclass(frozen=True)
class BKTParams:
    """Per-concept BKT parameters. Defaults are literature-grounded cold-start
    priors; replace with EM-fitted values once >~100 sequences per concept exist."""

    p_l0:    float = 0.30
    p_t:     float = 0.15
    p_guess: float = 0.20
    p_slip:  float = 0.10

    def guarded(self) -> "BKTParams":
        return replace(self,
                       p_guess=_clamp(self.p_guess, 0.01, 0.45),
                       p_slip=_clamp(self.p_slip,  0.00, 0.45))

    def for_item(self, difficulty: float) -> "BKTParams":
        d = _clamp(difficulty, 0.0, 1.0)
        g = self.p_guess * (1.0 - d)
        s = self.p_slip + (0.40 - self.p_slip) * d * 0.5
        return replace(self, p_guess=g, p_slip=s).guarded()


@dataclass
class MasteryState:
    p_mastery: float = 0.30
    n_obs:     int = 0
    a:         float = 0.5     # Beta posterior — passes + 0.5 (Jeffreys prior)
    b:         float = 0.5     # Beta posterior — fails  + 0.5
    history:   tuple = ()

    def credible_interval(self, level: float = 0.90):
        lo_q, hi_q = (1 - level) / 2, 1 - (1 - level) / 2
        if _HAVE_SCIPY:
            return float(_beta.ppf(lo_q, self.a, self.b)), \
                   float(_beta.ppf(hi_q, self.a, self.b))
        m, v = self.a / (self.a + self.b), self.variance
        return _clamp(m - 1.645 * sqrt(v), 0, 1), _clamp(m + 1.645 * sqrt(v), 0, 1)

    @property
    def variance(self):
        a, b = self.a, self.b
        return (a * b) / ((a + b) ** 2 * (a + b + 1))

    @property
    def confidence(self):
        return 1.0 - min(1.0, sqrt(self.variance) / 0.35)

    def trend(self):
        if len(self.history) < 2:
            return "flat"
        slope = self.history[-1] - self.history[0]
        return "up" if slope > 0.03 else "down" if slope < -0.03 else "flat"


def _posterior_given_obs(p_L, correct, g, s):
    if correct:
        num = p_L * (1.0 - s)
        den = num + (1.0 - p_L) * g
    else:
        num = p_L * s
        den = num + (1.0 - p_L) * (1.0 - g)
    return num / den if den > 1e-9 else p_L


def _apply_learning(p_L_post, t):
    return p_L_post + (1.0 - p_L_post) * t


def predict_correct(p_L, params):
    p = params.guarded()
    return p_L * (1.0 - p.p_slip) + (1.0 - p_L) * p.p_guess


class MasteryEstimator:
    """One instance manages the full mastery vector for one student."""

    def __init__(self, params_by_concept=None,
                 default_params=BKTParams(), history_len=6):
        self.params_by_concept = params_by_concept or {}
        self.default_params = default_params
        self.history_len = history_len
        self.states: dict[str, MasteryState] = {}

    def _params(self, concept):
        return self.params_by_concept.get(concept, self.default_params).guarded()

    def _state(self, concept):
        if concept not in self.states:
            p = self._params(concept)
            self.states[concept] = MasteryState(p_mastery=p.p_l0, history=(p.p_l0,))
        return self.states[concept]

    def update(self, concept, correct, item_difficulty=0.5):
        st = self._state(concept)
        params = self._params(concept).for_item(item_difficulty)
        before = st.p_mastery
        post = _posterior_given_obs(st.p_mastery, correct, params.p_guess, params.p_slip)
        st.p_mastery = _apply_learning(post, params.p_t)
        st.a += 1.0 if correct else 0.0
        st.b += 0.0 if correct else 1.0
        st.n_obs += 1
        st.history = (st.history + (round(st.p_mastery, 4),))[-self.history_len:]
        lo, hi = st.credible_interval(0.90)
        return {
            "concept": concept,
            "p_mastery": round(st.p_mastery, 4),
            "p_mastery_before": round(before, 4),
            "p_correct_next": round(predict_correct(st.p_mastery, self._params(concept)), 4),
            "n_obs": st.n_obs, "confidence": round(st.confidence, 3),
            "ci90": [round(lo, 3), round(hi, 3)], "variance": round(st.variance, 4),
            "trend": st.trend(), "item_difficulty": round(item_difficulty, 3),
            "eff_guess": round(params.p_guess, 3), "eff_slip": round(params.p_slip, 3),
        }

    def snapshot(self):
        out = {}
        for c, st in self.states.items():
            lo, hi = st.credible_interval(0.90)
            out[c] = {"p_mastery": round(st.p_mastery, 4), "n": st.n_obs,
                      "confidence": round(st.confidence, 3),
                      "ci90": [round(lo, 3), round(hi, 3)], "trend": st.trend()}
        return out


class DifficultyEstimator:
    """difficulty = 1 - Beta-smoothed cohort pass rate, per item."""

    def __init__(self, prior_a=2.0, prior_b=2.0):
        self.counts: dict[str, list] = {}
        self.prior = (prior_a, prior_b)

    def observe(self, item_id, passed):
        a, b = self.counts.get(item_id, list(self.prior))
        self.counts[item_id] = [a + (1 if passed else 0), b + (0 if passed else 1)]

    def difficulty(self, item_id):
        a, b = self.counts.get(item_id, self.prior)
        return 1.0 - a / (a + b)
