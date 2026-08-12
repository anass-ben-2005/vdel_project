"""benchmark/submissions/inefficient.py — archetype: correct but inefficient (BUILD_PLAN 3.2).

Same numbers as clean.py -- correct grain, correct totals -- so a judge that only checks
outputs should score this identically to clean.py on Correctness. It should not, on
Approach & Idiomatic Spark: every anti-pattern below is planted deliberately and named
here so a later recall measurement (M5) can check whether a judge actually spots each one,
rather than issuing a vague "not idiomatic" without evidence.

  1. `.collect()` pulls the entire `orders` table to the driver -- the cluster does no
     aggregation work at all.
  2. The aggregation itself runs in a plain Python dict, one row at a time, off-engine.
  3. The group key is a string built by concatenation instead of a structured column.
  4. The result is rebuilt as a Python list and re-wrapped in `createDataFrame` -- the
     driver, not Spark, produces the final table.
"""

from pyspark.sql import DataFrame, SparkSession


def compute_monthly_revenue(orders: DataFrame) -> DataFrame:
    spark = SparkSession.getActiveSession()
    rows = orders.collect()  # anti-pattern 1: whole dataset shipped to the driver

    totals: dict[str, float] = {}
    order_ids_seen: dict[str, set[str]] = {}
    for row in rows:  # anti-pattern 2: aggregation done off-engine, row by row
        month = str(row["order_date"])[:7]
        key = row["customer_id"] + "|" + month  # anti-pattern 3: string-concat group key
        totals[key] = totals.get(key, 0.0) + row["quantity"] * row["unit_price"]
        order_ids_seen.setdefault(key, set()).add(row["order_id"])

    result_rows = []
    for key, total_revenue in totals.items():
        customer_id, month = key.split("|")
        result_rows.append((customer_id, month, total_revenue, len(order_ids_seen[key])))

    return spark.createDataFrame(  # anti-pattern 4: driver-built table, not a Spark result
        result_rows, ["customer_id", "month", "total_revenue", "order_count"]
    ).orderBy("customer_id", "month")
