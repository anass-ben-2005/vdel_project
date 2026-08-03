"""
variables/pace.py — Learning Pace: cohort-normalized, censoring-aware.

Baseline bug fixed: computing the cohort median from PASSERS ONLY drops students
still stuck (survivorship bias). Non-passers are kept as censored lower bounds.
Upgrade path: lifelines CoxPHFitter -> per-student hazard ratio.

Transcribed from VDEL_Modules_1_2_Build.md, Variable 4.

Operational note for M1: this variable is cohort-relative by construction, and the
cohort is currently one student (CLAUDE.md section 2 -- Anas is the first student in the
system). With n=1 the cohort median is the student's own time, so the ratio is 1.0 and
the score is pinned at 0.5 by definition. That is not a bug and not a measurement; it is
the variable correctly reporting that it has no cohort to compare against. Read it as
"undefined until a cohort exists", and see features/compute_features.py where the
degenerate case is labelled explicitly.
"""
from math import log2


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def learning_pace(time_to_pass_h, cohort_median_h, elapsed_h=None, censored=False):
    """
    time_to_pass_h : hours from release to first passing run (if passed)
    cohort_median_h: median time-to-pass over PASSERS on this assignment
    elapsed_h      : hours since release so far (used when censored)
    censored       : True if the student has NOT passed yet
    """
    if censored:
        r = max((elapsed_h or 0) / cohort_median_h, 1.0)   # lower bound only
        return {"score": round(_clamp(0.5 - 0.25 * log2(r), 0, 0.5), 3),
                "censored": True,
                "note": "lower-bound; excluded from cohort median calc"}
    r = time_to_pass_h / cohort_median_h
    return {"score": round(_clamp(0.5 - 0.25 * log2(r), 0, 1), 3),
            "ratio": round(r, 3), "censored": False}


def cohort_censoring_rate(n_not_passed, n_total):
    """Assignment-level signal: high rate => assignment may be too hard/unclear."""
    return round(n_not_passed / n_total, 3) if n_total else 0.0
