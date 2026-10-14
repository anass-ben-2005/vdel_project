# VDEL — Deep Redesign & Technical Critique

### A critical review of the system, the 19 Aug redesign, and the eight new requirements

*Reviewed against: `START_HERE.md`, `CLAUDE.md`, `BUILD_PLAN.md`, `VDEL_v1_Execution_Plan.md`, `VDEL_Modules_1_2_Build.md`, `VDEL_Modules_3_9_Build.md`, `vdel_complete_design_document.md`, `explanation.md`, `SESSION_SUMMARY.md`, `SESSION_SUMMARY_M3.md`, and the 19 Aug design-review record.*

---

# 1. Executive Summary

## 1.1 The finding that reorders everything else

Before any redesign: **the system has never run on real data.** `SESSION_SUMMARY_M3.md` records blocker **D-006** — no `config/roster.yaml`, no `GITHUB_TOKEN`, therefore no telemetry anywhere. `scripts/prove_event_sourcing.py` prints `NOTHING TO PROVE` because there are zero real traces to wipe and replay. M1 has three DoD clauses never executed; M2 is code-complete but undemonstrated.

Every requirement in the new brief — semantic code comparison, duration tracking, notebooks, RAG — is downstream of data that does not yet exist. **Fixing D-006 outranks all eight requirements.** A system that grades brilliantly on zero submissions is worth less than one that grades crudely on twenty.

## 1.2 Four of the eight requirements assume a platform you have not built

The brief asks me to review the *"Backend, Frontend, Student submission system, Authentication/user data."* I grepped the entire project for any trace of these. There is **no frontend, no web server, no API layer, no authentication, and no submission system**. VDEL is a batch Python process plus PostgreSQL that reads the GitHub API on a schedule. There is nothing for a student to log into.

This is not a criticism of the architecture — the GitHub-native design is a good decision that avoids an enormous amount of work. It is a criticism of the requirements, and it changes two answers materially:

- **Requirement 4** (timer starts when the student *opens* the assignment) cannot be satisfied as literally written without building a web application or an IDE plugin. Something must observe the opening. Nothing currently can. §7 gives you three implementable alternatives and recommends one.
- **Requirement 5** (notebook interface) is a request to replace your delivery mechanism with a hosted service. §8 recommends **dropping it** and solving the underlying concern — which is real — with about forty lines of diff logic.

## 1.3 The headline judgements

| Requirement | Verdict |
|---|---|
| **2. Conceptual code comparison** | ✅ Right instinct, wrong mechanism. Surface similarity is correctly rejected — but "let the LLM judge concepts" is *also* wrong. Use **differential testing for the verdict, LLM for the explanation**. §6 |
| **3. Variables & data model** | ✅ Needs real surgery. Two variables should be demoted, one deleted, three re-grained, four added. §10–11 |
| **4. Assignment duration** | ⚠️ Cannot be built as written. Use **git-native session reconstruction** (a standard learning-analytics method) into the `sessions` table you already designed. §7 |
| **5. Notebook interface** | ❌ **Drop it.** Domain mismatch, infrastructure cost, breaks your telemetry. The real concern is solved by diff-scoping. §8 |
| **6. RAG / chatbot** | ⚠️ Mostly drop. RAG for grading: no. RAG for resources: unnecessary at your corpus size — use SQL. Chatbot: **drop, and note it directly contradicts the no-AI assignment policy the supervisor set.** §9 |
| **7. Architecture review** | ✅ The blackboard core is sound and survives. The assessment layer needs replacing. §13 |
| **8. Evidence** | Provided throughout, with the specific claim each source supports. §17 |

## 1.4 The single most valuable change

Requirement 2 asks for conceptual equivalence. The literature is unambiguous that this is **undecidable in general** — <cite index="72-1">detecting true semantic similarity is undecidable</cite>, and <cite index="81-1">the intuitive definition of a clone is undecidable precisely because it rests on code equivalence; there is no universally accepted, decidable definition</cite>.

The tractable substitute is **behavioural equivalence: run both implementations on the same inputs and compare outputs.** This is not a compromise — for a student assignment it is *closer to what you actually mean* than any conceptual judgement, because "does it do the same task" is operationally "does it produce the same results."

That single change cascades: it gives you objective ground truth, it lets you validate your LLM judge for the first time, it makes "Cannot Determine" a principled verdict rather than a hedge, and it removes the need for the LLM to make the one judgement it is least reliable at.

---

# 2. Current Design Critique

## 2.1 What is genuinely strong — and must not be lost in the redesign

I am listing these first because a redesign brief invites over-correction, and there are four things here that are better than most production systems.

**Event sourcing with a replayable profile.** `traces` is append-only; `learner_profile` is derived; wipe the profile, replay, get it back. This is the reason your grades are auditable rather than merely explained after the fact. Almost nobody in ed-tech does this. **Preserve absolutely.**

**Deterministic-first agent skeleton.** `TOOLS → ASSEMBLE → JUDGE → VALIDATE → COMMIT`, with the LLM as one stage in the middle rather than the whole thing. This principle is what saves you from most of the new brief's temptations.

**Evidence string-matching against the submission.** A fabricated quote *rejects the verdict* — a mechanical hallucination check, not a prompt asking the model nicely. This matters more now, not less: the feedback literature repeatedly flags that <cite index="132-1">LLM-generated feedback may include overly detailed guidance, complete solutions, or hallucinated issues</cite>.

**BKT over DKT, chosen for auditability, with the upgrade ladder written down.** The choice is revisitable rather than final, and the reasoning is defensible under questioning.

**And the governance discipline itself.** `START_HERE.md` exists because *"an earlier session invented database tables and a data source that contradicted the actual module documents."* That is an unusually mature response to an unusually common failure. Which brings us to:

## 2.2 The redesign is about to repeat the exact accident the project already suffered

`START_HERE.md`, in bold:

> *This project was already damaged once by an AI inventing a `problems`/`attempts` schema that didn't exist anywhere in the actual design. The fix cost a full session.*

`CLAUDE.md` §2, also in bold:

> *Do not add `problems` or `attempts` tables.*

The 19 August design review decided to add an attempts table. **That decision is correct** — per-attempt tracking is exactly what the new assessment model requires. But it is now in direct, unrecorded conflict with two governing documents, one of which is auto-loaded into every Claude Code session.

If you do not resolve this in writing, one of two things happens: Claude Code refuses the work and asks you to confirm every time, or it complies and the project's documentation silently becomes a lie. Both are bad. §12 gives the fix, which takes fifteen minutes.

**This is the most urgent non-technical item in this document.**

## 2.3 The assessment layer was designed for a different assignment format

The seven variables were built for multi-day, multi-file, self-authored repository work. The gap-fill format is short, small and single-sitting. Four variables have formulas that produce wrong numbers under the new format, and the failures are silent — you get well-formed values with confidence intervals and observation counts that are systematically incorrect. Full analysis in §10.2.

## 2.4 The current comparison approach is the weakest component

The design review settled on "LLM judges similarity between student code and master code." Three problems:

1. **Wrong construct.** Similarity ≠ correctness. A correct solution can diverge structurally.
2. **The transcript's version is worse than the notes suggest** — it was described in terms of *"the probability of the word"* being similar. Token-level similarity over a five-line snippet is dominated by identifier names; `for i in range(...)` versus `for attempt in range(...)` would score as materially different.
3. **It contradicts your own analysis.** `VDEL_Modules_3_9_Build.md` §D.3 supplies the reference solution to the Code Agent and explicitly flags *"the anchoring-bias risk,"* planning a with/without ablation. The redesign makes anchoring the primary signal.

## 2.5 The specification set has known internal contradictions

`SESSION_SUMMARY_M3.md` documents that the cache key has **four different definitions** across four documents, and that a docstring contradicts the code directly beneath it. Similar failures are logged as D-007 (BKT update returning identical numbers for pass and fail) and D-008 (schema drift).

This is a *documentation-integrity* problem, and it compounds with every redesign. A single `DECISIONS.md` with ADR entries is the fix, and it is cheaper than one more session spent reconciling four documents by hand.

---

# 3. What Should Be Removed

| # | Remove | Why | Risk of removal |
|---|---|---|---|
| R1 | **Token / word / embedding similarity as a correctness signal** | Measures the wrong construct; dominated by identifier names at snippet scale | None — replaced by something strictly better |
| R2 | **The notebook proposal** | Domain mismatch, requires hosting, destroys your git-diff telemetry (§8) | None — the underlying concern is solved differently |
| R3 | **The RAG chatbot / AI teaching assistant** | Contradicts the no-AI-during-assignments policy; needs a frontend; wrong product (§9) | None now. Revisit post-thesis |
| R4 | **RAG as a grading input** | Adds a failure mode (bad retrieval → bad grade) for no accuracy gain | None |
| R5 | **V3 Effort Regulation as a *scored* variable** | Its own docs say it "never touches grades"; returns `None` on short tasks; unvalidated at n=1 | Low — keep as an unscored diagnostic |
| R6 | **The Cronbach's-alpha composite gate in V2** | Returns `None` below 10 students, so the composite is dead code in every foreseeable run | None — report components instead |
| R7 | **`items` as a table separate from assignment variants** | Redundant once variants exist; two tables modelling one concept | Low |
| R8 | **The "Shuffling Agent" as an agent** | It is a seeded function. Calling it an agent is a credibility risk under questioning | None — rename only |
| R9 | **`cohort_censoring_rate` / cohort-median pace as *active* code** | Requires a cohort you do not have. Keep the function, disable the path, label cold-start | None |
| R10 | **The LLM narrative half of the Reviewer** *(defer, not delete)* | Keep the Python arithmetic — that is the explainability artefact. The prose is optional | Low |

