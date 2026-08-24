import sqlite3
import pytest
from weather_etl.load import insert_readings, readings_since


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE readings (temp REAL, humidity REAL, wind_speed REAL, timestamp TEXT)")
    yield c
    c.close()


@pytest.mark.gap("g_ld_insert")
def test_insert_readings_returns_count(conn):
    records = [{"temp": 20, "humidity": 50, "wind_speed": 5, "timestamp": "2024-01-01"}]
    assert insert_readings(conn, records) == 1


@pytest.mark.gap("g_ld_select")
def test_readings_since_filters_correctly(conn):
    conn.executemany(
        "INSERT INTO readings VALUES (:temp,:humidity,:wind_speed,:timestamp)",
        [
            {"temp": 10, "humidity": 40, "wind_speed": 3, "timestamp": "2024-01-01"},
            {"temp": 20, "humidity": 50, "wind_speed": 5, "timestamp": "2024-06-01"},
        ],
    )
    conn.commit()
    result = readings_since(conn, "2024-03-01")
    assert len(result) == 1
    assert result[0]["temp"] == 20