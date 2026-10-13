# DOCS_TRIAGE.md -- which documents the professor receives

Written for: the author, to decide what leaves the repository before handing it to the professor. Analysis only: no file was changed, moved or deleted, no `.md` was edited, no test was run. Branch `docs-triage` from `main`; this is the only file added. Scratch scripts and raw JSON are outside the repo at `C:\Users\ASUS\AppData\Local\Temp\vdel_docs_triage.QnKfFR`.

Method. Facts come from `git ls-files`, `git log`, `git grep` and a regex scan whose categories are described under the per-file table. Personal content is reported by line number and category only; no sensitive text is copied here. Every `python -m` command and file path a document mentions was checked for existence (tracked or on disk); false positives are named, not hidden. The Decision column is yours.

## 1. Counts and the main findings

| Measure | Count |
|---|---|
| Tracked `.md` files | 30 (plus this file once merged) |
| KEEP-REQUIRED | 5 |
| KEEP | 4 |
| KEEP-AFTER-EDIT | 11 |
| ARCHIVE | 2 |
| MERGE | 1 |
| PRIVATE | 7 |
| ASK | 0 |
| Other tracked documentation artifacts | 0 `.html`/`.pptx`/`.pdf`/`.docx`; 7 `.csv`/`.txt` data or pin files (section 4) |
| Documents the code or tests read, hash or assert | 5 (`PROMPT_CHANGELOG.md`, `PILOT.md`, fixtures `README.md`, `TASK.md`, plus `RECOMMENDATION.md` as an output path) |
| Documents named only in code comments or runtime messages | 8 (`OPERATIONS.md`, `DECISIONS.md`, `DEVELOPMENT_MAP.md`, `VDEL_TEN_PROJECT_CURRICULUM.md`, `STATUS.md`, `agents.md`, `explanation.md`, `resources_review.md`) |
| Tracked docs with a real token, key or password | 0 (pattern scan, section 9) |

**Findings that matter for the handover** (details below):

