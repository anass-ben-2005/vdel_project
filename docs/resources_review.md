# Resources review

Draft of the learning resources the Feedback Agent can recommend, for **you to review and load**. Nothing here has been loaded into any database. The CSV is `config/resources.csv`.

- Rows: **32** (11 beginner, 12 intermediate, 9 advanced). All `kind = doc_page`.
- Every URL below was fetched in this session (plain HTTP GET, https, allowed domains only). A row is kept only if: HTTP 200, **no redirect** (the URL is its own final URL), the anchor exists in the page when the URL has one, and the words the one-sentence rationale relies on appear in the fetched page.
- Checked on **2026-10-12**. Documentation moves: re-run the check before a term starts.
- The student sees: `Suggested reading: **<title>**, <locator>. <url>` (from `agents/feedback_agent.py`), so `title` and `locator` are written to read well in that line.

## Coverage

| Concept | Tier | Rows | Levels |
|---|---|---|---|
| `spark.df_basics` | 2 | 2 | beginner, beginner |
| `spark.transform_action` | 2 | 1 | intermediate |
| `spark.read` | 2 | 1 | beginner |
| `spark.aggregation` | 2 | 1 | intermediate |
| `spark.joins` | 2 | 1 | intermediate |
| `spark.window` | 2 | 1 | advanced |
| `spark.udf` | 2 | 1 | intermediate |
| `spark.partitioning` | 2 | 1 | advanced |
| `spark.caching` | 2 | 1 | intermediate |
| `spark.perf_tuning` | 2 | 1 | advanced |
| `sql.select_filter` | 1 | 3 | beginner, intermediate, advanced |
| `sql.joins` | 2 | 2 | beginner, intermediate |
| `sql.aggregation` | 1 | 3 | beginner, intermediate, advanced |
| `py.data_structures` | 1 | 3 | beginner, intermediate, advanced |
| `py.pandas` | 1 | 3 | beginner, intermediate, advanced |
| `py.errors_debugging` | 1 | 3 | beginner, intermediate, advanced |
| `py.testing` | 1 | 3 | beginner, intermediate, advanced |
| `airflow.operators` | 2 | 1 | beginner |
| `airflow.idempotency` | 2 | 0 | none |

Tier 1 = concepts used by gaps in the real database (`select distinct unnest(concept_ids) from gaps`): `py.data_structures`, `py.errors_debugging`, `py.pandas`, `py.testing`, `sql.aggregation`, `sql.select_filter`. Tier 2 = the other concepts of `config/concepts.yaml`.

## Resources

