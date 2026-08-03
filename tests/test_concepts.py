"""Taxonomy loader tests. BUILD_PLAN 1.1: fail loudly on an unknown prerequisite."""

from __future__ import annotations

import pytest
import yaml

from config import concepts
from config.concepts import TaxonomyError


def write_taxonomy(tmp_path, monkeypatch, data):
    path = tmp_path / "concepts.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(concepts, "TAXONOMY_PATH", path)
    concepts.load.cache_clear()
    return path


def test_real_taxonomy_loads():
    loaded = concepts.load()
    assert loaded
    assert all(0 <= c.difficulty <= 1 for c in loaded.values())


def test_real_taxonomy_stays_under_the_cap():
    """CLAUDE.md section 8 keeps this under 30 so each concept accumulates enough
    observations to estimate. Taxonomies grow by accident, so it is checked."""
    assert len(concepts.load()) <= concepts.MAX_CONCEPTS


def test_unknown_prerequisite_fails_loudly(tmp_path, monkeypatch):
    write_taxonomy(tmp_path, monkeypatch, {
        "concepts": [
            {"id": "sql.joins", "name": "Joins", "difficulty": 0.5,
             "prerequisites": ["sql.slect"]},  # typo
        ]
    })
    with pytest.raises(TaxonomyError, match="unknown prerequisite"):
        concepts.load()
    concepts.load.cache_clear()


def test_duplicate_id_is_rejected(tmp_path, monkeypatch):
    write_taxonomy(tmp_path, monkeypatch, {
        "concepts": [
            {"id": "a", "name": "A", "difficulty": 0.1},
            {"id": "a", "name": "A again", "difficulty": 0.2},
        ]
    })
    with pytest.raises(TaxonomyError, match="duplicate"):
        concepts.load()
    concepts.load.cache_clear()


def test_difficulty_outside_the_unit_interval_is_rejected(tmp_path, monkeypatch):
    write_taxonomy(tmp_path, monkeypatch, {
        "concepts": [{"id": "a", "name": "A", "difficulty": 7}]
    })
    with pytest.raises(TaxonomyError, match="difficulty"):
        concepts.load()
    concepts.load.cache_clear()


def test_self_prerequisite_is_rejected(tmp_path, monkeypatch):
    write_taxonomy(tmp_path, monkeypatch, {
        "concepts": [{"id": "a", "name": "A", "difficulty": 0.1, "prerequisites": ["a"]}]
    })
    with pytest.raises(TaxonomyError, match="itself"):
        concepts.load()
    concepts.load.cache_clear()
