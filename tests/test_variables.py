"""V2-V6 - the formulas from VDEL_Modules_1_2_Build.md, Variables 2 to 6."""

import pytest

from variables.error_frequency import error_frequency, recurrence_check
from variables.error_response import error_response
from variables.habits import (
    burstiness_regularity,
    cleanliness,
    cronbachs_alpha,
    effort_regulation,
    engineering_discipline,
    testing_signal,
)
from variables.pace import cohort_censoring_rate, learning_pace


# ---------- V3: Effort Regulation ----------
def test_burstiness_is_the_goh_barabasi_formula():
    """B = (sigma - mu)/(sigma + mu), mapped to [0,1] as (1-B)/2, regular = high."""
    perfectly_regular = [6.0, 6.0, 6.0, 6.0]     # sigma = 0 -> B = -1 -> 1.0
    assert burstiness_regularity(perfectly_regular) == 1.0
    bursty = [0.1, 0.1, 0.1, 200.0]
    assert burstiness_regularity(bursty) < burstiness_regularity([5, 6, 7, 8])


def test_burstiness_refuses_to_fabricate_from_one_gap():
    """The document is explicit: 'do NOT fabricate from 1 gap'."""
    assert burstiness_regularity([4.0]) is None
    assert burstiness_regularity([]) is None


def test_procrastination_is_tracked_but_not_scored():
    """release_to_first_commit is reported so a coach can see it; it never enters a
    score, because a slow start is not itself a failure."""
    result = effort_regulation([2.0, 3.0, 4.0], release_to_first_commit_h=72.0)
    assert result["procrastination_h"] == 72.0
    assert "score" not in result


# ---------- V2: Engineering Discipline ----------
def test_cleanliness_is_violations_per_100_loc():
    """1 - min(1, per_100/10). 10 violations per 100 LOC scores zero."""
    assert cleanliness(0, 1000) == 1.0
    assert cleanliness(100, 1000) == 0.0        # 10 per 100 LOC
    assert cleanliness(50, 1000) == 0.5


def test_cleanliness_is_none_when_nothing_changed():
    """Not measurable is not the same as zero."""
    assert cleanliness(5, 0) is None


def test_testing_signal_levels():
    assert testing_signal("wired") == 1.0
    assert testing_signal("present") == 0.5
    assert testing_signal("absent") == 0.0


def test_composite_is_withheld_until_cronbachs_alpha_justifies_it():
    """The alpha gate (Cronbach, 1951). Below 0.70, report components, not a composite --
    an unjustified composite is worse than none."""
    ungated = engineering_discipline(10, 1000, "wired", cohort_alpha=None)
    assert ungated.composite is None and ungated.composite_valid is False

    weak = engineering_discipline(10, 1000, "wired", cohort_alpha=0.55)
    assert weak.composite is None

    strong = engineering_discipline(10, 1000, "wired", cohort_alpha=0.82)
    assert strong.composite is not None and strong.composite_valid is True


def test_cronbachs_alpha_needs_a_cohort():
    """Fewer than ten students -> None. A cohort of one cannot have an alpha."""
    assert cronbachs_alpha([[0.5, 0.5]] * 9) is None
    assert cronbachs_alpha([]) is None


# ---------- V4: Learning Pace ----------
def test_pace_is_half_at_the_cohort_median():
    """score = 0.5 - 0.25*log2(ratio); ratio 1 -> exactly 0.5."""
    assert learning_pace(10.0, 10.0)["score"] == 0.5


def test_pace_log2_makes_twice_as_fast_and_twice_as_slow_symmetric():
    fast = learning_pace(5.0, 10.0)["score"]    # ratio 0.5 -> 0.75
    slow = learning_pace(20.0, 10.0)["score"]   # ratio 2.0 -> 0.25
    assert fast == pytest.approx(0.75)
    assert slow == pytest.approx(0.25)
    assert fast - 0.5 == pytest.approx(0.5 - slow)


def test_censored_students_are_capped_at_half_and_flagged():
    """A non-passer is a lower bound, never a point estimate, and is excluded from the
    cohort median -- that exclusion is what fixes the survivorship bias."""
    result = learning_pace(None, 10.0, elapsed_h=40.0, censored=True)
    assert result["censored"] is True
    assert result["score"] <= 0.5
    assert "excluded from cohort median" in result["note"]