1. **The documents the code calls its authority are not tracked.** `CLAUDE.md`, `BUILD_PLAN.md`, `EXECUTION.md`, `SETUP.md`, `VDEL_Modules_1_2_Build.md`, `VDEL_Modules_3_9_Build.md`, `VDEL_v1_Execution_Plan.md`, `VDEL_REDESIGN.md` and `vdel_complete_design_document.md` are in `.gitignore`. Code comments cite `CLAUDE.md` in 36 files, `VDEL_REDESIGN.md` in 24, `VDEL_Modules_1_2_Build.md` in 19 and `VDEL_Modules_3_9_Build.md` in 11; `DECISIONS.md` cites `CLAUDE.md` 51 times. A professor continuing the project cannot open the source of the formulas those comments say they transcribe. This is the biggest gap (Q1, Q9).
2. **`docs/STATUS.md` is tracked although `.gitignore` lists it** (it was added while allow-listed). Ignoring it does not untrack it.
3. **The git history carries identity metadata**: 95 commits under a noreply GitHub address and 16 under a personal Gmail address; 21 commit messages hold a `Co-Authored-By` trailer; a remote `origin` exists (a GitHub repository under the author's login) with `main` and `feature/agents` pushed. Whether it is public could not be checked (no network).
4. **Two documents state something the repository contradicts**: `benchmark/RECOMMENDATION.md:115`, `docs/KNOWN_ISSUES.md:111` and `docs/OPERATIONS.md:333` say `benchmark/TASK.md` is missing (the file is `benchmark/submissions/TASK.md`, and a test asserts it); `docs/agents.md:25` says main has no Feedback Agent.
5. **No secret is in the repository, in the tree or in any revision** (section 9). Test files contain dummy keys.

## 2. Per-file table

Audience: MAINTAINER, INSTRUCTOR, STUDENT, AUTHOR-ONLY, AI-ASSISTANT. Size/first/last/commits come from `git log --follow` (all branches share these files). 'Inbound' counts other tracked `.md` files that mention the path or file name. Personal-content columns are line numbers and categories only.

| Path | Size, lines, first..last commit | Audience | Type | Class | Reason | Machine readers | Inbound docs | Personal-content lines | Stale items | Destination | Risk | Decision |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `CHANGELOG.md` | 7 KB, 106 L, 2026-10-13..2026-10-13 (5) | MAINTAINER | reference (map into DECISIONS) | **KEEP-AFTER-EDIT** | Useful map of decisions by period; one link points at a private session file. | none | 11 | none | line 33 links docs/FINALIZE_PROGRESS.md (leaves) | stays | low | |
| `CONTRIBUTING.md` | 7 KB, 139 L, 2026-10-13..2026-10-13 (1) | MAINTAINER | how-to | **KEEP** | The rules of change (loop, fake-LLM rule, writing a decision, one-job-per-doc); no private link found. | none | 4 | supervision/meeting/intern-admin: 92 | none found | stays | low | |
| `README.md` | 5 KB, 87 L, 2026-08-02..2026-10-13 (4) | ALL (entry point) | overview / index | **KEEP-AFTER-EDIT** | Best entry for the professor; needs a full docs index and the authors line decided. | none (no test, script or CI reads it) | 3 | school/employer: 3; supervision/meeting/intern-admin: 23,86; names: 86 | docs list covers 10 of the kept docs; 11 are not linked from it (section 7) | stays | low | |
| `VDEL_TEN_PROJECT_CURRICULUM.md` | 25 KB, 497 L, 2026-08-31..2026-08-31 (1) | INSTRUCTOR | plan / design (ten projects) | **KEEP-AFTER-EDIT** | The only description of projects 2-10 a professor needs to write new projects; wording refers to a meeting and a supervisor, and cites a private design file. | code comments only: curriculum/master/sales_analyzer/sales_analyzer/__init__.py:10, scripts/seed_data.py:310, tests/test_gap_generator.py:318, tests/test_gap_parser.py:379 (no read) | 2 | supervision/meeting/intern-admin: 164,380,481 | 41 file names (dag.py, dedupe.py ...) do not exist: they are planned project files, by design; lines 17,148,457 cite VDEL_REDESIGN.md (not tracked) | stays (root path is cited by the 4 code comments) | low | |
| `docs/ARCHITECTURE.md` | 13 KB, 193 L, 2026-10-13..2026-10-13 (1) | MAINTAINER | design / reference | **KEEP-AFTER-EDIT** | The module map and the data model; the best second read after README. One line names a collaborator. | none | 5 | names: 190 | none found | stays | low | |
| `docs/AUTHORING.md` | 14 KB, 246 L, 2026-10-13..2026-10-13 (2) | INSTRUCTOR | how-to | **KEEP** | Complete guide to writing a master project, hidden tests, checks.yaml and judging.yaml, with a validator and a checklist. | none | 6 | none | none (example path tests/hidden/test_extract.py exists in curriculum/master/weather_etl) | stays | low | |
| `docs/CLEANUP_PLAN.md` | 38 KB, 361 L, 2026-10-13..2026-10-13 (1) | AUTHOR-ONLY | plan (analysis) | **PRIVATE** | The author's cleanup analysis, with local paths; its useful part (duplication X1-X7) moves into the proposed ROADMAP. | none | 0 | local-path: 9,44,360; names: 303 | n/a | private folder: analysis/ | low | |
| `docs/CONTEXT_POLICY.md` | 10 KB, 239 L, 2026-10-13..2026-10-13 (1) | AI-ASSISTANT / AUTHOR-ONLY | policy | **PRIVATE** | How to ration an AI assistant's context for this internship; not about the framework. | none | 0 | supervision/meeting/intern-admin: 43,159 | n/a | private folder: dev-system/ | low | |
| `docs/CURRENT_DEMO.md` | 3 KB, 85 L, 2026-10-13..2026-10-13 (1) | MAINTAINER | how-to (stale demo) | **MERGE** | Older M1 demo whose first step is TRUNCATE on the raw tables; its inspection queries belong in OPERATIONS.md. | none | 0 | none | title and intro cite STATUS.md/HANDOFF.md; last paragraph says wiring the fast path 'isn't built yet' (it is); step 1 is destructive | merge the inspection queries into docs/OPERATIONS.md; do not carry the TRUNCATE step | medium | |
| `docs/DECISIONS.md` | 395 KB, 4454 L, 2026-08-31..2026-10-13 (29) | MAINTAINER / INSTRUCTOR | decision log (append-only) | **KEEP-AFTER-EDIT** | The rationale of the whole project (111 entries) and the 'defend it' record; needs two login lines replaced. | no test or script parses it; D-numbers resolve from code comments: assessment/gap_generator.py:46, assessment/gap_parser.py:4,43, scripts/prove_event_sourcing.py:34,229, scripts/smoke_test.py:31, system/llm.py:88, sql/*.sql comments, many tests | 16 | supervision/meeting/intern-admin: 89 lines (7..4438); names: 145 lines (58..4447); evaluation-talk: 665,669,2705,3038,3157,3638; secret-pattern(false positive): 1236,1265; github-login: 2648,3556 | historical by design (old counts, removed names); cites 51x CLAUDE.md, 14x BUILD_PLAN.md, 14x VDEL_REDESIGN.md, 8x docs/reading/ (none tracked) | stays | medium | |
| `docs/DECISIONS_AGENTS.md` | 12 KB, 208 L, 2026-10-11..2026-10-11 (1) | MAINTAINER | decision log (D-200 and up) | **KEEP-AFTER-EDIT** | The agent decisions that code comments cite as D-2xx; its header describes a branch merge that has happened. | code comments cite D-2xx ids: benchmark/run_real_benchmark.py, system/llm.py | 4 | names: 194,195 | line 131 cites docs/AGENTS_OVERNIGHT_REPORT.md (never committed); line 190 cites CLAUDE.md; lines 1-6 'when the branches merge' are obsolete | stays | low | |
| `docs/DEVELOPMENT_MAP.md` | 36 KB, 598 L, 2026-10-13..2026-10-13 (1) | AUTHOR-ONLY / AI-ASSISTANT | analysis / compression artifact | **ARCHIVE** | A session-1 analysis of nine private documents and the AI dev-system layout; DECISIONS cites it 10 times, so keep the file name. | comments only: agents/echo_agent.py:9, agents/tools.py:40, tests/test_echo_agent.py:5, tests/test_tools.py:8, tests/test_validation.py:7 | 4 | names: 14 lines (43..330); supervision/meeting/intern-admin: 12 lines (122..545) | says 'working source tree was not available' and 'Code read: none'; lists VDEL_v01_Plan.md, docs/FILES.md, docs/MEMORY.md, memory/reflection.py, memory/sessionize.py (absent); built 2026-08-10 | docs/archive/DEVELOPMENT_MAP.md (+ banner 'historical') | medium | |
| `docs/FINALIZE_PROGRESS.md` | 3 KB, 50 L, 2026-10-13..2026-10-13 (6) | AUTHOR-ONLY | status / session log | **PRIVATE** | Resume file of the finished v1-finalize branch with the assistant rules of the brief. | .gitignore:46 (comment only) | 2 | none | test counts 1410/1461/1506 are old | private folder: sessions/ | low | |
| `docs/GLOSSARY.md` | 8 KB, 150 L, 2026-10-13..2026-10-13 (1) | ALL | reference | **KEEP** | Short shared vocabulary; no private content. | none | 3 | none | none found | stays | low | |
| `docs/INSTALL.md` | 10 KB, 199 L, 2026-10-13..2026-10-13 (1) | OPERATOR | how-to | **KEEP** | Clean machine to first cycle; the 'API_KEY=' hit at line 100 is a placeholder ('...'), not a secret. | none | 5 | secret-pattern(false positive): 100 | none found | stays | low | |
| `docs/KNOWN_ISSUES.md` | 15 KB, 228 L, 2026-10-13..2026-10-13 (6) | MAINTAINER / INSTRUCTOR | status (honest limits) | **KEEP-AFTER-EDIT** | The single best 'what is unproven or wrong' list; three citations of a private file and one stale sentence. | none | 7 | names: 120,167 | lines 75,153,160 cite docs/STATUS.md (leaves); line 111 'benchmark/TASK.md is missing' (stale, see RECOMMENDATION); line 180 '1461 passed' (now 1572) | stays | low | |
| `docs/MODEL_ROUTING.md` | 4 KB, 87 L, 2026-10-13..2026-10-13 (1) | AI-ASSISTANT / AUTHOR-ONLY | policy | **PRIVATE** | When to use which AI model while developing; not about the framework. | none | 2 | supervision/meeting/intern-admin: 32 | n/a | private folder: dev-system/ | low | |
| `docs/OPERATIONS.md` | 27 KB, 497 L, 2026-10-11..2026-10-13 (10) | OPERATOR | how-to / runbook | **KEEP-AFTER-EDIT** | The runbook; five command examples contain the author's local folder path. | text pointers: scripts/doctor.py:49,380 (message cites section 2 and 12), scripts/windows/register_task.ps1:23,97, docker/grader.Dockerfile:12 | 9 | local-path: 23,215,276,315,363; school/employer: 23,215,276,315,363; supervision/meeting/intern-admin: 23,215,276,315,363 | line 333 'benchmark/TASK.md is missing' (stale); line 187 '--clean/--if-exists' are pg_restore's own flags (false positive) | stays (section numbers 2, 11, 12 are cited by code messages: do not renumber) | medium | |
| `docs/PILOT.md` | 7 KB, 116 L, 2026-10-13..2026-10-13 (1) | INSTRUCTOR / OPERATOR | how-to (pilot checklist) | **KEEP-REQUIRED** | A test asserts its content; the pilot role SQL and roster example point at it. | tests/test_pilot.py:184-186 (read_text; asserts 'vdel_cycle_role.sql', 'not applied', 'pw=', '-v dbname=', 'PG_DSN'); config/roster.example.yaml:17; sql/pilot/vdel_cycle_role.sql:7 | 5 | none | none found | stays | low | |
| `docs/START_HERE.md` | 12 KB, 212 L, 2026-10-13..2026-10-13 (1) | AI-ASSISTANT / AUTHOR-ONLY | map (authority order of private documents) | **PRIVATE** | Its priority order ranks documents the professor will not have; tells an assistant to ask 'the person'. | none | 2 | school/employer: 13; supervision/meeting/intern-admin: 18,75,91,181,183; evaluation-talk: 72,204 | cites VDEL_v01_Plan.md, vdel_implementation_plan.md, system/observability.py, system/orchestrator.py (absent) | private folder: dev-system/ | low | |
| `docs/STATUS.md` | 47 KB, 1019 L, 2026-08-31..2026-10-11 (2) | AUTHOR-ONLY | status log (milestone board with pasted run output) | **PRIVATE** | The author's evidence board; tracked although .gitignore lists it (it was added while allow-listed). | .gitignore:39-48 (comment); collectors/collect_github.py:69 (comment) | 8 | supervision/meeting/intern-admin: 7,28,981,991,992; names: 10 lines (137..991); local-path: 875 | scripts/plot_mastery.py and benchmark/copy_paste.py (absent); counts 164/332/336 are old | private folder: evidence/ (see Q4) | medium | |
| `docs/WORKFLOW.md` | 7 KB, 165 L, 2026-10-13..2026-10-13 (1) | AI-ASSISTANT / AUTHOR-ONLY | workflow (slash-command loop, meeting prep) | **PRIVATE** | The author's task-to-commit loop for an AI assistant, with supervision-meeting steps. | none | 0 | supervision/meeting/intern-admin: 108,147,148; names: 146 | n/a | private folder: dev-system/ | low | |
| `docs/agents.md` | 35 KB, 595 L, 2026-10-11..2026-10-12 (2) | MAINTAINER | reference (agents inventory and contracts) | **KEEP-AFTER-EDIT** | The agents' contracts; the header still says it belongs to a branch and that main has no Feedback Agent. | comments: agents/feedback_agent.py:39, agents/pipeline.py:10,271, agents/trace_compat.py:8 | 4 | names: 51 | lines 3-6 and 25-26 stale (feature/agents banner; 'no Feedback Agent on main' - agents/feedback_agent.py and feedback_v2.py exist); lines 30,49,51 cite CLAUDE.md / VDEL_REDESIGN.md; lines 49-50 correctly say reviewer/orchestrator are not built | stays | medium | |
| `docs/code_agent_flow.md` | 27 KB, 376 L, 2026-10-12..2026-10-12 (3) | MAINTAINER | reference (snapshot, line-anchored) | **ARCHIVE** | Superseded in part by D-103; every file:line is at commit eb9727c. Valuable as history, misleading as a current reference. | none | 1 | supervision/meeting/intern-admin: 97; names: 254 | line anchors frozen at eb9727c (banner at line 9 says so); line 367 cites CLAUDE.md | docs/archive/code_agent_flow.md (see Q6: or refresh instead) | medium | |
| `docs/explanation.md` | 169 KB, 2442 L, 2026-08-31..2026-10-13 (21) | MAINTAINER | reference (file-by-file, written for an AI picking the code up cold) | **KEEP-AFTER-EDIT** | Largest description of what the code does and why; written at M0-M4 and extended; stale in places. | comment: memory/memory.py:221 | 9 | school/employer: 26,27; names: 8 lines (33..2420); supervision/meeting/intern-admin: 8 lines (33..2385); evaluation-talk: 861,1597,1846; github-login: 2083 | title says M0-M4; lines 799,1096,1165-1190,1373 describe reflection.py / sessionize.py / variables/help_seeking.py (absent); 1285-1286 orchestrator/reviewer (not built); 2062-2064 diff_runner.py (absent); old test counts at 1360,1460,1527,1755; cites CLAUDE.md 25x | stays (add a dated banner) | medium | |
| `docs/resources_review.md` | 16 KB, 108 L, 2026-10-12..2026-10-12 (1) | INSTRUCTOR | review record (provenance of config/resources.csv) | **KEEP-AFTER-EDIT** | Shows how the 32 learning resources were checked on 2026-10-12; first-person 'this session' wording and one name. | comment: tests/test_resources_seed.py:6 | 0 | names: 91 | none found; not linked from README | stays | low | |
| `agents/PROMPT_CHANGELOG.md` | 10 KB, 158 L, 2026-08-23..2026-10-13 (5) | MAINTAINER | changelog (prompts are code) | **KEEP-REQUIRED** | A test asserts it holds a '## v3 ' entry; it is the version history of the prompts. | tests/test_code_agent_hardening.py:196 (read_text, asserts '## v3 '). The sha256 pin at :197 is of prompts.RUBRIC_TABLE, not of this file; comments: agents/prompts.py:20,55, agents/feedback_prompts.py:21 | 9 | names: 32,42 | line 32 cites HANDOFF.md (not tracked); lines 8,14,21 cite BUILD_PLAN.md, CLAUDE.md, VDEL_Modules_3_9_Build.md (not tracked) | stays (edits to lines 32 and 42 allowed: the test only needs the '## v3 ' heading) | low | |
| `benchmark/RECOMMENDATION.md` | 5 KB, 120 L, 2026-10-11..2026-10-13 (2) | MAINTAINER / INSTRUCTOR | generated report (benchmark result) | **KEEP-REQUIRED** | Output path of benchmark/run_real_benchmark.py; it is regenerated, so edits to the file are overwritten. | benchmark/run_real_benchmark.py:72 (RECOMMENDATION_PATH), :548 (write); benchmark/run_benchmark.py:118; agents/tools.py:52 (comment) | 12 | none | line 115 says 'benchmark/TASK.md is missing' but benchmark/submissions/TASK.md exists (asserted by tests/test_benchmark_submissions.py:50); the sentence comes from benchmark/run_real_benchmark.py:345, so the fix is in the generator, not in the .md | stays | medium | |
| `benchmark/submissions/TASK.md` | 3 KB, 59 L, 2026-08-13..2026-08-13 (1) | MAINTAINER | benchmark spec | **KEEP-REQUIRED** | A test asserts it exists; ground_truth.json and the five benchmark files point at it. | tests/test_benchmark_submissions.py:50 (exists); benchmark/ground_truth.json:6,9; benchmark/run_benchmark.py:8,49; benchmark/run_real_benchmark.py:345; benchmark/submissions/clean.py:3 (and siblings) | 6 | none | none (the stale mentions point at it from elsewhere) | stays | low | |
| `tests/fixtures/agents/README.md` | 2 KB, 45 L, 2026-10-11..2026-10-11 (1) | MAINTAINER | README (fixture provenance) | **KEEP-REQUIRED** | A test asserts the file exists. | tests/test_agents_fixtures.py:31 (is_file) | 3 | none | none | stays | low | |

Reading the personal-content column. The scan is broad on purpose: 'names' counts the author, the collaborator and the supervisor wherever a name appears (in `DECISIONS.md` mostly as `Authority: <name>`); 'supervision/meeting/intern-admin' counts the words supervis*, meeting, viva, defence, internship, Wednesday/Tuesday write-up, so many hits are ordinary prose about the design rule, not private notes; 'school/employer' counts UiTM, AntsBees (project context, fine to keep) and the author's school name (only `OPERATIONS.md` contains it, inside the local folder path). 'secret-pattern(false positive)' are the two lines in `DECISIONS.md` that contain the text 'risk-reg...' and the `INSTALL.md` placeholder.

## 3. Exact lines to sanitize or fix (KEEP-AFTER-EDIT, plus edits allowed in KEEP-REQUIRED)

Nothing below was edited. 'Replacement kind' says what to put instead.

| File | Lines | Why | Replacement kind |
|---|---|---|---|
| README.md | 86 | authors / collaborator / supervisor names | keep (project context) or replace with 'Maintainers: see CONTRIBUTING.md' - your call (Q3) |
| README.md | 6-17 (table), 'Where things are' | docs index lacks 11 kept docs | add a documents table (section 7) |
| CHANGELOG.md | 33 | link to docs/FINALIZE_PROGRESS.md (leaves) | drop the link or point to docs/KNOWN_ISSUES.md |
| VDEL_TEN_PROJECT_CURRICULUM.md | 164, 380, 481 | 'the meeting', 'your supervisor' wording | neutral wording ('the course author') |
| VDEL_TEN_PROJECT_CURRICULUM.md | 17, 148, 457 | cite VDEL_REDESIGN.md (not tracked) | inline the fact or cite DECISIONS.md D-035 |
| agents/PROMPT_CHANGELOG.md | 32 | cites HANDOFF.md open question (not tracked); names a person | 'a labelled benchmark set is needed' without the file/name |
| agents/PROMPT_CHANGELOG.md | 42 | 'Raise with <supervisor>' | 'raise with the course author' |
| agents/PROMPT_CHANGELOG.md | 8, 14, 21 | cite BUILD_PLAN.md, CLAUDE.md, VDEL_Modules_3_9_Build.md | cite DECISIONS.md or inline (Q1) |
| docs/ARCHITECTURE.md | 190 | 'Hanafi's side' (a collaborator by name) | 'the tutor-side component' |
| docs/OPERATIONS.md | 23, 215, 276, 315, 363 | the author's local folder path (also contains the school folder name) | placeholder `<repo-folder>` |
| docs/OPERATIONS.md | 333 | stale: 'benchmark/TASK.md is missing' | 'benchmark/submissions/TASK.md' |
| docs/KNOWN_ISSUES.md | 75, 153, 160 | cite docs/STATUS.md (leaves) | inline the one-line fact or cite the decision (D-096) only |
| docs/KNOWN_ISSUES.md | 111 | stale: 'benchmark/TASK.md is missing' | correct path |
| docs/KNOWN_ISSUES.md | 120, 167 | names of the course author and collaborator | 'the course author', 'the tutor-side collaborator' |
| docs/KNOWN_ISSUES.md | 180 | '1461 passed' (current 1572) | 'a full run' without a number, or the current number |
| docs/DECISIONS.md | 2648, 3556 | the author's real GitHub login | placeholder login (`<owner>`) |
| docs/DECISIONS.md | 145 lines of names | 'Authority: <name>' style attributions | keep (it is a decision log) or replace by roles - your call (Q3) |
| docs/DECISIONS_AGENTS.md | 1-6 | describes a future branch merge; it has happened | one sentence: 'ids D-200+ live here; do not renumber' |
| docs/DECISIONS_AGENTS.md | 131, 190 | cite an overnight report (never committed) and CLAUDE.md | drop |
| docs/DECISIONS_AGENTS.md | 194, 195 | names a person as the source of model ids | role instead of name |
| docs/agents.md | 3-6, 25-26 | stale branch banner and 'no Feedback Agent on main' | state that the agents are merged; point to feedback_agent.py / feedback_v2.py |
| docs/agents.md | 30, 49, 51 | cite CLAUDE.md, VDEL_REDESIGN.md; a collaborator by name | cite DECISIONS.md or inline |
| docs/explanation.md | 2083 | the author's real GitHub login | placeholder login |
| docs/explanation.md | 502-503, 1491, 1757-1793 | cite STATUS.md, HANDOFF.md, SETUP.md, EXECUTION.md (not tracked) | inline the fact or drop |
| docs/explanation.md | title, 799, 1096, 1165-1190, 1285-1286, 1373, 2062-2064 | M0-M4 vintage; mentions files that do not exist | dated banner 'written at M4; later sections are in ARCHITECTURE.md'; mark non-existent files 'not built' |
| docs/explanation.md | 1360, 1460, 1527, 1755 | old test counts | remove numbers or date them |
| docs/resources_review.md | 91 | names the collaborator | 'the tutor-side collaborator' |
| benchmark/RECOMMENDATION.md | 115 | stale 'benchmark/TASK.md is missing' | fix benchmark/run_real_benchmark.py:345, then regenerate; do not hand-edit |
| code (not docs) | scripts/demo.py:9; tests/test_post_feedback_issue.py:234; tests/test_sync_template.py:276,279 | the author's GitHub login in code | placeholder login (outside this task, listed for completeness) |
| code (not docs) | scripts/windows/task_command.ps1:7; tests/test_task_command.py:4 | the private project folder name in a comment | describe it as 'a folder with an apostrophe' |
| code (not docs) | agents/echo_agent.py:68, agents/validation.py:75, assessment/gap_generator.py:112, benchmark/run_benchmark.py:13,206, config/concepts.py:5, config/roster.example.yaml:5, features/compute_features.py:290, system/llm.py:71,78,86,196,200, variables/pace.py:11, benchmark/ground_truth.json:3 | first names of the author / collaborator / supervisor in comments and data | keep (attribution) or role - your call (Q3) |

## 4. Other tracked documentation artifacts (information only)

No `.html`, `.pptx`, `.pdf` or `.docx` is tracked. Tracked data/pin files that read like documentation: `config/resources.csv` (the reviewed learning resources), `docs/resources_template.csv` (a template), `requirements.txt`, `requirements-airflow.txt`, `docker/grader-requirements.txt` (contains one `TODO(verify)`), and two `requirements.txt` inside `curriculum/master/*`. None holds personal content. Untracked but present in the working folder (never in git, so absent from both handover modes, but included if the folder itself is zipped): `CLAUDE.md`, `BUILD_PLAN.md`, `EXECUTION.md`, `SETUP.md`, `VDEL_Modules_1_2_Build.md`, `VDEL_Modules_3_9_Build.md`, `VDEL_v1_Execution_Plan.md`, `VDEL_REDESIGN.md`, `vdel_complete_design_document.md`, `docs/HANDOFF.md`, `docs/FRAMEWORK_STATUS.md`, `docs/OVERNIGHT_REPORT.md`, `docs/V1_OVERNIGHT_REPORT.md`, `docs/reading/`, `docs/design/`, `.claude/`, `backups/`, `logs/`, `renders/`, `config/roster.yaml` and the `*.bak` files.

`CLAUDE.md` is AI-ASSISTANT, not tracked. It does carry personal and internship rules (author, collaborator and supervisor names, 'intern', the supervisor-meeting cadence, an instruction naming the author's own repositories as the first student). Do not hand it over as is. If the professor will use an AI assistant, a short sanitized `CLAUDE.md` (the 16 invariants, the layout, the commands, no persons) is worth writing; see section 8.

## 5. Proposed final tree of the delivered repository

```
README.md                         (edit: docs index, authors line)
CHANGELOG.md                      (edit: 1 link)
CONTRIBUTING.md
VDEL_TEN_PROJECT_CURRICULUM.md    (edit: wording) -- or docs/design/ if the 4 code comments are re-pointed
LICENSE                           (NEW, Q8)
agents/PROMPT_CHANGELOG.md        (required by a test; stays here)
benchmark/RECOMMENDATION.md       (generated; stays here)
benchmark/submissions/TASK.md     (required by a test)
docs/
  ARCHITECTURE.md   AUTHORING.md   DECISIONS.md   DECISIONS_AGENTS.md   GLOSSARY.md
  INSTALL.md        KNOWN_ISSUES.md  OPERATIONS.md  PILOT.md   agents.md   explanation.md
  resources_review.md   resources_template.csv
  ROADMAP.md        (NEW, section 8)
  DATA_PROTECTION.md (NEW, section 8)
  archive/
    README.md            (NEW: 5-line index)
    DEVELOPMENT_MAP.md
    code_agent_flow.md
tests/fixtures/agents/README.md   (required by a test)
```

Leaves the repository (to a folder outside it; nothing is deleted): `docs/STATUS.md`, `docs/FINALIZE_PROGRESS.md`, `docs/CLEANUP_PLAN.md`, `docs/CONTEXT_POLICY.md`, `docs/MODEL_ROUTING.md`, `docs/START_HERE.md`, `docs/WORKFLOW.md`, this file `docs/DOCS_TRIAGE.md`, and `docs/CURRENT_DEMO.md` after its useful queries are merged into OPERATIONS. Suggested private layout: `vdel-private/{sessions,evidence,analysis,dev-system,untracked-originals}/`. Count after the move: 22 existing `.md` stay (20 in place, 2 into `docs/archive/`) plus 3 new ones proposed (`ROADMAP.md`, `DATA_PROTECTION.md`, `docs/archive/README.md`).

## 6. Links and references that break when the files leave

Only mentions inside documents that REMAIN are listed. Mentions inside the leaving documents themselves do not matter. `DECISIONS.md` is append-only; do not rewrite its history of mentions, add a one-line note at its top instead (Q5).

| In (remaining doc) | Line(s) | Points to | Suggested fix |
|---|---|---|---|
| CHANGELOG.md | 33 | docs/FINALIZE_PROGRESS.md (leaves) | drop the link |
| docs/KNOWN_ISSUES.md | 75, 153, 160 | docs/STATUS.md (leaves) | keep the decision id (D-096) and drop the file, or inline the sentence |
| docs/explanation.md | 502, 503 | docs/STATUS.md (leaves) | drop or inline |
| docs/explanation.md | 502, 1273 | docs/DEVELOPMENT_MAP.md (moves to docs/archive/) | re-point to docs/archive/DEVELOPMENT_MAP.md |
| docs/explanation.md | 502, 1491 | HANDOFF.md (not tracked) | drop |
| docs/explanation.md | 54, 58, 74, 125, 231, 475, 476, 670, 806, 1013, 1234, 1387, 1531, 1579, 1613, 1656, 2056, 2071, 2145, 2252, 2314, 2319, 2334, 2336, 2420 (25 lines) | CLAUDE.md (not tracked) | cite DECISIONS.md or the invariants listed in CONTRIBUTING.md |
| docs/explanation.md | 1757, 1770, 1772, 1793, 1831, 2063, 2147, ... | EXECUTION.md (not tracked) | inline or drop |
| docs/explanation.md | 50, 67, 74, 414, 506, 2400, ... | VDEL_Modules_*_Build.md, VDEL_v1_Execution_Plan.md, vdel_complete_design_document.md (not tracked) | see Q1: either deliver sanitized copies under docs/design/ or say 'formula source: author's design documents (available on request)' |
| docs/agents.md | 30, 49, 51 | CLAUDE.md (not tracked) | cite DECISIONS.md |
| docs/agents.md | 49, 51 | VDEL_REDESIGN.md (not tracked) | cite D-035 in DECISIONS.md |
| docs/DECISIONS_AGENTS.md | 131, 190 | AGENTS_OVERNIGHT_REPORT.md (never committed); CLAUDE.md | drop |
| agents/PROMPT_CHANGELOG.md | 14, 32, 8, 21 | CLAUDE.md, HANDOFF.md, BUILD_PLAN.md, VDEL_Modules_3_9_Build.md (not tracked) | inline the one fact each |
| benchmark/RECOMMENDATION.md | 109 | CLAUDE.md (not tracked) | generator text in run_real_benchmark.py; fix there |
| VDEL_TEN_PROJECT_CURRICULUM.md | 17, 148, 457 | VDEL_REDESIGN.md (not tracked) | cite D-035 or deliver the design file (Q1) |
| docs/DECISIONS.md | see counts | CLAUDE.md 51x, BUILD_PLAN.md 14x, VDEL_REDESIGN.md 14x, STATUS.md 5x, docs/reading/ 8x, DEVELOPMENT_MAP.md 10x, code_agent_flow.md 3x, START_HERE.md 1x, FINALIZE_PROGRESS.md 2x, MODEL_ROUTING.md 1x | leave as history; add a note at the top: 'files named here that are not in the repository stay with the author'; DEVELOPMENT_MAP.md and code_agent_flow.md keep their file names under docs/archive/. Path-form mentions: docs/DEVELOPMENT_MAP.md at DECISIONS.md:806 and docs/code_agent_flow.md at :4345-4348 need the archive/ segment |

Code comments and messages that name a document leaving the repo or sitting untracked (information; none is a functional dependency): `collectors/collect_github.py:69` (STATUS.md); `agents/echo_agent.py:9`, `agents/tools.py:40`, `tests/test_echo_agent.py:5`, `tests/test_tools.py:8`, `tests/test_validation.py:7` (DEVELOPMENT_MAP, still resolves by file name in docs/archive/); `CLAUDE.md` in 36 files, `VDEL_REDESIGN.md` in 24, `VDEL_Modules_1_2_Build.md` in 19, `VDEL_Modules_3_9_Build.md` in 11, `EXECUTION.md` in 8, `BUILD_PLAN.md` in 4 (`git grep -l` gives the lists). Messages that point to a document that STAYS: `scripts/doctor.py:49,380` and `register_task.ps1:23,97` and `docker/grader.Dockerfile:12` (OPERATIONS.md sections 2, 11, 12), `config/roster.example.yaml:17` and `sql/pilot/vdel_cycle_role.sql:7` (PILOT.md).

## 7. Reachability from README.md, and the index to write

Direct from README today (10): `CHANGELOG.md`, `CONTRIBUTING.md`, `docs/ARCHITECTURE.md`, `docs/AUTHORING.md`, `docs/DECISIONS.md`, `docs/GLOSSARY.md`, `docs/INSTALL.md`, `docs/KNOWN_ISSUES.md`, `docs/OPERATIONS.md`, `docs/PILOT.md`.

Reachable only in two hops (through another doc): `docs/agents.md`, `docs/explanation.md`, `docs/DECISIONS_AGENTS.md`, `agents/PROMPT_CHANGELOG.md`, `benchmark/RECOMMENDATION.md`, `benchmark/submissions/TASK.md`, `tests/fixtures/agents/README.md`, `VDEL_TEN_PROJECT_CURRICULUM.md`, and (until archived) `DEVELOPMENT_MAP.md`, `code_agent_flow.md`. **Not reachable at all: `docs/resources_review.md`.**

A README documents table to add (one line each): `docs/ARCHITECTURE.md` (how it fits), `docs/agents.md` (agent contracts), `docs/explanation.md` (file-by-file reference), `docs/AUTHORING.md` (write a project), `docs/OPERATIONS.md` (run it), `docs/PILOT.md` (before students), `docs/KNOWN_ISSUES.md` (what is wrong), `docs/DECISIONS.md` and `docs/DECISIONS_AGENTS.md` (why), `docs/GLOSSARY.md`, `CHANGELOG.md`, `agents/PROMPT_CHANGELOG.md`, `VDEL_TEN_PROJECT_CURRICULUM.md` (projects 1-10), `docs/resources_review.md` (provenance of the resources), `benchmark/RECOMMENDATION.md` (judge benchmark), `docs/archive/` (history), plus the two new files. Also update: README 'Where things are' (the `docs/` line), `CONTRIBUTING.md` 'Documents, one job each' table (lines 114-126, which lists the old doc roles) and `docs/ARCHITECTURE.md`'s pointers if it lists docs. A new `docs/archive/README.md` should say in five lines that these are dated analyses, not current references.

## 8. What a maintainer needs and does not have (proposed, not written)

### docs/ROADMAP.md (next steps with the real open work)

- 1. Open work in priority order, each with the document that records it.
- 2. First real run of the v2 agents (Feedback v2, Code Agent v2 behind `--agents-v2`; the Code Agent prompt v4 was never benchmarked; 'Going further' stays locked until `weather_etl` labels exist).
- 3. Bulk publishing / delivery for a 3-5 student pilot (today one student at a time; pilot role SQL never executed).
- 4. Code health: shared GitHub client / token / git helpers and roster editing (the X1-X4 items of the cleanup analysis), the long functions, `FakeLLM` seams.
- 5. Science: production-mode benchmark, BKT fitting once data exists, V5/V6 'unclassified' handling, the formula-version policy.

Pull from: KNOWN_ISSUES.md items 6, 11, 18, 21-23; D-105..D-110; CLEANUP_PLAN.md X1-X7; benchmark/RECOMMENDATION.md; HANDOFF (private) open questions.

### docs/HOWTO_EXTEND.md (or a section of CONTRIBUTING.md): add a project, a gap, a check, an agent, a variable

- 1. Project/gap/check: three commands (`validate_master`, `seed_data`, `roster_apply`) and where each file goes.
- 2. A check: `config/checks.yaml` entry, `reviewed` status rule.
- 3. An agent: the five-stage skeleton, the schema/evidence/delimiter rules, how to test with the fake LLM.
- 4. A variable: file, `formula_ver`, observation count `n`, the test that pins it.
- 5. The decision-log rule: every stable choice gets a D-number.

Pull from: AUTHORING.md sections 2-12; CONTRIBUTING.md; docs/agents.md; ARCHITECTURE.md sections 6-7; docs/GLOSSARY.md.

### docs/RELEASE_AND_UPGRADE.md (release and upgrade note)

- 1. There are no version tags: say what 'v1' means and propose a first tag.
- 2. Schema migrations: `sql/` is applied in order and idempotent; list files 06-10 and how to upgrade an existing database.
- 3. Formula versions: stored rows keep their `formula_ver`; what recomputation does.
- 4. Dependency pins (not yet verified on Python 3.11) and the grader image.
- 5. How to run the baseline before and after an upgrade.

Pull from: CHANGELOG.md; INSTALL.md; DECISIONS D-105, D-099; scripts/baseline.py; docker/grader.Dockerfile.

### LICENSE and ownership (a question, not a document)

- 1. No LICENSE file exists.
- 2. State who owns the code (author, university, industry partner).
- 3. Choose a licence or 'all rights reserved' explicitly.
- 4. Note the third-party licences of the dependencies.
- 5. Decide the authors line in README.

Pull from: none in the repo; needs the author, the supervisor and the partner (Q8).

### docs/DATA_PROTECTION.md

- 1. What student data is stored (names, code, traces) and where (Postgres, backups/).
- 2. What leaves the machine: code excerpts to an AI provider, with the student notice.
- 3. Opt-out (`ai_notes: false`), retention and deletion (not written down today).
- 4. Consent route to be confirmed by the course author and the data-protection owner.
- 5. The pilot database role (never executed).

Pull from: PILOT.md; KNOWN_ISSUES.md item 23; D-110; rendered DATA_NOTICE in scripts/render_student_repo.py.

### A sanitized CLAUDE.md (only if the professor will use an AI assistant)

- 1. The 16 invariants and the layout (no persons, no schedule).
- 2. The commands to run the suite and the baseline.
- 3. The stop-and-ask triggers.
- 4. Pointers to the kept docs instead of the private ones.
- 5. No instruction that names the author.

Pull from: the current local CLAUDE.md; CONTRIBUTING.md; ARCHITECTURE.md section 6.

## 9. Exposure by handover mode

### A. Full git history

The repository has 111 commits on 5 local branches (`main`, `cleanup`, `feature/agents`, `v1-finalize`, `docs-triage`) and 2 remote-tracking branches (`origin/main`, `origin/feature/agents`), 2026-08-02 to 2026-10-13. Every document ever committed is still tracked: **no `.md`/`.html`/`.pptx`/`.pdf`/`.docx`/`.txt` path in history is absent from the current tree**, so there are no deleted documents to list. (Documents classified PRIVATE therefore exist in history under their current paths):

| Path | Class | Commits touching it | First..last |
|---|---|---|---|
| `CHANGELOG.md` | KEEP-AFTER-EDIT | 5 | 2026-10-13..2026-10-13 |
| `README.md` | KEEP-AFTER-EDIT | 4 | 2026-08-02..2026-10-13 |
| `VDEL_TEN_PROJECT_CURRICULUM.md` | KEEP-AFTER-EDIT | 1 | 2026-08-31..2026-08-31 |
| `docs/ARCHITECTURE.md` | KEEP-AFTER-EDIT | 1 | 2026-10-13..2026-10-13 |
| `docs/CLEANUP_PLAN.md` | PRIVATE | 1 | 2026-10-13..2026-10-13 |
| `docs/CONTEXT_POLICY.md` | PRIVATE | 1 | 2026-10-13..2026-10-13 |
| `docs/CURRENT_DEMO.md` | MERGE | 1 | 2026-10-13..2026-10-13 |
| `docs/DECISIONS.md` | KEEP-AFTER-EDIT | 29 | 2026-08-31..2026-10-13 |
| `docs/DECISIONS_AGENTS.md` | KEEP-AFTER-EDIT | 1 | 2026-10-11..2026-10-11 |
| `docs/DEVELOPMENT_MAP.md` | ARCHIVE | 1 | 2026-10-13..2026-10-13 |
| `docs/FINALIZE_PROGRESS.md` | PRIVATE | 6 | 2026-10-13..2026-10-13 |
| `docs/KNOWN_ISSUES.md` | KEEP-AFTER-EDIT | 6 | 2026-10-13..2026-10-13 |
| `docs/MODEL_ROUTING.md` | PRIVATE | 1 | 2026-10-13..2026-10-13 |
| `docs/OPERATIONS.md` | KEEP-AFTER-EDIT | 10 | 2026-10-11..2026-10-13 |
| `docs/START_HERE.md` | PRIVATE | 1 | 2026-10-13..2026-10-13 |
| `docs/STATUS.md` | PRIVATE | 2 | 2026-08-31..2026-10-11 |
| `docs/WORKFLOW.md` | PRIVATE | 1 | 2026-10-13..2026-10-13 |
| `docs/agents.md` | KEEP-AFTER-EDIT | 2 | 2026-10-11..2026-10-12 |
| `docs/code_agent_flow.md` | ARCHIVE | 3 | 2026-10-12..2026-10-12 |
| `docs/explanation.md` | KEEP-AFTER-EDIT | 21 | 2026-08-31..2026-10-13 |
| `docs/resources_review.md` | KEEP-AFTER-EDIT | 1 | 2026-10-12..2026-10-12 |

Whatever is moved out of the tree in a later commit stays readable in earlier commits. History-wide pattern scan (`git log --all -G<pattern>`, commit counts and short ids only):

| Pattern | Commits | Where | Needs action |
|---|---|---|---|
| `ghp_` / `github_pat_` tokens (20+ chars) | 1 (`50af0ae`) | `tests/test_doctor.py`, `tests/test_roster_apply.py`: invented values used to test the redaction | no |
| `sk-` keys (20+ chars) | 4 (`50af0ae`, `219ce2d`, `5770cbd`, `d836c15`) | tests only (`test_llm*.py`, `test_doctor.py`, `test_roster_apply.py`): dummy values given to `monkeypatch.setenv` / client constructors | no |
| `AKIA...`, `Bearer <30+ chars>`, private-key blocks | 0 | n/a | no |
| `*_KEY/TOKEN/PASSWORD/SECRET=<16+ chars>` | 2 (`c2349cc`, `9ce4694`) | `9ce4694` is `.env.example` placeholders; `c2349cc` test fixtures | no |
| e-mail addresses in blobs | 2 (`c7af83a`, `1af37dd`) | two test files; the only domain is `example.com` | no |
| local drive-letter user paths | 6 (`7291001`, `e4afb91`, `7f66c22`, `fc602cd`, `89c7131`, `f0090ae`) | `docs/OPERATIONS.md` (4 commits), `docs/STATUS.md`, `docs/CLEANUP_PLAN.md` | yes if you want them gone: only a rewrite of history removes them |
| the author's school name | 4 (`e4afb91`, `7f66c22`, `fc602cd`, `f0090ae`) | `docs/OPERATIONS.md` only (inside the local path) | same |
| author's GitHub login | 6 (`4c49e94`, `a2674f1`, `72c1925`, `724295d`, `74d5947`, `72c0c2f`) | `docs/DECISIONS.md` (2), `docs/explanation.md`, `scripts/demo.py`, two tests | same; the login is also the remote's owner name |
| the second login named in the brief | 0 | n/a | no |

Other history exposure (not in blobs): **commit author metadata**: 95 commits carry a noreply GitHub address and **16 carry a personal Gmail address** (visible to anyone with the history); **21 commit messages** contain a `Co-Authored-By` trailer (AI attribution); commit messages describe sessions and internship milestones. `.env`, `config/roster.yaml`, `backups/`, `logs/` and `*.bak` were never committed.

**Rotation.** Nothing needs rotation on the evidence of this scan: no real token, key or password pattern appears in any revision. A pattern scan cannot prove absence (a secret in an unusual shape would be missed); if the GitHub token or the OpenAI key was ever pasted into a document, a commit message or an issue, rotate it. I did not read `.env`.

Remote: `origin` points to a GitHub repository under the author's login; `main` and `feature/agents` exist there. Visibility is unknown. If it is public, the history is already public; removing a file later does not remove it from clones.

### B. Fresh repository from the final tree (one import commit)

- **Disappears**: all 111 commits, their dates (2026-08-02..10-13), author and committer metadata (including the Gmail address), the 21 `Co-Authored-By` trailers, every branch, the per-file history of the documents, and the commit-message rationale.
- **Preserved**: `docs/DECISIONS.md` (111 `D-` entries, append-only, the viva answer sheet) and `docs/DECISIONS_AGENTS.md` (26 entries), `CHANGELOG.md` (map by period), `KNOWN_ISSUES.md` (24 items), `agents/PROMPT_CHANGELOG.md` and the code comments that cite `D-nnn`. The rationale is therefore intact; the *evidence* behind it is not: pasted run outputs live in `STATUS.md` (private) and commit messages.
- **Still leaks unless sanitized**: the lines in section 3 (login in 2 docs and 3 code files, local path in 5 `OPERATIONS.md` lines, names). A fresh repo removes history exposure only; the tree must still be cleaned.
- **Still missing**: the untracked authority documents (finding 1) and a LICENSE.
- **Authorship**: the import commit would carry the identity configured at the time; the professor sees no record of who wrote what unless the README or LICENSE says so.

### `.gitignore` versus kept documents

`.gitignore` ignores `CLAUDE.md`, `BUILD_PLAN.md`, `EXECUTION.md`, `SETUP.md`, the design documents (`VDEL_Modules_1_2_Build.md`, `VDEL_Modules_3_9_Build.md`, `VDEL_v1_Execution_Plan.md`, `VDEL_REDESIGN.md`, `vdel_complete_design_document.md`), `docs/HANDOFF.md`, `docs/FRAMEWORK_STATUS.md`, `docs/reading/`, `docs/design/`, `docs/*OVERNIGHT_REPORT.md` and `docs/STATUS.md`. **Yes: kept documents reference ignored ones** (section 6): `docs/explanation.md` (CLAUDE.md 25 lines, BUILD_PLAN.md 4, VDEL_Modules_* 9, EXECUTION.md 7, VDEL_REDESIGN.md 1, HANDOFF.md 2), `docs/agents.md` (CLAUDE.md 3, VDEL_REDESIGN.md 2), `agents/PROMPT_CHANGELOG.md` (4), `docs/DECISIONS.md` (about 100 mentions), `docs/DECISIONS_AGENTS.md` (2), `VDEL_TEN_PROJECT_CURRICULUM.md` (3), `benchmark/RECOMMENDATION.md` (1). Code does not READ any ignored document (no test or script opens them), so the suite is unaffected.

## 10. Questions for you

**Q1. The authority documents.** Do the professor and the code's own rule ('the documents win') need `VDEL_Modules_1_2_Build.md`, `VDEL_Modules_3_9_Build.md`, `VDEL_REDESIGN.md`, `vdel_complete_design_document.md`? Options: (a) deliver sanitized copies under `docs/design/` (largest effort), (b) deliver nothing and rewrite the 100+ citations as 'author's design notes, available on request', (c) deliver only the formulas in a new `docs/FORMULAS.md`.

**Q2. Handover mode.** Full history (then the history rows of section 9 apply: local paths, login, Gmail metadata, trailers) or a fresh repository with one import commit? If full history, do you accept the exposure, or will you rewrite it before handing over?

**Q3. Names.** Keep the author, collaborator and supervisor names as attribution (README line 86, 145 lines of `DECISIONS.md`, code comments), or replace them by roles? This decides how many lines of section 3 change.

**Q4. STATUS.md.** Move it unchanged to the private folder, or first distil a short 'what has been proven, with the command' page for the professor (the DoD evidence is the only record of live runs)?

**Q5. DECISIONS.md.** It is append-only and mentions private files about 100 times: keep it untouched with a one-line note at the top, or sanitize the two login lines only? Also: merge `DECISIONS_AGENTS.md` into it (the code cites the D-2xx ids, so ids must stay), or keep two files?

**Q6. code_agent_flow.md.** Archive as a historical snapshot (my proposal), or refresh it to the current code before handover? The same question for `explanation.md`: banner and trim, or split into 'current reference' and 'history'?

**Q7. DEVELOPMENT_MAP.md.** Archive (my proposal, 10 DECISIONS citations resolve by file name) or move to the private folder?

**Q8. LICENSE and ownership.** Who owns the code (you, the university, the industry partner), and which licence, if any? No LICENSE exists.

**Q9. CLAUDE.md.** Will the professor use an AI assistant on this repo? If so I would propose a sanitized `CLAUDE.md`; if not, it stays private.

**Q10. The remote.** Is `origin` (GitHub) public? If yes, the history is already exposed whatever you decide here.

**Q11. Generated text.** May the stale 'benchmark/TASK.md is missing' sentence be fixed in `benchmark/run_real_benchmark.py:345` (code, not doc) and `RECOMMENDATION.md` regenerated? That needs a real LLM run or a template-only rerun; I did neither.

**Q12. VDEL_TEN_PROJECT_CURRICULUM.md.** Keep at the repository root (four code comments cite that path) or move to `docs/design/` and re-point the comments?

## 11. Review commands

```
git diff --stat main...docs-triage
git log --format="%h %an <%ae> | %cn <%ce>" main..docs-triage
git show --stat docs-triage
```

Scratch scripts and raw data (outside the repo): `C:\Users\ASUS\AppData\Local\Temp\vdel_docs_triage.QnKfFR` (`facts.py`, `links.py`, `build.py`, `facts.json`, `links.json`).
