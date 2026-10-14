# HOWTO_EXTEND.md: add a project, a gap, a check, an agent or a variable

Short pointers to where each extension is described in full. This page invents no procedure: every step names the
document or file that holds it. Always work the way `CONTRIBUTING.md` says (a branch, the baseline before and
after, the suite on its own database, a decision entry).

## 1. A project (a master the students complete)

1. Put the tree under `curriculum/master/<project>/` and register it in `scripts/seed_data.py` (`main()`; the
   project list is not discovered). `docs/AUTHORING.md` sections 1 and 9.
2. Write the stages, the hidden tests and the visible tests (sections 4 and 5), the learning resources (section 6),
   the public check descriptions (section 7) and the judging entry (section 8).
3. `python -m scripts.validate_master <project>` must report no error; `--require-reviewed` before a pilot
   (section 11). Then `python -m scripts.seed_data`. The checklist is section 12.
4. A released master is frozen content: to fix a mistake prefer a new stage or project over an edit (section 10,
   invariant 15 in `CLAUDE.md` section 7).
5. The design of the first ten projects is `VDEL_TEN_PROJECT_CURRICULUM.md`.

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
