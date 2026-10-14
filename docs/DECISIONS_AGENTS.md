# DECISIONS_AGENTS.md: decisions taken on the agents branch (D-200 and up)

Numbered from D-200 so they never collide with `docs/DECISIONS.md`. Append-only. The branches have merged;
these entries stay in this file under their D-2xx ids, which are never renumbered (code comments cite them).

Status values: **BRIEF** = the overnight brief asked for it. **UNATTENDED** = taken during the
unattended night without the author; the alternative is written so each can be reversed cheaply.
Format per entry: Context / Decision / Alternative / Reverse.

---

### D-200 Only the score field is renamed, not the rubric criterion
Status: BRIEF (rename) + UNATTENDED (scope of the rename)
Context: `Scores.correctness` is the model's reading of the code. Since D-036 it must not look like
a result. The word `correctness` is also the rubric criterion (evidence key, `CRITERIA`, the
anchors, `ground_truth.json`, Echo's parity tests, stored `evidence` objects).
Decision: rename the score field to `llm_correctness_opinion` (schema, model, prompt `v2`), keep
the criterion name `correctness` everywhere else.
Alternative: rename the criterion too. Rejected: it breaks Echo's identical-criteria contract, the
ground-truth file format and the evidence of every stored trace, for no extra safety.
Reverse: change `Scores`, `OUTPUT_SCHEMA_BLOCK`, the prompt note; keep `trace_compat`.

### D-201 Old name stays readable; no edit to the forbidden reader
Status: UNATTENDED
Context: traces are append-only (old payloads keep `correctness`); `scripts/demo.py` (forbidden)
reads `s.correctness` on the object.
Decision: `Scores` accepts either key when reading (`AliasChoices`), exposes `correctness` as a
read-only property, always writes the new key; `agents/trace_compat.py` reads stored payloads of
either version. The demo edit is IR-1.
Alternative: drop the property and break the demo until the main branch edits it. Rejected.
Reverse: delete the property once IR-1 is applied.

### D-202 The fake LLM replaces the provider handlers, not `llm.judge`
Status: UNATTENDED
Context: the existing tests fake `llm.judge`, which skips fence stripping, validation, the retry,
the cost log, the fallback chain and the timeout: exactly what bad model replies exercise.
Decision: `agents/fake_llm.py` replaces all five handlers in `llm._PROVIDER_HANDLERS`, disables
key discovery, pins the provider, and runs the real `llm.judge` on scripted raw text. All five,
not one, because a scripted failure would otherwise walk the fallback chain to a real provider
whenever a key is in `.env`.
Alternative: keep faking `judge` (simpler, less faithful, cannot test the gateway behaviours).
Reverse: agents accept any object with `judge`; a plain fake still works.

### D-203 No LLM call for collection_error, timeout, tooling, or a commit with no failure
Status: UNATTENDED (the brief says these statuses get "a plain-words explanation, never a mastery
claim"; it does not say who writes it)
Decision: the deterministic v0 text is used; the budget is not spent; the model cannot say
anything wrong about a status it is never shown.
Alternative: an LLM explanation of the status. Rejected for v1: the v0 text is already plain and
correct, and a load error or a timeout is not a wrong answer, so there is nothing to interpret.
Reverse: remove the early returns in `run_feedback_agent`.

### D-204 The Feedback Agent prompt contains no student code
Status: UNATTENDED (C10 says the LLM receives the diagnosis "plus the code")
Context: the brief's input contract lists the diagnosis, the allowed failure info, the mastery
slice and the candidates, not the code. Code in a prompt is a prompt-injection surface and a
second channel for hidden-test content to be echoed.
Decision: facts only. Alternative: add the gap region of the student's file. Deferred (section 12).
Reverse: add a `code` field to `FeedbackInput` and a delimited block to the prompt.

### D-205 Two validation rules beyond the brief: no links, no mastery wording
Status: UNATTENDED
Decision: `link_in_text` rejects any URL in model text (links come only from the resource row);
`mastery_claim` rejects "master/mastery/mastered" (the slice is for tone only; a mastery statement
to a student is a claim nobody computed for this message).
Alternative: only the five rules in the brief. Cost: possible false rejections, which end in the
deterministic text, never in a worse message.
Reverse: delete the rule from `validate_output`.

### D-206 Budget exhaustion: the Code Agent raises, the Feedback Agent falls back
Status: UNATTENDED (the brief asks for "a clear error" for the Code Agent budget, and a fallback
only on validation failure)
Decision: `BudgetExceeded` propagates from `code_agent.grade`; in the Feedback Agent it ends in
the deterministic text with the reason recorded, because a student's message must not be lost to
a cap. The pipeline reports each as that step's outcome.
Alternative: raise in both.

### D-207 Resource vocabularies: kinds from the schema comment, levels chosen
Status: UNATTENDED
Context: `sql/06` comments `kind` as `book_section | doc_page | kaggle | video` and gives `level`
no values.
Decision: `KINDS` as commented; `LEVELS = beginner | intermediate | advanced`, both validated by the
loader. Alternative: free text (no validation). Reverse: edit `agents/resources.py`.

### D-208 Loader safety stack
Status: BRIEF (dry run default, `--dsn`) + UNATTENDED (the extra guards)
Decision: dry run touches no database; `--apply` needs an explicit `--dsn` (never the
environment); refuses a database whose name does not end in `_test` unless `--allow-real-db`;
refuses `EXAMPLE` rows; one transaction; upsert; no delete.
Alternative: trust the operator. Rejected: the real table is empty and the first real load should
be a deliberate act.

### D-209 Candidate selection policy
Status: UNATTENDED
Decision: by concept, optional level filter (rows with no level are kept), easiest first then id,
default limit 5, no inference of the student's level. The limit is a choice, not a measurement.
Alternative: pick the level from mastery. Deferred: it would need thresholds nobody has measured.

### D-210 Budget: unit, defaults, fail-closed ledger
Status: BRIEF (caps, counting by model, JSON file) + UNATTENDED (details)
Decision: the unit is the provider call; a judge reserves 2 and settles to what happened; any
failure that hides the count is charged in full as model `unknown`; default per run 6, no default
daily cap (the caller sets it); the ledger is counts only, and an unreadable file raises instead
of resetting to zero. `.vdel/` was added to `.gitignore` (a new path, so added, not proposed).
Alternative: count logical judge calls; reset on a corrupt file. Both under-count.

### D-211 Persistence proposal uses the existing `coach` / `intervention` vocabulary
Status: UNATTENDED
Decision: IR-3 writes the Feedback Agent's result as `actor="coach"`, `kind="intervention"`
(already in `NON_MASTERY_KINDS`), so no `memory.py` change is needed and BKT cannot be fed.
Alternative: a new kind `feedback` (a forbidden-file change plus a replay-set decision).

### D-212 The pipeline cannot persist yet
Status: BRIEF
Decision: `persist=True` raises `IntegrationPending` before any work; `persist=False` runs the
Code Agent on a `DryRunMemory` that records instead of writing. Alternative: a real write path
behind a flag. Rejected: it needs IR-3.

### D-213 The benchmark must not use the gateway cache
Status: UNATTENDED
Context: `llm.judge`'s docstring says so; `run_benchmark` called `grade()` with the cache on, and
`grade()` could not pass the flag.
Decision: `grade(..., use_cache=True)` (default unchanged, so live behaviour on main is the same),
`run_benchmark` passes `False`, and reports JSON validity and token counts from the cost log.
Consequence: any stability number produced by the old benchmark measured cache replays.

### D-214 Shared-file edits made on this branch
Status: UNATTENDED
Decision: `.gitignore` (+3 `!docs/...` lines so the new docs and the CSV template are trackable
without `git add -f`; `+.vdel/`); `pyproject.toml`
`extend-exclude` += `tests/fixtures/agents/code` (a fixture that does not compile on purpose).
Alternative: a `.txt` extension for the broken fixture and `-f` when adding docs. Rejected: the
first hides the file type from ruff's explicit-path linting the Code Agent relies on; the second
is forbidden by the brief.

### D-215 Fixtures
Status: BRIEF + UNATTENDED
Decision: real exports store the diagnosis, statuses, gap and concept ids and exception types
only (never messages, tracebacks, code); mastery is the profile at export time, not at the commit;
there is no real `timeout` commit, so one is synthetic; the Code Agent fixtures are hand-written.
`tests/test_agents_fixtures.py` scans every fixture for hidden-test lines (bare `import` lines are
ignored: they are shared by every file about the same library).

### D-216 `use_cache` defaults to True in `grade`
Status: UNATTENDED. Changing the default would change what main's demo does with a live key.

### D-217 The correctness-claim check is a pattern list, v1
Status: UNATTENDED
Decision: a short English regex list behind the prompt rule, tested on positives and negatives.
It will miss paraphrases; it may reject a harmless sentence; both end safely (retry, then the
deterministic text). Hostile paraphrase is listed under "Later".

### D-218 Test references are normalised before checking
Status: UNATTENDED. `tests/x.py::test_a`, `test_a (x.py)` and `test_a` all name one test; anything
else is `unknown_test`.

### D-219 The Feedback Agent does not raise for LLM-side problems
Status: UNATTENDED. Every provider error, timeout, double schema failure, rejection or spent
budget returns the deterministic text with a recorded reason. Bad inputs (unknown attempt or
commit) still raise `ValueError`.

### D-220 Concept taxonomy path
Status: UNATTENDED. The brief names `curriculum/concepts.yaml`; it does not exist. The loader uses
`config/concepts.yaml` through `config.concepts.ids()` (the taxonomy the rest of the repo uses).

### D-221 Prompt versions
Status: UNATTENDED. The Code Agent keeps `PROMPT_VERSION` (now `v2`); the Feedback Agent has its
own `FEEDBACK_PROMPT_VERSION` (`fb1`); one changelog (`agents/PROMPT_CHANGELOG.md`) records both.

### D-222 The labeling sheet and ground truth
Status: UNATTENDED. The sheet goes to a gitignored directory and is never overwritten without
`--force`; the import step validates scores in {0, 2, 4}, drops fixture rows, and refuses to
overwrite `benchmark/ground_truth.json`. No label was written by the branch; the file is still all
`null`.

### D-223 The benchmark ran only against the test database, with the fake
Status: BRIEF. `run_benchmark.run()` inserts its own synthetic student and rolls back; run against
the real database it would have been a write session, so it was only ever run inside pytest
against `vdel_test`. Live numbers need the author's decision and key.

### D-224 OpenAI provider in system/llm.py
Status: BRIEF (the request) + UNATTENDED (the details below)
Decision: `_call_openai` is a real handler on the official `openai` SDK (already a dependency),
plain chat completions, no native JSON mode, key `OPENAI_API_KEY` (its own variable, `.env.example`
only), `max_retries=0` (the gateway is the single retry policy), `max_completion_tokens`
(assumption to confirm in the first live call). `Provider.OPENAI` joins `_FALLBACK_KEY_ENV_VARS`.
Model ids stay `TODO(verify)` (superseded by D-225): the handler raises `ValueError` before any
network call, and the fallback chain skips them. `_OPENAI_REJECTS_TEMPERATURE` exists and is empty (no source for any id).
Alternative: guess current model names (rejected: CLAUDE.md section 10); keep `max_tokens`.
Cost: `test_llm.py` lost its "openai is a stub" test, replaced by "openai refuses an unconfirmed model".

### D-225 OpenAI model ids are the author's, unverified by this branch
Status: DECIDED by Anas (supplied the ids), recorded here after the fact
Context: `MODEL_TIERS` now holds `gpt-6.1-sol` (default) and `gpt-6-luna` (cheap), written by Anas
after D-224 left them `TODO(verify)`. Same status as D-031's NVIDIA id: given, not checked against
the provider's catalogue by the session that wrote the code. A first live call returned HTTP 400
on both; the handler now retries once without `temperature` on a 400 that names it, remembers the
model in `_OPENAI_REJECTS_TEMPERATURE`, and failure lines show the provider's message.
Live result: the author ran the smoke call with the other providers' keys blanked in that
session, so no fallback could mask it. Output, exactly:
`ok=True word='hello' provider=openai model=gpt-6.1-sol tokens_in=16 tokens_out=12 attempt=1`.
OpenAI is therefore a live provider, not a stub. What is NOT established: the two ids were
supplied by the author and this branch has not verified them against OpenAI's public model list;
nothing else is claimed about them.
Consequence: with `OPENAI_API_KEY` set, OpenAI is now part of the fallback chain. Setting an id
back to `TODO(verify)` removes it from the chain and makes the handler refuse it.
