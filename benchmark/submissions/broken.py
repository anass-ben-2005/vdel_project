"""benchmark/submissions/broken.py — archetype: broken, doesn't run (BUILD_PLAN 3.2).

Fails at runtime, not at parse time -- `ast.parse` (and ruff, and sqlfluff-style tools in
general) still accept the file as valid Python, so the M4 tool stage can run over it and
report real findings rather than choking on a syntax error. Two independent failures are
planted, so a partial fix doesn't accidentally make it "work":

  1. `orders_df` is referenced but never defined -- the parameter is named `orders`.
     Ruff's default pyflakes rule (F821, undefined name) catches this as a genuine
     tool-stage finding, which is the point: this file exists to test whether a judge
     treats "the tool already told you this is broken" as evidence rather than repeating
     the same conclusion the tool already gave it for free.
  2. Even if (1) were fixed, `.groupby(...)` is pandas' spelling, not PySpark's
     `.groupBy(...)` -- an `AttributeError` at call time that ruff cannot see statically,
     because `orders` is only known to be *a* DataFrame-shaped object, not which one.
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def compute_monthly_revenue(orders: DataFrame) -> DataFrame:
    df = orders_df.withColumn(  # NameError: should be `orders`, the actual parameter
        "month", F.date_format("order_date", "yyyy-MM")
    )
    return df.groupby("customer_id", "month").agg(  # AttributeError: pandas spelling
        F.sum(F.col("quantity") * F.col("unit_price")).alias("total_revenue")
    )
