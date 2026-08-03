"""V5 -- Error response: what the student does after a failure.

The boundary that must stay clear (CLAUDE.md section 8): error *frequency* is how often
errors happen, a rate. Error *response* is what the student does about them, a
behaviour. A student who fails often and recovers fast is experimenting, not drowning --
and the two variables have to be able to say so separately.

Reference: Jadud (2006) on the compile-error behaviour of novices; Beck & Gong (2013) on
wheel-spinning, defined as continued practice without reaching mastery.
"""

from __future__ import annotations

from datetime import UTC, datetime

from variables import clamp01

# Beck & Gong (2013) treat a student as wheel-spinning if they have not mastered a skill
# within roughly ten practice opportunities. Applied here per concept.
WHEEL_SPIN_THRESHOLD = 10


def _utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def error_response(runs: list[tuple[datetime, bool, str | None]]) -> dict:
    """V5 from an ordered attempt history.

    Args:
        runs: (timestamp, passed, concept_id) for every workflow run, any order.

    Recovery rate is the fraction of failures followed by a pass -- the direct
    measurement of "did they fix it". Median time-to-recovery says how fast.

    The previous version computed the score from an empty state while reporting counts
    from a different query, so the number shown and the number scored were unrelated.
    Everything here comes from the one `runs` list.
    """
    if not runs:
        return {"score": None, "n": 0}

    ordered = sorted(((_utc(ts), ok, cid) for ts, ok, cid in runs), key=lambda r: r[0])
    failures = [r for r in ordered if not r[1]]

    if not failures:
        return {"score": None, "n": 0, "reason": "no failures to respond to"}

    recovered = 0
    recovery_hours: list[float] = []
    for ts, _, _ in failures:
        nxt = next((t for t, ok, _ in ordered if ok and t > ts), None)
        if nxt:
            recovered += 1
            recovery_hours.append((nxt - ts).total_seconds() / 3600)

    recovery_rate = recovered / len(failures)

    # Wheel-spinning: many attempts on one concept, still no pass.
    by_concept: dict[str, list[bool]] = {}
    for _, ok, cid in ordered:
        if cid:
            by_concept.setdefault(cid, []).append(ok)
    spinning = sorted(
        c
        for c, outcomes in by_concept.items()
        if len(outcomes) >= WHEEL_SPIN_THRESHOLD and not any(outcomes)
    )

    median_recovery = (
        round(sorted(recovery_hours)[len(recovery_hours) // 2], 2) if recovery_hours else None
    )

    return {
        # Recovery rate is the score. Speed is reported alongside rather than blended in,
        # because "fixed it slowly" and "never fixed it" are different situations and
        # averaging them into one number hides which one a student is in.
        "score": round(clamp01(recovery_rate), 4),
        "n": len(failures),
        "recovered": recovered,
        "recovery_rate": round(recovery_rate, 4),
        "median_recovery_h": median_recovery,
        "wheel_spinning_concepts": spinning,
    }
