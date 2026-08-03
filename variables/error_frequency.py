"""V6 -- Error frequency: how often errors happen, normalised by opportunity.

"Opportunity-normalised" means the denominator is attempts, not calendar time. Ten
failures across two hundred runs is not the same as ten across twelve, and a per-day
rate would call them equal for a student who simply works more.

Pairs with V5 (error_response). High frequency plus fast recovery reads as learning by
experimentation; high frequency plus no recovery reads as being stuck. Neither variable
can distinguish those alone, which is exactly why they are two variables.
"""

from __future__ import annotations

from variables import clamp01


def error_frequency(attempts: int, failures: int) -> dict:
    """V6 from raw attempt counts.

    No confidence shrinkage is applied. The previous version pulled the score towards
    0.5 by a sqrt(n)/sqrt(20) factor, which quietly mixes "how often do errors happen"
    with "how sure are we" -- two things invariant 8 keeps separate by shipping `n`
    alongside every estimate and letting the consumer weigh it.
    """
    if attempts <= 0:
        return {"score": None, "n": 0}

    failures = max(0, min(failures, attempts))
    rate = failures / attempts

    return {
        "score": round(clamp01(1 - rate), 4),
        "n": attempts,
        "failures": failures,
        "failure_rate": round(rate, 4),
    }
