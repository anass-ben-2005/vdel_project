"""Visible smoke test for weather_etl/quality.py -- runs STANDALONE, nothing injected.
See tests/visible/test_extract.py for the full rationale (VDEL_REDESIGN.md 8.3).

Only the clean-data pass-through for assert_no_nulls. The raise-on-missing-field case
and assert_reasonable_range entirely are the hidden suite's job (gap_id g_qa_nulls /
g_qa_range).
"""
from weather_etl.quality import assert_no_nulls


def test_assert_no_nulls_accepts_clean_data():
    assert_no_nulls([{"temp": 20, "humidity": 50}], ["temp", "humidity"])
