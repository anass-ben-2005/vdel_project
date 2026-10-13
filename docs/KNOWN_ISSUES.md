# KNOWN_ISSUES.md -- what is wrong or missing in v1, written down so it is not a surprise

Each entry: what it is, the impact, the workaround that exists today, and where it is recorded.
"Not verified" means nobody ran it. Nothing here is a plan: the planned fixes are in the
`Later` lists of the decisions cited. Added 2026-10-13 (D-105); facts about the live database were
read with a read-only `SELECT` on that day.

## Data and grading

### 1. `attempts.closed_at` does not exist
- **Impact.** An attempt that was superseded or abandoned stays open (`submitted_at IS NULL`). The
  grader lets an OPEN attempt win over a FROZEN higher one (`grade_collected._target_attempts`), so a
  stale open attempt 1 keeps receiving commits that belong to a frozen attempt 2. It is the reason
  `deliver_next_attempt --force` needs `--i-understand`.
- **Workaround.** Do not use `--force`. Deliver attempt N+1 only after attempt N is frozen (its hidden
  tests reached 100% on a pushed commit). Ten attempts are open in the live database today; that is
  the normal state of an attempt that is not finished, not a symptom.
- **Recorded.** D-072, D-090 (`Later`), `docs/OPERATIONS.md` section 8.

### 2. A commit dated in the future hides every later commit
- **Impact.** The collector asks GitHub only for commits newer than the largest stored
  `committed_at`, which is the COMMITTER date and is chosen by the student. One commit dated in the
  future moves that point past every honest later commit, which then stop being collected and graded.
  The live database has no future-dated commit today (`SELECT ... WHERE committed_at > now()` returned
  no row).
- **Workaround.** When a student says "I pushed and nothing happened", run
  `SELECT max(committed_at) FROM raw_commits WHERE student_id = 'X'` first. No script in this
  repository repairs a poisoned point: the fix proposed in D-093 (re-list without `since`, or clamp a
  future date to the collection time) is not built. Not verified: what it takes to recover by hand.
- **Recorded.** D-093 (b), pinned by `tests/test_collector_known_limits.py`, `docs/OPERATIONS.md` section 10.

### 3. A force-push is graded as new work
- **Impact.** Rewritten commits have new shas, so they are collected and graded again; their new
  `test_results` rows make V5 and V6 count the same work twice. The mastery observation does not
  (the first-attempt observation of an (attempt, gap) is immutable, D-079). A rewritten or back-dated
  commit whose date is not newer than the stored maximum is never collected at all. Whether GitHub
  still serves the orphaned old sha is not verified.
- **Workaround.** None built. Read the commit list of a student whose V5/V6 jumps. D-093 lists the
  fixes (do not trust the committer date, flag `forced` pushes, store the graded blob sha).
- **Recorded.** D-093 (b).

### 4. A deleted repository makes the cycle report the student FAILED every hour
- **Impact.** `run_cycle` exits 1 for that student each run with the same 404 until the roster row is
  fixed; commits already collected but not graded fail at checkout every cycle. Graded work is untouched
  and no other student is affected.
- **Workaround.** Fix or remove the student's roster rows (`scripts/roster_apply.py` edits a row;
  removing one is by hand). The roster has no `archived` field.
- **Recorded.** D-093 (b), `docs/OPERATIONS.md` section 10.

### 5. Commits with no assignment (`assignment_id IS NULL`)
- **Impact.** A commit that touches no assignment file, or files of several, is stored but not graded.
  Read on 2026-10-13, the live database has four such rows: two template pushes
  (`Initial commit: weather_etl gapfill for ...`, anas and student2) and two `ci: sync template (D-060)`
  commits of anas. The request that asked for this entry says three; I did not find which three it
  means and list all four. Under formula v8 the template push and the sync commits are not student
  actions (D-098, D-060), so they do not enter V3, V6 or the feedback.
- **Workaround.** None needed for those four. A genuine student commit with a NULL attribution would be
  silently ungraded: `run_cycle --dry-run` prints how many unattributed commits it sees.
- **Recorded.** D-043, D-098, `scripts/grade_collected.py` (module docstring).

### 6. Several formula versions live side by side; "v9" does not exist in the repository
- **Impact.** `learner_features` keeps every row with the `formula_ver` it was computed with, so rows
  of v2, v3, v5, v7 and v8 coexist for the two live students (`python -m scripts.baseline`). The code
  computes `FORMULA_VER = "v8"` (`features/compute_features.py:100`). A "formula v9" is not mentioned in
  the code or in `docs/DECISIONS.md`: I found nothing to describe and did not invent it. If v9 is a
  planned change, it needs a decision entry before it is built.
