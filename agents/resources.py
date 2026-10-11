"""agents/resources.py -- the candidate selector. The LLM never invents a resource.

C-redesign A7: a curated `resources` table (20-40 rows keyed by concept) "kills URL
hallucination; replaces RAG". The Feedback Agent is shown a SMALL, CLOSED list of rows and may
pick one `resource_id` from it or none; the title / locator / url the student sees are copied
from the row, never written by the model.

`select_candidates` is the whole selection policy and it is deterministic: the same table and
the same arguments give the same list in the same order, whatever the row order in the database
(an explicit ORDER BY, the same discipline as `diagnose._weakest_concept`'s tie-break).

  1. rows whose `concept_ids` contain the concept
  2. optionally filtered to the given levels (a row with NO level is kept: it is not known to be
     wrong for the student)
  3. ordered easiest first (beginner, intermediate, advanced, unspecified), then by resource_id
  4. at most `limit` rows

Read-only: one SELECT. The real `resources` table has 0 rows at the time of writing, so this
returns an empty list there and the Feedback Agent then accepts only `resource_id: null`.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# The values below are design choices, not measurements (CLAUDE.md §10): the schema only says
# `kind TEXT -- book_section | doc_page | kaggle | video` and leaves `level` unspecified.
KINDS = ("book_section", "doc_page", "kaggle", "video")
LEVELS = ("beginner", "intermediate", "advanced")
DEFAULT_LIMIT = 5


@dataclass(frozen=True)
class ResourceCandidate:
    resource_id: str
    title: str
    kind: str | None = None
    level: str | None = None
    concept_ids: tuple[str, ...] = ()
    locator: str | None = None
    url: str | None = None


def select_candidates(cur, concept_id: str, *, levels: Sequence[str] | None = None,
                      limit: int = DEFAULT_LIMIT) -> list[ResourceCandidate]:
    if limit < 0:
        raise ValueError("limit must be >= 0")
    unknown = set(levels or ()) - set(LEVELS)
    if unknown:
        raise ValueError(f"unknown level(s) {sorted(unknown)}; allowed: {list(LEVELS)}")

    args: list = [concept_id]
    level_filter = ""
    if levels:
        level_filter = " AND (level IS NULL OR level = ANY(%s))"
        args.append(list(levels))
    args.append(limit)
    cur.execute(
        "SELECT resource_id, title, kind, level, concept_ids, locator, url FROM resources"
        " WHERE %s = ANY(concept_ids)" + level_filter +
        " ORDER BY CASE level WHEN 'beginner' THEN 0 WHEN 'intermediate' THEN 1"
        " WHEN 'advanced' THEN 2 ELSE 3 END, resource_id LIMIT %s",
        args)
    return [ResourceCandidate(rid, title, kind, level, tuple(cids or ()), locator, url)
            for rid, title, kind, level, cids, locator, url in cur.fetchall()]
