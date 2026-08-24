"""Visible smoke test for weather_etl/transform.py -- runs STANDALONE, nothing injected.
See tests/visible/test_extract.py for the full rationale (VDEL_REDESIGN.md 8.3).

One known value for to_fahrenheit. clean_readings' null-dropping and
enrich_with_timestamp's malformed/None-input handling are the hidden suite's job
(gap_id g_tf_clean / g_tf_timestamp).
"""
from weather_etl.transform import to_fahrenheit


def test_to_fahrenheit_freezing_point():
    assert to_fahrenheit(0) == 32
