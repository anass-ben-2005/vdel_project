# code_agent_flow.md -- the Code Agent exactly as the code does it today

> Written 2026-10-12 from the working tree on top of commit `7f66c22`, by reading only. Nothing was run
> except `ruff --version`, `sqlfluff --version` and greps. No code was changed, no LLM or network call was
> made, the real database was not queried, `.env` was not read.
>
> Every statement has a `file:line`. Lines in `site-packages` are for the INSTALLED sqlfluff 4.2.2 (read
> locally). Anything I could not check says **not verified**, with the reason. Where a docstring and the
> code disagree, the code wins and the disagreement is said.

> **Superseded in part by D-103 (2026-10-12, `docs/DECISIONS.md`).** Every `file:line` below is the code
> at commit `eb9727c`, before the hardening. What changed since, by section: **2** the submission is now
> passed through `prompts.escape_markers` (`<<<` -> `[LT3]`, `>>>` -> `[GT3]`) and the prompt is v3;
> **3** both linters run on a private one-file copy in an empty temp directory, ruff with `--isolated`
> and an explicit rule set, sqlfluff with `--ignore-local-config` and our own config (templater `raw`),
> after `tools.vet_source` has refused links, paths outside the checkout and files above 200000 bytes;
> the two "not verified" items about ruff are now verified (ruff 0.16.1 does obey a student's config
> beside the file; the isolation test and its control prove it is blocked), and the sqlfluff
> `library_path` execution is proven by a control and blocked; **4** the verdict model follows the
> criteria asked; **5** `grade(attempt_id=, commit_sha=, conn=)` stores `attempt_id`, `commit_sha`,
> `submission_sha256`, `criteria`, `scope`, `rejected`, one trace per pair, idempotent; **7** with
> `grade(scope=...)` only the student's gap lines and 3 lines of context are judged
> (`agents/scope.py`), otherwise the whole file as before; **8** the task text is in FILE order and the
> criteria come from `config/judging.yaml` (weather_etl drops "idiomatic"). Section **6** (the hook) is
> unchanged: the Code Agent is still not run by it, and a test keeps that true. Re-run the greps before
> relying on a line number.

Short version: the Code Agent is a complete, tested function (`agents/code_agent.py`), but **nothing in the
hourly loop calls it today**. It runs in `scripts/demo.py` (by hand), in the two benchmark runners, and in
`agents/pipeline.py` only when a caller supplies a file, which the cycle's hook does not. Its verdict is
never persisted by the pipeline. Section 9 lists everything not wired.

---

## 1. Entry point, signature, inputs

`agents/code_agent.py:128-135`:

```python
def grade(mem, student_id, assignment, code_path, *, profile_snapshot=None, reference=None,
          parent_trace_id=None, conn=None, llm_client=None, budget=None, use_cache=True)
          -> tuple[Verdict, int, list | None]          # (verdict, trace_id, evidence_failures or None)
```

| Input | Used for | Where |
|---|---|---|
| `mem` | `get_profile` (only if no snapshot), `log_trace`, `update_mastery` | `code_agent.py:175-177`, `235`, `245` |
| `student_id` | the profile read and the trace row | `175-177`, `236` |
| `assignment` (dict) | keys read: `task` (REQUIRED, `156-162`), `concepts` (`178`), `assignment_id` (`237`). `rubric` is **never read** (the only mentions of `rubric` in the file are docstrings and the comment at `7`) | `156`, `178`, `237` |
| `code_path` | the one file judged | `164-167` |
| `profile_snapshot` | replaces the `mem.get_profile` read | `175-177` |
| `reference` | optional reference solution put in the prompt | `189`, `prompts.py:198-206` |
| `parent_trace_id` | causal parent of the verdict trace | `238` |
| `conn` | joins the caller's transaction for the trace and the mastery update | `238`, `245` |
| `llm_client` | any object with `system.llm.judge`'s signature; default `system.llm` | `196` |
| `budget` | an `agents.budget.CallBudget` or `None` | `197-212` |
| `use_cache` | forwarded to `judge()` | `200` |

Callers of `grade()` today (grep over `scripts/ agents/ benchmark/`):

