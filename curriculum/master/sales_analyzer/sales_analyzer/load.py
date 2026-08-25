import sqlite3

import pandas as pd


def write_summary(conn: sqlite3.Connection, summary_df: pd.DataFrame) -> int:
    """Write a summary DataFrame to the 'summary' table, replacing any prior contents."""
    # @gap:id=g_ld_write concepts=[sql.select_filter] difficulty=0.3
    # @instruct: Write summary_df to the 'summary' table via to_sql, with
    #            if_exists='replace' and index=False. Return len(summary_df).
    summary_df.to_sql("summary", conn, if_exists="replace", index=False)
    return len(summary_df)
    # @endgap
