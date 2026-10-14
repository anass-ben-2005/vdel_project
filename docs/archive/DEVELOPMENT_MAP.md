# DEVELOPMENT_MAP.md — VDEL Student-Side

> Produced by the §2 repository analysis pass. This is a **compression artifact** (§4.6):
> once this file exists, the analysis does not need to be repeated. Later sessions start
> here, not from the documents.
>
> **Provenance and its limit.** This map was produced by reading the nine project
> documents. The working source tree was **not available** at the time of writing.
> Everything below about "what the code does" is sourced from `explanation.md`, which is
> Tier 3 ground truth *as of when it was written*. Two claims must be re-verified against
> the live repo before this map is fully trusted — they are flagged **[VERIFY]** inline.
>
> Analysis date: 2026-08-10 · Documents read: all 9 in the project · Code read: none

---

## 0. The finding that should shape the whole setup

The hard part of this project is **not** implementation difficulty. Most of the code for
M0–M4 already exists inside `VDEL_Modules_1_2_Build.md` and `VDEL_Modules_3_9_Build.md`.
`BUILD_PLAN.md` says it outright: *"Your job is largely to transcribe, wire together, and
verify — not to design from scratch."*

The hard part is **specification drift**, and this project has already been damaged by it
three separate times:

| Incident | What happened | Cost |
|---|---|---|
| Invented schema | An earlier session invented `problems` / `attempts` tables and a public-dataset data source that appear nowhere in the design | A full session to undo; `START_HERE.md` exists because of it |
| Pass 1 BKT bug | The Bayesian update used the same numerator for the pass and fail branches. `update(prior, fail)` and `update(prior, pass)` returned the **identical** posterior. The model was structurally incapable of learning | Silent — the code ran, looked plausible, and passed its own tests |
| Pass 1 fabricated data | `duration_s = run_number * 60`; lint counts = `commit_count // 20`, with no linter ever run. Written to the database as if measured | Would have invalidated every downstream number |

Every one of these was code that **ran without error, passed its own tests, and read as
internally coherent**. None of them were caught by reading the code. They were caught by
(a) comparing against the source documents and (b) actually executing the code and
inspecting the numbers.

**Therefore the Claude Code setup's primary job is not to write code faster. It is to make
"did we check this against the spec?" a cheap, automatic, always-on question.** That single
decision drives the agent list (§1 below), the skills, the hooks, and the commit ritual. A
generic productivity setup would be the wrong setup for this project.

Second-order consequence, which the setup also has to serve: Anas has to **defend** this
work to the supervisor. Code he cannot re-derive by hand is code he cannot defend. So the
setup optimises for `Implementation + Understanding + Demonstrability` (§24), and the
verification discipline doubles as the learning mechanism — re-deriving a number by hand is
both the check and the lesson.

---

## A. Current state — what exists and what works

### A.1 Documentation layer (complete, high quality, already well-organised)

This is unusual and worth stating plainly: **the documentation system §10 asks for already
mostly exists.** The setup should extend it, not rebuild it in parallel.

| File | Role | Maps to setup-prompt section |
|---|---|---|
| `START_HERE.md` | Authority hierarchy across four tiers; navigation | — (no analogue; keep as-is) |
| `CLAUDE.md` | Condensed source of truth: scope, architecture, schemas, 12 invariants, domain reference, conventions. Auto-loaded every session | §12 project memory (partially) |
| `VDEL_Modules_1_2_Build.md` | Full design + code for Module 1 (7 variables) and Module 2 (telemetry) | §2 source spec |
| `VDEL_Modules_3_9_Build.md` | Full design + code for Modules 3–9 (memory, LLM selection, agents, Reviewer, backbone) | §2 source spec |
| `VDEL_v1_Execution_Plan.md` | Milestone plan M0–M7 with per-milestone DoD, risk register, cut policy | §13 roadmap |
| `BUILD_PLAN.md` | Ordered executable task list M0–M4 with DoD per milestone | §16 granularity |
| `vdel_complete_design_document.md` | Design rationale in five phases, glossary, "defend it" compendium | §24 understanding |
| `explanation.md` | What the code **actually does** today, file by file, plus a documented bug history | §10 file/function documentation |

**Implication for §3 (minimal setup):** do not create `docs/ARCHITECTURE.md`,
`docs/FILES.md`, or a "project memory" file that restates `CLAUDE.md`. Those jobs are done.
Only three documentation artifacts are genuinely missing — see §B.3.