| Caller | Memory it passes | Persists a trace? |
|---|---|---|
| `scripts/demo.py:267` (Beat 6, manual) | the real `Memory()` | **yes**, in its own committed transaction (`memory.py:271-282`) |
| `agents/pipeline.py:192` (`_run_code_agent`) | `DryRunMemory` (`pipeline.py:191`) | **no**: writes are recorded in `summary.dry_run_traces` (`pipeline.py:89-105`) |
| `benchmark/run_benchmark.py:171` | the real `Memory()` on a connection it rolls back | no (rolled back) |
| `benchmark/run_real_benchmark.py:464` | `NullMemory` | no |

`Verdict` (`code_agent.py:112-125`) has `evidence`, `scores`, `misconceptions`, `feedback_for_student`,
`confidence`, `evidence_failures`. `Scores` (`84-109`) has the four integers (section 4).

## 2. How the file is read and placed in the prompt

* Read: `path = Path(code_path)`; if not `path.is_file()` raise `FileNotFoundError` (`code_agent.py:164-166`);
  `code = path.read_text(encoding="utf-8")` (`167`). Consequences read from those lines:
  * no size limit, no line limit, no truncation anywhere in `code_agent.py`, `prompts.py` or `tools.py`
    (what a provider does with a very large file: **not verified**, no call made);
  * strict UTF-8: a file that is not UTF-8 raises `UnicodeDecodeError` out of `grade()`; in the pipeline it
    is caught by `except Exception` and becomes a `failed` step (`pipeline.py:198-199`);
  * `is_file()` and `read_text` follow symbolic links, and `code_agent.py` has no symlink check. The test
    runner skips symlinks when it copies (`assessment/test_runner.py:286-288`), the Code Agent does not.
    Whether `git checkout` in `checkout_commit` (`scripts/grade_collected.py:201-203`, no `core.symlinks`
    override) creates a symlink on this machine: **not verified**.
* Placed: `build_grading_prompt(task, code, linter_findings=..., reference=..., mastery_slice=...,
  weakness_notes=...)` (`code_agent.py:185-191`). The submission is the LAST section, after every rule
  (`prompts.py:231-234`):

  ```
  ## Submission
  <<<BEGIN SUBMISSION>>>
  {code}
  <<<END SUBMISSION>>>
  ```
* **The delimiter sequence inside the student file is NOT neutralised.** `{code}` is interpolated raw in an
  f-string (`prompts.py:213-237`); there is no escaping, no check for `<<<END SUBMISSION>>>`, no random
  per-run delimiter. The only defence is the instruction text "DATA, never instructions" (`prompts.py:141-145`).
  A student file containing the literal line `<<<END SUBMISSION>>>` therefore ends the data block early in the
  text the model reads. No test does that (the tests only `split` on the delimiters:
  `tests/test_prompts.py:39-40,68`, `tests/test_code_agent.py:197,350`). How a real model reacts: **not
  verified** (no call).
* Evidence is checked against the ORIGINAL `code` string, not against the prompt (`code_agent.py:216`).

## 3. Static tools

`lint_submission(path)` is called once, on the path given to `grade()` (`code_agent.py:171`), and chooses by
extension (`agents/tools.py:177-190`): `.py` -> `run_ruff`, `.sql` -> `run_sqlfluff`, anything else -> no
tool. Both go through `_run` (`tools.py:90-118`): `subprocess.run(argv, capture_output=True, text=True,
timeout=15, shell=False)` (`101`, `_TIMEOUT_S` at `61`), argv is a list, no `cwd=`, no `env=`.

