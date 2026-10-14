# CONTRIBUTING.md

How to change this repository without breaking what is proven. Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
first (the sixteen invariants are in its section 6) and [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) so you do
not fix a known limit by accident or break its workaround.

## The loop for every change

1. **Branch from `main`.** Small, one purpose per commit, in conventional style: `feat:`, `fix:`, `docs:`,
   `test:`, `chore:`. The message says what and cites the decision (`(D-106)`).
2. **Snapshot the data before you start**, then again after:

   ```bash
   python -m scripts.baseline --full > before.txt
   # ... change ...
   python -m scripts.baseline --full > after.txt && diff before.txt after.txt
   ```

   The baseline is read-only (Postgres rejects writes in its session). With every new flag *off*, a change
   must leave the two outputs **identical**; if it cannot, the change touches real data and needs a decision
   entry that says so.
3. **Run the suite on its own database, and lint:**

   ```bash
   VDEL_REQUIRE_DB=1 python -m pytest -q       # about eight minutes
   ruff check .
   ```

   The suite builds a throwaway `<name>_test` database (so `vdel` becomes `vdel_test`), applies the schema and
   the curriculum, and **refuses to connect to the real one**; the end of the output prints the number of
   connections made to `vdel` (it must be 0). `VDEL_REQUIRE_DB=1` makes "the test database could not be
   built" an error instead of a silent skip: always set it. One test session at a time (an advisory lock).
4. **Write the decision** (section below) and update the documents the change makes untrue.
5. **Commit.** Never commit `.env`, `config/roster.yaml`, anything in `renders/`, `backups/`, `logs/`,
   `.vdel/` or `benchmark/results/` (all gitignored; do not force-add them).

## The fake LLM rule

**No test makes a live LLM call, ever.** Use `agents/fake_llm.py`:

```python
fake = fl.FakeLLM([fl.valid_json({...}), fl.invalid_json()])   # one scripted step per PROVIDER call
with fake.installed():                                         # code that calls system.llm directly
    code_agent.grade(...)
```

It replaces the provider *handlers*, so the real gateway (fence stripping, schema validation, the corrective
retry, cost log, cache, fallback, timeout) runs on top of scripted text. It also forces key discovery to
nothing and makes `generate` raise, so a test that forgets the fake cannot walk on to a real provider because
a key is in `.env`. Test modules that exercise the cycle block the handlers in an autouse fixture. Once, a
test that forgot made two real calls and wrote to `.vdel/` (D-099, "Incident"); the guard exists because of it.
Never call a provider SDK outside `system/llm.py`: ruff's banned-import rule fails the build.

A real call is a deliberate, manual, capped act: `scripts/llm_first_call.py` and
`benchmark/run_real_benchmark.py`, run by a person (`docs/OPERATIONS.md` sections 12 and 13).

## Rules that are easy to break

- **`traces` is append-only.** Insert only. Code that updates or deletes a trace is a bug. Tests that write
  traces roll back; they never commit to a shared database.
- **`memory/memory.py` is the only door** to traces and the profile. Agents and scripts do not write SQL there.
- **Never run a student's code in your process.** Grading runs in `assessment/test_runner.py`, a subprocess or
  container that imports nothing from `agents/` or `system/llm.py` (a grep before each commit that touches it).
- **Raw tables are never overwritten.** Formulas change; history is recomputed from raw events.
- **Idempotent writers.** A collector, loader or seeder must be safe to run twice (`ON CONFLICT`).
- **Do not trade explainability for accuracy.** If a change would (a neural mastery model, an LLM deciding
  correctness), stop and ask.
- **Never invent a number, price or citation.** Write `TODO(verify)` until a command has produced it, and
  paste the command and its output beside it. A disappointing measured result is a finding, not a failure.
- **Concept ids and `formula_ver` are schema.** Add, never rename. A formula change bumps `formula_ver` and
  keeps the old rows reproducible.
- **Nothing here posts to GitHub on its own.** Writes need both `--apply` and `VDEL_ALLOW_GITHUB_WRITE=1`.
- **Never edit the real `config/roster.yaml` from code or a test.** Use `scripts/roster_apply.py`, by hand, or
  a temporary copy in a test.
- **Secrets stay in `.env`.** Print their names, never their values; `.env.example` lists names only.

## Prompts are code

Prompts live in `agents/prompts.py` and `agents/feedback_prompts.py`. Changing the text of one means:

1. bump its version constant (`PROMPT_VERSION`, and the feedback prompt's version);
2. add an entry to `agents/PROMPT_CHANGELOG.md` saying what changed and why;
3. update the tests that pin it (the rubric table's sha256 is pinned, so a silent edit fails);
4. re-run the benchmark if the change could move scores (`benchmark/` is the prompts' test suite; the real run
   is billed, capped and manual, and measures one provider on five files only).

The stored trace carries `prompt_version`, so an old verdict stays interpretable.

## Writing a decision

`docs/DECISIONS.md` is the append-only record of what was decided and why. It is what a reviewer or
supervisor reads to defend a choice, so it is written for them.

```bash
grep -n "^### D-" docs/DECISIONS.md | tail -3      # find the next number; never reuse or renumber
```

Append at the end:

```
### D-106 -- one line: what was decided
Date:        2026-10-14
Status:      DECIDED and implemented | OPEN | RESOLVED
Authority:   who asked for it
<the decision, the reason, what was NOT done, what was verified and how, and a CONFIRM line for each choice
 that is the author's to confirm>
Tests:       which tests prove it, and which mutation (a deliberate break) turned them red
```

Do not edit an earlier entry to change what was decided; add a new one that supersedes it (D-035 does this to
an older prohibition). A correction of a mistake of fact may be made in place with a visible note. Agents-branch
decisions are numbered D-200 and up in `docs/DECISIONS_AGENTS.md`.

## Documents, one job each

| File | Owns |
|---|---|
| `docs/explanation.md` | What the code actually does, file by file. Update it in the **same commit** as the code |
| `docs/DECISIONS.md` | What was decided and why. Append-only |
| `docs/KNOWN_ISSUES.md` | What is wrong or missing, with impact and workaround |
| `docs/OPERATIONS.md` | How to run it |
| `docs/ARCHITECTURE.md`, `docs/AUTHORING.md`, `docs/INSTALL.md`, `docs/GLOSSARY.md`, `docs/HOWTO_EXTEND.md` | Orientation |
| `docs/VALIDATION.md` | What has been shown to work, with command, date and source |
| `docs/ROADMAP.md`, `docs/DATA_PROTECTION.md`, `docs/RELEASE_AND_UPGRADE.md` | The open work, the data held, how to upgrade |
| `CLAUDE.md`, `docs/design/` | The rules for the code and the design documents it cites |
| `CHANGELOG.md` | A map into the decisions |

Do not state the same fact in two of them. A docstring states the **why**, citing the decision or the paper.

## Style

Python 3.11+, line length 100, the ruff rule set in `pyproject.toml` (`E F W I UP B SIM C4 DTZ BLE RUF TID`).
Match the surrounding code: comment density, naming, idiom. Files transcribed from the specification
(`variables/*.py`) are held character for character and exempted from cosmetic rules on purpose; do not
restyle them. `curriculum/` is graded content and frozen once issued ([docs/AUTHORING.md](docs/AUTHORING.md)
section 10).

## On Windows

The author's working folder has a name that contains an apostrophe, and yours may contain spaces or other special characters. Quote every path
in PowerShell and use `-LiteralPath`; `scripts/windows/task_command.ps1` and D-095 explain what broke.