### A.2 Code layer — M0 and M1 built and tested

Per `explanation.md`. **[VERIFY]** — confirm by running the §11 verification block on the
live repo before relying on any of this.

**M0 — Foundations (done).**
- `docker-compose.yml` — PostgreSQL 16 + pgvector. Includes a documented workaround for a
  local port-5432 conflict.
- `sql/01`–`sql/05` — all five DDL files. `traces` append-only is enforced by two Postgres
  `RULE`s that turn UPDATE/DELETE into silent no-ops **at the database level**, not by
  convention. `smoke_test.py` actually attempts both and asserts no effect.
- `system/db.py` — the single place `psycopg2.connect()` is called. Includes a workaround
  for locale-mangled psycopg2 error messages.
- `scripts/init_db.py` (idempotent, checked twice in CI), `scripts/smoke_test.py`.
- `.github/workflows/ci.yml` — smoke test on every push.
- `.env.example` committed, `.env` gitignored.

**M1 — Telemetry + Features (done).**
- `config/concepts.yaml` — the concept taxonomy with real IDs (`py.*`, `spark.df_basics`,
  `sql.joins`, `airflow.idempotency`, …), plus a validating loader.
- `collectors/collect_github.py` — the optimised collector (skip-if-present, incremental
  `since=`, rate-limit-header backoff, batched `execute_values`, per-repo try/except).
- `collectors/error_classifier.py` — precision-first rule table. Unmatched → `unclassified`,
  updates no mastery. `match_rate()` reports coverage.
- `variables/mastery.py` (V1: BKT + KT-IDEM + Jeffreys Beta posterior),
  `variables/habits.py` (V2 + V3), `variables/pace.py` (V4),
  `variables/error_response.py` (V5), `variables/error_frequency.py` (V6).
- `features/compute_features.py` — wires raw tables to the variable functions, with a
  watermark-based dirty-student filter for idempotency.
- `dags/vdel_pipeline.py` — `collect → compute_features → update_profiles`, third task a stub.
- `tests/` — including `test_sara.py` (the hand-computed worked example) and
  `test_pipeline_integration.py` (end-to-end, the most informative single test in the repo).
- Reported state: **64 passed, 1 xfailed**. **[VERIFY]**

### A.3 Two open findings already recorded — do not "fix" either casually

**Finding 1 — the Sara joins number does not reproduce, and cannot.**
The design document quotes `spark.joins: 0.47 (n=2)` after the sequence `[fail, pass]`
("fixed in 4h"). A brute-force sweep of `item_difficulty` across `[0,1]` with that exact
sequence yields **0.591 → 0.964** — the whole reachable range sits *above* 0.47. 0.47 is
reachable only via the opposite sequence `[pass, fail]` at difficulty ≈0.35, which
contradicts the narrative.

`spark.aggregation` reproduces exactly (`0.30 → 0.211 → 0.705 → 0.407` vs documented 0.40).

This is recorded as a strict `xfail` plus a companion test that fails if 0.47 ever *becomes*
reachable. **This is correct engineering and must not be "resolved" by tuning parameters to
hit the target.** It is an open question for the worked example's author: transcription slip,
or a slice taken at a different point in the sequence? Ask the supervisor. Presented properly,
this is a *strength* in a supervision meeting — "I found a discrepancy in the design's worked
example and pinned it with a test instead of hiding it."

**Finding 2 — V4 (Learning Pace) is structurally degenerate at n=1.**
V4 is framed cohort-relative (survival analysis against peer timings). With one student in
the cohort, there is no cohort. V2's Cronbach's-alpha composite gate has the same problem.
These are **not bugs** — they are variables whose signal is definitionally unavailable until
there is a cohort. Report them as such; do not invent a synthetic cohort to make them light up.

---

## B. Missing components — what still needs to be implemented

### B.1 Code that does not exist yet (all designed, none written)