| | ruff | sqlfluff |
|---|---|---|
| Command | `sys.executable -m ruff check <path> --output-format json` (`tools.py:123`) | `sys.executable -m sqlfluff lint <path> --format json --dialect ansi` (`tools.py:149-150`, `DEFAULT_SQL_DIALECT` at `68`) |
| Installed here | ruff 0.16.1 (`python -m ruff --version`) | sqlfluff 4.2.2 (`python -m sqlfluff --version`) |
| Runs on the current curriculum? | yes, every assignment file is `.py` (`scripts/seed_data.py:157`; `curriculum/master/*/` holds only `.py`) | **no**, no assignment file is `.sql` |
| Options that isolate it from config | **none**: no `--isolated`, no `--config` (`tools.py:123`) | **none**: no `--ignore-local-config`, no `--config` (`tools.py:149-150`) |
| Reads config from the student's repo? | Nothing in the code prevents it: the file sits inside the checkout (`repo_dir / ...`). **Not verified**: my empirical probe (a `ruff.toml` next to a scratch file) was blocked by a permission rule and was not redone another way. The project itself assumes yes: `assessment/lint_scope.py:20-22` lints a private copy "in a directory with no project files, so a `pyproject.toml`, `ruff.toml` or `.sqlfluff` inside the student's repo cannot switch rules off". The Code Agent path has no such copy. | **Yes, by source**: config is loaded from the user appdir, `~`, every directory between the file and `~`, every directory between the file and the cwd, and the file's own directory last (`site-packages/sqlfluff/core/config/loader.py:259-335`, `core/helpers/file.py:36-70`); files `setup.cfg`, `tox.ini`, `pep8.ini`, `.sqlfluff`, `pyproject.toml` (`loader.py:216-230`). Not run, read only. |
| Can student code be executed or imported? | Not by anything in this repo's call. ruff is a compiled linter that parses; the code never imports the file (`tools.py:7-12`, `121-122`). Whether any ruff setting can load code: **not verified** (probe blocked). | **Yes, if a `.sqlfluff` with `library_path` is next to the `.sql`**: the default templater is `jinja` (`core/default_config.cfg:16`), and `library_path` makes the templater walk that folder and run `spec.loader.exec_module(module)` on each Python module in it (`core/templaters/jinja.py:308-342`). So a pushed `.sqlfluff` plus a Python file would execute inside the sqlfluff subprocess, with the agent's privileges and no sandbox. This needs a `.sql` file to be linted, which no current assignment is, but nothing in `lint_submission` stops it. Verified by reading the source, **not by running it**. |
| Plugins | none passed | installed packages' entry points only (not student-controlled); not verified further |

Other facts about the tool stage:

* Findings are NOT gap-scoped: `run_ruff` returns every finding in the whole file (`tools.py:133-144`) and
  `render_findings` puts them all in the prompt (`193-232`). Invariant 14 ("all static analysis is GAP-SCOPED")
  is applied by `assessment/lint_scope.py` (for V2) and `scope_check`, not by the Code Agent.
* Paths are reduced to the basename in the prompt (`tools.py:223`, `code_agent.py:172`).
* A tool that did not run says so in the prompt (`tools.py:210-216`); no tool for the file type says so
  (`tools.py:204-206`).
* The findings reach the trace: `tool_reports` in the payload (`code_agent.py:231`).

## 4. Prompt version, schema, validation, retry, cache, budget

**Prompt.** `PROMPT_VERSION = "v2"` (`prompts.py:56`), stamped into the payload (`code_agent.py:227`). Parts, in
order (`prompts.py:213-237`): system preamble (`96-107`), task (`215-216`), rubric (`62-84`), the
`llm_correctness_opinion` note (`137-139`), optional reference (`198-206`), linter block (`148-162`), student
context for tone only (`165-177`), evidence rule (`126-132`), field order (`90-94`), injection rule (`141-145`),
the submission (section 2), the output schema (`114-124`). Changelog: `agents/PROMPT_CHANGELOG.md`.

**Verdict schema** (`code_agent.py:84-125`). `Scores`: `llm_correctness_opinion` (also accepts the old key
`correctness`, `100-101`), `approach`, `readability`, `idiomatic`, each `conint(ge=0, le=4)` (`100-104`): typed
0..4, **not** restricted to {0, 2, 4}, so a 1 or a 3 is accepted (docstring `94-97`). `Verdict`: `evidence`
(dict of lists), `scores`, `misconceptions` (list of str->str dicts), `feedback_for_student`, `confidence`
(any string), `evidence_failures`.

**Validation** (`agents/validation.py`, called at `code_agent.py:216-218`):

* every quote of every criterion must appear in the submission: exact (`validation.py:121-122`), else with
  whitespace runs collapsed (`87-89`, `123-124`); a quote may be wrapped in `"`, `'` or a backtick, stripped
  first (`84`, `104-106`);
