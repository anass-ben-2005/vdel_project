"""benchmark/submissions/clean.py — archetype: clean & correct (BUILD_PLAN 3.2).

The reference implementation for TASK.md's task: total revenue and distinct order count
per customer per calendar month. Correct grain -- `order_id` is used only inside
`countDistinct`, never left in the `groupBy` -- and idiomatic: the DataFrame API end to
end, no anti-patterns, no engine-fighting. Nothing else in this directory should
outscore this file on any rubric axis.
"""

from pyspark.sql import DataFrame
from pyspark.sql import functions as F


def compute_monthly_revenue(orders: DataFrame) -> DataFrame:
    """One row per (customer_id, month): total revenue, distinct order count.

    See TASK.md for the input schema and the exact grain this must produce.
    """
    return (
        orders.withColumn("month", F.date_format("order_date", "yyyy-MM"))
        .withColumn("line_revenue", F.col("quantity") * F.col("unit_price"))
        .groupBy("customer_id", "month")
        .agg(
            F.sum("line_revenue").alias("total_revenue"),
            F.countDistinct("order_id").alias("order_count"),
        )
        .orderBy("customer_id", "month")
    )
