"""benchmark/submissions/copy_paste.py — archetype: copy-paste-looking (BUILD_PLAN 3.2).

Numerically correct -- same grain and totals as clean.py -- but reads like several
StackOverflow answers stitched together rather than written for this task: a needless
class wrapper around a pure transformation, a dead import, a wildcard import, and naming
that switches convention mid-file (`AddMonthColumn` next to `add_revenue_col`). None of
this changes the answer; all of it is what the Readability rubric row exists to catch.
`import pandas` and the wildcard import are real ruff findings (F401, F403) -- genuine
tool-stage evidence, not just an LLM's opinion of the style.
"""

import pandas as pd  # unused -- a copy-paste tell (F401)
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import *  # a copy-paste tell (F403) -- nothing here needs it


class RevenueCalculator:
    """Needless class wrapper around what clean.py does as one pure function."""

    def __init__(self, df):
        self.df = df
        self.Result = None  # PascalCase attribute next to snake_case methods below

    def AddMonthColumn(self):  # PascalCase method -- inconsistent with the one below
        self.df = self.df.withColumn("month", F.date_format(self.df.order_date, "yyyy-MM"))
        return self

    def add_revenue_col(self):
        self.df = self.df.withColumn(
            "line_revenue", self.df["quantity"] * self.df["unit_price"]
        )
        return self

    def do_the_groupby_thing(self):
        tmp_df_v2 = self.df.groupBy("customer_id", "month").agg(
            F.sum("line_revenue").alias("total_revenue"),
            F.countDistinct("order_id").alias("order_count"),
        )
        self.Result = tmp_df_v2
        return self


def compute_monthly_revenue(orders: DataFrame) -> DataFrame:
    calc = RevenueCalculator(orders)
    calc.AddMonthColumn().add_revenue_col().do_the_groupby_thing()
    final_result_df_final = calc.Result  # redundant rename -- another copy-paste tell
    return final_result_df_final.orderBy("customer_id", "month")
