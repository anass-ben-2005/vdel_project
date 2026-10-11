# tests/fixtures/agents: origin of every fixture

Rule: no hidden test source, no assertion message, no traceback, no real student code. Failures
are stored as test name + exception TYPE only (D-077). `tests/test_agents_fixtures.py` checks it.

## real/ (exported read-only from the project database)

Produced by `python -m scripts.agents_export_fixtures` (opens a read-only session; writes only
these files). One file per graded commit. The `diagnosis` block is `assessment.diagnose`'s
output for the ATTEMPT (its `failing_tests` is the attempt's latest commit, so for an older
commit it can be empty while the commit's own `checks` show failures; the agents read the
commit's `checks`). `mastery` is the profile at export time, not at the commit.

| file | situation |
|---|---|
| `student2__weather_etl_extract__a82__128da3e9__ok` | 3 of 4 checks; one retry check fails (ConnectionError); retry gap recurs |
| `student2__weather_etl_extract__a82__52d4ac3d__collection_error` | the file did not load; no check ran |
| `student2__weather_etl_extract__a82__ecee2946__ok` | 4 of 4, all done |
| `student2__weather_etl_load__a84__4832ec3c__ok` | the load stage, 1 of 2 |
| `anas__weather_etl_extract__a1__57590786__ok` | 2 of 4 |
| `anas__weather_etl_extract__a1__2d087f5c__ok` | 4 of 4 |
| `anas__weather_etl_load__a3__d818c872__collection_error` | load stage did not load |

(`anas` and `student2` are roster ids, not names.)

## synthetic/ (hand-written, same shape)

| file | why it exists |
|---|---|
| `synthetic1__weather_etl_extract__multi_failure` | 3 failing checks, 3 exception types, recurring gap, 2 concepts |
| `synthetic1__weather_etl_extract__timeout` | no real commit has status `timeout` yet |
| `synthetic2__weather_etl_extract__no_mastery` | empty mastery slice (first attempt) |
| `resources_synthetic.json` | FAKE candidate resources (`EXAMPLE-` ids); the real table has 0 rows |

## code/ (small synthetic student files for the Code Agent)

Written by hand; not copied from the master solution, a student repo or `renders/`.

| file | situation |
|---|---|
| `extract_retry_ok.py` | bounded retry loop with backoff, safe parsing |
| `extract_no_retry.py` | one attempt, brittle parsing |
| `extract_syntax_error.py` | does not load (matches the collection_error situation) |
| `extract_infinite_loop.py` | loop with no exit (matches the timeout situation); never executed |