| Component | Milestone | Design location | Why it matters |
|---|---|---|---|
| `memory/memory.py` | M2 | `Modules_3_9` | The only door to memory. `log_trace` (INSERT only), `get_profile`, `snapshot_profile`, `update_mastery`, `open_weakness`, `rebuild_from_traces` |
| `memory/sessionize.py` | M2 | `Modules_3_9` | 30-min inactivity grouping + compression stub |
| `memory/reflection.py` | M2/M5 | `Modules_3_9` | Weekly LLM slow path — needs `system/llm.py`, so effectively M3-gated |
| Fast-path wiring + recurrence rule | M2 | `Modules_3_9` | Classified CI run → trace → deterministic mastery update; ≥2 failures opens a structured weakness with lifecycle |
| `agents/echo_agent.py` | M2 | `Modules_3_9` | ~20 lines, rule-based, no LLM. The tracer bullet |
| `scripts/plot_mastery.py` | M2 | `BUILD_PLAN` 2.5 | Mastery evolution plotted **from the running system**, not a notebook |
| `scripts/prove_event_sourcing.py` | M2 | `BUILD_PLAN` 2.6 | The demo: truncate profile → replay traces → deep-diff → `IDENTICAL ✅` |
| `system/llm.py` | M3 | `Modules_3_9` | Provider abstraction, temp 0, pydantic + one corrective retry, token/cost logging, prompt-hash cache, `cohort_cost()` with retry rate in the formula |
| `benchmark/submissions/` (×5) | M3 | `BUILD_PLAN` 3.2 | clean / subtly-wrong / correct-but-inefficient / copy-paste-looking / broken |
| `benchmark/ground_truth.json` | M3 | `BUILD_PLAN` 3.2 | Intended per-criterion scores + one-line justification each |
| `benchmark/run_benchmark.py` | M3 | `BUILD_PLAN` 3.3 | 3 runs × candidates × 5 submissions; stability, JSON validity, ranking, cost |
| `benchmark/RECOMMENDATION.md` | M3 | `BUILD_PLAN` 3.4 | Signed off with the tutor-side collaborator; PDPA note; `verified as of <date>` |
| `agents/code_agent.py` | M4 | `Modules_3_9` | Replaces Echo internals; same interface |
| `agents/tools.py` | M4 | `BUILD_PLAN` 4.2 | ruff over Python, sqlfluff over SQL; findings enter prompt as verified facts |
| `agents/prompts.py` + CHANGELOG | M4 | `BUILD_PLAN` 4.3 | Every prompt element defends a named failure mode |
| `agents/validation.py` | M4 | `BUILD_PLAN` 4.4 | pydantic → one corrective retry → flag; `validate_evidence()` string-matches every quote against the submission. **The most important function in M4** |

Deferred by design, with named triggers (do **not** build): Performance Agent, Pedagogy
Agent, Reviewer, orchestrator, observability, Coach, Execution Agent, Data Quality Agent,
Spark event-log collector, IDE telemetry, question generation, knowledge graph, multi-agent
debate, embedding retrieval, webhooks, V7 Help-Seeking, EM-fitted BKT params, Cox PH for pace.

### B.2 Forbidden — three things that must never be built

Repeating these because each has already been attempted or proposed once:

1. **No `problems` / `attempts` tables.** The schema is fixed at `students / assignments /
   raw_commits / raw_workflow_runs / learner_features / traces / sessions / learner_profile`.
2. **No synthetic student generator.** The telemetry source is Anas's own GitHub repos via
   `config/roster.yaml`. Sara is a hand-computed *test fixture*, not a generator.
3. **No IBM CodeNet load.** Downloaded, held in reserve for a possible external-validation
   chapter. Out of scope now.

### B.3 Development-system artifacts that are genuinely missing

Exactly three. Everything else the setup prompt asks for is already covered by the existing
documents.

| Missing | Fills | Why it doesn't already exist |
|---|---|---|
| `docs/HANDOFF.md` | §12.1 session handoff record | Nothing today carries "where I stopped, what's half-done, which 3 files to open next" across a session boundary. This is the single highest-value addition |
| `docs/DECISIONS.md` | §12 architecture decision log | `CLAUDE.md` records decisions *already settled*. There is no append-only place for decisions made **during** the internship — and Anas will be asked to defend those |
| `docs/reading/` | §4.6 compression artifacts | Wide reads currently evaporate at the end of a session and get paid for again |

Plus `docs/STATUS.md` — a thin milestone/DoD status board. Arguably a subset of HANDOFF;
kept separate because DoD evidence is durable and handoff is volatile.

---

## C. Proposed independent development phases

### C.1 Recommendation in one line

**Keep the existing M2 → M3 → M4 sequence. Insert one short verification phase (M1.5)
before M2, and pull one M3 task (benchmark authoring) forward into M2's slack.**

