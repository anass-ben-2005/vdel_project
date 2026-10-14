# HOWTO_EXTEND.md: add a project, a gap, a check, an agent or a variable

Section 1 is a full checklist for a new project; the other sections are short pointers to where each extension is
described in full. Every step names the document or file that holds it. Always work the way `CONTRIBUTING.md` says (a branch, the baseline before and
after, the suite on its own database, a decision entry).

## 1. Add a new project, end to end

This is the checklist for adding a project to the curriculum, beyond `weather_etl` and `sales_analyzer`.
[AUTHORING.md](AUTHORING.md) stays the reference for the layout (section 1), the marker syntax (2), concepts (3), the test
conventions (4 and 5), resources (6), check descriptions and judging (7 and 8), changing a master (10) and the validator
(11); this section gives the order of the work, the commands and the proof that each step worked. Anything that could not
be confirmed against the code is marked `TODO(verify)`.

### What a project is

- A **project** is a directory `curriculum/master/<project_id>/` that mirrors the student repository. The importable
  package lives at `curriculum/master/<project_id>/<project_id>/` (`scripts/seed_data.py` `seed_curriculum`).
- A **stage** is one assignment and one file: `<project_id>/<stage>.py`. Its assignment id is `<project_id>_<stage>` and
  its `file_path` is `<project_id>/<stage>.py`. The same string is a path in the master tree, a path in the student
  repository and the file name GitHub reports in a commit, which is how a commit is attributed to an assignment (D-043).
- A **gap** is a region of a stage file marked in the master. In some attempts it is hidden from the student and replaced by
  its instruction. Each gap carries concept ids, a difficulty and an instruction; hidden tests are attributed to gaps.
- The master file is the **complete, correct solution**. The student receives a rendered copy.

### Decide before you start

| Decision | Guidance |
|---|---|
| `project_id` | snake_case. It is the package name and part of the repository name: `vdel-<project_id with _ as ->-gapfill-<student_id>` for attempt 1 (`scripts/publish_repo.py` `default_repo_name`). |
| Stages, in order | Their order becomes `assignments.seq`. The stage names are listed by hand in step 8, not discovered. |
| Concepts per stage | Tag a stage's gaps with **at least two different concepts**. Variant choice picks a concept and hides every gap that carries it (D-042); a stage whose gaps all share one concept can only ever produce one variant, so every student gets the same one. `weather_etl` `load` and `quality` are that case (D-058). |
| One gap = one skill | A rule of thumb, not enforced by any code: a block a student can write without help (roughly 10 to 30 lines) with one behaviour a test can check. Keep each gap small and testable by itself (AUTHORING section 4). |
| Dependencies | Hidden tests run offline. With the container on (`VDEL_GRADING_SANDBOX=docker`, required for a pilot, D-086) they run with no network in an image that has only the packages in `docker/grader-requirements.txt` (D-092); with the container off they run in a host subprocess (D-065). Every package the master imports must be in the image (step 9). |
| Determinism | No network, no clock, no randomness in a hidden test. Fake them. |

### The steps

