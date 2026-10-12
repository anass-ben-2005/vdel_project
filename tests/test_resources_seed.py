"""The committed resources CSV (config/resources.csv) stays valid whatever is edited later.

No network, no database: this runs the loader's own validation (`scripts.load_resources.validate`)
on the committed file and adds the rules that belong to the curated list rather than to the
format. Whether a URL still answers is NOT tested here (that needs the network); the author
re-checks links by hand (docs/resources_review.md says when and how they were checked).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import pytest

from config import concepts as taxonomy
from scripts.load_resources import COLUMNS, read_rows, validate

REPO = Path(__file__).resolve().parent.parent
CSV = REPO / "config" / "resources.csv"
MIN_PER_TIER1 = 2


@pytest.fixture(scope="module")
def rows():
    parsed, errors = validate(read_rows(CSV))
    assert errors == [], "the committed CSV fails the loader's validation:\n" + "\n".join(errors)
    return parsed


def tier1_concepts() -> set[str]:
    """Concepts that at least one gap of the curriculum uses: what students are graded on."""
    found: set[str] = set()
    for source in (REPO / "curriculum" / "master").rglob("*.py"):
        for match in re.finditer(r"@gap:id=\S+\s+concepts=\[([^\]]*)\]",
                                 source.read_text(encoding="utf-8")):
            found.update(c.strip() for c in match.group(1).split(",") if c.strip())
    return found


def test_the_header_is_exactly_the_loaders_columns():
    first = CSV.read_text(encoding="utf-8-sig").splitlines()[0]
    assert first.split(",") == list(COLUMNS)


def test_the_file_passes_the_loaders_validation(rows):
    assert rows, "the CSV has no rows"


def test_no_template_example_row_is_left(rows):
    assert [r.resource_id for r in rows if r.is_example] == []
    text = CSV.read_text(encoding="utf-8")
    assert "example.invalid" not in text and "EXAMPLE" not in text


def test_every_concept_id_exists_in_the_taxonomy(rows):
    known = taxonomy.ids()
    assert {c for r in rows for c in r.concept_ids} <= known


def test_every_url_is_https_and_present(rows):
    for r in rows:
        assert r.url is not None, f"{r.resource_id} has no url"
        assert urlparse(r.url).scheme == "https", f"{r.resource_id}: {r.url}"


def test_no_duplicate_id_or_url(rows):
    ids = Counter(r.resource_id for r in rows)
    urls = Counter(r.url for r in rows)
    assert [i for i, n in ids.items() if n > 1] == []
    assert [u for u, n in urls.items() if n > 1] == []


def test_every_row_has_a_kind_a_level_and_a_locator(rows):
    for r in rows:
        assert r.kind and r.level and r.locator, f"{r.resource_id} is incomplete"


def test_every_tier_1_concept_has_at_least_two_resources(rows):
    tier1 = tier1_concepts()
    assert tier1, "no @gap marker found under curriculum/master: the test has lost its input"
    assert tier1 <= taxonomy.ids()
    counts = Counter(c for r in rows for c in r.concept_ids)
    short = {c: counts[c] for c in sorted(tier1) if counts[c] < MIN_PER_TIER1}
    assert short == {}, f"tier 1 concepts with fewer than {MIN_PER_TIER1} resources: {short}"


def test_the_tier_1_concepts_are_offered_more_than_one_level(rows):
    levels: dict[str, set[str]] = {}
    for r in rows:
        for c in r.concept_ids:
            levels.setdefault(c, set()).add(r.level)
    one_level = [c for c in sorted(tier1_concepts()) if len(levels.get(c, set())) < 2]
    assert one_level == []
