"""V1 tests.

These assert structural properties of BKT rather than specific numbers. The numbers
depend on guess/slip values that are placeholders until VDEL_Modules_1_2_Build.md is
available, so asserting them would only prove the code agrees with itself -- which is
what the previous test suite did. Properties like "a failure must lower the belief" hold
for any valid parameterisation, so they keep their meaning when the constants change.
"""

from __future__ import annotations

import json

import pytest

from variables.mastery import (
    IDENTIFIABILITY_CEILING,
    MASTERY_CEILING,
    BKTParams,
    initial,
    replay,
    update,
)


def test_failure_lowers_and_success_raises():
    """The bug that made the first implementation useless.

    It used the correct-answer numerator for both branches, so passing and failing gave
    the identical posterior (0.30 -> 0.825 either way): the model ignored the evidence.
    """
    start = initial()
    assert update(start, correct=False).p_mastery < start.p_mastery
    assert update(start, correct=True).p_mastery > start.p_mastery


def test_belief_never_saturates():
    """A saturated belief is an unfalsifiable one.

    Once p_mastery reached exactly 1.0 the incorrect-branch posterior was also 1.0, so
    no amount of failure could move it. BKT was chosen over DKT for falsifiability; an
    absorbing state gives that away.
    """
    confident = replay([True] * 20)
    assert confident.p_mastery <= MASTERY_CEILING
    assert update(confident, correct=False).p_mastery < confident.p_mastery


def test_one_failure_bends_a_strong_belief_rather_than_breaking_it():
    """The reason slip is modelled at all (CLAUDE.md section 8)."""
    strong = replay([True] * 8)
    after = update(strong, correct=False)
    assert after.p_mastery < strong.p_mastery
    assert after.p_mastery > 0.5, "one slip should not erase eight successes"


def test_update_is_pure():
    """BUILD_PLAN 1.6 requires a pure function of (state, outcome, difficulty, params)."""
    start = initial()
    first = update(start, correct=True)
    second = update(start, correct=True)
    assert first == second, "same inputs must give the same output"
    assert start.p_mastery == pytest.approx(0.30), "input state must not be mutated"


def test_observation_count_always_travels_with_the_estimate():
    """Invariant 8: 0.9 from n=2 is a rumour, from n=20 a fact."""
    state = replay([True, False, True])
    assert state.n == 3
    assert state.to_dict()["n"] == 3


def test_more_evidence_narrows_the_interval():
    narrow = replay([True] * 20).ci90()
    wide = replay([True] * 2).ci90()
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_output_is_json_serialisable():
    """scipy returns numpy scalars and psycopg2 cannot adapt them to JSONB.

    Without the float() cast in ci90() this dict reaches the database and raises
    ProgrammingError at insert time -- the same class of failure as the previous
    version's str(dict).
    """
    payload = replay([False, True, True]).to_dict()
    assert json.loads(json.dumps(payload))["n"] == 3


def test_identifiability_guard_is_enforced():
    """Beck & Chang (2007): at or above 0.5 the model stops being identifiable."""
    reckless = BKTParams(p_guess=0.9, p_slip=0.8)
    assert reckless.p_guess <= IDENTIFIABILITY_CEILING
    assert reckless.p_slip <= IDENTIFIABILITY_CEILING


def test_kt_idem_conditions_guess_and_slip_not_learning_rate():
    """What distinguishes KT-IDEM from BKT with difficulty bolted onto p_t."""
    base = BKTParams()
    easy, hard = base.for_difficulty(0.0), base.for_difficulty(1.0)

    assert hard.p_guess < easy.p_guess, "a hard item is harder to fluke"
    assert hard.p_slip > easy.p_slip, "a hard item is easier to trip over"
    assert hard.p_t == base.p_t, "difficulty must not be smuggled into the learning rate"


def test_failing_a_hard_item_is_less_damning_than_failing_an_easy_one():
    start = initial()
    assert (
        update(start, correct=False, difficulty=0.9).p_mastery
        > update(start, correct=False, difficulty=0.1).p_mastery
    )


def test_prediction_stays_a_probability():
    params = BKTParams()
    for outcomes in ([], [True] * 10, [False] * 10, [True, False] * 5):
        assert 0.0 <= replay(outcomes).p_correct_next(params) <= 1.0


def test_replay_is_event_sourcing_in_miniature():
    """The same events in the same order must always rebuild the same state."""
    events = [True, False, False, True, True]
    assert replay(events) == replay(events)
