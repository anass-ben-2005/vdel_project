"""V2 -- Engineering discipline, and V3 -- Effort regulation.

V2 asks whether the student writes code an engineer would keep: linted, tested, green.
V3 asks whether they work steadily or in panics before a deadline.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from itertools import pairwise

from variables import clamp01

# TODO(verify): the density at which lint quality scores zero. 10 findings per 100 lines
# is an anchor, not a measurement -- VDEL_Modules_1_2_Build.md should replace it.
LINT_ZERO_AT_PER_100_LOC = 10.0


def engineering_discipline(
    lint_findings: int | None,
    lines_of_code: int | None,
    tests_present: bool | None,
    tests_green: bool | None,
) -> dict:
    """V2, from ruff/sqlfluff findings per 100 LOC plus test presence and result.

    Every argument is optional and None means "not measured". The previous version
    invented all four (`violations = commit_count // 20`, `tests_present=True`
    hardcoded) and wrote the result to the database as though it were observed. A
    variable with nothing behind it reports None.

    Components are weighted equally: with no data on their relative predictive value,
    equal weights are the assumption that adds least. TODO(verify) against the source
    document.
    """
    components: list[float] = []
    detail: dict = {}

    if lint_findings is not None and lines_of_code:
        density = lint_findings / lines_of_code * 100
        detail["lint_per_100_loc"] = round(density, 2)
        components.append(clamp01(1 - density / LINT_ZERO_AT_PER_100_LOC))

    if tests_present is not None:
        detail["tests_present"] = tests_present
        components.append(1.0 if tests_present else 0.0)

    if tests_green is not None:
        detail["tests_green"] = tests_green
        components.append(1.0 if tests_green else 0.0)

    return {
        "score": round(sum(components) / len(components), 4) if components else None,
        "n": len(components),
        **detail,
    }


def effort_regulation(commit_times: list[datetime]) -> dict:
    """V3, from the burstiness of inter-commit gaps.

    Burstiness B = (sigma - mu) / (sigma + mu), from Goh & Barabasi (2008). Chosen
    because it is bounded in [-1, 1] by construction, so mapping it to a score needs no
    invented divisor: B = -1 is perfectly regular work, B = +1 is maximally bursty, and
    score = (1 - B) / 2 lands in [0, 1] with no free parameter. The previous version
    used sigma/mu divided by an arbitrary 3, which is unbounded and clipped silently.

    Steady work scores high; long silences broken by a cramming burst score low.
    """
    if len(commit_times) < 3:
        # Two commits give one gap, and one gap has no dispersion to measure.
        return {"score": None, "n": len(commit_times), "reason": "need >= 3 commits"}

    ordered = sorted(commit_times)
    gaps_h = [(b - a).total_seconds() / 3600 for a, b in pairwise(ordered)]

    mu = statistics.fmean(gaps_h)
    sigma = statistics.stdev(gaps_h)
    burstiness = (sigma - mu) / (sigma + mu) if (sigma + mu) > 0 else 0.0

    return {
        "score": round(clamp01((1 - burstiness) / 2), 4),
        "n": len(commit_times),
        "burstiness": round(burstiness, 4),
        "mean_gap_h": round(mu, 2),
        "max_gap_h": round(max(gaps_h), 2),
    }
