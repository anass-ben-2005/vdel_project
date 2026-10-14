# AUTHORING.md: writing a master project

For the course author. A **master project** is a complete, working solution with some blocks marked as
*gaps*. The system hides some of the gaps for each student (a *completion problem*, D-035), grades what the
student writes with **hidden tests**, and updates the student's mastery of the **concepts** each gap is
tagged with.

Contents: 1 The layout · 2 The gap markers · 3 Concepts · 4 The hidden tests · 5 The visible tests ·
6 Resources · 7 Public check descriptions (`checks.yaml`) · 8 What the judge is told (`judging.yaml`) ·
9 Registering a project · 10 Change an existing assignment · 11 The validator · 12 A checklist

Worked examples to copy from: `curriculum/master/weather_etl/` (four stages) and
`curriculum/master/sales_analyzer/`.

## 1. The layout

```
curriculum/master/<project>/
├── requirements.txt                 what the student's CI installs (and the grading container, see below)
├── <project>/                       the importable package: ONE FILE PER STAGE
│   ├── __init__.py
│   ├── extract.py                   a stage = an assignment = a file the student edits
│   ├── transform.py
│   └── ...
└── tests/
    ├── hidden/
    │   ├── conftest.py              registers the @pytest.mark.gap marker (copy from weather_etl)
    │   └── test_<stage>.py          one hidden test file per stage
    └── visible/
        └── test_<stage>.py          standalone smoke tests the student can run (section 5)
```

- **One stage = one assignment = one file.** The assignment id is `<project>_<stage>` and its `file_path` is
  `<project>/<stage>.py`. That string is simultaneously a path under the master, a path in the rendered
  student repository, and the filename GitHub reports on a commit, which is how the collector attributes a
  commit to an assignment (D-043). Do not rename it casually.
- Stage order is fixed by the code, not discovered: `seed_curriculum(..., stages=(...))` in
  `scripts/seed_data.py` (default `extract, transform, load, quality`; `sales_analyzer` passes
  `ingest, clean, aggregate, load`). `seq` follows that tuple.
- `master_version` of a project is a hash of the stage files' git blob hashes, so it changes exactly when
  the code does (section 10).

## 2. The gap markers

A gap is a block between `# @gap:` and `# @endgap`; the lines in between are the **solution**, which the
student sees blanked.

```python
def clean_readings(records: list[dict]) -> list[dict]:
    """Drop readings missing a critical field (temp)."""
    # @gap:id=g_tf_clean concepts=[py.data_structures] difficulty=0.3
    # @instruct: Return only records where record.get("temp") is not None.
    return [r for r in records if r.get("temp") is not None]
    # @endgap
```

| Part | Rule |
|---|---|
| `# @gap:id=<gap_id> concepts=[<concept>, ...] difficulty=<0..1>` | `id` and `concepts=[...]` are required. `difficulty` is a cold-start prior (default 0.5); the cohort's pass rate replaces it once there are observations. |
| `# @instruct: <text>` | Required, and it becomes the TODO comment the student sees. It may continue on following plain `#` lines, aligned underneath. This text is also all the Code Agent is told the task is (section 8). |
| `# @endgap` | Closes the gap. Gaps cannot nest. The id must be unique **across the whole curriculum**: `gaps.gap_id` is the table's primary key, the parser only catches a duplicate inside one file, and the seeder's `ON CONFLICT (gap_id) DO UPDATE` would silently re-point a gap of another stage to the new one. |
| The body | Must not be empty. Its line range is what static analysis is scoped to (invariant 14): only findings inside it are ever attributed to the student. |

The parser (`assessment/gap_parser.py`, `parse_master`) fails loudly with the line number: nested gap,
duplicate id, missing `id=` or `concepts=`, a `difficulty` that is not a number, an unclosed or unmatched
marker, a gap with no `@instruct`, an empty body, and a concept id that is not in the taxonomy.

Design advice that follows from how variants are chosen:

- **Tag a gap with the concept it actually exercises.** A wrong tag silently updates the wrong mastery.
- **A concept group is hidden whole** (D-042): `select_variant` hides *all* the gaps of a concept it picks, as
  one unit. With only two gaps in a stage, attempt 2 can be the same bundle as attempt 1 (a finding recorded
  for `weather_etl_extract`, D-072). Give each stage enough gaps over enough concepts to vary.
- Keep each gap small and testable by itself: a test is attributed to a gap, and a gap's result is one
  mastery observation (the first attempted pushed commit per attempt and gap, D-079).

## 3. Concepts

Every concept id used in a marker must exist in `config/concepts.yaml` (`config/concepts.py` loads and
validates it):

```yaml
  - id: py.errors_debugging
    name: ...
    typical_evidence: ...
    difficulty: 0.4        # a cold-start seed only
    prerequisites: []
```