That is a deliberately small change. `BUILD_PLAN.md`'s ordering is already correct on the
criteria §1 asks me to judge by, and rearranging a sound plan to demonstrate independent
thinking would be a cost with no benefit.

### C.2 The phases

| Phase | Content | Days | Independence | Demo strength |
|---|---|---|---|---|
| **M1.5** | Verification pass (new) | 0.5–1 | Total — reads only | Low, but it's the insurance |
| **M2** | Memory + Echo Agent | 5 | Depends on M1 only. **No LLM, no API cost, no network** | **Highest** |
| **M3** | LLM Gateway + Benchmark | 4 | Depends on M0 only — parallelisable | Medium (a measured matrix) |
| **M4** | Code Agent | 5 | Depends on M2 + M3 | High (the research result) |

### C.3 Why M1.5 exists — the one genuine addition

Half a day to a day, before touching M2, spent on:

1. Run the `explanation.md` §11 verification block. Confirm 64 pass / 1 xfail on **this**
   machine, today.
2. For each of V1–V6, open its paragraph in `VDEL_Modules_1_2_Build.md` and **re-derive one
   number by hand**. Six numbers, six formulas.
3. Record the result in `docs/reading/` as the first compression artifact.

**Why this is worth a day.** M2, M3 and M4 all sit on top of M1's numbers. The codebase has
been rewritten three times, the last time as a verbatim transcription of documents that
weren't available during the first two passes. Its correctness is *asserted* by
`explanation.md`, not *established by Anas*. Discovering a transcription error in week 3, from
the top of the M4 stack, costs days. Discovering it now costs an hour.

And it is simultaneously the best possible §24 exercise: after M1.5 Anas can answer "how does
BKT actually update?" with a worked example on a whiteboard, which is exactly the question a
supervisor asks.

**Timebox it hard.** If a formula doesn't reconcile in 30 minutes, log it in `DECISIONS.md`
as an open question and move on. M1.5 is a checkpoint, not a research project.

### C.4 Why M2 before M3 — reasoning against the criteria in §1

- **Educational value.** Event sourcing is the most conceptually transferable idea in the
  project. Understanding "traces are truth, profile is derived belief" is the thing worth
  learning here.
- **Implementation independence.** M2 needs nothing external. No API key, no model choice, no
  network, no cost. It cannot be blocked by a vendor.
- **Demonstrability.** The M2 DoD — wipe `learner_profile`, replay the traces, get a
  bit-identical profile back — is the single most persuasive 30 seconds available in this
  entire project. It proves auditability, which is *the sentence that governs every design
  choice* in `CLAUDE.md`. **Rehearse it.**
- **Technical dependencies.** M2 needs M1's classified events. Nothing else.
- **Time constraints.** If the internship collapses to half its length, M0+M1+M2
  demonstrated and documented is a coherent, defensible deliverable. M0+M1+M3 is a database
  and a model-selection memo — much weaker.
- **Independent validation.** `prove_event_sourcing.py` is a self-checking proof. No human
  judgement, no LLM variance.

### C.5 Why M3 second, and the one task to pull forward

M3 depends only on M0, so it *could* go anywhere. It goes second because model choice is the
**least reversible** decision in the project — every M4 prompt is tuned against a specific
model — and because `BUILD_PLAN` flags it as the natural split point with the tutor-side collaborator.

**Pull task 3.2 (author the 5 benchmark submissions) forward into M2's week.** Rationale:

- It is pure writing. No code, no dependencies, no API.
- It is the classic task that gets squeezed when M3 runs late, and squeezing it corrupts the
  benchmark — a rushed ground truth makes every later stability number meaningless.
- It has zero conflict risk with M2 (different directory, different mental mode).
- It is good "tired evening" work when the head isn't sharp enough for memory semantics.

### C.6 Why M4 last

M4 needs M2 (traces to write, mastery to update) and M3 (a gateway and a chosen model). It is
also the phase where the deliverable is a *measurement*, not a feature — and `BUILD_PLAN`
already says the right thing: if stability won't converge, **that is a finding to report, not
a failure to hide.** Guard the two-day prompt-iteration timebox.

---

## D. Dependencies

### D.1 Milestone graph

```
M0 Foundations ──┬──► M1 Telemetry+Features ──► M1.5 Verify ──► M2 Memory + Echo ──┐
                 │                                                                 │
                 └──► M3 LLM Gateway + Benchmark ──────────────────────────────────┤
                          (M0 only — parallelisable)                               │
                                                                                   ▼
                                                                            M4 Code Agent
```