* failure kinds (`63-65`): `unmatched_quote` (a quote found nowhere) **rejects** (`77`, `241-250`);
  `missing_evidence` (a criterion with no usable quote) and `unknown_criterion` only **flag** (`223-236`);
* all four criteria are required to have a quote (`CRITERIA` at `57`, loop at `212-228`);
* it checks that a quote EXISTS, not that it supports the score (`205-207`).
* **A rejected verdict is still returned and still written**: `rejected` only sets `flagged` in the payload
  (`code_agent.py:217,230`); `grade()` does not raise. A caller must read the third return value. The
  pipeline marks the step `ok` whatever the failures and only reports their count (`pipeline.py:195-197`).

**Retry** (`system/llm.py:340-404`): `judge()` has no temperature parameter; the call is at `0.0` (`369`). One
call, validated with pydantic after stripping ONE surrounding code fence (`310-331`, `371`). On a validation
error ONE corrective call with `_CORRECTIVE_SUFFIX` appended (`334-337`, `385`); a second failure raises
`SchemaValidationError` carrying both records (`388-400`), which `grade()` re-raises after settling the budget
(`code_agent.py:201-204`). An evidence failure triggers no second call. Inside each call the gateway walks the
configured provider's model chain on a transient failure (up to 3 models, `llm.py:593-611`), then other
providers that have a key (`708-709`), each handler call under a 30 s ceiling (`523`; the walk is `684-777`).

**Cache.** `grade(use_cache=True)` is the default (`code_agent.py:135`; D-216). The cache is a module-level
`dict` in process memory (`llm.py:220`), keyed `provider:model:temperature:prompt` (`780-812`), looked up per
candidate model (`721-726`), filled on success (`765-766`). It is never saved to disk, so a second process
starts empty. The benchmarks pass `use_cache=False` (`benchmark/run_real_benchmark.py:467`).

**Budget.** Optional (`code_agent.py:134`). With one, `grade()` reserves the worst case of 2 provider calls
(`budget.py:45`) before the call, raising `BudgetExceeded` with no provider reached (`code_agent.py:197-198`,
`budget.py:171-193`), and settles by the real records afterwards (`code_agent.py:201-212`, `budget.py:195-204`).
Without one there is no cap in `grade()` itself. Cost records go to `llm.COST_LOG` (`llm.py:815-817`).

## 5. What is written

One `Memory.log_trace` call (`code_agent.py:235-239`), then one `update_mastery` per concept (`244-245`):

| Column | Value | Line |
|---|---|---|
| `student_id` | the argument | `236` |
| `actor` | `"code_agent"` | `78`, `236` |
| `kind` | `"verdict"` | `236` |
| `assignment_id` | `assignment["assignment_id"]` | `237` |
| `concept_ids` | `assignment["concepts"]` | `178`, `237` |
| `parent_trace_id` | the argument (default none) | `238` |
| `session_id` | not passed, so NULL | (`memory.py:798-803`) |
| `ts` | database default `now()` | `sql/05_memory_tables.sql:8` |

Payload (`code_agent.py:224-233`): everything in `Verdict.model_dump()` (`evidence`, `scores` with the four
keys, `misconceptions`, `feedback_for_student`, `confidence`, `evidence_failures`) plus `agent`
(`"code_agent_v2"`), `prompt_version`, `provider`, `model` (the ones that actually served the call),
`flagged`, `tool_reports`, `reference_supplied`.

* **It carries no `attempt_id`, no `commit_sha` and no submission hash.** Neither the table (`sql/05_memory_tables.sql:3-14`)
  nor the payload has them, and `grade()` is not given them (its `assignment` dict holds `assignment_id`,
  `task`, `concepts`). A verdict can be tied to a submission only through student, assignment, time and the
  quotes it contains. The file path is not stored either.
* **A second run is NOT idempotent.** `_insert_trace` always INSERTs (`memory.py:307-318`), `traces` has no
  unique constraint (`sql/05_memory_tables.sql:3-14`; UPDATE and DELETE are blocked by rules, `20-23`), and
  `grade()` does no pre-check. Two calls give two verdict traces. The cache does not help: in the same
  process it spares the provider call but a new trace is still written; in a new process there is a new call.
  The mastery update is described as idempotent (`code_agent.py:241-243`; `memory.py:913` **not re-read in
  full here**).