**Concept ids are schema.** They appear in columns, prompts and error mappings; renaming one breaks history.
Add new ones, do not rename. The taxonomy is meant to stay under about 30 so each concept collects enough
observations to say something (a mastery of 0.9 from n=2 is a rumour). The file says it holds 19 of the
planned ~25, taken from the source documents rather than invented; extend it from the curriculum.

## 4. The hidden tests

`tests/hidden/test_<stage>.py` is what grades the stage. Rules, from `assessment/test_runner.py` and the
existing files:

- **Mark every test with its gap**: `@pytest.mark.gap("g_tf_clean")` (D-046). The conftest turns that into a
  JUnit property so a failure is localised to a concept without parsing test names. A test with no marker is
  not attributed to any gap.
- **Every gap needs at least one test, and every test should name a gap.** A gap no test covers can never be
  shown to be solved; the validator checks this (section 11).
- Import the student's module the way the student's repo does: `from weather_etl.transform import ...`.
- Only the one file for the assignment being graded is copied next to the student's code, at
  `tests/hidden/<name>.py`, with the trusted conftest. A hidden file that cannot be imported (a collection
  error) is recorded separately and is not evidence of the student's skill (D-066, D-069).
- **Hidden means hidden.** The publisher refuses to push anything with a path component named `hidden`;
  the feedback shows a test's name and exception type only, never its assertion text or source (D-077); the
  feedback agent's output is checked against every hidden source line. Do not put an answer in a test name:
  names appear in the student's feedback.
- Tests run offline in a container with **no network** and a read-only root. Do not call a real service; fake
  it in the test.
- The grading container installs only what `docker/grader-requirements.txt` lists. If a stage needs a new
  package, add it there and rebuild the image (`docs/OPERATIONS.md` section 11), and to the project's
  `requirements.txt` for the student's CI.
- A stage freezes when its hidden tests reach 100% on a pushed commit (D-045). Make them deterministic: the
  runner pins the hash seed, but no test should depend on time, ordering of a set, or randomness.

## 5. The visible tests

`tests/visible/test_<stage>.py` is what the student can run locally and what their generated CI runs. It must
**run standalone** (nothing injected), import only what exists in a single-stage repository (a repo for
attempt 2 ships one stage's file, D-097), and prove the code is wired without giving away the hidden cases.
They are a smoke net: the hidden suite is the grader. The renderer also writes `ASSIGNMENT.md`, which lists
every hidden gap with its file, line and instruction.

## 6. Resources

The feedback may point a student at reading for their weakest concept, but only from a **closed list** you
curate; the model never invents a link (D-038). Each row of `config/resources.csv` (template:
`docs/resources_template.csv`):

```
resource_id,concept_ids,kind,title,locator,url,level
py-tut-dictionaries,py.data_structures,doc_page,5. Data Structures (Python docs),5.5 Dictionaries,https://docs.python.org/3/tutorial/datastructures.html#tut-dictionaries,beginner
```

`concept_ids` separates several ids with `|`; `kind` is one of `book_section`, `doc_page`, `kaggle`, `video`;
`level` is `beginner`, `intermediate` or `advanced`. Verify each URL once, by hand: the loader checks syntax
only. `python -m scripts.load_resources config/resources.csv` is a dry run that lists every error with its row
number; it writes only with `--apply --dsn ...`. Give every concept a project teaches at least one resource.

## 7. Public check descriptions (`config/checks.yaml`)

A student sees a failing check by its name and the exception type only (D-077). `config/checks.yaml` gives
every hidden test a **public description**: one or two sentences saying what behaviour the test checks, so
feedback can say what must hold instead of only naming a test.

```yaml
assignments:
  weather_etl_extract:
    - test: tests/hidden/test_extract.py::test_fetch_weather_raises_after_max_attempts
      gap: g_ext_retry
      description: >-
        When every request fails with a connection error, fetch_weather stops after the allowed
        number of attempts and lets the connection error reach the caller.
      status: draft
```

- `test` is the stored name, `tests/hidden/<file>.py::<test>` (`Class::test` for a class); `gap` must be the
  gap the test is marked with.
- The description is **prose about behaviour**: the situation (the inputs) and what must be observed. No test
  code, no `assert`, no `==`, no code block, no more than 400 characters (`config/checks.py` refuses them), and
  no literal expected value unless it is trivial. Say *what* must happen, not *how* to write it: it will be
  shown to students.
- **`status: draft` entries are never used.** `config/checks.py` ignores them: `description_for` and `entries`
  return a description only when the status is `reviewed`, so a draft can reach neither a prompt nor a student.
  The fifteen entries for the four `weather_etl` assignments were drafted from the hidden
  tests; **the course author must read each against its test and change `draft` to `reviewed`** (or reword it).
- Every hidden test needs exactly one entry; `scripts/validate_master.py` reports a missing one, an entry for
  a test that does not exist, and a gap that disagrees with the test's marker.

## 8. What the judge is told (`config/judging.yaml`)

The optional Code Agent judges working code against a rubric of four criteria (correctness, approach,
readability, idiomatic). `config/judging.yaml` says, per assignment, which criteria apply (`weather_etl` drops
"idiomatic" because it is plain Python, not Spark or SQL), a `note` saying why, and a `statement`: one to three
sentences describing the exercise, put in front of the gap instructions. A statement is `null`, a plain string
(taken as reviewed), or `{text: "...", status: draft | reviewed}`; **only a reviewed one is used**
(`config/judging.py` ignores a draft). The four `weather_etl` statements are drafts written
from the master files (D-107): read each and mark it `reviewed`. `sales_analyzer_*` has no entry, so it is
judged on all four criteria with no statement. The task text is otherwise the gap instructions in **file
order**.

## 9. Registering a project

1. Put the tree under `curriculum/master/<project>/`.
2. Add the project to `main()` in `scripts/seed_data.py` with its stage tuple (a code change, today: the
   project list is not discovered). Then `python -m scripts.seed_data` writes `projects`, `assignments` and
   `gaps` idempotently and prints the `master_version`.
3. If the stage names differ, check `scripts/deliver_next_attempt.py` (`stage_name`) and the repo naming:
   `vdel-<project>-gapfill-<student>-<stage>-attempt<n>` for attempts after the first.
4. Add the project's assignments to a student's roster only when delivering (`docs/OPERATIONS.md` sections 8
   and 15).
5. Run the validator (section 11) and the suite.

## 10. Change an existing assignment

What happens depends on WHAT you change. Read the row for your change before you touch a file that students already
use.

| You change | Takes effect | What it does to work in progress |
|---|---|---|
| a stage file's text (code, a marker, a gap's lines) | after `seed_data` re-seeds it | **new `master_version`**; see "Editing a master" below |
| a hidden test | at once, at the next grading | grading of unfinished attempts changes; **no version changes** |
| a visible test | for repositories published afterwards | nothing for repositories already published |
| a check description (`checks.yaml`) or a task statement (`judging.yaml`) | at the next cycle | nothing stored changes |
| the concepts or the resources | see "Concepts and resources" below | nothing stored changes |

