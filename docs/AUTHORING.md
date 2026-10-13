# AUTHORING.md: writing a master project

For the course author. A **master project** is a complete, working solution with some blocks marked as
*gaps*. The system hides some of the gaps for each student (a *completion problem*, D-035), grades what the
student writes with **hidden tests**, and updates the student's mastery of the **concepts** each gap is
tagged with.

Contents: 1 The layout · 2 The gap markers · 3 Concepts · 4 The hidden tests · 5 The visible tests ·
6 Resources · 7 Public check descriptions (`checks.yaml`) · 8 What the judge is told (`judging.yaml`) ·
9 Registering a project · 10 Changing a master afterwards · 11 The validator · 12 A checklist

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

*Added in stage 3 of the finalisation branch; this section is completed there.* The idea: the student sees a
test by its name, so each hidden test gets a **public description** of the behaviour it checks, in words, with
no test code and no expected literal. An entry is only used once its `status` is reviewed; a `draft` entry
never reaches a prompt or a student.

## 8. What the judge is told (`config/judging.yaml`)

The optional Code Agent judges working code against a rubric of four criteria (correctness, approach,
readability, idiomatic). `config/judging.yaml` says, per assignment, which criteria apply (`weather_etl` drops
"idiomatic" because it is plain Python, not Spark or SQL), a `note` saying why, and a `statement`: one to three
sentences describing the exercise, put in front of the gap instructions. Today the statements are `null` for
`weather_etl` (the course author's to write, D-104 CONFIRM 2) and `sales_analyzer_*` has no entry, so it is
judged on all four. The task text is otherwise the gap instructions in **file order**.

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

## 10. Changing a master afterwards

`master_version` is part of every gap, variant and attempt (invariant 15), and gap **line numbers are valid for
one master version only**. Editing a stage file changes its hash, so: the gaps are re-seeded against the new
version, but attempts already issued stay pinned to the old one, and their line ranges no longer match the new
file. Treat a released master as **frozen content**: the repository's ruff configuration even excludes
`curriculum/` so that a restyle cannot silently invalidate the ranges. To fix a mistake, prefer a new stage or
a new project over an edit; if you must edit, do it before anyone is issued the stage, and re-run the
validator.

## 11. The validator

*Added in stage 3 of the finalisation branch (`scripts/validate_master.py`); this section is completed there.*
Until then `parse_master` (section 2) is the check that runs at seeding time.

## 12. A checklist

- [ ] The solution is complete and every gap body is non-empty; the whole master passes its own hidden tests.
- [ ] Every gap has a unique id, a real concept, an honest difficulty and a clear `@instruct`.
- [ ] Every gap is covered by at least one hidden test marked with its id; no test is unmarked.
- [ ] No test name, instruction or description gives the answer away.
- [ ] The visible tests run standalone.
- [ ] Every concept the project uses has at least one resource.
- [ ] `config/judging.yaml` has an entry and a reviewed statement for each stage.
- [ ] New packages are in the project's `requirements.txt` and `docker/grader-requirements.txt`.
- [ ] `python -m scripts.seed_data` runs clean and the suite is green.
