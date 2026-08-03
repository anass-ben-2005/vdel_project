"""Load and validate the concept taxonomy.

BUILD_PLAN 1.1: "A loader that validates it and fails loudly on an unknown prerequisite
id." Loudly is the operative word -- a typo in a prerequisite is a silent broken edge in
the graph Hanafi's knowledge model will later depend on, and silence is how it survives
to production.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

TAXONOMY_PATH = Path(__file__).resolve().parent / "concepts.yaml"

# CLAUDE.md section 8: "Kept under 30 so each accumulates enough observations for a
# reliable estimate." Enforced rather than trusted -- taxonomies grow by accident.
MAX_CONCEPTS = 30


class TaxonomyError(ValueError):
    """The taxonomy is malformed. Never recoverable at runtime -- fix the YAML."""


@dataclass(frozen=True)
class Concept:
    id: str
    name: str
    typical_evidence: str
    difficulty: float
    prerequisites: tuple[str, ...]


@lru_cache(maxsize=1)
def load() -> dict[str, Concept]:
    """Parse, validate and cache the taxonomy."""
    raw = yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))
    entries = (raw or {}).get("concepts") or []
    if not entries:
        raise TaxonomyError(f"{TAXONOMY_PATH} defines no concepts")

    concepts: dict[str, Concept] = {}
    for entry in entries:
        cid = entry.get("id")
        if not cid:
            raise TaxonomyError(f"concept without an id: {entry!r}")
        if cid in concepts:
            raise TaxonomyError(f"duplicate concept id: {cid}")

        difficulty = entry.get("difficulty")
        if not isinstance(difficulty, (int, float)) or not 0 <= difficulty <= 1:
            raise TaxonomyError(f"{cid}: difficulty must be a number in [0, 1], got {difficulty!r}")

        concepts[cid] = Concept(
            id=cid,
            name=entry.get("name", cid),
            typical_evidence=entry.get("typical_evidence", ""),
            difficulty=float(difficulty),
            prerequisites=tuple(entry.get("prerequisites") or ()),
        )

    for concept in concepts.values():
        for prereq in concept.prerequisites:
            if prereq not in concepts:
                raise TaxonomyError(f"{concept.id}: unknown prerequisite {prereq!r}")
            if prereq == concept.id:
                raise TaxonomyError(f"{concept.id}: lists itself as a prerequisite")

    if len(concepts) > MAX_CONCEPTS:
        raise TaxonomyError(
            f"{len(concepts)} concepts exceeds the cap of {MAX_CONCEPTS}. Each concept "
            "needs enough observations to estimate; more concepts means thinner evidence."
        )

    return concepts


def get(concept_id: str) -> Concept:
    concepts = load()
    if concept_id not in concepts:
        raise TaxonomyError(f"unknown concept: {concept_id}")
    return concepts[concept_id]


def ids() -> set[str]:
    return set(load())