### Editing a master (a stage file) that students already use

- **`master_version` changes.** It is a hash over the stage files only, each file's content keyed by its name
  (`scripts/seed_data.py:36-54`, `_tree_version`). Any edit to a stage file, a marker included, gives the project a new
  version. Hidden tests, visible tests and the config are **not** in the hash.
- **Re-seeding rewrites the gaps in place.** `seed_data` upserts every gap by `gap_id` with its new line range and the new
  `master_version` (`scripts/seed_data.py:162-181`); it never deletes a gap, so a gap you removed from the file stays in the
  `gaps` table. The line ranges of a gap are valid for **one** master version only (invariant 15), and after the upsert only
  the new one is stored.
- **Attempts already issued stay pinned to the old version**: an attempt's variant row keeps the `master_version` it
  was rendered from. The student's repository files do not change, so a student keeps working on the file they
  were given. What the system can no longer do for that attempt, because the variant's version differs from the project's:
  - the out-of-scope measurement (V9) is skipped and `out_of_scope_lines` is left unset
    (`assessment/test_runner.py:917-929`);
  - the gap-scoped lint measurement (V2 cleanliness) is skipped (`assessment/lint_scope.py:98-100`);
  - the agents that read the student's own gap lines (Feedback Agent v2, Code Agent) cannot rebuild the released file and
    skip it (`agents/scope.py:134-136`).

  Grading itself does not check the version: hidden-test results, the freeze and the mastery observations depend on the
  hidden tests and the gap ids (and, for mastery, the `difficulty` currently stored on the gap).
- **A new attempt after the edit** gets a new variant, because the variant id hashes the master version
  (`assessment/gap_generator.py:81-92`). Students who start after the change work on the new text.
- **Hidden tests change without a version bump.** An edit to `tests/hidden/test_<stage>.py` is picked up by the very next
  grading run, for every unfinished attempt, and nothing records that the tests changed. A commit already graded is not
  graded again (the cycle skips commits that already have results), so only new commits are judged by the new test.
  Change a hidden test only when the old one was wrong, and say so in a decision entry.

