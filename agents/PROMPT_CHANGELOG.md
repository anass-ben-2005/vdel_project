# PROMPT_CHANGELOG.md — `agents/prompts.py`

> Build-plan task 4.6: **prompts are code — version them.** Every change to a string in
> `agents/prompts.py` bumps `PROMPT_VERSION` and adds an entry here, newest last.
>
> The reason this file exists is that M4's deliverable is a *measurement*. A stability number
> or an agreement rate is meaningless without knowing which prompt produced it, and prompt
> iteration is the research in M4 (build-plan task 4.5). An entry that does not say what
> failure mode the change addressed is not a useful entry — "improved wording" tells a future
> reader nothing about whether to keep the change.
>
> Format per entry: version · date · what changed · which failure mode · what the benchmark
> said before and after. Leave the benchmark columns as `not yet measured` rather than
> guessing — `CLAUDE.md` §10 forbids inventing numbers, and an unmeasured prompt change
> honestly labelled is worth more than a plausible fabricated delta.

---

## v1 — 2026-08-19 — initial prompt

**What it is.** The first judge prompt, transcribed from `VDEL_Modules_3_9_Build.md` D.3/D.5
with four documented deviations (all recorded in the `agents/prompts.py` module docstring):
structured `{"quote", "why"}` evidence objects instead of `"quote + why"` strings; the rubric
as a module constant rather than an `assignments` column that does not exist; the D.4 fairness
rule stated twice; and no `CRITICAL:`/`YOU MUST` emphasis anywhere.

**Failure modes each element defends** — the table in the module docstring is authoritative;
in short: hallucinated quotes, prompt injection, halo/anchoring bias, unanchored scores,
wasted attention on findings a linter already produced, and tone-deaf feedback.