**Not removed, despite the brief inviting it:** the seven-variable framework, event sourcing, BKT, the blackboard architecture, the LLM Gateway, pgvector (installed, unused, harmless), and the Code Agent's anchored rubric. The brief says *"do not preserve variables simply because they already exist."* Agreed — and equally, do not delete things because a redesign prompt invited deletion. Each of these earns its place on its merits.

---

# 4. What Should Be Changed

Each entry follows **Current → Proposed → Why → Evidence → Impact.**

## C1. Correctness signal: LLM judgement → executed tests

**Current.** An LLM reads student code and master code and judges whether they match.
**Proposed.** Instructor-authored hidden tests execute in GitHub Actions; pass/fail is the correctness ground truth. The LLM never decides correctness.
**Why.** GitHub Actions already executes your students' code — you wrote the workflow, it installs requirements and runs pytest, and `raw_workflow_runs.conclusion` exists because of it. The premise that "the system cannot execute code" is false; what you lack is *in-process* execution, which is a much smaller limitation.
**Evidence.** <cite index="49-1">nbgrader's design pairs solution regions with hidden test cells — the instructor notebook marks solutions with `### BEGIN SOLUTION` and tests with `### BEGIN HIDDEN TESTS`, and the student version is generated from it with solutions stubbed and hidden tests stripped.</cite> <cite index="58-1">Its autograding guidance — test each function in isolation so a failure localises to one part of the problem — maps directly onto per-gap diagnosis.</cite>
**Impact.** Objective ground truth. Enables judge validation (§4/C8). Removes the highest-variance component from the grading path. Roughly one test module per assignment.

## C2. Item identity: assignment → variant

**Current.** `items.item_id = assignment_id`; BKT/KT-IDEM conditions on per-item difficulty.
**Proposed.** `variant_id = sha1(assignment_id ‖ sorted(gap_ids) ‖ master_version)`.
**Why.** Under randomised gaps, two students "attempting the same item" attempt different problems with different difficulties. `DifficultyEstimator` pools their outcomes and produces the average of two unrelated things, which then conditions guess/slip for both. KT-IDEM exists to model per-item difficulty; randomising the item while fixing the ID removes the property it models.
**Evidence.** The randomised-assessment literature treats this as a first-order concern — PrairieLearn's research catalogue includes work specifically on *reducing difficulty variance in randomised assessments*, and <cite index="24-1">PrairieLearn persists each student's generated variant rather than regenerating it, so an instance is stable and reconstructible.</cite>
**Impact.** Prevents silent corruption of every mastery estimate. One column and a hash function.

## C3. Gap selection: random → adaptive-then-random

**Current.** Uniform random line selection.
**Proposed.** Select the *concept* by lowest BKT mastery among the assignment's tagged concepts; select the *variant* uniformly among templates tagged with that concept. Fall back to uniform when `n_obs < 3` everywhere.
**Why.** You have built a system whose entire purpose is a per-concept mastery estimate, and then generate assignments ignoring it. Concept-adaptive selection serves pedagogy; within-concept randomness still prevents student-to-student copying. Both goals, no conflict.
**Evidence.** <cite index="4-1">Ericson defined inter-problem adaptation as setting the next problem's difficulty from the learner's performance on the last one</cite>, and <cite index="8-1">found that adaptation helped more learners successfully solve the problems</cite>.
**Impact.** Converts the contribution from "an LLM grades code" (crowded) to "knowledge-tracing-driven adaptive fading" (citable lineage, defensible novelty). Two lines of selection logic.

## C4. Static analysis: whole-file → gap-scoped

**Current.** `ruff` runs on the committed file; all findings attributed to the student.
**Proposed.** Run linters on the full file (parsing needs context), then **filter findings to line ranges inside gap regions.** Same for `sqlfluff`. Same for the `changed_loc` denominator.
**Why.** The student commits master code plus their gaps. The master's violations swamp the student's, so V2 stops varying with student behaviour and becomes a per-assignment constant measuring the instructor.
**Impact.** Fixes a fairness bug, not merely a metrics bug. You already know the gap line ranges — that is what the gap spec is.

## C5. Duration: release→pass → session-reconstructed time-on-task

**Current.** `pace = f(time_to_pass_h / cohort_median_h)`, clock from `assignments.released_at`.
**Proposed.** Reconstruct sessions from commit timestamps with an inactivity threshold; sum session lengths per attempt. Full design in §7.
**Why.** With simultaneous release of a project's assignments, the pace clock for assignment 7 has been running for days while the student worked on 1–6. Every student is reported as catastrophically slow on later stages. Separately, on a 25-minute task with a cohort median of 0.4h, a coffee break moves the score by a quarter of the scale.
**Evidence.** <cite index="121-1">The WeBWorK log analysis uses exactly this algorithm: logins and submissions are activity events; a session is a run of events with no gap exceeding an inactivity threshold; session length is first-to-last event, and total assignment time is the sum over sessions.</cite>
**Impact.** Satisfies Requirement 4 without building a web app.

## C6. Assignment granularity: repository → file, then function

**Current.** One repo = one assignment. Two assignments total.
**Proposed.** Project → assignments (per file) → gaps (per function/region), each concept-tagged.
**Why.** More, smaller, concept-tagged items multiply observations per concept — BKT is observation-hungry and this is the one change that makes your estimates estimable at all. **This is the strongest genuine argument for the whole redesign and nobody made it in the review.**
**Impact.** ~4× observations per concept. Also makes weakness attribution possible at the granularity the supervisor asked for.

## C7. Concept tags: assignment-level → gap-level

**Current.** `assignments.concepts[]`.
**Proposed.** Tags on the gap; `assignments.concepts[]` becomes the derived union.
**Why.** A retry loop and a Spark aggregation sit in the same file under the same assignment-level tags. When the student fails you cannot say which concept failed — and the entire diagnostic pitch depends on being able to.
**Impact.** Derived-not-authored means it can never drift out of sync.

## C8. Judge validation: benchmark-ranking appeal → measured agreement

**Current.** "DeepSeek is ranked #1 for coding, so it is the judge."
**Proposed.** Report agreement between the LLM's correctness score and executed test outcomes: *"judge–ground-truth agreement was __%, Cohen's κ = __."*
**Why.** Your risk register lists *"no instructor-graded reference set → cannot compute Cohen's κ."* C1 removes that constraint. You correctly identified in the review that the ranking argument is weak; this replaces it with a measurement.
**Evidence.** The autograding literature treats testing-based grading as the reference against which other methods are assessed — <cite index="90-1">the EPFL classroom deployment ran program-verifier equivalence checks *alongside the existing testing-based grading infrastructure*</cite>, using tests as the baseline.
**Impact.** Converts a systems demo into a research result, at the cost of running one correlation.

## C9. Judge model must sit outside the candidate set

**Current.** DeepSeek is both a grading candidate and the proposed judge.
**Proposed.** Judge is a different family from every candidate. Nemotron qualifies.
**Why.** Self-preference contamination — LLM evaluators have a documented tendency to favour their own generations.
**Impact.** **This is the real methodological reason to prefer Nemotron, and it is far better than "it's free."** Say it that way.

## C10. "Analysis Agent" → "Feedback Agent" fed a pre-computed diagnosis

**Current.** An agent that counts attempts, finds the weak stage, and writes feedback.
**Proposed.** A deterministic diagnosis function produces `{weakest_concept, attempts_per_stage, recurrence_flags, failing_tests}`; the LLM receives that plus the code and writes only the explanation.
**Why.** Four of its seven listed jobs are `GROUP BY`. Your own invariant: *never pay an LLM for what a free tool does perfectly.*
**Impact.** Smaller prompt, cheaper, more reliable, and the diagnosis becomes auditable independently of the LLM.

---

# 5. What Should Be Added

| # | Add | Purpose | Cost |
|---|---|---|---|
| A1 | **Hidden test harness** — `tests/hidden/` per assignment, injected in CI | Ground-truth correctness (C1) | ~1 module/assignment |
| A2 | **Differential test runner** — execute student vs master on generated inputs, capture divergences | The equivalence verdict (§6) | ~150 LOC |
| A3 | **Gap marker parser** — nbgrader-style `# @gap:` annotations → student file + gap catalogue + concept map | One master file as single source | ~120 LOC |
| A4 | **Deterministic gap generator** — seeded, adaptive-then-random, persisted | Variants (C2, C3) | ~80 LOC |
| A5 | **Out-of-scope edit detector** — diff committed file vs released file; flag edits outside gaps | Replaces the notebook (§8); new integrity signal | ~40 LOC |
| A6 | **Session reconstructor** — commit stream → sessions with inactivity threshold | Duration (§7) | ~60 LOC |
| A7 | **Curated `resources` table** — 20–40 rows keyed by `concept_id` | Kills URL hallucination; replaces RAG (§9) | one afternoon |
| A8 | **`DECISIONS.md`** — ADR log, Tier 0 authority | Resolves the governance conflict (§12) | 15 min |
| A9 | **Judge-validation script** — correlate LLM correctness vs test outcomes | The research result (C8) | ~50 LOC |
| A10 | **`vdel` CLI** *(optional)* — `start` / `submit`, writes session heartbeats | Sharper duration; still no server | ~100 LOC |

