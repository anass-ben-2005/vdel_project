# VDEL — Ten-Project Curriculum Design

### Mapped against the real `config/concepts.yaml` (19 concepts). Nothing here invents a concept ID.

---

## 0. Read this before authoring anything

**Author Project 1 fully. Run it through the real pipeline. Then scale to the other nine.**

Reason, concretely: Project 1 is the one that will surface whether the `@gap:` marker
convention actually survives contact with real multi-function files, whether
`scope_check`'s line-drift remapping holds on a file with more than one gap, and whether
CI test injection assumes something about file layout that isn't true yet. Every one of
those is a ten-minute fix on one project and a re-authoring job on ten.

**Concept coverage rule carried over from `VDEL_REDESIGN.md` §2.1/§C6:** a concept needs
**≥3 tagged gaps** across the whole curriculum before BKT can produce anything but a
cold-start prior for it. The coverage matrix in §12 is built to satisfy this for every
concept that appears at all — a few of the hardest Spark concepts fall short by design
(see §12 note) and that is flagged, not hidden.

**Difficulty seeds** below are copied from `concepts.yaml` where the gap is a direct
instance of that concept; adjusted slightly (±0.05–0.1) where a gap is an easier or
harder-than-typical instance of it. These are cold-start priors only — `DifficultyEstimator`
supersedes them the moment `n_cohort_obs > 0`, per the yaml's own header comment.

**Concept ID discipline.** If a project genuinely needs a skill not in the 19 (e.g.
"file I/O" or "date parsing" as their own concept), it is tagged `TODO(concept)` in the
design below and mapped to the nearest real concept for now — never silently invented.
See §13 for the short list of these.

---

## 1. The ten projects, at a glance

| # | Project | Tier | Primary area | New concepts introduced |
|---|---|---|---|---|
| 1 | **Weather ETL Pipeline** | Beginner | Python | py.data_structures, py.errors_debugging, py.testing, sql.select_filter |
| 2 | **CSV Sales Analyzer** | Beginner | Python/SQL | py.pandas, sql.aggregation |
| 3 | **E-Commerce Order Reconciliation** | Beginner–Intermediate | SQL/Python | sql.joins |
| 4 | **Library Catalog Cleaning** | Intermediate | Python/SQL | *(reinforcement only — no new concepts)* |
| 5 | **Web Server Log Analytics** | Intermediate | PySpark | spark.df_basics, spark.read, spark.transform_action |
| 6 | **Retail Transaction Aggregation** | Intermediate | PySpark | spark.aggregation, spark.joins |
| 7 | **Ride-Sharing Trip Analysis** | Advanced | PySpark | spark.window, spark.udf |
| 8 | **Social Media Engagement Pipeline** | Advanced | PySpark | *(reinforcement — window/udf/aggregation)* |
| 9 | **IoT Sensor Stream Aggregation** | Advanced | PySpark | spark.partitioning, spark.caching, spark.perf_tuning |
| 10 | **Daily Pipeline Orchestration** | Capstone | Airflow | airflow.operators, airflow.idempotency |

