"""agents/trace_compat.py -- read verdict payloads written before and after prompt v2.

Traces are append-only (invariant 1): payloads written by prompt v1 keep the score key
`correctness`; payloads written by prompt v2 use `llm_correctness_opinion` (the model's reading of
the code, not a test result, D-036). Any reader inside `agents/` goes through these helpers so it
accepts both. They never write, never touch the database, and never turn an opinion into a result.

Readers OUTSIDE `agents/` (not editable on this branch) are listed in `docs/agents.md`,
"Integration requests".
"""
from __future__ import annotations

from typing import Any

NEW_KEY = "llm_correctness_opinion"
OLD_KEY = "correctness"


def correctness_opinion(scores: Any) -> int | None:
    """The model's correctness opinion from a `scores` dict, a `Scores` model, or a whole verdict
    payload (a dict with a `scores` entry). Accepts the old and the new key; the new key wins if
    both are present. None if neither is."""
    if scores is None:
        return None
    if isinstance(scores, dict) and "scores" in scores:
        return correctness_opinion(scores["scores"])
    if isinstance(scores, dict):
        for key in (NEW_KEY, OLD_KEY):
            if scores.get(key) is not None:
                return int(scores[key])
        return None
    for key in (NEW_KEY, OLD_KEY):
        value = getattr(scores, key, None)
        if value is not None:
            return int(value)
    return None


def normalise_payload(payload: dict) -> dict:
    """A copy of a verdict payload with `scores` using the NEW key only. The stored payload is
    not modified (it is evidence); this is for display and comparison."""
    out = dict(payload)
    scores = dict(out.get("scores") or {})
    opinion = correctness_opinion(scores)
    if opinion is not None:
        scores.pop(OLD_KEY, None)
        scores[NEW_KEY] = opinion
    out["scores"] = scores
    return out