**Deliberately not added:** vector store for RAG, chatbot, web frontend, authentication, IDE plugin, notebook hosting, symbolic execution, formal verifier. Each has a named trigger in §15.

---

# 6. Code Concept/Functional Comparison — Redesign

This is the centre of the brief, so I will be blunt about where it is right and where it is wrong.

## 6.1 The brief is right to reject surface similarity

Ruling out word, variable-name, syntax, structure and workflow similarity is correct. Those measure *how* code was written, not *what it does*. A student who writes a correct list comprehension where the master used a loop should not be penalised.

## 6.2 The brief is wrong that an LLM should render the conceptual verdict

Two independent problems.

**First: the target is undecidable.** <cite index="72-1">Detecting true semantic similarity is undecidable in general.</cite> <cite index="81-1">Even the intuitive definition of a clone is undecidable because it rests on code equivalence, and there is no universally accepted, decidable definition.</cite> Any system claiming a conceptual-equivalence verdict is producing an approximation; the honest question is *which* approximation and what evidence backs it.

**Second: LLMs are unreliable at exactly this.** <cite index="67-1">A 2026 systematic study of state-of-the-art semantic (Type-4) clone detectors found it unclear whether their high benchmark scores reflect genuine ability to capture semantic equivalence or merely the exploitation of dataset-specific patterns</cite> — the authors <cite index="64-1">designed eight clone operators to test whether detectors remain robust under lexical and syntactic variation</cite>, precisely because benchmark performance was not trusted to generalise. And <cite index="77-1">work on what LLMs capture about functional equivalence frames it as lying on a spectrum, since different programs can compute the same function in very different ways.</cite>

An LLM asked "are these conceptually equivalent?" produces a fluent verdict with no evidence behind it. That is the same failure class your own invariant 6 was written to prevent.

## 6.3 What "same underlying task" actually means, operationally

For a student assignment, **two implementations do the same task if they produce the same outputs and effects on the same inputs.** This is behavioural equivalence, and it is testable. It is not a lesser substitute for conceptual comparison — for grading purposes it is a *sharper* definition, because it is falsifiable.

The literature converges here. <cite index="69-1">Semantic equivalence is undecidable, but a reasonable approximation is obtainable by combining static and dynamic analysis</cite> — that work extended the input-output notion of observable behaviour to include a method's persistent effects on the heap, which matters for your domain, where a `load.py` gap writes to a database rather than returning a value. <cite index="70-1">HyClone takes the same route, explicitly bridging LLM understanding with dynamic execution for semantic clone detection.</cite>

## 6.4 The proposed architecture: a three-layer cascade

```
┌─ LAYER 1 · DIFFERENTIAL EXECUTION ─────────────── deterministic, evidence-producing
│  Run student gap + master gap on the SAME generated inputs.
│  Compare returned values, and DB/file effects for side-effecting stages.
│  Output: agreement rate, plus concrete counterexample inputs where they diverge.
│
├─ LAYER 2 · PROPERTY & METAMORPHIC CHECKS ──────── deterministic, for untestable stages
│  When there is no single right output (network I/O, nondeterministic ordering):
│  assert invariants — schema preserved, row count relation, idempotency,
│  retry-count bounded, no data loss. Hypothesis generates the inputs.
│
└─ LAYER 3 · LLM ADJUDICATION & EXPLANATION ─────── judgement, grounded in Layer 1/2 output
   INPUT: both implementations + the CONCRETE COUNTEREXAMPLES from Layer 1.
   JOB:   (a) classify each divergence as meaningful or incidental
          (b) explain it conceptually in language a student can act on
          (c) suggest an improvement
   NOT ITS JOB: deciding whether a divergence exists. Layer 1 decided that.
```

The inversion is the point. The LLM is not asked *"are these the same?"* — it is told *"they differ on input `{"rows": [], "date": "2024-02-30"}`; the student returns `[]` and the master raises `ValueError`. Is that meaningful, and how do you explain it?"* That question an LLM answers well, and it cannot hallucinate a difference that does not exist, because the difference arrived as evidence.

## 6.5 Verdict mapping — earned, not asserted

| Verdict | Condition |
|---|---|
| **Equivalent** | All hidden tests pass **and** differential agreement = 100% across generated inputs **and** LLM finds no meaningful divergence |
| **Mostly Equivalent** | Hidden tests pass **and** divergences exist but LLM classifies all as incidental (ordering, formatting, error-message wording) |
| **Not Equivalent** | Any hidden test fails **or** a divergence is classified meaningful — always reported **with the counterexample input** |
| **Cannot Determine** | The gap is not isolatable for execution (unmockable network, unbounded external state) **or** the student's code does not import/parse |

**"Cannot Determine" becomes a principled outcome rather than a hedge**, which is a real improvement: your `quality.py` and `load.py` stages have genuine side effects and deserve honest abstention rather than a guessed verdict.

## 6.6 Where the inputs come from

Two sources, both cheap:

- **Instructor-authored fixtures** — the edge cases you care about pedagogically: empty input, nulls, duplicate keys, malformed dates, unicode.
- **Generated inputs** via Hypothesis. <cite index="93-1">Property-based testing, beginning with QuickCheck and now mature in Python, checks an executable specification of the program under test</cite>, and <cite index="103-1">supports differential test design directly.</cite>

There is a directly relevant recent result: <cite index="100-1">solution-generated autograding exploits a key difference between software testing and autograding — the question author can provide a solution — and by starting from that solution eliminates the need to manually enumerate test cases</cite>. <cite index="85-1">The authors note it shares ground with property-based testing while differing in that property-based testing verifies output properties rather than output equality.</cite> **You are already authoring master code. That master is your oracle.** This is the same insight, and it means your test-authoring burden is far lower than it looks.

## 6.7 What this deliberately does not do

**No formal verification.** <cite index="90-1">The EPFL deployment used a program verifier to check equivalence against reference solutions and could differentiate submissions by recursion pattern even when input-output behaviour was identical</cite> — genuinely more powerful than differential testing. But it requires Scala/Stainless and expertise you do not have time to acquire. Note it in future work; do not build it.

**No AST or PDG matching.** <cite index="73-1">Hybrid AST+PDG approaches with graph neural networks are the current research direction for Type-4 detection</cite> — and they are *structural*, which the brief explicitly rejects, and they need training data you do not have.

**One honest limitation to state in the write-up.** <cite index="76-1">Output agreement depends on test-suite adequacy: finite input sets may overestimate equivalence between non-identical programs or miss rare divergences. This applies to all execution-based similarity methods.</cite> Say that sentence, in your own words, in the limitations section. It is the correct caveat and stating it pre-empts the obvious question.

---

# 7. Assignment Duration — Redesign

## 7.1 The requirement cannot be met as written, and here is precisely why

The brief specifies: *student opens assignment → timer starts → student works → submits → duration stored.*

**Something must observe the opening.** In your architecture, nothing can. There is no web app to open, no server to receive a request, no IDE plugin, no authentication. The first moment VDEL learns a student exists is when a commit lands on GitHub — which is *after* the work.

Three implementable options, evaluated honestly:

| Option | Start signal | Fidelity | Cost | Verdict |
|---|---|---|---|---|
| **A. Web platform** | Real page-open event | Highest | Frontend + backend + auth + hosting + PDPA | ❌ Larger than everything built so far |
| **B. `vdel` CLI** | `vdel start <assignment>` writes a heartbeat commit | High, but compliance-dependent | ~100 LOC, no server | ⚠️ Good cheap upgrade |
| **C. Git-native session reconstruction** | First commit, plus inferred sessions | Moderate, systematically under-counts the first session | ~60 LOC, uses data you already collect | ✅ **Recommended now** |

## 7.2 The recommended design (Option C, with B as an upgrade path)

Activity events = commits + workflow runs. A **session** is a run of events with no gap exceeding a threshold; session length is first-to-last event; attempt duration is the sum of its sessions.

This is not improvised — it is the standard learning-analytics method. <cite index="121-1">The WeBWorK study defines exactly this: logins and answer submissions are activity events, a session is a sequence of such events with no gap exceeding a predetermined inactivity threshold, session length is the total time between first and last event, and total assignment time is the sum of session lengths.</cite> <cite index="116-1">Time-oriented heuristics are the most commonly used session-identification approach, with 30 minutes the most common threshold</cite>, and 30 minutes is also <cite index="114-1">the Google Analytics default.</cite>

**Recommended threshold: 30 minutes**, with two adjustments for your domain — a **10-minute floor** below which duration is recorded but not scored (a two-commit fix should not generate a pace signal), and **explicit versioning of the threshold** in the row, because:

> <cite index="111-1">Time-on-task measures are used to build predictive models of student learning, yet the consequences of their estimation are not fully described or examined; different estimation methods materially influence research findings.</cite>

**You must state your estimation method in the write-up.** Kovanović et al. is precisely a paper about researchers failing to do so. Storing `threshold_min` in the row makes your method reproducible and lets you run a sensitivity analysis later — which is itself a small, cheap, publishable result.

## 7.3 The honest limitation

