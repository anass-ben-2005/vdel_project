"""BUILD_PLAN 1.8 / Execution Plan M1.5 — hand-verify against Sara.

"Run the code on Sara's synthetic events and confirm the output matches the
hand-computed worked example. This is testing-by-construction and it catches formula
transcription errors immediately."

Sara's events, from vdel_complete_design_document.md:
  - Assignment A2.
  - 10:05  CI r1 FAIL — AnalysisException: ambiguous column 'id'  -> spark.joins
  - 14:06  CI r2 FAIL — wrong agg column                          -> spark.aggregation
  - narrative: "join error fixed in 4h; aggregation-grain error recurring twice
    before passing"; "aggregation declined 0.5 -> 0.40 over A2".

Hand-computed targets, from the Code Agent's working-memory example:
  mastery slice:  spark.joins: 0.47 (n=2) · spark.aggregation: 0.40 (n=3)

One target reproduces and one does not. Both results are recorded here rather than
resolved by tuning parameters, because tuning the code to hit a number the code
disagrees with is how a transcription error becomes permanent.
"""
import pytest

from collectors.error_classifier import classify_error
from variables.mastery import MasteryEstimator


def replay(sequence, difficulty):
    """Replay one concept's outcome sequence and return its snapshot."""
    est = MasteryEstimator()
    for correct in sequence:
        est.update("c", correct=correct, item_difficulty=difficulty)
    return est.snapshot()["c"]


def test_saras_first_error_classifies_to_spark_joins():
    """10:05 — 'AnalysisException: ambiguous column id'. Rule 1 of the table."""
    _, concept = classify_error("AnalysisException: Reference 'id' is ambiguous column")
    assert concept == "spark.joins"


def test_sara_aggregation_matches_the_hand_computation():
    """spark.aggregation: 0.40 at n=3.

    Reproduces exactly. The sequence is fail -> pass -> fail at difficulty 0.4, giving
    the trajectory 0.30 -> 0.211 -> 0.705 -> 0.407, whose final decline is the
    document's own "aggregation declined ... -> 0.40 over A2". The slice is therefore a
    mid-assignment snapshot taken while the aggregation error was still open, which is
    consistent with "unresolved at session end" in the short-term-memory example.
    """
    state = replay([False, True, False], difficulty=0.4)
    assert state["n"] == 3
    assert state["p_mastery"] == pytest.approx(0.40, abs=0.01)


@pytest.mark.xfail(
    strict=True,
    reason="Documented value 0.47 (n=2) is unreachable for spark.joins under the "
           "documented narrative. The narrative says the join error was fixed, i.e. "
           "[fail, pass], which spans 0.591 (difficulty 0) to 0.964 (difficulty 1) -- "
           "0.47 is outside that range at every difficulty. 0.47 is reachable at n=2 "
           "only via [pass, fail] at difficulty ~0.35, which contradicts the narrative. "
           "Needs a ruling: is the slice mid-assignment (as aggregation's is), or is "
           "0.47 a transcription slip in the worked example?",
)
def test_sara_joins_matches_the_hand_computation():
    """spark.joins: 0.47 at n=2, with the narrative sequence fail -> pass."""
    state = replay([False, True], difficulty=0.5)
    assert state["n"] == 2
    assert state["p_mastery"] == pytest.approx(0.47, abs=0.01)


def test_sara_joins_is_unreachable_across_every_difficulty():
    """Pins the finding above so it cannot be quietly lost.

    If a future parameter change makes 0.47 reachable with the narrative sequence, this
    test fails and the xfail above starts passing -- which is the signal to revisit.
    """
    reachable = [replay([False, True], d / 20)["p_mastery"] for d in range(21)]
    assert min(reachable) > 0.47, "0.47 became reachable; revisit test_sara_joins_*"
