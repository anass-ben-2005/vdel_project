# GLOSSARY.md

Terms as this repository uses them, alphabetical. A `D-nnn` points to the decision in
[DECISIONS.md](DECISIONS.md) that explains it; a path points to where it lives.

**Advisory lock.** A Postgres lock the cycle and the hourly run take so two of them cannot overlap; the second
exits with code 3. `scripts/run_cycle.py`, `scripts/run_hourly.py`.

**After-grade hook (`AgentsHook`).** Code that runs right after a commit is graded, while the student's file
still exists in the temporary checkout. The only place the agents are called from. D-099, D-104.

**Assignment.** One stage of a project: one file the student edits, with its hidden tests. Id
`<project>_<stage>`, for example `weather_etl_extract`.

**Attempt.** One student's try at one assignment, numbered from 1, with a variant. Open until its hidden tests
reach 100% on a pushed commit, then frozen. Table `attempts`. D-045.

**Auditability.** The governing rule: a grade that cannot be explained cannot be defended. It is why the system
uses event sourcing, executed tests, quoted evidence and an interpretable mastery model.

**Baseline.** `python -m scripts.baseline [--full]`: a read-only fingerprint of the database (row counts and
content hashes). Run before and after a change; identical output is the evidence the change did not touch
data.

**BKT (Bayesian Knowledge Tracing).** The mastery model: a probability that the student knows a concept,
updated per observation, with guess and slip rates clamped below 0.5. Chosen over a neural model because it
is interpretable and its prediction can be falsified. `variables/mastery.py`.

**Blackboard.** The architecture: components share state in PostgreSQL and never message each other.

**Burstiness.** A measure of how unevenly commits are spaced in time (part of V3, a diagnostic only).

**Code Agent.** The optional LLM judge of working code: it scores approach and readability (and an
`llm_correctness_opinion` that is not a result) with quoted evidence. Stored, never posted, never fed to mastery,
and unmeasured on `weather_etl`. `agents/code_agent.py`. D-061, D-103, D-104.

**Collection error.** A hidden test file that could not be imported or collected. Recorded, not counted as the
student's failure and not evidence of skill. D-066, D-069.

**Completion problem.** The assignment format: a working project with blocks removed that the student writes.
D-035.

**Concept.** One id of the taxonomy (`config/concepts.yaml`), such as `py.errors_debugging`. Gaps and errors
are tagged with concepts; mastery is kept per concept. Concept ids are schema: never renamed.

**Cycle.** One `run_cycle`: collect, grade, features, profile, for every student in the roster. Idempotent.

**Deterministic text.** The feedback comment built by code from test names and exception types, with no LLM.
It is always the base of what is posted. `scripts/post_feedback.py`.

**Delivery.** Handing a student attempt N+1 of one stage as a new private repository.
`scripts/deliver_next_attempt.py`. D-090.

**Doctor.** `python -m scripts.doctor`: read-only OK/WARN/FAIL checks of the machine. D-105.

**Dry run.** A mode that reads and prints what would happen and writes nothing. The default of every script
that could write to GitHub.

**Event sourcing.** `traces` is the truth, an append-only log; `learner_profile` is a belief derived from it and
can be rebuilt by replaying the log.

**Evidence quote.** A verbatim string from the student's code that an LLM score must carry; checked by string
match, and a fabricated quote rejects the verdict. Invariant 6.

**Fake LLM.** `agents/fake_llm.py`: scripted provider handlers so the real gateway runs in tests without a
network call. The rule for tests is in [CONTRIBUTING.md](../CONTRIBUTING.md).

**Fast path / slow path.** Fast: deterministic, every event, free (BKT update, recurrence rule). Slow: a
weekly LLM reflection (designed, not built).

**Feedback Agent.** The optional LLM that words a diagnosis already computed by code. Its paragraph is added
under the deterministic text after validation. `agents/feedback_agent.py`. D-099.

**Feedback issue.** The GitHub issue, one per (student, attempt), where each graded commit gets one comment.
D-089.

