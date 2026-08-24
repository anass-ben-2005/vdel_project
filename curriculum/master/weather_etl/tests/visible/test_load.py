"""Visible smoke test for weather_etl/load.py -- runs STANDALONE, nothing injected.
See tests/visible/test_extract.py for the full rationale (VDEL_REDESIGN.md 8.3).

Builds its own in-memory sqlite connection inline, rather than sharing a fixture with
tests/hidden/test_load.py -- true independence means no shared conftest.py either, not
just no shared test_runner.py machinery. readings_since's date filtering is the hidden
suite's job (gap_id g_ld_select).
"""
import sqlite3

from weather_etl.load import insert_readings


def test_insert_readings_returns_row_count():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE readings (temp REAL, humidity REAL, wind_speed REAL, timestamp TEXT)"
    )
    records = [{"temp": 20, "humidity": 50, "wind_speed": 5, "timestamp": "2024-01-01"}]
    assert insert_readings(conn, records) == 1
    conn.close()