| resource_id | concept | why it helps | why this level | page title fetched | HTTP | checked | doubt |
|---|---|---|---|---|---|---|---|
| `py-tut-dictionaries` | py.data_structures | Shows what a dict is and how keys are looked up, the base for reading records safely. | beginner: Official tutorial chapter, no prior knowledge assumed. | 5. Data Structures — Python 3.15.0 documentation | 200 | 2026-10-12 | Teaches dicts in general; it is not a page about handling a missing key, so it does not give away g_ext_parse. |
| `py-ref-mapping-types` | py.data_structures | The reference for every dict operation, for a student who knows the basics and needs the exact behaviour. | intermediate: A reference page: precise but terse. | Built-in Types — Python 3.15.0 documentation | 200 | 2026-10-12 | It lists all dict methods, including the ones relevant to g_ext_parse. It is a reference, not a worked solution, but check you are happy to point students there. |
| `py-lib-collections` | py.data_structures | Specialised containers (counting, default values, ordered queues) once the built-in structures feel natural. | advanced: Goes beyond the built-in list/dict/set the exercises use. | collections — Container datatypes — Python 3.15.0 documentation | 200 | 2026-10-12 | Whole module page, long; the locator does not name a section. |
| `py-tut-handling-exceptions` | py.errors_debugging | Explains try/except step by step, which is how a failure is caught instead of crashing the program. | beginner: Official tutorial section written for newcomers. | 8. Errors and Exceptions — Python 3.15.0 documentation | 200 | 2026-10-12 | try/except is part of the solutions of g_ext_retry and g_tf_timestamp; the page teaches the construct, it does not solve either exercise. |
| `py-ref-exception-hierarchy` | py.errors_debugging | Shows which exception is a kind of which, so a student can catch the right one and read a traceback. | intermediate: Needs the idea of exceptions first. | Built-in Exceptions — Python 3.15.0 documentation | 200 | 2026-10-12 | none |
| `py-lib-pdb` | py.errors_debugging | Stepping through code and inspecting values to find the cause of a failure instead of guessing. | advanced: A command-line debugger reference, for a student already comfortable reading tracebacks. | pdb — The Python Debugger — Python 3.15.0 documentation | 200 | 2026-10-12 | none |
| `pandas-10min` | py.pandas | A short tour of Series and DataFrames and the usual operations. | beginner: Written as a first tour. | 10 minutes to pandas — pandas 3.0.6 documentation | 200 | 2026-10-12 | none |
| `pandas-indexing-basics` | py.pandas | How rows and columns are selected, the step before any view-versus-copy question matters. | intermediate: Assumes the 10-minute tour. | Indexing and selecting data — pandas 3.0.6 documentation | 200 | 2026-10-12 | The classic 'view versus a copy' section no longer exists in this pandas version (see Dropped). |
| `pandas-copy-on-write` | py.pandas | Explains when pandas copies data and when a change made through one object reaches another. | advanced: Needs solid indexing knowledge. | Copy-on-Write (CoW) — pandas 3.0.6 documentation | 200 | 2026-10-12 | Describes current pandas behaviour; a student on an older pandas may see different warnings. |
| `pytest-get-started` | py.testing | Write and run a first test and read its output. | beginner: Official first page of the documentation. | Get Started - pytest documentationContentsMenuExpandLight modeDark modeAuto light/dark, in light modeAuto light/dark, in dark mode | 200 | 2026-10-12 | none |
| `pytest-assertions` | py.testing | What a good assertion looks like and how pytest reports a failing one. | intermediate: Assumes a first test has been run. | How to write and report assertions in tests - pytest documentationContentsMenuExpandLight modeDark modeAuto light/dark, in light modeAuto light/dark, in dark mode | 200 | 2026-10-12 | The page also covers asserting exceptions; it does not mention our exercises. |
| `pytest-fixtures` | py.testing | Shared setup for tests, the step after plain test functions. | advanced: Fixtures are an abstraction on top of basic tests. | How to use fixtures - pytest documentationContentsMenuExpandLight modeDark modeAuto light/dark, in light modeAuto light/dark, in dark mode | 200 | 2026-10-12 | none |
| `pg-tutorial-select` | sql.select_filter | First SELECT, column lists and WHERE on one table. | beginner: The official tutorial, in order. | PostgreSQL: Documentation: 18: 2.5. Querying a Table | 200 | 2026-10-12 | PostgreSQL syntax; our exercises use SQLite, and the basics are the same. |
| `pg-where-clause` | sql.select_filter | How the WHERE clause filters rows with a condition. | intermediate: Reference-style section of the manual. | PostgreSQL: Documentation: 18: 7.2. Table Expressions | 200 | 2026-10-12 | PostgreSQL manual; the shared part with SQLite is the standard SQL core. |
| `pg-select-reference` | sql.select_filter | The full formal definition of the WHERE clause, for exact semantics. | advanced: Formal reference, dense. | PostgreSQL: Documentation: 18: SELECT | 200 | 2026-10-12 | none |
| `pg-tutorial-aggregates` | sql.aggregation | count, max, GROUP BY and HAVING on a small example. | beginner: The official tutorial, in order. | PostgreSQL: Documentation: 18: 2.7. Aggregate Functions | 200 | 2026-10-12 | PostgreSQL syntax; the aggregate basics are standard SQL. |
| `pg-group-by` | sql.aggregation | How GROUP BY forms groups and how HAVING filters them. | intermediate: Reference-style section. | PostgreSQL: Documentation: 18: 7.2. Table Expressions | 200 | 2026-10-12 | none |
| `pg-aggregate-functions` | sql.aggregation | The complete list of aggregate functions with their exact behaviour, including NULL handling. | advanced: A long reference table. | PostgreSQL: Documentation: 18: 9.21. Aggregate Functions | 200 | 2026-10-12 | none |
| `pg-tutorial-joins` | sql.joins | Joining two tables, inner and outer, on a small example. | beginner: The official tutorial, in order. | PostgreSQL: Documentation: 18: 2.6. Joins Between Tables | 200 | 2026-10-12 | PostgreSQL syntax; the join basics are standard SQL. |
| `pg-join-types` | sql.joins | The join kinds side by side, to choose the one that keeps the intended grain. | intermediate: Reference-style section. | PostgreSQL: Documentation: 18: 7.2. Table Expressions | 200 | 2026-10-12 | none |
| `spark-sql-getting-started` | spark.df_basics | Creates a SparkSession and DataFrames and runs the first operations. | beginner: The official getting-started page for Spark SQL. | Getting Started - Spark 4.2.0 Documentation | 200 | 2026-10-12 | none |
| `pyspark-quickstart-df` | spark.df_basics | A runnable PySpark DataFrame tour, in Python rather than SQL. | beginner: Official quickstart. | Quickstart: DataFrame — PySpark 4.2.0 documentation | 200 | 2026-10-12 | none |
| `spark-rdd-operations` | spark.transform_action | States the difference between lazy transformations and actions that run the computation. | intermediate: Needs the DataFrame basics first. | RDD Programming Guide - Spark 4.2.0 Documentation | 200 | 2026-10-12 | Written for RDDs; DataFrames behave the same way but the page does not use DataFrame examples. |
| `spark-load-save` | spark.read | Reading and writing data sources with explicit formats and options. | beginner: Official page, short. | Generic Load/Save Functions - Spark 4.2.0 Documentation | 200 | 2026-10-12 | none |
| `spark-groupby` | spark.aggregation | How grouping and aggregate expressions produce the intended grain in Spark SQL. | intermediate: Reference page. | GROUP BY Clause - Spark 4.2.0 Documentation | 200 | 2026-10-12 | none |
| `spark-joins` | spark.joins | The join types and syntax Spark supports, for choosing keys and avoiding an accidental cross join. | intermediate: Reference page. | JOIN - Spark 4.2.0 Documentation | 200 | 2026-10-12 | none |
| `spark-window-functions` | spark.window | The syntax and supported window functions, including the frame specification. | advanced: Needs aggregation first. | Window Functions - Spark 4.2.0 Documentation | 200 | 2026-10-12 | none |
| `spark-scalar-udfs` | spark.udf | What a UDF is and how to register one. | intermediate: Needs DataFrame basics. | Scalar User Defined Functions (UDFs) - Spark 4.2.0 Documentation | 200 | 2026-10-12 | It does not say when a built-in function should be preferred. |
| `spark-partitioning-hints` | spark.partitioning | How to control the number of partitions with coalesce, repartition and rebalance hints. | advanced: Needs joins and an idea of shuffles. | Hints - Spark 4.2.0 Documentation | 200 | 2026-10-12 | none |
| `spark-caching-data` | spark.caching | When and how to cache a DataFrame that is reused. | intermediate: Needs transformations versus actions. | Performance Tuning - Spark 4.2.0 Documentation | 200 | 2026-10-12 | none |
| `spark-performance-tuning` | spark.perf_tuning | The tuning options in one place: partitions, shuffles, joins and caching. | advanced: Needs partitioning and caching first. | Performance Tuning - Spark 4.2.0 Documentation | 200 | 2026-10-12 | none |
| `airflow-operators` | airflow.operators | What an operator is and how it relates to a task. | beginner: Core-concepts page. | Operators — Airflow 3.3.2 Documentation | 200 | 2026-10-12 | none |

