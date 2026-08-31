# VDEL Student-Side — Implementation Explanation (M0–M4)

> Written for an AI (or human) picking up this codebase cold, with no memory of how it
> was built. It explains what exists, why it exists in this exact shape, where every
> number and formula comes from, and what is still open. Read this before touching any
> file — it will save you from re-deriving decisions that were already made, and from
> repeating mistakes that were already made and fixed once.

---

## 0. The one sentence that explains every design choice

> **Auditability is a functional requirement. A grade we cannot explain is not a grade
> we can defend.**

This is why: event sourcing instead of in-place updates, anchored rubrics instead of
free-form scores, verbatim evidence quotes instead of paraphrase, and an interpretable
mastery model (Bayesian Knowledge Tracing) instead of a neural one (Deep Knowledge
Tracing). Every time this document says "X was chosen over Y," this sentence is the
reason, even when it isn't repeated.

---

## 1. What VDEL is and what this repository is

**VDEL** (Virtual Data Engineering Lab) is a teaching platform at UiTM (industry partner
AntsBees) that teaches Python, SQL, PySpark and Airflow. This repository is the
**student-side AI intelligence layer**: it watches a student work (via their GitHub
activity), builds a private, continuously-updated model of what that student knows and
how they work, and will eventually use that model to (1) grade submissions with
explainable AI agents and (2) coach students who are stuck.

**People:** Anas is the intern building this (student-side). Hanafi is building the
tutor-side (knowledge graph, RAG, personas) in parallel. Dr. Ezzatul Akmal supervises.

**This repository's job right now (M0 + M1) is narrow:** get real telemetry from GitHub
into a database, and turn that telemetry into seven numeric variables that describe a
student. Nothing here grades anyone yet — there is no LLM call anywhere in this
codebase. Grading (Code Agent) is M4. Memory and the event-sourced profile are M2. This
document covers only what has been built: **M0 (Foundations)** and **M1 (Telemetry +
Features)**.

### Where the specification comes from

Four documents in the repo root are the **source of truth**. This codebase is a
**transcription** of them, not an independent design:

| Document | What it contains |
|---|---|
| `VDEL_Modules_1_2_Build.md` | The seven variables' exact formulas, the schema, the GitHub collector, the error classifier — with code, for Modules 1 (variables) and 2 (telemetry). |
| `VDEL_Modules_3_9_Build.md` | Memory, LLM gateway, the agents, the Reviewer (Modules 3–9) — not yet built. |
| `VDEL_v1_Execution_Plan.md` | The M0–M7 milestone plan, task by task, with each milestone's Definition of Done. |
| `vdel_complete_design_document.md` | Full design rationale, the memory-hierarchy philosophy, and **Sara** — the hand-computed worked example used to test the code. |
| `CLAUDE.md` | A condensed summary of the above four, plus repository conventions (this is what an AI assistant reads automatically; it is *not* itself a source of new formulas). |
| `BUILD_PLAN.md` | The task breakdown this repo's construction actually followed, mirroring the Execution Plan. |

