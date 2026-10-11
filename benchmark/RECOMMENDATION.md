# Judge model recommendation: SKELETON (no results yet)

> Status: **empty on purpose.** Every number below is `TODO(measure)`. Nothing in this file has
> been measured: no live LLM call was made when this skeleton was written; the pipeline was only
> exercised against a scripted fake provider (`tests/test_agents_benchmark.py`). Per CLAUDE.md §10
> no score, price, rate or citation may be filled in without a source: write `TODO(verify)` until
> a command has produced it, and paste the command and its output next to it.

## 1. Question

Which model should the Code Agent and the Feedback Agent run on, and is the Code Agent's judgement
worth its cost? The decision is per agent, because the two have different jobs: the Code Agent
scores approach / readability / idiom (and gives a correctness *opinion*, `llm_correctness_opinion`,
which is not a result: D-036); the Feedback Agent only words a diagnosis that code computed.

## 2. Method (fixed before looking at any number)

| Item | Choice | Why |
|---|---|---|
| Inputs | `benchmark/submissions/*.py` (5 files, one task, `TASK.md`) plus the 4 synthetic student files in `tests/fixtures/agents/code/` | the only inputs with a known intent; no hidden test content |
| Labels | the author's own, 0/2/4 per criterion, from `scripts/agents_make_labeling_sheet.py` | the labels are never a model's (CLAUDE.md §10) |
| Judge outside the candidate set | the judge model must be a different family from every candidate that wrote or graded the code | C9, self-preference contamination (Panickssery et al. 2024: **verify before citing**) |
| Temperature | 0, enforced by `judge()` having no temperature parameter | invariant 4 |
| Cache | off (`use_cache=False`) | otherwise a re-run replays stored strings and "stability" measures a dict. **Found on this branch:** before it, `run_benchmark` called `grade()` with the cache on, so runs 2 and 3 were replays. Any number measured before this change is not a stability number |
| Runs | 3 per submission per model | BUILD_PLAN 4.5 |
| Prompt version | record `PROMPT_VERSION` (`agents/prompts.py`) with every number | a number without its prompt version is meaningless |
| Database | the benchmark opens its own student and rolls back (`--commit` not used) | no trace may be left behind |

Order of work: (1) label by hand, fill `benchmark/ground_truth.json`; (2) run
`python -m benchmark.run_benchmark --runs 3` per candidate model (this is the first live call and
needs the author's decision and a key); (3) paste the output below.

## 3. Metrics

| # | Metric | Definition | Computed by | Result |
|---|---|---|---|---|
| M1 | Agreement with the author's labels | per criterion: fraction of submissions where the judge's score equals the label (exact match on 0/2/4); also report mean absolute error | `benchmark/run_benchmark.py` compares run 1 to `ground_truth.json` per submission; the aggregate across submissions is **not computed by any script yet** (`TODO(build)`) | TODO(measure) |
| M2 | Stability across 3 runs | per criterion: fraction of the 3 runs equal to the most common value (`_exact_agreement`); report the minimum over submissions as well as the mean | `benchmark/run_benchmark.py` (`self_consistency`) | TODO(measure) |
| M3 | JSON validity | first-attempt valid rate, corrective-retry rate (`attempt 2` / `attempt 1` records), flagged-after-retry count | `_gateway_stats` in `benchmark/run_benchmark.py`, key `_gateway` of the results file | TODO(measure) |
| M4 | Evidence validity | share of verdicts with at least one `unmatched_quote` (fabricated quote) | `evidence_failures` printed per run; the share is **not aggregated yet** (`TODO(build)`) | TODO(measure) |
| M5 | Cost | tokens in / out per graded submission, times the provider's price per token | tokens: `_gateway_stats`; prices: **not in the repo**, `TODO(verify)` from the provider's price page at the time of the run | TODO(measure) |
| M6 | Latency | `elapsed_s` per call | `CallRecord.elapsed_s` (not summarised yet) | TODO(measure) |
| M7 | Judge versus executed tests (C8) | agreement and Cohen's kappa between `llm_correctness_opinion >= 3` and the hidden-test outcome | needs real attempts with `test_results`; `TODO(build)` after the benchmark | TODO(measure) |

Sub-questions the numbers must answer (decide the thresholds BEFORE seeing results and write them
here; none is chosen yet): the minimum acceptable M1, M2 and M3; whether the cheap tier is enough
for the Feedback Agent; whether the reference-solution option changes M1.

## 4. Results

### 4.1 Candidates and prompt version

TODO(measure): model ids actually served (`CallRecord.model`, not the configured name; the fallback
chain can substitute), `PROMPT_VERSION`, date, provider.

### 4.2 Table

| Model | M1 agreement | M2 stability | M3 first-attempt valid | M3 retry rate | M4 fabricated-quote share | M5 tokens in / out per submission | M5 cost per 100 submissions |
|---|---|---|---|---|---|---|---|
| TODO(measure) | TODO | TODO | TODO | TODO | TODO | TODO | TODO(verify prices) |

### 4.3 Per-criterion detail

TODO(measure): the four criteria separately. The rubric's `idiomatic` criterion is "Idiomatic
Spark/SQL" but the benchmark files are pandas/Python (open question in `agents/PROMPT_CHANGELOG.md`
v1): report it, do not average it away.

## 5. Recommendation

TODO(decide): one line per agent (Code Agent, Feedback Agent), the evidence for it (cite the rows
above), and what would change the answer. A disappointing measured result is a finding, not a
failure (CLAUDE.md §10): write it down as it is.

## 6. Threats to validity (known before running)

* One task, five submissions, one labeller: small and not independent. Agreement numbers will have
  wide uncertainty; say so rather than hiding it.
* The labeller is also the author of the rubric.
* The synthetic fixture files were written to reproduce situations, not sampled from students.
* Provider fallback can change the serving model mid-run (check `CallRecord.model`).
* Prices change; record the date.
