"""Visible smoke test for sales_analyzer/clean.py -- runs STANDALONE, nothing injected.
See weather_etl/tests/visible/test_extract.py for the full rationale (VDEL_REDESIGN.md
8.3). Only fill_missing_region's clean-data pass-through. The keep-latest dedupe logic
and the actual missing-value fill are the hidden suite's job (gap_id g_cl_dedupe /
g_cl_fillna).
"""
import pandas as pd
from sales_analyzer.clean import fill_missing_region


def test_fill_missing_region_leaves_clean_data_unchanged():
    df = pd.DataFrame({"region": ["West", "East"]})
    result = fill_missing_region(df, "Unknown")
    assert list(result["region"]) == ["West", "East"]
