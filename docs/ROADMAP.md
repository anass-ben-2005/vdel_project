# ROADMAP.md: next steps, and the ownership question

What is open, in a sensible order, with the document that records each item. Nothing here is a promise or a
schedule. Facts are cited; where a fact could not be confirmed from the repository it says `TODO(verify)`.
What has been proven is in [VALIDATION.md](VALIDATION.md); what is wrong today is in [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

## 1. Next steps

1. **Run the v2 agents once with a real model, by hand, on one student.** `--agents-v2` (Feedback Agent v2 and
   Code Agent v2) has only met the scripted fake provider. How often a real model passes the Feedback Agent's
   validator is unknown, and its thresholds (100 and 60 characters, 4-grams at 25%, 4000 characters of excerpt,
   the 1/2/3 ladder) are design choices, not measurements. Procedure: `docs/OPERATIONS.md` section 16.
   Sources: KNOWN_ISSUES items 21 and 22; D-108, D-109.
2. **Measure the Code Agent on the real course material.** Its verdict is stored and never posted. The one real
   benchmark measured the benchmark-mode prompt on five PySpark files whose labels were pre-written by an LLM;
   the production prompt (v4) has never been benchmarked and no `weather_etl` labels exist. The "Going further"
   note stays locked (`post_review.enabled: false` in `config/judging.yaml`) until that is done: label
   `weather_etl` submissions by hand, add a production mode to the benchmark runner, run it, enable only if the
   gate opens. Sources: KNOWN_ISSUES items 11 and 22; D-102, D-103, D-109; `benchmark/RECOMMENDATION.md`.
3. **Publishing and delivery for more than one student.** Publishing a repository, inviting the student and
   delivering the next attempt are run by hand, one student and one stage at a time (`docs/OPERATIONS.md`
   sections 7, 8 and 15; D-057, D-090, D-105). A bulk path is not built. `TODO(verify)`: whether a loop over the
   roster is enough or the GitHub rate limits need handling.
4. **A multi-student pilot.** The checklist is `docs/PILOT.md`. Still open: the database role in
   `sql/pilot/vdel_cycle_role.sql` has never been executed on a PostgreSQL; consent, retention and deletion are
   not written (see [DATA_PROTECTION.md](DATA_PROTECTION.md)); a placeholder GitHub login for the second
   student is refused by posting and delivery. Sources: KNOWN_ISSUES items 18 and 23; D-110.
5. **Code health: duplicated plumbing.** The same logic exists more than once. Each copy has tests; unifying
   them is a refactor that must leave the baseline identical (`CONTRIBUTING.md`):
   - the GitHub REST wrapper (`scripts/publish_repo.py` `GitHub`, `scripts/sync_template.py` `Contents`,
     `scripts/backfill_head_sha.py` `RunsAPI`), each with its own header dict and timeout;
   - reading `GITHUB_TOKEN` (`scripts/publish_repo.py` `_token`, `scripts/sync_template.py` `_load_token`);
   - the git environment and runner (`scripts/grade_collected.py` `_git_env`, imported by `scripts/publish_repo.py`
     together with its own `_git`);
   - roster text editing with two backup policies (`scripts/publish_repo.py` `update_roster_text` and
     `write_roster`, which keeps one rolling `.bak`; `scripts/roster_apply.py` `plan_edit` and `apply`, which writes a
     timestamped backup and never overwrites one);
   - `_session` (identical in `memory/memory.py` and `assessment/test_runner.py`, a copy kept on purpose so
     the test runner imports nothing from the agents) and `gap_of` (`assessment/test_runner.py` and
     `scripts/validate_master.py`).
   Several functions are longer than 80 lines (for example `agents/code_agent.py` `grade`,
   `scripts/validate_master.py` `validate`). No change is proposed to them here.
6. **Science.** BKT parameters are defaults until there are at least 50 sequences per concept to fit
   (`CLAUDE.md` section 8); V4 and the V2 alpha gate are degenerate with a cohort of one (D-004); unclassified CI
   errors reduce the evidence for V5 and V6 (KNOWN_ISSUES item 7, D-096); several formula versions live side by
   side (KNOWN_ISSUES item 6; the current `FORMULA_VER` is `v8` in `features/compute_features.py`).
7. **Designed but not built** (each has a named seam and trigger in `CLAUDE.md` section 3 and
   `docs/ARCHITECTURE.md` section 8): the Reviewer and orchestrator, the Coach, the knowledge graph and retrieval
   from the tutor side, differential testing (D-036), an Airflow run (KNOWN_ISSUES item 16).
8. **A per-project manifest.** Replace the hard-wired registration in `scripts/seed_data.py` `main()` (and its copy in
   `tests/conftest.py`) by a small manifest per project (stages, order), so adding a project needs no code edit
   (`docs/HOWTO_EXTEND.md` section 1, step 8).

## 2. Ownership and licence (open question)

No `LICENSE` file exists, and the repository does not say who owns the code. The README says: "License: not decided yet".
Decide, and record the decision in `docs/DECISIONS.md`:

1. Who owns the code: the author, the university, the industry partner, or a combination. `TODO(verify)`.
2. Which licence applies, or whether the code stays all rights reserved.
3. The licences of the dependencies in `requirements.txt` (no inventory has been made). `TODO(verify)`.
4. What the authors line in `README.md` should say once the owner is known.
5. Whether the sanitized design documents in `docs/design/` fall under the same licence.
