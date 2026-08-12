"""benchmark/submissions/subtly_wrong.py — archetype: subtly wrong (BUILD_PLAN 3.2).

Looks right: same columns, same aggregation functions, same imports as clean.py, runs
without error. Wrong: `order_id` is left in the `groupBy`, so the true output grain is
one row per (customer_id, order_id, month) -- per *order*, not per month. For a customer
with exactly one order that month this is numerically identical to the correct answer,
which is exactly what makes the bug survive a quick read; for a customer with two or more
orders in the same month, `total_revenue` is a single order's revenue, not the monthly
total, and `order_count` is always 1 instead of the true count. Same root cause surfaces
in both output columns -- two independent pieces of evidence for a judge to quote.
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def compute_monthly_revenue(orders: DataFrame) -> DataFrame:
    return (
        orders.withColumn("month", F.date_format("order_date", "yyyy-MM"))
        .withColumn("line_revenue", F.col("quantity") * F.col("unit_price"))
        .groupBy("customer_id", "order_id", "month")  # order_id doesn't belong in this grain
        .agg(
            F.sum("line_revenue").alias("total_revenue"),
            F.countDistinct("order_id").alias("order_count"),
        )
        .orderBy("customer_id", "month")
    )
