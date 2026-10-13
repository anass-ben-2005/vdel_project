# CLEANUP_PLAN.md -- analysis only

Branch `cleanup` from `main` at `df9f2b8689365950fcba0d7bfa62eed7ef40a1b1`. **Nothing in this branch changes code, deletes, or renames.** This file is the only thing written; the Decision column is yours.

Rules followed: no network, no LLM call, no GitHub write, real database read-only (`scripts.baseline` is `readonly=True`; the test suite uses its own `vdel_test`), `.env` not read, the real `config/roster.yaml` not edited, the scheduled task not registered/enabled/disabled/started, nothing pushed or merged. `benchmark/RECOMMENDATION.md` was already modified in the working tree before this task and is untouched and not part of this commit.

## 0. Reference snapshot

Stored OUTSIDE the repo: `C:\Users\ASUS\AppData\Local\Temp\vdel_snapshot.4530Hv`

| Item | Result | File in the snapshot |
|---|---|---|
| `git rev-parse HEAD` | `df9f2b8689365950fcba0d7bfa62eed7ef40a1b1` | head.txt |
| `git status --short` at start | ` M benchmark/RECOMMENDATION.md` only | status.txt |
| `python -m scripts.baseline --full` | exit 0, database `vdel`, sha256 of the output `5e9d1a8f35e60498...` | baseline_full.txt |
| full suite `VDEL_REQUIRE_DB=1 python -m pytest -q` | `1572 passed, 3 skipped, 1 xfailed, 5 warnings in 517.19s (0:08:37)` (exit 0) | pytest.txt |
| `ruff check .` | `All checks passed!` | ruff.txt |
| `ruff check --select F401,F811,F841,F821 --no-cache .` | `All checks passed!` (0 findings) | (printed, not saved) |
| `python -m <module> --help` | 30 modules (28 in `scripts/`, 2 in `benchmark/`), all exit 0 | help/ |

**Prompt templates** (sha256 of the file and of every module-level string over 150 characters):

```
FILE agents/prompts.py  ae3d0f9c51a26635b73e3ccc7307eb591d4345d66b1ad443404a834fdcd6352e
FILE agents/feedback_prompts.py  9d67c1d0a59b6972d1557fc76aaf1885a67104fa1f918254eb5715aa02fe1d42
FILE agents/PROMPT_CHANGELOG.md  b19e665994e2013910c69e9846c75ba812a78b07997fb214f9d5fc3e282f3548
agents.prompts.OUTPUT_SCHEMA_BLOCK  0d960689b4d7c55508c3a1292c3bca55e2be9bbfaf75440a2ea8c3546f5014c1  len=666
agents.prompts.RUBRIC_TABLE  b825e43473cffbd2bed1db17398d7d96138ac561dd84c899594701cf6e321cf1  len=749
agents.prompts.SYSTEM_PREAMBLE  1b07654e9d894332f0d127f75f8074fd6028323481c8c6fc692621a56f367424  len=615
agents.prompts._CORRECTNESS_NOTE  a540ada3bc0ca500518e031f9a43b0d6c702accd5085065431a83ebf36e420ad  len=188
agents.prompts._EVIDENCE_RULE  012250aea0b18894b049e76d856c5711abcf7748460252ed8656d184a75f27d1  len=474
agents.prompts._FIELD_ORDER_NOTE  7aa74ecd5656122df247f5c3fd5c3475166aded6aaf55334a7827f78040b07db  len=248
agents.prompts._FIELD_ORDER_NOTE_PRODUCTION  95a34046dcc6012469e2f8517d9d6cb1879ad28689d0ab89bea10f6f4ed75104  len=163
agents.prompts._INJECTION_RULE  0ebcb56a17bd6fac49165cfbffba3e8602e6420dcb30b43c49caf4149ca3059b  len=624
agents.prompts._PRODUCTION_NOTE  03a56afa81598351dff676c489c58958684c92ff2cbb8a9cbf79fe1c55e7b464  len=284
agents.prompts._RUBRIC_HEADER  253a2920815f1652fc364affe39760aa347e3543e5f3c6f2e261b3f7427c5a15  len=181
agents.prompts._SCHEMA_TAIL  1fdb7602804287560fd23f3b46c5b1451662389c77b7767e33acc88dc6e46f36  len=205
agents.feedback_prompts.OUTPUT_SCHEMA_BLOCK  99ada631168451175e59c76e2c64276822cc66e451ef060063e17af303fa5ec1  len=458
agents.feedback_prompts.OUTPUT_SCHEMA_BLOCK_V2  61d415922aed9a6f794277c3a0a671581b419330f32620a3769e3eb655a557c2  len=517
agents.feedback_prompts.SYSTEM_PREAMBLE  870bad8b1ae79814d7946f6dc28e4efd31898b6f3671bedda195c38b9a3d57df  len=1397
agents.feedback_prompts.SYSTEM_PREAMBLE_V2  ca246409a49fd3e6ebe45204da193a2372e4e7f6a5bff57a4b7d82c3643e5fa1  len=1834
```

**Scheduled-task command** (decoded from the `-EncodedCommand` that `scripts/windows/task_command.ps1` actually generates; python path stubbed to `C:\Python\python.exe`, folder = this repo):

