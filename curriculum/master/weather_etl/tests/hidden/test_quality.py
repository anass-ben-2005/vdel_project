import pytest
from weather_etl.quality import assert_no_nulls, assert_reasonable_range


@pytest.mark.gap("g_qa_nulls")
def test_assert_no_nulls_passes_on_clean_data():
    assert_no_nulls([{"temp": 20, "humidity": 50}], ["temp", "humidity"])


@pytest.mark.gap("g_qa_nulls")
def test_assert_no_nulls_raises_on_missing_field():
    with pytest.raises(AssertionError):
        assert_no_nulls([{"temp": None}], ["temp"])


@pytest.mark.gap("g_qa_range")
def test_assert_reasonable_range_passes():
    assert_reasonable_range([{"temp": 20}], "temp", -10, 50)


@pytest.mark.gap("g_qa_range")
def test_assert_reasonable_range_raises_out_of_bounds():
    with pytest.raises(AssertionError):
        assert_reasonable_range([{"temp": 200}], "temp", -10, 50)