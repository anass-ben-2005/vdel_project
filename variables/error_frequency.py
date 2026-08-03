"""
variables/error_frequency.py — Error Frequency (V6).

Raw error counts predict little on their own (Jadud, 2006) — the load-bearing outputs
are the per-concept histogram (feeds mastery) and the recurrence rule (opens weaknesses;
Becker, 2016, Repeated Error Density).

Transcribed from VDEL_Modules_1_2_Build.md, Variable 6.
"""
from statistics import mean


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def error_frequency(failed_runs, total_runs, errors, changed_loc,
                    by_concept, weekly_slope):
    fail_ratio = failed_runs / total_runs if total_runs else 0.0
    per_100 = errors / (changed_loc / 100.0) if changed_loc else 0.0
    score = 1.0 - _clamp(mean([fail_ratio, min(1.0, per_100 / 5.0)]), 0, 1)
    return {"score": round(score, 3), "fail_ratio": round(fail_ratio, 3),
            "by_concept": by_concept,   # {concept_id: count} -> mastery + weaknesses
            "trend": ("worsening" if weekly_slope > 0
                      else "improving" if weekly_slope < 0 else "flat")}


def recurrence_check(error_class_counts_this_assignment):
    """Same error class >=2 within one assignment -> open a weakness now."""
    return [ec for ec, n in error_class_counts_this_assignment.items() if n >= 2]