The first session's start is the **first commit**, not the first keystroke. A student who works 45 minutes before committing has 45 minutes invisible to you. Two mitigations:

1. **Encourage frequent commits.** This is good practice anyway, it is what your `raw_commits` metrics want, and it tightens the estimate. Make it an explicit assignment instruction.
2. **The `vdel start` CLI** (Option B) closes the gap properly when you want it. One command, writes a timestamped marker, no server.

State it plainly in the limitations: *duration is elapsed within-session time bounded by observable git activity; it under-estimates pre-first-commit work and cannot distinguish active from idle time within a session.*

## 7.4 Elapsed vs active time — decide and declare

You cannot measure active time without keystroke telemetry. What you are measuring is **elapsed within-session time**, and that is fine. <cite index="104-1">Time-oriented heuristics are simple but often unreliable, since users may undertake parallel off-task activities.</cite> That caveat is exactly what the threshold and the floor are for. Do not claim active time.

## 7.5 Where it belongs — and the answer is already in your schema

The brief asks whether duration belongs in the profile, the attempt table, a separate session table, or elsewhere. **The answer is all three, at different roles**, and the split follows directly from your event-sourcing rule:

```
sessions          ← PRIMARY. One row per reconstructed session. Derived from
                    raw_commits, reproducible, carries the threshold used.
                    ★ This table is ALREADY in sql/05_memory_tables.sql.

attempts          ← DERIVED ROLLUP. active_duration_min = SUM(sessions in window).
                    Not primary data — recomputable.

learner_features  ← AGGREGATE. Pace computed FROM session durations, versioned
                    under formula_ver.

learner_profile   ← ✗ NEVER. The profile is derived belief, not measurement.
                    Putting duration here breaks replayability.
```

**Not in the profile** is the load-bearing constraint. Your architecture's proudest claim is *wipe the profile, replay, get it back.* Any measurement stored only in the profile breaks that.

## 7.6 The edge cases from the brief, resolved

| Case | Handling |
|---|---|
| **Multiple attempts** | Sessions carry `attempt_no`; an attempt sums its own sessions |
| **Close / reopen** | Naturally handled — a new session opens after the threshold elapses |
| **Page refresh** | Not applicable (no page). Under Option B, `vdel start` is idempotent within a session |
| **Browser crash** | Not applicable. Under B, an unterminated session closes at last-activity + threshold |
| **Abandoned session** | Right-censored. Recorded with `abandoned = true`, **excluded from pace**, but retained as an engagement signal — abandonment is diagnostically interesting |
| **Resuming** | New session row, same attempt. The count of sessions per attempt is itself a useful fragmentation signal |
| **Active vs elapsed** | Elapsed within-session, declared explicitly (§7.4) |

---

# 8. Student Code Editing / Notebook Evaluation

**Verdict: drop the notebook. The concern behind it is real; the notebook is the wrong solution.**

## 8.1 Why not

**Domain mismatch — the decisive reason.** VDEL teaches Python, SQL, **PySpark and Airflow**. Real data engineering is multi-file: modules that import each other, DAG definitions, packaged jobs, CI. Notebooks are single-file and hostile to module structure. Teaching data engineering *in* notebooks teaches the habits the industry spends its time undoing. Your `extract.py / transform.py / load.py / quality.py` structure is pedagogically correct and a notebook would flatten it.

**It destroys your telemetry.** `.ipynb` files are JSON with embedded outputs and execution counts. Your `raw_commits.additions / deletions / files_changed` become noise — a re-run with no code change produces a large diff. Every commit-derived variable degrades. You would be trading your measurement layer for a UI.

**It requires the thing you do not have.** A notebook interface means hosting JupyterHub: a server, per-user containers, authentication, storage, PDPA. That is Option A from §7.1, arriving through a side door.

**Where notebooks genuinely fit, it is a different course.** nbgrader is excellent — for single-notebook exercises in an intro course. Adopting it means adopting its delivery model wholesale and abandoning GitHub-native telemetry, which is the foundation of everything you have built.

## 8.2 The real concern, and the cheap fix

The underlying worry is legitimate: *students could edit lines outside their gaps, corrupting static analysis.*

**You do not need to prevent this. You need to detect it — and detection is strictly more useful.**

You hold the released student file. The student commits a file. Diff them. Any changed line outside a gap region is an out-of-scope edit, and you now know exactly which lines. Roughly forty lines of code:

```python
def scope_check(released: str, submitted: str, gap_ranges: list[tuple[int,int]]) -> dict:
    """Classify every changed line as in-gap or out-of-scope.
    Feeds: lint attribution, an integrity signal, and optionally a CI failure."""
```

This gives you three things a notebook would not:

1. **Correct lint attribution** — findings outside gaps are excluded from the student's V2 (this is C4).
2. **A new variable** — out-of-scope edit rate. Occasionally legitimate (a student fixes a genuine bug in the scaffold, which is *praiseworthy*), sometimes an integrity signal. Either way it is information you currently throw away.
3. **Optional enforcement** — a CI step that fails with *"line 47 is outside your assigned region."* Enforcement is a policy choice you can make later; the detection is valuable regardless.

## 8.3 What to adopt from the notebook idea

The *presentation* concerns in the brief — showing what to implement, showing context, showing errors — are all satisfiable in a plain repository:

- **`# @gap:` markers with instruction text**, nbgrader-style. <cite index="43-1">nbgrader's solution delimiters are language-independent and its generated stubs are correctly re-indented</cite> — a convention worth copying whether or not you use the tool.
- **A generated `ASSIGNMENT.md`** per attempt listing each gap, its file, its line, and what to implement.
- **Visible smoke tests** the student can run locally (`pytest tests/visible`) — immediate feedback, while hidden tests stay hidden. This is nbgrader's exact split.
- **CI annotations** — GitHub Actions can post errors inline on the diff, which is the "errors and feedback in context" the brief asks for, at zero infrastructure cost.

**Result: every stated benefit of the notebook, none of the cost.**

---

# 9. RAG & AI Reviewer Evaluation

The brief asks me to criticise this seriously. Doing so.

## 9.1 Question by question

**1. Is RAG actually useful here?** Only in one narrow place, and not yet. Split the three proposed uses:

| Use | Verdict | Reasoning |
|---|---|---|
| RAG for **grading** | ❌ **No** | Grading needs ground truth. Retrieval adds a failure mode — bad retrieval → bad grade — for no accuracy gain. Tests decide correctness (C1); a rubric decides quality |
| RAG for **resource recommendation** | ❌ **Not needed** | 20–40 resources is not a retrieval problem. `SELECT ... WHERE concept_ids && ARRAY[...]` is exact, free, deterministic, and cannot hallucinate. Embedding search over 40 rows is strictly worse |
| RAG for **conceptual feedback grounded in course materials** | ⚠️ **Defensible, gated** | The only real case. But it depends on course materials, which your own risk register lists as an unlanded supervisor dependency. **Build the seam, not the system** |

**2. What should be retrieved?** If and when it happens: assignment specification, the concept definition from your taxonomy, and course material for that concept. Not "similar student solutions" — that leaks answers.

**3. What should the knowledge base contain?** Start with the `resources` table (§5/A7). It is a knowledge base with a SQL index instead of a vector index, which at this scale is a feature.

**4. Grading, recommendation, teaching, or all?** Recommendation only, via SQL. Not grading. Teaching is §9.2.

**5. Is a chatbot necessary?** **No — and it is actively contradictory.** See below.

**6. Implement now?** The `resources` table and concept-keyed selection. That is the whole scope.

**7. Postpone?** RAG-grounded conceptual feedback, gated on course materials landing and on the tutor-side SKG reaching v1. The `retrieve()` contract already exists as the swap-in point — that is good design and it should stay.

**8. Drop?** The chatbot. The AI teaching assistant. The vector store.

## 9.2 The chatbot must be dropped, and one reason is decisive

**It contradicts the policy the supervisor set.** The 19 August design review agreed students are *restricted from using AI* during these assignments. You cannot simultaneously ban AI assistance and ship an AI assistant. If the argument is "ours is pedagogically bounded, so it's different," then you need a compelling account of that boundary — and you would be building and defending a second research contribution in a project that has not yet demonstrated its first.

**Three supporting reasons:**

*It is the wrong product.* You are building an assessment and diagnosis system. A tutoring chatbot is a different system with different evaluation methods, different safety requirements and a different literature. The collaborator's workstream is the tutor side. Adding a chatbot to the student side blurs the boundary your architecture was explicitly designed to keep sharp.

*The evidence on student behaviour is cautionary.* <cite index="132-1">Classroom studies report that LLM hints are often perceived as more readable than compiler output and can support progress across submissions, but also reveal risks of over-reliance; evaluations report that LLM feedback may include overly detailed guidance, complete solutions, or hallucinated issues, and that students often use such feedback for immediate help-seeking rather than deeper self-regulatory strategies.</cite> "Immediate help-seeking rather than self-regulation" is the precise failure mode your `error_response` variable exists to detect. A chatbot would manufacture the pathology you are trying to measure.

*It needs the platform you do not have.* Interactive means a frontend, session management, moderation, rate limiting, and abuse handling.

## 9.3 If RAG returns later, here is the honest state of the evidence

