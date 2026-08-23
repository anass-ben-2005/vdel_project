# PROMPT_CHANGELOG.md — `agents/prompts.py`

> BUILD_PLAN 4.6: **prompts are code — version them.** Every change to a string in
> `agents/prompts.py` bumps `PROMPT_VERSION` and adds an entry here, newest last.
>
> The reason this file exists is that M4's deliverable is a *measurement*. A stability number
> or an agreement rate is meaningless without knowing which prompt produced it, and prompt
> iteration is the research in M4 (`BUILD_PLAN.md` 4.5). An entry that does not say what
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
(blocked on Anas's per-criterion scores — `HANDOFF.md` open question 1), so accuracy against
intended scores cannot be computed. Self-consistency across repeated runs is measurable
without ground truth and has not been run either, because no `ANTHROPIC_API_KEY` is
configured yet.

**Known open question carried into v1.** The rubric's `idiomatic` criterion is "Idiomatic
Spark/SQL", but all five benchmark submissions are pandas/Python, not Spark or SQL. The
prompt currently instructs the judge to score the lower anchor and quote the line showing why
when a criterion cannot be assessed. Whether that is the right treatment — versus marking the
criterion not-applicable and excluding it from the aggregate — is a real design question and
is deliberately **not** resolved by silently tuning the prompt. Raise with Dr. Ezzatul.