* The verdict never moves mastery: `verdict` is in `NON_MASTERY_KINDS` (`memory.py:176-186`) and the
  rubric-to-outcome mapping is undecided (`code_agent.py:48-62`, D-061).
* In the hourly loop **no verdict trace is written** (section 6).

## 6. The temporary checkout, the `after_grade` hook, and what it runs today

**Checkout** (`scripts/grade_collected.py`):

* `run()` loops over pending (attempt, commit) pairs (`263`). For each: `tmp = Path(tempfile.mkdtemp(prefix="vdel_grade_"))`
  (`274`, the system temp directory), `repo_dir = tmp / "repo"` (`276`).
* `checkout_commit(owner, repo, sha, dest, *, remote_url=None)` (`182`) makes `dest` (`190`), runs
  `git init -q` (`201`), `git fetch -q --depth 1 <url> <sha>` (`202`), `git checkout -q --detach FETCH_HEAD`
  (`203`) and refuses if `HEAD != sha` (`204-206`). The token goes through `GIT_CONFIG_*` environment
  variables, never the command line (`170-179`).
* Deleted in a `finally` after everything, even on an error: `_remove_tree(tmp)` (`299-300`; `_remove_tree`
  at `209-217` handles git's read-only files on Windows).

**The hook today.** Signature of the host function (`grade_collected.py:237-241`):

```python
def run(*, student=None, assignment=None, dry_run=False, latest_only=False, repo_for,
        checkout=checkout_commit, grade=grade_attempt, conn=None, after_grade=None) -> dict
```

Call site (`grade_collected.py:290-295`), inside the `try`, after `grade(...)` (`278`) and `_record_lint(...)`
(`285`), before the `finally` that deletes the directory, only when `status == "ok"`:

```python
if after_grade is not None and status == "ok":
    try:
        after_grade(p, repo_dir, result)          # p: Pending, repo_dir: Path, result: the grade result
    except Exception as exc:
        summary["agent_errors"].append((label, f"{type(exc).__name__}: {exc}")); print(...)
```

The hook is `AgentsHook.bind(conn)` (`scripts/run_cycle.py:158-168`), passed by `_stage_grade` only when
`--with-llm` is on and not `--dry-run` (`run_cycle.py:230-234`). It runs `_run` (`170-192`) inside a SAVEPOINT
(`161-167`):

1. returns if the commit is the template push (`172-174`, `post_feedback.py:193`);
2. returns if `result.tests_total` is 0 (`175-177`);
3. calls `run_agents_for_commit(student_id, attempt_id, sha, llm=, budget=, cur=, memory=)` **with no
   `assignment` and no `code_path`** (`180-182`);
4. inside the pipeline that makes the Code Agent step `skipped` with no call: `if not code_path or not
   assignment or not (assignment.get("task") or "").strip()` (`pipeline.py:185-188`);
5. the Feedback Agent runs (`pipeline.py:245`) and its LLM answer, if any, is stored as one
   `coach`/`intervention` trace (`run_cycle.py:184-187`, `pipeline.py:108-132`).

**The Code Agent is skipped by decision** (Anas, `docs/DECISIONS.md:4221`, D-099 "CODE AGENT"): the Feedback
Agent does not read its output and its verdict is not to be persisted, so running it would only cost calls.

**What it would take to turn it back on, and then to store it:**

1. In `AgentsHook._run` (`run_cycle.py:178-182`) load `assignment, file_path =
   agents_pipeline.load_assignment_inputs(cur, p.assignment_id)` (`pipeline.py:160-175`) and pass
   `assignment=assignment, code_path=repo_dir / file_path`. That alone makes `_run_code_agent` call
   `grade()` (`pipeline.py:190-194`).
2. It would still persist nothing: `_run_code_agent` hands `grade()` a `DryRunMemory` (`pipeline.py:191`) and
   `run_agents_for_commit(persist=True)` raises `IntegrationPending` (`pipeline.py:226-230`, a test pins it).
   Storing needs a deliberate step (like `persist_feedback`) and a decision on the payload (no `attempt_id`,
   `commit_sha` or hash today, section 5) and on duplicates (no dedupe today).
3. Before spending, decide the open items of sections 2, 3, 7, 8 (delimiter, config isolation, which task text,
   which criteria). None is a one-line change.

## 7. Which file and which lines are judged

* **Which file.** One assignment = one file: `assignments.file_path`, seeded as `<project>/<stage>.py`, for
  example `weather_etl/transform.py` (`scripts/seed_data.py:138,157`; stages `PIPELINE_STAGES = extract,
  transform, load, quality`, `seed_data.py:33`). `load_assignment_inputs` reads it (`pipeline.py:165-170`). The
  sketch in `docs/agents.md:537` joins it as `repo_dir / file_path`; the hook as committed does not build any
  path (section 6); `scripts/demo.py:264` spells it `REPO_DIR / "weather_etl" / "transform.py"`.
* **Which assignment a commit belongs to.** The collector attributes each commit by the files it touched
  against each assignment's `file_path` (D-043, `collectors/collect_github.py:19-28,166-186`); a commit that
  matches none or several gets `assignment_id IS NULL` and is not graded (`grade_collected.py:24-26`). Pending
  work is selected per (student, assignment, attempt) (`grade_collected.py:117-135`).
* **Whole file or gap lines?** The WHOLE file: `code = path.read_text(...)` (`code_agent.py:167`) is what goes
  into the prompt (`prompts.py:233`). Gap line ranges are not used by `code_agent.py`, `prompts.py`, `tools.py`
  or `validation.py` (a grep for `gap` in those four finds only an unrelated word at `validation.py:40`). The
  gaps reach the prompt in one way: their `instruction` text, as the task (section 8). Ranges
  (`gaps.line_start`/`line_end`, `seed_data.py:162-181`) are used by `scope_check` and `lint_scope`.
* **Several files.** `grade()` takes one `code_path` (`code_agent.py:128`) and the pipeline one
  (`pipeline.py:220`). A repo with four assignment files is judged as four separate (assignment, commit) items,
  each its own file and its own `task`; nothing combines files. A single commit that touches two assignment
  files is not graded at all (above). Cross-file context (for example `load.py` against `extract.py`) is never
  given to the judge.

## 8. Task text and criteria for `weather_etl`

* **Task text.** There is no `assignments.task` column (`code_agent.py:40-46`). `load_assignment_inputs` builds
  it as the `gaps.instruction` of the assignment joined with a single space and ordered by `gap_id`
  (`pipeline.py:171-174`; the same query is in `scripts/demo.py:257-261`). The instructions come from the
  master's `# @instruct:` lines, for example `curriculum/master/weather_etl/weather_etl/transform.py:7,15,23-24`,
  parsed by `assessment/gap_parser.py` and stored by `seed_data.py:162-181`. For `weather_etl_transform` that is
  "Return only records where record.get("temp") is not None. Apply the standard C-to-F formula. Try to parse
  raw_ts as ISO format..." (the three gaps).
* **Criteria.** Fixed, four, for every assignment: `RUBRIC_TABLE` (`prompts.py:62-84`). The fourth is
  "Idiomatic Spark/SQL" (`81-84`), whose anchors speak of DataFrames and `collect`. `weather_etl` is plain
  Python, so that criterion has no meaning for it, and the code offers no way to drop or rename it:
  `build_grading_prompt` accepts `rubric_table` (`prompts.py:183`) but `grade()` never passes it
  (`code_agent.py:185-191`) and never reads `assignment["rubric"]`. The validator still requires a quote for
  `idiomatic` (`validation.py:212-228`), or it flags `missing_evidence`. `assignments.concepts` (derived from
  the gaps, `seed_data.py:140`) go to the prompt only as the tone-only mastery slice (`code_agent.py:178-179`,
  `prompts.py:165-177`) and into the trace's `concept_ids`.
* **What is missing for `weather_etl`:**
  1. an assignment-level statement of the exercise (inputs, outputs, what a good solution does): the task is
     only the TODO lines of the gaps, in alphabetical `gap_id` order, not file order (for `extract.py`:
     `g_ext_parse` comes before `g_ext_retry`, while the file has `g_ext_retry` first,
     `curriculum/master/weather_etl/weather_etl/extract.py:9,28`);
  2. a Python rubric or a way to mark a criterion not applicable;
  3. a reference solution in the loop: the pipeline's `reference` defaults to `None` (`pipeline.py:222`); the
     master exists (`curriculum/master/weather_etl/weather_etl/transform.py`) and `demo.py:265,269-270` uses it;
  4. ground truth for `weather_etl`: `benchmark/ground_truth.json` holds only the five PySpark files; the four
     `weather_etl` fixtures (`tests/fixtures/agents/code/`) have labels only in the local, ignored
     `benchmark/results/labeling_sheet_llm.csv`;
  5. the hidden tests' result is not given to the judge, by design (the correctness opinion is not a result,
     `prompts.py:137-139`).