Do not overclaim. Retrieval-grounded tutoring is an active area with mixed results, and the strongest recent work is careful about scope: <cite index="138-1">one controlled evaluation separates retrieval, learner-state tracking, pedagogical response policy, prompt assembly and logging into explicit components — noting this separation is useful for auditability but creates new integration risks such as trace artifacts and evidence-boundary leakage — and explicitly states it does not test classroom learning or real learner adaptivity.</cite>

Note what that architecture is: **exactly your blackboard, with retrieval added.** If you build RAG later, that is the shape, and the auditability-versus-integration-risk trade-off is the one you will face.

Meanwhile the quality problem is unsolved in general — <cite index="131-1">researchers have raised persistent concerns about hallucinations in LLM-generated educational feedback</cite>, and there is now a whole line of work on automatically reviewing AI-generated feedback because human review does not scale.

**The one-line summary for the supervisor:** *RAG is a good idea for the tutor side and a distraction on the student side. We are building the retrieval seam and the curated resource table now; grounded conceptual feedback activates when course materials land.*

---

# 10. Variables and Data Model Critique

## 10.1 Verdict on each existing variable

| # | Variable | Verdict | Action |
|---|---|---|---|
| V1 | **Concept Mastery** (BKT + KT-IDEM) | ✅ **Keep — the best-designed variable** | Item ID must become the variant (C2) |
| V2 | **Engineering Discipline** | ⚠️ **Broken twice** | Gap-scope it; drop the composite; re-grain to project |
| V3 | **Effort Regulation** | ❌ **Demote** | Unscored diagnostic; project-grained; out of the feature vector |
| V4 | **Learning Pace** | ⚠️ **Redefine** | Rebuild on session duration (§7); drop cohort normalisation until a cohort exists |
| V5 | **Error Response** | ✅ **Keep, re-grain** | The most valuable behavioural variable. Aggregate at project level |
| V6 | **Error Frequency** | ⚠️ **Fix denominator** | Same collapse as V2. Its real job — the per-concept histogram — is sound |
| V7 | **Help-Seeking** | ✅ **Keep as seam** | Nullable, unbuilt, correctly deferred |

## 10.2 The specific breakages, with the arithmetic

**V2 — the denominator collapses.**
```python
per_100 = lint_violations / (changed_loc / 100.0)
return 1.0 - min(1.0, per_100 / 10.0)
```
Old model: `changed_loc` ≈ 100–500. New model: 4–15. A student writes 8 lines with **one** violation → `per_100 = 12.5` → `min(1, 1.25) = 1` → **cleanliness = 0.0**. One violation in eight lines scores zero. The metric saturates on noise.

**V2 — and it is grading the instructor.** The student commits master code *plus* their gaps. `ruff` runs on everything. The master's violations swamp the student's, so V2 becomes a per-assignment constant. This is the fairness bug from C4.

**V2 — the composite is dead code.** `cronbachs_alpha` returns `None` below 10 students; `composite` requires `alpha >= 0.70`; therefore `composite` is `None` in every run you will do this year. Report components.

**V3 — mostly `None`.** `burstiness_regularity` needs ≥2 gaps, i.e. ≥3 commits. A gap-fill task is 1–3 commits in one sitting. And its own documentation says it is *"purely a coaching flag, never touches grades."* An unscored flag that is usually null does not belong in the scored feature vector.

**V4 — two independent failures.** (a) The clock: with simultaneous release, assignment 7's clock has run for days while the student worked on 1–6, so every student is reported catastrophically slow on later stages. (b) The scale: `0.5 - 0.25*log2(r)` with `cohort_median_h ≈ 0.4h` means a coffee break moves the score a quarter of the range. Both fixed by §7.

**V6 — identical denominator collapse to V2.**

## 10.3 Variables to add

| New | Definition | Why it earns its place |
|---|---|---|
| **V8 Functional Equivalence Rate** | Fraction of hidden tests + differential inputs where student ≡ master | The correctness ground truth. Feeds BKT directly, replacing coarse CI pass/fail |
| **V9 Out-of-Scope Edit Rate** | Changed lines outside gaps ÷ total changed lines | Free from §8.2. Integrity signal *and* an initiative signal — a student who fixes a real scaffold bug is showing something valuable |
| **V10 First-Attempt Success Rate** *(per concept)* | Gaps solved on attempt 1 ÷ gaps attempted | The cleanest fluency signal in a variant-based system, and directly comparable across students because variants are difficulty-matched |
| **V11 Session Fragmentation** | Number of sessions per attempt | Falls out of §7 for free. Distinguishes "one focused hour" from "six scattered ten-minute pokes" — a genuine self-regulation signal, and unlike V3 it is well-defined on short tasks |

**Note V8 replaces the "similarity score" the review proposed.** Same slot in the architecture; evidence instead of opinion.

## 10.4 Table-by-table critique

| Table | Verdict | Reasoning |
|---|---|---|
| `students` | ✅ Keep unchanged | Minimal and correct |
| `assignments` | ⚠️ Change | Needs `project_id`; `concepts[]` becomes derived from gaps |
| `raw_commits` | ✅ Keep | Source of truth, correctly designed |
| `raw_workflow_runs` | ⚠️ Extend | Add `tests_passed` / `tests_total`; `conclusion` alone is too coarse |
| `learner_features` | ✅ Keep | The `formula_ver` column is about to prove its worth |
| `kt_params` | ✅ Keep | Correct as a versioned param set |
| `items` | ❌ **Replace** | Redundant once `variants` exists — two tables modelling one concept |
| `traces` | ✅ Keep, untouched | The architecture's spine |
| `sessions` | ✅ **Already designed — now activate it** | §7 gives it its purpose |
| `learner_profile` | ✅ Keep | Derived belief. Do not add measurements to it |
| `kb_chunks` (pgvector) | ⏸ Leave dormant | Harmless. Activates only if §9's gated RAG case arrives |

## 10.5 Tables to add

`projects`, `gaps`, `variants`, `attempts` (derived), `test_results`, `resources`. Full DDL in §11.

---

# 11. Proposed Database Schema

Additions and changes only; unchanged tables omitted.

```sql
-- ═══ ASSIGNMENT STRUCTURE ═══════════════════════════════════════════

CREATE TABLE projects (
  project_id    TEXT PRIMARY KEY,
  repo_prefix   TEXT NOT NULL,           -- moved up from assignments
  title         TEXT NOT NULL,
  released_at   TIMESTAMPTZ NOT NULL,
  master_version TEXT NOT NULL           -- git sha of the master repo state
);

ALTER TABLE assignments
  ADD COLUMN project_id TEXT REFERENCES projects(project_id),  -- NULLABLE: old rows survive
  ADD COLUMN file_path  TEXT,            -- 'src/extract.py'
  ADD COLUMN seq        INT;             -- stage order within the project
-- assignments.concepts[] is now DERIVED from gaps. Kept for query convenience,
-- rebuilt by the seed job, never hand-authored.

CREATE TABLE gaps (
  gap_id        TEXT PRIMARY KEY,        -- 'g_retry_loop'
  assignment_id TEXT NOT NULL REFERENCES assignments(assignment_id),
  concept_ids   TEXT[] NOT NULL,         -- ← C7: tags live HERE, not on the assignment
  line_start    INT NOT NULL,
  line_end      INT NOT NULL,
  instruction   TEXT NOT NULL,           -- becomes the student's TODO comment
  difficulty    REAL NOT NULL DEFAULT 0.5,   -- cold-start seed
  master_version TEXT NOT NULL           -- line numbers are only valid for one master
);

CREATE TABLE variants (
  variant_id     TEXT PRIMARY KEY,       -- sha1(assignment ‖ sorted(gap_ids) ‖ master_version)
  assignment_id  TEXT NOT NULL REFERENCES assignments(assignment_id),
  gap_ids        TEXT[] NOT NULL,
  master_version TEXT NOT NULL,
  difficulty     REAL,                   -- ← THE KT-IDEM ITEM (C2). Replaces `items`
  n_cohort_obs   INT NOT NULL DEFAULT 0
);
DROP TABLE IF EXISTS items;              -- superseded

-- ═══ ACTIVITY & TIMING ══════════════════════════════════════════════

CREATE TABLE sessions (                  -- DERIVED from raw_commits; rebuildable
  session_id     BIGSERIAL PRIMARY KEY,
  student_id     TEXT NOT NULL REFERENCES students(student_id),
  assignment_id  TEXT REFERENCES assignments(assignment_id),
  attempt_no     INT,
  started_at     TIMESTAMPTZ NOT NULL,   -- first event in the session
  ended_at       TIMESTAMPTZ NOT NULL,   -- last event
  duration_min   REAL NOT NULL,
  n_events       INT NOT NULL,
  threshold_min  INT NOT NULL DEFAULT 30,   -- ← METHOD IS DATA (§7.2)
  method_ver     TEXT NOT NULL DEFAULT 'git_session_v1',
  abandoned      BOOLEAN NOT NULL DEFAULT FALSE
);

-- ═══ ATTEMPTS (DERIVED — NOT a source of truth) ═════════════════════

CREATE TABLE attempts (
  attempt_id      BIGSERIAL PRIMARY KEY,
  student_id      TEXT NOT NULL REFERENCES students(student_id),
  project_id      TEXT NOT NULL REFERENCES projects(project_id),
  assignment_id   TEXT NOT NULL REFERENCES assignments(assignment_id),
  attempt_no      INT  NOT NULL,
  variant_id      TEXT NOT NULL REFERENCES variants(variant_id),
  gap_seed        BIGINT NOT NULL,       -- regeneration determinism
  commit_sha      TEXT NOT NULL REFERENCES raw_commits(sha),
  submitted_at    TIMESTAMPTZ NOT NULL,
  duration_min    REAL,                  -- Σ sessions (§7.5)
  n_sessions      INT,                   -- → V11
  tests_passed    INT, tests_total INT,  -- → V8, ground truth
  diff_agreement  REAL,                  -- differential-execution agreement rate
  equivalence     TEXT,                  -- Equivalent|Mostly|Not|CannotDetermine
  out_of_scope_lines INT,                -- → V9
  verdict_trace   BIGINT REFERENCES traces(trace_id),
  UNIQUE (student_id, assignment_id, attempt_no)
);

CREATE TABLE test_results (              -- the evidence behind tests_passed
  attempt_id  BIGINT NOT NULL REFERENCES attempts(attempt_id),
  test_name   TEXT NOT NULL,
  gap_id      TEXT REFERENCES gaps(gap_id),   -- localises failure to a concept
  passed      BOOLEAN NOT NULL,
  message     TEXT,
  PRIMARY KEY (attempt_id, test_name)
);

-- ═══ RESOURCES (replaces RAG — §9) ══════════════════════════════════

CREATE TABLE resources (
  resource_id TEXT PRIMARY KEY,
  concept_ids TEXT[] NOT NULL,
  kind        TEXT,                      -- book_section | doc_page | kaggle | video
  title       TEXT NOT NULL,
  locator     TEXT,                      -- 'Ch. 4, §4.2' — the SECTION the supervisor asked for
  url         TEXT,                      -- verified once, at authoring time
  level       TEXT
);
CREATE INDEX ON resources USING GIN (concept_ids);
```