**When to deliver a new attempt, or a new stage, instead of editing.** Prefer a new stage or a new project to an edit, and
edit a stage file at all only before anyone has been issued it. If a mistake is found in a stage that students are
already working on: fix it in the master, re-seed, and let students who have not started use the new version; for a
student in progress, either leave them on the old text (they lose only the measurements above) or deliver a fresh attempt
once the current one is frozen (`python -m scripts.deliver_next_attempt`, `docs/OPERATIONS.md` section 20). `--force`
starts the next attempt although the current one is not frozen and leaves the old one open (D-072); avoid it.

**Commands to run, in this order**

```bash
python -m scripts.validate_master <project>     # read-only: markers, gap ids across the curriculum, test coverage
VDEL_REQUIRE_DB=1 python -m pytest -q           # on its own database; the master's own tests must still pass
python -m scripts.baseline --full > before.txt  # keep the fingerprint of the real database
# back up the database first (docs/OPERATIONS.md section 9), then:
python -m scripts.seed_data                     # re-seeds projects, assignments and gaps; idempotent
python -m scripts.baseline --full > after.txt && diff before.txt after.txt
python -m scripts.run_cycle --dry-run --student <id>
```

The only expected differences in the baseline are the project's `master_version` line and the gap rows. A hidden-test or
visible-test change needs no re-seed. Record the change in `docs/DECISIONS.md`.

### Changing a check description or a task statement

Edit the entry in `config/checks.yaml` (one per hidden test) or the `statement` in `config/judging.yaml`. A new or edited
text starts as `status: draft`: **only `reviewed` entries are ever used**, and a draft reaches neither a prompt nor a
student (`config/checks.py`, D-107). Read it against its test, then set `reviewed`. Nothing is re-seeded and no stored
verdict changes: the files are read when a cycle starts (`config/checks.py` `_load` caches per process), so the
next hourly run uses the new text. Check with `python -m scripts.validate_master <project>`; add `--require-reviewed` to
turn remaining drafts into errors before a pilot.

### Changing concepts or resources

- **Concepts.** Ids are schema: add a concept to `config/concepts.yaml`, never rename or reuse one, because they are
  stored in gaps, traces and the profile. A gap whose marker names a concept needs that concept to exist or `parse_master` fails.
  Changing the concepts of an existing gap means editing the marker in the stage file, which is an edit of the master
  (above). `assignments.concepts` is derived from the gaps by `seed_data`, never by hand.
- **Resources.** Edit `config/resources.csv`, check it with `python -m scripts.load_resources config/resources.csv` (a
  dry run that lists every error with its row), then write it to the database with `--apply --dsn ... --allow-real-db`
  (`scripts/load_resources.py --help`); the agents read the `resources` table, not the file (`agents/resources.py:59`).
  Every concept used by a gap needs at least two resources at more than one level (`tests/test_resources_seed.py`).

## 11. The validator

```bash
python -m scripts.validate_master weather_etl            # one project, or no argument for all
python -m scripts.validate_master --require-reviewed     # drafts become errors: run this before a pilot
```

Read-only (no database, no network). Per stage it reports `ERROR`, `WARN` and `INFO` lines for:

1. marker syntax (`parse_master`: nesting, missing `id=` or `concepts=`, an unclosed gap, no `@instruct`, an
   empty body), one message per file;
2. gap ids unique **across the whole curriculum** (see section 2);
3. every concept in the taxonomy;
4. every gap covered by at least one hidden test with `@pytest.mark.gap("<id>")`;
5. hidden tests with no gap marker (a warning) or a marker naming a gap the stage does not define (an error);
6. every hidden test has a `checks.yaml` entry whose gap agrees, and no entry names a missing test;
7. an entry for the assignment in `judging.yaml`;
8. at least one resource in `config/resources.csv` for every concept the project uses.

`draft` check descriptions and judging statements are notes (`INFO`) unless `--require-reviewed` is given.
The exit code is 1 when any `ERROR` remains. The files are read with `ast`: nothing is imported or run.
`parse_master` also runs at seeding time, but only the validator catches a duplicate id across files, a gap
no test covers, or a hidden test with no public description.

## 12. A checklist

- [ ] The solution is complete and every gap body is non-empty; the whole master passes its own hidden tests.
- [ ] Every gap has a unique id, a real concept, an honest difficulty and a clear `@instruct`.
- [ ] Every gap is covered by at least one hidden test marked with its id; no test is unmarked.
- [ ] Every hidden test has a public description in `config/checks.yaml`, reviewed.
- [ ] No test name, instruction or description gives the answer away.
- [ ] The visible tests run standalone.
- [ ] Every concept the project uses has at least one resource.
- [ ] `config/judging.yaml` has an entry and a reviewed statement for each stage.
- [ ] New packages are in the project's `requirements.txt` and `docker/grader-requirements.txt`.
- [ ] `python -m scripts.validate_master <project>` reports no error, and `--require-reviewed` too before a pilot.
- [ ] `python -m scripts.seed_data` runs clean and the suite is green.