This is a genuine progression, not ten unrelated repos: 1–4 build Python/SQL fluency,
5–6 introduce Spark on the same ETL shape students already know, 7–9 push into Spark's
harder corners, and 10 wraps an *existing* pipeline (reuse Project 5's DAG) in
orchestration — teaching operator design and idempotency without re-teaching ETL logic
the student has already demonstrated.

---

## 2. Project 1 — Weather ETL Pipeline *(author this one first, completely)*

**Framing:** ingest hourly weather observations from a public-style API, clean and
validate them, load into SQLite. This project already exists informally in your repo —
this is its formalization into the gap/concept format.

```
weather_etl/
├── extract.py
├── transform.py
├── load.py
├── quality.py
└── tests/
    ├── visible/   (student-runnable smoke tests)
    └── hidden/    (the correctness oracle)
```

### `extract.py`

| Function | Gap | Concept(s) | Difficulty | Gap type |
|---|---|---|---|---|
| `fetch_weather(url, params)` | `g_ext_retry` — retry loop on transient failure | `py.errors_debugging` | 0.35 | region (3–4 lines) |
| `fetch_weather(url, params)` | `g_ext_request` — the actual HTTP call + timeout | `py.data_structures` *(building the params dict correctly)* | 0.3 | line |
| `parse_response(raw)` | `g_ext_parse` — extract fields from nested JSON safely | `py.data_structures` | 0.35 | region |

**Worked example — the actual annotated master file, to set the pattern every other
project follows:**

```python
import time
import requests

MAX_ATTEMPTS = 3

def fetch_weather(url: str, params: dict) -> dict:
    """Fetch current weather, retrying on transient failure."""
    # @gap:id=g_ext_retry concepts=[py.errors_debugging] difficulty=0.35
    # @instruct: Loop over attempt numbers from 1 to MAX_ATTEMPTS inclusive. On the
    #            final attempt, let the exception propagate instead of retrying.
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            if attempt == MAX_ATTEMPTS:
                raise
            time.sleep(2 ** attempt)
    # @endgap


def parse_response(raw: dict) -> dict:
    """Extract the fields the pipeline actually needs, defensively."""
    # @gap:id=g_ext_parse concepts=[py.data_structures] difficulty=0.35
    # @instruct: Safely extract 'temp', 'humidity', 'wind_speed' from raw['current'].
    #            Missing keys must produce None, not a KeyError.
    current = raw.get("current", {})
    return {
        "temp": current.get("temp"),
        "humidity": current.get("humidity"),
        "wind_speed": current.get("wind_speed"),
    }
    # @endgap
```

*(`g_ext_request` omitted here for brevity — same pattern, one line, tagged
`py.data_structures` for correctly assembling the request `params` dict.)*

### `transform.py`

| Function | Gap | Concept(s) | Difficulty |
|---|---|---|---|
| `clean_readings(records)` | drop/flag records with `None` critical fields | `py.data_structures` | 0.3 |
| `to_fahrenheit(celsius)` | unit conversion — deliberately trivial, a warm-up gap | `py.data_structures` | 0.2 |
| `enrich_with_timestamp(record)` | attach ISO timestamp | `py.errors_debugging` *(handling a malformed input timestamp)* | 0.3 |

### `load.py`

| Function | Gap | Concept(s) | Difficulty |
|---|---|---|---|
| `insert_readings(conn, records)` | parameterised INSERT, executemany | `sql.select_filter` *(schema/column discipline, not a SELECT itself — nearest real concept)* | 0.25 |
| `readings_since(conn, since_ts)` | SELECT with a WHERE clause | `sql.select_filter` | 0.25 |

### `quality.py`

| Function | Gap | Concept(s) | Difficulty |
|---|---|---|---|
| `assert_no_nulls(records, required_fields)` | validation assertion | `py.testing` | 0.4 |
| `assert_reasonable_range(records, field, lo, hi)` | range-check assertion | `py.testing` | 0.45 |

**Hidden tests, per §6.6 of `VDEL_REDESIGN.md` — your master IS the oracle:**

```python
# tests/hidden/test_extract.py
def test_fetch_weather_retries_then_succeeds(monkeypatch): ...
def test_fetch_weather_raises_after_max_attempts(monkeypatch): ...
def test_parse_response_missing_key_returns_none(): ...

# tests/hidden/test_transform.py
def test_clean_readings_drops_null_temp(): ...
def test_to_fahrenheit_known_values(): ...   # 0°C -> 32°F, 100°C -> 212°F
def test_enrich_with_timestamp_malformed_input(): ...
```

**Project 1 concept tally:** py.data_structures ×4, py.errors_debugging ×2, py.testing
×2, sql.select_filter ×2. Nine gaps, four files — matches the "5–9 assignments per
project" range from the meeting.

---

## 3. Project 2 — CSV Sales Analyzer

**Framing:** ingest a messy sales CSV (missing values, inconsistent formatting),
aggregate by region/product, load into SQLite. Reinforces Project 1's structure,
introduces `py.pandas` and `sql.aggregation` as genuinely new material.

```
sales_analyzer/
├── ingest.py       # read + coerce dtypes
├── clean.py        # dedupe, fill/drop nulls
├── aggregate.py    # groupby summaries
└── load.py         # write to SQLite
```

| File | Function | Gap | Concept | Difficulty |
|---|---|---|---|---|
| `ingest.py` | `read_sales_csv(path)` | dtype coercion on read (`dtype=`, `parse_dates=`) | `py.pandas` | 0.4 |
| `ingest.py` | `read_sales_csv(path)` | handling a malformed row without crashing the whole read | `py.errors_debugging` | 0.4 |
| `clean.py` | `drop_duplicate_orders(df)` | dedupe on `order_id`, keep latest | `py.pandas` | 0.45 |
| `clean.py` | `fill_missing_region(df, default)` | `.fillna()` on a specific column, view-vs-copy handled correctly | `py.pandas` | 0.5 *(the classic `SettingWithCopyWarning` trap — matches the yaml's own `typical_evidence` for this concept)* |
| `aggregate.py` | `revenue_by_region(df)` | `groupby().agg()` to the intended grain | `sql.aggregation` *(the SQL concept, tested via pandas — the underlying skill is identical, and reusing the concept ID rather than inventing `pandas.groupby` is deliberate)* | 0.5 |
| `aggregate.py` | `top_products(df, n)` | sort + head, off-by-one on `n` is the common bug | `py.data_structures` | 0.35 |
| `load.py` | `write_summary(conn, summary_df)` | `to_sql` with explicit `if_exists` behaviour | `sql.select_filter` | 0.3 |

**Concept tally:** py.pandas ×3, py.errors_debugging ×1, py.data_structures ×1,
sql.aggregation ×1, sql.select_filter ×1.

---

## 4. Project 3 — E-Commerce Order Reconciliation

**Framing:** reconcile orders against payments across two related tables — the first
project where getting the join wrong silently produces a plausible-looking wrong answer
(duplicated or dropped rows), which is exactly what `sql.joins`'s `typical_evidence`
("no accidental cartesian product") is testing for.

```
order_reconciliation/
├── extract.py      # load orders.csv, payments.csv
├── reconcile.py     # join + discrepancy detection
└── report.py         # summarise mismatches
```

| File | Function | Gap | Concept | Difficulty |
|---|---|---|---|---|
| `extract.py` | `load_orders(path)` / `load_payments(path)` | schema validation on read | `py.errors_debugging` | 0.35 |
| `reconcile.py` | `join_orders_payments(orders, payments)` | join on `order_id`, correct `how=` to avoid silent row loss | `sql.joins` | 0.5 |
| `reconcile.py` | `find_amount_mismatches(joined, tolerance)` | comparison with a float tolerance, not `==` | `py.data_structures` | 0.4 |
| `reconcile.py` | `find_orphan_payments(orders, payments)` | anti-join pattern (payments with no matching order) | `sql.joins` | 0.6 *(harder instance — anti-joins are a common blind spot)* |
| `report.py` | `summarise_by_status(mismatches)` | groupby summary reusing Project 2's pattern | `sql.aggregation` | 0.45 |

**Concept tally:** sql.joins ×2, sql.aggregation ×1, py.errors_debugging ×1,
py.data_structures ×1. This project pushes `sql.joins` over the ≥3 threshold together
with Project 6.

---

## 5. Project 4 — Library Catalog Data Cleaning

**Framing:** deliberately a *reinforcement* project — introduces no new concept IDs.
Its purpose is pure repetition at slightly higher difficulty, which is what lets BKT
actually accumulate the ≥3 observations per concept the whole design depends on. Not
every project in a real curriculum should be novel; some should just be more reps.

```
library_catalog/
├── ingest.py
├── normalize.py    # title casing, ISBN validation
└── dedupe.py        # fuzzy-ish duplicate detection
```

| File | Function | Gap | Concept | Difficulty |
|---|---|---|---|---|
| `ingest.py` | `load_catalog(path)` | malformed-row handling, same skill as Project 2, different shape | `py.errors_debugging` | 0.45 |
| `normalize.py` | `normalize_title(title)` | string cleaning, no pandas needed | `py.data_structures` | 0.3 |
| `normalize.py` | `validate_isbn(isbn)` | checksum validation — a real assertion-writing task | `py.testing` | 0.5 |
| `dedupe.py` | `find_duplicate_titles(df)` | groupby + filter to duplicates | `sql.aggregation` | 0.5 |
| `dedupe.py` | `merge_duplicate_records(df, keep)` | `.fillna()` merge across duplicate rows | `py.pandas` | 0.55 |

**Concept tally:** all five concepts here are their 3rd–5th occurrence across the
curriculum so far — this is the project that actually satisfies the ≥3 rule for
`py.testing` and `py.pandas`.

---

## 6. Project 5 — Web Server Log Analytics *(first Spark project)*

**Framing:** parse raw access logs (Apache combined log format) into a structured
DataFrame, filter and aggregate. First contact with Spark, deliberately reusing the
extract→transform→load shape from Project 1 so the *new* difficulty is Spark's API,
not the pipeline concept itself.

```
log_analytics/
├── extract.py      # read raw log lines
├── parse.py         # regex parse into a Spark DataFrame
├── transform.py     # filter, derive columns
└── aggregate.py      # requests per endpoint per hour
```

| File | Function | Gap | Concept | Difficulty |
|---|---|---|---|---|
| `extract.py` | `read_log_lines(spark, path)` | `spark.read.text(...)`, explicit schema-less read | `spark.read` | 0.35 |
| `parse.py` | `parse_log_line(line)` (used inside a Spark `map`/`withColumn`) | regex extraction into named columns | `spark.df_basics` | 0.4 |
| `transform.py` | `filter_error_responses(df)` | `.filter()` — a **transformation**, not an action | `spark.transform_action` | 0.4 *(the gap's instruction deliberately asks the student to explain, in their commit rationale per D-032's completion-problem framing, why nothing executes yet — testing the lazy-eval concept directly, not just the syntax)* |
| `transform.py` | `add_hour_column(df)` | `withColumn` with a timestamp function | `spark.df_basics` | 0.45 |
| `aggregate.py` | `requests_per_endpoint_hour(df)` | `.groupBy().count()` triggering an action | `spark.aggregation` | 0.55 |

**Concept tally:** spark.read ×1, spark.df_basics ×2, spark.transform_action ×1,
spark.aggregation ×1. Deliberately light on `spark.aggregation` here — Project 6
carries the weight for that concept.

---

## 7. Project 6 — Retail Transaction Aggregation

**Framing:** join a transactions fact table against a small product dimension table,
aggregate revenue by category. The concept-coverage workhorse for `spark.aggregation`
and the second occurrence of `spark.joins` (after Project 3's SQL-flavoured version) —
same underlying skill, different API, which is a genuinely useful contrast for a student
whose profile shows they're strong at SQL joins but new to Spark joins.

```
retail_aggregation/
├── extract.py
├── join.py
├── aggregate.py
└── quality.py
```

| File | Function | Gap | Concept | Difficulty |
|---|---|---|---|---|
| `join.py` | `join_transactions_products(tx, products)` | broadcast-aware join, avoiding an accidental cartesian product on a bad key | `spark.joins` | 0.55 |
| `aggregate.py` | `revenue_by_category(df)` | `groupBy().agg(sum(...))` | `spark.aggregation` | 0.5 |
| `aggregate.py` | `top_categories(df, n)` | `orderBy` + `limit`, action-triggering | `spark.aggregation` | 0.55 |
| `quality.py` | `assert_no_null_revenue(df)` | Spark-side assertion — first Spark instance of `py.testing` | `py.testing` | 0.5 |

**Concept tally:** spark.joins ×1 (2nd overall), spark.aggregation ×2 (3rd/4th
overall — clears the threshold), py.testing ×1 (4th overall).

---

## 8. Project 7 — Ride-Sharing Trip Analysis

**Framing:** first project needing `spark.window` and `spark.udf` — trip duration
ranking per driver, and a UDF for a calculation with no clean built-in (haversine
distance between pickup/dropoff coordinates).

```
ride_share/
├── extract.py
├── enrich.py        # UDF: haversine distance
├── rank.py           # window functions
└── aggregate.py
```

| File | Function | Gap | Concept | Difficulty |
|---|---|---|---|---|
| `enrich.py` | `haversine_udf(lat1, lon1, lat2, lon2)` | the actual distance formula, registered as a UDF | `spark.udf` | 0.6 |
| `enrich.py` | `add_trip_distance(df)` | applying the UDF as a new column — **the instruction explicitly asks why a built-in couldn't do this**, directly testing the yaml's `typical_evidence: "UDFs used only where built-ins cannot serve"` | `spark.udf` | 0.55 |
| `rank.py` | `rank_trips_by_driver(df)` | `Window.partitionBy("driver_id").orderBy(...)` + `row_number()` | `spark.window` | 0.65 |
| `rank.py` | `longest_trip_per_driver(df)` | window frame — first vs. unbounded frame is the common bug | `spark.window` | 0.7 |
| `aggregate.py` | `avg_fare_by_hour(df)` | reinforcement of `spark.aggregation` at higher difficulty | `spark.aggregation` | 0.6 |

**Concept tally:** spark.udf ×2 (first occurrences), spark.window ×2 (first
occurrences), spark.aggregation ×1 (5th overall).

---

## 9. Project 8 — Social Media Engagement Pipeline

**Framing:** deliberately a reinforcement project for `spark.window` and `spark.udf` —
same reasoning as Project 4: the ≥3-observations rule needs a second rep at these harder
concepts, and this is it, at slightly higher difficulty than Project 7.

```
social_engagement/
├── extract.py
├── enrich.py         # UDF: sentiment-score stub (no real ML — a rule-based UDF)
├── rank.py            # trending posts per hour, window function
└── aggregate.py
```

| File | Function | Gap | Concept | Difficulty |
|---|---|---|---|---|
| `enrich.py` | `engagement_score_udf(likes, shares, comments)` | weighted-sum UDF, deliberately harder null-handling than Project 7's | `spark.udf` | 0.65 |
| `rank.py` | `trending_posts_per_hour(df)` | `Window.partitionBy` on a derived hour column (compounding Project 5's `add_hour_column` skill) | `spark.window` | 0.7 |
| `aggregate.py` | `engagement_by_platform(df)` | reinforcement | `spark.aggregation` | 0.55 |

**Concept tally:** spark.udf ×1 (3rd overall — clears threshold), spark.window ×1
(3rd overall — clears threshold), spark.aggregation ×1 (6th overall).

---

## 10. Project 9 — IoT Sensor Stream Aggregation

**Framing:** the hardest Spark project — large-volume sensor readings requiring
deliberate partitioning and caching decisions to avoid OOM/skew, and a performance-tuning
gap that asks the student to justify a choice (broadcast vs. shuffle join) rather than
just fill in code. This is the project that introduces the three hardest concepts in the
taxonomy.

```
iot_sensors/
├── extract.py
├── repartition.py    # spark.partitioning
├── aggregate.py       # spark.caching (reused DataFrame)
└── tune.py            # spark.perf_tuning
```

| File | Function | Gap | Concept | Difficulty |
|---|---|---|---|---|
| `repartition.py` | `repartition_by_sensor(df, n)` | choosing `n` with a stated reason (instruction requires a one-line rationale in the commit, per the meeting's "explain your approach" ask) | `spark.partitioning` | 0.7 |
| `aggregate.py` | `hourly_readings_summary(df)` | `.cache()` before two downstream aggregations, `.unpersist()` after | `spark.caching` | 0.6 |
| `aggregate.py` | `readings_per_sensor(df)` | reinforcement of `spark.aggregation` | `spark.aggregation` | 0.6 |
| `tune.py` | `join_with_sensor_metadata(readings, metadata)` | broadcast join for a small dimension table — the instruction shows `.explain()` output and asks the student to fix the plan | `spark.perf_tuning` | 0.8 |

**Concept tally:** spark.partitioning ×1, spark.caching ×1, spark.perf_tuning ×1 — each
its **only** occurrence in the curriculum. **Flagged in §12: these three do not reach
the ≥3-observation threshold with ten projects at this scope.** See §12 for the
honest handling of this rather than padding gaps artificially to hit a number.

---

## 11. Project 10 — Daily Pipeline Orchestration *(capstone, Airflow)*

**Framing:** wraps **Project 5's log-analytics pipeline** in an Airflow DAG. Deliberately
does *not* re-teach ETL logic — the student has already demonstrated that. This project
tests operator design and idempotency in isolation, which is exactly what makes it a
capstone rather than an eleventh unrelated project.

```
log_pipeline_dag/
├── dag.py             # the DAG definition
└── tasks/
    └── task_wrappers.py   # thin wrappers around Project 5's real functions
```

| File | Function | Gap | Concept | Difficulty |
|---|---|---|---|---|
| `dag.py` | `build_dag()` | task granularity — one operator per pipeline stage, not one giant task | `airflow.operators` | 0.45 |
| `dag.py` | `build_dag()` | dependency wiring (`>>`) matching the real extract→parse→transform→aggregate order | `airflow.operators` | 0.5 |
| `tasks/task_wrappers.py` | `load_hourly_summary_idempotent(conn, summary_df, run_date)` | delete-then-insert (or upsert) keyed on `run_date`, so a re-run produces no duplicates | `airflow.idempotency` | 0.75 |
| `tasks/task_wrappers.py` | `mark_run_complete(conn, run_date)` | guard against double-marking on retry | `airflow.idempotency` | 0.7 |

**Concept tally:** airflow.operators ×2, airflow.idempotency ×2. This is the *only*
project touching Airflow, so both concepts sit at exactly the practical minimum — see
§12.

---

## 12. Full concept coverage matrix

| Concept | Projects | Total gaps | ≥3 threshold met? |
|---|---|---|---|
| py.data_structures | 1, 2, 3, 4 | 6 | ✅ |
| py.errors_debugging | 1, 2, 3, 4 | 5 | ✅ |
| py.testing | 1, 4, 6 | 4 | ✅ |
| py.pandas | 2, 4 | 4 | ✅ |
| sql.select_filter | 1, 2 | 3 | ✅ (exactly at threshold) |
| sql.joins | 3 | 2 | ⚠️ **below threshold** |
| sql.aggregation | 2, 3, 4 | 3 | ✅ (exactly at threshold) |
| spark.read | 5 | 1 | ⚠️ **below threshold** |
| spark.df_basics | 5 | 2 | ⚠️ **below threshold** |
| spark.transform_action | 5 | 1 | ⚠️ **below threshold** |
| spark.aggregation | 5, 6, 7, 8, 9 | 6 | ✅ |
| spark.joins | 3*, 6 | 1 (Spark-native) | ⚠️ **below threshold** |
| spark.window | 7, 8 | 3 | ✅ (exactly at threshold) |
| spark.udf | 7, 8 | 3 | ✅ (exactly at threshold) |
| spark.partitioning | 9 | 1 | ❌ **single occurrence** |
| spark.caching | 9 | 1 | ❌ **single occurrence** |
| spark.perf_tuning | 9 | 1 | ❌ **single occurrence** |
| airflow.operators | 10 | 2 | ⚠️ **below threshold** |
| airflow.idempotency | 10 | 2 | ⚠️ **below threshold** |

*(sql.joins row: Project 3 tests the concept via pandas/SQL semantics but the gap ID
used is `sql.joins`; Project 6's join gap is tagged `spark.joins` — a different, related
concept — so they don't stack toward the same threshold. This is intentional: they are
different skills that happen to rhyme.)*

**The honest read of this table:** the four Python/SQL fundamentals concepts are solidly
covered. Every single-Spark-project concept — `spark.read`, `spark.df_basics`,
`spark.transform_action`, and all three of `spark.partitioning`/`caching`/`perf_tuning`
— falls short of ≥3 because **ten projects is not enough breadth to give every one of 19
concepts three independent occurrences while still keeping each project coherent and
realistically scoped.**

**What to do about it — do not pad gaps to hit a number:**
1. **Accept it for the demo.** Mastery on under-observed concepts stays a cold-start
   prior, correctly labelled — exactly the honest handling `VDEL_REDESIGN.md` §4.3
   already prescribes for n=1 cohorts. This is not a new problem; it's the same one at
   a different layer.
2. **The real fix is more projects in the same tier, not more gaps per project.**
   `spark.perf_tuning` needs its own second and third *project*, not two more gaps
   stuffed into Project 9 — cramming three occurrences of a hard concept into one file
   would violate the "coherent, concept-tagged region" principle this design is
   otherwise built on.
3. **If scope allows only ten projects, prioritise breadth in Python/SQL/core-Spark**
   (already true above) and treat the three advanced Spark concepts and both Airflow
   concepts as **demonstrated but not masterable-with-confidence** in this phase —
   state that limitation directly in the presentation rather than letting an examiner
   discover it.

---

## 13. Concepts used at their nearest-real-ID, flagged per §0

| Design need | Nearest real concept used | Why it's not a perfect fit |
|---|---|---|
| CSV/schema read discipline (Projects 1, 3, 4 `extract.py`) | `py.errors_debugging` | The skill is "read defensively," which is adjacent to but not identical to debugging an existing failure |
| INSERT/parameterised-write discipline (Project 1 `load.py`) | `sql.select_filter` | No `sql.write`/`sql.insert` concept exists in the yaml; `sql.select_filter`'s `typical_evidence` ("correct... rows") is the closest attested match |
| pandas `groupby` (Project 2) | `sql.aggregation` | Deliberate reuse — the underlying skill (grouping to the right grain) is identical whether expressed in SQL or pandas; inventing `pandas.groupby` as a separate concept would fragment one skill into two IDs |

None of these are silent — each is named here so a future session (or your supervisor,
reading this) can decide whether `concepts.yaml` should grow to ~25 with real IDs for
these, closing the gap the yaml's own header comment already names as open.

---

## 14. What to actually do next

1. **Author Project 1** (§2) verbatim as the master files + hidden tests, in your repo.
2. Run it through `gap_parser.py` → `gap_generator.py` → `scope_check.py` → CI, exactly
   as Step 9 → Step 10 of the runbook specify.
3. **Only then** come back and author Projects 2–10 from the tables in §3–§11 — they are
   specified in enough detail (function names, gap concepts, difficulty, gap type) to
   write directly, following Project 1's now-proven `@gap:` pattern.
4. Feed §12's coverage table into the presentation's limitations section honestly,
   per point 3 above.