- **Workaround.** Compare features only within one `formula_ver`.
- **Recorded.** D-063 and following (`compute_features.py` comments), D-084, D-088, D-098.

### 7. `unclassified` errors in V5 and V6
- **Impact.** The CI error classifier left 12 of 21 real failures `unclassified` (match rate 0.429,
  measured 2026-09-02). Unclassified errors update no mastery (invariant 10) but they are counted in
  V5/V6 as a concept of their own, which is a finding, not a fix.
- **Workaround.** Extend `collectors/error_classifier.py` from the observed logs.
- **Recorded.** `docs/STATUS.md` (M1, 2026-09-02), D-096.

## Grading safety

### 8. Student code runs on the operator's PC unless the container is on
- **Impact.** By default the hidden tests run in a subprocess with a stripped environment. Acceptable for
  one trusted student, not for a pilot of 3 to 5.
- **Workaround.** Build `vdel-grader:1` and set `VDEL_GRADING_SANDBOX=docker` (`-UseDockerGrading` on the
  task). `python -m scripts.doctor` reports whether the image exists and whether the task uses it.
- **Recorded.** D-086, D-092, `docs/OPERATIONS.md` section 11.

### 9. A student's code can forge the grade from inside the test process
- **Impact.** The student's module is imported by the hidden test, in either mode, so it can patch pytest
  or the JUnit report it can reach. Isolation cannot fix it. The hidden test file also sits next to the
  code it grades.
- **Workaround.** None. A second signal (differential execution, D-036) is not built.
- **Recorded.** `docs/OPERATIONS.md` section 11 ("What the container still does NOT protect").

### 10. ruff and sqlfluff obey a configuration file placed beside the file they lint
- **Impact.** Found while hardening the Code Agent (D-103): ruff 0.16.1 reads a student's `ruff.toml`,
  `.ruff.toml` or `pyproject.toml` beside the linted file, and sqlfluff 4.2.2 imports the Python module that
  a student's `library_path` names, so linting a checkout in place would let the student switch rules off
  or run code. Both linters now run on a private one-file copy in an empty temporary directory, with
  `--isolated` (ruff) and `--ignore-local-config` (sqlfluff), in the Code Agent and in the V2
  measurement (`assessment/lint_scope.py`).
- **Workaround.** Keep that: never lint a student's file in place, and never remove the isolation flags
  (`tests/test_code_agent_hardening.py` has a structural test, because the behavioural tests alone did
  not catch the removal). The repository's own `ruff check .` is governed by `pyproject.toml` and excludes
  `curriculum/` and `benchmark/submissions/` on purpose.
- **Recorded.** D-103 item 2.

## The agents

### 11. The Code Agent is an unmeasured judge
- **Impact.** Its verdict is stored (`--with-code-agent`) and never posted. The benchmark ground truth
  was pre-labelled by an LLM and reviewed by a person on 10 rows only; its files' docstrings reveal the
  planted bug; `benchmark/TASK.md` is missing; no `weather_etl` labels exist. The one real run
  (`benchmark/RECOMMENDATION.md`) measured one provider on five PySpark files.
- **Workaround.** Read `scripts/code_agent_report.py` as an internal aid; do not act on a score.
- **Recorded.** D-102, D-103, D-104, `benchmark/RECOMMENDATION.md` section 7.

### 12. `config/judging.yaml` has no task statement
- **Impact.** `statement` is null for the four `weather_etl` assignments, so the judge is told only the
  gap instructions. `sales_analyzer_*` has no entry and is judged on all four criteria, including
  "Idiomatic Spark/SQL".
- **Workaround.** The course author's statements (Dr. Ezzatul or Hanafi). `config/judging.yaml` now holds
  DRAFT statements for the four `weather_etl` stages (D-107); a draft is ignored by the loader, so nothing
  changes until a person marks one `reviewed`.
- **Recorded.** D-103 item 3, D-104 (CONFIRM 2).

### 13. LLM budgets are counts of calls, not money, and the ledger has no lock
- **Impact.** The caps (10 per run, 20 per day by default) count provider calls; a failed fallback attempt
  is not seen by the budget, which is why the cycle also wraps the provider handlers in a hard cap
  (D-104). Two processes writing `.vdel/llm_usage.json` at the same moment can lose an update. Prices are
  not in the repository, so no cost is computed unless passed on the command line.
- **Workaround.** Do not run two cycles at once (the advisory locks already stop that for `run_hourly`).
- **Recorded.** `docs/agents.md` sections 8 and 12, D-104.

### 14. Failure messages are not byte-stable and are never shown
- **Impact.** pytest prints dict differences in an order that changes between runs; only the first line
  of a stored failure message is stable. Students see the test name and the exception type, never the
  message (D-077).
