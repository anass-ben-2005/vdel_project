"""The committed resources CSV, loaded into the TEST database and read back by the selector.

Everything runs in one transaction on `vdel_test` (the test conftest points PG_DSN there) that is
rolled back; no LLM is called. It proves that the curated list works with the real selection policy
(agents/resources.py: easiest first) and shows what a student would read.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from agents.feedback_agent import FeedbackInput, FeedbackOutput, render_markdown
from agents.feedback_prompts import _candidate_lines
from agents.resources import DEFAULT_LIMIT, select_candidates
from config import concepts as taxonomy
from scripts.load_resources import apply_rows, read_rows, validate
from system import db

pytestmark = pytest.mark.skipif(not os.environ.get("PG_DSN"),
                                reason="PG_DSN not set; integration test needs a database")

CSV = Path(__file__).resolve().parent.parent / "config" / "resources.csv"
LEVEL_RANK = {"beginner": 0, "intermediate": 1, "advanced": 2}


@pytest.fixture
def loaded():
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = conn.cursor()
    cur.execute("DELETE FROM resources")          # this transaction only: rolled back below
    rows, errors = validate(read_rows(CSV))
    assert errors == []
    apply_rows(cur, rows)
    yield cur, rows
    conn.rollback()
    conn.close()


def test_every_concept_with_a_row_gets_candidates_easiest_first(loaded):
    cur, rows = loaded
    covered = {c for r in rows for c in r.concept_ids}
    for concept in sorted(covered):
        got = select_candidates(cur, concept)
        print(f"{concept}: " + ", ".join(f"{c.resource_id} [{c.level}]" for c in got))
        assert got, concept
        assert len(got) <= DEFAULT_LIMIT
        ranks = [LEVEL_RANK[c.level] for c in got]
        assert ranks == sorted(ranks), f"{concept}: not easiest first: {[c.level for c in got]}"
        assert all(concept in c.concept_ids for c in got)


def test_a_concept_without_a_row_returns_an_empty_list(loaded):
    cur, rows = loaded
    uncovered = sorted(taxonomy.ids() - {c for r in rows for c in r.concept_ids})
    for concept in uncovered:
        assert select_candidates(cur, concept) == []


def test_the_student_reads_title_locator_and_url_from_the_row(loaded, capsys):
    """No LLM: a fixed output stands in for the model, and the real renderer builds the note."""
    cur, _ = loaded
    candidates = tuple(select_candidates(cur, "py.errors_debugging"))
    chosen = candidates[0]
    inp = FeedbackInput(
        attempt_id=1, commit_sha="abcdef1234567", student_id="s",
        assignment_id="weather_etl_extract", project_id="weather_etl", attempt_no=1,
        status="ok", passed=3, total=4, failed=(), diagnosis_failing=(),
        weakest_concept="py.errors_debugging", recurring_gaps=(),
        concepts=("py.errors_debugging",), candidates=candidates)
    out = FeedbackOutput(summary="One check is still failing.",
                         what_to_check_next=["Re-read the error."],
                         resource_id=chosen.resource_id, confidence="high")
    note = render_markdown(inp, out)
    with capsys.disabled():
        print("\n--- candidates as the prompt lists them ---\n" + _candidate_lines(candidates))
        print("\n--- what the student reads ---\n" + note)
    assert f"Suggested reading: **{chosen.title}**, {chosen.locator}. {chosen.url}" in note