## 9. From a GitHub commit to a verdict trace, and everything not wired

```
GitHub push
  |  collectors/collect_github.py            raw_commits (assignment_id by file, D-043)
  v
scripts/run_cycle -> _stage_grade (run_cycle.py:230) -> grade_collected.run (grade_collected.py:237)
  |  find_pending (117)                      one item per (attempt, commit) with no test_results yet
  |  mkdtemp + checkout_commit (274-277)     tmp/repo = exactly that commit
  |  grade_attempt (278)                     hidden tests in a subprocess/container -> test_results
  |  _record_lint (285)                      gap-scoped lint counts for V2 (own temp copy)
  v
after_grade(p, repo_dir, result)  (290-295)  only if --with-llm, status ok       <- hook exists, ON only by flag
  |  AgentsHook._run (run_cycle.py:170)      skip template push / no test rows
  |  run_agents_for_commit (pipeline.py:218) NO assignment, NO code_path passed
  |     +-- Code Agent step ........ SKIPPED (pipeline.py:185-188)  ---X---> grade() is NOT called
  |     |        (would be: grade(DryRunMemory ...) -> verdict in memory only, nothing stored)
  |     +-- Feedback Agent .......... judge -> validate -> FeedbackResult
  |  persist_feedback (pipeline.py:108)      one coach/intervention trace per (attempt, commit)
  v
_remove_tree(tmp)  (299-300)                 the student's file is gone

A Code Agent VERDICT trace (actor code_agent, kind verdict) is written only by:
  scripts/demo.py:267  (Beat 6, by hand, real Memory, file from renders/anas_attempt1)
```

