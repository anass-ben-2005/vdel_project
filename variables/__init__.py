"""The seven variables.

Every module here exposes one function returning a plain dict shaped:

    {"score": float | None, "n": int, ...detail}

with, per CLAUDE.md section 8:
  * `score` scaled to [0, 1], higher is better -- or None when there is nothing to
    measure. None is not the same as 0.0: 0.0 means "measured, bad"; None means "not
    observed". The previous version collapsed the two by inventing values for unmeasured
    inputs, which wrote fiction into the database.
  * `n`, the observation count. Invariant 8: 0.9 from n=2 is a rumour, from n=20 a fact.

A dict rather than a dataclass because these go straight into a JSONB column, and every
translation layer between the formula and the column is somewhere a bug can hide.
"""

from __future__ import annotations


def clamp01(x: float) -> float:
    """Hold a score inside [0, 1]. The one place the range contract is enforced."""
    return max(0.0, min(1.0, float(x)))