| # | Do | Where | Proof it worked |
|---|---|---|---|
| 1 | Write the **complete solution** of each stage, importable and passing its own tests. Add the package `__init__.py` and the project `requirements.txt` (runtime packages the student's CI installs; copy the shape of `weather_etl`'s). | `curriculum/master/<project_id>/<project_id>/<stage>.py`, `__init__.py`; `curriculum/master/<project_id>/requirements.txt` | `cd curriculum/master/<project_id> && python -c "import <project_id>.<stage>"` |
| 2 | **Mark the gaps** with `# @gap:` and `# @instruct:` (AUTHORING section 2). The parser rejects a missing `id=` or `concepts=[...]`, a missing `@instruct`, an empty body, a nested or unclosed gap, a duplicate id inside the file and an unknown concept (`assessment/gap_parser.py` `parse_master`, `GapParseError`). A gap id must be unique across the whole curriculum, not just the project (`gaps.gap_id` is the primary key); only the validator checks that across files. Write `id=` first and `concepts=[...]` right after it, as in AUTHORING: `tests/test_resources_seed.py` finds concepts with that exact shape. | the stage file | `python -c "from assessment.gap_parser import parse_master; [print(g.gap_id, g.concept_ids, g.line_start, g.line_end) for g in parse_master('curriculum/master/<project_id>/<project_id>/<stage>.py')]"` lists every gap without a `GapParseError` |
| 3 | Write the **visible tests**: `tests/visible/test_<stage>.py`. They must run standalone: no `conftest.py` in `tests/visible`, no `@pytest.mark.gap`, no import from `assessment` (`tests/test_visible_tests_standalone.py` checks every project). | `curriculum/master/<project_id>/tests/visible/` | `cd curriculum/master/<project_id> && python -m pytest tests/visible -q` passes |
| 4 | Write the **hidden tests**: `tests/hidden/test_<stage>.py`; the file name is required, the grader looks up `test_<stage>.py` and fails with a `TestRunnerError` otherwise (`assessment/test_runner.py` `_hidden_test_file`). Mark each test `@pytest.mark.gap("<gap_id>")` and name it after the behaviour it checks. Copy `tests/hidden/conftest.py` from `weather_etl`: it turns the marker into the JUnit property that attributes a result to a gap, and without it every gap id silently comes back empty (`assessment/test_runner.py` `_inject_hidden_test`). | `curriculum/master/<project_id>/tests/hidden/` | `cd curriculum/master/<project_id> && python -m pytest tests/hidden -q` passes (100 %). Run it **apart from** the visible tests: files with the same name in the two folders make a combined run fail at collection |
| 5 | Add **new concepts** if the project teaches something not yet in the taxonomy (AUTHORING section 3; ids are schema: add, never rename). | `config/concepts.yaml` | step 2 stops complaining about unknown ids |
| 6 | Add at least **two verified learning resources** per concept the gaps use, at more than one level: `tests/test_resources_seed.py` asserts that (`MIN_PER_TIER1 = 2`). The validator only asks for one. Then load them into the database: the agents read the `resources` table, not the CSV (`agents/resources.py`). | `config/resources.csv` (AUTHORING section 6; `docs/resources_review.md` shows how the existing ones were checked) | `python -m scripts.load_resources config/resources.csv` (a dry run) lists no error; then `python -m scripts.load_resources config/resources.csv --apply --dsn "<the real PG_DSN>" --allow-real-db`; `python -m scripts.validate_master <project_id>` reports no missing resource |
| 7 | Write the **public descriptions**: one entry per hidden test in `config/checks.yaml` (behaviour, no code, no literal expected values) and an entry per assignment in `config/judging.yaml` with its task statement. Start as `draft`, read each against its test, then set `reviewed`; only `reviewed` entries are ever used (AUTHORING sections 7 and 8). | `config/` | `python -m scripts.validate_master <project_id>` exits 0 with no `ERROR`; `--require-reviewed` turns remaining drafts into errors |
| 8 | **Register the project.** Projects are not discovered: add a `seed_curriculum(cur, "<project_id>", stages=(...))` call to `main()` in `scripts/seed_data.py`, with the stage names in order (the existing calls are the model), and add the same call to the test database setup in `tests/conftest.py`. Back up the database first (`docs/OPERATIONS.md` section 9), then run `python -m scripts.seed_data`: it is idempotent, but it also needs `config/roster.yaml` and stops after seeding the curriculum if the roster is missing or invalid. **A stage name with no matching file is skipped silently**, so check the counts. | `scripts/seed_data.py` `main()`; `tests/conftest.py` | one line per project, `seeded curriculum: 1 project(s), N assignment(s), M gap(s) (master_version ...)`, with N and M equal to your stage and gap counts; `select assignment_id, seq, file_path from assignments where project_id = '<project_id>' order by seq;` lists the stages in order |
| 9 | Make sure the **grader image** has the dependencies. If the master or its tests import a package that is not in `docker/grader-requirements.txt`, add it there (pinned, with its own dependencies, as the file's comments show) and to the project's `requirements.txt`, then rebuild: `docker build -f docker/grader.Dockerfile -t vdel-grader:1 docker`. The tag stays `vdel-grader:1` (`assessment/test_runner.py` `DEFAULT_GRADING_IMAGE`; `VDEL_GRADING_IMAGE` names another image); rebuilding under the same tag replaces it. Otherwise every student commit ends as a `collection_error`. | `docker/grader-requirements.txt`, `curriculum/master/<project_id>/requirements.txt` | `python -m scripts.doctor` shows `grader image ... present`; `docker run --rm --network none vdel-grader:1 python -c "import <package>"` succeeds for each new package |
| 10 | **Render without publishing.** Use a test student who is in the database (the roster's `students` block, loaded by `seed_data`). The render runs inside a transaction that is rolled back, so nothing persists. | `python -m scripts.publish_repo --student <test_student> --attempt 1 --project <project_id> --dry-run` | the file list has no path containing `hidden`, the line `hidden-test check: PASS` appears and the output ends with `DRY RUN: nothing was created, pushed, written or persisted.` |
| 11 | **Acceptance run** with a test student on a second GitHub account (below). | | see the list below |
| 12 | **Record it.** Run the full suite and the baseline, add a decision entry (next D-number), update `README.md`, `CHANGELOG.md` and `docs/KNOWN_ISSUES.md`. Commit. | repository | `VDEL_REQUIRE_DB=1 python -m pytest -q` is green and `python -m scripts.baseline --full` differs from the earlier one only by the new project, assignment and gap rows |

What the student repository gets (`scripts/render_student_repo.py`): the rendered stage files, the package `__init__.py`,
`requirements.txt` copied verbatim, `tests/visible`, `ASSIGNMENT.md`, a generated `.github/workflows/ci.yml` (it runs
`pip install -r requirements.txt`, lints without blocking and runs the visible tests) and a root `conftest.py`. The
project author writes none of the last three, and no directory named `hidden` is ever written.

Two details for step 12. No test pins the number of projects, assignments or gaps (a search of `tests/` found only
`sales_analyzer`'s own concept tally in `tests/test_gap_parser.py`); the tests that DO react to a new project are
`tests/test_resources_seed.py` (the resource rule of step 6) and `tests/test_visible_tests_standalone.py` (step 3).
The baseline will show the new rows, which is expected.

### Acceptance run with a test student

1. Back up the database.
2. Add the test student to the `students` block of `config/roster.yaml` (the login of a second account you control), then
   run `python -m scripts.seed_data`.
3. Publish for real: `python -m scripts.publish_repo --student <test_student> --attempt 1 --project <project_id>` (it asks
   for confirmation unless you pass `--yes`, and needs a token with the `workflow` scope). The repository is private and
   owned by the instructor account, and the roster rows are written after the push. `publish_repo` does not invite
   anyone: add the test account as a collaborator with write access in the repository settings and accept the invitation
   from that account (only `deliver_next_attempt` invites, `scripts/deliver_next_attempt.py`).
4. From the test account, push a commit that leaves at least one check failing.
5. Run the cycle: `python -m scripts.run_hourly` (collect, grade, features, feedback) with `VDEL_GRADING_SANDBOX=docker`
   and `VDEL_ALLOW_GITHUB_WRITE=1` in the environment, or `python -m scripts.run_cycle --student <test_student>` followed by
   `python -m scripts.post_feedback --student <test_student> --issue --apply` (`docs/OPERATIONS.md` sections 4, 7 and 11).
   `run_cycle` alone collects and grades but never posts. Never run `grade_collected` by hand outside the Docker sandbox.
6. Read the comment posted on the repository's issue: the failing checks are named, no test code or expected value is
   shown, and the public description of the check reads well.
7. Push the correct solution. The next comment says all checks passed and the attempt is frozen (a stage freezes when its
   hidden tests reach 100 %, D-045). If the Code Agent is on (`--with-llm --with-code-agent`),
   `python -m scripts.code_agent_report --student <test_student>` shows its stored verdict.
8. For the next stage or attempt: `python -m scripts.deliver_next_attempt --student <test_student> --assignment <assignment_id>`
   prints the plan; add `--apply` with `VDEL_ALLOW_GITHUB_WRITE=1` to do it. It prints the roster rows to record; record
   them with `python -m scripts.roster_apply --student <test_student> --assignment <assignment_id> --owner <owner> --repo <repo>`
   and then the same command with `--yes` (`docs/OPERATIONS.md` sections 8 and 15).

### When it fails

| Symptom | Likely cause | Fix |
|---|---|---|
| `GapParseError` | a bad marker, or a concept id missing from `config/concepts.yaml` | fix the marker, or add the concept |
| `validate_master`: "has no entry in config/checks.yaml" or "no entry for ... in config/judging.yaml" | step 7 not finished | add the entry |
| Every gap comes back with no gap id in the results | `tests/hidden/conftest.py` is missing | copy it from `weather_etl` (step 4) |
| `TestRunnerError: no hidden test file for project ... stage ...` | the hidden file is not named `test_<stage>.py` | rename it |
| A student commit ends as `collection_error` | a syntax error in the master, or a package missing from the grader image | step 9 |
| `hidden-test check` fails | a path component named `hidden` reached the rendered repository | hidden tests belong only in the master's `tests/hidden/` |
| `seed_data` reports fewer assignments than stages | a stage name does not match a file (it is skipped silently) | fix the tuple in `main()` |
| `publish_repo`: "unknown student" or "unknown project" | `seed_data` has not run for that student or project | step 8 |
| Nothing is collected for a student | the roster has no row for that repository | `python -m scripts.run_cycle --dry-run --student <id>`, then `roster_apply` |
| `open attempt ... has no roster repo` in the log | the attempt was created but never published | expected until step 11 |

### Not automatic today

- Project registration is hard-wired in two places, `scripts/seed_data.py` `main()` and `tests/conftest.py`. A small
  manifest per project (stages, order) would remove the only code edits from this checklist ([ROADMAP.md](ROADMAP.md)).
- There is no scaffold command that creates the directory layout.
- `sales_analyzer` has no `checks.yaml` or `judging.yaml` entries, so `python -m scripts.validate_master sales_analyzer`
  reports 17 errors for it. It is the example of an unfinished project.
- Drafting check descriptions and task statements is manual. An instructor-only assistant for the drafts, with every
  line reviewed by a person, is an idea, not built.

## 2. A gap (a block the student must write)

Mark it in the master file between `# @gap:id=<gap_id> concepts=[<concept>, ...] difficulty=<0..1>` and `# @endgap`, with an
`# @instruct:` line (`docs/AUTHORING.md` section 2),
use a unique id across the whole curriculum, a concept from `config/concepts.yaml`, an honest difficulty, and cover it
with at least one hidden test marked `@pytest.mark.gap("<id>")` (D-046). The validator checks all of this.
A student's file is generated from the master by `assessment/gap_generator.py`; how a variant is chosen is
D-035 and D-042.

## 3. A check (the public description of a hidden test)

An entry in `config/checks.yaml` per hidden test: the test name, its gap, a one-sentence behaviour description and a
`status`. Only `reviewed` entries are ever used; a `draft` is ignored by the loader (`config/checks.py`,
`config/_loader.py`, D-107). A student sees a failing check by its name and the exception type only (D-077).
`docs/AUTHORING.md` section 7.

## 4. An agent

1. Read `CLAUDE.md` section 8 (the agent skeleton: tools, assemble, judge, validate, commit) and the invariants in
   section 7: every LLM call goes through `system/llm.py` (3), temperature 0 for judging (4), schema validation then
   one corrective retry (5), verbatim evidence quotes (6), the submission is data (7), no agent executes submitted
   code (12), correctness comes from executed tests, never from a model (13).
2. Follow `docs/agents.md` (inventory and contracts, sections 2 to 8) and the existing agents as templates:
   `agents/code_agent.py`, `agents/feedback_agent.py`, `agents/feedback_v2.py`.
3. Test with the fake LLM (`agents/fake_llm.py`; `CONTRIBUTING.md`, "The fake LLM rule"): a test that reaches a real
   provider is a bug.
4. Prompts are code: a change bumps the version and adds an entry to `agents/PROMPT_CHANGELOG.md`.
5. A new agent ships behind a flag that is off by default and writes only through `memory/memory.py`
   (`CLAUDE.md` section 7, invariant 2); see how `--agents-v2` is wired in `scripts/run_hourly.py` and
   `scripts/run_cycle.py` (D-099, D-104, D-108).

## 5. A variable

1. A variable is a pure function with no I/O in `variables/` (`docs/explanation.md` section 7): scaled to [0,1],
   higher is better, and it ships with its observation count `n` (`CLAUDE.md` section 8, invariant 8).
2. Compute it in `features/compute_features.py`; a new rule bumps `FORMULA_VER` and gets a decision that says what
   earlier rows keep (`docs/RELEASE_AND_UPGRADE.md` section 3).
3. A test pins the formula against a worked example. The existing ones are `tests/test_variables.py` and `tests/test_sara.py`.
4. Where a formula comes from a module document, cite it (`docs/design/VDEL_Modules_1_2_Build.md`) and record any
   divergence in `docs/DECISIONS.md` rather than tuning the number to fit.

## 6. Recording the change

Append a decision (`CONTRIBUTING.md`, "Writing a decision"): find the next free number with
`grep -n "^### D-" docs/DECISIONS.md | tail -3`, never reuse or renumber one. Update the documents the change makes
untrue; the index of documents is the table in `README.md`.