### D.2 Code-level dependencies

| Component | Depends on | Contract it exposes |
|---|---|---|
| `system/db.py` | — | The only `psycopg2.connect()` |
| `collectors/collect_github.py` | `db.py`, `roster.yaml`, GitHub API | Rows in `raw_commits`, `raw_workflow_runs` |
| `error_classifier.py` | `concepts.yaml` | `(error_class, concept_id)` or `unclassified` |
| `variables/*.py` | **nothing** — pure functions, no I/O | Dicts, each carrying its observation count |
| `features/compute_features.py` | `db.py`, `variables/*`, classifier output | `learner_features` rows |
| `memory/memory.py` **(M2)** | `db.py`, `variables/mastery.py` | `log_trace`, `get_profile`, `snapshot_profile`, `update_mastery`, `open_weakness`, `rebuild_from_traces` |
| `agents/echo_agent.py` **(M2)** | `memory.py` | **The agent interface M4 must preserve exactly** |
| `system/llm.py` **(M3)** | provider SDK, `.env` | Validated structured output, cost log |
| `agents/code_agent.py` **(M4)** | `memory.py`, `llm.py`, `tools.py`, `validation.py` | Same interface as Echo |

### D.3 The three seams that carry integration risk

These are the interfaces to get right the first time; everything else is local.

1. **The agent interface** (defined by Echo in M2, honoured by Code Agent in M4). If Echo's
   signature is right, M4 is an internals swap and the plots, traces and mastery updates keep
   working untouched. If it's wrong, M4 becomes a refactor. **Design Echo's interface as
   though the Code Agent already existed.**
2. **`memory.py` as the only door.** Invariant 2. The moment one agent writes raw SQL to
   `traces`, the audit story is dead and `rebuild_from_traces` stops being a proof.
3. **`retrieval.py` — the tutor-side contract.** The boundary with the tutor-side. Not built, but
   its shape should be agreed early, because it's the one dependency outside Anas's control.

### D.4 External and human dependencies

| Dependency | Risk | Mitigation already in the plan |
|---|---|---|
| GitHub API rate limit | Medium | Five optimisations in the collector; incremental `since=` |
| LLM provider availability / pricing | Medium | Two providers behind `llm.py`; primary + fallback in RECOMMENDATION.md |
| Tutor-side collaborator (retrieval, RECOMMENDATION sign-off) | Medium | M3 is the designated split point; `retrieval.py` is a stub contract |
| The supervisor's weekly cadence | Low | The Tuesday-stop discipline |
| Cohort of one (V4, V2 alpha gate) | **Accepted** | Report as a structural finding, not a bug |

---

## E. Demonstration strategy — each component shown independently

Per §14, every component gets Objective / Input / Processing / Output / Test / Demo. The
recurring question is: *can I show my supervisor this works, on its own, in under two minutes?*

### M1.5 — Verification
- **Objective:** the M1 floor is trustworthy, and Anas can derive it by hand.
- **Input:** the module documents + the test suite.
- **Output:** `pytest -q` green (64 pass, 1 xfail) + six hand-derivations.
- **Demo:** whiteboard one BKT update end to end. This is what makes the viva easy.

### M2 — Memory + Echo Agent
- **Objective:** memory is event-sourced and the belief state is fully reconstructible.
- **Input:** classified CI runs from M1.
- **Processing:** trace appended → deterministic BKT update → profile mutated → recurrence
  rule opens a weakness at the second failure of a concept.
- **Output:** rows in `traces`, an updated `learner_profile`, `outputs/mastery_evolution.png`.
- **Test:** `prove_event_sourcing.py` — snapshot → `TRUNCATE learner_profile` → replay →
  deep-diff.
- **Demo (the headline):** *"Watch. I delete the entire profile. I replay the log. Same
  numbers, byte for byte. That's why I can defend any grade this system produces."*
  Then the mastery plot: *"and this curve came from the running system, not a simulation."*

### M3 — LLM Gateway + Benchmark
- **Objective:** the model decision was made on measured evidence, not vibes.
- **Input:** 5 authored submissions + `ground_truth.json`.
- **Processing:** 3 runs × candidates × 5 submissions at temperature 0.
- **Output:** the measured matrix — stability spread, JSON validity rate, ranking correctness,
  accuracy vs intended, cohort cost including retry rate.