## 11.1 Why this schema is better

| Property | How it is achieved |
|---|---|
| **Event sourcing preserved** | `attempts` and `sessions` are *derived* and rebuildable. Wipe-and-replay still works |
| **Mastery stays valid** | `variants` is the KT-IDEM item; `variants.difficulty` is per-variant, as the model requires |
| **History stays comparable** | `master_version` on `gaps`, `variants` and `projects`. Edit a master → new version → old scores stay interpretable |
| **Reproducible** | `gap_seed` + `master_version` reconstructs exactly what any student saw, at any time |
| **Failure localises to a concept** | `test_results.gap_id → gaps.concept_ids` — a failing test names the concept directly |
| **Method is data** | `threshold_min` and `method_ver` on sessions make time-on-task reproducible and sensitivity-testable |
| **Migration is safe** | Every change is additive or nullable. Nothing existing breaks (§14) |
| **One fewer table** | `items` dies; `variants` does its job better |

---

# 12. Claude / `CLAUDE.md` / Project Configuration Changes

**Yes — and this is more urgent than any code change, because it is currently blocking your ability to work with Claude Code at all.**

## 12.1 The governance conflict, stated exactly

| Source | Says |
|---|---|
| `CLAUDE.md` §2 | *"Do not add `problems` or `attempts` tables."* |
| `START_HERE.md` | *"This project was already damaged once by an AI inventing a `problems`/`attempts` schema… The fix cost a full session."* |
| 19 Aug design review | Adds an attempts table |

Both governing documents forbid the thing the supervisor mandated. `CLAUDE.md` is auto-loaded into every session, and `START_HERE.md` instructs the assistant to **stop and ask** rather than invent structure. So every future session either refuses the work or complies while your documentation quietly becomes false.

**The distinction that matters:** last time, an AI invented the table with no authority. This time a supervisor mandated it. Same artefact, opposite provenance. **The documents must record the provenance, or the rule that protected you becomes the rule that blocks you.**

## 12.2 Required file changes

**① Create `DECISIONS.md` — new Tier 0.**

```markdown
# ADR-032 — Attempts and variant tables (supersedes CLAUDE.md §2)
Date: 2026-08-19 · Status: ACCEPTED · Authority: the supervisor (design review)

CONTEXT  The prohibition in CLAUDE.md §2 was written after an AI invented an
         attempts schema with no design authority (see START_HERE.md).
DECISION Attempts, variants, gaps, sessions and test_results are now IN SCOPE,
         mandated by the supervisor and required by the completion-problem format.
CONSTRAINT `attempts` and `sessions` are DERIVED tables, rebuildable from
         raw_commits + gap specs. They are NOT sources of truth. Event sourcing
         and the wipe-and-replay property are preserved unchanged.
SUPERSEDES CLAUDE.md §2 (prohibition), CLAUDE.md §6 (schemas).
```

**② `START_HERE.md` — insert Tier 0 above `CLAUDE.md`:**
```
TIER 0  DECISIONS.md   ← supersession log. Read FIRST. An ADR here beats every
                          other file, including CLAUDE.md.
```

**③ `CLAUDE.md` — six edits:**

| § | Change |
|---|---|
| §2 | Replace the prohibition with: *"Attempts/variants ARE in scope — see ADR-032. The original prohibition applied to AI-invented structure, not supervisor-mandated design."* |
| §3 | Update the scope table: M5 Perf/Pedagogy → DROPPED; add M4b Differential Testing and M4c Gap Engine |
| §5 | Add `assessment/` (gap parser, generator, scope checker, differential runner) |
| §6 | Replace schemas with §11 of this document |
| §7 | Add invariants 12–15 (below) |
| §8 | Update the variables table with V8–V11 and the demotions |

**④ Four new invariants:**

> **12.** Correctness is decided by **executed tests**, never by an LLM. An LLM may explain a divergence, never assert one.
> **13.** All static analysis is **gap-scoped**. Findings outside gap regions are never attributed to the student.
> **14.** Every gap, variant and attempt pins `master_version`. Line numbers and divergence scores are only valid within one master version.
> **15.** An equivalence verdict of `Not Equivalent` **must carry a counterexample input**. A verdict without one is rejected — the same rule as invariant 6 (fabricated evidence).

**⑤ Reconcile the cache key.** `SESSION_SUMMARY_M3.md` D-020 records four conflicting definitions across four files, with a docstring contradicting the code beneath it. Pick one, write an ADR, fix all four sites. This is fifteen minutes and it removes a live trap.

## 12.3 One process recommendation

Your documentation set is now **~10,000 lines across twelve files** with a four-tier authority hierarchy and a known history of internal contradiction (D-007, D-008, D-020). That is a lot of specification for a single student-side workstream.

After the presentation, **consolidate**. `CLAUDE.md` + `DECISIONS.md` + one merged design document. The module documents become an appendix. The tier hierarchy exists to manage contradictions between documents that should not have been allowed to contradict.

---

# 13. Recommended Architecture

```
┌── AUTHORING (instructor, offline) ─────────────────────────────────────┐
│  master/extract.py  with  # @gap:id=… concepts=[…] difficulty=…        │
│  tests/visible/     student-runnable smoke tests                       │
│  tests/hidden/      instructor tests — the correctness oracle          │
└───────────────┬────────────────────────────────────────────────────────┘
                │  gap_parser.py  (deterministic)
                ▼
        gaps · variants · assignments · projects
                │
                │  gap_generator.py  — seeded; concept adaptive, variant random
                ▼
        student repo: scaffolded file + ASSIGNMENT.md + visible tests
                │
                │  student works, commits  ── no AI, by policy
                ▼
┌── TELEMETRY ───────────────────────────────────────────────────────────┐
│  GitHub API → raw_commits · raw_workflow_runs                          │
│  GitHub Actions → ruff · visible tests · HIDDEN TESTS → test_results   │
└───────────────┬────────────────────────────────────────────────────────┘
                ▼
┌── DETERMINISTIC ANALYSIS (no LLM, no variance, free) ──────────────────┐
│  scope_check.py    diff vs released → in-gap / out-of-scope   → V9     │
│  sessionize.py     commits → sessions (30-min threshold)      → V11,V4 │
│  diff_runner.py    student ⊕ master on shared inputs → agreement +     │
│                    CONCRETE COUNTEREXAMPLES                   → V8     │
│  diagnose.py       attempts · recurrence · weakest concept            │
│  compute_features  V1–V11, gap-scoped, formula_ver='v3'               │
│  BKT               variant-conditioned mastery update                  │
└───────────────┬────────────────────────────────────────────────────────┘
                ▼
┌── LLM LAYER (two agents, both grounded in the evidence above) ─────────┐
│  Code Agent      approach · readability · idiom      ← NOT correctness │
│  Feedback Agent  counterexamples + diagnosis → explanation             │
│                  + resource SELECTED from `resources` (never generated) │
└───────────────┬────────────────────────────────────────────────────────┘
                ▼
┌── REVIEWER (pure Python) ──────────────────────────────────────────────┐
│  weighted grade · reproducible arithmetic                              │
│  ★ flags disagreement: tests PASS but Code Agent scored approach low    │
│    = "correct but no understanding" — the pedagogically golden case     │
└───────────────┬────────────────────────────────────────────────────────┘
                ▼
        traces (append-only) → learner_profile (derived, replayable)
```

## 13.1 Component dependency map

```
D-006 (roster + token)  ──────────────► EVERYTHING. Nothing runs without it.
gap_parser ──► gap_generator ──► student repos ──► telemetry ──► analysis
hidden tests ──► test_results ──► V8 ──► BKT ──► adaptive gap selection
   └─────────────────────────────────► judge validation (the research result)
sessionize ──► V4, V11
scope_check ──► V2 (attribution), V9
diff_runner ──► equivalence verdict ──► Feedback Agent
resources ──► Feedback Agent
```

