# STATUS.md — Milestone Board

> Written only by the `dod-evidence` skill. **A milestone advances here when its DoD command
> has been run and its literal output pasted below — never because the work felt finished.**
>
> `HANDOFF.md` says where you are *today*. This file says what has been *proven*, with
> evidence, and it is the file to open before a supervision meeting.

| M | Milestone | Status | DoD run | Commit |
|---|---|---|---|---|
| M0 | Foundations | ✅ **DONE** | 2026-08-11 | `acffca6` |
| M1 | Telemetry + Features | 🟡 **PARTIAL** | 2026-08-11 | `acffca6` |
| M1.5 | Verification pass | 🟡 PARTIAL (step 1 done, step 2 pending) | 2026-08-11 | `acffca6` |
| M2 | Memory + Echo Agent | 🟡 **PARTIAL** — code done, live DoD pending real data | 2026-08-12 | `b614597` |
| M3 | LLM Gateway + Benchmark | 🟡 **PARTIAL** — gateway done, benchmark not started | — | — |
| M4 | Code Agent | ⬜ Not started | — | — |
| M5–M7 | Deferred by design | ⏸ Out of scope | — | — |

**Why M0 is DONE and M1 is PARTIAL rather than UNVERIFIED.** `explanation.md` reported 64
passed / 1 xfailed. M1.5 step 1 has now run the `explanation.md §11` block on this machine,
at commit `acffca6`, and the literal output reproduces that claim exactly — see the entries
below. M0's DoD is fully covered by that run. M1's DoD has three clauses the test suite
does not independently demonstrate (DAG execution, an actual `learner_features` row count,
the classifier match rate as a recorded number) — see the M1 entry's Known gaps.

This distinction is the whole reason this file exists. "It was working when it was written"
and "it works now, and here is the output" are different claims, and only the second one
survives a supervision meeting.

---

## Legend

| | |
|---|---|
| ✅ DONE | DoD command run, output pasted, every clause met |
| 🟡 PARTIAL | Some clauses met; the unmet ones named explicitly |
| ❌ NOT DONE | DoD run and failed. **Record it — a failure is data about where the risk is** |
| ⚠️ UNVERIFIED | Believed complete, but no DoD evidence at a known commit |
| ⬜ Not started | |
| ⏸ Out of scope | Deferred by design, with a named trigger |

---

## Entries

<!--
Appended by the dod-evidence skill, newest last. Template:

## M<n> — <name>

Status:  DONE | PARTIAL | NOT DONE
Date:    <YYYY-MM-DD>
Commit:  <short hash>

### DoD as written
<quoted verbatim from BUILD_PLAN.md>

### Command run
```
<the exact command, not a paraphrase>
```

### Output
```
<literal stdout, exit code. Truncate only at the ends, and mark the cut>
```

### Assessment
<one line per DoD clause: met / not met / not applicable, and why>

### Known gaps
<things true but unsatisfying — the V4 n=1 degeneracy, the Sara joins xfail.
 These are findings, not failures. Naming them here is what makes them defensible.>
-->

## M0 — Foundations

Status:  DONE
Date:    2026-08-11
Commit:  `acffca6`

### DoD as written
> On a machine that has never seen this project:
> ```bash
> docker compose up -d && python scripts/init_db.py && python scripts/smoke_test.py
> ```
> creates every table from scratch and passes. CI badge green.
(`BUILD_PLAN.md`, M0)

### Command run
```
docker compose up -d
python -m scripts.init_db      # run once
python -m scripts.init_db      # run again — must be a no-op
python -m scripts.smoke_test
ruff check .
```
Not run on a machine that has never seen the project (a warm local Docker cache was in
use) — see Known gaps.

### Output
```
[+] up 1/1
 ✔ Container vdel-postgres Started                                          0.7s

  applied 01_reference_tables.sql
  applied 02_raw_tables.sql
  applied 03_feature_tables.sql
  applied 05_memory_tables.sql
  applied 04_indexes.sql
schema ready

  applied 01_reference_tables.sql
  applied 02_raw_tables.sql
  applied 03_feature_tables.sql
  applied 05_memory_tables.sql
  applied 04_indexes.sql
schema ready

OK    10 tables present
OK    traces rejects UPDATE and DELETE

All checks passed!
```

