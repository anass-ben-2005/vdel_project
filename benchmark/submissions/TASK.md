# The M3 benchmark task — monthly revenue per customer

> Read by a human before scoring, and paraphrased into the Code Agent's assembled prompt
> (M4, `agents/prompts.py`) alongside each submission. Not Sara's A2 — a new task, same
> concept (`spark.aggregation`), so the benchmark stays independent of the M1/M2 fixtures
> it will later sit next to on the same blackboard.

## Prompt given to whoever wrote each submission

> You have a PySpark DataFrame `orders` with one row per **order line**:
>
> | column | type | meaning |
> |---|---|---|
> | `order_id` | string | one order can have several lines (several products) |
> | `customer_id` | string | |
> | `order_date` | date | `YYYY-MM-DD` |
> | `product_id` | string | |
> | `quantity` | int | units of `product_id` on this line |
> | `unit_price` | float | price per unit, in this line's currency |
>
> Write `compute_monthly_revenue(orders: DataFrame) -> DataFrame` returning, for every
> customer and every calendar month that customer ordered in:
>
> | column | meaning |
> |---|---|
> | `customer_id` | |
> | `month` | `"YYYY-MM"` |
> | `total_revenue` | sum of `quantity * unit_price` over every line in that customer's orders that month |
> | `order_count` | number of **distinct orders** (not lines) that customer placed that month |
>
> One row per `(customer_id, month)`. Nothing else touches the row count.

## Concept tested

`spark.aggregation` (`config/concepts.yaml`) — grouping and aggregation grain. Prerequisite:
`spark.df_basics`.

## Why this grain is the interesting part

An order has several lines (several `product_id`s), so a naive implementation that forgets
to drop `order_id` after computing per-line revenue silently changes the output's grain from
"one row per customer-month" to "one row per customer-order" — every column still typechecks,
the job still runs, and the numbers look plausible until you check the row count or a
customer with two orders in the same month. That is exactly the class of bug the rubric's
Correctness/Approach rows exist to catch, and exactly the kind of thing a quick glance misses.

## The five submissions

| File | Archetype | Rubric axis it's built to test |
|---|---|---|
| `clean.py` | Correct & idiomatic | The reference — nothing below should outscore it |
| `subtly_wrong.py` | Subtly wrong | Correctness: does the judge check the *grain*, not just that the code runs and the columns are named right? |
| `inefficient.py` | Correct, wrong engine use | Approach & Idiomatic Spark: same numbers as `clean.py`, but `.collect()` + a Python loop does the aggregation off-cluster |
| `copy_paste.py` | Over-engineered / inconsistent | Readability: correct numbers, but a needless class wrapper, mixed naming conventions, a dead import, and a wildcard import |
| `broken.py` | Doesn't run | Correctness floor: fails at runtime (undefined name, then a pandas/PySpark API mix-up), not at parse time — ruff's tool-stage pass over it produces real findings |

Each file exposes the identical entry point, `compute_monthly_revenue(orders) -> DataFrame`,
so `benchmark/run_benchmark.py` (3.3) can call all five the same way.