| Mode | run_hourly line | env set | sha256 of the decoded script |
|---|---|---|---|
| no flags | `python -m scripts.run_hourly` | PYTHONIOENCODING only | `f0cc6aa8d0d4e029...` |
| `-WithLlm` | `... run_hourly --with-llm` | + `LLM_PROVIDER=openai` | `1eb19e1131cac478...` |
| `-WithLlm -WithCodeAgent` | `... run_hourly --with-llm --with-code-agent` | + `LLM_PROVIDER=openai` | `76a09713c862f9cd...` |
| `-WithLlm -WithCodeAgent -AgentsV2` | **NOT PRODUCIBLE** | | `New-HourlyTaskScript` has no `-AgentsV2` parameter: PowerShell reports no matching parameter. Logged and skipped, not worked around. See question Q8. |

## 1. Method, scope and limits

* **Scope:** `git ls-files` only (267 tracked files: 195 `.py`, 29 `.md`, 12 `.json`, 11 `.sql`, ...). Untracked/ignored data (`backups/`, `logs/`, `renders/`, `.vdel/`, `.env`, `config/roster.yaml`, every `*.bak`, `benchmark/results/`, `check_assignments.py`, `agents_scratch_test/`) is not analysed and appears nowhere below as a candidate.
* **Tools:** `vulture` and `coverage` are not installed. Used instead: `ruff` F401/F811/F841/F821 (0 findings) and an own AST script (`tools/analyse.py` in the snapshot folder). For every top-level function, class and constant in the 951 definitions of non-test, non-`curriculum/`, non-`benchmark/submissions/` modules it finds references as AST `Name`/`Attribute`/import-alias nodes (outside the definition's own body, so recursion does not count), then re-runs to a fixpoint treating references that sit inside an already-dead definition as dead.
* **Dynamic references:** `git grep -n -E "importlib|__import__|getattr\(|globals\(\)|entry_points"` over non-test code finds only `getattr(obj, "attr", default)` on payload/result objects; none dispatches to a project function by name. The string hits shown below are docstring/comment mentions, not dispatch.
* **Limits (all biased toward KEEP):** matching is by name, so a common name used as an attribute elsewhere hides a dead definition; **class methods and nested functions were not analysed** (the request covers top-level items); test-only helpers inside `tests/` were not analysed.

## 2. Unused code (top-level functions, classes, constants)

Result: **951 definitions analysed; 18 have no non-test code reference; 21 more are referenced only from inside those 18** (chains), for 39 in total. Every other definition has a live non-test reference. The 39 fall into 9 rows below. Counts are `git grep -n -w -I -- NAME` hit lines, definition line excluded, split as code(non-test .py) / tests / docs(.md) / other.

| # | Item | Where | Kind | Who references it | Evidence (command, then code/tests/docs/other) | Class | Risk | Decision |
|---|---|---|---|---|---|---|---|---|
| U1 | `_failure_log` | collectors/collect_github.py:151 | function | **nobody in code, nobody in tests.** Only prose: explanation.md:378 and :2388 describe it, DECISIONS.md:3062 (D-067, append-only history) says it was replaced by `_fetch_failure_log`/`_log_needs_work`. Its own docstring says "kept for callers/tests that only want the text"; there are none. | `git grep -n -w -- _failure_log` -> 0 / 0 / 3 / 0 (a doc line in explanation.md must change in the same commit) | DELETE-SAFE | low | |
| U2 | `post_comment` | scripts/post_feedback.py:295 | function | tests only: tests/test_post_feedback.py:277-285 (`test_posting_is_refused_unless_the_flag_and_the_env_var_are_both_set`, which also tests the `--post` CLI gate through `pf.main`). The CLI never reaches it (module docstring: "OLD COMMIT-COMMENT PATH ... the CLI never reaches it"). Real-write path guarded by `VDEL_ALLOW_FEEDBACK_POST`. | `git grep -n -w -- post_comment` -> 1 / 3 / 2 / 0 (the test also covers the `--post` flag and `require_enabled`, which `main` still uses at :635; only the `post_comment` lines of that test would go) | DELETE-WITH-ITS-TESTS | low | |
| U3 | `generate` | system/llm.py:407 | function (public gateway entry) | tests only (25 hit lines in tests/test_llm*.py, test_agents_fake_llm.py); `FakeLLM.generate` exists solely to raise `GenerateForbidden` (agents must call `judge`). No agent, script or benchmark calls it. It is the only entry with a caller-chosen temperature; DECISIONS.md:658-725 explains the judge/generate split. | `git grep -n -w -- generate` -> 17 / 29 / 12 / 0 (shared-contract module; invariants 3/4) | ASK | medium | |
| U4 | `FakeLLM`, `valid_json`, `fenced_json`, `invalid_json`, `truncated_fence`, `provider_error`, `slow` (+ `FakeCall`, `GenerateForbidden`, `ScriptExhausted`, `HARNESS_TIMEOUT_S` only used inside `FakeLLM`) | agents/fake_llm.py:54-245 | test harness | tests (172 hit lines for `FakeLLM` alone); documented in CONTRIBUTING.md and docs/agents.md as the way to test without a provider; named in agents/code_agent.py:270, feedback_agent.py:332, scripts/llm_first_call.py:170 and run_cycle.py/run_hourly.py docstrings. Not production code, but a supported public test seam. | `git grep -n -w -- FakeLLM` -> 9 / 181 / 5 / 0 | KEEP-REFERENCED | low | |
| U5 | `build_section`, `check_gate`, `require_allowed`, `Decision`, `GoingFurtherRefused`, `GATED_CRITERIA`, `MAX_WORDS`, `BENCHMARK_RESULTS`, `_agreements`, `_exact`, `_words` and, in config/judging.py, `PostReview`, `post_review`, `_load_post_review`, `_post_review_entry`, `DEFAULT_MIN_BENCHMARK_AGREEMENT` | agents/going_further.py:39-142; config/judging.py:114-142 | the post_review gate (D-109) | tests (tests/test_code_agent_v2.py); config/judging.yaml `post_review`; DECISIONS.md:4440 "BUILT, DISABLED, POSTED BY NOTHING". Locked on purpose until weather_etl labels exist (HANDOFF open question 4). | `git grep -n -w -- build_section` -> 0 / 5 / 1 / 0 | KEEP-DORMANT | low (protected) | |
| U6 | `correctness_opinion`, `normalise_payload`, `NEW_KEY`, `OLD_KEY` | agents/trace_compat.py:15-47 | append-only trace reader helpers | tests (tests/test_agents_code_agent.py:111-122, tests/test_code_agent_hardening.py:795-810 asserts it is imported by no non-test code ON PURPOSE) and docs/agents.md:174 ("readers outside agents/ ... integration requests"). Stored v1 traces keep the old `correctness` key forever (invariant 1), so the reader contract cannot be derived from code. | `git grep -n -w -- normalise_payload` -> 0 / 1 / 1 / 0 | KEEP-DORMANT | low | |
| U7 | `LINT_MEASURED_FROM`, `UNATTEMPTED_EXCLUDED_FROM` | features/compute_features.py:89, :107 | constants | tests assert them (test_lint_scope.py:237, test_unattempted_not_a_failure.py:145); comments at :81 and DECISIONS.md:3602 name them as the formula version from which a rule applies. Not read by any code path: they record history. | `git grep -n -w -- UNATTEMPTED_EXCLUDED_FROM` -> 1 / 1 / 1 / 0 | KEEP-REFERENCED | low | |
| U8 | `NON_MASTERY_KINDS` | memory/memory.py:176 | constant | tests (test_memory.py:206-218 asserts `MASTERY_TRACE_KINDS | NON_MASTERY_KINDS == KINDS`, disjoint, each reason > 20 chars; test_code_agent_hardening.py:786); cited in 4 docs. The partition check is the point of the constant. | `git grep -n -w -- NON_MASTERY_KINDS` -> 4 / 6 / 14 / 0 | KEEP-REFERENCED | low | |
| U9 | `cronbachs_alpha`, `cohort_censoring_rate`, `DifficultyEstimator` | variables/habits.py:61, variables/pace.py:42, variables/mastery.py:158 | spec-defined formulas | tests (test_variables.py, test_mastery.py) and explanation.md; named in VDEL_Modules_1_2_Build.md-derived text and config/concepts.yaml:14. Structurally degenerate at a cohort of one (STATUS.md M1 Known gaps), so no live caller yet. CLAUDE.md: the module documents win. | `git grep -n -w -- cronbachs_alpha` -> 1 / 3 / 1 / 0 | KEEP-DORMANT | low | |

`ruff` F401/F811/F841/F821: **0 findings** -- there are no unused imports, shadowed redefinitions or unused locals to list.

## 3. Unused files

Rule: a tracked non-`.md`, non-test, non-`curriculum/` file is "unused" only if no other tracked file mentions its path, its basename or its dotted module path, and no file imports it. **Result: 0 files are unreferenced.** The table lists every module/config file with how it is reached. `code` = other non-test `.py` files, `tests` = test files, `docs` = `.md`, `other` = yaml/sql/ps1/yml/json/csv/txt/toml/Dockerfile.

| File | code | tests | docs | other | Reached as | Class | Risk | Decision |
|---|---|---|---|---|---|---|---|---|
| .github/workflows/ci.yml | 3 | 3 | 6 | 2 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| agents/ab.py | 2 | 1 | 2 | 0 | imported / referenced by code | KEEP-DORMANT (protected) | low | |
| agents/budget.py | 6 | 9 | 5 | 1 | imported / referenced by code | KEEP-REFERENCED | low | |
| agents/code_agent.py | 8 | 11 | 9 | 1 | imported / referenced by code | KEEP-REFERENCED | low | |
| agents/echo_agent.py | 3 | 5 | 8 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| agents/fake_llm.py | 2 | 14 | 5 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| agents/feedback_agent.py | 5 | 9 | 4 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| agents/feedback_prompts.py | 3 | 4 | 4 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| agents/feedback_v2.py | 4 | 2 | 2 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| agents/going_further.py | 0 | 1 | 3 | 1 | config / fixture / doc-referenced | KEEP-DORMANT (protected) | low | |
| agents/pipeline.py | 7 | 6 | 8 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| agents/prompts.py | 10 | 5 | 11 | 1 | imported / referenced by code | KEEP-REFERENCED | low | |
| agents/resources.py | 3 | 2 | 3 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| agents/scope.py | 4 | 3 | 5 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| agents/tools.py | 4 | 3 | 7 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| agents/trace_compat.py | 0 | 2 | 3 | 0 | config / fixture / doc-referenced | KEEP-REFERENCED | low | |
| agents/validation.py | 4 | 5 | 7 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| assessment/diagnose.py | 4 | 7 | 5 | -1 | imported / referenced by code | KEEP-REFERENCED | low | |
| assessment/gap_generator.py | 2 | 2 | 5 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| assessment/gap_parser.py | 10 | 12 | 6 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| assessment/lint_scope.py | 2 | 1 | 4 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| assessment/scope_check.py | 8 | 2 | 6 | 1 | imported / referenced by code | KEEP-REFERENCED | low | |
| assessment/test_runner.py | 17 | 12 | 7 | 1 | imported / referenced by code | KEEP-REFERENCED | low | |
| benchmark/ground_truth.json | 3 | 1 | 10 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| benchmark/run_benchmark.py | 3 | 6 | 11 | 2 | imported / referenced by code | KEEP-DORMANT (protected) | low | |
| benchmark/run_real_benchmark.py | 1 | 3 | 7 | 0 | imported / referenced by code | KEEP-DORMANT (protected) | low | |
| collectors/collect_github.py | 9 | 5 | 8 | 2 | imported / referenced by code | KEEP-REFERENCED | low | |
| collectors/error_classifier.py | 3 | 3 | 7 | 1 | imported / referenced by code | KEEP-REFERENCED | low | |
| config/checks.py | 2 | 3 | 4 | 1 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| config/checks.yaml | 4 | 3 | 8 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| config/concepts.py | 6 | 5 | 5 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| config/concepts.yaml | 4 | 4 | 13 | 1 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| config/judging.py | 4 | 4 | 3 | 1 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| config/judging.yaml | 7 | 2 | 12 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| config/resources.csv | 2 | 3 | 4 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| config/roster.example.yaml | 4 | 0 | 7 | 2 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| dags/vdel_pipeline.py | 2 | 0 | 6 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| docker-compose.yml | 0 | 0 | 4 | 0 | config / fixture / doc-referenced | KEEP-REFERENCED (protected) | low | |
| docker/grader-requirements.txt | 0 | 1 | 5 | 1 | config / fixture / doc-referenced | KEEP-REFERENCED (protected) | low | |
| docker/grader.Dockerfile | 2 | 1 | 5 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| docs/resources_template.csv | 1 | 1 | 2 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| features/compute_features.py | 9 | 10 | 9 | 1 | imported / referenced by code | KEEP-REFERENCED | low | |
| memory/memory.py | 17 | 19 | 14 | 1 | imported / referenced by code | KEEP-REFERENCED | low | |
| pyproject.toml | 7 | 3 | 7 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| requirements-airflow.txt | 0 | 0 | 4 | 1 | config / fixture / doc-referenced | KEEP-REFERENCED (protected) | low | |
| requirements.txt | 1 | 3 | 9 | 6 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| scripts/ab_report.py | 1 | 1 | 5 | 0 | imported / referenced by code | KEEP-DORMANT (protected) | low | |
| scripts/agents_export_fixtures.py | 0 | 8 | 1 | -1 | CLI (`python -m`), documented/tested | KEEP-REFERENCED | low | |
| scripts/agents_make_labeling_sheet.py | 0 | 1 | 1 | 0 | CLI (`python -m`), documented/tested | KEEP-REFERENCED | low | |
| scripts/backfill_head_sha.py | 1 | 1 | 2 | 1 | imported / referenced by code | KEEP-REFERENCED | low | |
| scripts/backfill_mastery_observations.py | 1 | 1 | 2 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| scripts/baseline.py | 0 | 1 | 10 | 0 | CLI (`python -m`), documented/tested | KEEP-REFERENCED | low | |
| scripts/code_agent_report.py | 0 | 4 | 5 | 1 | CLI (`python -m`), documented/tested | KEEP-DORMANT (protected) | low | |
| scripts/collect.py | 3 | 1 | 6 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| scripts/deliver_next_attempt.py | 3 | 2 | 5 | 0 | imported / referenced by code | KEEP-DORMANT (protected) | low | |
| scripts/demo.py | 4 | 2 | 9 | 0 | imported / referenced by code | KEEP-DORMANT (protected) | low | |
| scripts/doctor.py | 0 | 2 | 10 | 1 | CLI (`python -m`), documented/tested | KEEP-DORMANT (protected) | low | |
| scripts/grade_collected.py | 4 | 9 | 5 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| scripts/init_db.py | 2 | 2 | 9 | 8 | imported / referenced by code | KEEP-REFERENCED | low | |
| scripts/llm_first_call.py | 3 | 1 | 3 | 0 | imported / referenced by code | KEEP-DORMANT (protected) | low | |
| scripts/load_resources.py | 0 | 3 | 2 | 0 | CLI (`python -m`), documented/tested | KEEP-REFERENCED | low | |
| scripts/next_attempt.py | 3 | 2 | 4 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| scripts/normalise_test_names.py | 0 | 1 | 1 | 1 | CLI (`python -m`), documented/tested | KEEP-REFERENCED | low | |
| scripts/post_feedback.py | 9 | 15 | 7 | 1 | imported / referenced by code | KEEP-REFERENCED | low | |
| scripts/prove_event_sourcing.py | 2 | 7 | 7 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| scripts/publish_repo.py | 9 | 5 | 3 | 0 | imported / referenced by code | KEEP-DORMANT (protected) | low | |
| scripts/render_student_repo.py | 7 | 8 | 4 | 2 | imported / referenced by code | KEEP-DORMANT (protected) | low | |
| scripts/roster_apply.py | 2 | 1 | 9 | 0 | imported / referenced by code | KEEP-DORMANT (protected) | low | |
| scripts/run_cycle.py | 4 | 8 | 10 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| scripts/run_hourly.py | 0 | 8 | 8 | 3 | CLI (`python -m`), documented/tested | KEEP-REFERENCED | low | |
| scripts/seed_data.py | 13 | 4 | 6 | 2 | imported / referenced by code | KEEP-REFERENCED | low | |
| scripts/smoke_test.py | 1 | 1 | 5 | 2 | imported / referenced by code | KEEP-REFERENCED | low | |
| scripts/sync_template.py | 3 | 3 | 3 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| scripts/validate_master.py | 0 | 1 | 7 | 1 | CLI (`python -m`), documented/tested | KEEP-DORMANT (protected) | low | |
| scripts/windows/register_task.ps1 | 1 | 3 | 5 | 1 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| scripts/windows/task_command.ps1 | 0 | 3 | 3 | 1 | config / fixture / doc-referenced | KEEP-REFERENCED (protected) | low | |
| scripts/windows/unregister_task.ps1 | 0 | 2 | 2 | 1 | config / fixture / doc-referenced | KEEP-REFERENCED (protected) | low | |
| sql/01_reference_tables.sql | 1 | 0 | 3 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| sql/02_raw_tables.sql | 1 | 0 | 4 | 1 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| sql/03_feature_tables.sql | 1 | 0 | 4 | 1 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| sql/04_indexes.sql | 1 | 0 | 3 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| sql/05_memory_tables.sql | 2 | 0 | 5 | 1 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| sql/06_assessment_tables.sql | 4 | 1 | 1 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| sql/07_feedback_tables.sql | 1 | 0 | 1 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| sql/08_lint_columns.sql | 1 | 0 | 0 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| sql/09_feedback_issues.sql | 1 | 0 | 0 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| sql/10_attempt_started_at.sql | 1 | 0 | 0 | 0 | imported / referenced by code | KEEP-REFERENCED (protected) | low | |
| sql/pilot/vdel_cycle_role.sql | 0 | 1 | 4 | 0 | applied by `scripts/init_db.py` glob / documented | KEEP-REFERENCED (protected) | low | |
| system/db.py | 29 | 51 | 8 | 3 | imported / referenced by code | KEEP-REFERENCED | low | |
| system/llm.py | 13 | 17 | 12 | 2 | imported / referenced by code | KEEP-REFERENCED | low | |
| variables/error_frequency.py | 3 | 1 | 4 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| variables/error_response.py | 2 | 1 | 4 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| variables/habits.py | 3 | 1 | 4 | 0 | imported / referenced by code | KEEP-REFERENCED | low | |
| variables/mastery.py | 4 | 2 | 6 | 2 | imported / referenced by code | KEEP-REFERENCED | low | |
| variables/pace.py | 2 | 1 | 4 | 1 | imported / referenced by code | KEEP-REFERENCED | low | |

Notes on the lowest-reference rows:

* `scripts/agents_export_fixtures.py`: code 0, referenced by `tests/fixtures/agents/README.md` and the fixtures it wrote (its own output). It is the exporter for `tests/fixtures/agents/real/`; keep unless you want the fixtures frozen (ASK, see Q6).
* `scripts/backfill_head_sha.py`, `scripts/backfill_mastery_observations.py`, `scripts/normalise_test_names.py`: one-off data migrations, each with its own test and a DECISIONS entry. Reachable only as CLIs. KEEP-REFERENCED today; candidates for retirement after the data they fix is gone -- not a code-only decision (ASK, Q6).
* `agents/trace_compat.py`: see U6. `sql/pilot/vdel_cycle_role.sql`: deliberately never applied (D-110), referenced by tests+docs.
* `tests/fixtures/agents/real/*.json` (6) and `synthetic/*.json` (3) are loaded from that directory by the tests (`tests/test_agents_budget.py:223-250`, `tests/test_agents_code_agent.py:26`), not by file name.

## 4. Duplicated logic

Found two ways: (a) `ast.dump` of normalised function bodies grouped across modules (1 byte-identical pair), and (b) same-name functions in different modules (20 names, mostly unrelated: `run`, `render`, `validate`, `apply` ...), then read by hand. "Covered" = a test exercises that copy, directly or through its caller.

| # | Duplicated logic | Copies (file:line) | Tests cover every copy? | Proposed single home | Class | Risk | Decision |
|---|---|---|---|---|---|---|---|
| X1 | **GitHub REST client plumbing**: the same `{"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}` dict plus a `requests.request(method, f"{GH_API}{path}", headers=..., timeout=...)` wrapper | `publish_repo.GitHub._req` :250-259; `sync_template.Contents._req` :155-162; `backfill_head_sha.RunsAPI.head_sha` :71 (also `_TIMEOUT_S = 60` defined three times: publish_repo:62, sync_template:65, backfill_head_sha:46). Related but different: `collectors/collect_github._headers` :46 (own `GH` constant, no `Accept`), `doctor._default_http_get` :222, `post_feedback.post_comment` :304 (dies with U2) | Yes: test_publish_repo.py, test_sync_template.py, test_backfill_head_sha.py (`RunsAPI`); collector via the collector tests; doctor via test_doctor.py | a small base class `GitHubBase(token)` with `_req` inside the **existing** `scripts/publish_repo.py` (sync_template and backfill_head_sha already import `GH_API` from it). A new module would go beyond CLAUDE.md section 5's fixed layout (stop-and-ask trigger 1) | REFACTOR | medium | |
| X2 | **Token lookup**: read `GITHUB_TOKEN` from the environment and refuse with the same sentence "GITHUB_TOKEN is not set. See .env.example." | `publish_repo._token` :606 (re-exported as `post_feedback.github_token` :55); `sync_template._load_token` :359 (adds `load_dotenv()`; imported by `backfill_head_sha` :43); `scripts/collect.py` :32; `collectors/collect_github._headers` :53 (raises `RuntimeError`, another exception type) | Yes for `_token`/`_load_token` (test_backfill_head_sha, test_sync_template, test_doctor); `collect.py` guard: no direct test found | `publish_repo._token` (one exception type `PublishRefused`; `load_dotenv()` done once at CLI entry) | REFACTOR | low | |
| X3 | **git subprocess env + runner**: `GIT_TERMINAL_PROMPT=0` + base64 `extraheader` token env, and a `subprocess.run(["git", *args], check=True, capture_output=True, text=True, timeout=...)` wrapper that turns `CalledProcessError` into a refusal | `grade_collected._git_env` :170 (imported across scripts by `publish_repo` :56 together with `_remove_tree`); runner copy 1 = the inner `git()` in `grade_collected.checkout_commit` :192-200 (timeout 180, raises `RuntimeError`); runner copy 2 = `publish_repo._git` :385 (timeout 180, raises `PublishRefused`); also `seed_data.py` :50 (`git hash-object`, no env) | `_git_env`: **no direct test**, covered through `checkout_commit` (test_checkout_safety.py, test_grade_collected.py) and `git_publish` (test_publish_repo.py). Both runners covered through those two | `scripts/grade_collected.py` keeps `_git_env`/`_git_run(cwd, env, *args, error=...)`; `publish_repo` imports the public name instead of a private one. Changing grading code touches the Docker-sandbox grading path -> do last | REFACTOR | medium | |
| X4 | **Roster text editing + backup policy** | `publish_repo.update_roster_text` :160 / `write_roster` :240 (one rolling `roster.yaml.bak`, overwritten every time); `roster_apply.plan_edit` :128 / `check_unambiguous` :85 / `backup_path` :191 / `apply` :201 (timestamped `.<UTC>.bak`, never overwritten, ambiguity refusal, credential refusal, diff); `deliver_next_attempt._roster_lines` :184 (calls publish_repo's). Two different safety policies for the same file; the untracked `config/roster.pre_publish.bak`, `roster.pre_deliver.bak`, `roster.yaml.bak` and `roster.yaml.<ts>.bak` are the visible result | Yes: test_publish_repo.py (`update_roster_text`, `write_roster`), test_roster_apply.py (`roster_apply`), test_deliver_next_attempt.py | `scripts/roster_apply.py` (the stricter one, D-105) as the only roster writer; `publish_repo` calls it. Behaviour change (backups stop overwriting) -> needs your decision | REFACTOR | high | |
| X5 | `_session(conn)` context manager | `assessment/test_runner.py:112` and `memory/memory.py:271` -- **byte-identical bodies** (AST hash equal). test_runner's docstring says "replicated rather than imported" on purpose | memory copy: test_memory.py and ~7 other files; test_runner copy: via `grade_attempt` tests (test_test_runner.py). Yes | `memory/memory.py` is "the only door" to memory but this helper only joins a `db.connect()` transaction; moving it to `system/db.py` would serve both. CLAUDE.md invariant 13 requires test_runner to import nothing from `agents/` or `system/llm.py`; `system/db.py` is not forbidden, but the isolation was a design choice | REFACTOR (or KEEP) | medium | |
| X6 | `gap_of(fn)` (reads the `@gap("id")` decorator) | `assessment/test_runner.py:475` (looser: no `str` check, `getattr` decorator_list) and `scripts/validate_master.py:89` (stricter) | test_runner copy: test_test_runner_gap_marker.py; validate_master copy: test_validate_master.py. Yes | `assessment/gap_parser.py` (the module whose job is `@gap` parsing). The two copies differ, so unifying changes one of them | REFACTOR | medium | |
| X7 | YAML config loaders `_entry`/`_load` | `config/checks.py:67,89` and `config/judging.py:71,83` (both "draft-ignoring" loaders, D-105) | Yes: tests/test_checks_and_drafts.py, test_validate_master.py, test_code_agent_v2.py | a shared `_load_yaml_list` helper in `config/` | REFACTOR | low | |
| X8 | `unified_diff` | `scripts/roster_apply.py:183` (two strings) vs `scripts/sync_template.py:255` (a `FileState`) | Yes | **do not merge**: same name, different inputs and labels | KEEP-REFERENCED | low | |
| X9 | `to_trace_payload` | `agents/feedback_agent.py:310` (v1) and `agents/feedback_v2.py:335` (v2) | Yes | **do not merge**: v1 and v2 live side by side by design (`--agents-v2`) | KEEP-DORMANT | low | |
| X10 | `load_dotenv()` at import | `system/db.py:22`, `system/llm.py:139`; called in `doctor.py:545`, `sync_template.py:360` | n/a | harmless (idempotent); mention only | KEEP-REFERENCED | low | |

Not duplicates despite sharing a name: `run` (11 modules), `render`, `validate` (x3), `apply` (x3), `snapshot`, `guarded`, `summary`, `grade` (code agent vs echo agent), `judge` (gateway vs fake), `log_trace` (pipeline vs Memory), `to_dict`, `build_parser`.

## 5. Classification summary

| Class | Items | Which |
|---|---|---|
| DELETE-SAFE | 1 | U1 |
| DELETE-WITH-ITS-TESTS | 1 | U2 (part of one test) |
| KEEP-DORMANT | 3 rows (U5, U6, U9) + X9 | post_review gate, trace_compat, spec formulas, v1/v2 pair |
| KEEP-REFERENCED | 3 rows (U4, U7, U8) + X8, X10 + every file in section 3 | |
| REFACTOR | 7 (X1-X7) | duplicates; none touches behaviour except X4 |
| ASK | 1 (U3) + the questions below | |

Section 3 file counts by class: KEEP-DORMANT (protected): 14; KEEP-REFERENCED: 50; KEEP-REFERENCED (protected): 31 (total 95 rows).

## 6. Protected (never proposed for deletion)

Every `.md` file anywhere; `config/`; `curriculum/` (including hidden tests); `sql/` (including `sql/pilot/`); `docker/`, `docker-compose.yml`; `.github/`; `requirements*.txt`, `docker/grader-requirements.txt`, `pyproject.toml`; `benchmark/` data and fixtures (`ground_truth.json`, `submissions/`); `scripts/windows/*.ps1` and anything README/INSTALL/OPERATIONS reference. Dormant features kept even if no live path calls them -- existence checked:

| Feature | Present at | Reached how |
|---|---|---|
| `--agents-v2` | scripts/run_cycle.py, scripts/run_hourly.py | CLI / flag |
| `--ab-llm` | scripts/run_cycle.py -> agents/ab.py | CLI / flag |
| `post_review` gate | config/judging.py, config/judging.yaml, agents/going_further.py | CLI / flag |
| benchmark runners | benchmark/run_benchmark.py, benchmark/run_real_benchmark.py | CLI / flag |
| demo script | scripts/demo.py | CLI / flag |
| doctor | scripts/doctor.py | CLI / flag |
| validate_master | scripts/validate_master.py | CLI / flag |
| roster_apply | scripts/roster_apply.py | CLI / flag |
| llm_first_call | scripts/llm_first_call.py | CLI / flag |
| run_real_benchmark | benchmark/run_real_benchmark.py | CLI / flag |
| code_agent_report | scripts/code_agent_report.py | CLI / flag |
| ab_report | scripts/ab_report.py | CLI / flag |
| publish_repo | scripts/publish_repo.py | CLI / flag |
| deliver_next_attempt | scripts/deliver_next_attempt.py | CLI / flag |
| render_student_repo | scripts/render_student_repo.py | CLI / flag |

Check: `git grep -c -e "--agents-v2" -- scripts` = scripts/run_cycle.py:2 ; scripts/run_hourly.py:1; `git grep -c -e "--ab-llm" -- scripts` = scripts/ab_report.py:1 ; scripts/run_cycle.py:2 ; scripts/run_hourly.py:1.

## 7. For information only (no action proposed)

### Functions over 80 lines (AST, `end_lineno - lineno + 1`)

| File | Function | Line | Lines |
|---|---|---|---|
| agents/code_agent.py | `grade` | 247 | 209 |
| scripts/validate_master.py | `validate` | 125 | 188 |
| benchmark/run_real_benchmark.py | `run` | 384 | 173 |
| collectors/collect_github.py | `collect_repo` | 200 | 168 |
| scripts/publish_repo.py | `run` | 438 | 159 |
| scripts/render_student_repo.py | `render_student_repo` | 344 | 143 |
| scripts/seed_data.py | `seed_curriculum` | 57 | 131 |
| benchmark/run_real_benchmark.py | `render_recommendation` | 236 | 121 |
| scripts/seed_data.py | `main` | 296 | 112 |
| agents/feedback_v2.py | `run_feedback_agent_v2` | 367 | 107 |
| features/compute_features.py | `_error_stats` | 524 | 105 |
| benchmark/run_benchmark.py | `run` | 137 | 99 |
| assessment/gap_parser.py | `_parse_gap_structure` | 157 | 98 |
| scripts/llm_first_call.py | `run` | 167 | 98 |
| system/llm.py | `_call_with_fallback` | 684 | 94 |
| assessment/test_runner.py | `grade_attempt` | 973 | 91 |
| scripts/run_cycle.py | `_plan_report` | 424 | 91 |
| agents/prompts.py | `build_grading_prompt` | 264 | 88 |
| memory/memory.py | `_replay_weaknesses` | 572 | 88 |
| scripts/run_hourly.py | `run` | 209 | 87 |
| agents/feedback_v2.py | `validate_output_v2` | 165 | 83 |

21 functions (tests included in the scan; none of them is in `tests/`).

### Modules over 600 lines

| File | Lines |
|---|---|
| memory/memory.py | 1305 |
| assessment/test_runner.py | 1090 |
| tests/test_memory.py | 1075 |
| system/llm.py | 1053 |
| tests/test_llm.py | 942 |
| tests/test_code_agent_hardening.py | 929 |
| scripts/run_cycle.py | 827 |
| tests/test_with_code_agent.py | 815 |
| features/compute_features.py | 752 |
| tests/test_feedback_v2.py | 669 |
| scripts/post_feedback.py | 661 |
| scripts/publish_repo.py | 640 |
| agents/feedback_v2.py | 616 |
| tests/test_pilot.py | 601 |

### TODO / FIXME / XXX

`77` matching lines in tracked text files: 36 in `.md`, 41 elsewhere. There is **no FIXME and no XXX** anywhere. Every `TODO` is one of the project's own markers (`TODO(verify)` = a value not yet checked, per CLAUDE.md section 10; `TODO(author)`; `TODO(measure)`), or the word "TODO" meaning the student's TODO comment in curriculum text and test strings.

| File:line | Text (first 120 chars) |
|---|---|
| benchmark/run_benchmark.py:118 | `TODO(verify)` and belong in RECOMMENDATION.md once someone has checked them.""" |
| benchmark/run_real_benchmark.py:533 | "not computed: no verified price supplied (TODO(verify)); recompute from the " |
| config/judging.yaml:14 | # TODO(author): read each against its stage and change `draft` to `reviewed` (or rewrite it). |
| docker/grader-requirements.txt:6 | # TODO(verify): that every pin installs on the image's Python 3.11 (the first `docker build` shows |
| sql/06_assessment_tables.sql:53 | instruction    TEXT NOT NULL,           -- becomes the student's TODO comment |
| system/llm.py:71 | by Anas and are unverified here (D-225). An id set back to `TODO(verify)` is refused by |
| system/llm.py:82 | `MODEL_TIERS["cheap"][Provider.NVIDIA]` stays `TODO(verify)` because no cheap-tier |
| system/llm.py:190 | # The rest are TODO(verify) rather than guesses, per CLAUDE.md §10's rule against invented |
| system/llm.py:197 | # branch (same status as D-031's NVIDIA id). Replace with `TODO(verify)` to disable. |
| system/llm.py:199 | Provider.QWEN_LOCAL: "TODO(verify)", |
| system/llm.py:210 | Provider.QWEN_LOCAL: "TODO(verify)", |
| system/llm.py:211 | Provider.NVIDIA: "TODO(verify)",  # no cheap-tier DeepSeek variant was specified |
| system/llm.py:492 | # `_model_chain` still skips it while its model ids are `TODO(verify)`. |
| system/llm.py:596 | provider, in a fixed order, deduplicated. `"TODO(verify)"` placeholders (D-024/D-031 -- |
| system/llm.py:609 | if candidate and candidate != "TODO(verify)" and candidate not in chain: |
| system/llm.py:966 | # (`MODEL_TIERS` holds `TODO(verify)`), and an id listed here without a source would be exactly |
| system/llm.py:982 | - Model: a `TODO(verify)` id is refused here with a `ValueError` (never retried, never |
| system/llm.py:996 | if model.startswith("TODO(verify)"): |
| system/llm.py:998 | "the OpenAI model id is still TODO(verify): write the real default/cheap ids into " |

Omitted from the table: 22 lines in `tests/` (strings that assert on the `TODO(verify)` refusal, or on the student-facing word TODO) and the `.md` lines (mostly DECISIONS.md `TODO(verify)` bookkeeping). The full list is `markers.json` in the snapshot folder.

## 8. Summary of counts

| Measure | Count |
|---|---|
| Tracked files analysed | 267 |
| Top-level definitions analysed | 951 |
| Definitions with no non-test code reference | 18 (+21 only reachable from them) |
| ruff F401/F811/F841/F821 findings | 0 |
| Unreferenced files | 0 |
| DELETE-SAFE | 1 (`_failure_log`, 5 lines) |
| DELETE-WITH-ITS-TESTS | 1 (`post_comment`, ~16 lines + part of 1 test) |
| KEEP-DORMANT / KEEP-REFERENCED rows | 6 code rows + every file |
| REFACTOR (duplicates) | 7 |
| ASK | 1 code item + 8 questions |
| Functions > 80 lines | 21 |
| Modules > 600 lines | 14 |
| FIXME / XXX | 0 |

Honest reading: the repository is **clean**. After 100+ decisions the only real dead code is two small functions; the larger finding is duplication (X1-X4), which is a maintenance risk, not dead weight.

## 9. Questions for you

**Q1.** U1 `_failure_log`: delete it (and the two explanation.md sentences)? It is a 3-line wrapper nobody calls.

**Q2.** U2 `post_comment`: delete the old commit-comment POST and the lines of `test_posting_is_refused_...` that call it, keeping the `--post` gate test? Or keep it as the documented "real write" seam?

**Q3.** U3 `system/llm.generate`: public API kept for a future non-judging use, or remove it together with `FakeLLM.generate`/`GenerateForbidden`? (Touches invariants 3-4 text; I recommend KEEP.)

**Q4.** X1-X3: may the shared GitHub/token/git helpers live inside the existing `scripts/publish_repo.py` and `scripts/grade_collected.py` (no new file), or do you want a new module and a CLAUDE.md section 5 update?

**Q5.** X4: which roster backup policy wins -- rolling `roster.yaml.bak` (publish_repo) or timestamped never-overwritten (roster_apply)? This is a behaviour change.

**Q6.** One-off migrations (`backfill_head_sha`, `backfill_mastery_observations`, `normalise_test_names`) and the fixture exporter (`agents_export_fixtures`): keep indefinitely, or retire after the data they fix is confirmed gone?

**Q7.** X5/X6: is `assessment/test_runner.py` allowed to import `_session`/`gap_of` from a shared module, or must it stay self-contained (invariant 13 isolation)?

**Q8.** `New-HourlyTaskScript` has no `-AgentsV2` switch, so the fourth scheduled-task mode cannot be generated. Intended (v2 stays manual until you try it), or missing?

**Q9.** `benchmark/RECOMMENDATION.md` is modified in your working tree (99 insertions, 61 deletions) and I left it alone. Commit it separately or discard?

Reference snapshot: `C:\Users\ASUS\AppData\Local\Temp\vdel_snapshot.4530Hv`
