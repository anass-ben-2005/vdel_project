"""Visible smoke test for sales_analyzer/aggregate.py -- runs STANDALONE, nothing
injected. See weather_etl/tests/visible/test_extract.py for the full rationale
(VDEL_REDESIGN.md 8.3). Only a trivial single-region revenue_by_region case.
top_products entirely, and revenue_by_region's multi-region grouping, are the hidden
suite's job (gap_id g_ag_revenue / g_ag_top).
"""
import pandas as pd
from sales_analyzer.aggregate import revenue_by_region


def test_revenue_by_region_single_region():
    df = pd.DataFrame({"region": ["West"], "quantity": [2], "unit_price": [10.0]})
    result = revenue_by_region(df)
    assert result.iloc[0]["revenue"] == 20.0