**Formula version (`formula_ver`).** The version of the feature formulas a `learner_features` row was computed
with (now `v8`). Rows of several versions coexist. `features/compute_features.py`.

**Freeze.** An attempt is frozen at the commit whose hidden tests all pass; later commits are collected but not
graded as evidence. D-045, D-069.

**Gap.** A marked block of the master solution that the student must write: `# @gap: ... # @endgap`. Has an id,
concepts, a difficulty and an instruction. Table `gaps`. [AUTHORING.md](AUTHORING.md).

**Gateway.** `system/llm.py`, the only module that calls an LLM provider. Temperature 0, schema validation, one
corrective retry, fallback chain, timeout.

**Hard cap.** A wrapper on every provider handler that raises on the (cap+1)th real call, so a budget holds
even when the gateway walks its fallback models. D-101, D-104.

**Hidden tests.** The tests that grade an assignment; students never see their source, names or messages.
`curriculum/master/<project>/tests/hidden/`.

**Invariant.** One of the sixteen rules in [ARCHITECTURE.md](ARCHITECTURE.md) section 6.

**Jadud / Watwin.** Measures of how a student reacts to compile or run errors, used for V5.

**KT-IDEM.** BKT whose guess and slip depend on the item's difficulty (here `variants.difficulty`).

**Land raw first.** Raw tables are never overwritten, so history can be recomputed when formulas change.

**Ledger.** `.vdel/llm_usage.json`: counts of provider calls per day and model, no content. Gitignored.

**Leak guard.** The check that no hidden test source line appears in anything sent to a student or a prompt.
`scripts/post_feedback.py`, D-077.

**Master project / master version.** The reference solution with markers, and a hash of its files
(`master_version`) that every gap, variant and attempt pins; line numbers are valid for one version only.
Invariant 15.

**Mastery observation.** One piece of evidence for BKT: the first attempted pushed commit for each (attempt,
gap), with the test outcome. Trace kind `mastery_observation`. D-079.

**Observation count (`n`).** How many observations a mastery estimate rests on; always stored beside it.

**Out-of-scope lines (V9).** Changed lines outside the gap regions, over total changed lines: an integrity and
initiative signal. `assessment/scope_check.py`. D-073.

**Roster.** `config/roster.yaml` (gitignored): which students, repositories and start dates the cycle reads. A
person edits it, with `scripts/roster_apply.py`.

**Rubric.** The Code Agent's four criteria anchored at 0, 2 and 4: correctness, approach, readability,
idiomatic. `agents/prompts.py`; the subset per assignment is in `config/judging.yaml`.

**Sandbox.** Where student code runs for grading: a subprocess with a stripped environment, or, with
`VDEL_GRADING_SANDBOX=docker`, a container with no network. D-065, D-092.

**Stage.** One step of a project (extract, transform, load, quality); one assignment.

**Template push.** The first commit of a delivered repository (`Initial commit: ...`); not a student action.
D-098.

**Trace.** One row of the append-only `traces` table: an event with an actor, a kind, an assignment, concepts
and a JSON payload.

**Unclassified.** A failed CI run the error classifier could not map to a concept. It updates no mastery.
Invariant 10.

**Variant.** The set of gaps hidden for one student on one attempt, chosen deterministically from a seed and
the student's mastery; its id is a hash. Table `variants`. D-042.

**Variables V1 to V11.** V1 mastery, V2 engineering discipline, V3 effort regulation (diagnostic only), V4
learning pace, V5 error response, V6 error frequency, V7 help-seeking (not built), V8 functional equivalence,
V9 out-of-scope edit rate, V10 first-attempt success rate, V11 session fragmentation. All scaled to 0 to 1,
higher is better, each with its observation count. V1 to V6 are computed today; see `docs/explanation.md`
section 7.20 for the state of V8 to V11.

**Wheel-spinning.** Repeated failed attempts at the same check without progress (part of V5).
