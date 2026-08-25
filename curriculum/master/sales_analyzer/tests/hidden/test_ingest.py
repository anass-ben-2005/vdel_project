import pandas as pd
import pytest
from sales_analyzer.ingest import read_sales_csv

CSV_HEADER = "order_id,order_date,region,product,quantity,unit_price\n"


@pytest.mark.gap("g_ing_dtype")
def test_read_sales_csv_parses_order_date_as_a_real_date(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text(
        CSV_HEADER + "ORD-001,2024-01-15,West,Widget A,3,19.99\n",
        encoding="utf-8",
    )
    df = read_sales_csv(str(path))
    assert pd.api.types.is_datetime64_any_dtype(df["order_date"])


@pytest.mark.gap("g_ing_malformed")
def test_read_sales_csv_drops_a_malformed_row_instead_of_crashing(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text(
        CSV_HEADER
        + "ORD-001,2024-01-15,West,Widget A,3,19.99\n"
        + "ORD-002,2024-01-16,East,Widget B,bad_qty,9.99\n"
        + "ORD-003,2024-01-17,East,Widget C,1,29.99\n",
        encoding="utf-8",
    )
    df = read_sales_csv(str(path))
    assert len(df) == 2
    assert "ORD-002" not in set(df["order_id"])


@pytest.mark.gap("g_ing_malformed")
def test_read_sales_csv_drops_a_malformed_price_too(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text(
        CSV_HEADER
        + "ORD-001,2024-01-15,West,Widget A,3,19.99\n"
        + "ORD-002,2024-01-16,East,Widget B,1,not_a_price\n",
        encoding="utf-8",
    )
    df = read_sales_csv(str(path))
    assert len(df) == 1
    assert df.iloc[0]["order_id"] == "ORD-001"
