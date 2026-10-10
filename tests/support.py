"""Helpers for database tests: make the rows a test needs instead of borrowing a real one.

Until D-064 a few tests did `SELECT variant_id FROM variants WHERE assignment_id = ...` and
used whatever came back. That row existed only because a REAL student's repo had been
rendered in the shared dev database, so the test silently depended on real student data and
failed on any clean database. `ensure_variant` builds the variant from the SEEDED curriculum
(structure, not student data) with the same id function and upsert the renderer uses.
"""

from __future__ import annotations

from assessment.gap_generator import _compute_variant_id
from scripts.render_student_repo import _upsert_variant


def ensure_variant(cur, assignment_id: str) -> str:
    """The variant covering ALL of `assignment_id`'s seeded gaps; created if absent."""
    cur.execute("SELECT gap_id, master_version FROM gaps WHERE assignment_id = %s"
                " ORDER BY gap_id", (assignment_id,))
    rows = cur.fetchall()
    if not rows:
        raise AssertionError(f"no seeded gaps for {assignment_id!r}: is the curriculum seeded?")
    versions = {master for _, master in rows}
    if len(versions) != 1:
        raise AssertionError(f"{assignment_id!r} has gaps from several master versions")
    (master_version,) = versions
    gap_ids = tuple(gap_id for gap_id, _ in rows)
    variant_id = _compute_variant_id(assignment_id, gap_ids, master_version)
    _upsert_variant(cur, variant_id, assignment_id, gap_ids, master_version)
    return variant_id