def test_censoring_never_rewards_being_slow():
    """ratio is floored at 1.0 while censored, so waiting cannot raise the score."""
    barely = learning_pace(None, 10.0, elapsed_h=1.0, censored=True)["score"]
    long_wait = learning_pace(None, 10.0, elapsed_h=1000.0, censored=True)["score"]
    assert barely == 0.5
    assert long_wait < barely


def test_cohort_censoring_rate_flags_the_assignment_not_the_student():
    assert cohort_censoring_rate(8, 10) == 0.8
    assert cohort_censoring_rate(0, 0) == 0.0


# ---------- V5: Error Response ----------
def test_error_response_combines_time_to_fix_and_resolution_ratio():
    """base = mean(ttf_score, resolution_ratio), ttf_score = 1 - median_ttf/24."""
    result = error_response(median_ttf_h=12.0, resolved_errors=5, total_errors=10,
                            concept_opportunities=3, current_mastery=0.8,
                            mastery_slope=0.0)
    assert result["ttf_score"] == pytest.approx(0.5)
    assert result["resolution_ratio"] == pytest.approx(0.5)
    assert result["score"] == pytest.approx(0.5)


def test_wheel_spinning_needs_all_three_conditions():
    """>=8 opportunities AND mastery < 0.6 AND slope <= 0 (Beck & Gong, 2013)."""
    stuck = {"median_ttf_h": 2.0, "resolved_errors": 1, "total_errors": 10,
             "concept_opportunities": 9, "current_mastery": 0.4, "mastery_slope": -0.02}
    assert error_response(**stuck)["wheel_spinning"] is True
    assert error_response(**{**stuck, "concept_opportunities": 7})["wheel_spinning"] is False
    assert error_response(**{**stuck, "current_mastery": 0.7})["wheel_spinning"] is False
    assert error_response(**{**stuck, "mastery_slope": 0.1})["wheel_spinning"] is False


def test_productive_failure_and_wheel_spinning_pull_opposite_ways():
    """Same error count, opposite trajectories: Kapur's productive failure vs Beck &
    Gong's wheel-spinning. This separation is the point of the variable."""
    common = {"median_ttf_h": 6.0, "resolved_errors": 5, "total_errors": 10,
              "concept_opportunities": 9}
    spinning = error_response(**common, current_mastery=0.4, mastery_slope=-0.05)
    learning = error_response(**common, current_mastery=0.4, mastery_slope=0.10)
    assert spinning["wheel_spinning"] and not spinning["productive_failure"]
    assert learning["productive_failure"] and not learning["wheel_spinning"]
    assert learning["score"] > spinning["score"]


def test_no_errors_means_a_perfect_resolution_ratio():
    result = error_response(0.0, 0, 0, 0, 1.0, 0.0)
    assert result["resolution_ratio"] == 1.0


# ---------- V6: Error Frequency ----------
def test_error_frequency_is_normalised_by_opportunity():
    """Raw counts predict little (Jadud, 2006); the ratio is what carries signal."""
    few = error_frequency(2, 100, 2, 1000, {}, 0.0)["score"]
    many = error_frequency(50, 100, 50, 1000, {}, 0.0)["score"]
    assert few > many


def test_error_frequency_reports_the_per_concept_histogram():
    """The load-bearing output: it feeds mastery and the recurrence rule."""
    hist = {"spark.joins": 3, "spark.aggregation": 1}
    assert error_frequency(4, 10, 4, 500, hist, 0.0)["by_concept"] == hist


def test_error_frequency_trend_wording():
    assert error_frequency(1, 10, 1, 100, {}, 0.5)["trend"] == "worsening"
    assert error_frequency(1, 10, 1, 100, {}, -0.5)["trend"] == "improving"
    assert error_frequency(1, 10, 1, 100, {}, 0.0)["trend"] == "flat"


def test_recurrence_rule_opens_a_weakness_at_two():
    """Same error class twice in one assignment (Becker, 2016, Repeated Error Density)."""
    assert recurrence_check({"ambiguous column": 2, "KeyError": 1}) == ["ambiguous column"]
    assert recurrence_check({"KeyError": 1}) == []


def test_zero_runs_does_not_divide_by_zero():
    assert error_frequency(0, 0, 0, 0, {}, 0.0)["fail_ratio"] == 0.0
