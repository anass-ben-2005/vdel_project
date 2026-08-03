"""BUILD_PLAN 1.8 -- hand-verification against the worked examples.

Testing by construction: Sara's numbers were computed by hand in
VDEL_Modules_1_2_Build.md, so running the code on her events and matching the output
catches formula transcription errors immediately.

That document is not in this repository, so Sara's events and expected outputs are not
available and the check below is skipped rather than faked. The previous version filled
this file with assertions against constants it had itself invented, which proves only
that the code agrees with itself -- and three of those assertions failed anyway, because
they were never run.

The second test uses the one worked example that IS available: the mastery object in
CLAUDE.md section 8.
"""

from __future__ import annotations

import pytest

from variables.mastery import replay

SOURCE_DOC = "VDEL_Modules_1_2_Build.md"


@pytest.mark.skip(reason=f"{SOURCE_DOC} is not in the repo: Sara's events and expected "
                         f"outputs are unavailable. Unskip when the document arrives.")
def test_sara_matches_the_hand_computation():
    """The M1 DoD's "Sara's numbers match the hand computation".

    When the document is available, this becomes: load her event sequence, run
    features.compute_features over it, and assert equality with the published table --
    per variable, not just on mastery.
    """
    raise AssertionError("unreachable until the source document is available")


@pytest.mark.xfail(
    strict=True,
    reason="The documented interval is narrower than any uniform-prior Beta at n=3 -- it "
           "implies roughly six pseudo-observations, so the source document uses a "
           "stronger prior that the single example does not determine. Recorded as a "
           "live check so it turns green the moment the parameterisation is known.",
)
def test_claude_md_documented_mastery_vector():
    """CLAUDE.md section 8 publishes a full mastery object for spark.aggregation:

        p_mastery 0.412, p_correct_next 0.48, n 3, confidence 0.31, ci90 [0.18, 0.71]

    n=3 with p_mastery below the 0.30 prior implies more failures than successes, so one
    correct and two incorrect is the sequence to try. Everything except the interval is
    a matter of transcription; the interval is the part that needs the document.
    """
    result = replay([False, True, False]).to_dict()
    assert result["n"] == 3
    assert result["ci90"] == [0.18, 0.71]
    assert result["confidence"] == 0.31
