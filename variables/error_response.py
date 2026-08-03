"""
variables/error_response.py — Error Response (V5).

Grounded in Jadud's Error Quotient (2006) and the Watwin score (Watson et al., 2013),
with a productive-vs-unproductive layer: wheel-spinning (Beck & Gong, 2013) vs.
productive failure (Kapur, 2008). The distinction drives the intervention.

Transcribed from VDEL_Modules_1_2_Build.md, Variable 5.
"""
from statistics import mean


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def error_response(median_ttf_h, resolved_errors, total_errors,
                   concept_opportunities, current_mastery, mastery_slope):
    ttf_score = _clamp(1 - median_ttf_h / 24.0, 0, 1)
    resolution_ratio = resolved_errors / total_errors if total_errors else 1.0
    base = mean([ttf_score, resolution_ratio])

    wheel_spinning = (concept_opportunities >= 8 and current_mastery < 0.6
                      and mastery_slope <= 0.0)
    productive = mastery_slope > 0.03

    score = base
    if wheel_spinning:
        score = _clamp(base - 0.25, 0, 1)
    elif productive:
        score = _clamp(base + 0.15, 0, 1)

    return {"score": round(score, 3), "ttf_score": round(ttf_score, 3),
            "resolution_ratio": round(resolution_ratio, 3),
            "wheel_spinning": wheel_spinning, "productive_failure": productive}