- **Workaround.** None needed.
- **Recorded.** `docs/OPERATIONS.md` section 11.

## Operations

### 15. The scheduler scripts are Windows-only
- **Impact.** `scripts/windows/register_task.ps1` registers a Task Scheduler task; there is no cron or
  systemd equivalent in the repository. The PC must be on, logged in and running Docker.
- **Workaround.** Run `python -m scripts.run_hourly` from cron; `docs/INSTALL.md` section 11 gives the line
  (not verified).
- **Recorded.** D-091, `docs/OPERATIONS.md` section 10.

### 16. Airflow has never run here
- **Impact.** `dags/vdel_pipeline.py` exists but `airflow` is not installed, so the M1 clause "the DAG runs
  green end to end" is unmet. The hourly task replaces it in practice.
- **Workaround.** `requirements-airflow.txt` (a separate environment, Python 3.11).
- **Recorded.** `docs/STATUS.md`, M1 (2026-08-25).

### 17. Test-suite trace pollution in the development database
- **Impact.** `traces` cannot be deleted, so students named `_test_runner` and similar from early runs
  stay in the shared development database and appear in the event-sourcing proof as "no prior profile".
- **Workaround.** None; it is cosmetic. The suite itself runs on a throwaway `vdel_test` database
  (D-064) and never connects to `vdel`.
- **Recorded.** `docs/STATUS.md`, M2 (2026-08-25).

### 18. Open items that need a person
- `student2` has a placeholder GitHub login: posting and delivery are refused for it.
- Consent and data protection for a 3 to 5 student pilot are not written (Stage 6 drafts a notice for
  review).
- A template-push column on `raw_commits` was proposed instead of recognising it by message (D-098).
- Hanafi's hints (D-077) are not wired.

### 19. A duplicate gap id in another file silently re-points a gap
- **Impact.** `gaps.gap_id` is the primary key and the seeder upserts with `ON CONFLICT (gap_id) DO UPDATE`,
  while the parser only rejects a duplicate id inside one file. Two stages (or projects) sharing an id would
  leave one gap pointing at the wrong assignment, with no error. No such duplicate exists today.
- **Workaround.** `python -m scripts.validate_master` checks ids across the whole curriculum (D-107); run it
  before seeding a new master.
- **Recorded.** D-106 finding (a), D-107.

### 20. One Docker test failed once in a full run
- **Impact.** In the stage-3 gate, `tests/test_grading_container.py::test_an_infinite_loop_times_out_and_the_container_is_killed`
  failed once in a full suite run (`leftover_containers()` found `vdel-grade-513b8dc2ed196cb8`), then passed in
  the rerun of that file (24 passed) and in a second full run (1461 passed). No container was left afterwards
  (`docker ps -a --filter name=vdel-grade-` empty). My reading, not verified: the check ran while Docker was
  still removing the killed container (`assessment/test_runner.py` kills it, then `docker rm -f`), under the
  load of a full run. If the code path ever leaves a container behind, the symptom is the same.
- **Workaround.** Rerun the file; after any failure look at `docker ps -a --filter name=vdel-grade-` and remove a
  leftover by hand.
- **Recorded.** D-107 (gate), this file.

### 21. The v2 Feedback Agent has never met a real model
- **Impact.** `--agents-v2` (D-108) is tested only against the scripted fake provider. How often a real model
  passes its validator (quotes, no code, no copy of the solution, no repeated counts) is unknown; every
  rejection costs one more call and ends in the deterministic text. The thresholds (100 and 60 characters,
  4-grams at 25%, 4000 characters of excerpt, the 1/2/3 ladder) are design choices, not measurements. While the
  fifteen check descriptions are `draft`, level 1 has no expected-behaviour sentence.
- **Workaround.** Try it by hand on one student (`docs/OPERATIONS.md` section 16) and read the log lines
  `feedback_agent_v2=...`; a high share of `deterministic_v0_fallback` means the thresholds or the prompt
  need to move. Review the descriptions in `config/checks.yaml`.
- **Recorded.** D-108.

### 22. Fixed while writing this file
- `RequestsDependencyWarning` on every import: a stray `chardet` 7.x with `requests` 2.32.3.
  `requirements.txt` now pins `chardet>=5.2,<6`; on a machine that already has 7.x run
  `pip install "chardet<6"` (the environment was not changed by this work).
- Three tests asserted that the repository's `.vdel/` directory does not exist, so they failed as soon
  as a real LLM call had created the ledger. They now compare its state before and after
  (`tests/support.vdel_dir_state`).
- An open attempt with no matching roster repo was silent (attempt 3 of `weather_etl_extract`). `run_cycle`
  and `run_hourly` now log a `WARN` line for it.