## Dropped

Candidates that failed verification, or were replaced by something verified:

- `https://www.sqlite.org/lang_select.html, lang_expr.html, nulls.html, lang_aggfunc.html`: TLS certificate verification failed (`certificate has expired`) on www.sqlite.org. I did not bypass the check, so none of these four could be verified. They would have given `sql.select_filter` and `sql.aggregation` a SQLite-specific page (the exercises use SQLite). PostgreSQL pages are used instead.
- `https://docs.python.org/3/library/stdtypes.html#mapping-types-dict`: Redirects to /3/builtins/stdtypes.html and the anchor does not exist there. Replaced by `/3/builtins/stdtypes.html#typesmapping` (fetched, anchor present).
- `https://docs.python.org/3/library/exceptions.html#exception-hierarchy`: Redirects to /3/builtins/exceptions.html. Replaced by the final URL (fetched, anchor present).
- `https://docs.python.org/3/tutorial/datastructures.html#dictionaries and errors.html#handling-exceptions`: Both existed, but they are aliases of the section's own ids. Replaced by `#tut-dictionaries` and `#tut-handling`.
- `https://pandas.pydata.org/docs/user_guide/indexing.html#returning-a-view-versus-a-copy`: Anchor not in the page (the 'view versus a copy' section is gone from the pandas 3 docs). Replaced by the Copy-on-Write page.
- `https://spark.apache.org/docs/latest/sql-performance-tuning.html#caching-data-in-memory`: Anchor not in the page. Replaced by `#caching-data`.
- `airflow.idempotency: best-practices.html, core-concepts/tasks.html, dag-run.html, dags.html, tutorial/fundamentals.html`: All return 200 but none contains the word 'idempotent' (checked in the page text). Not recommended for the concept; **airflow.idempotency has no resource**.

