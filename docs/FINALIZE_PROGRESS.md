# FINALIZE_PROGRESS.md -- resume file for the `v1-finalize` branch

Tracked on purpose: a new session starts here. Rules of the brief that never change: work on the local
branch `v1-finalize` (created from `main` at e4afb91), one local commit per stage, no Co-Authored-By line,
NEVER push or merge or switch the user's other branches; NO live LLM call (fake LLM in every test), no
GitHub write, real database read-only, do not read `.env`, never edit the real `config/roster.yaml`,
never register / enable / disable / start the scheduled task, never run `deliver_next_attempt --apply`
or `--resume`. Before each stage `python -m scripts.baseline --full`; after it, baseline identical (every
new flag OFF), `VDEL_REQUIRE_DB=1 python -m pytest -q`, `ruff check .`. A blocked command is logged and
skipped, not redone another way.

The user's own uncommitted edits (`benchmark/RECOMMENDATION.md`, and `.gitignore`'s `*.bak` line) are
never staged by a stage that does not own them.

| Stage | Status | Commit | Decisions |
|---|---|---|---|
| 1 Hygiene | DONE (1410 passed, 3 skipped, 1 xfailed; baseline identical; ruff clean) | see `git log` | D-105 |
| 2 Handoff documentation | DONE (docs only; 1410 passed, 3 skipped, 1 xfailed; baseline identical; ruff clean) | see `git log` | D-106 |
| 3 Authoring scaffolding | not started | - | |
| 4 Feedback Agent v2 (`--agents-v2`) | not started | - | |
| 5 Code Agent v2 (`--agents-v2`) | not started | - | |
| 6 Pilot preparation | not started | - | |

## Baseline reference

Taken before stage 1 (`python -m scripts.baseline --full`, 42 lines): attempts 15 rows hash
`db1f8fd8ddf184dc7020a535bb64c9be`; traces 116, highest trace_id 71852; raw_commits 60; raw_workflow_runs 61.

## Open CONFIRM items

(see the decision entry of each stage; this list is the index)

- D-105 1: which docs stay local (STATUS, FRAMEWORK_STATUS, HANDOFF, reading/, overnight reports, design/);
  `git rm --cached docs/STATUS.md` is the user's to run.
- D-105 2: `pip install "chardet<6"` is the user's to run; the suite under chardet 5.2 was not run.
- D-105 3: `.env.example` has optional variables commented out; `LLM_MODEL` removed (unused).
- D-105 5, 6: `roster_apply` exit code 2 without `--yes`; the default hint of `publish_repo`'s CLI changed.
- D-106 c: prompt names. Feedback Agent v2 = `fb2`, Code Agent v2 = `v4` (the brief says "v4 / v3"); CONFIRM before stage 4.
- D-105 8: "formula v9" and "3 unattributed commits" (the database has 4) need the user's answer.

## Blocked / skipped commands

- Stage 1 follow-up: creating a Python 3.11 venv and installing `requirements.txt` into it (to check the pins
  install on the Python version CI uses) was denied by a permission rule; not redone another way. Recorded in
  D-105 and `docs/INSTALL.md` as not verified.