- **Test:** re-running reproduces the matrix.
- **Demo:** the matrix plus the cost arithmetic. *"The cheaper model is more expensive once
  you price its JSON failures."* Cost reasoning lands well with supervisors.

### M4 — Code Agent
- **Objective:** an LLM judge whose reliability is measured, not assumed.
- **Input:** a submission + rubric + linter findings + memory slice.
- **Processing:** tools → assemble → one judge call at temp 0 → validate → commit.
- **Output:** a per-criterion verdict where every score carries a verbatim evidence quote.
- **Test:** 3 runs per submission; ≥80% exact agreement; `validate_evidence` rejects any
  fabricated quote.
- **Demo:** two moments. (1) Show a verdict, then Ctrl-F each quoted snippet in the actual
  submission — every one is really there. (2) Show the copy-paste-looking submission failing
  to fool correctness scoring. Then the stability table, honestly, whatever it says.

### The cross-cutting demo
Because every milestone writes to the same blackboard, the running demo is always available:
*"Here is a real commit from my own repo, here is the CI failure, here is the trace it wrote,
here is the mastery number that moved, and here is the paragraph in the design document that
says it should have moved by exactly that much."*

---

## F. Final integration strategy

Integration is nearly free here **because of an architectural decision already made**:
the blackboard. Agents never message each other; they read and write PostgreSQL. There is no
call graph to untangle, no message bus, no ordering problem. Integration means "another
writer appears," not "two components must be rewired."

Consequently, the §26 incremental integration sequence is:

```
M1 (features) + M2 (memory)          → the fast path closes        → integration test → commit
   ↳ proof: prove_event_sourcing.py passes with real collector data

M2 + M3 (llm gateway)                → reflection slow path        → integration test → commit
   ↳ proof: a weekly reflection writes a trace; cost is logged; temp 0 is enforced

M2 + M3 + M4 (code agent)            → Echo's internals swapped    → integration test → commit
   ↳ proof: the M2 mastery plot regenerates unchanged in shape; traces still replay identically

(deferred) + M5/M6                   → Reviewer aggregates ≥2 agents
```

**The integration test that matters at every step is the same one:** wipe
`learner_profile`, replay `traces`, deep-diff. If that still passes after a new writer joins,
the new writer respected event sourcing. If it fails, the new writer broke the audit story —
and it fails loudly, immediately, before anything is built on top of it.

That is a strong position: one cheap, deterministic test guards the project's central claim
at every integration boundary.

Per §4.2, integration is one of the moments where wide context reading is explicitly correct.

---

## G. Context map — the file that makes every later session cheap

This is the §2-G deliverable and the reason this document exists.

### G.1 Read in full, once, then never again

| File | When | After that |
|---|---|---|
| `START_HERE.md` | First session only | Superseded by this map |
| `CLAUDE.md` | **Every session — it's auto-loaded** | Always in context; never re-read manually, never paste it |
| This file (`DEVELOPMENT_MAP.md`) | Every session start | The map replaces the territory |
| `docs/HANDOFF.md` | Every session start | Rewritten every session end |

### G.2 Reference-only — open the section, never the file

**Never load these whole.** Each is 40–90 KB. Jump to the relevant section, read that section
in full (§4.4), and state which parts were not read.

| File | Open for | Typical slice |
|---|---|---|
| `VDEL_Modules_1_2_Build.md` | The variable formulas, the collector, the classifier | One variable's section |
| `VDEL_Modules_3_9_Build.md` | Memory, LLM gateway, the agents | One module's section |
| `explanation.md` | "What does the current code actually do?" | One `§7.x` subsection |
| `VDEL_v1_Execution_Plan.md` | Sequencing, risk register, cut policy | §5, §6 |
| `BUILD_PLAN.md` | The current milestone's task list + DoD | One milestone block |
| `vdel_complete_design_document.md` | **Only** before a supervisor meeting — the glossary and "defend it" answers | Glossary, or one justification |

### G.3 Ignore entirely for the rest of the project

| File | Why |
|---|---|
| `VDEL_v01_Plan.md` | **Actively dangerous.** Proposes the abandoned `problems`/`attempts` schema. This is the document that caused the first incident |
| `vdel_implementation_plan.md` | Superseded by the Execution Plan |
| `vdel_master_build_guide.md` | Superseded by the two Modules docs |
| `VDEL_Presentation.html` | Tone reference only, not a spec |
| `claude_code_internship_setup_prompt_v2.md` | Its output is the `.claude/` setup. Once that exists, the prompt is history |