**Critical fact about how this codebase came to be:** an earlier pass at this repo was
built *without* the four large source documents being available — only `CLAUDE.md`'s
summary was readable. That pass **invented** formulas that looked plausible (a
same-shape BKT update, a same-shape pace formula) instead of stopping to ask for the
source documents. Several of those inventions were subtly or badly wrong — one class of
bug made the entire mastery model mathematically inert (see §9, "History of this
codebase," for the specifics — it matters for calibrating how much to trust code that
looks right but wasn't checked against a source). When the four documents were added to
the repo, the entire variables layer, the classifier, and the collector were **rewritten
from scratch as verbatim transcriptions**. That is the code described below. If you are
about to modify a formula, find its paragraph in `VDEL_Modules_1_2_Build.md` first — the
document wins over any local reasoning about what "should" be correct.

---

## 2. Repository layout

Fixed by `CLAUDE.md` §5 and `VDEL_Modules_1_2_Build.md`'s own "Repository layout"
section — not meant to grow organically.

```
vdel-student-side/
├── sql/
│   ├── 01_reference_tables.sql   # students, assignments
│   ├── 02_raw_tables.sql         # raw_commits, raw_workflow_runs
│   ├── 03_feature_tables.sql     # learner_features, kt_params, items
│   ├── 04_indexes.sql            # perf indexes (+ traces indexes, see §4.5 ordering note)
│   └── 05_memory_tables.sql      # traces, sessions, learner_profile (M2's tables, DDL only)
├── variables/                    # THE SEVEN FORMULAS. Pure functions, no I/O, no DB.
│   ├── mastery.py                 # V1: BKT + KT-IDEM + Beta posterior
│   ├── habits.py                  # V2 discipline + V3 effort
│   ├── pace.py                    # V4: censoring-aware, cohort-relative
│   ├── error_response.py          # V5: Jadud/Watwin + wheel-spin vs productive failure
│   └── error_frequency.py         # V6: opportunity-normalised + recurrence rule
├── collectors/
│   ├── collect_github.py          # GitHub -> raw_commits / raw_workflow_runs
│   └── error_classifier.py        # CI failure log -> (error_class, concept_id)
├── features/
│   └── compute_features.py        # raw tables -> the seven variables -> learner_features
├── config/
│   ├── concepts.py                # taxonomy loader + validator
│   ├── concepts.yaml              # the 19 concept ids (of an eventual ~25)
│   └── roster.example.yaml        # template for real students/repos (never invented)
├── scripts/
│   ├── init_db.py                 # runs sql/01..05 in dependency order, idempotent
│   ├── smoke_test.py              # DB reachable? tables + columns exist? traces append-only?
│   ├── seed_data.py               # loads config/roster.yaml into students/assignments/items/kt_params
│   ├── collect.py                 # CLI entrypoint: run the GitHub collector over the roster
│   └── prove_event_sourcing.py    # the M2 proof: snapshot -> TRUNCATE -> rebuild -> deep-diff
├── dags/
│   └── vdel_pipeline.py           # Airflow: collect -> compute_features -> update_profiles
├── system/
│   └── db.py                      # the ONE place psycopg2.connect() is called
├── tests/
│   ├── test_mastery.py            # V1 formulas, checked against the published equations
│   ├── test_variables.py          # V2-V6 formulas, checked against the published equations
│   ├── test_classifier.py         # every documented rule + false-positive resistance
│   ├── test_concepts.py           # taxonomy loader validation
│   ├── test_sara.py               # hand-computed worked example (testing by construction)
│   └── test_pipeline_integration.py  # raw tables -> learner_features, end to end, against a real DB
├── docker-compose.yml             # Postgres 16 + pgvector, host port 5433 (see §4.1)
├── pyproject.toml                 # packaging + pytest + ruff config
├── requirements.txt / requirements-airflow.txt
├── .env.example
└── .github/workflows/ci.yml       # schema build x2, smoke test, lint, pytest
```

Directories that exist as empty scaffolding for later milestones (`memory/`, `agents/`,
`benchmark/`) are present because `CLAUDE.md` §5 fixes the tree in advance; they hold
only `__init__.py` right now and are **not described further in this document** because
nothing is in them yet.

---

## 3. The data model — what's in the database and why

### 3.1 The governing rule: land raw first

Raw tables (`raw_commits`, `raw_workflow_runs`) are the **source of truth**. The seven
variables in `learner_features` are *computed from* raw data, and that computation
carries a `formula_ver` column because **the formulas will change** — mastery has
already gone through one ladder rung (EWMA, dropped, in favor of BKT). If raw data is
kept, history can always be recomputed when a formula changes. If only the computed
features were kept, changing a formula would silently rewrite history with no way back.
**Nothing in this codebase ever overwrites a raw table's historical row** — collectors
upsert on natural keys (commit SHA, workflow run ID) and only add columns or update
mutable fields (a workflow run's `conclusion` can change from `in_progress` to
`success`), never delete or fabricate a row.

### 3.2 Schema, table by table

All DDL uses `CREATE TABLE IF NOT EXISTS` — re-running `init_db.py` against an existing
database is a documented no-op, not an error. This is invariant 9 (see §8).

**`students`** (`sql/01_reference_tables.sql`)
```sql
student_id       TEXT PRIMARY KEY,     -- e.g. 'anas' -- the internal key used everywhere
github_username  TEXT UNIQUE NOT NULL, -- what the collector actually queries GitHub with
cohort           TEXT NOT NULL         -- groups students for cohort-relative stats (V4, V2's alpha gate)
```

**`assignments`**
```sql
assignment_id  TEXT PRIMARY KEY,     -- e.g. 'A2'
repo_prefix    TEXT NOT NULL,        -- e.g. 'owner/repo' -- which GitHub repo this maps to
released_at    TIMESTAMPTZ NOT NULL, -- STARTS THE PACE CLOCK. Never invented (see §5.4, §7.4).
due_at         TIMESTAMPTZ,          -- optional; not currently read by any formula
concepts       TEXT[] NOT NULL       -- taxonomy ids this assignment tests; how a CI failure
                                      -- knows which mastery scores are even in scope
```

**`raw_commits`** (`sql/02_raw_tables.sql`) — one row per Git commit, keyed by SHA
(GitHub's own unique ID, so re-collecting the same commit is naturally idempotent via
`ON CONFLICT (sha) DO UPDATE`). `committed_at` is what V3 (effort/burstiness) is
computed from. `additions`/`deletions`/`files_changed` come from a *second*, more
expensive GitHub API call per commit (see §5.1's "detail call").

**`raw_workflow_runs`** — one row per GitHub Actions run, keyed by GitHub's `run_id`.
`conclusion` (`success` / `failure` / ...) is **the pass/fail signal that drives
everything**: V1 (mastery) replays these in order; V5/V6 (error response/frequency) are
computed from the failures. `error_class` and `concept_id` are filled in by the
classifier (§6) **at collection time**, not later — this matters (see §9's list of fixed
bugs: an earlier version left these permanently `NULL`).

**`learner_features`** (`sql/03_feature_tables.sql`) — one row per `(student_id,
computed_at)`. This is the output of `features/compute_features.py`. Six JSONB columns,
one per variable computed so far (V1 through V6; V7/`help_seeking` is nullable — it has
no formula yet, see §7.7). `computed_at` is **not** wall-clock "when did I run this
script" — see §7.2 for why that distinction is load-bearing for idempotency.

**`kt_params`** — one row per `(param_set, concept_id)`: the four BKT numbers
(`p_l0`, `p_t`, `p_guess`, `p_slip`) for that concept, versioned by `param_set` (starts
at `'bkt_v1'`, cold-start literature defaults; will become `fitted=TRUE` EM-estimated
values once ≥100 sequences per concept exist — not there yet, cohort is n=1).

**`items`** — the KT-IDEM item bank. **Not** keyed by `concept_id` — keyed by
`item_id` (currently, one item per *assignment*, tagged with the concepts it tests via
`concept_ids TEXT[]`). `difficulty` is `1 − cohort pass rate`, Beta-smoothed
(`DifficultyEstimator` in `variables/mastery.py`, §7.1); `n_cohort_obs` tracks how much
evidence backs that difficulty estimate. Seeded at a taxonomy-derived cold-start value
by `scripts/seed_data.py` and never overwritten by seeding again (`DO NOTHING` on
conflict) — the live value is meant to be owned by the cohort estimator once one exists.

**`traces`, `sessions`, `learner_profile`** (`sql/05_memory_tables.sql`) — **M2's
tables.** The DDL is created now (BUILD_PLAN 0.3 asks for all five SQL files in M0) but
**nothing in M1 writes to them yet**. `traces` has two Postgres `RULE`s that make
`UPDATE` and `DELETE` silent no-ops — this is invariant 1 (append-only) **enforced by
the database itself**, not by convention or code discipline. See §8 and §3.4.

Two columns — `learner_profile.session_digest` and `sessions.summary` — were missing from
this file until 2026-08-11. `Modules_3_9` B.4 declares both, B.5 reads `session_digest`,
B.6 writes `sessions.summary`, and the complete design document lists both, so this was a
transcription gap here rather than a design decision (`DECISIONS.md` D-008). They are now
in the `CREATE TABLE` bodies *and* added by idempotent `ALTER TABLE ... ADD COLUMN IF NOT
EXISTS`, because `CREATE TABLE IF NOT EXISTS` does nothing to a database that already
exists. Nothing writes to either column yet; `sessions.summary` is filled by the
compression job in M2.3. `sessions.trace_count` exists here and not in the module document
— additive drift, deliberately left alone.

### 3.3 Indexes (`sql/04_indexes.sql`)

Two purposes: match the actual query patterns of `compute_features.py` (composite
indexes on `(student_id, assignment_id, timestamp)` for both raw tables — every feature
query filters by exactly those columns), and a **partial** index on
`raw_workflow_runs(concept_id) WHERE conclusion = 'failure'` — smaller and faster
because only failed runs ever carry a concept. Plus two indexes for `traces` (hot path:
"what has this student done lately", and a GIN index for `concept_ids @>` containment
queries) even though nothing populates `traces` yet — added here because M2 will need
them immediately and the module document specifies them.

### 3.4 A subtlety: file numbering vs. dependency order

`sql/04_indexes.sql` indexes the `traces` table, but `traces` is *created* in
`sql/05_memory_tables.sql`. The filenames say 04 before 05; the actual dependency
requires 05 before 04. This isn't a bug to "fix" by renumbering — `CLAUDE.md` §5 and the
module document both fix these exact filenames, and renumbering would break that
correspondence for no benefit. Instead, `scripts/init_db.py` has an explicit `ORDER`
list that runs `05_memory_tables.sql` before `04_indexes.sql`, with a comment pointing
at this exact explanation. **If you ever add a new SQL file, check `init_db.py`'s
`ORDER` list — it is not simply "sorted by filename."**

---

## 4. Infrastructure (M0)

### 4.1 Docker Compose — and a real trap on this specific machine

`docker-compose.yml` runs a single `pgvector/pgvector:pg16` container. Two things worth
knowing:

- **Host port is 5433, not 5432.** This machine has a native Windows PostgreSQL 13
  service already listening on 5432. Docker will happily publish the container's 5432 to
  the host's 5432 with zero error — but every connection from the host then silently
  reaches the *native* PostgreSQL 13 instance, which has no `vdel` role. The failure mode
  is **not** "port already in use" (Docker doesn't detect the conflict that way here) —
  it's `password authentication failed for user "vdel"`, which looks exactly like a typo
  in the password. This cost real debugging time once already. `.env.example`'s `PG_DSN`
  already points at `5433`; if you ever see that specific auth error on this machine,
  check `netstat`/`Get-NetTCPConnection` for who owns 5432 before assuming the password
  is wrong.
- The image tag matters: `pgvector/pgvector:pg16-latest` **does not exist** (a
  once-invented tag from before the source documents were available). The correct tag is
  `pgvector/pgvector:pg16`.

### 4.2 `system/db.py` — the one place `psycopg2.connect()` is called

Three context managers, all building on one private `_open()`:

- **`_open()`** wraps `psycopg2.connect()` and specifically catches
  `UnicodeDecodeError`. Why: on a non-English-locale Windows machine, libpq (the C
  library psycopg2 wraps) returns connection error text in the OS codepage (`cp1252`
  here — French, in this case), but psycopg2 always tries to decode server messages as
  UTF-8. The result is that **any** connection failure — wrong password, wrong host, DB
  down — surfaces as an opaque `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9`
  with the actual message (`"authentification par mot de passe échouée"`) destroyed.
  `_open()` catches this, re-decodes the raw bytes as `cp1252`, and re-raises as a
  readable `psycopg2.OperationalError`. This is exactly how the 5433-port issue above was
  diagnosed — without this fix the real cause would have stayed invisible.
- **`connect()`** — commits on success, rolls back on any exception, always closes.
- **`cursor()`** — the common case, one cursor inside one `connect()`.
- **`dry_run_cursor()`** — opens a connection, yields a cursor, and **always** rolls
  back regardless of outcome. Used by `smoke_test.py` to prove `traces` rejects
  UPDATE/DELETE by actually attempting both, without leaving any row behind afterward.

Every other file in the repo (`init_db.py`, `smoke_test.py`, `seed_data.py`,
`compute_features.py`, the DAG) goes through this module. Nothing else calls
`psycopg2.connect()` directly. This is what lets a collector run be a real transaction —
one failure partway through a repo's collection rolls back that repo's writes instead of
leaving half-written rows (combined with per-repo isolation, §5.5, that means one bad
repo can't corrupt another repo's data).

### 4.3 `scripts/init_db.py`

Runs the five SQL files as raw multi-statement scripts (not through an ORM/migration
tool — deliberately: `BUILD_PLAN` M0 warns explicitly against spending day one on
package/migration ceremony). Also runs `CREATE EXTENSION IF NOT EXISTS vector` first
(pgvector — reserved for M3's RAG work, unused by anything in M0/M1, but the extension
needs to exist before any future `vector` column is declared). Idempotent because every
statement inside the SQL files is `IF NOT EXISTS` / `CREATE OR REPLACE`.

### 4.4 `scripts/smoke_test.py`

The M0 Definition of Done, executable: (1) can we connect, (2) do all ten expected
tables exist, (3) are the decision-bearing columns present, (4) does `traces` actually
reject `UPDATE` and `DELETE` — the append-only invariant is *tested*, not just declared.
All four checks run inside `dry_run_cursor()`, so the smoke test can run safely against a
database that already has real student data in it.

Check (3) — `EXPECTED_COLUMNS` — is deliberately **not** an exhaustive column list; each
table's DDL owns its own shape. It names only columns that exist because of a recorded
decision and whose absence is *silent*: a missing table fails loudly on the next query,
but a missing column fails only when the one code path that reads it finally runs. That is
exactly how `session_digest` and `sessions.summary` stayed missing (D-008), so those two
are what it currently guards.

### 4.5 CI (`.github/workflows/ci.yml`)

On every push: spin up a `pgvector/pgvector:pg16` service container, install deps, run
`ruff check .`, run `init_db.py` **twice** in a row (proving idempotency, not just
correctness on first run), run `smoke_test.py`, run `pytest -q`. This is the automated
form of the M0 DoD.

### 4.6 Environment configuration (`.env.example` / `.env`)

`PG_DSN`, `GITHUB_TOKEN`, and three keys reserved for M3 (`LLM_PROVIDER`, `LLM_MODEL`,
`ANTHROPIC_API_KEY`) that are **listed but read by nothing yet** — present so the seam
is visible in one place rather than appearing out of nowhere when M3 starts.
`FEATURE_WINDOW_DAYS` (default 14) is read by `compute_features.py` for the
`window_days` column, though as of this writing no formula actually windows its query by
it yet (see §7's TODOs) — it's wired through but not yet load-bearing everywhere the
column name implies.

---

## 5. The GitHub collector (`collectors/collect_github.py`)

**Purpose:** pull commits and CI run results from GitHub into `raw_commits` /
`raw_workflow_runs`. This is Module 2 of the source document, transcribed, with three
additions (each marked `ADDED` in the file's own comments) layered on top of the
document's logic without changing it.

### 5.1 The core problem it solves: GitHub's rate limit

GitHub's REST API allows 5,000 requests/hour for an authenticated token. Naively
re-fetching everything on every run would burn through that fast, especially because
**getting a commit's diff stats (`additions`/`deletions`/`files_changed`) requires a
second, per-commit API call** — the list endpoint doesn't include them. The module
document calls this "the expensive call." Seven optimizations exist for this, in a
specified priority order (also mirrored in `BUILD_PLAN.md` 1.3):

1. **Skip-if-present before the expensive per-commit detail call** (highest leverage —
   do this first). Before fetching a commit's detail, check if `raw_commits` already has
   a row for that SHA with `additions IS NOT NULL`. If so, skip the detail call
   entirely.
2. **Incremental `since=`** — track the max `committed_at` already stored for this
   `(student_id, assignment_id)` and only ask GitHub for commits after that.
3. **Rate-limit-header-aware backoff** — every GitHub response carries
   `X-RateLimit-Remaining` and `X-RateLimit-Reset`. When remaining drops below 50, sleep
   until the reset time *before* hitting the wall, rather than getting a 403 and having
   to retry.
4. **Batched `execute_values` upserts** — one round-trip per repo's commits/runs instead
   of one INSERT per row.
5. *(Indexes — see §3.3, not part of this file.)*
6. *(Tiered classification — not implemented; see §6's note on this.)*
7. **Per-repo `try/except` isolation** — `collect_all()` wraps each repo's
   `collect_repo()` call individually. One broken repo (deleted, renamed, permissions
   revoked) becomes a logged failure entry in the returned dict, not a crash that stops
   collection for every other repo.

### 5.2 Function-by-function

- **`_headers()`** — builds the auth header from `os.environ["GITHUB_TOKEN"]`, read
  **lazily on each call**, not as a module-level constant. This is one of the three
  `ADDED` deviations: the source document builds `HEADERS` at import time, which means
  `import collectors.collect_github` itself raises `KeyError` if no token is set —
  breaking every test and CI run that merely imports the module without needing to
  actually collect anything.
- **`_get(url, params)`** — one authenticated GET, increments a call counter, checks
  rate-limit headers and sleeps if needed, raises on HTTP error.
- **`_paged(url, params)`** — generator that walks GitHub's pagination (100 items/page,
  stop when a page comes back short).
- **`_failure_log(owner, repo, run_id)`** — the second `ADDED` piece. Downloads a failed
  run's logs (GitHub returns them as a zip archive) and flattens the first 20 files'
  text into one string. **Only called for `conclusion == "failure"`** — a success has no
  error to classify, and the logs endpoint is expensive, so this is deliberately never
  called for passing runs. Missing logs (they expire after 90 days) are caught and
  treated as `None`, which the classifier then reports as `"empty"`/`"unclassified"`
  rather than crashing.
- **`collect_repo(conn, owner, repo, student_id, assignment_id)`** — the main routine.
  Fetches commits incrementally (optimizations 1–2), fetches workflow runs, and —
  **third `ADDED` piece** — calls `classify_error()` on every failed run's log at
  collection time, storing `(error_class, concept_id)` directly into the row being
  inserted. This matters: the source document *defines* `classify_error()` in
  `error_classifier.py` but its own collector code **never calls it** — a gap that, if
  transcribed literally, would leave `concept_id` permanently `NULL` and therefore
  `variables/mastery.py`'s replay query (which filters on
  `concept_id IS NOT NULL AND concept_id <> 'unclassified'`) would never see any events,
  and mastery would stay empty forever. This was caught and fixed during transcription.
- **`collect_all(conn, repos)`** — iterates a list of repo dicts, isolates failures per
  repo (optimization 7), returns `{"ok": count, "failed": [...], "stats": summary}`.
- **`Stats` (added dataclass)** — counts `api_calls`, `detail_calls`,
  `commits_upserted`, `runs_upserted`, and the list of classifications made, so that
  `BUILD_PLAN` 1.4's requirement — "confirm the second run makes almost no API calls" —
  can be answered with an actual printed number instead of an impression. `.summary()`
  also reports the classifier's match rate (see §6).

### 5.3 Entry point: `scripts/collect.py`

Reads `GITHUB_TOKEN` from the environment, loads `config/roster.yaml` (see §7.6), builds
one `{owner, repo, student_id, assignment_id}` **dict** per assignment (matching
`collect_repo`'s keyword signature exactly), opens one connection via `system.db.connect()`,
and calls `collect_all(conn, repos)` — the same pattern `dags/vdel_pipeline.py`'s `_collect`
task already uses. Prints the stats summary, exits non-zero if any repo failed.

**Fixed 2026-08-19.** This previously imported and called a `collect(token, targets)`
function that never existed anywhere in the repo — `collectors/collect_github.py` only
ever defined `collect_repo(conn, ...)` / `collect_all(conn, repos)`, matching
`VDEL_Modules_1_2_Build.md` Part D exactly (`spec-verifier`: MATCH). `python -m
scripts.collect` failed at the import line, before `main()` could even run, while the DAG's
`_collect` task called the collector correctly the whole time. Caught by running
`spec-verifier` against the module document rather than trusting the code; fixed by making
this script mirror the DAG's already-correct call, not by changing `collect_github.py`.

---

## 6. The error classifier (`collectors/error_classifier.py`)

**Purpose:** map a CI failure's log text to `(error_class, concept_id)`. Called "the
load-bearing risk" in the source document, because it feeds **three** variables
(Mastery, Error Response, Error Frequency) — a misclassification doesn't just mislabel
one number, it silently corrupts a chain of downstream beliefs about a student.

### 6.1 The governing rule: never force a wrong guess

```python
RULES = [
    (r"ambiguous column",                       "spark.joins"),
    (r"cannot resolve .* given input columns",  "spark.df_basics"),
    (r"AnalysisException.*group by",            "spark.aggregation"),
    (r"is neither present in the group by",     "sql.aggregation"),
    (r"cartesian product|cross join",           "spark.joins"),
    (r"OutOfMemory|GC overhead",                "spark.partitioning"),
    (r"KeyError|IndexError",                    "py.data_structures"),
    (r"SettingWithCopyWarning",                 "py.pandas"),
    (r"SyntaxError|IndentationError",           "py.errors_debugging"),
    (r"AssertionError",                         "py.testing"),
]
```

`classify_error(log_text)` walks this list **in order** — first match wins, so the
ordering is part of the specification, not incidental (more specific patterns are placed
before more general ones deliberately, e.g. group-by-shaped AnalysisException before a
bare exception check). If nothing matches, it returns `("unmatched", "unclassified")`;
an empty/`None` log returns `("empty", "unclassified")` — two different reasons for the
same practical outcome, so a coverage report can later distinguish "we had no log to
read" from "we had a log and no rule fit it."

**`"unclassified"` is not a concept id.** Every consumer of `concept_id` — most
importantly `compute_features.py`'s mastery query — explicitly excludes it. An
unmatched error contributes to the *frequency* count (V6) but moves **no** mastery
score. This is invariant 10 (§8) and it exists because a wrong specific guess is worse
than an honest "don't know": it would silently drag down (or, worse, prop up) a mastery
estimate for a concept the student's actual mistake had nothing to do with.

### 6.2 `match_rate(classifications)` — an addition, not in the source document

The source document and `BUILD_PLAN` both require the classifier's match rate to be
logged, but the document doesn't provide the helper function. Added here:
`matched / total`, rounded to 3 places, `0.0` on an empty list. Deliberately **not**
something to optimize by loosening rules — a low match rate is meant to be reported as a
finding ("the taxonomy doesn't yet cover most of what students actually break"), not
inflated by making a rule vaguer until it matches more logs.

### 6.3 What was explicitly *not* built: tiered LLM classification

The source document's optimization table lists a sixth flaw/fix: "LLM classifier on
every failure → Tiered (rules → LLM) + signature cache → thousands of calls become
dozens." **This tier does not exist in the current code.** Only the rule-based v1
classifier is implemented. This is intentional and matches `CLAUDE.md`'s scope table:
LLM-anything is out of scope until M3 (LLM Gateway) exists, and `CLAUDE.md` invariant 3
says every LLM call must go through `system/llm.py`, which doesn't exist yet either. If
you're asked to "improve classifier coverage," the sanctioned next step per the source
document is "extend to your ~15 most common real failures" (i.e., add more rules from
observed logs) — **not** to reach for an LLM prematurely.

### 6.4 Concept IDs are schema

`config/concepts.yaml` (§7.6) currently contains 19 concept ids, chosen to be exactly
the set that is *attested* somewhere in the four source documents (in this rule table,
in the Code Agent's anti-pattern examples in Module 3-9, or in Sara's worked example).
The design document says "~25 curriculum concepts" but never enumerates the full list —
so 19 of ~25 is a known, deliberate gap, not an oversight. **Renaming or removing a
concept id breaks history** — it appears in this rule table, in `learner_features.mastery`
JSON keys, in `kt_params`, in `items.concept_ids`, and (eventually) in agent prompts. A
test (`test_classifier.py::test_every_rule_maps_to_a_concept_in_the_taxonomy`) fails
loudly if the classifier ever references an id that `concepts.yaml` doesn't define, so
the two files can't silently drift apart.

---

## 7. The seven variables (`variables/*.py`) — and the code built on them

> §7.1–§7.7 are the variables themselves. §7.8–§7.10 are what consumes them:
> `compute_features.py`, the DAG, and now `memory/memory.py`. The section numbering is
> kept as-is rather than promoting §7.10 to a top-level section, because `§11` (the
> verification block) is cited from `DEVELOPMENT_MAP.md`, `HANDOFF.md`, `STATUS.md` and
> `SETUP.md`, and renumbering would invalidate dated evidence in `STATUS.md`.

**This is the mathematical core of the project.** Every module here is a
**verbatim transcription** of `VDEL_Modules_1_2_Build.md` Part B — the formulas,
constants, clamps and even variable names are the document's, not invented. Each
module's docstring says so explicitly and cites its source paragraph. Every function is
a **pure function**: no I/O, no database access, no globals mutated outside an explicit
state object passed in. This is deliberate (`BUILD_PLAN` 1.6: "`mastery.update()` must
be a pure function... so it is unit-testable") — it's what makes `tests/test_mastery.py`
and `tests/test_variables.py` able to check formulas in complete isolation from the
database.

**Universal design fact worth internalizing:** none of these six implemented variables
return values in a uniform shape. V1 returns a rich per-concept dict from a stateful
estimator class. V2 returns a dataclass. V3–V6 return plain dicts with different keys.
This is intentional — the source document gives each variable the shape that answers
*its own* question, and imposing one uniform contract across all seven would mean
rewriting the documented interfaces for no benefit. Don't "normalize" these without
checking the source document first.

### 7.1 V1 — Concept Mastery (`variables/mastery.py`)

**What it answers:** "does this student understand concept X, right now, with how much
confidence?" This is the spine of the whole system — read (eventually) by the Code Agent
for tone, the Pedagogy Agent for trajectory, the weakness inventory, and the coach for
picking which "rung" of help to offer.

**Model: Bayesian Knowledge Tracing (Corbett & Anderson, 1994) + item-difficulty
conditioning (KT-IDEM, Pardos & Heffernan, 2011) + a Beta-Bernoulli companion posterior
for calibrated uncertainty.**

Why BKT and not the two alternatives that were considered and rejected:
- **EWMA** (`M ← α·o + (1−α)·M`) was the original baseline. Rejected: it's not a
  probability, has no noise model, ignores item difficulty, has no learning dynamics,
  and gives no real uncertainty estimate. It was tried and explicitly dropped.
- **Deep Knowledge Tracing** (Piech et al., 2015) was considered and rejected: needs
  thousands of sequences to train (this system has, at most, one student's worth of
  data right now), and is a black box — which directly violates the governing sentence
  in §0. The document cites Gervet et al. (2020) showing BKT-family models match or beat
  deep models specifically in low-data regimes, which is this project's actual regime.

**The published equations** (transcribed exactly):

```
Evidence step (Bayes), if the attempt was correct:
    p(L|c)  = p(L)(1−S) / [ p(L)(1−S) + (1−p(L))G ]

Evidence step, if the attempt was incorrect:
    p(L|¬c) = p(L)S     / [ p(L)S     + (1−p(L))(1−G) ]

Learning step (applied after the evidence step, regardless of outcome):
    p(L)    = p(L|obs) + (1 − p(L|obs))·T

KT-IDEM item-difficulty conditioning (d = normalized item difficulty, 0=easy..1=hard):
    G_item  = G·(1−d)
    S_item  = S + (0.40−S)·d·0.5

Testable prediction (externally falsifiable — this is the whole point of choosing BKT):
    P(correct_next) = p(L)(1−S) + (1−p(L))G
```

Where `L` = "knows the concept," `G` = guess probability (answering correctly without
knowing), `S` = slip probability (answering incorrectly despite knowing), `T` =
probability of learning at each opportunity.

**Cold-start defaults** (`BKTParams`): `p_l0=0.30, p_t=0.15, p_guess=0.20, p_slip=0.10`
— literature-grounded priors, meant to be replaced by EM-fitted values once ≥~100
sequences per concept exist (tracked via `kt_params.fitted`).

**Identifiability guard** (Beck & Chang, 2007, cited by name in the document): `guess`
is clamped to `[0.01, 0.45]`, `slip` to `[0.00, 0.45]`. Above roughly 0.5, the model
becomes statistically unidentifiable — "always guessing" and "always knowing" start
fitting the same observed data equally well, and the model can no longer distinguish
them. `BKTParams.guarded()` enforces this on every use.

**Uncertainty: a Beta-Bernoulli posterior with a Jeffreys prior.** Each `MasteryState`
carries `a` and `b`, both starting at **0.5** (not 0, not 1 — a Jeffreys prior), and
incremented by 1 on each correct/incorrect observation respectively.
`credible_interval(0.90)` computes the 90% interval via `scipy.stats.beta.ppf` if scipy
is available, falling back to a normal approximation
(`mean ± 1.645·sqrt(variance)`) if it isn't — so the module degrades gracefully rather
than hard-failing if scipy is missing. `confidence = 1 − min(1, sqrt(variance)/0.35)` —
this exact formula, including the `0.35` constant, is the document's.

**`MasteryEstimator`** — the class that actually gets used. One instance per student,
holding a `dict[concept_id → MasteryState]`. `.update(concept, correct, item_difficulty)`
does one BKT step for that concept and returns a rich dict (`p_mastery`,
`p_mastery_before`, `p_correct_next`, `n_obs`, `confidence`, `ci90`, `variance`, `trend`,
`item_difficulty`, `eff_guess`, `eff_slip`). `.snapshot()` returns the compact form
that's actually stored in `learner_features.mastery` — per concept: `p_mastery`, `n`,
`confidence`, `ci90`, `trend`. **Every mastery value ships with `n`** (invariant 8, §8)
— `0.9 from n=2` and `0.9 from n=20` are treated as very different claims by any
consumer that reads this field correctly.

`trend()` — `"up"` if the retained history (last 6 values) rose by more than 0.03,
`"down"` if it fell by more than 0.03, `"flat"` otherwise (or if fewer than 2 points
exist). This ±0.03 threshold is a **reporting** threshold — below it, movement is
treated as noise not worth surfacing to a student or coach.

**`DifficultyEstimator`** — a separate small class: `difficulty(item_id) = 1 −
Beta(2,2)-smoothed cohort pass rate` on that item. This is what should eventually
populate `items.difficulty` as a cohort forms; right now, with a cohort of one student,
`compute_features.py` falls back to a neutral `0.5` (§7.8).

### 7.2 The reproducibility check against Sara — and what it found

**Sara** is the hand-computed synthetic worked example that appears throughout the
design document as the canonical illustration. Her Assignment A2: a join error (fixed in
4 hours) and an aggregation-grain error (recurred twice before finally passing). The
design document's Code Agent working-memory example quotes her mastery slice as:

```
spark.joins: 0.47 (n=2)   ·   spark.aggregation: 0.40 (n=3)
```

`tests/test_sara.py` replays the documented event sequences through the transcribed
`MasteryEstimator` and checks these two numbers:

- **`spark.aggregation` reproduces exactly.** Sequence `[fail, pass, fail]` at
  `item_difficulty=0.4` gives the trajectory `0.30 → 0.211 → 0.705 → 0.407` — a final
  value of 0.407, matching 0.40 within rounding, and its *shape* (rising then declining)
  matches the design document's own narrative elsewhere ("aggregation declined 0.5 →
  0.40 over A2," "unresolved at session end").
- **`spark.joins` does not reproduce, and a brute-force search shows it cannot.** The
  narrative for joins is unambiguous — "fixed in 4h" means the sequence is
  `[fail, pass]`. Sweeping `item_difficulty` across its full `[0, 1]` range with that
  exact sequence produces mastery values from **0.591 to 0.964** — the entire reachable
  range sits *above* 0.47 at every difficulty. 0.47 is only reachable at n=2 via the
  *opposite* sequence, `[pass, fail]`, at difficulty ≈0.35 — which contradicts "the
  error was fixed."

This is recorded as a **strict `xfail`** in `test_sara.py`
(`test_sara_joins_matches_the_hand_computation`), plus a companion test
(`test_sara_joins_is_unreachable_across_every_difficulty`) that pins the finding: if a
future change to the formula or its parameters ever makes 0.47 reachable under the
documented sequence, that companion test starts failing — which is the intended signal
to go re-examine the xfail rather than let the discrepancy silently resolve itself
unnoticed. **This was not "fixed" by tuning parameters to hit the target number** —
that would risk quietly encoding a wrong formula just to match one anecdote. It is an
open question for whoever wrote the worked example: **is 0.47 a transcription slip, or
was the joins slice taken at some different point in the sequence than "after both
events"?** Until answered, treat the joins number in the design document as unverified
and the aggregation number as verified.

### 7.3 V2 & V3 — Engineering Discipline / Effort Regulation (`variables/habits.py`)

These two variables come from deliberately **splitting** an earlier, vaguer "coding
habits" idea into two distinct constructs, following Zimmerman's Self-Regulated
Learning framework: **discipline is a cognition/skill signal** (can they write clean,
tested code?), **effort regulation is a behavior signal** (do they work steadily or
cram?).

**V2 — Engineering Discipline.**
- `cleanliness(lint_violations, changed_loc)` = `1 − min(1, violations_per_100_loc / 10)`.
  Returns `None` if `changed_loc <= 0` — explicitly refusing to compute a rate over zero
  lines rather than dividing by zero or silently returning something misleading.
- `testing_signal(state)` — a lookup: `{"wired": 1.0, "present": 0.5, "absent": 0.0}`.
  "Wired" means tests exist *and run in CI*; "present" means they exist but aren't
  necessarily run; "absent" means none exist.
- **The composite is gated by Cronbach's alpha** (Cronbach, 1951; DeVellis, 2016).
  `cronbachs_alpha(item_matrix)` needs **at least 10 students'** worth of rows to
  compute at all (returns `None` below that) and the composite score itself is only
  reported if `alpha >= 0.70` — otherwise the function reports the individual
  components (`cleanliness`, `testing`) with `composite=None` and `composite_valid=False`.
  This is the document's own honesty mechanism: **an unjustified composite is worse than
  no composite**, because averaging two things together implies they measure a common
  underlying construct, and that claim needs statistical support before it's made. Right
  now the "cohort" is one student (`CLAUDE.md` §2), so `cohort_alpha` is always passed as
  `None` and the composite is always `None` — this is the correct, honest behavior, not
  a bug, and it will start reporting a real composite automatically the moment a real
  cohort with ≥10 students exists.

**V3 — Effort Regulation.**
- **Regularity is measured via burstiness** (Goh & Barabási, 2008), specifically chosen
  over the more obvious "coefficient of variation" (`σ/μ`) baseline because CV is
  numerically unstable when the mean gap is small — the source document flags this
  explicitly as a fixed flaw. Burstiness: `B = (σ − μ)/(σ + μ)`, which is bounded to
  `[-1, 1]` by construction (`-1` = perfectly periodic, `0` = random/Poisson, `+1` =
  maximally bursty). Mapped to a `[0, 1]` "regularity" score via `(1 − B) / 2` — no
  invented divisor needed, because the input is already bounded.
  `burstiness_regularity()` **explicitly refuses to compute anything from a single
  gap** (returns `None` if fewer than 2 gaps are given) — the document's comment is
  blunt: "do NOT fabricate from 1 gap."
- **Procrastination (`release_to_first_commit_h`) is tracked but never scored.** It's
  reported in the output dict for a coach to see, but deliberately excluded from any
  score — a slow start by itself isn't treated as a failure (someone might be reading
  the assignment carefully, or juggling other work); only the pattern of gaps
  *between* commits is scored.
- Pedagogical grounding cited for why regularity/spacing matters at all: the spacing
  effect (Cepeda et al., 2006) — spaced-out engagement is better for retention than
  cramming, independent of anything to do with grading.

### 7.4 V4 — Learning Pace (`variables/pace.py`)

**What it answers:** is this student fast or slow to reach a passing solution,
*relative to their peers on the same assignment* — and separately, is the *assignment
itself* unusually hard for the whole cohort (a signal about the assignment, not the
student)?

**The baseline flaw this fixes: survivorship bias.** Computing "how long does it take to
pass" only from students who *have* passed silently drops everyone currently stuck —
exactly the students this signal should be most informative about. The fix: **survival
analysis framing.** Non-passers are kept as **censored lower bounds** rather than
excluded. (`learning_pace(..., censored=True)`: their score is capped at exactly `0.5`
— never higher, because a censored student cannot be shown to be *fast*, only "at least
this far along, still unresolved" — and their `elapsed_h` is **excluded from the cohort
median calculation itself**, which is precisely the fix for the survivorship bias: the
median that everyone else is compared against no longer secretly excludes the students
struggling the most.)

**Formula:** `score = clamp(0.5 − 0.25·log2(ratio), 0, 1)`, where `ratio =
time_to_pass_h / cohort_median_h`. Using `log2` specifically makes "twice as fast as the
cohort" and "twice as slow" perfectly symmetric around the 0.5 midpoint — verified in
`test_variables.py`: `ratio=0.5 → score=0.75`, `ratio=2.0 → score=0.25`, and
`0.75 − 0.5 == 0.5 − 0.25` exactly.

**`cohort_censoring_rate(n_not_passed, n_total)`** — a separate, assignment-level
signal (not per-student): if most of the cohort hasn't passed yet, that's a signal the
*assignment* may be too hard or unclear, distinct from any individual student's pace.

**Upgrade path noted but not built:** Cox proportional hazards (Cox, 1972) via the
`lifelines` package, once real cohort data exists — this file is a placeholder for that,
not the final form.

**Operational reality right now: n=1 makes this variable structurally degenerate.**
`compute_features.py`'s `_pace()` computes the cohort median from all *passers on this
specific assignment*. With one student in the system, that "cohort" is the student
themselves — so `cohort_median_h` equals their own `time_to_pass_h`, `ratio` is
always exactly `1.0`, and `score` is always exactly `0.5`. **This is not a bug and not a
real measurement — it is the formula correctly reporting "undefined until a real cohort
exists."** `compute_features.py` labels this explicitly by including `cohort_n` in the
stored JSON (`cohort_n: 1` means "don't trust this score as a real pace signal yet"),
and if there are *zero* passers at all yet, `_pace()` reports `score: None` with a
`"no cohort passers yet; pace undefined"` note rather than dividing by zero or
fabricating a number.

### 7.5 V5 — Error Response (`variables/error_response.py`)

**What it answers:** not *how many* errors a student hits, but *what they do about it* —
this is "the metacognitive heart of the set" per the source document, because it's what
separates a bold experimenter (many errors, but resolves all of them, improving over
time) from a student who's actually stuck (many errors, resolving nothing).

**Grounding:** Jadud's Error Quotient (2006) and the Watwin score (Watson et al., 2013)
for the base time-to-fix / resolution-ratio signal, plus a second interpretive layer
distinguishing **wheel-spinning** (Beck & Gong, 2013) from **productive failure**
(Kapur, 2008) — same raw error count, opposite pedagogical meaning, and the distinction
is what should drive which intervention (if any) a coach offers.

**Formula:**
```
ttf_score          = clamp(1 − median_time_to_fix_h / 24, 0, 1)
resolution_ratio    = resolved_errors / total_errors   (or 1.0 if total_errors == 0)
base                = mean(ttf_score, resolution_ratio)

wheel_spinning  = (concept_opportunities >= 8) AND (current_mastery < 0.6) AND (mastery_slope <= 0)
productive      = mastery_slope > 0.03

score = base − 0.25   if wheel_spinning
      = base + 0.15   elif productive
      = base           otherwise
```

All three wheel-spinning conditions must hold simultaneously — **verified explicitly**
in `test_variables.py::test_wheel_spinning_needs_all_three_conditions`, which checks
that relaxing any single one of the three flips the flag off. The productive-vs-spinning
split is tested directly too
(`test_productive_failure_and_wheel_spinning_pull_opposite_ways`): identical error
counts and identical time-to-fix, differing only in mastery slope sign, land on opposite
sides of the flag and produce meaningfully different scores.

### 7.6 V6 — Error Frequency (`variables/error_frequency.py`)

**What it answers:** the raw rate and per-concept breakdown of errors. The source
document is explicit that raw counts are **weak as a standalone predictor** — Jadud
found they predict little on their own — so this variable's real job isn't its `score`
so much as its **`by_concept` histogram**, which is what feeds back into V1 (which
concepts to even attempt to update mastery for) and the **recurrence rule**.

**Formula:**
```
fail_ratio = failed_runs / total_runs   (0.0 if total_runs == 0)
per_100    = errors / (changed_loc / 100)   (0.0 if changed_loc == 0)
score      = 1.0 − clamp(mean(fail_ratio, min(1.0, per_100 / 5.0)), 0, 1)
```

**`recurrence_check(error_class_counts_this_assignment)`** — the same error class
occurring **≥2 times within one assignment** immediately flags that error class for a
weakness to be opened. This aligns with Repeated Error Density (Becker, 2016). **Wired as
of M2 piece 3:** `memory/memory.py`'s `apply_recurrence_rule` calls this function directly
rather than re-implementing the threshold — see §7.10. (This session's first attempt at
piece 3 missed this seam and re-derived the rule at concept granularity instead;
`spec-verifier` caught it, corrected in `DECISIONS.md` D-011.)

### 7.7 V7 — Help-Seeking: intentionally absent

There is no `variables/help_seeking.py` and none should be added yet. The data source
for this variable — a log of when and how a student asks the coach for help — **does
not exist**, because the coach doesn't exist (it's Module 7). `learner_features.help_seeking`
is a nullable JSONB column that's always written as `NULL` by `compute_features.py`
right now (§7.8). This is documented as a "v2 seam" in the source material, grounded in
Aleven et al.'s (2003/2006) help-seeking-in-intelligent-tutoring-systems literature for
whenever it is built. **Do not build a placeholder formula for this** — an invented
help-seeking score would be exactly the kind of fabricated number `CLAUDE.md` explicitly
prohibits ("Never invent numbers... Unknown → TODO(verify)").

### 7.8 `features/compute_features.py` — wiring the six variables to the database

The source document's own version of this file is **explicitly a skeleton** — its
comments literally say "Query details elided for brevity" and only mastery and effort
are actually implemented in it, with comments like `# 3..6: pace / error_response /
error_frequency / discipline (call the respective Module-1 functions with queried
inputs)` standing in for the rest. **This repository's `compute_features.py` fills in
every one of those elided queries** — the six `_mastery`, `_effort`, `_discipline`,
`_pace`, `_error_stats` (covers both V5 and V6, since they read the same run history)
helper functions are additions built to call the documented formula functions with real
SQL-sourced inputs. None of the formulas themselves live in this file — every number
that reaches a variable function comes from a query against `raw_commits` /
`raw_workflow_runs` / `assignments` / `items`.

**Two things worth understanding deeply because they're easy to get wrong if this file
is ever modified:**

1. **`computed_at` is the student's data watermark, not `now()`.**
   `watermark(cur, student_id)` returns `max(committed_at, started_at)` across both raw
   tables for that student — i.e., the timestamp of their single most recent raw event —
   and that value is what gets written into `learner_features.computed_at`, which is
   part of the table's primary key `(student_id, computed_at)`. The consequence: running
   `compute_features.run()` twice in a row with **no new raw activity in between**
   computes the exact same `computed_at` both times, so the second `INSERT ... ON
   CONFLICT (student_id, computed_at) DO UPDATE` targets the *same row* and rewrites it
   with identical values — net effect, nothing changes. This is exactly what the M1
   Definition of Done requires: "a deliberate re-run changes nothing." If `computed_at`
   had instead defaulted to `now()` (as the source document's own INSERT statement,
   taken completely literally, would do — it lists no `computed_at` value at all,
   implying the column default `now()`), every re-run would silently create a brand-new
   row, and the idempotency requirement would be unsatisfiable *by construction*, no
   matter how careful the rest of the logic was. `tests/test_pipeline_integration.py::
   test_rerunning_changes_nothing` checks this end-to-end against a real database.

2. **`dirty_students(cur, last_run_iso)` is the incremental-recompute optimization**
   (source document's "Flaw 5": don't recompute students with no new activity — it's
   pure waste, since unchanged inputs produce unchanged outputs). It's a `UNION` of
   "students with a commit newer than `last_run_iso`" and "students with a workflow run
   newer than `last_run_iso`." `run()` defaults `last_run_iso` to the Unix epoch
   (`"1970-01-01T00:00:00Z"`) when called with no argument, which means "everyone with
   any activity ever" — the Airflow DAG (§7.9) instead passes the actual previous run's
   timestamp, so daily runs only touch students who did something that day.

**What each helper does, briefly** (all read-only SQL against the raw tables, feeding
the pure formula functions from `variables/`):

- `_mastery()` — pulls `(concept_id, conclusion)` pairs in timestamp order, **excludes
  `concept_id IS NULL` and `concept_id = 'unclassified'`** (this is invariant 10, §8,
  enforced at the SQL level — a literal string in a `WHERE` clause that a dedicated test,
  `test_classifier.py::test_unclassified_errors_are_excluded_from_mastery_by_the_query`,
  checks is still present in the source, precisely because it would be easy to silently
  lose this filter in a future refactor), looks up each concept's cohort-derived
  difficulty via `_item_difficulty()`, and replays the sequence through a fresh
  `MasteryEstimator`.
- `_item_difficulty(cur, concept_id)` — averages `items.difficulty` across items tagging
  this concept, but only where `n_cohort_obs > 0`; falls back to `NEUTRAL_DIFFICULTY =
  0.5` otherwise (§7.4's "n=1 cohort" situation applies here too — there's no real cohort
  difficulty signal yet).
- `_effort()` — pulls ordered commit timestamps for the gap list, plus a separate query
  computing the *first* commit's lag after the *earliest* assignment's `released_at`
  (the "release-to-first-commit" input `effort_regulation()` wants but doesn't score).
- `_discipline()` — **cannot currently measure `cleanliness`** (lint violations over
  changed LOC) because M1 never checks out a student's actual code — it only has GitHub
  metadata, not a working tree to run `ruff`/`sqlfluff` against. So `lint_violations=0,
  changed_loc=0` is passed, which `cleanliness()`'s own guard turns into `None` (§7.3) —
  correctly representing "not measured," not "measured as perfect." `tests_state` *is*
  measurable now, though: any workflow run existing for the student means CI is "wired."
  This is explicitly flagged as needing the Code Agent's deterministic tools (M4) to
  actually fill in `cleanliness`.
- `_pace()` — see §7.4's full explanation of the cohort-median and censoring logic.
- `_error_stats()` — shared pass for V5 and V6 since both read the same ordered run
  history: computes per-failure time-to-fix (first success strictly after that failure
  timestamp), the resolved count, the per-concept failure histogram, and — for the
  *worst* concept (most failures) — looks up its mastery-trajectory slope from the same
  `MasteryEstimator` instance used by `_mastery()` (`_mastery_slope()` reads the
  estimator's retained 6-point history) to feed V5's wheel-spinning/productive-failure
  determination.

`run(last_run_iso=...)` ties it together: find dirty students, compute their payload,
upsert into `learner_features` with `Json(...)` wrapping every dict (using
`psycopg2.extras.Json`, **not** `str(dict)` — the latter produces a Python repr with
single quotes, which is not valid JSON and would either be rejected by the `JSONB`
column type or silently mangled; this was a bug in an earlier, pre-transcription version
of this file).

### 7.9 The Airflow DAG (`dags/vdel_pipeline.py`)

`collect → compute_features → update_profiles`, `@daily`, `catchup=False` (backfilling
this specific pipeline would just re-collect the same GitHub history, which is
pointless — Airflow's backfill semantics don't apply usefully here),
`max_active_runs=1` (two concurrent runs would race on writes to the same raw tables).
`update_profiles` is no longer a no-op stub (D-034): it calls
`memory.memory.Memory.sync_features_ref` for every student with a `learner_features` row,
so the live profile's `features_ref` pointer stops falling behind what
`rebuild_from_traces` re-derives. The `_collect` task loads real repos from
`config/roster.yaml` (via `scripts.seed_data.load_roster()`) rather than the source
document's literal placeholder (`collect_all(conn, repos=[])`, an empty list that would
collect nothing) — this is one of two small deviations from the document, both marked
in the file's own docstring, the other being timezone-aware `start_date` (Airflow
requires this; the source document's `datetime(2026, 1, 1)` is naive and would be
rejected).

### 7.10 `memory/memory.py` — the only door (M2, complete)

**Status: all four pieces.** `log_trace`, `get_profile`, `snapshot_profile`, the
transaction machinery, `update_mastery`, `rebuild_mastery_from_traces`, `open_weakness`,
`apply_recurrence_rule`, `link_intervention` and the broad `rebuild_from_traces`. The
30-day staleness transition is deliberately *not* here — it depends on elapsed time
regardless of new events, so it belongs to a scheduled job, not to the fast path or a
rebuild.

Transcribed from `VDEL_Modules_3_9_Build.md` B.5 with **three deliberate deviations**,
each stated in the module's own docstring rather than left to be discovered:

1. **No held connection.** B.5 keeps `self.conn` for the object's lifetime. `system/db.py`
   exists precisely because that pattern produced a collector run with no transaction
   boundary, and its docstring makes it the single place `psycopg2.connect()` is called.
   `Memory` is therefore **stateless** — construct one, share it, nothing to close.
2. **Every public method takes an optional `conn`.** Passing one joins the caller's
   transaction; omitting it opens and commits its own (`_session` is the context manager
   that decides). This exists for piece 2: the fast path must write the profile **and**
   its trace atomically, because a crash between them would leave a belief with no audit
   record — the one state event sourcing must make impossible. B.5 commits them separately.
3. **`__init__` takes no DSN**, because `db.dsn()` already owns that job.

**The trace vocabulary (`ACTORS`, `KINDS`) is validated strictly**, and is built as the
*union* of its two authorities because neither is complete alone: `Modules_3_9` B.4 omits
`error_event` (which `CLAUDE.md` §6 lists and `smoke_test.py` writes), while `CLAUDE.md`
§6's list omits `ci_run`, `profile_update` and `session_summary` (which B.5 and B.6
write). The strictness is the point — a typo'd kind (`ci-run` for `ci_run`) would insert
cleanly and then sit silently outside the replay set, which is exactly how a profile stops
being reconstructible. Adding a kind is *meant* to require a code change, so the replay
set gets updated in the same breath.

Two smaller properties worth knowing, both pinned by tests:

- `get_profile` returns a **freshly built** dict for an unknown student, never a shared
  module constant. Callers mutate what they get back (piece 2 does
  `profile["mastery"][concept] = ...`), so a shared default would silently accumulate one
  student's beliefs into every other student's.
- `features_ref` is deliberately **not** in `get_profile`'s return. B.5 doesn't read it, and
  though `Memory.sync_features_ref` now writes it (D-034), no caller reads it back through
  `get_profile` yet either; it stays out of the contract until one does, rather than
  appearing as a key most callers have no use for.

#### Piece 2 — mastery by replay (the D-007 fix)

`update_mastery(student_id, concept)` **takes no outcome argument.** The evidence is
whatever is already in `traces`, so a caller logs the attempt first (a `ci_run` trace
carrying `conclusion` and `item_difficulty`) and then asks memory to recompute. B.5 instead
passed the outcome in and folded it onto state read back from the profile — restoring only
`p_mastery` and `n_obs` of `MasteryState`'s five fields, which dropped the Beta posterior
and froze `confidence` at 0.286 no matter how much evidence accumulated (`DECISIONS.md`
D-007).

Two properties fall out of taking the evidence from the log, and both are tested:

- **Idempotent** — recomputing is not a second attempt. An outcome-taking signature cannot
  have this property.
- **Identical to a rebuild** — `update_mastery` *is* `rebuild_mastery_from_traces`
  restricted to one concept, the same function rather than a parallel implementation. This
  is what makes the M2 DoD hold by construction instead of because two code paths agree.

**`MASTERY_TRACE_KINDS`** names what counts as evidence (`ci_run` today). It is paired with
`NON_MASTERY_KINDS`, a dict of every *other* kind and the prose reason it is excluded, and
a test asserts the two together cover `KINDS` exactly. So a kind cannot be added without a
decision being made about whether it moves mastery. `verdict` currently sits in the
excluded set: an agent verdict *is* evidence, but its payload is a per-criterion 0/2/4
rubric rather than a pass/fail, and the rubric-to-BKT-outcome mapping has not been decided
— adding it without that mapping would silently score every verdict as a failure.

**Only `success` and `failure` are evidence.** GitHub's `conclusion` vocabulary also
includes `cancelled`, `skipped`, `timed_out` and `neutral`; those are skipped rather than
coerced, because a cancelled run is a fact about CI infrastructure, not about what the
student knows. B.5's `== "success"` scored all of them as failures.

Two smaller mechanics: replay is ordered by `(ts, trace_id)` because `ts` alone is not a
total order and BKT is order-dependent, so a tie would otherwise replay in whatever order
the planner chose and the rebuild would not be reproducible; and the profile write is a
`jsonb ||` merge **in SQL**, not a read-modify-write in Python, so two concurrent updates
on different concepts cannot silently discard each other.

**Testing note (`tests/test_memory.py`).** Every test drives its own connection and rolls
it back, because `traces` is append-only: the Postgres RULEs make `DELETE` a silent no-op,
so a test that *commits* a trace cannot clean up after itself and would pollute the
database permanently. That is the invariant working as designed, not an obstacle — so the
self-managed-transaction path is exercised by substituting `db.connect`, not by letting it
commit.

#### Piece 3 — the recurrence rule, `open_weakness`, `link_intervention`

B.5 gives `open_weakness` but nothing that decides *when* to call it — the recurrence rule
had to be built, not transcribed. **First attempt got it wrong** (see the correction
below); the version that shipped:

- **What "recurring" means.** `apply_recurrence_rule` calls
  `variables.error_frequency.recurrence_check` directly — one implementation of the
  ">=2" threshold, not a second copy re-derived in `memory.py` (the same reasoning D-007
  applied to mastery). `recurrence_check` counts by **`error_class`** (the raw classifier
  string, e.g. `"ambiguous column"`), not concept, scoped to one **assignment**
  (`traces.assignment_id`, not a calendar span). A concept failing once in each of two
  different assignments does not trigger this rule; nor does the same concept failing
  once each via two *different* error classes — Becker's Repeated Error Density signal is
  the same mistake recurring, not merely the same topic area. The resulting weakness is
  still tagged by concept (the schema has no `error_class` field); only the trigger's
  counting key is `error_class`.
- **How a weakness gets its id.** `w-{trace_id}` of the trace that records opening it, not
  B.5's `f"w-{len(weaknesses)+1:03d}"` — two concurrent opens could compute an identical
  counter value; `trace_id` is a Postgres `BIGSERIAL`, collision-free by construction.
  `DECISIONS.md` D-010. Nothing downstream reads the format: `reflection.py`'s validation
  only checks membership in `existing_weakness_ids`.

**The correction (`DECISIONS.md` D-011, superseding D-009).** The first attempt read
"error class" as concept, reasoning from the weakness schema's `"concept"` key and
`BUILD_PLAN 2.2`'s wording. `spec-verifier` found that count of authorities was wrong:
`variables/error_frequency.py`'s `recurrence_check` already existed, was already tested
and cited (Becker 2016), and this document's own §7.6 already named it as *"the seam [M2]
will plug into."* Demonstrated concretely: `classify_error()` maps both `'ambiguous
column'` and `'cartesian product|cross join'` to the same concept (`spark.joins`) but they
are different `error_class` strings — under the first attempt's reading, one occurrence of
each would open a weakness; under the corrected reading, it does not. Real behavior, not
cosmetic — pinned by `test_two_different_error_classes_on_the_same_concept_do_not_recur`,
and reproduced with a mutant that faithfully replays the original bug's exact triggering
condition rather than a generic "delete some code" mutant.

`apply_recurrence_rule(student_id, assignment_id, concept)` is **idempotent** — safe to
call after every failure, not just the one that first crosses the threshold — because it
dedups against any currently-**open** weakness for the concept. Dedup is against `open`
specifically, not `closed`/`escalated`/`stale`: a concept recurring after its earlier
weakness closed is new evidence and gets a new weakness, not silence.

`link_intervention` **raises on an unknown `weakness_id`** rather than B.5's silent
no-op (its loop falls through on no match and still re-writes an unchanged array). Both
the weakness append and the intervention link happen as one atomic JSONB update in SQL
(`_append_weakness`, `_link_intervention_sql`) — the same reasoning as `_merge_mastery`,
extended from merging a top-level key to mutating one element inside an array. The link
is additionally idempotent: relinking the same intervention twice does not duplicate it.

**Known, accepted gap:** the recurrence rule's dedup is check-then-act, not atomic against
a second, genuinely concurrent caller for the same student. Accepted at today's scale (one
fast-path writer, one event at a time) — the same category of accepted limitation as V4's
cohort-of-one degeneracy.

#### Piece 4 — `rebuild_from_traces`, the full event-sourcing proof

**This is the M2 DoD**: wipe `learner_profile`, replay the log, get the identical profile
back. It holds — measured, not asserted — for every column whose live writer exists.

Every column is authoritative-from-the-log, but they get there **four different ways**, and
the four-way distinction is the honest form of the claim (`DECISIONS.md` D-012; an earlier
draft of these notes framed it as a simpler two-way split, which implementing it disproved):

| Column | How | Why that way |
|---|---|---|
| `mastery` | **recomputed** | BKT over `ci_run` traces. A pure function, so first principles are safe. Calls `_replay_all_mastery` — the same helper `rebuild_mastery_from_traces` uses, so there is one implementation of the mathematics (D-007) |
| `weaknesses` | **replayed** | from their own lifecycle traces, *not* by re-running the recurrence rule |
| `reflections` | **recovered** | an LLM wrote them; there is nothing to recompute |
| `session_digest` | **recovered** | pointers to `session_summary` traces — the design document calls it "just a cache… safe to rebuild, never authoritative" |
| `features_ref` | **re-derived** | a pointer into `learner_features`, which is a different table's business |

**Why weaknesses are replayed, not re-derived.** Two concrete reasons, both mutation-tested:
re-running the recurrence rule would **resurrect every closed weakness** (`open_weakness`
only ever writes `status="open"`; closing happens later from a reflection, so a pure
re-derivation cannot know it happened), and it would **change every id** (`w-{trace_id}` is
tied to its opening trace, so re-deriving means new traces, new ids, and every intervention
already recorded against a weakness points at nothing). So the three trace kinds that mutate
a weakness — `weakness_opened`, `intervention_linked`, `reflection_run` — are folded in one
pass in `(ts, trace_id)` order, because they interleave.

**The rebuild is authoritative, so it replaces rather than merges.** State the log does not
justify must *disappear* — a merge would preserve exactly the unjustifiable rows a rebuild
exists to expose. All five columns are written in one statement.

**A timestamp subtlety that would have broken the DoD** (`DECISIONS.md` D-013). `traces.ts`
comes from the database clock; `open_weakness` originally set `opened_at` from
`datetime.now()`, which measured **22ms** away. Since a rebuild can only recover `opened_at`
*from* the trace, the two paths disagreed in exactly that field. `_insert_trace` now returns
`(trace_id, ts)` and `opened_at` comes from that `ts` — the paths agree by construction. The
same requirement lands on `reflection.py` when it is built: take the reflection's `ts` from
its trace, not from the wall clock. (B.5 and B.7 both write the literal string `"now"`
there, so neither was a usable model.)

**A `profile_update` payload convention this code introduces.** `_replay_weaknesses` has to
tell a mastery `profile_update` apart from a weakness-lifecycle one, so `open_weakness` and
`link_intervention` tag theirs with `payload.action` (`weakness_opened` /
`intervention_linked`), and `update_mastery`'s deliberately has no `action` key — which is
how the filter excludes it. **No document specifies this vocabulary**; it is introduced here.
It lives inside `payload JSONB`, which the design document calls the "flexible letter" of its
"structured envelope, flexible letter" pattern — the typed columns are the envelope, payload
content is meant to evolve — so it is an addition inside a sanctioned space rather than a
schema change. Anything that later writes a weakness transition (`reflection.py`, the
staleness job) must follow the same convention or its transition will not replay.

**A truncation bug caught by `spec-verifier`, worth recording because it was subtle.** An
earlier draft applied `WEAKNESS_NOTE_MAX_CHARS` (B.5's 120-char cap on the note
`open_weakness` writes) to the *reflection-driven* note update as well. That is a different
write path with a different documented constraint: B.7 caps reflection notes at **30 words**,
inside `reflection.py`'s validation, before the trace exists — and applies no character cap
when storing. So the rebuild silently truncated notes the live path would keep whole, for any
note over 120 characters. Reproduced (200 chars in, 120 out), fixed, and pinned by
`test_a_reflection_note_is_replayed_verbatim_not_truncated`. It is the same class of failure
as D-013, one field over: a rebuild that quietly disagrees with the live path.

**One deliberate, tested asymmetry.** `reflection.py` and `sessionize.py` do not exist, so
nothing *live* folds a `reflection_run` or `session_summary` trace into the profile — but the
rebuild already does. For those columns the rebuild is **ahead of** the live path: replaying
*changes* the profile rather than reproducing it, because it correctly derives state the live
path never applied. That is the rebuild being more correct than the live state, not a rebuild
bug, and `test_rebuild_derives_state_the_live_path_cannot_yet_apply` pins it so it is a known
fact rather than a later surprise. That test doubles as the specification for those two
components: when they are built, they must apply exactly what the rebuild derives.

Likewise a `stale` status can never be reproduced by a rebuild until the scheduled job that
sets it writes its transition as a trace — recorded in the module's known-gaps list.

### 7.11 `scripts/prove_event_sourcing.py` — the M2 proof (BUILD_PLAN 2.6)

Snapshot every `learner_profile` → `TRUNCATE learner_profile` → `rebuild_from_traces` for
every student → deep-diff → print `IDENTICAL` or exactly which fields differ. This is the
executable form of the project's central claim, and the thirty seconds worth rehearsing.

Six decisions, each load-bearing:

1. **Stored state is compared to stored state.** The snapshot is read back out of the table,
   and so is the rebuilt profile — *not* compared against `rebuild_from_traces`'s in-memory
   return value. Both sides travel the identical JSONB→Python path, so a difference can only
   mean the values really differ, never that one side took a different route.
2. **It rolls back by default.** The comparison happens inside the transaction, so the proof
   is complete either way; rolling back makes it safe to run against real data and safe to
   rehearse repeatedly. `TRUNCATE` is transactional in PostgreSQL, so the wipe is genuine and
   genuinely undone. `--commit` exists for the one case where persisting is the point:
   repairing a profile that has drifted from its log.
3. **A vacuous pass is a failure.** Zero comparable profiles exits **2** with
   `NOTHING TO PROVE`, so neither CI nor a DoD write-up can mistake an empty database for a
   passing proof. That matters today: the database has no telemetry (D-006).
4. **`updated_at` is excluded** — a freshness stamp, not derived belief; a rebuild
   legitimately touches it. Every other column is compared.
5. **`traces` is counted before and after** and printed. A proof that quietly modified the
   log it replays would prove nothing.
6. **Students who had no profile are reported, not failed.** A student with traces but no
   profile row means the fast path has not run for them yet; the rebuild creating one is
   correct, so it is listed separately and kept out of the verdict.

Exit codes: `0` identical, `1` differences found, `2` nothing to prove.

**The diff is hand-written** (~20 lines) rather than pulled from a dependency: this
comparison *is* the proof, so it should be readable and explainable in a viva, and the
dependency list stays as CLAUDE.md §9 fixes it. It reports full paths
(`mastery.spark.joins.p_mastery`), list lengths, list indices, and distinguishes "key absent"
from "key present and None".

**One thing mutation testing found, worth recording because it is a mild surprise.** Removing
the `TRUNCATE` entirely left every test passing — because `rebuild_from_traces` *replaces*
each column rather than merging, so the rebuild overwrites the profile either way. The wipe
still belongs: BUILD_PLAN specifies it, it is the demo's whole rhetorical core, and it is what
would expose a future rebuild that merged into existing state instead of deriving it. So
`rows_after_wipe` is now recorded and asserted — **a step nothing checks is a step that can
silently stop happening.**

The suite is mutation-checked rather than merely green. Piece 1: removing the vocabulary
validation fails 9 tests; aliasing the empty-profile dict fails exactly the one test
written to catch it. Piece 2: reintroducing B.5's partial-state restore fails
`test_confidence_grows_with_evidence` (the D-007 regression test); coercing non-`success`
conclusions to failure fails 4; hardcoding difficulty to 0.5 fails the KT-IDEM test; adding
an unclassified kind to `KINDS` fails the coverage guard. Piece 3: removing the open-
weakness dedup fails the idempotency test; dedupping against any status instead of just
`open` fails the reopen-after-close test; dropping the assignment scope fails the
cross-assignment test; reverting to a length-based counter fails the id test; removing the
link's idempotency guard or its raise-on-unknown each fail exactly the test built for it;
reintroducing the corrected bug (counting by concept instead of `error_class`) fails
`test_two_different_error_classes_on_the_same_concept_do_not_recur` specifically. Piece 4,
eight mutants: reverting `opened_at` to the wall clock fails the headline DoD test (which is
the point — that test genuinely guards round-trip identity); merging instead of replacing
fails the authoritative-rebuild test; ignoring status transitions fails the
closed-weakness-resurrection test; dropping the intervention replay fails the identity test;
an uncapped `reflections`, an oldest-first `session_digest`, an earliest-instead-of-latest
`features_ref`, and perturbing mastery so the broad rebuild disagrees with the mastery-only
one each fail exactly their own test.

---

### 7.12 `agents/echo_agent.py` — the tracer bullet (BUILD_PLAN 2.4)

Rule-based, no LLM, no network, no cost. It judges a submission from one fact — the CI
conclusion — and its real product is not the judgement but **the interface**: the `grade()`
signature that M4's `agents/code_agent.py` must preserve so that milestone is an internals
swap and not a refactor. `DEVELOPMENT_MAP.md` D.3 names this as one of the three integration
seams, and the reason it is worth a whole file is that the seam would otherwise be defined by
whoever writes M4 first, under deadline.

**Designed against four consumers, not one.** This is why the file is ~120 code lines rather
than `BUILD_PLAN`'s estimated "~20": the estimate covers the rule, not the contract, and
`BUILD_PLAN`'s own next sentence ("it must expose the same interface the real Code Agent will
use") is what the bulk serves.

| Consumer | What it fixes |
|---|---|
| `Modules_3_9` D.5 `grade()` (line 906) | Positional order, the return triple `(verdict, trace_id, failures)` |
| `system/orchestrator.py` (M6, line 1818) | Module-level sync function named `grade`, callable via `asyncio.to_thread` |
| `agents/reviewer.py`'s `detect_disagreement` (M6, line 1535) | The verdict **object's** attribute surface |
| `memory/memory.py` | The only door (invariant 2) |

Neither the orchestrator nor the Reviewer exists yet, so those two comparisons are against
the document text. That is exactly why the test file asserts them: nothing else in the repo
calls `grade()`, so a signature drift would be silent until M4 or M6 tripped over it.

**What it scores, and what it refuses to.** Correctness maps 4 on a CI pass, 0 on a failure.
The other three criteria — approach, readability, idiomatic — take the middle anchor 2 with
`confidence="low"`, because a green CI run is evidence about correctness and nothing else,
and scoring readability from it would be the fabricated judgement invariant 6 exists to
prevent. That neutral-anchor-plus-low-confidence shape is not invented: it is the convention
`orchestrator._missing_perf_verdict()` already uses for an agent with no information (D-016).
A conclusion outside `{success, failure}` — `cancelled`, `skipped`, `timed_out` — drops
correctness to the neutral anchor too, reusing `memory.OUTCOME`'s existing judgement that
those say something about CI infrastructure rather than about a person. A conclusion of
`None` raises instead, because that is a caller who forgot the one fact Echo grades on.

**What actually moves mastery — the part worth understanding (D-017).** Echo's scores feed
nothing. `MASTERY_TRACE_KINDS` is `{"ci_run"}`, and `NON_MASTERY_KINDS["verdict"]` says
plainly that the rubric→BKT mapping has not been decided. So Echo logs its `verdict` as a
*child* of the `ci_run` it judges and then calls `update_mastery`, which replays that
`ci_run`. **Mastery moves because of the CI event, not because of the agent's opinion.** Three
tests pin this: mastery reaches the hand-computed 0.8126 from the `ci_run`; a verdict with no
`ci_run` behind it moves nothing at all; and — the regression guard that matters — Echo is
handed `"failure"` while the log holds a pass, and the log wins. If someone ever re-wires the
outcome into the mastery update, that third test fails, and it is the D-007 mistake returning.

**Three deviations from D.5, each recorded rather than silent.**

- **D-015 — the memory calls are the live door's, not D.5's.** D.5 calls
  `update_mastery(correct=..., item_difficulty=...)`; the live method takes neither, because
  D-007 replaced outcome-folding with replay. Transcribing D.5 verbatim raises `TypeError`,
  verified by execution. This is the third place D-007 propagates, and M4 will hit it too.
- **`evidence_failures` is a field on the verdict model.** `reviewer.detect_disagreement`
  reads it via `getattr`, but D.5's `Verdict` declares no such field — so as the document
  stands, the `evidence:code_agent_unmatched` flag can never fire. Declaring it makes that
  flag *reachable*; M4 is what populates it, M6 what reads it.
- **Parameters after `code_path` are keyword-only.** D.5 writes them positional-or-keyword.
  Every call site in the documents passes them by keyword, so nothing breaks; the narrowing
  is deliberate and recorded, since a positional `profile_snapshot` and a positional
  `reference` are indistinguishable at a glance.

**Deliberately absent, and tested for.** `code_path`, `reference` and `profile_snapshot` are
accepted and never read — they are M4's inputs, present so the swap changes no call site, and
a test passes a nonexistent path to prove nothing opens it. Echo does **not** call
`apply_recurrence_rule`: opening weaknesses is the fast path's job (2.2), not a judge's. And
no memory slice is recorded: an earlier draft wrote one into the verdict payload to exercise
the `profile_snapshot` seam, and it was cut on review, because H.2 names the *grade* trace as
where a judgement-time snapshot belongs and a second home for "what did the system believe
when it graded this?" is the duplication D-007 and D-012 argue against everywhere else. Its
absence is pinned by a test, so reintroducing it has to be a decision rather than a habit.

**One open question, shipped as open (D-018).** Echo emits four rubric scores and no verbatim
quotes. It cites the `ci_run` trace instead. The reading this relies on — that invariant 6's
string-matching clause governs LLM-authored verdicts, whose named defence is hallucination,
and that a deterministic agent with no generative step satisfies its purpose by citing the
event — is *plausible but not authorised*, and is logged OPEN for Dr. Ezzatul rather than
recorded as a decision. M4 must not lean on it until it is settled.

**Tests:** 32, in `tests/test_echo_agent.py`, split into seam tests (which pin the interface,
including a literal reproduction of the orchestrator's printed call shape) and behaviour
tests (the mapping and Option A). Suite total: **196 passed, 1 xfailed**.

### 7.13 `system/llm.py` — the LLM Gateway (M3, BUILD_PLAN 3.1)

The provider abstraction every LLM call in this project must pass through — invariant 3's
actual enforcement point, not just its name. Transcribed from `VDEL_Modules_3_9_Build.md`
Part H (1700-1783), which specifies a single `llm_call(prompt, temperature=0.0, ...)`
function; the live code diverges from that in five recorded ways (D-020 through D-025),
because the source document's own prose disagrees with its own code in two places and its
one hardcoded behavior 400s on the model this repo now defaults to.

**Two doors, not one.** `judge(prompt, schema) -> (T, CallRecord)` has no `temperature`
parameter — it always judges at 0. `generate(prompt, *, temperature) -> (str, CallRecord)`
takes a caller-chosen temperature for the non-judging calls (`reflection.py`'s weekly
narrative). Splitting the door makes invariant 4 checkable rather than merely discouraged:
a `temperature` argument appearing anywhere under `agents/` is a grep away, and `system/llm.py`
is the *only* module `pyproject.toml`'s `flake8-tidy-imports.banned-api` permits to import
`anthropic` or `openai` — every other module fails `ruff check .` for trying, which is
already in every milestone's DoD.

**Validation and the one corrective retry live in the gateway (D-022).** `judge()` validates
the response against the caller's schema, retries exactly once with a corrective suffix on
failure, and raises `SchemaValidationError` (carrying both attempts' `CallRecord`s) if the
retry also fails — invariant 5, structurally: a caller cannot receive an unvalidated value,
because there is none to return. This is a deliberate divergence from the source document's
own executable code, which retries inside the *agent* (D.5, calling `llm_call` twice); the
document's gateway docstring and `BUILD_PLAN.md` both side with the gateway instead, so the
document disagrees with itself and CLAUDE.md's "documents win" tiebreak doesn't resolve it.

**Generic over schema.** `judge` takes the pydantic model as an argument; it never defines
what a verdict looks like. `agents/echo_agent.py`'s `EchoVerdict` — already live, carrying a
field (`evidence_failures`) D.5's own `Verdict` lacks — is untouched by anything this file
does.

**D-025 — temperature 0 is not representable on every model.** Claude Sonnet 5, D-024's
corrected default-tier model, rejects an explicit non-default `temperature` with a 400; only
omitting it is accepted. `_call_anthropic` sends `temperature=0.0` where the model allows a
non-default value, omits the parameter where the model rejects one *and* the request is
`0.0` (every `judge()` call lands here), and raises `ValueError` where the model rejects one
*and* the request is genuinely non-zero (only reachable from `generate()`). This has no
counterpart in the source document at all — `llm_call` sends `temperature=temperature`
unconditionally into every branch — and was caught in review, before any code was written
against a hardcoded call that would have 400'd the first time it actually ran.

**Three providers live, one stubbed (D-031, D-032).** Anthropic is `.env.example`'s
documented default. NVIDIA — a free-tier, OpenAI-compatible hosted endpoint added under
`LLM_PROVIDER=nvidia` without touching the default — is the second live branch,
`_call_nvidia`, reusing the `openai` SDK against `base_url="https://integrate.api.nvidia.com/v1"`
and keyed by `NVIDIA_API_KEY` (never `OPENAI_API_KEY`). Its model id,
`deepseek-ai/deepseek-v4-pro`, was supplied directly by Anas and is **not** independently
verified against NVIDIA's live catalog by this project, unlike D-024's checked correction of
the Anthropic default — the cheap tier stays `TODO(verify)` for the same reason. Google is
the third live branch, `_call_google` (D-032) — **this reverses D-023**, which had removed
`google` from `Provider` entirely because no document asked for it; D-023's text stays
verbatim in the module as the historical record (append-only), with its status line pointing
at D-032. `_call_google` uses `client.models.generate_content`, not the SDK's own
currently-recommended `client.interactions.create` — both exist on the installed
`google-genai` package, but `generate_content`'s `config` argument is a typed
`GenerateContentConfig` with a real `temperature: float` field, confirmed by installing and
introspecting the actual package rather than trusted from two documentation pages that
disagreed with each other and never fully specified `interactions.create`'s body schema.
Model ids `gemini-3.7-flash` (default) and `gemini-3.5-flash-lite` (cheap) were cross-checked
live against ai.google.dev on 2026-08-19 with two independent fetches, both stable/GA, not
preview. OpenAI proper remains a structural stub — the dispatch branch exists
(`_PROVIDER_HANDLERS` routes to it), and calling it raises `NotImplementedError`, which is
what makes the abstraction real rather than theoretical: selecting `openai` fails *inside
OpenAI-shaped code*, not at a generic "unknown provider" check that would fire identically
for a typo. `qwen_local` remains stubbed the same way.

**Two things left genuinely open, not silently resolved.** D-020: `_cache_key` is
implemented against the source code's literal `sha256(f"{model}:{temperature}:{prompt}")`
formula (verified byte-identical by `spec-verifier`, executed), because a cache with no body
can't be tested — but four sources disagree on what the key should actually be, and this is
the document's own "safer default", not a ratified decision. D-024: `MODEL_TIERS` carries
corrected/verified model ids for Anthropic, NVIDIA and Google, and `TODO(verify)`
placeholders remaining only for OpenAI, Qwen, and NVIDIA's cheap tier — nothing is guessed,
and `CallRecord` carries `attempt`/`schema_valid`/`cache_hit` specifically so
`benchmark/run_benchmark.py` can later *measure* `json_retry_rate` rather than default it to
the document's invented `0.05`.

**Tests:** 46, in `tests/test_llm.py`, mocking `anthropic.Anthropic`, `openai.OpenAI`, and
`genai.Client` themselves — not the internal dispatch table — so each real branch's own
kwargs are inspected. Anthropic side: cache hit/miss including the benchmark's
`use_cache=False` requirement, both D-022 retry branches, all three D-025 temperature
branches for both `judge` and `generate`, cost-log writes, and provider dispatch including
the remaining stub branches raising cleanly. NVIDIA side (D-031): the branch is real; the
client is constructed with the NVIDIA base URL and `NVIDIA_API_KEY` specifically, never
`OPENAI_API_KEY`; a missing key raises a clear `RuntimeError` before any client is
constructed; token counts and response text are read from OpenAI-shaped fields
(`usage.prompt_tokens`/`completion_tokens`, `choices[0].message.content`), with a fake
response object carrying no Anthropic-shaped attributes at all so a copy-paste of the wrong
field names would `AttributeError` rather than silently read zero. Google side (D-032): same
shape of tests — real branch, correct key, both verified model ids resolved per tier — plus
one specific to the SDK-shape decision: `test_google_sends_temperature_through_a_typed_generate_content_config`
asserts the argument passed is a real `types.GenerateContentConfig` instance with
`.temperature` set, which fails loudly (pydantic rejects unknown fields) if the code ever
regressed to a guessed dict shape. `pyproject.toml`'s invariant-3 import ban was extended to
`"google.genai"` and verified empirically — three import forms tested, and a throwaway file
outside `system/llm.py` confirmed to actually fail lint before being deleted (not just
assumed to work because the ban entry was added). No real network call anywhere in the file.
Suite total: **336 passed, 1 xfailed**.

**Known gaps:** `agents/validation.py`'s evidence string-matching (BUILD_PLAN 4.4) is not
here and never will be — this gateway knows about transport, schemas, cost and caching,
nothing about rubrics. `cohort_cost` lives in `benchmark/run_benchmark.py` (H, 689), not
this module, despite invariant 3 reading as though the whole gateway were one file.

**D-051, added 2026-08-25 — the gateway now enforces its own call-timeout.** A live
`scripts/demo.py` run sat silent for 15 minutes; traced to a real 222.3s Google call
before failing transient, and confirmed (web search, not guessed) that `google-genai`'s
SDK delegates timeout behavior to the server and its own `http_options` timeout is
documented as unreliable (googleapis/python-genai#911, #681) — not fixable by tuning an
SDK parameter. `_call_with_timeout` wraps the ONE place every provider handler is already
dispatched (`_call_with_fallback`'s call to `_PROVIDER_HANDLERS[provider]`) in
`concurrent.futures`, uniformly for all three providers, with a 30s ceiling
(`_PROVIDER_CALL_TIMEOUT_S`). A timeout is classified `"transient"` by
`_classify_transport_error` and walks the exact same D-049 fallback chain any other
transient failure does — no second trigger. Re-confirmed live, same session: a second
Beat 6 run hit the identical slow-primary pattern, this time caught at 29.6s instead of
running 222s, correctly fell back, all seven demo beats still passed. 8 new tests in
`tests/test_llm.py` — the first tests this file ever had covering
`_classify_transport_error`/`_call_with_fallback` at all. Full record: `docs/DECISIONS.md`
D-051.

### 7.14 `benchmark/submissions/` — the five canary submissions (M3, BUILD_PLAN 3.2)

A new task, not Sara's A2 — `TASK.md` states it: given a PySpark `orders` DataFrame with
one row per order *line*, return total revenue and distinct order count per customer per
calendar month. Concept `spark.aggregation`. Keeping this independent of the M1/M2 Sara
fixtures matters because M4's ground truth must not be written by looking at a task the
system has already graded once — the whole reason 3.2 is unblocked before `code_agent.py`
exists (`HANDOFF.md`, 2026-08-12).

All five files expose the identical entry point, `compute_monthly_revenue(orders) ->
DataFrame`, so `benchmark/run_benchmark.py` (3.3) can call every archetype the same way.

- **`clean.py`** — the reference. Idiomatic DataFrame-API code, correct grain: `order_id`
  appears only inside `countDistinct`, never in the `groupBy`.
- **`subtly_wrong.py`** — `order_id` is left in the `groupBy`, silently narrowing the grain
  from per-month to per-order. Numerically identical to `clean.py` for a customer with one
  order that month; wrong (and `order_count` pinned at 1) the moment there are two or more.
  Runs cleanly, types check — the bug is grain, not syntax.
- **`inefficient.py`** — numerically correct, wrong engine use: `.collect()` ships the whole
  table to the driver, the aggregation runs in a Python dict, and the result is rebuilt with
  `createDataFrame`. Four anti-patterns, named in the file's own docstring so a later recall
  measurement (M5) can check whether a judge names each one rather than a vague "not
  idiomatic."
- **`copy_paste.py`** — numerically correct, reads like several answers stitched together: a
  needless class wrapper, `AddMonthColumn` next to `add_revenue_col` (naming convention
  changes mid-file), a dead `pandas` import, a wildcard import. The dead and wildcard imports
  are real ruff findings (F401, F403) — verified live, not asserted — so the tool stage has
  genuine evidence here, not just an LLM's opinion of style.
- **`broken.py`** — fails at runtime, not at parse time. `orders_df` (undefined; the
  parameter is `orders`) is a live F821 finding under this repo's own ruff config; even if
  that were fixed, `.groupby(...)` is pandas' spelling of PySpark's `.groupBy(...)`, an
  `AttributeError` no static tool can see. Two independent failures, so a partial fix can't
  accidentally look like a pass.

**`pyproject.toml`'s `[tool.ruff] extend-exclude`** keeps this directory's two intentionally
broken files from failing the repo-wide `ruff check .` gate (D-026) while staying lintable by
the M4 tool stage, which will check one submission path at a time — verified live both ways:
`ruff check .` reports clean, `ruff check benchmark/submissions/broken.py` still reports
F821, `ruff check benchmark/submissions/copy_paste.py` still reports F401 and F403.

**Tests:** `tests/test_benchmark_submissions.py` — 12 tests: each file exists and parses as
valid Python (a syntax smoke check only; `subtly_wrong.py` and `broken.py` are *supposed* to
be wrong at runtime), the directory has exactly the five expected files and no others, every
file defines `compute_monthly_revenue`, and `TASK.md` exists. Suite total: **232 passed,
1 xfailed.**

**Known gaps:** `benchmark/ground_truth.json` (the second half of 3.2 — intended per-criterion
scores and a one-line justification each) is not written yet; per CLAUDE.md §10 the numbers
are Anas's to state, not to invent, so that file is the next task, not part of this one.

---

### 7.15 `agents/validation.py` — the evidence check (M4, BUILD_PLAN 4.4)

`BUILD_PLAN` calls `validate_evidence` "the most important function in M4", and the reason is
invariant 6: every rubric score carries verbatim evidence quotes, string-matched against the
actual submission, and a fabricated quote rejects the verdict. Every other stage of the Code
Agent produces a *judgement*; this one produces a **fact** — the quoted text was found in the
submission or it was not, and no model opinion enters.

That is also why the file has no LLM call, no database, and no I/O. It is a pure function of
`(verdict, code)`, so its tests need neither a provider key nor `PG_DSN` —
`test_module_imports_no_database` pins that property by reading the source and asserting it
imports nothing from `memory`, `system`, or `psycopg2`.

**Three deviations from D.5's `validate_evidence`, each closing a way D.5 under-reports:**

1. **Evidence entries may be `{"quote": ..., "why": ...}` mappings, not only `"quote + why"`
   strings.** D.5 recovers the quote with `q.split(" + ")[0]`, which truncates any quote
   containing `" + "` — in code, that is string concatenation and arithmetic, i.e. common.
   The string form is still accepted, and is parsed with two candidates (whole string first,
   then D.5's segment) so a real line like `total = df["qty"] + df["price"]` is verified
   whole rather than shortened to `total = df["qty"]` and checked against a fragment.
2. **A scored criterion with no evidence at all is a failure.** D.5 iterates
   `for q in quotes`, so an empty list yields no failures — a verdict scoring 4/4 with zero
   quotes passes D.5's check untouched. Invariant 6 says every score carries evidence, and
   silence is the cheapest way for a judge to avoid being caught fabricating.
3. **Matching is a documented two-level ladder and the level that succeeded is recorded.**
   Exact match first, whitespace-normalised as the only fallback — an LLM that re-indents a
   quoted line has not fabricated anything. Nothing case-folds and nothing strips punctuation,
   because identifiers are case-sensitive and `!=` is not `==`; those normalisations would let
   real fabrications through. `evidence_report()` returns every quote with its match level and
   is the function to show in a demo: "here is every quote, and here is the one that needed
   whitespace normalisation" is a stronger claim than "no failures".

**The flag-versus-reject asymmetry, stated as a choice.** `rejects_verdict()` returns True
only for `unmatched_quote`, not for `missing_evidence`. Invariant 6's rejecting clause is
specifically "a fabricated quote rejects the verdict" and says nothing about an absent one,
and D.6 resolves that case as "flagged for human review, not silently trusted". This is a
defensible reading rather than a null one, and it is an **open question for Dr. Ezzatul**,
recorded alongside D-018 which asks the mirror-image question about Echo citing an event
rather than a quote.

**Known limitation, named rather than papered over:** a very short quote (`x`, `df`) matches
almost any submission and still passes. The obvious guard is a minimum quote length, which is
exactly the invented number `CLAUDE.md` §10 forbids; the honest fix is a prompt that asks for
whole lines, which `agents/prompts.py` does.

**Tests:** `tests/test_validation.py` — 25 tests, no database, no key.
`test_fabricated_quote_is_caught` is the one that matters; the rest cover each deviation,
malformed evidence never raising, and `test_criteria_match_echo`, which is what makes the
locally-declared `CRITERIA` tuple safe from drifting against Echo's.

---

### 7.16 `agents/tools.py` — the deterministic stage (M4, BUILD_PLAN 4.2)

Stage 1 of the agent skeleton: run free, zero-variance checks and hand their findings to the
judge as verified facts. Deterministic-first — never pay an LLM to notice an unused import
that ruff notices perfectly, for nothing, every time.

**This is also where invariant 12 lives, and the boundary is worth stating precisely.** `ruff
check` and `sqlfluff lint` are static analysers: they tokenise and parse, they do not import,
evaluate, or run. Nothing uses `shell=True`, and every path is passed as its own argv element,
so a submission cannot escape through its own filename. `test_never_executes_the_submission`
plants a file that writes a marker at import time and asserts the marker never appears — the
only mechanical check in the repo that the no-execution boundary is real rather than intended.

**Three deviations from D.5, all of which follow from actually running the two tools:**

1. **`except Exception: return "[]"` is replaced by an explicit status.** D.5 collapses "the
   linter ran and found nothing" and "the linter is not installed" into the same empty string,
   which the prompt then presents to the judge as a verified fact that the code is lint-clean.
   That is inventing a fact by omission — the same class of error as the fabricated
   `duration_s = run_number * 60` in this document's §9 history. A `ToolReport` carries its
   `status` (`ok` / `unavailable` / `timeout` / `error`), and `render_findings` says "DID NOT
   RUN … the absence of findings below is not evidence that there are none" out loud.
2. **Findings are normalised to five fields, not passed through as raw stdout.** A single
   five-violation sqlfluff run emits several thousand tokens, ~90% of it `fixes` edit spans
   and per-rule `timings`. `CLAUDE.md` §8 lists linter findings as the element that defends
   against *wasted attention*; pasting the timings block would defeat the element with itself,
   on every graded submission.
3. **Absolute paths are reduced to the basename.** Both tools report the full local filesystem
   path. That is noise to the judge, and it puts a developer's directory structure into a
   third-party API call and into `COST_LOG` — pointed the wrong way for the PDPA note M3's
   `RECOMMENDATION.md` has to make about student code being personal data.

Both linters are invoked as `sys.executable -m <tool>` rather than as bare `ruff` / `sqlfluff`,
because the console scripts are not on `PATH` on this machine while the modules are. Note also
that both tools exit non-zero when they *find* violations, so status is decided by whether
stdout parses, never by the return code.

`DEFAULT_SQL_DIALECT = "ansi"` is a real limitation, not a setting to forget: a Spark SQL
submission linted as ANSI is judged against slightly the wrong grammar, producing false
positives rather than a parse failure that would report nothing at all.

**Tests:** `tests/test_tools.py` — 15 tests. They skip cleanly where ruff or sqlfluff is
absent, and monkeypatch `subprocess.run` to simulate the unavailable/timeout/unparseable
paths without needing to uninstall anything.

---

### 7.17 `agents/prompts.py` — the judge prompt (M4, BUILD_PLAN 4.3, 4.6)

Every element defends a **named** failure mode; the table in the module docstring is
authoritative. An element that cannot name what it defends is deleted rather than kept "just
in case" — an instruction with no failure mode behind it is one more thing for the judge to
weigh.

`PROMPT_VERSION` is stamped into every verdict payload, because a stability number is
meaningless without knowing which prompt produced it. Changing any string here means bumping
the version and adding an entry to `agents/PROMPT_CHANGELOG.md`, whose format requires each
entry to name the failure mode addressed and what the benchmark said before and after —
`not yet measured` where nothing has been measured, rather than a plausible invented delta.

**Four deviations from D.5's `build_grading_prompt`:**

1. **Evidence is requested as objects, not `"quote + why"` strings** — the separator collides
   with the data it separates (§7.15, deviation 1).
2. **The rubric is a module constant, not `assignment["rubric"]`.** D.5 reads it off the
   assignment dict, but the `assignments` table has no `rubric` column — only `assignment_id`,
   `repo_prefix`, `released_at`, `due_at`, `concepts[]`. Inventing one would be exactly the
   structure invention `CLAUDE.md` §11 names as the failure mode to avoid. The same applies to
   `assignment["task"]`, which the caller supplies and `grade()` requires with a loud error.
3. **The D.4 fairness rule is stated twice** — once as a standing rule, once inline at the
   memory slice. Everything else in the prompt is said once; this is the one instruction whose
   violation is undetectable after the fact, because a score nudged by a student's history
   looks exactly like a score that was not.
4. **No `CRITICAL:` / `YOU MUST` emphasis anywhere.** Current models follow a plain system
   prompt closely, and prompts written to overcome older models' reluctance now over-trigger —
   the instruction gets applied where it does not belong. `test_no_shouting` pins this.

Ordering is structural, not cosmetic: every rule precedes the submission, so a rule can never
appear to be part of the data it governs. `test_every_rule_precedes_the_submission` fails if a
future edit moves the schema or the evidence rule below the delimiters, which is the opening a
student would need to close the fence and append their own instructions.

The reference solution is **off by default**. D.6 records why: supplying a wrong reference
makes a judge award zero to correct answers (the physics-marking finding), so it is a measured
tradeoff the benchmark tests with and without, not a default.

**Tests:** `tests/test_prompts.py` — 22 tests, pure string assembly, no key or database. Each
pins one element to the failure mode it defends, so deleting an element during prompt
iteration says which defence went with it.
`test_schema_block_matches_verdict_model` is the drift guard: the schema shown to the judge is
hand-written for readability, and this is what stops it disagreeing with the pydantic model
the response is validated against. That mismatch is otherwise invisible — the judge returns
fields the validator does not expect, the gateway's corrective retry burns a second call, and
it surfaces only as a mysteriously high retry rate in the cost log.

**Known open question carried into v1:** the rubric's fourth criterion is "Idiomatic
Spark/SQL", but all five benchmark submissions are PySpark-shaped while the current prompt
tells the judge to score the lower anchor and quote the line showing why when a criterion
cannot be assessed. Whether that is right — versus marking the criterion not-applicable and
excluding it from the aggregate — is a design question deliberately **not** resolved by
silently tuning the prompt.

---

### 7.18 `agents/code_agent.py` — the first real judge (M4, BUILD_PLAN 4.1)

The five-stage skeleton, with the LLM as **one stage in the middle** rather than the whole
thing: tools → assemble → judge → validate → commit. Every stage that is not stage 3 replaces
an unreliable judgement with a deterministic one. The agent is stateless; all state is on the
blackboard.

**It replaces Echo's internals, not Echo's interface.** `grade()` keeps D.5's contract — the
first four positional parameters, the `profile_snapshot` / `reference` keyword names, and the
`(verdict, trace_id, failures)` return triple — and writes under the same `ACTOR =
"code_agent"` Echo already used, so the trace log and the causal forest survive the swap
unmigrated. §7.12 records that Echo's shapes exist for exactly this: `EchoScores` is "D.5's
`Scores`, field for field. M4 replaces the values, not the shape", and its empty `evidence`
dict exists "so M4 fills a slot rather than adding one". `tests/test_code_agent.py` asserts
from this side that the two signatures and both model shapes actually agree, which is what
keeps M4 an internals swap instead of a refactor.

**Three deviations from D.5's `grade()`, each forced rather than chosen:**

1. **`llm.judge()` replaces `llm_call()` plus a hand-rolled retry.** D.5 calls a function that
   does not exist in this repo, then implements its own corrective retry around it. §7.13
   already owns that: `judge()` takes no `temperature` parameter at all (invariant 4 enforced
   by absence, not by a default) and performs exactly one corrective retry before raising
   `SchemaValidationError` (invariant 5, D-022). A second copy of the invariant is the one
   that drifts.
2. **No `correct=` / `item_difficulty=` on `update_mastery`.** D.5's call would raise
   `TypeError`: §7.10's `update_mastery` takes **no outcome argument, deliberately** (D-007 —
   folding a passed-in outcome onto partial state is what lost the Beta posterior and froze
   confidence at 0.286 regardless of *n*). Evidence comes from the log; the caller logs first
   and calls after, exactly as Echo does. `test_update_mastery_is_called_without_an_outcome_argument`
   asserts the parameters are absent so this cannot silently regress.
3. **`task` and `rubric` are not read from the `assignments` table** — see §7.17, deviation 2.

**A rejected verdict is still written.** Invariant 5 forbids dropping it silently, and a
flagged verdict with its reasons attached is the auditable form — deleting the record of a
judge that fabricated a quote destroys the evidence that it did. The payload carries
`flagged`, `prompt_version`, `model`, the tool reports, and `reference_supplied`, so any
verdict can be traced back to everything that produced it.

**The open decision this file deliberately does not resolve.** §7.10's `MASTERY_TRACE_KINDS`
is `frozenset({"ci_run"})`, and `verdict` sits in `NON_MASTERY_KINDS` with a reason written in
anticipation of this milestone: *"M4. An agent verdict IS mastery evidence, but its payload is
a per-criterion 0/2/4 rubric rather than a pass/fail, so the mapping from rubric score to BKT
outcome is a decision that has not been made. Adding it here without that mapping would
silently score every verdict as a failure."* D.5 proposes the mapping (`correctness >= 3`) and
§7.12 records that Echo chose 4/0 scores specifically so that threshold reproduces its binary
unchanged — so the pieces line up. But making a verdict move mastery means editing
`memory.py`, the only door (invariant 2), and changing what `rebuild_from_traces` produces,
which is the M2 DoD's proof. That is a shared-contract change and a stop-and-ask, not a side
effect of writing this file. **Until it is decided the Code Agent behaves exactly as Echo
does:** it calls `update_mastery`, which recomputes from the `ci_run` traces already in the
log, and the verdict itself moves nothing.

**Tests:** `tests/test_code_agent.py` — 20 tests. The judge is faked throughout: `system/llm.py`
is exercised by its own tests, and what needs testing here is the pipeline around the
judgement. Faking the one call also means these tests need no provider key and cost nothing,
which is what lets them run in CI. Seam tests come first;
`test_grading_never_executes_the_submission` re-checks invariant 12 end to end through the
whole pipeline rather than only at the tool stage, and
`test_schema_failure_propagates_rather_than_defaulting` pins that two invalid attempts write
no verdict at all rather than a placeholder.

Suite total after M4: **314 passed, 1 xfailed** (the xfail unchanged — see §7.2).

**Known gaps, corrected 2026-08-25 (`EXECUTION.md` §3.2 caught this stale):** the line above
used to say nothing had been run against a real model for want of an `ANTHROPIC_API_KEY`.
That was true when written and is not true now — `GOOGLE_API_KEY` is set and Google has been
a live provider since D-032 (`5770cbd`). `code_agent.grade()` has since run live, for real,
twice (D-049): once against `anas`'s real `weather_etl_transform` submission (`trace_id=48238`),
once again via `scripts/demo.py`'s Beat 6 (`trace_id=49505`, §7.21 below) — both real verdicts,
every evidence quote independently string-matched against the actual submitted file. What is
still genuinely missing is BUILD_PLAN 4.5's stability table (3 runs per benchmark submission)
and `benchmark/ground_truth.json` (§7.14) — those need Anas's own labels, not another API key,
and M4's "≥80% exact agreement" DoD clause cannot be measured without them.

---

### 7.19 The assessment layer (`assessment/*.py`) — added 2026-08-25, `EXECUTION.md` §3.4

This whole layer was missing from this document until now — a real gap `EXECUTION.md` §3.4
caught: the code existed (Stage A/B, `docs/DECISIONS.md` D-035/D-036/D-043/D-045/D-046) but
was never written up here. Five files, one job each, in the order a submission actually
flows through them.

**`assessment/gap_parser.py` — turns one master file into completion-problem specs.**
`parse_master(path)` reads a real curriculum file, finds every `# @gap:` marker, and returns
a list of `Gap` objects (`gap_id`, `concept_ids`, `line_start`/`line_end`, `instruction`,
`difficulty`). It validates every `concept_id` against `config/concepts.yaml`'s real
taxonomy at parse time — a gap tagged with a concept nobody defined would silently never
contribute to that concept's mastery, the same failure mode invariant 10 names for
unclassified errors, so it's rejected loudly instead (`GapParseError`). `render_student_file`
is the other half: given a master file's text and which gap IDs to hide, it produces the
student-facing version — the hidden gaps' bodies replaced with the instruction as a `TODO`
comment, everything else untouched.

**`assessment/gap_generator.py` — deterministic, per-student variant selection.**
`compute_seed(student_id, assignment_id, attempt_no)` and `select_variant(...)` are the
KT-IDEM item: which gaps get hidden for *this* student's *this* attempt is a seeded,
reproducible choice, conditioned on the student's current mastery per concept (cold-start
default when there's no observation yet). Two students calling this for the same assignment
get different `variant_id`s by construction, not by chance — proven live, `EXECUTION.md`
Beat 2, `anas` and `student2` on `weather_etl_extract`.

**`assessment/scope_check.py` — the invariant-14 boundary, as code.**
`scope_check(master_text, submitted_text, gap_ranges)` diffs a student's submission against
the released variant and classifies every changed line as inside or outside the gap regions
it was allowed to touch, returning `out_of_scope_lines_changed` and the actual line numbers.
This is a pure function — no I/O, no database write of its own — so **it is built but not
yet wired**: nothing currently calls it from a live script and persists its result into
`attempts.out_of_scope_lines` (the V9 column `sql/06` already has). That wiring is the
concrete remaining gap, not a redesign.

**`assessment/test_runner.py` — where correctness actually executes (invariant 13).**
`grade_attempt(project_id, assignment_id, repo_dir, attempt_id, ...)` runs one assignment's
hidden tests against a real rendered repo, in a real subprocess (`sys.executable -m pytest`)
— never inside an agent's process, which is the load-bearing fact that lets invariants 12
and 13 both hold without contradicting each other (see §8's reconciliation note). It parses
JUnit XML for real pass/fail per test, attributes each outcome to a `gap_id` via
`@pytest.mark.gap(...)` (D-046), and writes one `test_results` row per test per commit
(D-045c) — never overwriting a different commit's row, so a student's pre-freeze failure
history survives even after the attempt eventually freezes. Freezing itself (D-045a) is
this module's other job: `attempts.commit_sha`/`submitted_at` are written if and only if
hidden tests reach 100% pass on a real, already-collected commit — never merely on push,
which is why `collectors/collect_github.py` (§5) deliberately does not write those columns
itself. Every genuinely new, gap-tagged outcome also becomes a `test_result` trace through
`memory.Memory` (D-048, §7.10) — never raw SQL to `traces` (invariant 2) — which is what
lets V1/V5/V6 read a student's full failure history, not only the commit that eventually
passed. Proven live: `EXECUTION.md` Beat 3 (`12 failed, 3 passed` against an unsolved
render, then `4/4 passed` once `anas` actually solved `extract.py` for real — same function,
two real outcomes, no code changed in between).

**`scripts/render_student_repo.py` — materialises one attempt as a real file tree.**
Calls `gap_generator.select_variant` and `gap_parser.render_student_file` to produce a real
directory: rendered source, `tests/visible/` (copied; `tests/hidden/` is never copied — a
runtime check, `_assert_no_hidden_tests_leaked`, walks the output tree and refuses to return
a repo where that's been violated, not just a comment promising it won't happen),
`ASSIGNMENT.md`, and a generated `.github/workflows/ci.yml`. As of 2026-08-25 it also writes
a generated `.gitignore` (`tests/hidden/`, `__pycache__/`, `*.pyc`) — `test_runner.py`
injects the one hidden test a grading run needs directly into this same directory and never
cleans up after itself, so an ungitignored copy of it was one `git add -A` away from being
pushed to a student's real GitHub repo. Caught live this session before it happened, not
after.

### 7.20 V8–V11 — real schema, partial wiring

`CLAUDE.md` §8 lists four variables added by the 2026-08-19 redesign. Their actual state in
the running code, checked directly rather than assumed from the design doc:

- **V8 (Functional Equivalence Rate)** — the columns exist (`attempts.tests_passed`,
  `tests_total`), and the thing that fills them, `test_runner.py`, is real and proven live
  (§7.19 above). What was **not** built, and is not planned for v1, is the differential-input
  layer the original design specified in `assessment/diff_runner.py` — reduced (D-036,
  `EXECUTION.md` §5) to "a failing hidden test's own assertion message is the concrete
  counterexample." No `diff_runner.py` exists; this is a deliberate cut, not an oversight —
  see `BUILD_PLAN.md`'s M4b block.
- **V9 (Out-of-Scope Edit Rate)** — `scope_check.py` computes it correctly (§7.19) but
  nothing calls it from a live path and persists the result into `attempts.out_of_scope_lines`
  yet. Built, not wired.
- **V10 (First-Attempt Success Rate)** and **V11 (Session Fragmentation)** — schema exists
  (`attempts.attempt_no`, `sessions` table), but no code currently aggregates either into a
  reported number. `CLAUDE.md` calls V11 something that "falls out of duration tracking for
  free" once the session reconstructor exists — it doesn't yet, and per the soutenance-scope
  rule (`docs/DECISIONS.md`, pinned memory) it's cut deliberately: structurally degenerate at
  a cohort of one, invisible in the demo, trigger is cohort ≥ 10.

### 7.21 `scripts/demo.py` — the seven demo beats, one command (Stage D1)

Pure sequencing, deliberately. Every beat calls a function that already proved itself live
elsewhere in this document (§7.19's `test_runner.grade_attempt`, §5's collector, §7.10's
`Memory`, §7.18's `code_agent.grade`, §7.11's `prove`/`report`) — this file reimplements
none of them, so a bug found while running the demo is a bug in the function it called, not
in this script. Fixed throughout to real data: student `anas`, project `weather_etl`, the
real repo already pushed to `anass-ben-2005/vdel-weather-etl-gapfill-anas`.

Two flags, `--skip-network` and `--skip-llm`, exist because Beats 4 and 6 are the two with
a real cost (a live GitHub collection needing `GITHUB_TOKEN`; a real billed LLM call) — not
because either proof is optional. A full rehearsal runs with neither flag. Run live twice
2026-08-25 (once fully live, once offline), both times ending Beat 7 `IDENTICAL`, exit 0.

**Per-beat isolation, added the same day after a real failure.** Originally `main()` called
each `beatN_...()` in a flat sequence — one exception anywhere killed the whole script with
a raw traceback, discarding whatever the other six beats had already proven. A live rehearsal
run hit exactly this: Beat 6's primary model took 222.3s before failing transient, and the
resulting retry/fallback chain, combined with Python's default output buffering when stdout
isn't a TTY, looked indistinguishable from a 15-minute hang until re-run unbuffered
(`python -u`) confirmed it was real API latency, not a bug in this script. **`-u` is no
longer needed** — `main()`'s first statement is now `sys.stdout.reconfigure(line_buffering=
True)`, so every future run self-corrects regardless of launcher, with no flag or convention
to remember. Verified live: a synthetic script using the same call, redirected to a file
(not a TTY), had its first `print` already on disk mid-`sleep`, before the process even
exited. Fixed by wrapping
every beat in `_run_beat()`, which catches any exception, prints `FAIL` with the real error,
and continues — `KeyboardInterrupt`/`SystemExit` are `BaseException`, not caught, so Ctrl+C
still works. Each beat now returns a `BeatResult(passed, evidence)` built from its own real
query/verdict output (not just a print), and `main()` prints a final summary table and exits
non-zero if ANY beat failed — previously only Beat 7's `identical` check controlled the exit
code, so Beats 1–6 could fail their own internal check silently with exit 0.

Verified this does not touch the invariant-5 mechanism it sits around: a `SchemaValidationError`
after two failed corrective-retry attempts still means `code_agent.grade()` never reaches its
own `COMMIT` step (`agents/code_agent.py`), so no verdict trace is written — true both before
and after this wrapper existed. `_run_beat` only changes how loudly that already-unpersisted
failure surfaces: previously an uncaught traceback crashing the whole script, now a caught,
printed `FAIL` with the full exception, and the script continues to the next beat.

Connection isolation: every beat still opens its own connection fresh, via
`db.cursor()`/`db.connect()`/`db._open()` — none is ever held or passed between beats. No
synthetic/test data is created by any beat; Beat 6's LLM call writes a real trace for the
real student `anas` (matching D-049's precedent), real production activity, not a fixture
needing cleanup.

**Known limitation:** `tests/test_demo.py` covers `_run_beat`'s isolation logic (catch,
continue, pass args through) with stub functions, not the seven real beats themselves —
those are still only exercised live, by hand, each rehearsal. A regression in *how a beat's
own logic behaves* (as opposed to how demo.py sequences and isolates beats) would only
surface by actually running it, not by `pytest -q`.

---

### 7.22 `assessment/diagnose.py` — the C10 deterministic diagnosis function

`VDEL_REDESIGN.md` §C10: *"'Analysis Agent' → 'Feedback Agent' fed a pre-computed
diagnosis... A deterministic diagnosis function produces `{weakest_concept,
attempts_per_stage, recurrence_flags, failing_tests}`; the LLM receives that plus the
code and writes only the explanation... never pay an LLM for what a free tool does
perfectly."* This module is exactly that diagnosis function, and only that — the
"Feedback Agent" C10 also names, which would consume this output and write the
explanation, is M5/M6-era (`CLAUDE.md`'s scope table: M5 dropped, M6 needs ≥2 agents to
aggregate) and deliberately not built here. **Not wired into `scripts/demo.py` or any
`EXECUTION.md` Stage A–E item** — commissioned directly, ground-laying for the
still-deferred Feedback Agent, the same trigger as M6 itself.

`diagnose(cur, attempt_id) -> Diagnosis` — real reads only, zero writes, zero LLM calls,
no new table or column. Keyed by `attempt_id`, not `(student_id, assignment_id)`:
`test_results` FKs directly to `attempts.attempt_id`, and `(student_id, assignment_id)`
alone is ambiguous across `attempt_no` (`attempts`' own UNIQUE constraint is three
columns, not two). `student_id`/`assignment_id`/`project_id` are looked up from the
attempt row itself, matching every real column name confirmed against the live schema
(`\d test_results` etc.) before writing a line, not assumed from this document's own
schema listing.

Four fields, each with a distinct, deliberate scope:
- **`weakest_concept`** — the concept_id with the lowest pass rate across the attempt's
  FULL `test_results` history (more observations, same reasoning BKT already uses), via
  each failing/passing test's `gaps.concept_ids`. `None` if there's no evidence at all,
  or if every concept touched is already at 100% — "weakest" must mean a real weakness,
  not "the least perfect one when everything is perfect." Ties broken alphabetically by
  concept_id, deterministically — never left to depend on unordered SQL row order.
- **`attempts_per_stage`** — `{assignment_id: commit_count}` for every assignment
  (stage/file) in the attempt's project, from real `raw_commits.assignment_id` (D-043's
  per-file attribution). A stage never touched appears with count 0, not omitted.
  Falls back to just the one assignment when `project_id` is NULL (legacy pre-D-035
  assignments) — a NULL = NULL join would silently match nothing, so this is handled
  explicitly rather than producing an empty dict by accident.
- **`recurrence_flags`** — `{gap_id: bool}`, True once a gap has failed under
  `RECURRENCE_MIN_COMMITS` (2) or more DISTINCT commits — over full history, since
  recurrence is meaningless looking at one snapshot. Only gaps that failed at least once
  appear at all.
- **`failing_tests`** — only the LATEST commit's snapshot (or the latest local run, if
  more recent than any push) — "currently failing," the deliberate complement of
  `recurrence_flags` looking at history.

**Tests:** `tests/test_diagnose.py`, 6 tests, reusing `tests/test_test_runner.py`'s own
rollback-fixture pattern and real `weather_etl_transform` gaps/variants rather than a
fabricated parallel schema — a synthetic student (`_test_diagnose`), real commits/
test_results inside one transaction opened by the fixture and never committed. All four
`Diagnosis` fields' expected values are hand-computed against the real
`g_tf_clean`/`g_tf_convert`/`g_tf_timestamp` concept tags in the fixture's own
docstring, not just asserted self-consistent with the code.

---

## 8. The twelve non-negotiable invariants

From `CLAUDE.md` §7, and how each one is actually enforced (not just stated) in this
codebase as it stands today:

1. **`traces` is append-only. INSERT only.** — Enforced by two Postgres `RULE`s in
   `sql/05_memory_tables.sql` that turn `UPDATE`/`DELETE` into silent no-ops at the
   database level. Tested by `smoke_test.py` actually attempting both and checking they
   had no effect.
2. **Agents never write raw SQL to memory — everything goes through `memory/memory.py`.**
   — **Held, and now actually load-bearing.** `memory/memory.py` exists as of M2 piece 1
   (all four pieces: the trace/profile door, the fast path, the recurrence rule, and
   `rebuild_from_traces`). Four places write memory tables with raw SQL, all of them
   deliberate exceptions rather than drift:
   - `scripts/smoke_test.py` — proves the append-only RULEs by attempting UPDATE and
     DELETE on `traces`, inside a rolled-back transaction.
   - `scripts/prove_event_sourcing.py` — reads `learner_profile` directly and TRUNCATEs
     it. An **audit** script, not an agent: its whole job is to verify the door's output
     from outside, which it cannot do through the door. It still calls
     `memory.rebuild_from_traces()` through `Memory` for the step that matters.
   - `tests/test_memory.py` and `tests/test_prove_event_sourcing.py` — setup and
     assertions.

   No agent exists yet to violate this invariant, so its real test arrives with the Echo
   Agent in M2.4.
3. **Every LLM call goes through `system/llm.py`.** — **Held, and enforced at lint time, not
   just by convention.** `system/llm.py` exists (§7.13); `pyproject.toml`'s
   `flake8-tidy-imports.banned-api` fails `ruff check .` on any `import anthropic` or
   `import openai` outside that one file (and `tests/test_llm.py`, which mocks the SDK
   boundary itself). No agent calls it yet — Echo Agent is rule-based, no LLM — so the
   invariant's real test arrives with M4's Code Agent.
4. **Temperature 0 for all judging.** — **Held, structurally.** `judge()` has no
   `temperature` parameter at all; the value is unsayable, not merely discouraged. Where the
   resolved model rejects an explicit `0`, the parameter is omitted rather than defaulted to
   something else (D-025) — never a silent substitution.
5. **Every LLM output is schema-validated → one corrective retry → flag.** — **Held.**
   `judge()` validates against the caller's schema, retries once on failure, and raises
   `SchemaValidationError` carrying both attempts' cost records on a second failure — never
   returns an unvalidated value (D-022).
6. **Every rubric score carries verbatim evidence quotes.** — N/A yet (M4, Code Agent).
7. **The submission is DATA, never instructions.** — N/A yet (M4).
8. **Every mastery estimate ships with its observation count `n`.** — **Actively
   enforced.** `MasteryState.snapshot()` always includes `n`; every V2–V6 formula's
   return dict includes an equivalent count field (`n_obs`, or the raw counts that
   produced the ratio). No formula in this codebase reports a bare score with no sense
   of how much evidence backs it.
9. **Collectors and loaders are idempotent (`ON CONFLICT DO UPDATE/NOTHING`).
   Re-running must be safe.** — **Actively enforced and tested.** Every `INSERT` in
   `collect_github.py`, `seed_data.py`, and `compute_features.py` has an explicit
   `ON CONFLICT` clause. `init_db.py`'s idempotency is checked twice in CI (§4.5).
   `compute_features`'s idempotency (via the watermark trick, §7.8) is checked in
   `test_pipeline_integration.py`.
10. **Unclassified errors update no mastery, and the match rate is logged.** —
    **Actively enforced.** See §6.1 and §7.8's `_mastery()` query filter, plus the test
    that pins the filter's literal presence in the source.
11. **Secrets in `.env` (gitignored); `.env.example` committed.** — Done; `.gitignore`
    excludes `.env`. `config/roster.yaml` follows the same split (real GitHub username
    and repo names vs. its tracked `roster.example.yaml` template) — it was untracked but
    **not** ignored until this was noticed, a real gap given the public remote, closed
    2026-08-11.
12. **No agent executes submitted code.** — N/A yet (M4, Code Agent's tool stage isn't
    built). Promoted from a design note to a numbered invariant on 2026-08-13 (D-027),
    while attempting to verify `benchmark/submissions/` by actually running the fixtures
    through PySpark surfaced that the documented M4 tool stage (`ruff`/`sqlfluff`/AST,
    CLAUDE.md §8's agent skeleton) never included an execution step at all — the gap
    between "we never designed execution in" and "execution is explicitly forbidden" was
    implicit until that moment. Nothing to enforce yet, same as 6 and 7, but now written
    down before M4 exists rather than discovered as a missing check afterward.

Invariants 2–7 and 12 are listed here for completeness because `CLAUDE.md` states them as
governing the *whole project*, but as of M0/M1 they simply have nothing to apply to yet
— there's no memory layer, no LLM call, and no tool stage in this codebase. **Do not treat
their current "N/A" status as permission to violate them when M2/M3/M4 start** — they
become load-bearing the moment the relevant module exists, and should be designed in from
that module's first line, not retrofitted.

---

## 9. History of this codebase — what changed and why, in order

Understanding this sequence matters for calibrating trust in any given line of code, and
for not repeating a mistake that's already been made and fixed once.

**Pass 1 — built without the four large source documents available.** Only
`CLAUDE.md`'s condensed summary existed. This pass never checked whether the source
documents existed in the repo, and proceeded to *invent* plausible-looking formulas
instead of stopping to ask — directly contrary to `CLAUDE.md`'s own explicit instruction
("Stop and ask when something is ambiguous or conflicts with the source documents...
Silent scope invention is the failure mode to avoid"). Concretely wrong things this pass
produced, verified by actually running the code rather than just reading it:
- **The BKT update was mathematically inert.** Its Bayesian evidence step used the
  same numerator formula for both the "correct" and "incorrect" branches, so
  `update(prior, fail)` and `update(prior, pass)` produced the **identical** posterior —
  the model was structurally incapable of learning from evidence. `0.30 → 0.825`
  regardless of outcome, verified by direct execution.
- Fabricated numbers were written to the database as if they were measurements: a CI
  run's `duration_s` was computed as `run_number * 60` (a "placeholder" comment
  admitted this); lint-violation counts were derived from `commit_count // 20` with no
  actual linting ever performed.
- The classifier's rule table used bare-word regexes like `r"...|action"`, which would
  have matched the word "action" in the header of literally every GitHub Actions log —
  making every single failure classify as `spark.dataframe` regardless of actual cause.
- `docker-compose.yml` referenced a Docker image tag (`pgvector/pgvector:pg16-latest`)
  that does not exist in the registry — the M0 Definition of Done's very first command
  (`docker compose up -d`) would fail on a clean machine.
- Tests existed but had never actually been run: 3 of 11 failed when finally executed.
- `str(dict)` was used to write JSONB columns instead of `psycopg2.extras.Json` —
  writing Python's repr syntax (single-quoted) into a column that expects valid JSON.

**Pass 2 — rewrite from scratch, still without the source documents, but now careful.**
Every one of the bugs above was found by actually *running* the code (not just reading
it) and fixed with correct, from-first-principles implementations: a proper two-branch
BKT posterior, a saturation-avoiding mastery ceiling (`MASTERY_CEILING = 0.999` — a
belief that reaches exactly 1.0 becomes an unfalsifiable absorbing state that no future
evidence can move, which is precisely the property BKT was chosen over DKT to avoid),
`None` instead of any invented number wherever a genuine measurement was missing, a
precision-first classifier tested against a deliberately benign GitHub Actions log,
database-enforced append-only `traces`, and a full CI pipeline. This pass also
discovered and worked around two machine-specific environment traps that would otherwise
silently corrupt debugging: the port-5432-conflict (§4.1) and the locale-mangled
psycopg2 error messages (§4.2). This pass was methodologically sound but was still
**not verifiable against the actual specification**, because the four large source
documents still weren't in the repo — it could only be checked for *internal*
consistency (does the code do what it claims to do?), not *correctness against the
design* (does it do what the design actually specifies?).

**Pass 3 (current state) — the four source documents were added to the repo, and
everything variable-related was rewritten as a verbatim transcription of them,** rather
than kept as pass 2's from-first-principles (but unverified-against-spec)
reimplementation. This is the code described throughout this document. Concretely, this
pass changed: the Beta posterior's prior (uniform → Jeffreys, `a=b=0.5`), the exact
`confidence` formula, KT-IDEM's slip formula (`S·(1+d)` → the document's
`S + (0.40−S)·d·0.5`), the identifiability clamp bounds, the mastery estimator's
architecture (pure-function fold → the document's stateful class with a retained history
window driving `trend`), V4's entire framing (assignment-window-relative → the
document's cohort-relative survival-analysis framing), V2's Cronbach's-alpha
composite-gating (added — wasn't present in pass 2 at all), and the concept taxonomy's
actual IDs (`python.functions`/`spark.dataframe` → the document's real `py.*`/
`spark.df_basics`). This pass also added the `_failure_log`/classify-at-collection-time
wiring that pass 2 didn't have a document to know it needed, and discovered the Sara
partial-mismatch finding described in §7.2.

**The lesson this history exists to teach:** code that runs without error, passes its
own tests, and reads as internally coherent can still be **completely wrong** relative
to an actual specification it was never checked against. The BKT bug in pass 1 didn't
look wrong — it looked like a normal Bayesian update with a variable name that happened
to be unused. Every one of the fixes above required *comparing against the documents*
or *actually executing the code and inspecting the numbers*, not just reading the code
and reasoning about whether it looked plausible. If you're about to trust a formula in
this codebase, the fastest way to build justified confidence is: find its paragraph in
`VDEL_Modules_1_2_Build.md`, and re-derive at least one number by hand.

---

## 10. What is explicitly out of scope right now

Both to prevent accidentally rebuilding something that's deliberately deferred, and to
know where the designed seams are for when it's time:

| Not built | Why | Seam |
|---|---|---|
| `update_mastery` (fast path), the recurrence rule, `rebuild_from_traces` | M2 pieces 2–4 | `memory/memory.py` exists with `log_trace`/`get_profile`/`snapshot_profile`; every method already takes an optional `conn` so the fast path can write profile+trace atomically. DAG's `update_profiles` task now calls `sync_features_ref` (D-034) — the rest of this row is historical, predating those pieces' construction |
| A Code Agent verdict against a *real* model | Needs `ANTHROPIC_API_KEY` | `agents/code_agent.py` (§7.18) is built and calls the gateway, but every test fakes the one `llm.judge()` call — nothing has run against a live provider |
| The M4 stability table (BUILD_PLAN 4.5) | Needs a key, and ground truth for the accuracy half | 3 runs × 5 submissions is unmeasured; `benchmark/ground_truth.json` (§7.14) is still unwritten |
| A verdict moving mastery | Open decision, not a missing feature | `MASTERY_TRACE_KINDS` is `{"ci_run"}`; the rubric→BKT mapping is a stop-and-ask (§7.18) |
| `_discipline()`'s `cleanliness` wired to real lint counts | M5 | `agents/tools.py` (§7.16) now produces the ruff/sqlfluff findings this needs, but `compute_features.py` does not yet consume them |
| Tiered LLM error classification | Optimization 6 in the source doc, deferred | `error_classifier.py`'s rule table is v1-only |
| V7 Help-Seeking | Needs the coach's interaction log (M7) | `learner_features.help_seeking` is nullable, always `NULL` currently |
| EM-fitted BKT parameters (`bkt_v1` → data-fitted) | Needs ≥~100 sequences/concept; currently n=1 student | `kt_params.fitted` boolean column exists for this |
| Cox proportional hazards for pace | Needs real cohort data | `variables/pace.py`'s docstring notes this as the upgrade path |
| Synthetic student generators, `problems`/`attempts` tables, IBM CodeNet | Explicitly forbidden by `CLAUDE.md` §2 — the real telemetry source is Anas's own GitHub repos, seeded via `config/roster.yaml`, never fabricated | — |

---

## 11. How to verify this document against the live repository

Everything stated above as a *fact about current behavior* (not a historical note) is
checked by an automated test or a runnable command. If in doubt, re-run:

```bash
docker compose up -d && sleep 3
python -m scripts.init_db      # run twice — second run must print the same thing, change nothing
python -m scripts.init_db
python -m scripts.smoke_test   # tables exist; traces rejects UPDATE/DELETE
ruff check .                   # style/correctness lint, pinned rule set in pyproject.toml
pytest -q                      # 336 passed, 1 xfailed as of this writing (see §7.2 for the xfail)
```

`tests/test_pipeline_integration.py` is the single most informative test to read after
this document — it runs Sara's actual event sequence through the real database and the
real `compute_features.run()`, and asserts on all six implemented variables' output
simultaneously, including the idempotency property from §7.8.