**Two things to notice.** First, the LLM layer sits at the *end* and depends on everything, which is why it should be built last. Second, **hidden tests are the highest-leverage node** — they feed correctness, mastery, adaptive selection *and* judge validation. One artefact, four payoffs.

## 13.2 What survives unchanged from the current design

Event sourcing · the blackboard · `traces` append-only · `learner_profile` derived · the LLM Gateway as the single choke point · temperature 0 for judging · pydantic schema validation with one corrective retry · evidence string-matching · submission-as-data delimiters · BKT with the upgrade ladder · the `retrieve()` contract as Hanafi's swap-in point.

**That is most of the architecture.** The redesign replaces the assessment layer and leaves the intelligence layer intact — which is itself evidence the original boundaries were drawn correctly, and is the strongest thing you can say about the revision in your presentation.

---

# 14. Implementation Plan

## Phase 0 — Unblock and record (½ day) · **DO FIRST**

1. `DECISIONS.md` + ADR-032 + `START_HERE.md` Tier 0 + `CLAUDE.md` §2 fix
2. **Resolve D-006** — `config/roster.yaml`, `GITHUB_TOKEN`, run the collector
3. Confirm `prove_event_sourcing.py` stops printing `NOTHING TO PROVE`

> **Nothing else matters until step 2 passes.** Every requirement in this document is downstream of real rows in `raw_commits`.

## Phase 1 — Assessment foundation (2–3 days)

4. Schema migration — all additive/nullable (§11)
5. `gap_parser.py` — `# @gap:` markers → student file + `gaps` rows
6. `gap_generator.py` — seeded, uniform for now (adaptive in Phase 4)
7. `scope_check.py` — the diff detector (§8.2)
8. Author master + gaps for **one** project, 3 assignments

**DoD:** two students, same assignment, demonstrably different variants, both reconstructible from `(seed, master_version)`.

## Phase 2 — Ground truth (2 days)

9. `tests/hidden/` for those 3 assignments; CI injection
10. `test_results` populated from CI
11. `diff_runner.py` — differential execution + counterexample capture
12. Feature fixes: gap-scoped linting, V2/V6 denominators, V3 demotion

**DoD:** a wrong submission produces a **concrete counterexample input**, not a similarity score.

## Phase 3 — Timing + feedback (2 days)

13. `sessionize.py` (§7); `attempts.duration_min` rollup
14. V4 rebuilt on sessions; `formula_ver='v3'`; **replay and show history recompute**
15. `resources` table, 20–40 curated rows
16. Feedback Agent — counterexamples + diagnosis → explanation + resource selection

**DoD:** end-to-end. Commit → CI → verdict → feedback naming a concept and a resource *section* → profile updated → wipe → replay → identical.

## Phase 4 — Research results (2–3 days, post-presentation)

17. Adaptive concept selection from BKT (C3)
18. Judge-vs-ground-truth agreement + κ (C8)
19. Self-consistency: 3 runs at temp 0, report variance
20. Reviewer arithmetic + the objective-vs-LLM disagreement flag

## Phase 5 — Deferred, with triggers

21. `vdel` CLI · RAG seam (trigger: course materials land) · Perf/Pedagogy agents · model comparison (trigger: ≥100 attempts) · formal verification (future work)

## 14.1 The migration safety rule

**Build alongside, not in place.** `project_id` nullable, gap engine in a new `assessment/` module nothing imports, new `formula_ver` with old formulas retained, old seed data kept. Feature-flag it. **If Phase 1 is not green, keep the old path as the working version.** The one genuinely bad outcome available is ending with less working than you have today.

---

# 15. Priority: Must / Should / Could / Drop

## 🔴 MUST HAVE — the system is not defensible without these

| Item | Why |
|---|---|
| **Fix D-006** | Nothing has ever run on real data |
| `DECISIONS.md` + `CLAUDE.md` reconciliation | Your own tooling currently blocks the mandated work |
| Gap-scoped static analysis | Fairness bug: you are grading the instructor |
| `variant_id` as the KT-IDEM item | Silent corruption of every mastery estimate |
| Gap-level concept tags | Weakness attribution is impossible without them |
| Hidden tests in CI | Ground truth; the single highest-leverage artefact |
| `master_version` pinning | Without it, history is incomparable |
| V2/V6 denominator fix, V3 demotion | Four variables currently produce wrong numbers |
| Curated `resources` table | Prevents URL hallucination in a live demo |

## 🟠 SHOULD HAVE — turns a working system into a defensible one

Differential execution + counterexamples · session-based duration · judge-vs-ground-truth agreement · adaptive concept selection · Reviewer arithmetic + disagreement flag · self-consistency variance · out-of-scope edit detection

## 🟡 COULD HAVE — real value, no urgency

`vdel start` CLI · V10/V11 · sensitivity analysis on the session threshold · CI inline annotations · generated `ASSIGNMENT.md` · project-level V2/V3 rollups

## ⛔ DROP

| Dropped | Reason | Trigger to revisit |
|---|---|---|
| **Notebook interface** | Domain mismatch; destroys git telemetry; needs hosting | Course moves to notebook-based teaching (unlikely) |
| **RAG chatbot / AI tutor** | Contradicts the no-AI policy; wrong product; needs a frontend | Post-thesis, tutor-side, the tutor-side collaborator's workstream |
| **RAG for grading** | Adds failure modes for no accuracy gain | Never |
| **Vector store for resources** | 40 rows is a SQL query | Corpus > ~1,000 documents |
| **Token/embedding similarity** | Measures identifier names | Never — replaced by differential testing |
| **Cronbach composite in V2** | Dead code below n=10 | Cohort ≥ 10 |
| **Cohort-normalised pace** | No cohort exists | Cohort ≥ 10 |
| **Performance + Pedagogy Agents** | Correctly deferred; overlap folds into Code Agent | Course materials + tutor-side SKG v1 |
| **Formal verification** | Right idea, wrong toolchain and timeline | Future work section |
| **Web platform / auth** | Larger than everything built so far | Institutional adoption decision |

---

# 16. Risks and Trade-offs

| Risk | Impact | Mitigation | Honest residual |
|---|---|---|---|
| **D-006 stays unresolved** | 🔴 Total — nothing demonstrable | Phase 0, day one | None; entirely in your control |
| **Redesign breaks working code** | 🔴 End with less working than today | Build alongside; feature-flag; keep old seed data | Low if §14.1 is followed |
| **Hidden tests leak to students** | 🟠 Assessment invalidated | Separate repo + deploy key, or GitHub Classroom autograder | Moderate — a determined student may find them; treat as policy, not security |
| **Differential testing overestimates equivalence** | 🟠 Wrong submissions pass | Instructor edge-case fixtures + Hypothesis generation | **Irreducible** — <cite index="76-1">finite input sets may overestimate equivalence or miss rare divergences; this applies to all execution-based methods.</cite> State it |
| **Side-effecting gaps not testable** | 🟠 Many `load.py` gaps → Cannot Determine | Layer 2 property checks; mock the DB | Moderate. Prefer authoring gaps in pure functions where possible |
| **Session threshold is arbitrary** | 🟡 Duration estimates shift with it | Store `threshold_min`; run sensitivity analysis | <cite index="111-1">Estimation method materially influences findings</cite> — so declare it, don't hide it |
| **First-commit start under-counts** | 🟡 Systematic underestimate of session 1 | Encourage frequent commits; CLI upgrade | Real and unavoidable without a platform. Declare it |
| **Adaptive selection with n<3** | 🟡 Adapting on noise | Uniform fallback below 3 observations | Low |
| **Cohort of one** | 🟡 Difficulty, pace, alpha all vacuous | Label cold-start explicitly | None if labelled; embarrassing if not |
| **Scope in remaining weeks** | 🟠 Phases 1–3 is 6–7 days of work | Phase 0–1 first; rest after | Moderate — cut per §15 |

## 16.1 The three trade-offs worth defending out loud

**Behavioural equivalence over conceptual equivalence.** You give up detecting "same idea, different behaviour." You gain falsifiability, counterexamples students can act on, and a ground truth to validate your judge against. Given undecidability, this is the correct trade — and the one the autograding literature has already made.

**Determinism over sophistication.** Six deterministic components, two LLM agents. Less impressive on a slide, far more reliable in a demo, and directly consistent with the principle already written in your own `CLAUDE.md`.

**Detection over prevention** (the notebook decision). You do not stop out-of-scope edits; you measure them. Zero infrastructure, and you gain a variable instead of merely closing a hole.

---

# 17. Research and Real-World References

Grouped by the decision each supports. **Verify exact author/year/venue against primary sources before publication**, per your existing `TODO(verify)` convention.

## Semantic equivalence — why the LLM must not render the verdict (§6)