**Rule:** if a session's reasoning starts leaning on any file in G.3, that is a signal
something has gone wrong. Stop and re-read `CLAUDE.md` §2.

### G.4 Code reading policy

| Directory | Policy |
|---|---|
| `variables/*.py` | **Read whole.** Small, pure, no I/O, and they are the math. Partial reads of formula code are how transcription errors survive |
| `memory/memory.py` (M2) | **Read whole** whenever touching memory. It is the only door; a partial read of the door is worthless |
| `collectors/`, `features/` | Read whole on first touch, then use the `docs/reading/` artifact |
| `sql/*.sql` | Read whole — they are short and they are the contract |
| `tests/` | Read the test being changed, plus `test_pipeline_integration.py` when a contract changes |
| `benchmark/submissions/` | Read only the one under discussion |
| Everything else | Reference-only |

**Threshold (the §4.4 number this project will use): read whole under 800 lines.** Above that,
read interfaces, entry points, and the sections the task touches — **and state explicitly which
parts were not read.** In practice almost every file in this repo is under 800 lines, so the
default is "read it whole."

### G.5 What a normal session actually loads

```
Auto:     CLAUDE.md                                    (~18 KB, cached, stable prefix)
Start:    DEVELOPMENT_MAP.md + docs/HANDOFF.md         (~2 KB of that is what changes)
Task:     the target file + its test + one doc section (~10–30 KB)
                                                        ─────────
                                                        well under 15% of context
```

Wide reads happen in a **sub-agent** (§4.5) and return ≤1500 words to the main thread. The
main conversation should rarely exceed 30% during implementation work. If it does, the task
was scoped too large — split it (§4.7).

---

## H. §27.1 — Recommended Claude Code structure

Everything marked **EXISTS** stays where it is. Everything marked **NEW** is genuinely
missing. Nothing here duplicates a job an existing document already does.

```
vdel-student-side/
│
├── CLAUDE.md                        EXISTS · Tier 1, auto-loaded. Add one short §11
│                                      pointing at .claude/ and docs/HANDOFF.md. That is
│                                      the ONLY edit — CLAUDE.md is the cached stable
│                                      prefix (§4.9); churning it costs money every turn.
├── START_HERE.md                    EXISTS · authority hierarchy. Unchanged.
├── BUILD_PLAN.md                    EXISTS · the ordered task list. Unchanged.
├── VDEL_*.md, vdel_*.md             EXISTS · move under docs/spec/ if you want a tidy root;
│                                      cosmetic only, and it breaks existing cross-references,
│                                      so the default recommendation is: leave them.
│
├── .claude/
│   ├── settings.json                NEW · committed. Hooks + permission rules. The
│   │                                  destructive-git guard lives here.
│   ├── settings.local.json          NEW · gitignored. Personal overrides, model prefs.
│   │
│   ├── agents/                      Three sub-agents. Each is a context firewall (§4.5).
│   │   ├── explorer.md              NEW · Sonnet. Reads wide, returns ≤1500 words of
│   │   │                              structured findings. The generic firewall.
│   │   ├── spec-verifier.md         NEW · Sonnet. THE project-specific agent. Given a file
│   │   │                              or function, finds its paragraph in the module docs
│   │   │                              and reports agreement / divergence with both texts
│   │   │                              quoted. This is the direct countermeasure to the
│   │   │                              three drift incidents in §0.
│   │   └── reviewer.md              NEW · Sonnet (Opus for cross-component). Reviews a diff
│   │                                  against the 12 invariants and flags doc drift.
│   │
│   ├── skills/                      Two skills. Model-invoked procedures with real mechanics.
│   │   ├── compress-read/SKILL.md   NEW · turns a wide read into docs/reading/<date>-<topic>.md
│   │   │                              in the §4.6 six-field shape. Triggers after any
│   │   │                              exploration pass.
│   │   └── dod-evidence/SKILL.md    NEW · runs a milestone's DoD command, captures the ACTUAL
│   │                                  output, appends it to docs/STATUS.md. Never claims a
│   │                                  DoD passed without pasted evidence.
│   │
│   ├── commands/                    Three slash commands. User-invoked rituals.
│   │   ├── session-start.md         NEW · loads HANDOFF + git status + names the next
│   │   │                              smallest task + states this session's context budget.
│   │   ├── session-end.md           NEW · rewrites HANDOFF, appends to DECISIONS if a stable
│   │   │                              decision was made, confirms the tree is clean.
│   │   └── commit.md                NEW · the §8 ritual: diff → tests → docs → 7-point
│   │                                  explanation → conventional commit.
│   │
│   └── hooks/
│       ├── guard_destructive.sh     NEW · PreToolUse. Blocks force-push, history rewrite,
│       │                              and any UPDATE/DELETE/TRUNCATE aimed at `traces`.
│       └── lint_on_edit.sh          NEW · PostToolUse. ruff on a touched .py. Report only,
│                                      never auto-fix (silent edits break trust in the diff).
│
├── docs/
│   ├── DEVELOPMENT_MAP.md           NEW · this file. The §2 output and the standing context map.
│   ├── HANDOFF.md                   NEW · the §12.1 record. Volatile, ~1 page, rewritten
│   │                                  every session end. The single highest-value addition.
│   ├── DECISIONS.md                 NEW · append-only ADR log for decisions made DURING the
│   │                                  internship. One entry ≈ 8 lines. This is the file that
│   │                                  makes the viva easy — it is a ready-made "why did you
│   │                                  do it that way?" answer sheet.
│   ├── STATUS.md                    NEW · milestone board with pasted DoD evidence and dates.
│   ├── explanation.md               EXISTS · move here. The §10 file/function documentation.
│   │                                  Updated in the same commit as the code it describes.
│   └── reading/                     NEW · §4.6 compression artifacts.
│       ├── README.md                NEW · the six-field template + naming convention.
│       └── 2026-XX-XX-<topic>.md    NEW · one per wide read.
│
└── (source tree unchanged — sql/ config/ collectors/ variables/ features/
     memory/ agents/ system/ benchmark/ dags/ scripts/ tests/)
```

