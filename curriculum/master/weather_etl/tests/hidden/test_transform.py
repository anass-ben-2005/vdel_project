import pytest
from weather_etl.transform import clean_readings, to_fahrenheit, enrich_with_timestamp


@pytest.mark.gap("g_tf_clean")
def test_clean_readings_drops_null_temp():
    records = [{"temp": 20}, {"temp": None}, {"temp": 15}]
    assert clean_readings(records) == [{"temp": 20}, {"temp": 15}]


@pytest.mark.gap("g_tf_convert")
def test_to_fahrenheit_known_values():
    assert to_fahrenheit(0) == 32
    assert to_fahrenheit(100) == 212


@pytest.mark.gap("g_tf_timestamp")
def test_enrich_with_timestamp_malformed_input():
    record = {"temp": 20}
    result = enrich_with_timestamp(record, "not-a-date")
    assert "timestamp" in result


@pytest.mark.gap("g_tf_timestamp")
def test_enrich_with_timestamp_none_input():
    record = {"temp": 20}
    result = enrich_with_timestamp(record, None)
    assert "timestamp" in result


@pytest.mark.gap("g_tf_timestamp")
def test_enrich_with_timestamp_valid_iso():
    record = {"temp": 20}
    result = enrich_with_timestamp(record, "2024-01-01T00:00:00+00:00")
    assert result["timestamp"].startswith("2024-01-01")