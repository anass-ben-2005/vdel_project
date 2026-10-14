# RELEASE_AND_UPGRADE.md: versions, upgrades and how to check one

How a change reaches a running installation without damaging its data. Facts are cited; gaps say `TODO(verify)`.

## 1. What "v1.0" means

Version 1.0 is **the tip of `main` at hand-over**: the behaviour recorded in `docs/DECISIONS.md` up to D-112 and in
`docs/DECISIONS_AGENTS.md`, with the documents of `README.md`. No commit is tagged in this repository: the history that
is delivered is rebuilt, so a tag here would name a commit the recipient does not have. `pyproject.toml` still says
version `0.1.0`; it is not a release marker. `CHANGELOG.md` has a "v1.0" entry grouped by theme. A later release should
be a tag on a validated commit (see [VALIDATION.md](VALIDATION.md)), and `CHANGELOG.md` should then follow the tags.

## 2. The database schema

- `sql/01_reference_tables.sql` to `sql/10_attempt_started_at.sql` are applied in order by `python -m scripts.init_db`,
  which is idempotent: running it again is a no-op (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`).
- Later files are additive. Examples: `08_lint_columns.sql` (D-088) and `10_attempt_started_at.sql` (D-090) say in
  their headers that they are applied by hand with `python -m scripts.init_db`.
- `CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists with different columns, so a changed column
  needs its own additive `ALTER` file, not an edit of an old file (the comment in `sql/05_memory_tables.sql`, D-008).
- `sql/pilot/vdel_cycle_role.sql` is **never applied by `init_db`**; it is a manual step (`docs/PILOT.md` section 2).
- To upgrade an existing database: take a backup (`docs/OPERATIONS.md` section 9), read the headers of the new files,
  run `python -m scripts.init_db`, and run the baseline before and after (section 5).

## 3. Formula versions

`FORMULA_VER` in `features/compute_features.py` (currently `v8`) names the rules that produced a `learner_features`
row. Stored rows keep their own `formula_ver` and are never rewritten; a new version changes what the next computation
writes (`CLAUDE.md` section 6, KNOWN_ISSUES item 6; the history is in D-069, D-079, D-084, D-088, D-098). When a rule
changes, bump the version, write the decision, and say in it which earlier rows stay as they were.
Mastery is rebuilt from `traces`, not from the feature rows (`docs/ARCHITECTURE.md` section 1).

## 4. Dependencies and images

- `requirements.txt` is pinned; `requirements-airflow.txt` is a separate environment (Python 3.11). Whether every pin
  installs on Python 3.11, the version CI uses, is **not verified** (`docs/INSTALL.md`).
- On a machine that already has `chardet` 7.x run `pip install "chardet<6"` (KNOWN_ISSUES item 24).
- The grading image is built from `docker/grader.Dockerfile` with `docker/grader-requirements.txt` (one `TODO(verify)`
  about its pins). A project that adds a package must add it to both requirement files (`docs/AUTHORING.md` section 12).
- A prompt change bumps `PROMPT_VERSION` and adds an entry to `agents/PROMPT_CHANGELOG.md` (`CONTRIBUTING.md`).

## 5. Checking an upgrade

```bash
python -m scripts.baseline --full > before.txt     # read-only fingerprint of the real database
# ... upgrade ...
python -m scripts.baseline --full > after.txt && diff before.txt after.txt
python -m scripts.doctor --no-network              # read-only readiness checks
VDEL_REQUIRE_DB=1 python -m pytest -q              # on its own throwaway database
ruff check .
```

An upgrade is verified when the baseline differs only by rows the upgrade is meant to add. With every new flag off, the two baseline outputs must be identical; if they cannot be, the change touches real
data and needs a decision entry that says so (`CONTRIBUTING.md`, "The loop for every change").
Re-register the scheduled task only after reading `docs/OPERATIONS.md` section 14: re-registering replaces the
whole command.
