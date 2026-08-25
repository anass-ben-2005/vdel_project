import sqlite3

import pandas as pd
import pytest
from sales_analyzer.load import write_summary


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    yield c
    c.close()


@pytest.mark.gap("g_ld_write")
def test_write_summary_returns_row_count(conn):
    df = pd.DataFrame({"region": ["West", "East"], "revenue": [25.0, 6.0]})
    assert write_summary(conn, df) == 2


@pytest.mark.gap("g_ld_write")
def test_write_summary_replaces_prior_contents(conn):
    first = pd.DataFrame({"region": ["West"], "revenue": [1.0]})
    write_summary(conn, first)
    second = pd.DataFrame({"region": ["East"], "revenue": [2.0]})
    write_summary(conn, second)

    rows = conn.execute("SELECT region, revenue FROM summary").fetchall()
    assert rows == [("East", 2.0)]
