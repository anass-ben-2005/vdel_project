"""Visible smoke test for sales_analyzer/ingest.py -- runs STANDALONE, nothing injected.
See weather_etl/tests/visible/test_extract.py for the full rationale (VDEL_REDESIGN.md
8.3). Deliberately thin: one well-formed CSV, no malformed rows. Dtype coercion's date
parsing and the malformed-row handling are the hidden suite's job (gap_id g_ing_dtype /
g_ing_malformed).
"""
from sales_analyzer.ingest import read_sales_csv


def test_read_sales_csv_reads_a_well_formed_row(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text(
        "order_id,order_date,region,product,quantity,unit_price\n"
        "ORD-001,2024-01-15,West,Widget A,3,19.99\n",
        encoding="utf-8",
    )
    df = read_sales_csv(str(path))
    assert len(df) == 1
    assert df.iloc[0]["order_id"] == "ORD-001"
