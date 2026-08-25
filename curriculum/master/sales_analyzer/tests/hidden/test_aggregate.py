import pandas as pd
import pytest
from sales_analyzer.aggregate import revenue_by_region, top_products


@pytest.mark.gap("g_ag_revenue")
def test_revenue_by_region_sums_quantity_times_unit_price():
    df = pd.DataFrame({
        "region": ["West", "West", "East"],
        "quantity": [2, 1, 3],
        "unit_price": [10.0, 5.0, 2.0],
    })
    result = revenue_by_region(df).set_index("region")["revenue"]
    assert result["West"] == pytest.approx(25.0)   # 2*10 + 1*5
    assert result["East"] == pytest.approx(6.0)     # 3*2


@pytest.mark.gap("g_ag_revenue")
def test_revenue_by_region_returns_one_row_per_region():
    df = pd.DataFrame({
        "region": ["West", "East", "West"],
        "quantity": [1, 1, 1],
        "unit_price": [1.0, 1.0, 1.0],
    })
    result = revenue_by_region(df)
    assert set(result.columns) == {"region", "revenue"}
    assert len(result) == 2


@pytest.mark.gap("g_ag_top")
def test_top_products_returns_exactly_n_rows_not_n_plus_one():
    df = pd.DataFrame({
        "product": ["A", "B", "C", "D"],
        "quantity": [40, 30, 20, 10],
    })
    result = top_products(df, 2)
    assert len(result) == 2
    assert list(result["product"]) == ["A", "B"]


@pytest.mark.gap("g_ag_top")
def test_top_products_sums_quantity_across_repeated_products():
    # A's two rows (60 + 60 = 120) must outrank B's single row (100) -- only true
    # if quantity is summed per product BEFORE ranking, not ranked row-by-row.
    df = pd.DataFrame({
        "product": ["A", "B", "A"],
        "quantity": [60, 100, 60],
    })
    result = top_products(df, 1)
    assert list(result["product"]) == ["A"]
    assert result.iloc[0]["quantity"] == 120