Verified (HTTP 200) but not used, kept as spares so each tier 1 concept has at most 4 rows: docs.python.org `/3/library/unittest.mock.html`, `/3/howto/logging.html`; pandas `/user_guide/missing_data.html`; pytest `/how-to/parametrize.html`; PostgreSQL `/functions-comparison.html`; Spark `/rdd-programming-guide.html#rdd-persistence`.

## Needs manual check

- **www.sqlite.org** (allowed domain, but its certificate failed validation from this machine): `lang_select.html`, `lang_expr.html`, `nulls.html`, `lang_aggfunc.html`. Open them in your browser; if they load, they are good SQLite-specific pages for `sql.select_filter` / `sql.aggregation`. The failure could also be this machine's clock or trust store.
- **Off the allowed list, not fetched** (candidates only): the free Kaggle Learn courses (`kaggle.com/learn/pandas`, `kaggle.com/learn/intro-to-sql`, `kaggle.com/learn/python`) would fit `kind = kaggle` for `py.pandas`, `sql.select_filter`, `sql.aggregation`, `py.data_structures`. Verify the course pages and exact lesson URLs yourself before adding any.
- **No resource for `airflow.idempotency`**: I found no official page in the allowed domains that treats idempotency (see Dropped). The tutor-side collaborator may have a course page for it.

## What I could not judge

Whether each page suits *your students*. I could only check that a page exists and what it says:
- Language and reading level: all pages are in English and written for a general audience.
- **Python version.** The student repos run Python 3.11 in CI; docs.python.org/3 now serves the 3.15 documentation. The tutorial and the exceptions page are stable, but a detail may differ.
- **SQL dialect.** The exercises use SQLite; the SQL pages are PostgreSQL's manual (standard SQL core, a few differences). Fine for concepts, wrong for dialect questions.
- **pandas/Spark versions.** pandas pages are for 3.x (Copy-on-Write on by default), Spark pages for 4.x. If the course uses older versions, warnings and syntax may differ.
- **Reference pages at 'intermediate'/'advanced'** (Python Built-in Types, PostgreSQL command reference, Spark SQL reference) are accurate but terse; some students may find them hard.
- **Hints versus answers.** I avoided pages that walk through our exercises (for example the `sqlite3` tutorial that shows inserting rows, `datetime.fromisoformat`, list-comprehension filtering). Two rows are close enough to flag: `py-tut-handling-exceptions` (try/except is part of two solutions) and `py-ref-mapping-types` (lists `dict` methods). Both teach a construct, not the exercise. Your call.
- Whether pointing a student at the full manual is better than a short tutorial for a given concept.

## How this was checked

Plain HTTP GET only, https, one request per page at a time, a descriptive User-Agent, redirects followed by hand with the domain re-checked at every hop. Domains requested: docs.python.org, pandas.pydata.org, docs.pytest.org, www.postgresql.org, spark.apache.org, airflow.apache.org, www.sqlite.org (4 attempts, all failed at the TLS handshake, no content received). Total HTTP requests: **120**. No POST, no login, no file download.