**Not wired (each verified above unless marked):**

1. The Code Agent in the hourly loop (skipped by decision, D-099).
2. Persisting a Code Agent verdict from the pipeline (`DryRunMemory`, `persist=True` raises).
3. `attempt_id`, `commit_sha` and a submission hash in the verdict trace.
4. Idempotence of the verdict trace (a second run writes a second row).
5. Neutralising the submission delimiter in the prompt.
6. Isolating the linters from config in the student's checkout for the Code Agent path (done only for V2 in
   `lint_scope`); the `.sql` path can execute student Python through sqlfluff's `library_path` (by source).
7. Gap-scoping the linter findings the judge sees.
8. A per-assignment rubric, or a way to mark a criterion not applicable (`weather_etl` is judged against a
   Spark/SQL rubric).
9. An assignment-level task text; task order follows `gap_id`, not the file.
10. A reference solution supplied by the pipeline.
11. Multi-file context, and any handling of a commit touching several assignment files.
12. A verdict-to-mastery mapping (D-061 open); `verdict` is a non-mastery kind.
13. A guard on file size, encoding errors and symbolic links in `code_agent.py`.
14. Acting on `evidence_failures`: a rejected verdict is returned and would be stored like any other.
15. Pairwise or position-swapped judging (`CLAUDE.md` section 8 recommends it; `grade()` makes one pointwise
    call).
16. Ground truth and a measured agreement for `weather_etl` (the first real run is on the five PySpark files).
17. The Reviewer and the orchestrator (M6, out of scope by design).

**Not verified:** ruff's config discovery and any code loading in ruff (probe blocked); whether `git checkout`
makes symlinks here; how a real model handles an unneutralised end delimiter or a very large file (no call);
`update_mastery`'s exact idempotence (`memory.py:913` not re-read); the live database's `assignments`/`gaps` rows
(not queried, everything above is from the seed code and the master files).
