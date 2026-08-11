"""The schema columns that are load-bearing for a recorded decision actually exist.

`session_digest` and `sessions.summary` were declared in VDEL_Modules_3_9_Build.md B.4,
read in B.5 and written in B.6, and were still missing from sql/05 (DECISIONS.md D-008).
A missing table fails loudly on the next query; a missing column fails only when the one
code path that reads it finally runs -- which is precisely why that gap survived. These
tests are the loud failure.

Skips when no database is reachable, matching test_pipeline_integration.py, so `pytest`
still runs on a laptop with nothing started.
"""
import os

import pytest

from scripts import smoke_test
from system import db

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; schema test needs a database"
)


@pytest.fixture
def cur():
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    try:
        with conn.cursor() as c:
            yield c
    finally:
        conn.rollback()
        conn.close()


def test_decision_bearing_columns_present(cur):
    assert smoke_test.check_columns(cur) == []


def test_check_columns_detects_a_missing_column(cur, monkeypatch):
    """The negative control. A check that cannot fail proves nothing."""
    monkeypatch.setattr(
        smoke_test, "EXPECTED_COLUMNS", {"learner_profile": ["_does_not_exist"]}
    )
    assert smoke_test.check_columns(cur) == [
        "missing column: learner_profile._does_not_exist"
    ]


@pytest.mark.parametrize(
    "table, column, data_type, is_nullable, has_default",
    [
        # B.4: session_digest JSONB NOT NULL DEFAULT '[]'
        ("learner_profile", "session_digest", "jsonb", "NO", True),
        # B.4: summary TEXT -- NULL until the compression job fills it
        ("sessions", "summary", "text", "YES", False),
    ],
)
def test_column_shape_matches_the_module_document(
    cur, table, column, data_type, is_nullable, has_default
):
    """Presence is not enough: a nullable session_digest would break get_profile's
    contract that the key is always an array."""
    cur.execute(
        "SELECT data_type, is_nullable, column_default IS NOT NULL"
        " FROM information_schema.columns"
        " WHERE table_schema = 'public' AND table_name = %s AND column_name = %s",
        (table, column),
    )
    row = cur.fetchone()
    assert row is not None, f"{table}.{column} does not exist"
    assert row == (data_type, is_nullable, has_default)