**Total new components: 3 agents, 2 skills, 3 commands, 2 hooks, 6 documentation files.**
Every one of them is justified against a specific failure this project has actually
experienced or a specific section of the setup prompt. Nothing is there because it is
standard practice.

### What was deliberately NOT created, and why

| Not created | Why not |
|---|---|
| An **architect / planner agent** | Planning needs the raw material *afterwards*, to keep editing. §4.5 says explicitly: don't use a sub-agent to summarise something you'll immediately need in full. Planning happens in the **main thread on Opus**. A planner sub-agent would hand back a summary and throw away exactly what the next step needs |
| An **implementation agent** | Implementation is what the main thread does. Delegating it adds a context boundary in the one place where continuity is the whole point |
| A **git agent** | Git is a deterministic ritual, not a reasoning task. It belongs in `/commit`, which costs nothing when unused |
| A **documentation agent** | Doc updates are small, local, and must land in the same commit as the code. A separate agent makes that harder, not easier |
| `docs/ARCHITECTURE.md` | `CLAUDE.md` §4 already is it |
| `docs/MEMORY.md` | `CLAUDE.md` already is long-term memory. A second file would drift from the first, and then which one is true? |
| A **multi-part-output skill** | §19: if an instruction can live in the project instructions, it should. This becomes ~15 lines in `CLAUDE.md` §11 |
| Any **plugin** | See Part 5. Short answer: none needed |

---

## I. What Part 1 does not yet answer

Deliberately deferred to later parts, so nothing here is half-stated:

- Part 2 — the three agents in full, with context policies and return-payload caps; model routing.
- Part 3 — the two skills and the three commands, in full; the task→commit workflow.
- Part 4 — memory mechanics, the documentation system, the context strategy, the multi-part conventions.
- Part 5 — hooks, plugins, the git workflow, the detailed roadmap, cost optimisation, and installation.

---

## J. Two things to verify against the live repo before trusting this map

1. **[VERIFY]** Run the `explanation.md` §11 block. Confirm the test count (64 passed,
   1 xfailed) and that `init_db.py` is idempotent on this machine today. If the numbers
   differ, `explanation.md` has drifted from the code and Tier 3 needs updating **before**
   M2 starts.
2. **[VERIFY]** Confirm the actual directory listing matches `CLAUDE.md` §5. If files exist
   that appear in neither `CLAUDE.md` §5 nor `explanation.md` §2, they are drift — identify
   them and either document or delete them before building on top.
