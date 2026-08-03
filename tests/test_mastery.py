"""V1 tests — the equations from VDEL_Modules_1_2_Build.md, Variable 1.

The document publishes the equations explicitly, so these assert them directly rather
than asserting properties around them. Where a specific number is checked it is
recomputed from the published formula in the test, so the test fails if the transcription
drifts -- not merely if the code disagrees with itself.
"""
import json

import pytest

from variables.mastery import (
    BKTParams,
    DifficultyEstimator,
    MasteryEstimator,
    MasteryState,
    _apply_learning,
    _posterior_given_obs,
    predict_correct,
)


def test_documented_defaults():
    """p_l0=0.30, p_t=0.15, p_guess=0.20, p_slip=0.10."""
    p = BKTParams()
    assert (p.p_l0, p.p_t, p.p_guess, p.p_slip) == (0.30, 0.15, 0.20, 0.10)


def test_evidence_step_matches_the_published_equations():
    """p(L|c) = p(L)(1-S) / [p(L)(1-S) + (1-p(L))G]
       p(L|!c) = p(L)S / [p(L)S + (1-p(L))(1-G)]"""
    p_L, g, s = 0.30, 0.20, 0.10
    assert _posterior_given_obs(p_L, True, g, s) == pytest.approx(
        p_L * (1 - s) / (p_L * (1 - s) + (1 - p_L) * g))
    assert _posterior_given_obs(p_L, False, g, s) == pytest.approx(
        p_L * s / (p_L * s + (1 - p_L) * (1 - g)))


def test_outcome_actually_changes_the_posterior():
    """The two branches must differ. A single-branch implementation makes the model
    ignore its evidence, which is a silent and total failure."""
    assert _posterior_given_obs(0.3, True, 0.2, 0.1) != _posterior_given_obs(
        0.3, False, 0.2, 0.1)


def test_learning_step_matches_the_published_equation():
    """p(L) = p(L|obs) + (1 - p(L|obs))*T"""
    assert _apply_learning(0.4, 0.15) == pytest.approx(0.4 + 0.6 * 0.15)


def test_prediction_matches_the_published_equation():
    """P(correct_next) = p(L)(1-S) + (1-p(L))G"""
    p = BKTParams()
    assert predict_correct(0.5, p) == pytest.approx(0.5 * 0.9 + 0.5 * 0.2)


def test_kt_idem_item_conditioning():
    """G_item = G(1-d);  S_item = S + (0.40-S)*d*0.5"""
    base = BKTParams()
    for d in (0.0, 0.25, 0.5, 1.0):
        item = base.for_item(d)
        assert item.p_guess == pytest.approx(max(0.01, 0.20 * (1 - d)))
        assert item.p_slip == pytest.approx(0.10 + (0.40 - 0.10) * d * 0.5)
    # Difficulty conditions guess and slip, never the learning rate.
    assert base.for_item(1.0).p_t == base.p_t


def test_identifiability_guard():
    """Beck & Chang (2007): guess clamped to [0.01, 0.45], slip to [0.00, 0.45]."""
    wild = BKTParams(p_guess=0.99, p_slip=0.99).guarded()
    assert wild.p_guess == 0.45
    assert wild.p_slip == 0.45
    assert BKTParams(p_guess=0.0).guarded().p_guess == 0.01


def test_beta_posterior_uses_a_jeffreys_prior():
    """a and b start at 0.5, not 0 and not 1 — a Jeffreys prior."""
    st = MasteryState()
    assert (st.a, st.b) == (0.5, 0.5)
    est = MasteryEstimator()
    est.update("c", correct=True)
    est.update("c", correct=False)
    assert (est.states["c"].a, est.states["c"].b) == (1.5, 1.5)


def test_variance_and_confidence_match_the_published_formulas():
    st = MasteryState(a=1.5, b=2.5)
    a, b = 1.5, 2.5
    assert st.variance == pytest.approx((a * b) / ((a + b) ** 2 * (a + b + 1)))
    assert st.confidence == pytest.approx(1.0 - min(1.0, st.variance ** 0.5 / 0.35))


def test_more_evidence_narrows_the_interval():
    def width(n):
        est = MasteryEstimator()
        for _ in range(n):
            est.update("c", correct=True)
        lo, hi = est.states["c"].credible_interval(0.90)
        return hi - lo
    assert width(20) < width(2)


def test_trend_thresholds():
    """slope > 0.03 -> up; < -0.03 -> down; otherwise flat. Fewer than 2 points -> flat."""
    assert MasteryState(history=(0.30,)).trend() == "flat"
    assert MasteryState(history=(0.30, 0.50)).trend() == "up"
    assert MasteryState(history=(0.50, 0.30)).trend() == "down"
    assert MasteryState(history=(0.300, 0.310)).trend() == "flat"


def test_update_does_not_mutate_its_params():
    """The document's contract: update() is a pure function of its inputs. The estimator
    holds the state; the parameters must survive a call unchanged."""
    params = BKTParams()
    est = MasteryEstimator(default_params=params)
    est.update("c", correct=False, item_difficulty=0.9)
    assert params == BKTParams()


def test_snapshot_is_json_serialisable():
    """Feature rows go into a JSONB column; a numpy scalar from scipy would raise at
    insert time."""
    est = MasteryEstimator()
    est.update("spark.joins", correct=False)
    assert json.loads(json.dumps(est.snapshot()))["spark.joins"]["n"] == 1


def test_difficulty_estimator_is_one_minus_smoothed_pass_rate():
    """difficulty = 1 - a/(a+b), Beta(2,2)-smoothed."""
    d = DifficultyEstimator()
    assert d.difficulty("unseen") == pytest.approx(0.5)   # prior 2/(2+2)
    for _ in range(6):
        d.observe("easy", passed=True)
    assert d.difficulty("easy") < 0.3
    for _ in range(6):
        d.observe("hard", passed=False)
    assert d.difficulty("hard") > 0.7