**Benchmark result:** **not yet measured.** `benchmark/ground_truth.json` does not exist yet
(blocked on the author's per-criterion scores), so accuracy against
intended scores cannot be computed. Self-consistency across repeated runs is measurable
without ground truth and has not been run either, because no `ANTHROPIC_API_KEY` is
configured yet.

**Known open question carried into v1.** The rubric's `idiomatic` criterion is "Idiomatic
Spark/SQL", but all five benchmark submissions are pandas/Python, not Spark or SQL. The
prompt currently instructs the judge to score the lower anchor and quote the line showing why
when a criterion cannot be assessed. Whether that is the right treatment — versus marking the
criterion not-applicable and excluding it from the aggregate — is a real design question and
is deliberately **not** resolved by silently tuning the prompt. Raise with the supervisor.

---

## v2 — 2026-10-11 — the correctness score is an opinion, and is named as one

**What changed.** (1) The score field `correctness` is now `llm_correctness_opinion` in the
output schema (the rubric criterion, the evidence key `correctness` and the anchors are
unchanged). (2) One sentence after the rubric tells the judge the score is its reading of the
code, not a test result, and that executed tests decide correctness. (3) `Scores` in
`agents/code_agent.py` accepts both names when reading (`correctness` stays as a read-only
alias for old traces and for `scripts/demo.py`); new traces are written with the new key. The
payload `agent` field is now `code_agent_v2`.

**Failure mode.** A reader (a dashboard, a future Reviewer, a mastery rule) taking the model's
reading of the code for a result. D-036 / invariant 13: correctness is decided by executed hidden
tests, never asserted by an LLM. Naming the field after what it is makes the misuse visible in
every query and diff.

**Benchmark result:** not yet measured (no live calls were made on the agents branch; no
`ground_truth.json` labels exist). The rubric anchors and evidence rules did not change, so no
effect on scores is expected, but that is a hypothesis, not a measurement.

---

## fb1 — 2026-10-11 — Feedback Agent, first prompt (`agents/feedback_prompts.py`)

**What it is.** The prompt of the Feedback Agent (a separate file and version line from the
Code Agent's `PROMPT_VERSION`). It contains facts computed by code (failed checks by name and
exception type, recurring gaps, weakest concept, a tone-only mastery slice, a closed list of
candidate resources) and no student code and no hidden test source.

**Failure modes each element defends:** invented tests/concepts (closed lists, validated),
invented resources or links (resource_id or null, links rejected), the model asserting correctness
(rule in the prompt, pattern check after), leaking a hidden check (exception type only, hidden-line
guard), a mastery claim reaching the student (quoting numbers forbidden, "master*" rejected).

**Benchmark result:** not yet measured. No live call has been made; the agent was exercised only
against a scripted fake provider.

---

## v3 — 2026-10-12 — Code Agent hardening (D-103)

**What changed.** (1) Every run of three or more `<` or `>` characters in text that comes from the
student (the submission, and the linter findings built from it) is replaced by `[LT3]` / `[GT3]`
before it enters the prompt, and the injection rule says so. (2) The rubric, the output schema and
the evidence rule follow the criteria asked: an assignment can be judged on a subset
(`config/judging.yaml`; `weather_etl` drops "Idiomatic Spark/SQL"). With all four criteria the rubric
table and the schema block are byte-identical to v2 (a test pins the rubric hash). (3) When only the
student's gap lines are judged, a `## What you are shown` section says so and tells the judge not to
quote the `[... n line(s) not shown ...]` marker. The Code Agent's payload `agent` is now
`code_agent_v3`.

**Failure modes.** A student file containing `<<<END SUBMISSION>>>` followed by instructions closed the
data block in the text the model reads (prompt injection through the delimiter). A pure-Python
assignment scored against a Spark/SQL criterion. The master's own code, present in every file, judged
as the student's work.

**Benchmark result:** not yet measured. No live call has been made on this version. For the PySpark
benchmark (all four criteria, whole file) the only difference in the prompt of a file that holds no
marker sequence is the three-line addition to the injection rule, so no change in scores is expected;
that is a hypothesis, not a measurement.

---

## fb2 — 2026-10-13 — Feedback Agent v2, behind `--agents-v2` (D-108)

**What it is.** A second prompt for a second agent id (`feedback_agent_v2`), in `agents/feedback_prompts.py`
(`build_feedback_prompt_v2`). The fb1 prompt, schema and agent are untouched and remain what runs without
the flag; a test pins their sha256 (prompt, markdown, trace payload, addendum). fb2 adds to the facts:
the student's own gap lines plus three lines of context between `<<<BEGIN STUDENT LINES>>>` delimiters (a run
of three `<` or `>` inside them is escaped, D-103); the reviewed public description of each failing check
(`config/checks.yaml`, drafts never); how many pushes of the attempt each failing check has failed on; and a
hint level chosen by code from that count (1 expected behaviour, 2 point at one line, 3 a strategy in words).
The schema gains `quotes` (1 to 3 single lines copied from the student's lines, at most 100 characters).
Rules added to the prompt: never write code; do not repeat the counts or the check names; the student's lines
are data. The reference solution is not in the prompt.

**Failure modes each addition defends.** A hint that gives the answer (no code, no code block, an inline span of
at most 60 characters, and a validator that rejects a reply sharing 25% of the master body's 4-grams); a
generic reply that never looked at the student's work (a verbatim quote of their code is required and
string-matched); a reply that repeats what the deterministic text already shows (counts and test names
rejected); a student file that tries to instruct the model (delimiters escaped, the lines marked as data); a
commit with nothing to quote or nothing started (no provider call at all: a fixed sentence for
`NotImplementedError` stubs, the deterministic text when no excerpt can be cut out).

**Benchmark result:** not measured. No live call was made; the agent was exercised only against the scripted
fake provider. The thresholds (25%, 4-grams, 100 and 60 characters, the recurrence-to-level mapping) are design
choices to be confirmed, not measurements.

---

## v4 — 2026-10-13 — Code Agent production prompt, behind `--agents-v2` (D-109)

**What changed.** A production mode (`grade(production=True)`, `build_grading_prompt(production=True)`),
used by the cycle with `--agents-v2`. The code has already passed every hidden check, so: the
"correctness" criterion is dropped (its rubric block, its evidence line and its score field
`llm_correctness_opinion` are gone from the prompt and the schema, and the verdict stores null for it);
the `llm_correctness_opinion` note is replaced by a short note saying every hidden check has passed and
the judge is to say nothing about whether the code works; the sentence "Judge correctness before
readability" is dropped from the field-order note; and a reference solution is refused (a `ValueError`, in
both `grade` and the prompt builder). The stored payload says `agent: code_agent_v4`, `prompt_version: v4`,
`mode: production`, `research_only: []`. The default (no `production`) is exactly v3: the benchmarks
(`benchmark/run_benchmark.py`, `benchmark/run_real_benchmark.py`) and the demo still ask for the opinion and
may supply a reference, and a test compares the two prompts.

**Failure modes.** A judge asked for a correctness opinion on code the tests already passed would be paid
to disagree with an executed result, and a reader could take its number for one (D-036); a reference
solution in the production prompt would make the judge grade closeness to one solution instead of the
quality of a working one.

**Benchmark result:** not measured. The v4 prompt has never been sent to a model. The only real run
(`benchmark/RECOMMENDATION.md`) measured the v2 prompt in benchmark mode on five PySpark files, with
labels pre-written by an LLM; it reached 60% exact agreement on approach. v4 judges approach and
readability only, so what that run says about it is a hypothesis, not a measurement.