| Source | What it shows | Application |
|---|---|---|
| Elva, *Detecting Semantic Method Clones Using Method IOE-Behaviour* (UCF) | <cite index="69-1">Semantic equivalence is undecidable, but a reasonable approximation is obtainable by combining static and dynamic analysis; extends input-output observable behaviour to include heap effects</cite> | The three-layer cascade; heap effects justify Layer 2 for side-effecting stages |
| Gabel, Jiang & Su, *Scalable Detection of Semantic Clones* (ICSE '08) | <cite index="72-1">True semantic similarity is undecidable in general</cite> | Kills any claim of a "conceptual equivalence verdict" |
| Kitsios et al., *Detecting Semantic Clones of Unseen Functionality* (2025) | <cite index="81-1">The clone definition is undecidable because it rests on code equivalence; no universally accepted decidable definition exists</cite> | Justifies "Cannot Determine" as a first-class verdict |
| *Semantic Code Clone Detection: Are We There Yet?* (arXiv 2606.25272) | <cite index="67-1">Unclear whether SOTA Type-4 detectors capture genuine semantic equivalence or exploit dataset patterns</cite> | Do not trust an LLM's unaided equivalence judgement |
| *What can LLMs Capture about Code Functional Equivalence?* (arXiv 2408.11081) | <cite index="77-1">Equivalence lies on a spectrum; different programs compute the same function in very different ways</cite> | Motivates verdict *tiers* rather than binary |
| *HyClone* (arXiv 2508.01357) | <cite index="70-1">Bridges LLM understanding with dynamic execution for semantic clone detection</cite> | Direct precedent for the hybrid architecture |
| *Improving Source Code Similarity Detection* (arXiv 2408.08903) | <cite index="76-1">Output agreement depends on test-suite adequacy; finite input sets may overestimate equivalence — applies to all execution-based methods</cite> | The limitation sentence to write |

## Autograding and reference solutions (§4/C1, §6.6)

| Source | What it shows | Application |
|---|---|---|
| **nbgrader** documentation | <cite index="49-1">Solution regions marked `### BEGIN SOLUTION`, hidden tests `### BEGIN HIDDEN TESTS`; the student version is generated from the instructor version</cite>; <cite index="43-1">delimiters are language-independent, stubs correctly re-indented</cite>; <cite index="58-1">test each function in isolation so failures localise</cite> | The gap-marker convention, the hidden/visible test split, and per-gap failure localisation |
| Milovančević et al., *Formal Autograding in a Classroom* (ESOP '25) | <cite index="90-1">Program-verifier equivalence checks against reference solutions, deployed alongside existing testing-based grading</cite>; <cite index="99-1">generates counterexamples for incorrect programs, valuable to students and instructors</cite> | Tests as baseline; counterexamples-as-feedback is the model for Layer 3 |
| *Solution-Generated Autograders* (arXiv 2608.06572) | <cite index="100-1">Exploits the fact that the question author can provide a solution, eliminating manual test-case enumeration</cite>; <cite index="85-1">shares ground with property-based testing, which verifies properties rather than equality</cite> | Your master code is already the oracle — test authoring is cheaper than it looks |
| Hypothesis / QuickCheck lineage | <cite index="93-1">PBT checks an executable specification; mature in Python</cite>; <cite index="103-1">supports differential test design</cite> | Input generation for Layer 1 and properties for Layer 2 |

## Completion problems — the pedagogical justification (§2.3, C3, C6)

| Source | What it shows | Application |
|---|---|---|
| Ericson, PhD dissertation (Georgia Tech, 2018) | <cite index="8-1">Students complete Parsons problems significantly faster than fixing or writing code with the same pretest-to-posttest learning gains; adaptation helped more learners succeed</cite> | The evidence base for the gap-fill format |
| Hou, Ericson & Wang (ICER 2022) | <cite index="4-1">Intra-problem adaptation makes a struggling learner's current problem easier; inter-problem adaptation sets the next problem's difficulty from prior performance</cite> | The name and mechanism for BKT-driven gap selection |
| Denny et al. (ICER '08); Ericson et al., *Parsons Problems and Beyond* (ITiCSE WG 2022) | <cite index="14-1">Easier to grade than free-form code writing while still yielding rich information about student knowledge</cite> | Format choice is defensible on assessment grounds, not just cognitive load |
| Denny et al., *Prompt Problems* (SIGCSE 2024) | <cite index="18-1">A programming exercise designed for the generative-AI era</cite> | Related work for the AI-policy discussion (§6 of the critique) |

## Randomised variants (§C2)

| Source | What it shows | Application |
|---|---|---|
| PrairieLearn (Zilles, West et al.; docs + research catalogue) | <cite index="29-1">Question parameters are randomised on every attempt so the answer always differs, with a mastery score reflecting the system's ability estimate</cite>; <cite index="24-1">generated variants are persisted per student rather than regenerated</cite>; Sud, West & Zilles (ASEE '19) on reducing difficulty variance in randomised assessments | Persist the variant; treat difficulty variance as a first-order concern |

## Time-on-task (§7)

| Source | What it shows | Application |
|---|---|---|
| Kovanović et al., *Does Time-on-task Estimation Matter?* (JLA 2015) | <cite index="111-1">Estimation details are rarely described and materially influence findings</cite> | You must declare your method; store `threshold_min` |
| WeBWorK log analysis (arXiv 2005.03826) | <cite index="121-1">Sessions are event runs separated by less than an inactivity threshold; total time is the sum of session lengths</cite> | The exact algorithm to implement |
| Session-identification literature (arXiv 1411.2878); Google Analytics | <cite index="116-1">Time-oriented heuristics are the most common approach, 30 minutes the most common threshold</cite>; <cite index="114-1">GA default is 30 minutes of inactivity</cite> | Justifies the 30-minute default |
| Chitraa & Davamani, via Kovanović | <cite index="104-1">Time-oriented heuristics are simple but often unreliable, since users may undertake parallel off-task activities</cite> | The elapsed-not-active caveat |

## LLM feedback and RAG (§9)

| Source | What it shows | Application |
|---|---|---|
| *The Effects of Structured LLM-Generated Feedback* (arXiv 2605.16933) | <cite index="132-1">Hints can support progress but risk over-reliance; feedback may contain complete solutions or hallucinated issues; students often use it for immediate help-seeking rather than self-regulation</cite> | The strongest argument against the chatbot |
| *Dean of LLM Tutors* (arXiv 2508.05952) | <cite index="131-1">Persistent concerns about hallucination in LLM-generated educational feedback</cite> | Why resources are selected from a table, never generated |
| Frontiers in Education (2026), pedagogical RAG evaluation | <cite index="138-1">Separating retrieval, learner-state tracking, response policy, prompt assembly and logging aids auditability but creates integration risks such as evidence-boundary leakage; the study explicitly does not test classroom learning or real adaptivity</cite> | If RAG returns, this is the architecture and the honest scope limit |

## Already in your documents — carry forward, do not lose in the redesign

CodeJudgeBench (arXiv 2507.10535) — position bias up to 14%, swap and average; reasoning models outperform as judges. Corbett & Anderson (BKT); Pardos & Heffernan (KT-IDEM); Jadud (Error Quotient); Watson et al. (Watwin); Beck & Gong (wheel-spinning); Kapur (productive failure); Becker (repeated error density); Goh & Barabási (burstiness); Cox (proportional hazards); Cronbach (alpha). Panickssery et al. 2024 on LLM self-preference — **verify** this one before citing, it is load-bearing for C9.

---

# 18. Final Recommendation

## 18.1 The one-paragraph answer

**Keep the intelligence layer; replace the assessment layer; do not build a platform.** Event sourcing, the blackboard, BKT, the gateway and the deterministic-first agent skeleton are sound and survive intact. What must change is everything touching the new assignment format: correctness moves from LLM judgement to executed hidden tests, equivalence moves from similarity to differential execution with counterexamples, item identity moves from assignment to variant, concept tags move from assignment to gap, static analysis becomes gap-scoped, and duration moves from release-to-pass to reconstructed sessions. Drop the notebook, drop the chatbot, drop RAG-for-grading. **And fix D-006 before any of it**, because nothing here matters until real data flows.

## 18.2 Three things to do this week

1. **`DECISIONS.md` + `CLAUDE.md` reconciliation.** Fifteen minutes. Without it your own tooling blocks the work the supervisor mandated.
2. **Resolve D-006.** Roster, token, collector run. Everything is downstream.
3. **One project, three assignments, gap-parsed, two students, different variants.** That is a demo.

## 18.3 The sentence that reframes the presentation

> *The evaluation layer — event-sourced memory, the variable framework, the blackboard architecture, the interpretable mastery model — is unchanged. What changed is the assessment format, which the architecture treats as a pluggable input. The revision required no rework of the core, which is evidence the boundaries were drawn correctly.*

True, defensible, and it converts a change of plan into evidence of good design.

## 18.4 What "good" looks like at the end

Not a bigger system. A smaller one that is honest:

- Correctness decided by **executed tests**, not opinion
- Divergences reported with **counterexamples a student can run**
- Feedback naming a **specific concept** and a **specific resource section** — never a fabricated URL
- Mastery estimates that are **variant-conditioned** and ship with their observation counts
- Duration measured by a **declared, versioned, reproducible method**
- A judge whose agreement with ground truth is a **measured number**
- A profile you can **wipe and replay**
- Every deferred component with a **named trigger**

Six deterministic components, two LLM agents, one honest architecture. That is a better result than three agents and a chatbot, and it is a better presentation.

---

*Every recommendation above is a proposal, not a mandate. Where this document conflicts with a supervisor decision, the supervisor decides — but record the decision in `DECISIONS.md` rather than letting the documentation drift, because that drift is what cost this project a full session once already.*