### Assessment
- Container starts, DB connects, all tables exist: **met** (`smoke_test` — 10 tables present).
- `traces` append-only enforced: **met** (`smoke_test` — rejects UPDATE and DELETE).
- `init_db.py` idempotent: **met** — second run printed byte-identical output to the first
  (same five files, same "schema ready" line); nothing changed.
- Lint clean: **met** (`ruff check .` — "All checks passed!").
- CI badge green: **not re-checked this session** — `.github/workflows/ci.yml` exists per
  `explanation.md` but its live GitHub Actions status was not queried here.

### Known gaps
- Run on Anas's own development machine with an existing Docker cache, not a genuinely
  clean machine ("never seen this project" per the DoD's literal wording). The idempotency
  double-run is real evidence regardless; the clean-machine claim is not yet demonstrated.
- Live CI badge state not queried this session.

---

## M1 — Telemetry + Features

Status:  PARTIAL
Date:    2026-08-11
Commit:  `acffca6`

### DoD as written
> The DAG runs green end to end · one `learner_features` row per repo · a deliberate re-run
> changes nothing (idempotency proven) · Sara's numbers match the hand computation · the
> classifier match rate is recorded.
(`BUILD_PLAN.md`, M1)

### Command run
```
pytest -q
pytest -q      # run again
```

### Output
```
.........................................x.......................       [100%]
64 passed, 1 xfailed in 13.77s

.........................................x.......................       [100%]
64 passed, 1 xfailed in 2.61s
```
Matches `explanation.md §11`'s stated baseline exactly (64 passed, 1 xfailed).

### Assessment
- **Sara's numbers match the hand computation:** met — `test_sara.py` is in the 64 passing
  and `explanation.md` states the xfail is the separate, already-recorded `spark.joins:
  0.47` discrepancy (see Known gaps), not a Sara mismatch elsewhere.
- **A deliberate re-run changes nothing (idempotency):** met by proxy — per
  `explanation.md`, `test_pipeline_integration.py` (among the 64 passing) asserts the
  idempotency property described in its §7.8, and it passed on both runs above. This is
  not the same as this session independently querying `learner_features` before/after a
  second `compute_features.run()` and diffing the rows by hand.
- **The DAG runs green end to end:** **not met this session** — `pytest -q` exercises the
  variable functions and the integration test, not `dags/vdel_pipeline.py` itself. The
  Airflow DAG was not run.
- **One `learner_features` row per repo:** **not met this session** — no direct query of
  the table was run; row count is inherited from the integration test's internal assertions,
  not independently confirmed here.
- **Classifier match rate recorded:** **not met this session** — no match-rate number was
  produced or logged in this pass.

### Known gaps
- The three unmet clauses above are the concrete follow-up: run the DAG once, query
  `learner_features` row count directly, and log `error_classifier.match_rate()` as a
  number in this file. None of this is expected to be hard — the code exists per
  `explanation.md` — it just was not exercised in this verification pass.
- **Finding, already open (do not resolve by tuning):** `spark.joins: 0.47` in the design
  document's worked example is unreachable under its documented `[fail, pass]` sequence at
  any difficulty (reachable range 0.591–0.964, per `DEVELOPMENT_MAP.md §A.3`). Pinned as a
  strict `xfail` — consistent with the "1 xfailed" above. Open question for Dr. Ezzatul.
- **Finding, already open:** V4 (pace) and V2's alpha-gate composite are structurally
  degenerate at a cohort of one. Not a bug; no cohort exists yet to make the signal
  available. Report as a structural finding, not a defect to fix.

---

## M1.5 — Verification pass

Status:  PARTIAL (step 1 done; step 2 pending)
Date:    2026-08-11
Commit:  `acffca6`

### DoD as written
> Run the `explanation.md §11` block; confirm 64 passed / 1 xfailed at a known commit. Then,
> for each of V1–V6, open its paragraph in `VDEL_Modules_1_2_Build.md` and re-derive one
> number by hand. Six numbers.
(`DEVELOPMENT_MAP.md §C.3`, `SETUP.md §4`)

### Command run
Same as the M0 and M1 entries above (`docker compose up -d`, `init_db` ×2, `smoke_test`,
`ruff check .`, `pytest -q` ×2).

### Output
See M0 and M1 entries above — not repeated here.

### Assessment
- **Step 1 — run the §11 block, confirm 64/1 xfailed on this machine:** met. Output
  reproduces `explanation.md`'s claimed baseline exactly, at commit `acffca6`.
- **Step 2 — six hand-derivations, one per V1–V6 formula:** **not started.** This is the
  remaining half of M1.5 and the next task.

### Known gaps
- Step 2 is unstarted. Per `DEVELOPMENT_MAP.md §C.3`, timebox each formula to 30 minutes;
  anything that doesn't reconcile gets logged `OPEN` in `DECISIONS.md`, not tuned to fit.
- The directory-listing verification item (`DEVELOPMENT_MAP.md §J.2` — does the live tree
  match `CLAUDE.md §5`?) has not been run either.

---

## M2 — Memory + Echo Agent

Status:  PARTIAL — code complete and verified; the live demo itself is blocked
Date:    2026-08-12
Commit:  `b614597`

### DoD as written
> Wipe `learner_profile`, replay traces, get the **identical** profile back — demonstrated
> live. This is the best 30 seconds of any demo; **rehearse it.**
(`BUILD_PLAN.md`, M2 DoD)

### Command run
```
python -m scripts.prove_event_sourcing
pytest -q
ruff check .
```

### Output
```
VDEL - event-sourcing proof   (BUILD_PLAN 2.6)
traces are truth; learner_profile is derived belief

  traces in the log            : 0
  profiles snapshotted         : 0

  1. SNAPSHOT   read learner_profile as stored
  2. WIPE       TRUNCATE learner_profile -> 0 rows remain
  3. REPLAY     rebuild_from_traces() for every student
  4. COMPARE    deep-diff, field by field

NOTHING TO PROVE

  No learner_profile row existed, so there was no belief to reproduce.
  'IDENTICAL' here would be true and worthless -- see decision 3 in this
  file's docstring. The database has no telemetry yet (DECISIONS.md D-006).

  rolled back - the database is exactly as it was (pass --commit to persist)

EXIT CODE: 2
```
```
pytest -q  ->  164 passed, 1 xfailed in 8.06s     (exit 0)
ruff check .  ->  All checks passed!               (exit 0)
```

### Assessment
- **"Wipe `learner_profile`, replay traces, get the identical profile back":** **not met
  live.** The mechanism is built, tested, mutation-tested, and independently verified
  (`spec-verifier`: MATCH against `VDEL_Modules_3_9_Build.md` B.1–B.8; `reviewer`: SAFE TO
  COMMIT / COMMIT WITH FIXES, both resolved) — but there is no telemetry in the database to
  wipe and replay. `prove_event_sourcing.py` correctly refuses to call an empty database a
  pass: it exits **2** with `NOTHING TO PROVE` rather than printing a vacuous `IDENTICAL`.
  That refusal is itself a designed part of the proof (decision 3 in the script's docstring)
  and is why this reads honestly as **not met** rather than as a pass with an asterisk.
- **"demonstrated live":** not met, for the same reason — there is nothing live to
  demonstrate yet. The property has been demonstrated against fixture data inside the test
  suite (`tests/test_memory.py`, `tests/test_prove_event_sourcing.py` — including a
  deliberately tampered profile, which the proof correctly caught and named field-by-field),
  which is real evidence the mechanism works, but it is not the live demo the DoD asks for.
- **"rehearse it":** not applicable yet — nothing to rehearse until there is real data to
  wipe.
- `pytest -q` / `ruff check .`: **met** — 164 passed, 1 xfailed (unchanged xfail), lint clean.

### Known gaps
- **The actual blocker is D-006, not this milestone.** `config/roster.yaml` still isn't
  configured (no real GitHub username/repos/token), so `students`/`traces`/`learner_profile`
  are all empty. M2's code has nothing to do with this gap — closing D-006 is what turns this
  entry from PARTIAL to DONE, with no further code change expected.
- **Not yet built:** the Echo Agent (`agents/echo_agent.py`, BUILD_PLAN 2.4) and the
  mastery-evolution plot (`scripts/plot_mastery.py`, BUILD_PLAN 2.5). `memory.py` (all four
  pieces: the door, the fast path, the recurrence rule, the broad rebuild) and
  `scripts/prove_event_sourcing.py` (2.6) are done. 2.2's "wire the fast path to collector
  events" is available as primitives (`update_mastery`, `apply_recurrence_rule`) but nothing
  yet calls them from a real collected event — that wiring is also gated on D-006.
- **Four historical findings, independently re-verified as resolved** (confidence freeze
  D-007, missing `session_digest`/`sessions.summary` columns D-008, the
  `rebuild_mastery_from_traces` vs. `rebuild_from_traces` naming, the two-transaction
  profile/trace write) — see `DECISIONS.md` and the `spec-verifier` pass that checked each
  against the live code and a live database rather than trusting the docstrings.
- Two bugs were caught by review *during* this work, fixed, and are not open: a note
  truncated on replay that the live path would have kept whole (piece 4), and a test's
  `skipif` that crashed collection instead of skipping without `PG_DSN` (the proof script).
  Both are DECIDED / fixed, not open gaps — named here only so the record is complete.

---

## M2 — Memory + Echo Agent (live DoD attempt, real data)

Status:  PARTIAL — the live demo ran for the first time against real data, and it found a bug
Date:    2026-08-23
Commit:  `d012ac6`

### DoD as written
> Wipe `learner_profile`, replay traces, get the **identical** profile back — demonstrated
> live. This is the best 30 seconds of any demo; **rehearse it.**
(`BUILD_PLAN.md`, M2 DoD)

### Command run
```
python -m scripts.prove_event_sourcing
```

### Output
```
VDEL - event-sourcing proof   (BUILD_PLAN 2.6)
traces are truth; learner_profile is derived belief

  traces in the log            : 3
  profiles snapshotted         : 1

  1. SNAPSHOT   read learner_profile as stored
  2. WIPE       TRUNCATE learner_profile -> 0 rows remain
  3. REPLAY     rebuild_from_traces() for every student
  4. COMPARE    deep-diff, field by field

  anas
      mastery         identical  (1 concept(s))
      weaknesses      identical  (0 entry(ies))
      reflections     identical  (0 entry(ies))
      session_digest  identical  (0 entry(ies))
      features_ref    DIFFERS    (set)
      -> DIFFERS

DIFFERENT - 1 field(s) differ

    anas  features_ref
        snapshot : None
        rebuilt  : datetime.datetime(2026, 8, 19, 2, 37, 14, tzinfo=datetime.timezone.utc)

  traces after                 : 3  (unchanged)
  rolled back - the database is exactly as it was (pass --commit to persist)
```
Reproduced identically on a second run — not a flake.

### Assessment
- **"Wipe, replay, get the identical profile back":** **not met** — reported `DIFFERENT`,
  not `IDENTICAL`, for the one real student in the system. `mastery`, `weaknesses`,
  `reflections`, `session_digest` all replayed identically; only `features_ref` diverges
  (stored `None` vs. rebuilt to a real timestamp).
- **"demonstrated live":** met in the sense that this is a genuine live run against real
  telemetry, for the first time — but the result it demonstrated is a real discrepancy, not
  the intended proof.
- **"rehearse it":** not applicable — cannot rehearse a demo that does not currently pass.

### Known gaps
- **This supersedes the previous M2 entry's "NOTHING TO PROVE" state** — real data now
  exists (student `anas`, 3 traces, 1 concept), so the proof is finally runnable, and running
  it surfaced a genuine, reproducible divergence rather than a vacuous pass.
- **Root cause not found.** Logged as `D-034` (OPEN) in `docs/DECISIONS.md`. Two live
  hypotheses, neither checked: `rebuild_from_traces` derives a `features_ref` it should not,
  or the live fast-path write silently drops one it should set.
- Same divergence breaks three tests in `tests/test_prove_event_sourcing.py`
  (`test_a_faithful_profile_proves_identical`,
  `test_a_student_with_no_prior_profile_is_reported_not_failed`,
  `test_no_profiles_is_vacuous_not_identical`) — full suite this session:
  `3 failed, 332 passed, 1 skipped, 1 xfailed`, down from the previous session's clean
  `336 passed, 1 xfailed` (no code changed between the two runs — the difference is real data
  now sitting in the shared dev database that the tests' assumptions didn't anticipate).
- Blocks every pending commit (the reviewed-and-approved M3 provider diff, and the entire
  unreviewed M4 batch) until resolved — see `docs/HANDOFF.md`.

---

## M2 — Memory + Echo Agent (Stage D1/D2 — `scripts/demo.py`, live, twice)

Status:  PARTIAL — the live demo itself now passes, twice, but the DoD command run through
         the test suite reproduces D-034 for the first time with a concrete example
Date:    2026-08-25
Commit:  `618d795` (working tree ahead: `scripts/demo.py` new,
         `scripts/render_student_repo.py` and `EXECUTION.md` modified, none committed yet)

### DoD as written
> Wipe `learner_profile`, replay traces, get the **identical** profile back — demonstrated
> live. This is the best 30 seconds of any demo; **rehearse it.**
(`BUILD_PLAN.md`, M2 DoD)

### Command run
```
python -m scripts.demo                          # full live run, Stage D1/D2
python -m scripts.demo --skip-network --skip-llm # offline run, same day
python -m scripts.prove_event_sourcing           # the DoD command in isolation
pytest -q
ruff check .
```

### Output
`scripts.demo` (full live run, abridged to Beat 7 — the other six beats are new evidence
folded into `EXECUTION.md`'s beat table, not repeated here):
```
-- Beat 7 ---------------------- wipe learner_profile -> replay traces -> identical
  traces in the log            : 27
  ...
  anas
      features_ref    identical  (set)
      -> identical
IDENTICAL
  traces after                 : 27  (unchanged)
DEMO COMPLETE
```
Reproduced a second time, offline (`--skip-network --skip-llm`), with the same result:
`IDENTICAL`, `traces after: 24 (unchanged)`.

`python -m scripts.prove_event_sourcing` run standalone, immediately after: also
`IDENTICAL`.

`pytest -q`:
```
FAILED tests/test_prove_event_sourcing.py::test_a_faithful_profile_proves_identical
AssertionError: assert [Difference(student_id='anas', path='features_ref',
  snapshot=datetime.datetime(2026, 8, 19, 2, 37, 14, tzinfo=datetime.timezone.utc),
  rebuilt=datetime.datetime(2026, 8, 25, 1, 52, 6, tzinfo=datetime.timezone.utc))] == []
1 failed, 409 passed, 2 skipped, 1 xfailed in 39.44s
```

`ruff check .`: one violation found and fixed during this pass (`scripts/demo.py:120`,
line too long) — re-run after the fix: `All checks passed!`.

### Assessment
- **"Wipe, replay, get the identical profile back — demonstrated live":** **met**, twice,
  the actual thing the DoD asks for — `scripts/demo.py`'s Beat 7 (which calls the same
  `prove()`/`report()` functions as the standalone script, not a reimplementation) printed
  `IDENTICAL` on a full live run and again on an offline re-run the same day. The standalone
  script also independently confirmed `IDENTICAL` moments later.
- **"rehearse it":** now genuinely true — this is the first session where the wipe/replay
  has actually run and passed against real data, and it ran three times in one sitting
  (live, offline, standalone) without once failing.
- **`pytest -q` clean:** **not met** — one failure. CORRECTION while writing this entry:
  I initially attributed it to `D-034`, but `D-034` (`docs/DECISIONS.md`) is marked
  **RESOLVED**, not OPEN — fixed 2026-08-23 by adding `Memory.sync_features_ref()`, wired
  into `dags/vdel_pipeline.py`'s `update_profiles` task. That citation was wrong; see
  below for what this failure actually is instead.

### Known gaps
- **A new, `D-034`-shaped drift, not a reopening of `D-034` itself.** `anas`'s
  `learner_features` table gained a real second row this session
  (`computed_at = 2026-08-25 01:52:06+00`, seven seconds after this session's own
  `d818c872b5` collector pickup), but `learner_profile.features_ref` still reads
  `2026-08-19 02:37:14+00` — the OLD row. That means `sync_features_ref()` was not called
  for this `compute_features` run, which is exactly the asymmetry D-034 fixed for the
  `update_profiles` DAG task specifically. **Not caused by anything in this session's own
  tool calls** — checked directly: no module this session ran (`scripts/demo.py`,
  `collect_all`, `grade_attempt`, `code_agent.grade`) imports `features.compute_features`
  at all; only `dags/vdel_pipeline.py` and the test suite do. So something else — most
  likely `compute_features` run directly, bypassing the DAG task wrapper `sync_features_ref`
  is wired into — produced that row outside this session's visibility. **Asked Anas
  directly** (see the message this entry accompanies) rather than guessing which path it
  was, since attributing a live-data question to the wrong code path would be exactly the
  kind of thing `D-034`'s own postmortem warns against (patch the symptom, not the cause).
  The live demo itself is unaffected today — both real runs of `scripts/demo.py` showed
  `features_ref identical`, because neither run re-triggered `compute_features` after the
  drift already existed — but the failing test proves it's real, not hypothetical, and
  worth root-causing before D2's final rehearsal.
- `student2` and `_test_runner` both appear in `prove()`'s "no prior profile; the rebuild
  created one" list. `student2` is expected (real second demo student, fast path not run
  for them yet). `_test_runner` is not — it matches no real student and is very likely
  permanent test-suite trace pollution in the shared dev database (`traces` cannot be
  DELETEd — see this session's `docs/reading/2026-08-25-memory-llm-mastery-wiring.md`,
  Finding 3). Flagged, not cleaned up — deciding whether/how to purge it safely is a
  separate task.

---

## M1 — Telemetry + Features (the three previously-unmet clauses, closed live)

Status:  PARTIAL — two clauses now genuinely demonstrated; one is ambiguous against the
         current schema and needs a decision, not a guess; one is blocked on missing
         infrastructure, not on code
Date:    2026-08-25
Commit:  `618d795` (working tree ahead, uncommitted — see this session's other changes)

### DoD as written
> The DAG runs green end to end · one `learner_features` row per repo · **a deliberate
> re-run changes nothing** (idempotency proven) · Sara's numbers match the hand
> computation · the classifier match rate is recorded.
(`BUILD_PLAN.md`, M1 DoD)

### Command run
```
# idempotency — queried learner_features before, ran twice, queried after each
docker exec vdel-postgres psql -U vdel -d vdel -c "SELECT student_id, computed_at FROM learner_features ORDER BY computed_at;"
python -m features.compute_features
python -m features.compute_features
docker exec vdel-postgres psql -U vdel -d vdel -c "SELECT student_id, computed_at FROM learner_features ORDER BY computed_at;"

# classifier match rate
python -m scripts.collect

# the DAG itself
python -c "import airflow"

# always
pytest -q
ruff check .
```

### Output
```
before:  anas | 2026-08-19 02:37:14+00
         anas | 2026-08-25 01:52:06+00

RUN 1:   1 student(s) with activity since 1970-01-01T00:00:00Z
         anas: 3 concept(s) in mastery
after 1: anas | 2026-08-19 02:37:14+00      <- unchanged
         anas | 2026-08-25 01:52:06+00      <- unchanged

RUN 2:   1 student(s) with activity since 1970-01-01T00:00:00Z
         anas: 3 concept(s) in mastery
after 2: anas | 2026-08-19 02:37:14+00      <- unchanged
         anas | 2026-08-25 01:52:06+00      <- unchanged
```
```
$ python -m scripts.collect
collecting 6 repo(s)
api_calls=27 detail_calls=0 commits=0 runs=46 commits_without_open_attempt=0
classified=21 match_rate=0.429
```
```
$ python -c "import airflow"
ModuleNotFoundError: No module named 'airflow'
```
```
$ pytest -q
FAILED tests/test_prove_event_sourcing.py::test_a_faithful_profile_proves_identical
1 failed, 409 passed, 2 skipped, 1 xfailed in 39.07s

$ ruff check .
All checks passed!
```

### Assessment
- **"A deliberate re-run changes nothing" (idempotency):** **met, directly** — not by proxy
  through a test's internal assertion this time. Queried `learner_features` before two
  back-to-back real `compute_features` runs and after each one; the row set (2 rows, same
  `computed_at` watermarks) was byte-identical all three times. This also answers, in part,
  last turn's open question about the mystery `2026-08-25 01:52:06` row: it was **already
  there** before these two runs, and running the pipeline again did not add a third row or
  change it — consistent with the watermark-based idempotency `explanation.md` §7.2
  describes, but it does not say who/what created that row originally. Still asking.
- **"The classifier match rate is recorded":** **met** — `match_rate=0.429` (21/49
  classified), from a real `scripts.collect` run against the live roster, printed above,
  not estimated.
- **"One `learner_features` row per repo":** **not assessed — genuinely ambiguous, not
  guessed.** The live schema (`sql/03_feature_tables.sql`, `PRIMARY KEY (student_id,
  computed_at)`) computes one row per **student** per run, aggregated across however many
  repos that student has — not one row per repo. `anas` has 2 real repos with telemetry
  (the legacy kaggle-pipeline pair) plus the new curriculum repo, and exactly 2
  `learner_features` rows exist, but the second is a second **run** (a new watermark), not
  a second **repo** — the two numbers matching here looks like it could be coincidence, not
  a mapping. Per this skill's own instruction ("if the DoD is ambiguous, stop and ask
  rather than choosing an easier reading"), this is left unresolved rather than forced to
  a reading that happens to fit today's data. **Needs a decision**: was "per repo" written
  against a schema this project no longer has (multi-repo-per-assignment came later, D-043),
  and should the clause now read "per student"?
- **"The DAG runs green end to end":** **not met — blocked on missing infrastructure, not
  a code defect.** `airflow` is not installed in this environment at all
  (`ModuleNotFoundError`), so `dags/vdel_pipeline.py` cannot be executed as a DAG here, full
  stop. Every real thing the DAG's three tasks do has been exercised directly and proven
  live this session, just not through Airflow itself: `_collect` is `scripts.collect`'s own
  body (run live, above); `_compute` is `features.compute_features.run` (run live, above,
  twice); `_update_profiles` is `Memory.sync_features_ref` per student (the exact function
  at the center of the open `features_ref` question in this file's M2 entry). Installing
  `apache-airflow` was not attempted without asking first — it is a large dependency
  tree and a real environment change, and the seven demo beats (`EXECUTION.md` §1) do not
  depend on Airflow at all; `scripts/demo.py` calls every function directly.
- **"Sara's numbers match the hand computation":** already met (2026-08-11 entry, unchanged).

### Known gaps
- The "one row per repo" ambiguity above is a real open question, not a defect — flagging
  for Dr. Ezzatul or Anas to resolve, not resolving it unilaterally.
- The DAG clause stays NOT MET until either `airflow` is installed and it's actually run,
  or the DoD is explicitly relaxed to "the three task bodies, exercised directly" — that is
  a scope decision, not something to assume.
- `pytest -q`'s one failure is the same open `features_ref` drift already logged in this
  file's M2 entry above — not repeated in full here, not a new M1 issue.

---

## M3 — LLM Gateway + Benchmark

Status:  NOT DONE (the benchmark half — the gateway half is separately proven live, see the
         M2 2026-08-25 entry above and `EXECUTION.md` §3.2)
Date:    2026-08-25
Commit:  `618d795`

### DoD as written
> Re-running the benchmark reproduces the matrix. (`BUILD_PLAN.md` M3, per this skill's
> milestone-specific notes)

### Command run
```
ls benchmark/
```

### Output
```
benchmark/
  submissions/   (broken.py, clean.py, copy_paste.py, inefficient.py, subtly_wrong.py)
  TASK.md
```
No `ground_truth.json`, no `run_benchmark.py`, no `RECOMMENDATION.md`.

### Assessment
- **Not a code failure — there is no command to run yet.** `run_benchmark.py` does not
  exist. This is `EXECUTION.md` Stage C3, explicitly blocked on Anas's own labels for the
  5 real submissions above (`CLAUDE.md`'s own words: "his to decide, not a model's"), not
  on anything buildable without him.

### Known gaps
- Nothing to add beyond `EXECUTION.md` §4 Stage C3 and the M2/D-049 entries, which already
  cover the gateway itself (real, live, proven — the part of M3 that IS done).

---

## M4 — Code Agent

Status:  NOT DONE (the stability-table clause specifically — the judge itself has graded
         real submissions live, see the M2 2026-08-25 entry above)
Date:    2026-08-25
Commit:  `618d795`

### DoD as written
> The stability target is met, **or** the deviation is documented with its cause analysed
> · the copy-paste-looking submission does **not** fool correctness scoring · every
> verdict carries evidence that string-matches. (`BUILD_PLAN.md`, M4 DoD)

### Command run
```
ls benchmark/*.json benchmark/run_benchmark.py 2>&1
```

### Output
```
No such file or directory
```

### Assessment
- **"Every verdict carries evidence that string-matches":** **met, independently** —
  D-049's two live runs (`trace_id=48238`, `trace_id=49505`) both had every evidence quote
  checked against the real submitted file text by a second, separate pass, not just an
  empty `evidence_failures` list trusted alone.
- **"The copy-paste submission does not fool correctness scoring":** **not assessed** —
  needs `benchmark/copy_paste.py` actually graded and compared; not run this pass.
- **"The stability target... or the deviation documented":** **cannot be measured at
  all** — BUILD_PLAN 4.5's stability table needs 3 runs per benchmark submission against
  `ground_truth.json`, which does not exist (same Stage C3 blocker as M3, above).

### Known gaps
- Same root blocker as M3: Stage C3, Anas's own labels. Everything downstream of that
  (the stability table, the copy-paste check against ground truth) is genuinely unbuildable
  until then — not a scheduling gap, a data gap only he can close.

---

## M3/M4 — Stage C3 built and run for real; the free tier's daily cap is the actual blocker

Status:  NOT DONE (both, unchanged) — but for a sharper, now-measured reason, not a missing
         script
Date:    2026-08-25
Commit:  `618d795` (working tree ahead — `benchmark/run_benchmark.py`,
         `benchmark/ground_truth.json` both new, uncommitted)

### DoD as written
> M3: re-running the benchmark reproduces the matrix. M4: the stability target is met, or
> the deviation is documented with its cause analysed · the copy-paste submission does not
> fool correctness scoring · every verdict carries evidence that string-matches.
(`BUILD_PLAN.md`, M3/M4 DoD; this skill's own M3/M4 notes)

### Command run
```
python -m benchmark.run_benchmark --runs 1 --only clean.py   # smoke test, x2 (1 fix landed between)
python -m benchmark.run_benchmark --runs 3                   # the real sweep, 15 calls
pytest -q
ruff check .
```

### Output
Full literal output is long (15 real call attempts); see `docs/DECISIONS.md` D-050 for the
complete record. Summary: **1/15 calls succeeded, 14/15 failed** — 13 `quota_billing`
(`gemini-3.7-flash`: `GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue: 20`,
exhausted by this session's cumulative real calls before the sweep even started), 1
transient `ServerError`. The sweep completed end to end (did not crash) and rolled back
cleanly — confirmed `SELECT student_id FROM students WHERE student_id='_benchmark'` returns
0 rows after every one of five real runs this session, including two that hit real bugs.
```
pytest -q  ->  410 passed, 2 skipped, 1 xfailed  (unchanged)
ruff check .  ->  All checks passed!
```

### Assessment
- **M3 "re-running reproduces the matrix":** **not met** — not because reproducibility is
  broken, but because there is no matrix yet to reproduce; 1 real verdict is not a matrix.
- **M4 "stability met, or deviation documented with cause analysed":** **the deviation
  branch, met.** The cause is analysed and real: a 20-request/day/model free-tier cap, not
  judge instability — only one real verdict was ever produced this session to be unstable
  against. This is the DoD's own explicitly sanctioned legitimate outcome, not a failure
  dressed up as one.
- **"Copy-paste doesn't fool correctness scoring":** **not assessed** — needs a successful
  verdict on `copy_paste.py` specifically; all 3 of its attempts hit the quota wall.
- **"Every verdict carries evidence that string-matches":** **met, again** — the one real
  verdict this sweep produced (`broken.py`, run 3, `trace_id=53096`) came back with real
  `evidence_failures` (an unmatched quote, a missing-evidence flag) — the validation
  pipeline working exactly as designed, catching its own judge's imperfect evidence rather
  than trusting it.

### Known gaps
- **The real next step, not attempted this session:** either set `ANTHROPIC_API_KEY` (a
  second, separately-quota'd provider — this also closes M3's "two providers" DoD clause
  for real) or re-run the sweep on a later day against a fresh daily quota. `D-050` records
  both options; neither was chosen without asking.
- `benchmark/ground_truth.json` is unaffected by any of this — every score is `null` because
  Anas hasn't read the five submissions yet, not because of API access. Filling it in has no
  dependency on the quota issue at all.
- Two real bugs were caught and fixed live during this work, both now closed (see D-050):
  a `ForeignKeyViolation` from an unverified schema assumption, and a single-call exception
  that used to kill the entire sweep. Neither is an open gap; named here only for completeness.

---

## The DoD clauses most likely to be skipped

Listed here because each is easy to assert and slightly annoying to demonstrate, which is
exactly the profile of a clause that quietly becomes a claim:

- **M0** — "on a machine that has never seen this project." Not your machine with a warm
  Docker cache. At minimum, `docker compose down -v` first.
- **M1** — "a deliberate re-run changes nothing." Run the pipeline twice; diff the
  `learner_features` rows; show the diff is empty.
- **M1** — "the classifier match rate is recorded." A number, in this file.
- **M2** — the demo must be **rehearsed**, not just working. Note the rehearsal date here.
- **M3** — "re-running the benchmark reproduces the matrix." Twice, both recorded.
- **M4** — "≥80% exact agreement **or** the deviation documented with its cause analysed."
  The second branch is a legitimate pass. Record the real number either way.
