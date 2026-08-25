"""Visible smoke test for sales_analyzer/load.py -- runs STANDALONE, nothing injected.
See weather_etl/tests/visible/test_extract.py for the full rationale (VDEL_REDESIGN.md
8.3). Only the row-count return value. The replace-on-rewrite behaviour is the hidden
suite's job (gap_id g_ld_write).
"""
import sqlite3

import pandas as pd
from sales_analyzer.load import write_summary


def test_write_summary_returns_the_row_count():
    conn = sqlite3.connect(":memory:")
    df = pd.DataFrame({"region": ["West"], "revenue": [20.0]})
    assert write_summary(conn, df) == 1
    conn.close()
