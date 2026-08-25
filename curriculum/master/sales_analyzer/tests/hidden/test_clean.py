import pandas as pd
import pytest
from sales_analyzer.clean import drop_duplicate_orders, fill_missing_region


@pytest.mark.gap("g_cl_dedupe")
def test_drop_duplicate_orders_keeps_the_latest_by_order_date():
    df = pd.DataFrame({
        "order_id": ["ORD-001", "ORD-001", "ORD-002"],
        "order_date": pd.to_datetime(["2024-01-01", "2024-03-01", "2024-02-01"]),
        "region": ["West", "West", "East"],
    })
    result = drop_duplicate_orders(df)
    assert len(result) == 2
    kept = result[result["order_id"] == "ORD-001"].iloc[0]
    assert kept["order_date"] == pd.Timestamp("2024-03-01")


@pytest.mark.gap("g_cl_dedupe")
def test_drop_duplicate_orders_is_a_noop_with_no_duplicates():
    df = pd.DataFrame({
        "order_id": ["ORD-001", "ORD-002"],
        "order_date": pd.to_datetime(["2024-01-01", "2024-02-01"]),
        "region": ["West", "East"],
    })
    result = drop_duplicate_orders(df)
    assert len(result) == 2


@pytest.mark.gap("g_cl_fillna")
def test_fill_missing_region_uses_the_default():
    df = pd.DataFrame({"region": ["West", None, "East"]})
    result = fill_missing_region(df, "Unknown")
    assert list(result["region"]) == ["West", "Unknown", "East"]


@pytest.mark.gap("g_cl_fillna")
def test_fill_missing_region_does_not_mutate_the_caller_s_dataframe():
    df = pd.DataFrame({"region": ["West", None]})
    fill_missing_region(df, "Unknown")
    # The original DataFrame must be untouched -- this is exactly what a
    # SettingWithCopyWarning bug would violate.
    assert df["region"].isna().sum() == 1
