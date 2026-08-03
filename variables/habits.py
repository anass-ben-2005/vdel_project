"""
variables/habits.py — Engineering Discipline (V2) + Effort Regulation (V3).

Split from the original "coding habits" per Zimmerman's SRL framework:
  - Engineering Discipline = cognition/skill (cleanliness, testing)
  - Effort Regulation      = behavior (commit regularity, procrastination)

Fixes vs. baseline:
  - CV-based regularity (unstable at low n) -> burstiness (Goh & Barabási, 2008)
  - fixed magic-number thresholds -> cohort-relative percentiles
  - equal-weight averaging with no justification -> Cronbach's alpha gate (Cronbach 1951)

Transcribed from VDEL_Modules_1_2_Build.md, Variables 2 & 3.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, pstdev, variance


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ----- Effort Regulation: regularity via burstiness -----
def burstiness_regularity(gap_hours):
    """B in [-1,1]: -1 periodic, 0 random, +1 bursty. Mapped to [0,1], regular=high.
    Returns None if too few gaps (do NOT fabricate from 1 gap)."""
    if len(gap_hours) < 2:
        return None
    mu, sigma = mean(gap_hours), pstdev(gap_hours)
    if mu + sigma == 0:
        return 1.0
    B = (sigma - mu) / (sigma + mu)
    return round((1.0 - B) / 2.0, 3)


def effort_regulation(gap_hours, release_to_first_commit_h):
    return {
        "regularity": burstiness_regularity(gap_hours),
        "burstiness": (round((pstdev(gap_hours) - mean(gap_hours)) /
                             (pstdev(gap_hours) + mean(gap_hours)), 3)
                       if len(gap_hours) >= 2 and (pstdev(gap_hours) + mean(gap_hours)) > 0
                       else None),
        "procrastination_h": round(release_to_first_commit_h, 1),  # tracked, NOT scored
    }


# ----- Engineering Discipline: cleanliness + testing -----
def cleanliness(lint_violations, changed_loc):
    if changed_loc <= 0:
        return None
    per_100 = lint_violations / (changed_loc / 100.0)
    return round(1.0 - min(1.0, per_100 / 10.0), 3)


def testing_signal(state):  # 'wired' | 'present' | 'absent'
    return {"wired": 1.0, "present": 0.5, "absent": 0.0}[state]


def cronbachs_alpha(item_matrix):
    """rows=students, cols=sub-signals in [0,1]. >=0.70 => composite defensible."""
    if len(item_matrix) < 10:
        return None
    k = len(item_matrix[0])
    item_vars = [variance([row[c] for row in item_matrix]) for c in range(k)]
    total_var = variance([sum(row) for row in item_matrix])
    if total_var == 0:
        return None
    return round((k / (k - 1)) * (1 - sum(item_vars) / total_var), 3)


@dataclass
class DisciplineResult:
    cleanliness: float | None
    testing: float
    composite: float | None
    composite_valid: bool
    alpha: float | None

    def to_dict(self) -> dict:
        """JSONB-ready. Added for the features layer; the fields are the document's.

        Note the composite is None until a cohort exists: with fewer than ten students
        cronbachs_alpha() cannot be computed, so the gate cannot open. That is the
        document's own honesty mechanism, not a gap -- an unjustified composite is worse
        than none, so the components are reported instead.
        """
        return {
            "cleanliness": self.cleanliness,
            "testing": self.testing,
            "composite": self.composite,
            "composite_valid": self.composite_valid,
            "alpha": self.alpha,
        }


def engineering_discipline(lint_violations, changed_loc, tests_state,
                           cohort_alpha=None):
    C = cleanliness(lint_violations, changed_loc)
    T = testing_signal(tests_state)
    valid = cohort_alpha is not None and cohort_alpha >= 0.70
    comps = [v for v in (C, T) if v is not None]
    composite = round(mean(comps), 3) if (comps and valid) else None
    return DisciplineResult(C, T, composite, valid, cohort_alpha)
