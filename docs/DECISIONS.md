# DECISIONS.md

> **Append-only.** Never edit a past entry — supersede it with a new one that references it.
> An edited decision log is a log you cannot trust, and the whole point of this file is that
> it can be trusted six weeks later when someone asks *"why did you do it that way?"*
>
> **This is the viva answer sheet.** Every entry is a ready-made answer to a supervisor
> question. That is also why it must stay small: pad it with implementation notes and the
> real decisions get buried.

## What belongs here

- An architectural or interface choice, and the alternative rejected.
- A divergence between the code and the design documents, and how it was resolved — or
  that it was not.
- A technology choice, with cost and complexity stated.
- A deliberate deviation from the design documents.
- A scope decision: something deferred, cut, or refused.

## What does **not** belong here

What was implemented today (→ `HANDOFF.md`). A bug fixed (→ the git log). A task completed
(→ `STATUS.md`). A finding from reading (→ `docs/reading/`).

## Entry format

```markdown
### D-<nnn> — <one-line title>
Date:        <YYYY-MM-DD>
Status:      OPEN | DECIDED | SUPERSEDED by D-<nnn>
Context:     <the situation forcing a choice — 1–2 lines>
Decision:    <what was chosen>
Alternative: <what was rejected, and why>
Cost:        <what this makes harder or more expensive>
Defence:     <the one sentence to say when asked to justify it>
```

Roughly eight lines. If an entry needs thirty, the reasoning belongs in `docs/reading/` or a
module document, and the entry should point at it.

---

## Inherited decisions

These were made before the internship's build phase and are recorded in `CLAUDE.md` and
`vdel_complete_design_document.md`. They are listed here **by reference only** so this log
is a complete index without duplicating the source. Do not re-litigate them; if one needs
revisiting, write a new entry that supersedes it.

| Ref | Decision | Where it is argued |
|---|---|---|
| I-01 | Auditability is a functional requirement | `CLAUDE.md` §1 |
| I-02 | BKT, not EWMA (dropped), not DKT (rejected as uninterpretable) | `CLAUDE.md` §8 |
| I-03 | Blackboard architecture — agents coordinate through data, never conversation | `CLAUDE.md` §4 |
| I-04 | Event sourcing — `traces` append-only, `learner_profile` derived | `CLAUDE.md` §4 |
| I-05 | Land raw first — feature formulas will change, raw events must survive them | `CLAUDE.md` §4 |
| I-06 | JSONB over full normalisation while the profile's shape is still moving | `CLAUDE.md` §6 |
| I-07 | Telemetry source is Anas's own GitHub repos; no synthetic generator, no CodeNet | `CLAUDE.md` §2 |
| I-08 | Fast path deterministic / slow path one weekly LLM job — cost-capped by construction | `CLAUDE.md` §4 |
| I-09 | The Echo Agent is a tracer bullet, not throwaway work | `BUILD_PLAN.md` M2.4 |
| I-10 | M5–M7 deferred, each with a named trigger | `VDEL_v1_Execution_Plan.md` §4 |

---

## Decisions made during the internship

### D-001 — Insert an M1.5 verification pass before M2
Date:        2026-08-10
Status:      DECIDED
Context:     M0/M1 were built across three rewrite passes, the last a verbatim transcription
             of documents unavailable during the first two. Their correctness is asserted by
             `explanation.md`, not established by me. M2, M3 and M4 all sit on those numbers.
Decision:    Spend 0.5–1 day before M2 running the full verification block and re-deriving
             one number by hand for each of V1–V6. Timeboxed hard: 30 minutes per formula,
             then log as OPEN and move on.
Alternative: Start M2 immediately and verify lazily when something looks wrong. Rejected —
             a transcription error found from the top of the M4 stack costs days; found now
             it costs an hour.
Cost:        One day of the six-week budget.
Defence:     "Three of the eleven tests in this repo failed the first time anyone actually
             ran them. I verified the floor before building three milestones on it — and
             re-deriving the formulas by hand is how I can explain them to you now."

### D-002 — Pull M3's benchmark authoring forward into M2's week
Date:        2026-08-10
Status:      DECIDED
Context:     Task 3.2 (author the five benchmark submissions) is pure writing with no code
             dependencies, and it is the task most likely to be squeezed when M3 runs late.
Decision:    Author the five submissions and `ground_truth.json` during M2's week, as
             low-cognitive-load evening work.
Alternative: Keep it inside M3. Rejected — a rushed ground truth corrupts every stability
             number measured against it in M3 and M4.
Cost:        Slight context switching during M2.
Defence:     "The benchmark is the test suite for every later prompt. Rushing it would have
             made every stability figure I report meaningless."

### D-003 — The Sara `spark.joins` discrepancy stays an xfail
Date:        2026-08-10 (inherited from a prior pass; recorded here because it is OPEN)
Status:      OPEN — needs Dr. Ezzatul
Context:     The design document quotes `spark.joins: 0.47 (n=2)` after `[fail, pass]`
             ("fixed in 4h"). Sweeping `item_difficulty` across `[0,1]` with that sequence
             yields 0.591–0.964. 0.47 is reachable only via `[pass, fail]` at difficulty
             ≈0.35, contradicting the narrative. `spark.aggregation` reproduces exactly.
Decision:    Recorded as a strict `xfail` plus a companion test that fails if 0.47 ever
             becomes reachable. Not resolved by parameter tuning.
Alternative: Tune `item_difficulty` or the slip formula until 0.47 appears. Rejected —
             that quietly encodes a possibly-wrong formula to satisfy one anecdote.
Cost:        One permanently red-flagged test until the author answers.
Defence:     "I found a number in the design's worked example that the documented event
             sequence cannot produce. I pinned it with a test rather than tuning until it
             matched, because tuning would have hidden whether the formula or the example
             was wrong."

### D-004 — V4 and V2's alpha gate are reported as structurally degenerate, not fixed
Date:        2026-08-10
Status:      OPEN — confirm with Dr. Ezzatul
Context:     V4 (Learning Pace) is framed cohort-relative; V2 uses a Cronbach's-alpha
             composite gate. The cohort is n=1. Neither has a signal to produce.
Decision:    Report as a structural finding with the trigger for when it resolves (a real
             cohort), rather than manufacturing a synthetic cohort.
Alternative: Generate synthetic peers to make the variables light up. Rejected — explicitly
             forbidden, and it would make the numbers fiction.
Cost:        Two of six variables produce no usable signal in v1.
Defence:     "A cohort-relative variable with a cohort of one has no signal by definition.
             Reporting that is a finding; fabricating peers would have been a fabrication."

### D-005 — The Claude Code setup is built around specification verification
Date:        2026-08-10
Status:      DECIDED
Context:     The project's three documented failures — the invented `problems`/`attempts`
             schema, the mathematically inert BKT update, the fabricated `duration_s` — all
             produced code that ran, passed its own tests, and read as coherent.
Decision:    The setup's centrepiece is a `spec-verifier` sub-agent that quotes code and
             specification side by side and is forbidden from proposing fixes. Three agents,
             two skills, three commands, two hooks — nothing generic.
Alternative: A conventional productivity setup with planner/implementer/reviewer agents.
             Rejected — none of this project's actual failures were speed failures.
Cost:        An extra verification step on every formula change.
Defence:     "The bugs in this project's history were invisible to reading and caught only
             by comparing against the specification. So I automated that comparison."

### D-006 — GitHub data collection deferred
Date:        2026-08-11
Status:      OPEN — revisit before final integration
Context:     `config/roster.yaml` was never created (only `roster.example.yaml` exists) and
             `GITHUB_TOKEN` isn't set up. The database is fully empty — 0 rows in students,
             assignments, raw_commits, raw_workflow_runs, learner_features — despite M1 being
             reported "done." It's also unconfirmed whether the candidate repos have any
             CI/workflow-run history to collect. This blocks M1 DoD's three remaining clauses
             (DAG end-to-end, one `learner_features` row per repo, classifier match rate) and
             blocks real telemetry for M2 onward.
Decision:    Defer real collection rather than seed with placeholder or guessed values. M1
             stays `PARTIAL` in `STATUS.md` until this closes. Deferred, not abandoned.
Alternative: Fabricate a `roster.yaml` with plausible repo names/dates to turn the DoD check
             green. Rejected — a made-up `released_at` would make V4 (Pace) fiction, and this
             project has already shipped invented numbers to the database twice.
Cost:        M1's DoD stays incomplete; M2's fast path has nothing real to wire against until
             this closes.
Defence:     "Rather than fabricate repo data to make a checkbox turn green, I left it open
             and named exactly what's missing — a real roster, a real token, confirmation
             the repos have CI history."

### D-009 — The recurrence rule: "error class" reads as concept; "window" is one assignment
Date:        2026-08-11
Status:      SUPERSEDED by D-011 — the "error class" reading below was wrong; kept verbatim
             as the historical record per this file's append-only rule.
Context:     `vdel_complete_design_document.md` 0.3 says "the same error class twice within
             one assignment opens a weakness immediately." `BUILD_PLAN` 2.2 says "a concept
             failing ≥2 times in a window." Neither is the M2 module document (B.5 gives
             `open_weakness` but no rule for calling it — `docs/reading/2026-08-11-memory-py-
             method-surface.md` finding 1), so this rule had to be built, not transcribed.
Decision:    Read "error class" as **concept**, and "window" as **one assignment**
             (`traces.assignment_id`), not a calendar span. Two authorities (the weakness
             schema's `"concept"` key, `BUILD_PLAN`'s own wording) against one dissenting
             phrase from the earlier design phase that also specified EWMA mastery — already
             superseded by BKT (`CLAUDE.md` §8) — so the dissent doesn't carry equal weight.
             The assignment-scoped window follows `CLAUDE.md`'s existing
             `assignments.concepts[]` boundary rather than inventing a time-based one.
Alternative: Dedup on the raw `error_class` string from `error_classifier.py`, or use a
             rolling time window (e.g. 14 days, matching `learner_features.window_days`).
             Rejected — no document specifies a duration, and inventing one would be exactly
             the kind of unstated number this project's invariants forbid.
Cost:        A concept failing once in each of two different assignments never triggers this
             rule, even though a human tutor glancing at both might call that a pattern.
             Accepted because it is what the sources, read together, actually say.
Defence:     "Two sources use 'concept', one dissenting phrase is from a superseded design
             phase, and the assignment-scoped window reuses a boundary the schema already
             has rather than inventing a time span nothing in the documents specifies."

### D-010 — Weakness IDs are `w-{trace_id}`, not a length-based counter
Date:        2026-08-11
Status:      DECIDED
Context:     B.5's `open_weakness` mints `f"w-{len(weaknesses)+1:03d}"`. Two concurrent opens
             for the same student could both read the same array length and produce the
             identical id — the same category of bug D-007 fixed for mastery, here applied
             to identity instead of arithmetic.
Decision:    Log the opening trace first, then derive the weakness id from its `trace_id`
             (a Postgres `BIGSERIAL`) — collision-free by construction. No document specifies
             the ID *format*, only that it is "a stable handle" (`vdel_complete_design_
             document.md` 2.4); `reflection.py`'s validation checks membership in
             `existing_weakness_ids`, never format, so nothing downstream depends on
             zero-padded sequential IDs.
Alternative: Keep the counter; accept the collision risk as academic at a cohort of one.
             Rejected — the fix costs nothing (the trace is already being written) and the
             failure mode, once a real cohort exists, is two different weaknesses sharing an
             id and silently overwriting each other in the array.
Cost:        Weakness IDs are no longer human-sequential (`w-8241`, not `w-014`) — cosmetic,
             not a documented requirement anywhere.
Defence:     "IDs derived from an already-unique, already-monotonic column cost nothing and
             remove a collision case the original counter had. Nothing downstream reads the
             format, only membership."

### D-011 — D-009 corrected: the recurrence rule is wired to `recurrence_check`, error_class-
             keyed, not concept-keyed
Date:        2026-08-11
Status:      DECIDED
Context:     D-009's "two authorities vs. one superseded dissent" tally was wrong. It never
             checked whether the rule already had an implementation. `variables/error_
             frequency.py`'s `recurrence_check` — already transcribed from `VDEL_Modules_1_2_
             Build.md` Variable 6, tested (`tests/test_variables.py`), and cited to Becker
             2016 (Repeated Error Density) — counts by the raw `error_class` string, not
             concept. `docs/explanation.md §7.6`, written in an earlier session, names it
             explicitly: *"this function exists in the module now but isn't wired to
             anything yet... this is the seam it will plug into."* Caught by `spec-verifier`,
             which demonstrated concretely: `classify_error()` maps both `'ambiguous column'`
             and `'cartesian product|cross join'` to the same concept (`spark.joins`) but
             they are different `error_class` strings. Under D-009's concept-level reading,
             one occurrence of each opens a weakness; under `recurrence_check`'s error_class-
             level reading, it does not — a real behavioral divergence, not cosmetic, pinned
             by `test_two_different_error_classes_on_the_same_concept_do_not_recur`.
Decision:    `apply_recurrence_rule` now calls `recurrence_check(counts)` directly rather
             than re-implementing the ">=2" threshold — one implementation of that check, not
             two that must be kept in agreement by hand (the same reasoning D-007 applied to
             mastery). `RECURRENCE_THRESHOLD` is removed: the threshold lives inside
             `recurrence_check`, not as a second, redundant constant in `memory.py`.
             `ci_run` trace payloads now need `error_class` alongside `conclusion` and
             `item_difficulty`. The resulting weakness stays concept-tagged — the schema has
             no `error_class` field — only the trigger's counting key changed.
Alternative: Keep concept-level counting and mark `recurrence_check` superseded, dead code.
             Rejected — it discards a cited, literature-grounded distinction on no stronger
             authority than `BUILD_PLAN 2.2`'s looser wording, and contradicts this project's
             own prior documented intent for the seam.
Cost:        `apply_recurrence_rule`'s signature grows an `error_class` parameter; whoever
             eventually wires the fast path (piece 5+) must now write `error_class` into
             every `ci_run` trace, a third payload requirement alongside `conclusion` and
             `item_difficulty`.
Defence:     "A spec-verifier check found I'd built a parallel implementation of a rule that
             already existed, tested, cited, and — in my own earlier session's notes —
             already named as the exact seam to plug into. I corrected it and kept the
             original decision on record rather than quietly rewriting it."

### D-012 — The rebuild taxonomy: four ways a profile column becomes authoritative
Date:        2026-08-12
Status:      DECIDED
Context:     The M2 DoD is "wipe `learner_profile`, replay traces, get the identical profile
             back." Earlier notes framed this as a two-way split — mastery/weaknesses
             *recomputed*, reflections *recovered*. Implementing it showed the split is
             four-way, and that weaknesses do **not** belong on the recomputed side.
Decision:    `rebuild_from_traces` derives each column its own way:
               - `mastery` — **recomputed** from `ci_run` traces through BKT. A pure
                 function, so deriving it from first principles is safe. Calls
                 `_replay_all_mastery`, the same helper `rebuild_mastery_from_traces` uses
                 (one implementation of the mathematics, per D-007).
               - `weaknesses` — **replayed** from their own lifecycle traces
                 (`weakness_opened`, `intervention_linked`, `reflection_run`), NOT
                 re-derived by re-running the recurrence rule.
               - `reflections` — **recovered** from `reflection_run` payloads.
               - `session_digest` — **recovered** as pointers to `session_summary` traces.
               - `features_ref` — **re-derived** from `learner_features`' latest row, which
                 is what CLAUDE.md §6 says the column means.
Alternative: Re-derive weaknesses by re-running the recurrence rule over `ci_run` traces.
             Rejected for two concrete reasons, not stylistic ones. (1) It would
             **resurrect closed weaknesses**: `open_weakness` only ever writes
             `status="open"`, and closing/escalating happens later from an LLM reflection,
             so a pure re-derivation has no way to know a weakness was closed — every
             closed one would come back open. (2) It would **change every id**: `w-{trace_id}`
             is tied to its opening trace, so re-deriving means new traces, new ids, and
             every `interventions` entry and coach hint already recorded against a weakness
             would point at an id that no longer exists. Both verified by mutation
             (`m3_ignore_status_transitions`, `m4_no_intervention_replay`).
Cost:        The profile is not a pure function of the current code plus raw events — for
             weaknesses it is a function of the recorded decisions. If the recurrence rule
             changes, old weaknesses reflect the old rule. That is correct for an audit
             trail ("this is what we decided then") but it means a rule change needs a
             deliberate re-run of the fast path over history, not just a rebuild.
Defence:     "Different columns are authoritative in different ways, and saying so is
             stronger than claiming the whole profile is deterministic. Mastery is
             recomputed because BKT is a pure function. Weaknesses are replayed from their
             lifecycle log, because re-deriving them would resurrect every closed weakness
             and invalidate every id an intervention points at. Reflections can only be
             recovered, because an LLM wrote them."

### D-013 — `opened_at` and reflection `ts` come from the trace's own `ts`
Date:        2026-08-12
Status:      DECIDED
Context:     `traces.ts` defaults to the database's `now()`. `open_weakness` originally set
             the weakness's `opened_at` from `datetime.now(UTC)` — a separate clock read,
             measured **22ms** away from the trace's `ts` on this machine. Since a rebuild
             can only recover `opened_at` FROM the trace, the live path and the rebuild
             would disagree in exactly that field, and the DoD would fail on it. B.5 and
             B.7 both write the literal string `"now"` there, so neither was a usable model.
Decision:    `_insert_trace` returns `(trace_id, ts)`, and `open_weakness` takes `opened_at`
             from that `ts`. Same for a reflection's `ts` when `reflection.py` is built —
             recorded here as a requirement on it, since the rebuild already reads it that
             way. Live path and rebuild agree by construction rather than by luck.
Alternative: Exclude timestamp fields from the DoD's comparison. Rejected — it would make
             the proof weaker precisely where it is most quotable ("identical, byte for
             byte"), to avoid a two-line fix.
Cost:        `_insert_trace`'s signature changed, so its four call sites unpack a tuple.
Defence:     "The profile's timestamps come from the same clock as the traces they are
             derived from, so wipe-and-replay reproduces them exactly. Reading the wall
             clock separately put them 22 milliseconds apart, which is enough to break the
             one property the whole design is defended on."

### D-014 — `profile_update` traces carry a `payload.action` discriminator
Date:        2026-08-12
Status:      DECIDED
Context:     `_replay_weaknesses` must distinguish a mastery `profile_update` from a
             weakness-lifecycle one. **No document specifies a payload vocabulary for
             `profile_update`** — B.5 just writes `log_trace(..., "profile_update", result)`
             with the mastery result dict. Flagged by `spec-verifier` as invented structure
             (correctly), so it is recorded rather than left implicit.
Decision:    `open_weakness` and `link_intervention` tag their traces with
             `payload.action` = `weakness_opened` / `intervention_linked`;
             `update_mastery`'s deliberately carries no `action` key, which is how the
             replay filter excludes it. Named as module constants so the write sites and the
             filter cannot drift.
Alternative: (a) Promote both to first-class `KINDS` members — cleaner and indexable, and
             the kind-coverage guard would force a mastery decision about each, but it
             expands the documented trace vocabulary, a larger invention than a payload
             field. (b) Infer from payload shape (`weakness_id` vs `p_mastery`) — invents no
             vocabulary but breaks silently the moment a payload shape changes, and silent
             breakage in the replay path is the failure mode this module exists to prevent.
             (a) remains the clean migration if these ever need indexing.
Cost:        A cross-component contract: anything that later writes a weakness transition
             (`reflection.py`'s close/escalate, the staleness job) must follow the same
             convention, or its transition will not replay and the profile will silently
             disagree with its own log.
Defence:     "It lives in `payload JSONB`, which the design document itself calls the
             'flexible letter' of a 'structured envelope, flexible letter' pattern — the
             typed columns are the envelope, the payload is meant to evolve. So it is an
             addition inside a space the design sanctions, not a schema change. I recorded
             it because a future component has to honour it."

### D-007 — `update_mastery` in Modules_3_9 B.5 drops Beta state; fixed by replay
Date:        2026-08-11 (local fix implemented 2026-08-11, M2 piece 2)
Status:      OPEN — the upstream document defect still needs its author. The local fix has
             shipped: `memory/memory.py` recomputes by replay, and
             `test_confidence_grows_with_evidence` is the regression test. Reintroducing
             B.5's partial-state restore fails it (verified by mutation). What remains open
             is whether B.5 itself gets corrected, which is the document author's call.
Context:     B.5's `update_mastery` restores `p_mastery` and `n_obs` from the profile, but
             `MasteryState` has five fields — `a`, `b` (the Beta posterior) and `history` are
             dropped on every call. Measured, replaying six consecutive passes:

               n_obs | confidence, B.5 as written | confidence, replay
                   1 |                      0.286 |              0.286
                   2 |                      0.286 |              0.468
                   5 |                      0.286 |              0.702
                  10 |                      0.286 |              0.828
                  20 |                      0.286 |              0.907

             Confidence never moves and `ci90` is a constant pair, so **invariant 8 is
             structurally violated**: `n` is carried correctly while the interval that gives
             `n` its meaning is not. `p_mastery` is unaffected, which is why it reads as
             plausible. It also means B.8's headline demo cannot pass with B.5's own code —
             the incremental path reports confidence 0.286 / ci90 [0.229, 0.998] where replay
             reports 0.74 / [0.736, 1.0] for the same six events. Compounding it, `rebuild`
             replays at default difficulty 0.5, so `p_mastery` diverges too once any update
             uses a non-default difficulty.
Decision:    Make `update_mastery` and `rebuild` **one code path**: replay the concept's
             traces on each update, with the profile's `mastery` as a pure cache of the replay
             result. The replayed trace-kind set is a named constant with a test, so M4's
             `verdict` traces cannot silently fall outside it.
Alternative: Persist `a`, `b`, `history` into the profile JSONB — O(1), no extra query, and
             perfectly defensible. Rejected because it fixes today's instance while keeping
             the structure that caused it: two implementations of the same mathematics that
             must be kept in agreement by hand. Replay makes the M2 DoD true by construction
             rather than true because two implementations happen to agree.
Cost:        One query per mastery update. Negligible at n=1; if it ever matters the fix is a
             checkpoint, and that is a clean seam. Forces `ci_run` payloads to carry
             `conclusion` and `item_difficulty` — arguably a benefit, since it makes the
             traces genuinely sufficient, which is what event sourcing claims anyway.
Defence:     "The design document's own mastery update drops part of the model's state, so
             confidence freezes at 0.286 no matter how much evidence accumulates. I found it
             by executing both paths and comparing, pinned it with a table, and fixed it by
             removing the second implementation rather than patching it."

### D-008 — `session_digest` and `sessions.summary` are a transcription gap in sql/05
Date:        2026-08-11
Status:      DECIDED
Context:     B.5's `get_profile` selects `learner_profile.session_digest`, and B.6 writes
             `sessions.summary`. Neither column exists in the live `sql/05_memory_tables.sql`,
             so transcribing B.5 verbatim raises `ProgrammingError` on its first call. Both
             columns appear in `Modules_3_9` B.4, are used in B.5/B.6, and appear in
             `vdel_complete_design_document`. CLAUDE.md §6 and the live DDL are the only two
             sources missing them.
Decision:    Treat as a transcription gap in `sql/05`, not a design conflict — three sources
             agree against two. Add both via idempotent `ALTER TABLE ... ADD COLUMN IF NOT
             EXISTS`, and add them to the `CREATE TABLE` bodies so a from-scratch build
             matches. Update CLAUDE.md §6. Leave `sessions.trace_count` (present live, absent
             from the document) alone — additive drift is harmless and dropping a column is
             destructive. Ships as its own commit before `memory.py`.
Alternative: Escalate to Dr. Ezzatul as a genuine spec conflict, or defer the columns to M2.3
             and omit `session_digest` from `get_profile`. Both rejected: the evidence is
             lopsided enough that it is a transcription slip rather than a design disagreement,
             and deferring leaves a landmine in the one module that must be trustworthy.
Cost:        A schema change touching a shared data contract, so it needs its own review. Two
             columns exist before anything writes to them.
Defence:     "Three independent sources declare these columns and two omit them, and the code
             in the same document reads and writes them. That is a transcription gap in one
             file, not a design decision anyone made — so I aligned the DDL rather than
             escalating it."

### D-015 — The Echo Agent matches the live `memory.py` door, not D.5's call to it
Date:        2026-08-12
Status:      DECIDED
Context:     `Modules_3_9` D.5 line 941 has the Code Agent call
             `mem.update_mastery(student_id, concept, correct=..., item_difficulty=...,
             parent_trace_id=tid)`. The live `update_mastery` takes **neither** `correct` nor
             `item_difficulty`: D-007 replaced the outcome-folding design with replay from
             the log. Verified by execution, not by reading — `TypeError: Memory.
             update_mastery() got an unexpected keyword argument 'correct'`. D.5 predates
             D-007, so any file transcribing it verbatim fails on its first mastery update.
Decision:    `agents/echo_agent.py` logs the evidence trace first, then calls
             `update_mastery(student_id, concept, parent_trace_id=trace_id)`. The interface
             Echo exposes is D.5's; the memory calls inside it are the live door's.
Alternative: Restore `correct`/`item_difficulty` on `update_mastery` so D.5 transcribes
             cleanly. Rejected outright — that is D-007 in reverse, and would refreeze
             `confidence` at 0.286 and re-split the live and rebuild paths.
Cost:        **This is the third place D-007's consequence propagates**, after
             `update_mastery` itself and `rebuild_mastery_from_traces`. M4 will hit it too:
             whoever writes `agents/code_agent.py` cannot transcribe D.5's mastery block and
             must log evidence before recomputing. Recorded here so that is discovered by
             reading this file, not by a TypeError in week four.
Defence:     "The design document's Code Agent calls a memory method with two arguments that
             method no longer takes, because an earlier decision replaced outcome-folding
             with replay. I matched the working code rather than the stale document, and
             recorded that M4 has to do the same."

### D-016 — Echo scores only the criterion CI actually evidences
Date:        2026-08-12
Status:      DECIDED
Context:     `BUILD_PLAN` 2.4 specifies "CI failed → outcome 0, passed → 0.75". Those numbers
             are on an unstated [0,1] scale; the Code Agent rubric is anchored **0/2/4**, so
             0.75 is not a rubric score. Separately, a green CI run is evidence about
             correctness only — it says nothing about readability, approach or idiomatic
             Spark, and scoring those from it would be fabricated judgement (invariant 6).
Decision:    Correctness maps 4 on pass / 0 on fail. The other three criteria take the middle
             anchor **2** with `confidence="low"`, following the convention
             `orchestrator._missing_perf_verdict()` already uses for an agent with no
             information (`PerfScores(efficiency=2)`, `confidence="low"` — verified present).
             `BUILD_PLAN`'s literal 0/0.75 is preserved in the trace payload as
             `echo_outcome`, on its own scale, so it is recorded rather than reinterpreted.
             4/0 rather than 2/0 is chosen so D.5's `correct = correctness >= 3` reproduces
             Echo's binary intent unchanged when M4 swaps the internals.
Alternative: (a) Map pass → 2 ("right on happy path"), which is arguably the more honest
             anchor since CI green does not prove edge-case handling. Rejected because it
             sits below D.5's `>= 3` line, so the later mapping would read every Echo pass as
             a BKT failure — an honest score producing a dishonest downstream. (b) Score all
             four criteria from the CI result. Rejected as fabrication.
Cost:        Every Echo verdict is permanently `confidence="low"`, so M6's Reviewer will flag
             each one `low_confidence:code`. That is correct — Echo is not a trustworthy
             judge — but it means the flag carries no signal until M4 lands.
Defence:     "CI tells you whether the tests passed. It does not tell you whether the code is
             readable, so I scored what the evidence supports and marked the rest neutral and
             low-confidence, using the convention the design document already uses for an
             agent that has nothing to say."

### D-017 — Echo does not make verdicts mastery evidence ("Option A")
Date:        2026-08-12
Status:      DECIDED
Context:     `BUILD_PLAN` 2.4 wants the tracer bullet to exercise the whole loop, *including*
             the mastery update. But `memory.MASTERY_TRACE_KINDS` is `{"ci_run"}` and
             `NON_MASTERY_KINDS["verdict"]` states in prose that the mapping from a 0/2/4
             rubric score to a BKT pass/fail "is a decision that has not been made". So a
             `verdict` trace alone moves no mastery (verified: `'verdict' in
             MASTERY_TRACE_KINDS` is False).
Decision:    Echo logs its `verdict` as a **child** of the `ci_run` it judges
             (`parent_trace_id`) and then calls `update_mastery`, which replays that
             `ci_run`. Mastery therefore moves because of the CI event, never because of
             Echo's opinion. Pinned by two tests: mastery reaches the hand-computed 0.8126
             from the `ci_run`, and a verdict with no `ci_run` behind it moves nothing. A
             third test feeds Echo a "failure" while the log holds a pass and asserts the log
             wins — a direct regression guard against re-wiring the outcome in.
Alternative: Add `verdict` to `MASTERY_TRACE_KINDS` now, with D.5's `correctness >= 3` rule.
             Genuinely specified in the document, and M4 will likely do exactly this — but it
             changes replay semantics, which means re-verifying every rebuild test, in a
             milestone whose DoD *is* the rebuild. Deferred to M4, where the rubric that
             justifies the mapping actually exists.
Cost:        Echo's own scores are inert: nothing downstream consumes them until M4. The loop
             is proven end to end, but the judge in the middle of it is decorative.
Defence:     "The tracer bullet proves the wiring without inventing the one mapping the
             memory module explicitly says nobody has decided yet. Mastery moves from the CI
             event, and I have a test that feeds the agent the opposite answer to prove the
             log wins."

### D-018 — Does invariant 6 bind a deterministic agent? OPEN
Date:        2026-08-12
Status:      **OPEN** — a question for Dr. Ezzatul. Current behaviour ships; the reading it
             relies on is deliberately *not* treated as authorised.
Context:     Invariant 6: "Every rubric score carries verbatim evidence quotes,
             string-matched against the actual submission. A fabricated quote rejects the
             verdict." Echo emits four rubric scores and **no quotes** — it reads no code. It
             cites the `ci_run` trace instead, via `parent_trace_id` and a payload
             `evidence_source`. `reviewer` called this "legitimate, not rationalizing, but
             not obviously authorized either."
Decision:    None yet. The file operates under the narrow reading — that the string-matching
             clause governs *LLM-authored* verdicts, its named defence being hallucination,
             and that a deterministic agent with no generative step satisfies the invariant's
             purpose by citing the event it judged. That reading is recorded in the module
             docstring and marked OPEN there too. **M4 must not lean on it** for its own
             no-quote cases (e.g. a non-assessing CI conclusion) until this is settled.
Alternative: Read invariant 6 unconditionally, in which case Echo must stop emitting scores
             it cannot quote — collapsing to correctness only, with the other three criteria
             absent rather than anchored. That changes the interface M4 inherits, which is
             why it is worth an explicit answer rather than a quiet assumption.
Cost:        A precedent left unset. Whichever way it resolves, M4's `validate_evidence` and
             the Reviewer's `evidence:code_agent_unmatched` flag inherit it.
Defence:     "Invariant 6 is written to defend against hallucinated quotes. My rule-based
             agent cannot hallucinate — it has no generative step — so I made it cite the
             event it judged instead of a quote. But the invariant is written unconditionally
             and I did not want to quietly narrow it, so I shipped the behaviour and logged
             the reading as an open question rather than as a decision I made alone."

### D-019 — M3 has no Hanafi split; a scope correction, not a design change
Date:        2026-08-12
Status:      DECIDED
Context:     `BUILD_PLAN.md`'s M3 header reads "parallelisable with M1–M2 (split with
             Hanafi)", and `DEVELOPMENT_MAP.md` §C.5/§D.4 build on that assumption — Hanafi
             running some benchmark candidates in parallel with Anas. That split is not
             happening: Anas runs every candidate himself.
Decision:    M3's benchmark work (3.1–3.3: `system/llm.py`, the five submissions, the 3-runs
             protocol) is solo. Recorded here as a scope correction — what actually happens,
             not a change to how M3 is done or what it measures. `BUILD_PLAN.md`'s M3 header
             and `DEVELOPMENT_MAP.md` §C.5/§D.4 still describe the old assumption and are
             *not* corrected by this entry — flagged in `HANDOFF.md` as a check before M3
             starts, left for a deliberate pass rather than an incidental one.
Alternative: Leave the record as-is and treat the split informally as "not happening this
             time". Rejected — `DEVELOPMENT_MAP.md` §C.5 uses the split as part of its
             argued reasoning for M3's ordering ("BUILD_PLAN flags it as the natural split
             point with Hanafi"), so a silently wrong assumption sits inside a defended
             argument, not just a schedule.
Cost:        None to the method — M3's protocol (3 runs × candidates × 5 submissions, CodeJudgeBench
             findings) is unchanged. Whatever calendar time the plan assumed from parallel
             execution is gone; task 3.4 (`RECOMMENDATION.md`, written *with* Hanafi for
             sign-off and the PDPA note) is untouched by this entry — that collaboration is
             separate from running the benchmark itself and was not part of the correction.
Defence:     "The build plan assumed Hanafi and I would split M3's benchmark runs in
             parallel. That isn't happening — I run every candidate myself — so I corrected
             the record rather than let the plan's reasoning lean on help that isn't coming."

### D-020 — `system/llm.py`'s cache key: docstring, code and two plan documents disagree. OPEN
Date:        2026-08-12
Status:      **OPEN** — pre-implementation, discovered by a wide-read pass before writing
             `system/llm.py` (`docs/reading/2026-08-12-llm-gateway-spec.md`).
Context:     Four sources, four different answers for what `system/llm.py`'s response cache
             keys on. `VDEL_Modules_3_9_Build.md:1709`'s docstring says
             `(submission_hash, prompt_version, model)`. Its own code, `:1732-1734`, hashes
             `f"{model}:{temperature}:{prompt}"` — model + temperature + full prompt text,
             not `submission_hash`/`prompt_version` at all. `VDEL_v1_Execution_Plan.md:155`
             says `(prompt_hash, model, temperature)` — matches the code's shape, not the
             docstring's. `BUILD_PLAN.md:190` says "keyed by prompt hash" — simplest, roughly
             matches the code. The same file's retry logic has a parallel drift: its
             docstring claims `llm_call` does "one corrective retry on invalid JSON"; the
             code shows retry implemented by the *caller* (`agents/code_agent.py:922-929`),
             not inside `llm_call` at all.
Decision:    None yet. Recorded OPEN rather than resolved by picking the code (the D-007/
             D-008 default) unilaterally, because unlike those two, no execution against a
             live `system/llm.py` has confirmed anything — the file doesn't exist yet, so
             there is no "live code" to defer to, only conflicting text.
Alternative: Build against the code block silently, on the D-007/D-008 precedent ("trust
             what runs, not what's commented"). Not taken — recorded as OPEN instead so the
             choice of key is a stated decision when `system/llm.py` is actually written,
             not an assumption inherited from a stale docstring nobody looked at twice.
Cost:        None yet — blocks nothing until `system/llm.py`'s cache function is written.
Defence:     "Before writing the gateway, I read all four places its cache key is described
             and found they disagree, including the module's own docstring against its own
             code. I logged it rather than silently picking one, because the last two times
             a docstring disagreed with its code in this project (D-007, D-008), the code was
             right — but this is the first time there's no live code yet to confirm that."

### D-021 — M3's DoD disagrees across BUILD_PLAN.md and VDEL_v1_Execution_Plan.md. OPEN
Date:        2026-08-12
Status:      **OPEN**, and sharper after D-019.
Context:     `VDEL_v1_Execution_Plan.md:172`: "The memo is signed off by both you and Hanafi
             · rerunning the benchmark reproduces the matrix." `BUILD_PLAN.md:209-211`: "Memo
             signed off by both · re-running the benchmark reproduces the matrix · the
             benchmark set is committed as the permanent canary." Same tier per CLAUDE.md's
             authority hierarchy (both below the four module documents), so this doesn't
             resolve by precedence. And D-019 already establishes the "signed off by ...
             Hanafi" clause rests on a split that isn't happening for the benchmark-running
             half of M3 — task 3.4's sign-off collaboration is untouched by D-019, but the
             DoD clause as literally written doesn't distinguish "ran the benchmark" from
             "wrote the memo", so it's unclear which act the sign-off clause is gating.
Decision:    None yet. Flagged rather than picked, because the third clause (benchmark set
             committed as permanent canary) is easy to just also satisfy — it costs nothing
             to commit the five submissions regardless of which DoD wording wins — but the
             sign-off clause's meaning needs an actual answer before M3's DoD can be run and
             called passing.
Alternative: Assume `BUILD_PLAN.md` wins (it's the file CLAUDE.md calls "the ordered task
             list and each milestone's DoD"). Not taken unilaterally — plausible, but
             `VDEL_v1_Execution_Plan.md` is one of the source-of-truth documents CLAUDE.md
             says wins in a conflict with BUILD_PLAN, which points the other way. Genuine
             tie, logged rather than broken by assumption.
Cost:        Blocks nothing until M3's DoD is actually run.
Defence:     "The two milestone documents state M3's DoD differently, and CLAUDE.md doesn't
             clearly rank one over the other for this kind of disagreement. I logged both
             verbatim rather than picking, especially since one of the disagreeing clauses
             now interacts with a scope change I made this session."

### D-022 — Schema validation and the corrective retry live in the gateway, not the caller
Date:        2026-08-12
Status:      DECIDED — a deliberate divergence from `Modules_3_9` D.5's executable code.
Context:     Three sources, and the module document contradicts *itself*. Its gateway
             docstring (`Modules_3_9:1707`) lists "one corrective retry on invalid JSON" as a
             gateway responsibility, and `BUILD_PLAN.md:189` puts "pydantic validation +
             single corrective retry policy" in task 3.1, which *is* `system/llm.py`. But
             its actual code retries in the **caller**: `agents/code_agent.py` (D.5,
             922-929) calls `llm_call` twice, and `llm_call` (1743-1782) contains no retry
             logic at all. **CLAUDE.md's "the documents win" tiebreak does not apply**, because
             the disagreement is inside one document rather than between BUILD_PLAN and it.
Decision:    Gateway-side. `judge(prompt, schema)` validates, retries once on failure, and
             raises `SchemaValidationError` carrying both attempts' `CallRecord`s. Two
             reasons: (a) `judge` returning a validated `T` is only possible if the gateway
             holds the schema, which is what lets agents stop hand-rolling parse-and-retry;
             (b) caller-side means every agent reimplements invariant 5, and the first one to
             forget breaks it silently — the exact failure class as D-007's two-path drift.
             Paired with generic-over-schema: the gateway validates, agents own the shape, so
             `agents/echo_agent.py`'s live `EchoVerdict` contract is untouched.
Alternative: Transcribe D.5 verbatim and retry in `code_agent.py`. Rejected — it is the
             document's least-supported reading (its own prose and BUILD_PLAN both say
             otherwise), and it makes invariant 5 a per-agent convention rather than a
             property of the one door every LLM call passes through.
Cost:        A real divergence from printed code, so `spec-verifier` will report DIVERGENT
             against D.5 and should — this entry is the answer. M4's `code_agent.py` must NOT
             transcribe D.5's try/except retry block; it calls `judge` and lets the gateway
             own it. Second place D.5 cannot be transcribed verbatim, after D-015.
Defence:     "The design document's gateway docstring says it retries, its code retries in
             the agent instead, and the build plan sides with the docstring. Since the
             document disagrees with itself, I couldn't defer to it — so I decided, and put
             the retry where it only has to be written once."

### D-023 — `google` dropped from MODEL_TIERS; Provider is an enum validated at import
Date:        2026-08-12
Status:      SUPERSEDED by D-032 — Anas asked for a Google/Gemini branch directly on
             2026-08-19; the "enum validated at import" mechanism this decision established
             stands unchanged, only its google-specific conclusion is reversed. Kept verbatim
             below as the historical record per this file's append-only rule.
Context:     `Modules_3_9`'s `MODEL_TIERS` (1719-1729) declares four providers —
             `anthropic`, `openai`, `google`, `qwen_local` — but `llm_call`'s if/elif chain
             (1753-1778) serves three and ends in `raise ValueError(f"unknown LLM_PROVIDER
             {PROVIDER}")`. Setting `LLM_PROVIDER=google` therefore *succeeds* at model
             lookup and dies at call time, after the prompt is assembled and paid for.
Decision:    `Provider` is a `StrEnum` with the three servable providers, validated at import,
             and `google` is removed from the tier table. An unservable provider becomes a
             startup failure rather than a runtime one — the same argument the
             `judge`/`generate` split makes for temperature: a constraint the type system can
             hold should not be left to a runtime branch.
Alternative: Keep `google` and add a fourth branch. Rejected as scope invention — no document
             asks for a Google integration, and M3's job is to *measure* candidates, not to
             add one. Keeping it listed-but-broken was also rejected: a config value that
             looks supported and isn't is worse than its absence.
Cost:        **Google is not a benchmark candidate, and `benchmark/RECOMMENDATION.md` must say
             so explicitly** rather than omitting it. A candidate named as unevaluated is
             defensible; a candidate silently dropped looks like it was never considered.
Defence:     "The design document lists a provider its own code can't serve, so selecting it
             fails after you've already built the prompt. I made the provider a validated
             type so that's a startup error, and I record Google as not evaluated rather than
             pretending it was on the list."

### D-024 — Model IDs and prices are unstamped until BUILD_PLAN 3.4; retry rate must be measured
Date:        2026-08-12
Status:      DECIDED (the stamping requirement); the values themselves stay `TODO(verify)`.
Context:     `MODEL_TIERS` ships concrete model ids and `cohort_cost` ships concrete prices
             (`price_in_per_1k=0.003`, `price_out_per_1k=0.015`) and a
             **`json_retry_rate=0.05`** default. None carries a `verified as of` date.
             BUILD_PLAN 3.4 already scopes the research — "current model versions only — the
             method is fixed, only the contestants change" — and requires the memo carry a
             `verified as of <date>` stamp.
Decision:    Model ids stay `TODO(verify)` in `system/llm.py` except two corrected against
             the document's stale values on 2026-08-12: **`claude-sonnet-5` supersedes
             `claude-sonnet-4-5`**, and **`claude-haiku-4-5` is unchanged and still current**.
             OpenAI and Qwen ids are left `TODO(verify)` rather than guessed, per CLAUDE.md
             §10. Prices stay as transcribed but are unusable until stamped.
             **`json_retry_rate` must be MEASURED, not defaulted — a stated requirement on
             `benchmark/run_benchmark.py`, not a note.** It computes the rate from `COST_LOG`
             (`attempt == 2` over `attempt == 1`) and passes it to `cohort_cost` explicitly.
             `CallRecord` carries `attempt` / `schema_valid` / `cache_hit` for exactly this;
             D.5's `_log_cost` records none of them and cannot produce the number.
Alternative: Keep `0.05` as a working default and refine later. Rejected outright — it is an
             invented number inside the one deliverable whose entire purpose is measurement,
             and BUILD_PLAN 3.1 is explicit that the retry rate belongs *in the formula*
             because "a cheap-per-call model with high JSON breakage can be more expensive end
             to end". Defaulting it assumes away the finding M3 exists to produce.
Cost:        `system/llm.py` cannot be run end to end until 3.4 fills the ids in. That is the
             correct order — the gateway's shape does not depend on which models it names.
Defence:     "The cost model's headline claim is that a cheaper model can be more expensive
             once you price its JSON failures. That claim is worthless if the failure rate is
             a hardcoded 0.05, so I made the gateway record every attempt and required the
             benchmark to derive the rate from what actually happened."

### D-025 — `temperature=0` is not representable on every model; send it only where accepted
Date:        2026-08-12
Status:      DECIDED
Context:     Discovered while implementing `system/llm.py`'s bodies, before any code was
             written against it (caught in review, not in production). Claude Sonnet 5 —
             D-024's corrected default-tier model — and every Claude API model 4.7-and-later
             reject an explicit non-default `temperature` parameter with an HTTP 400; only
             omitting the parameter, or passing the provider's own default, is accepted.
             `VDEL_Modules_3_9_Build.md`'s `llm_call` (1743-1782) sends
             `temperature=temperature` unconditionally into every provider branch, with no
             model-dependent logic at all — a transcription of that code would 400 on the
             very model D-024 just chose as the default tier, i.e. on every ordinary `judge()`
             call once the gateway is live.
Decision:    `_call_anthropic` sends `temperature=0.0` explicitly on models that accept a
             non-default value; omits the parameter entirely (using the provider's calibrated
             default) when the resolved model is in `_REJECTS_NONDEFAULT_TEMPERATURE` AND the
             requested value is `0.0` — which covers every `judge()` call, since `judge()`
             only ever asks for `0.0`; and **raises** `ValueError` when the resolved model
             rejects non-default values AND the requested value is genuinely non-zero — which
             only `generate()` can trigger, since only it takes a caller-chosen temperature.
             `judge()`'s reading of invariant 4 therefore widens from "always send a literal
             0" to "never send a non-default sampling parameter", which is what actually holds
             across the whole model family; `generate()`'s reading stays literal — a real
             non-zero request that can't be honoured fails loudly rather than silently running
             at a substituted value the caller never asked for.
Alternative: (a) Send `temperature=0` unconditionally, matching the document verbatim, and let
             the default-tier judging path 400 in production. Rejected — this is exactly the
             failure class `DEVELOPMENT_MAP.md §0` names as the project's recurring risk: code
             that runs, looks plausible, and is wrong in a way nothing catches until it's
             executed for real. (b) Roll the default tier back to `claude-sonnet-4-6`, which
             still accepts an explicit 0, and leave Sonnet 5 out of `MODEL_TIERS` until this is
             resolved gateway-wide. Rejected — D-024 already established Sonnet 5 as current;
             solving the temperature constraint in the gateway is more general than avoiding
             the model that exposed it, and other models the benchmark will compare against
             (Opus 4.7+, Fable 5) have the identical restriction, so the constraint returns
             either way.
Cost:        `_REJECTS_NONDEFAULT_TEMPERATURE` is a hand-maintained set sourced from documented
             per-model breaking changes, not a live capability query — it must be re-checked
             by hand whenever `MODEL_TIERS` gains a model id this file has not seen before, and
             it can go stale silently if a future model's sampling-parameter policy changes
             without this set being updated. `generate()` gains a failure mode (`ValueError`)
             that has no equivalent in the source document at all.
Defence:     "The design document sends temperature unconditionally, which 400s on the exact
             model we'd just chosen as the default. I found this before writing a single test
             against it, not after a live call failed, and made the gateway ask for 0 where the
             provider allows it and settle for 'as close to greedy as this model permits'
             everywhere else — never a silent substitution of some other value."

### D-026 — `benchmark/submissions/` is excluded from `ruff check .` by directory discovery, not by rule
Date:        2026-08-12
Status:      DECIDED
Context:     BUILD_PLAN 3.2 requires a `broken.py` (doesn't run) and a `copy_paste.py`
             (over-engineered, style-inconsistent) submission. Both contain deliberately
             planted lint violations — an undefined name, an unused import, a wildcard
             import — because those are exactly the "verified facts" the M4 tool stage
             (BUILD_PLAN 4.2) is supposed to hand a judge as real findings, not opinions.
             Left alone, those same violations fail `ruff check .`, which every M0–M3 DoD
             and `.github/workflows/ci.yml` treat as a hard gate — the fixtures the
             benchmark needs would permanently break CI.
Decision:    `[tool.ruff] extend-exclude = ["benchmark/submissions"]`. Verified live (not
             just read from ruff's docs): `ruff check .` reports "All checks passed!" with
             the five submissions present, while `ruff check benchmark/submissions/broken.py`
             (an explicit path, exactly how the M4 tool stage will invoke it on one
             submission at a time) still reports F821 on `orders_df`, and the same direct
             check on `copy_paste.py` still reports F401 and F403. `exclude`/`extend-exclude`
             only prunes ruff's own directory *discovery*; it does not apply to a path given
             explicitly on the command line unless `force-exclude = true` is set, which it
             is not here — on purpose.
Alternative: (a) Per-file `# noqa` comments on each intentional violation. Rejected — a
             `noqa` is config baked into the file itself, so it would suppress the finding
             for the M4 tool stage's direct per-file check too, silently deleting the exact
             evidence `broken.py` and `copy_paste.py` exist to provide. (b) Per-file-ignores
             in `pyproject.toml` keyed to these paths. Rejected for the same reason — ignores
             are config, not discovery, so they apply identically regardless of how ruff is
             invoked, unlike `exclude`.
Cost:        `force-exclude` must stay unset (or explicitly `false`) for this to keep working;
             if a future session sets it to simplify some other exclude rule, these two
             fixtures silently stop being lintable by the tool stage and this decision needs
             re-reading. Noted here so that trap is visible before it's hit.

### D-027 — The Code Agent never executes submitted code. No agent ever does. Numbered as invariant 12
Date:        2026-08-13
Status:      DECIDED
Context:     While trying to verify `inefficient.py`/`copy_paste.py`/`subtly_wrong.py` by
             actually running them under PySpark (the user's request, after spec-verifier's
             reading-only pass), it became clear no Spark execution path exists anywhere in
             this project — not in `docker-compose.yml` (Postgres only), not in the tech
             stack (`CLAUDE.md` §9), not in the M4 tool-stage design (`CLAUDE.md` §8's agent
             skeleton names only `ruff`/`sqlfluff`/`ast`). That gap had been implicit —
             "we never got around to building execution" — rather than stated as a boundary.
             It is in fact a boundary: submissions are, by construction, arbitrary
             student-submitted code, and a pipeline that compiles and runs arbitrary
             submitted code is a sandbox-escape and resource-exhaustion surface this project
             has no mitigation for (no container isolation, no resource limits, no network
             policy) and was never designed to need, because the design never intended to
             execute anything in the first place.
Decision:    No agent, now or later, executes submitted code. The tool stage is static
             analysis only — `ruff` over Python, `sqlfluff` over SQL, `ast` parsing — and
             correctness is judged entirely by the LLM reading the code plus whatever the
             static tools report, never by running it and observing behavior. This is
             promoted from an implicit design property to explicit invariant **12**,
             numbered alongside the eleven in `CLAUDE.md` §7, and propagated everywhere the
             invariant count is stated: `CLAUDE.md` itself (§7, the doc-contract table, the
             sub-agent list), `docs/explanation.md` §8, `docs/DEVELOPMENT_MAP.md`, and both
             `.claude/agents/reviewer.md` and `.claude/commands/commit.md`, which now check
             and cite "twelve invariants," not eleven.
Alternative: (a) Leave it as an unstated design property, inferred from what the tool stage
             happens to include. Rejected — that is exactly the shape of the failure this
             session's attempted PySpark verification could have produced: a future session,
             under less scrutiny, "helpfully" adds an execution step to the tool stage
             because nothing on record forbids it. (b) Sandbox submitted code and execute it
             under strict isolation (container, no network, CPU/memory/time limits) as a
             *future* M4+ capability. Not rejected outright — recorded as the named,
             deliberately-not-taken seam: if execution is ever wanted, it requires a new
             decision that revisits this one explicitly, not a quiet addition to the tool
             stage.
Cost:        Correctness detection has a real ceiling this decision accepts on purpose: a
             judge that only reads code can be fooled by something that looks right and
             isn't (exactly what `subtly_wrong.py` is built to test) in a way that one
             actual execution against a fixture would have caught immediately. The project
             accepts that ceiling in exchange for zero untrusted-execution surface — CLAUDE.md
             §1's own governing sentence, "a grade we cannot explain is not a grade we can
             defend," implies auditability first; running arbitrary student code is the kind
             of thing that is hard to defend even when it works.
Defence:     "I never built code execution because the design documents never asked for it —
             the tool stage was always lint-only. What changed today is that I stopped
             treating that as an accident of scope and started treating it as a security
             decision, because I'd nearly built the alternative by hand while trying to
             verify three fixture files, and no line in this project said not to. It's
             invariant 12 now, not a gap."

### D-028 — Fixture verification uses pandas-equivalent translation, not real Spark execution; no Spark dependency added
Date:        2026-08-13
Status:      DECIDED
Context:     D-027 (same session) settled that no agent in this project ever executes
             submitted code. That immediately reopened the question this session had been
             sitting on: how to check `inefficient.py`/`copy_paste.py`/`subtly_wrong.py`'s
             claims about their own output (identical to `clean.py`; diverges only for
             customers with ≥2 orders/month) without doing the thing D-027 just forbade. A
             throwaway `pyspark`/venv install had already been attempted for this and hung
             for 30+ minutes (Spark 4.2.0 vs. this machine's Java 8) before being killed —
             real cost already paid chasing the execution path D-027 rules out on principle.
Decision:    Verification is done by **hand-transcribing each submission's operations into
             pandas** (`scratchpad/pandas_verify.py` — not part of the repo, not a project
             dependency) and running that translation against one shared fixture, rather
             than running the submissions themselves. This is not a workaround standing in
             for the "real" check — it **is** the representative check: reading a
             submission, understanding what it computes, and confirming that understanding
             independently of the specific engine is exactly what a judge-reads-code system
             (D-027) does. Executing the literal PySpark file would have tested something
             the live Code Agent will never do either. `pyproject.toml` gained no `pyspark`
             dependency; `CLAUDE.md` §9's tech stack is unchanged. Both claims were confirmed
             against a fixture with a customer having 1 order and one having 2 orders in the
             same month: `inefficient.py`/`copy_paste.py` produced rows identical to
             `clean.py`; `subtly_wrong.py` matched only on the 1-order-per-month rows and
             fragmented the 2-order row into two wrong ones.
Alternative: (a) Real Spark execution (a throwaway venv, per the earlier discussion).
             Rejected after D-027 — it would have verified the fixtures using a method the
             production system is permanently forbidden from using, so a pass there would
             prove less about the actual Code Agent than the pandas translation does. (b) No
             execution-shaped check at all — trust the docstrings' claims as written.
             Rejected — this project's own history (`DEVELOPMENT_MAP.md` §0: the BKT sign bug,
             the fabricated `duration_s`) is three separate incidents of code that read as
             correct and wasn't; a translation that's actually run and diffed catches the
             same class of error a linter or a read-through can miss.
Cost:        The translation is only as faithful as the person writing it — six explicit
             judgment calls were logged inline in that session's report (date-format syntax
             mapping, `Timestamp` vs. `date` string truncation, dict insertion order,
             attribute-vs-bracket column access, float summation order, and the fixture's own
             shape). The fixture's shape is the one load-bearing call: without a customer
             having ≥2 orders in one month, `subtly_wrong.py` and `clean.py` would look
             identical and the divergence claim would go unfalsified rather than confirmed.
Evidence:    A second fixture (same shape, multi-order month raised from 2 orders to 3) was
             run to rule out an "exactly 2" artifact — same fragmentation, same divergence,
             confirming the bug scales with order count rather than being a pairing
             coincidence. Both fixtures, the full translation script, and both runs' literal
             output are preserved verbatim in
             `docs/reading/2026-08-13-benchmark-submissions-verification.md` rather than
             copied here, per the project's rule against duplicating a fact across two docs.

### D-029 — `benchmark/ground_truth.json`'s on-disk shape, settled with Anas
Date:        2026-08-13
Status:      **DECIDED** — opened OPEN this session by `spec-verifier` (dispatched
             specifically to check `ground_truth.json` against §C.9's shape requirement,
             before the file was written), closed OPEN → DECIDED later the same session by
             Anas's direct confirmation.
Context:     §C.9 never prints an explicit "Output JSON schema" block for `ground_truth.json`
             the way §D.3 does for the agent verdict. The shape is only inferable indirectly
             from `run_benchmark.py`'s pasted reference code: `sub["intended_scores"]
             ["correctness"]` (line 670) implies each submission's ground truth is a
             per-criterion dict keyed at least by `"correctness"` — but §C.9 never states the
             other three keys (`approach`? `approach_and_logic`?), and never states whether
             the file on disk is `{"clean": {...}, ...}` keyed by submission id, or a list of
             `{"id": ..., "intended_scores": {...}}` objects. Separately, the word
             "justification" — the requirement to write "a one-line justification each"
             (`BUILD_PLAN.md` task 3.2) — **does not appear anywhere in
             `VDEL_Modules_3_9_Build.md`**; it is a different document tier's requirement, not
             something §C.9 itself asks for, so whether it's a real field in the file or just
             prose accompanying the numbers is not settled by the module document.
Decision:    A dict keyed by submission id — `clean` / `subtly_wrong` / `inefficient` /
             `copy_paste` / `broken` — each value a dict with exactly four keys,
             `correctness` / `approach_and_logic` / `readability` / `idiomatic_spark`, plus
             one `justification` string per submission (not one per criterion). This was the
             candidate logged under "Alternative" below while OPEN; Anas confirmed it
             verbatim this session, so it is now the decision, not a guess proceeded on
             silently.
Alternative: (a) A list of `{"id": ..., "intended_scores": {...}}` objects instead of a dict
             keyed by id. Rejected — dict-by-id is the simpler lookup `run_benchmark.py` (3.3)
             will do per submission, and nothing in §C.9 implied ordering mattered. (b) Key
             name `approach` instead of `approach_and_logic`, or some other short form.
             Rejected — matched to `CLAUDE.md` §8's rubric table verbatim so the criterion
             names are identical everywhere they appear (rubric, prompt, this file). (c) A
             `justification` per criterion (four strings) instead of one per submission.
             Rejected — `BUILD_PLAN.md` task 3.2 says "a one-line justification each,"
             read as one per submission's overall intended-score set, not four per submission.
Cost:        None now — the shape was settled before the file was written, so
             `run_benchmark.py` (3.3) has one key structure to read, not a guessed one to
             discover was wrong later. Still blocked on the actual scores (separate from the
             shape) before the file can be written at all, per `CLAUDE.md` §10.
Defence:     "I checked `ground_truth.json`'s required shape against the module document
             before writing it, not after `run_benchmark.py` failed to parse it. §C.9 turned
             out to only imply the shape through one partial code fragment, not state it, so
             I logged the gap, proposed the most defensible reading, and had Anas confirm it
             explicitly rather than writing the file against my own guess."

### D-030 — `scripts/collect.py` fixed to call the DAG's existing pattern, not a new wrapper
Date:        2026-08-19
Status:      DECIDED
Context:     `config/roster.yaml` was filled with two real repos this session, which
             finally made it possible to actually run `python -m scripts.collect` for the
             first time. It failed immediately with `ImportError: cannot import name
             'collect'` — the script imported `collect(token, targets)` from
             `collectors/collect_github.py`, a function that has never existed there.
             `spec-verifier`, dispatched to check both files against
             `VDEL_Modules_1_2_Build.md` Part D, found `collect_github.py` MATCHES the
             spec exactly (`collect_repo(conn, ...)` / `collect_all(conn, repos)`) and
             that `dags/vdel_pipeline.py`'s `_collect` task already calls it correctly —
             `scripts/collect.py` was the only outlier, calling a signature (a token, not
             a connection; tuples, not dicts; `.errors`, not `failed`) that matched
             neither the spec nor the live collector.
Decision:    Rewrote `scripts/collect.py` to build the same `{owner, repo, student_id,
             assignment_id}` dicts and call `collect_all(conn, repos)` via
             `system.db.connect()`, mirroring `dags/vdel_pipeline.py`'s `_collect` task
             exactly. `collectors/collect_github.py` was not changed.
Alternative: Add a new `collect(token, targets)` wrapper function to `collect_github.py`
             so the original script's call would resolve. Rejected — that would have
             created a second, parallel entry point into the collector alongside
             `collect_all`, for two call sites (the script and the DAG) that should do the
             identical thing. Making the script match the DAG's already-correct call
             leaves exactly one interface to keep in sync with the spec, not two.
Cost:        None found. Full suite still green after the fix (232 passed, 1 xfailed, same
             xfail as before); ran the corrected collector twice against the two real
             repos in `config/roster.yaml` and confirmed both the backfill numbers and the
             incremental drop (`detail_calls` 41 -> 0) it was supposed to prove.
Defence:     "`scripts/collect.py` was never actually run until real repos existed to
             point it at, which is why this shipped broken and stayed broken. I found it
             by trying to run the exact command the file's own docstring says to run, not
             by code review, and verified the fix by running the corrected version twice
             against real data before calling it done."

### D-031 — NVIDIA-hosted DeepSeek added as a fourth `Provider`; Anthropic stays live and default
Date:        2026-08-19
Status:      DECIDED
Context:     Anas asked to add an NVIDIA-hosted, OpenAI-compatible inference endpoint
             (`integrate.api.nvidia.com`, model `deepseek-ai/deepseek-v4-pro`) as a
             config-switchable alternative to the Anthropic branch, motivated by free-tier
             access during this stage of the internship versus a paid Anthropic key. The
             request's premise — "reuse the existing openai SDK path" — did not hold:
             `_call_openai` is a structural stub (D-023) that raises `NotImplementedError`
             and is asserted as such by its own test; the `openai` package was neither
             installed nor in `requirements.txt`. There was no existing branch to reuse, so
             `_call_nvidia` was written fresh, shaped like `_call_anthropic`.
Decision:    `Provider.NVIDIA = "nvidia"` added to the enum (validated at import, D-023's
             pattern preserved). `_call_nvidia` is a real, live branch — not a third
             stub — using the `openai` SDK against NVIDIA's `base_url`, keyed by
             `NVIDIA_API_KEY` (never `OPENAI_API_KEY`, so the two credentials can never be
             silently interchanged). No `_REJECTS_NONDEFAULT_TEMPERATURE`-style restriction
             is applied — none is documented for this endpoint, so temperature is always
             sent explicitly, unlike D-025's Anthropic-specific carve-out. The model id
             `deepseek-ai/deepseek-v4-pro` is recorded **as supplied by Anas, not as
             independently verified** against NVIDIA's live catalog — a materially
             different provenance from D-024's correction of the Anthropic default, which
             was checked against verified documentation before being written in.
             `MODEL_TIERS["cheap"][Provider.NVIDIA]` stays `TODO(verify)`, per CLAUDE.md
             §10, because no cheap-tier DeepSeek variant was named. `openai>=1.0` added to
             `requirements.txt` (not `pyproject.toml`, which carries no dependency list at
             all — its own comment states this is deliberate); `python-dotenv` was already
             present and already installed, so nothing changed there. Anthropic remains the
             default provider; nothing about `_call_anthropic`, `_call_openai`, or
             `_call_qwen_local` was touched.
Alternative: (a) Implement the existing `openai` stub for real instead of adding a fourth
             provider. Rejected — no OpenAI account or key exists for this project, and
             NVIDIA's free tier during prototyping is the actual reason for this addition,
             not a proxy for wanting OpenAI specifically. (b) Make NVIDIA the default
             provider. Rejected outright — not asked for, and Anthropic remains the only
             provider this repo has exercised end to end against real data. (c) Treat the
             user-supplied model id as equivalent to a verified one and drop the
             provenance note. Rejected — CLAUDE.md §10 and this file's own D-024 precedent
             both require the distinction between "checked" and "supplied, unchecked" to
             stay visible, not be smoothed over for a cleaner-looking entry.
Cost:        `MODEL_TIERS["cheap"][Provider.NVIDIA]` being `TODO(verify)` means a
             `model_tier="cheap"` call under `LLM_PROVIDER=nvidia` reaches the (real)
             NVIDIA endpoint with the literal string `"TODO(verify)"` as the model — a
             provider-side 404, not an import-time failure, since D-023's "unservable
             provider is a startup failure" pattern covers unknown *providers*, not unknown
             *model ids* on a real one. NVIDIA's free tier is explicitly not treated as a
             production guarantee anywhere in the new code or tests — no retry/cost logic
             assumes durability, matching the instruction it was built to. The model id
             itself is unverified by this session and should be confirmed before any
             benchmark run is reported as measuring it.
Defence:     "I checked the request's premise before acting on it — there was no existing
             OpenAI branch to reuse, so I built one fresh, matching the shape the Anthropic
             branch already established. The model id came from Anas directly; I recorded
             that as supplied, not as verified, the same distinction this file already
             draws for the Sonnet 5 correction in D-024, so nobody downstream mistakes an
             unchecked string for a checked one."

### D-032 — `google` reinstated as a live provider; supersedes D-023
Date:        2026-08-19
Status:      DECIDED
Context:     Anas asked directly for a Google AI Studio (Gemini) branch, framed as "closing
             a gap" D-023 had left. That framing didn't hold on inspection: D-023 didn't
             leave a gap, it deliberately removed `google` from `Provider` and from
             `MODEL_TIERS`, with a stated, specific rejection of exactly this action ("Keep
             `google` and add a fourth branch. Rejected as scope invention — no document
             asks for a Google integration, and M3's job is to measure candidates, not to
             add one."). The request also described a `llm_call()` if/elif chain that no
             longer exists — that was the original design document's shape, replaced by
             D-022/D-023's `judge()`/`generate()` → `_PROVIDER_HANDLERS` dispatch pattern —
             and assumed stale `MODEL_TIERS["google"]` entries that D-023 had already
             deleted outright, not left stale. Surfaced to Anas directly before any code was
             written, given the specific, reasoned nature of what D-023 had rejected; he
             confirmed proceeding.

             Separately, the requested SDK call shape (`client.models.generate_content`) and
             model ids (`gemini-2.5-pro`/`gemini-2.5-flash`) were also unverified against the
             live SDK. Three documentation fetches against ai.google.dev disagreed with each
             other on the current method: two independent pages showed only
             `client.interactions.create(model=, input=)`, with one stating "The Interactions
             API is now generally available. We recommend using this API... for access to
             all the latest features." — read together with Anas, that pointed toward
             `interactions.create`, until installing and introspecting the actual
             `google-genai` package (2.18.1) showed `interactions.create`'s real Python
             signature is `(*, request=None, ..., **body: Any)`, an untyped passthrough
             neither fetched page fully specified the body schema of, whereas
             `client.models.generate_content(model=, contents=, config=)` still exists with
             a typed `config: GenerateContentConfig` carrying a real `temperature: float`
             field. Re-surfaced to Anas with the introspection evidence; he chose
             `generate_content` for the second time, reversing the interim choice.
Decision:    `Provider.GOOGLE = "google"` reinstated (D-023's status line updated to
             SUPERSEDED, its body kept verbatim as the historical record — the "enum
             validated at import" mechanism D-023 established is unchanged and still holds;
             only its google-specific conclusion is reversed). `_call_google` is a real, live
             branch using `client.models.generate_content` with a typed
             `GenerateContentConfig(temperature=...)`, keyed by `GOOGLE_API_KEY` (never the
             SDK's own default `GEMINI_API_KEY` lookup — same reasoning as
             NVIDIA_API_KEY-not-OPENAI_API_KEY in D-031). No temperature-rejection carve-out,
             matching NVIDIA — no restriction is documented for Gemini models. Model ids
             `gemini-3.7-flash` (default) and `gemini-3.5-flash-lite` (cheap) were verified
             live against ai.google.dev/gemini-api/docs/models on 2026-08-19 — cross-checked
             with two independently-worded fetches returning the same two ids, both marked
             stable/GA — a materially different provenance from D-031's NVIDIA model id,
             which is recorded as supplied-not-verified. `pyproject.toml`'s invariant-3
             banned-api list extended to `"google.genai"`, verified empirically (not
             assumed) to catch all three import forms the new code and its tests use
             (`from google import genai`, `from google.genai import types`,
             `import google.genai`), and confirmed live against a throwaway file outside
             `system/llm.py` before that file was deleted.
Alternative: (a) Implement `interactions.create` as originally requested, since live docs
             call it current and recommended. Rejected after installing the actual SDK and
             finding its typed parameter surface — `generate_content` is the one this
             session could verify field-by-field rather than guess into an opaque `**body`
             dict, and invariant 4 depends on temperature landing correctly. (b) Treat the
             original request's framing ("closing a gap") as accurate and proceed without
             surfacing D-023's specific rejection. Rejected — D-023 is a decided, reasoned
             entry naming this exact action; silently reversing it would be the kind of
             silent scope invention `CLAUDE.md` explicitly asks to stop and ask about,
             regardless of who is asking. (c) Guess at `gemini-2.5-pro`/`gemini-2.5-flash` as
             requested, since they follow a plausible naming pattern. Rejected — both are
             stale: live verification found `gemini-2.5-pro`/`gemini-2.5-flash` still listed
             but `gemini-3.7-flash`/`gemini-3.5-flash-lite` are the current stable/GA
             recommendations as of this date.
Cost:        D-023's original "Google is therefore NOT a benchmark candidate" consequence no
             longer holds as stated — if `benchmark/RECOMMENDATION.md` is ever written citing
             D-023 for that claim, it needs to cite D-032 instead. `qwen_local` and `openai`
             remain the only two providers still genuinely unservable; the "two providers
             behind llm.py" framing in `BUILD_PLAN.md` 3.1 now undercounts the live set by
             one, a documentation detail worth a pass but not blocking. Model ids are
             verified as of 2026-08-19 specifically, not permanently — Google's models page
             can and will change, the same caveat D-024 already states for the Anthropic ids.
Defence:     "The request described this as closing a gap, but the code showed it was
             reversing a decision that specifically rejected this action for a stated
             reason. I surfaced that before writing anything, and once given the go-ahead, I
             verified everything the request had guessed at rather than trusting either the
             request or the documentation on their own — the SDK call shape changed twice in
             this session as I found better evidence, and both model ids in the request
             turned out to be stale on a live check."

### D-033 — `validate_evidence()`'s two silent-underreporting gaps, closed with tests
Date:        2026-08-19
Status:      DECIDED
Context:     D.5's printed `validate_evidence()` has two gaps neither the module document
             nor any prior `DECISIONS.md` entry names. (a) It recovers a quote via
             `q.split(" + ")[0]`, which truncates any quote whose own text contains `" + "`
             — in code that is concatenation or arithmetic, common, not rare. (b) It
             iterates `for q in quotes`, so an empty evidence list for a criterion produces
             zero failures — a verdict scoring 4/4 across the board while quoting nothing at
             all passes the check untouched, which is precisely what invariant 6 exists to
             catch.
Decision:    `agents/validation.py` closes both. Quote recovery tries the whole string
             first, falling back to D.5's `" + "` split only as a second candidate — a quote
             genuinely written in D.5's `"quote + why"` form still validates, but a real
             code line containing `" + "` is checked whole rather than truncated. A
             criterion with no usable evidence at all is now reported as `missing_evidence`
             (flags, per D.6's "flagged for human review" resolution — does not reject,
             unlike a fabricated quote, which does). Both pinned by name:
             `test_code_containing_plus_is_not_truncated_into_a_false_pass`,
             `test_scored_criterion_with_no_evidence_is_reported`.
Alternative: Transcribe D.5's function verbatim and accept the gaps as a known limitation.
             Rejected — invariant 6 is the specific invariant this function exists to
             enforce, and a verdict that can score 4/4 with zero evidence and pass the check
             is the invariant failing silently, not a stylistic difference from the source.
Cost:        `validate_evidence`'s return shape gained a `kind` field (`unmatched_quote` /
             `missing_evidence` / `unknown_criterion`) D.5's plain `{criterion,
             unmatched_quote}` records don't have — kept as an addition, not a replacement,
             so a D.5-shaped reader still works. The missing-evidence case is a genuinely
             new judgment call (flag vs. reject) not specified anywhere — recorded as OPEN
             alongside D-018, not asserted as settled.
Defence:     "I found the printed evidence-check function has two ways to silently
             under-report — a truncation bug and a case where zero evidence still passes —
             neither mentioned in the document or any prior decision. I closed both and
             wrote a test naming each one, rather than transcribing a function whose job is
             catching exactly the failure it can itself commit."

### D-034 — The live M2 proof, run for real for the first time, reports DIFFERENT. RESOLVED
Date:        2026-08-23
Status:      DECIDED — was OPEN; resolved same day.
Context:     `python -m scripts.prove_event_sourcing` was run directly against the live dev
             database for the first time real telemetry exists to replay (student `anas`,
             3 traces, 1 concept). Every field of the rebuilt profile matches the stored
             snapshot — mastery, weaknesses, reflections, session_digest — except
             `features_ref`: the stored snapshot has it `None`; `rebuild_from_traces()`
             reconstructs it as a real timestamp (`2026-08-19 02:37:14 UTC`). Reproducible
             on a second run, not a flake. The same divergence breaks three tests in
             `tests/test_prove_event_sourcing.py`
             (`test_a_faithful_profile_proves_identical`,
             `test_a_student_with_no_prior_profile_is_reported_not_failed`,
             `test_no_profiles_is_vacuous_not_identical`) that previously passed only
             because the dev database held no real profile to expose the gap against.
Decision:    Hypothesis (b) confirmed, (a) ruled out. Queried the live DB directly: `anas`'s
             3 traces contain no reference to `learner_features` at all, so
             `rebuild_from_traces` cannot be fabricating the pointer from trace content —
             `_rederive_features_ref` genuinely re-derives it from `learner_features` by
             design. The real gap: `dags/vdel_pipeline.py`'s `update_profiles` task — the
             one place designed to fold new features into the live profile — was a literal
             `pass`. Nothing had ever written `learner_profile.features_ref` on the live
             path, so it stayed `None` while `learner_features` accumulated a real row from
             the M1 pipeline demo. Fix: `Memory.sync_features_ref()` added (`memory/memory.py`)
             — a targeted single-column write reusing `_rederive_features_ref`, so the live
             value and the rebuilt value are computed the same way and cannot disagree by
             construction (same argument as D-007, applied to a third piece of state).
             Wired into `update_profiles`. Ran once, live, to bring `anas`'s already-drifted
             row in sync. Fixing this exposed two more tests
             (`test_a_student_with_no_prior_profile_is_reported_not_failed`,
             `test_no_profiles_is_vacuous_not_identical`) that assumed `learner_profile` is
             globally empty except for their own fixture — an assumption `anas`'s now-real,
             permanently-committed profile breaks independently of `features_ref`. First was
             rescoped to assert what it actually tests (STUDENT-specific, not global
             emptiness); second was given the same `_profiles_exist()` skip guard the
             CLI-level test (`test_main_exits_nonzero_on_a_vacuous_proof`) already used for
             the identical reason, rather than inventing a new pattern.
Alternative: Patch the test fixtures to tolerate the divergence (e.g. exclude `features_ref`
             from the compare, or scope `prove()` to one student). Rejected outright — that
             would hide the exact class of silent drift `prove_event_sourcing.py` exists to
             catch, on the one occasion it caught something for real. (Confirmed correct in
             hindsight: the real fix was a missing write path, not a test that was too
             strict.)
Cost:        None going forward — `pytest -q` is 339 passed, 2 skipped (both the
             now-consistent vacuous-state skips), 1 xfailed (unrelated, the known Sara
             `spark.joins` discrepancy); `python -m scripts.prove_event_sourcing` reports
             IDENTICAL. Unblocks the M3 provider commit (D-031/D-032) and the M4 batch.
             `get_profile()`'s docstring still says `features_ref` is "deliberately not
             returned... nothing writes it yet" — no longer true; left unchanged in this
             pass since widening `get_profile`'s return contract is a separate, larger
             decision (`MODEL_ROUTING.md` situation #2), not required to close this bug.
Defence:     "The live event-sourcing proof said DIFFERENT for a real reason: the DAG task
             meant to sync `features_ref` into the live profile was an unimplemented stub, so
             the field just sat at `None` until real `learner_features` data existed to
             expose it. I confirmed that by reading `anas`'s actual traces against the actual
             code — not guessed — before writing a single line, then closed the gap with the
             same one-query-computes-both-paths pattern the project already uses for mastery,
             and re-ran the live proof to confirm IDENTICAL rather than trusting the fix."
---

### D-035 — Attempts, variants, gaps, sessions in scope; supersedes CLAUDE.md §2's prohibition
Date:        2026-08-19
Status:      DECIDED
Authority:   Dr. Ezzatul, supervision meeting
Context:     `CLAUDE.md` §2 forbids `problems`/`attempts` tables. That prohibition was
             written after an AI invented such a schema with no design authority
             (`START_HERE.md`; `explanation.md` §9). The 19 Aug supervision meeting changed
             the assessment model to completion problems (master code with hidden regions),
             which requires per-attempt and per-variant tracking.
Decision:    `projects`, `gaps`, `variants`, `attempts`, `sessions`, `test_results` and
             `resources` are IN SCOPE. `items` is superseded by `variants`. `attempts` and
             `sessions` are DERIVED tables, rebuilt idempotently from `raw_commits` +
             `raw_workflow_runs` + gap specs — NOT sources of truth. `traces` remains
             append-only; `learner_profile` remains derived; wipe-and-replay is unaffected.
Alternative: Keep `CLAUDE.md` §2's prohibition as-is. Rejected — that prohibition targeted
             AI-invented structure with no design authority; this is supervisor-mandated
             design, opposite provenance, for a genuinely new assessment model the original
             rule never anticipated.
Cost:        `CLAUDE.md` §2 and §6 both need updating; `explanation.md` §10's
             forbidden-structures row is now wrong. `TODO(verify)` beyond that — no DDL for
             the seven new tables exists in this repo (VDEL_REDESIGN.md, referenced for it,
             was not present when checked).
Defence:     `TODO(verify)` — not stated in the original entry.

---

### D-036 — Correctness is decided by execution, not by an LLM
Date:        2026-08-23
Status:      DECIDED
Authority:   Anas (technical review)
Context:     The meeting recorded "the system cannot execute code" as the reason for
             similarity-based grading. This is false: GitHub Actions already runs `pytest`
             on every push; `raw_workflow_runs.conclusion` exists because of it.
Decision:    Correctness = instructor-authored hidden tests executed in CI. The LLM scores
             approach/readability/idiom and explains divergences. It never asserts one.
Alternative: Continue similarity-based/LLM-asserted correctness on the premise that the
             system cannot execute code. Rejected — the premise was checked against the
             actual repo and found false.
Cost:        `TODO(verify)` — the original entry records a benefit, not a cost: "unblocks
             judge validation against ground truth — the risk-register item 'no
             instructor-graded reference set → cannot compute Cohen's κ' is partially
             resolved."
Defence:     `TODO(verify)` — not stated in the original entry.

---

### D-037 — Notebook interface rejected
Date:        2026-08-23
Status:      DECIDED
Context:     `TODO(verify)` — the original entry has no separate Context field.
Decision:    No notebook/JupyterHub interface. Reasons: multi-file data-engineering domain,
             `.ipynb` JSON diffs destroy `raw_commits.additions/deletions`, requires hosting.
             The underlying concern (edits outside gap regions) is handled by
             `scope_check.py` — detection, not prevention.
Alternative: A notebook/JupyterHub interface — the thing being rejected, for the three
             reasons in Decision above.
Cost:        `TODO(verify)` — not stated in the original entry.
Defence:     `TODO(verify)` — not stated in the original entry.

---

### D-038 — RAG chatbot dropped; curated resource table instead
Date:        2026-08-23
Status:      DECIDED
Context:     `TODO(verify)` — the original entry has no separate Context field.
Decision:    No chatbot. A curated `resources` table keyed by `concept_id` replaces RAG for
             recommendation; at 20–40 rows this is a SQL query, not a retrieval problem. RAG
             for grading: rejected. RAG for course-material-grounded feedback: DEFERRED,
             trigger = course materials delivered (existing risk-register item).
Alternative: A RAG chatbot for grading and/or recommendation. Rejected for grading outright;
             for recommendation because a curated table is simpler at this scale; for
             course-material feedback, deferred rather than rejected, pending materials.
Cost:        The decisive reason doubles as the cost of the alternative: the same
             supervision meeting restricted students from using AI during assignments, so
             shipping an AI assistant would have contradicted that policy.
Defence:     `TODO(verify)` — not stated in the original entry.

---

### D-039 — `.gitignore`'s exclusion of `CLAUDE.md` (and the other six internal documents) kept as-is
Date:        2026-08-23
Status:      DECIDED
Authority:   Anas
Context:     `CLAUDE.md` is untracked via `.gitignore` (commit `acffca6`, 2026-08-04): "kept
             locally as the authority every formula in `variables/` is transcribed from...
             but not meant for the public repo," bundled with `BUILD_PLAN.md`, the four
             `VDEL_*` module docs, and `explanation.md`. `DEVELOPMENT_MAP.md` (2026-08-10,
             six days later) describes `CLAUDE.md` as the permanent, auto-loaded Tier-1
             document and recommends `docs/explanation.md` be tracked — without revisiting
             the earlier gitignore rule. Investigated per this session's Step 3 (`git blame`
             + `git log` on the `.gitignore` line, `grep` of `DECISIONS.md`): no
             embedded-secret or accidental cause found; the reason is real and deliberate.
Decision:    Keep `.gitignore` as it is. `CLAUDE.md`, `BUILD_PLAN.md`, the four `VDEL_*`
             module docs, and `explanation.md` all stay untracked and local-only.
Alternative: Narrow the rule to exclude only the proprietary module docs, tracking
             `CLAUDE.md` (and/or `explanation.md`) going forward, matching
             `DEVELOPMENT_MAP.md`'s framing. Considered, not taken.
Cost:        The tension this entry records stays open: `DEVELOPMENT_MAP.md` describes
             `CLAUDE.md` and `explanation.md` in language that implies they're tracked
             project artifacts, but they are not. Anyone relying on `DEVELOPMENT_MAP.md`'s
             description without checking `.gitignore` first would be wrong about that.
Defence:     "I found the real, deliberate reason `CLAUDE.md` is untracked, flagged that a
             later document's framing doesn't quite match it, and asked rather than changing
             it myself. The decision was to keep the existing rule."

---

### D-040 — `sessions` and `activity_sessions` split: two concepts, one accidental name
Date:        2026-08-23
Status:      DECIDED
Authority:   Anas
Context:     `sql/06_assessment_tables.sql`'s first draft extended the existing `sessions`
             table (`sql/05_memory_tables.sql`: session_id, student_id, started_at, ended_at,
             trace_count, summary — a memory/trace-grouping session feeding
             learner_profile.session_digest) with six columns from VDEL_REDESIGN.md §11's
             `sessions` (assignment_id, attempt_no, duration_min, n_events, threshold_min,
             method_ver, abandoned — a git-derived activity session for duration/pace, V4/
             V11). Both concepts happen to share the name "sessions" in their respective
             documents; nothing else about them matches. Forcing them onto one row required
             weakening two of §11's NOT NULL constraints (duration_min, n_events) to nullable
             purely to avoid breaking existing rows — a constraint compromise with no upside,
             the same class of overloading this project already hit once (assignment-level
             concept tags being too coarse once gaps existed, fixed by moving tags to gaps —
             see C7 in VDEL_REDESIGN.md §4).
Decision:    Split. `sessions` reverts to exactly its `05_memory_tables.sql` definition,
             untouched. A new table, `activity_sessions`, carries VDEL_REDESIGN.md §11's
             definition verbatim, including the full NOT NULL constraints on duration_min,
             n_events and ended_at — safe because it is a brand-new table with zero existing
             rows, so there is no retrofit problem at all.
Alternative: Keep them merged with the nullable compromise already made. Rejected — grepped
             the codebase first (session_digest usage, anything reading duration/pace from
             `sessions`): confirmed zero call sites depend on the merged shape, so there was
             no cost to splitting and a real, named cost (weakened constraints, two unrelated
             concepts on one row) to not splitting.
Cost:        The live dev database had already been ALTERed by the first draft before this
             was caught; the seven stray columns were dropped from `sessions` by hand
             (`ALTER TABLE sessions DROP COLUMN IF EXISTS ...`) to bring it back to exactly
             `05_memory_tables.sql`'s shape — not part of `06_assessment_tables.sql` itself,
             since that file should never touch `sessions` at all now. Anyone else who ran
             the first draft's `init_db.py` against their own database needs the same manual
             cleanup; `06_assessment_tables.sql` re-running does not do it for them.
Defence:     "Two different things had the same name in two different documents. I noticed
             the merge was forcing a real constraint compromise, checked whether anything in
             the codebase actually depended on the merged shape before undoing it — nothing
             did — and split them into `sessions` (untouched) and `activity_sessions` (new,
             full constraints, zero compromise)."

---

### D-041 — `attempts.commit_sha`/`submitted_at` made nullable: an attempt exists at
             render time, not just at submission time
Date:        2026-08-24
Status:      DECIDED
Authority:   Anas
Context:     `sql/06_assessment_tables.sql`'s `attempts` table originally had
             `commit_sha TEXT NOT NULL REFERENCES raw_commits(sha)` and
             `submitted_at TIMESTAMPTZ NOT NULL`, transcribed verbatim from
             VDEL_REDESIGN.md §11. `scripts/render_student_repo.py` needs to write an
             `attempts` row the moment a variant is assigned to a student — before
             anything has been pushed to GitHub, so no real `commit_sha`/`submitted_at`
             exists yet. Table was empty (0 rows) when this was found, so no existing
             row was at risk from relaxing the constraint.
Decision:    `commit_sha`/`submitted_at` are nullable. An `attempts` row is created at
             RENDER time (`render_student_repo.py`, `commit_sha`/`submitted_at` both
             NULL) and filled in later, for real, once the student actually pushes
             (`collect_github`, a later step, matches the new row by `commit_sha` once
             one exists). This is a real modelling decision, not a workaround: it means
             an attempt exists once rendered, not only once submitted — the row itself
             is the record that a variant was assigned, independent of whether the
             student ever finishes it.
Alternative: Wait to INSERT the `attempts` row until the student's first commit arrives
             (keeping both columns NOT NULL, matching VDEL_REDESIGN.md §11 literally).
             Rejected: `collect_github` would then need its own INSERT-or-UPDATE
             branching logic to decide whether an attempt already exists — this project
             already has that exact pattern once, correctly, in `memory/memory.py`'s
             fast-path merges (`_merge_mastery`, `ON CONFLICT DO UPDATE`), and repeating
             it in a second place is exactly the "two implementations that could
             silently disagree" shape D-007 already named and rejected once for mastery.
             Insert-then-backfill means `collect_github` only ever needs a plain
             `UPDATE ... WHERE commit_sha IS NULL AND student_id = ... AND
             assignment_id = ...` (or equivalent match) against a row that is
             guaranteed to already exist — one code path, not two.
Cost:        `attempts` rows now exist for variants nobody has attempted yet, so a query
             counting "real attempts" must additionally filter `WHERE submitted_at IS
             NOT NULL` — not counting every row as a completed attempt is now the
             caller's responsibility, not something the table's own existence
             guarantees. `_upsert_attempt`'s `ON CONFLICT ... DO UPDATE ... WHERE
             attempts.submitted_at IS NULL` guard exists specifically so a later
             re-render can never silently overwrite a row `collect_github` has already
             filled in for real.
Defence:     "The schema said NOT NULL because the original design assumed an attempt
             row is only ever created once a submission exists. Rendering a student's
             file is itself a real event worth recording before that — and recording it
             immediately means the collector that fills in the real commit data later
             only ever has to UPDATE a row that's already there, not decide whether to
             INSERT or UPDATE. One code path, not two, for the same reason mastery
             replay is one implementation and not two."

---

### D-042 — select_variant hides an entire concept's gaps as one unit, not one gap
             picked from among them
Date:        2026-08-24
Status:      DECIDED
Authority:   Anas
Context:     `assessment/gap_generator.py`'s first draft, once a concept was selected
             (adaptively or by uniform fallback), picked ONE gap uniformly at random
             among that assignment's gaps tagged with the concept, to be that variant's
             hidden region. Reversed: cited reasons were the 19 Aug supervisor meeting
             judging a single hidden region "too easy," and VDEL_REDESIGN.md's own
             language calling a variant "a coherent, concept-tagged region." Neither
             citation could be verified — grepped VDEL_REDESIGN.md directly for
             "coherent," "too easy," and the supervisor-meeting phrasing; none appear
             anywhere in the file, and the meeting-notes files it lists as sources
             (SESSION_SUMMARY.md, SESSION_SUMMARY_M3.md) don't exist in this repo. Logged
             as unverifiable, not as confirmed, at the time; proceeded anyway on Anas's
             direct authority, since the technical reasoning stands independent of the
             citations.
Decision:    When a concept is selected, EVERY gap in that assignment tagged with that
             concept is hidden together as one variant — not one gap chosen from among
             them. A single-gap variant still falls out naturally when a concept happens
             to tag only one gap (checked live, not just asserted: `('g_c',)` for an
             assignment with one lowest-mastery-concept gap). `variant_id`'s formula
             (C2, unchanged) still hashes `sorted(gap_ids)`, so a multi-gap variant is
             exactly as reproducible as a single-gap one was.
Alternative: Keep one-gap-per-variant (the first draft, already built and tested at the
             time). Rejected per direct instruction — see Context. A middle option
             (weight the random pick toward larger regions without guaranteeing full
             coverage) was not raised or considered; the instruction was unambiguous
             about "ALL gaps tagged with that concept," not a probabilistic compromise.
Cost:        `select_variant`'s return contract changed shape in an already-shipped
             function (`chosen_gap_ids` can now be a longer tuple, not just length-1) —
             caught before any caller outside its own tests depended on the old
             behaviour, since `render_student_repo.py` (the only real caller) was built
             after this change, not before it. `test_gap_generator.py`'s prior single-
             gap-pick tests were rewritten, not appended around, since the old behaviour
             they asserted is no longer correct and leaving them would assert a lie.
Defence:     "I was told to bundle a concept's gaps instead of picking one, for reasons
             I could not verify against any document I have access to. I said so plainly
             before making the change rather than presenting an unverifiable citation as
             confirmed, then made the change anyway because the person asking has actual
             authority here and the technical reasoning holds regardless of the citation."
---

### D-043 — `raw_commits`/`raw_workflow_runs`.assignment_id made nullable: a commit or
             run can match zero, one, or many assignments, not always exactly one
Date:        2026-08-24
Status:      DECIDED
Authority:   Anas
Context:     `collectors/collect_github.py` was built under the one-repo-one-assignment
             model (`collect_repo(conn, owner, repo, student_id, assignment_id)`, one
             scalar `assignment_id` per call). The curriculum redesign (D-035 onward)
             puts FOUR `assignment_id`s in one repo, one per `assignments.file_path`
             (`extract.py`/`transform.py`/`load.py`/`quality.py`). A commit can touch one
             of those files, several at once, or none at all (README, `requirements.txt`,
             `.github/workflows/ci.yml`) — a scalar `NOT NULL assignment_id` cannot
             honestly represent "zero" or "more than one" of those.
Decision:    `raw_commits.assignment_id` and `raw_workflow_runs.assignment_id` are
             nullable. `raw_commits` itself is otherwise untouched — still one row per
             `sha`, same PK, same grain, matching VDEL_REDESIGN.md §10.4's "Keep,
             correctly designed" verdict for that table; only one column's constraint
             moves. `collect_repo` now takes a list of `assignment_id`s per repo (grouped
             by `(owner, repo, student_id)` in `collect_all`, so `config/roster.yaml`'s
             existing one-row-per-assignment shape needs no change) and matches each
             commit's real changed-file list (`detail["files"]`) against each
             assignment's `file_path`. `raw_commits.assignment_id` is set to the single
             match, or NULL for zero or multiple matches. The real per-assignment
             record for a multi-match commit is written on `attempts` instead —
             `attempts.commit_sha` already carries no uniqueness constraint (D-041), so
             one commit can update several `attempts` rows, one per assignment it
             touched, with zero further schema change. `raw_workflow_runs.assignment_id`
             is set NULL whenever its repo covers more than one assignment_id (a CI run
             tests the whole repo, so it cannot be file-matched the way a commit can);
             single-assignment repos are unaffected.
Alternative: Give `raw_commits` a composite PK (`sha`, `assignment_id`) and one row per
             matched assignment. Rejected: `attempts.commit_sha REFERENCES
             raw_commits(sha)` is a plain foreign key, which requires `sha` alone to
             keep a bare unique constraint — a composite PK would break that FK. It would
             also mean duplicating `additions`/`deletions`/`message` across N rows for
             one real git object, which is a worse fit for "raw_commits is the source of
             truth for what GitHub actually reported" than a single row with an honest
             NULL.
Alternative: Invent a value for the unmatched/ambiguous case (e.g. the project's
             first-`seq` assignment) instead of NULL. Rejected for the same reason
             `config/roster.example.yaml` already states for `released_at`: an invented
             value that looks real is worse than an honest gap, because nothing
             downstream can tell the difference — a `NULL`-checking query can, a wrong
             guess can't be told apart from a correct match.
Cost:        A commit matching zero or >1 assignment file leaves `attempts` unattached
             for the assignment(s) it should have updated whenever no unsubmitted
             `attempts` row exists yet to receive it (not rendered yet, or already
             submitted) — see the `commits_without_open_attempt` counter in
             `collectors/collect_github.py`'s `Stats`, counted and surfaced in
             `.summary()` rather than left as a silent 0-row UPDATE. `V4`'s existing
             `raw_commits JOIN assignments USING (assignment_id)` pace query
             (`features/compute_features.py`) degrades gracefully under a NULL — that
             commit simply doesn't join, which is correct (it wasn't really a commit to
             that assignment) — but is not rewritten here to read from `attempts`
             instead; that is VDEL_REDESIGN.md §7's job, not this one.
Defence:     "A commit is one real git object; forcing it to declare exactly one
             assignment is what broke under the new curriculum shape, not the table's
             grain. `raw_commits` keeps its row-per-sha identity and its 'source of
             truth, unchanged' status; only the one column that tried to also carry
             per-assignment attribution gives that job to `attempts`, which already had
             the right shape to hold it without any new table."

---

### D-044 — `items` is superseded by `variants` but deliberately NOT dropped yet
Date:        2026-08-24
Status:      DECIDED
Authority:   Anas
Context:     `CLAUDE.md` §6 and `VDEL_REDESIGN.md` §11 both end the `variants` DDL block
             with a literal `DROP TABLE IF EXISTS items;`. `sql/06_assessment_tables.sql`
             deliberately omits that statement and says so in an in-file comment. Raised
             by the `reviewer` agent during the A1 commit review: of the four places
             sql/06 diverges from its own specification, three (D-040, D-041, D-043) carry
             a decision citation and this one carried only prose ("per instruction"),
             making it the one divergence a future reader could mistake for an oversight.
Decision:    `items` (`sql/03_feature_tables.sql`) stays in the schema for now.
             `variants.difficulty` is the KT-IDEM item going forward (D-035) and nothing
             new may write to `items`, but the table itself is not dropped until the
             migration is verified — meaning until `variants` has been populated for a
             real project and something has actually read `variants.difficulty` on the
             live path. `scripts/seed_data.py` still writes `items` rows from
             `config/roster.yaml`; that write is legacy and dies with the table.
Alternative: Drop `items` in sql/06 as both documents literally instruct. Rejected on
             reversibility grounds: keeping a superseded empty table costs nothing and is
             trivially undone later, while dropping a table that something unnoticed still
             reads is a data-loss bug discovered at the worst possible moment. The
             asymmetry is the whole argument — this is the same reasoning D-041 used for
             relaxing a constraint rather than inventing a value.
Cost:        The schema carries two tables modelling one concept until the drop happens,
             which is exactly the redundancy VDEL_REDESIGN.md §10.4 flagged when it marked
             `items` "❌ Replace". Anyone reading the schema cold could write against the
             wrong one. Mitigated only by comments today (`sql/06`'s note and this entry);
             the real fix is to perform the drop, which is deferred, not cancelled.
Defence:     "Both design documents said to drop it. I kept it one milestone longer
             because nothing had yet exercised its replacement on a live path, and
             dropping a table is the one direction of this change that isn't reversible.
             The supersession is recorded in three places; the drop is a scheduled task,
             not a forgotten one."

---

### D-045 — An assignment freezes only at 100% hidden-test pass; unfrozen is a valid
             permanent state, and every commit's results are kept
Date:        2026-08-24
Status:      DECIDED
Authority:   Anas
Context:     `attempts.submitted_at` needed a meaning. D-041 made it nullable and
             described NULL as "assigned, not yet worked," with the intent that
             `collect_github` would set it on the student's first real push. That reading
             makes "submitted" mean "pushed something," which gives an attempt no notion
             of being finished and makes the first push indistinguishable from the last.
             PROVENANCE NOTE: this entry also refers to a prior scheduling decision making
             Feedback Agent runs batched. No such entry exists in this file (grepped for
             "batched"/"feedback agent" before writing this; the only "batch" hit is an
             unrelated reference to the M4 commit batch), and no Feedback Agent exists in
             the codebase. The batching is recorded here as instructed and attributed to
             Anas directly, NOT presented as a citation of an entry that can be found.
Decision:    Three parts, one rule and its two consequences.

             (a) FREEZE RULE. An assignment freezes when, and only when, its hidden tests
             reach 100% pass. There is no deadline cutoff and no forced submission.
             `submitted_at IS NULL` is therefore a valid PERMANENT state meaning "not yet
             passing," not a transient pre-submission window — a student who never solves
             an assignment simply has an attempt that never freezes, and that is a
             correct, expected terminal state rather than missing data. `submitted_at`
             accordingly means "froze at 100% pass," superseding D-041's "matched a real
             push" reading.

             (b) FEEDBACK TRIGGERS ON FAILURE, NOT ON FREEZE. Feedback runs are batched,
             but the batch is selected as "recent commits whose hidden tests failed," NOT
             "recently frozen attempts." A student who is stuck needs feedback precisely
             BECAUSE they have not passed; a trigger keyed on freeze would deliver help
             only to students who no longer need it, and deliver nothing at all to the
             student who never passes — the exact population the coaching exists for.

             (c) test_results IS KEYED BY COMMIT, NOT BY ATTEMPT. Every commit's
             hidden-test outcome is recorded, independent of whether that assignment has
             frozen. `test_results` gains a `commit_sha` column and its primary key
             becomes (attempt_id, commit_sha, test_name). `compute_features.py`'s V1 (BKT
             mastery), V5 (error response) and V6 (error frequency) must read ALL
             test_results rows for a student/assignment, never only the row tied to
             `attempts.commit_sha`.
Alternative: Key test_results by attempt alone, as originally written in
             VDEL_REDESIGN.md §11 (`PRIMARY KEY (attempt_id, test_name)`). Rejected, and
             this is the substantive finding of this entry: one `attempts` row carries one
             `commit_sha`, so under that key every pre-freeze commit's results overwrite
             the previous one and only the final passing run survives. V5 is defined as
             what a student does about errors and V6 as how often errors happen — both are
             computed ENTIRELY from the failures that key would discard. The original
             schema silently deletes the evidence for two of the six variables this
             project exists to measure, and does so invisibly, since the surviving row
             always looks complete and correct.
Cost:        Two pieces of already-committed work are now wrong and must change.
             (1) `collectors/collect_github.py`'s D-043 attribution sets
             `commit_sha`/`submitted_at` on the first matched commit, under a
             `WHERE submitted_at IS NULL` guard — i.e. it freezes on first push and then
             ignores every later commit, which is precisely backwards under (a).
             (2) `sql/06_assessment_tables.sql`'s `test_results` needs the (c) key change.
             The table is empty (zero rows, zero readers, zero writers — verified by grep
             across all Python before this entry), so the migration costs nothing now and
             would have been expensive later. `attempts.commit_sha` retains its meaning as
             "the commit that froze this attempt" and stays NULL until one does.
Defence:     "Submitted means finished, and finished means the tests pass. Anything else
             makes 'submitted' mean 'touched it once,' which tells you nothing. The
             consequence is that most of a student's history is pre-freeze failure, so the
             failures are the data — keeping only the passing commit would have thrown
             away everything error response and error frequency are computed from, while
             leaving a row that still looked perfectly well-formed."

---

### D-046 — Test-to-gap attribution via `@pytest.mark.gap("g_id")`, read from JUnit XML
             `<properties>`, never from the test's name
Date:        2026-08-24
Status:      DECIDED
Authority:   Anas
Context:     `test_results.gap_id` (sql/06) has been NULL on every row since B2
             landed (bda8431) -- `assessment/test_runner.py` had no way to know which
             gap a given hidden test exercised, and the module docstring said so plainly
             rather than inventing a naming-convention guess. This blocks C1: BKT needs
             concept_id per observation, and concept_id only reaches a test result via
             `gap_id -> gaps.concept_ids` (sql/06). No test-to-gap mapping existed
             anywhere in the codebase before this entry -- confirmed by grep across the
             four hidden test files before writing anything.
Decision:    Every hidden test carries `@pytest.mark.gap("g_id")`, naming the real
             `gaps.gap_id` it exercises. A `conftest.py`
             (`curriculum/master/<project>/tests/hidden/conftest.py`) converts the
             marker into a JUnit XML `<properties>` entry via
             `pytest_collection_modifyitems` writing to `item.user_properties`; nothing
             registers `--strict-markers`, so `pytest_configure` also registers the mark
             to silence the unknown-mark warning, since this conftest runs inside a
             STUDENT repo that may have no pyproject.toml of its own to register it in.
             `test_runner.py::_inject_hidden_test` now copies this conftest.py alongside
             the one hidden test file it injects (previously copied only the test file);
             `_parse_junit` reads `gap_id` from the property, defaulting to `None` when
             a test carries no marker -- absence, never a guess.

             VERIFIED empirically before being adopted, not assumed from pytest's docs:
             a bare `@pytest.mark.gap(...)` with no hook produces NO `<properties>`
             element in `--junitxml` output at all (checked directly, on a scratch
             probe). With the `pytest_collection_modifyitems` hook, the property DOES
             appear, and survives on a FAILING marked test too (property present
             alongside `<failure>` in the same `<testcase>`) -- which matters, since most
             real hidden-test outcomes are failures, not passes.

             The four hidden test files were retrofitted using a real, checked mapping,
             not a guess: every test function calls exactly one gap-bearing function
             (`fetch_weather` -> `g_ext_retry`, `parse_response` -> `g_ext_parse`,
             `insert_readings` -> `g_ld_insert`, `readings_since` -> `g_ld_select`,
             `assert_no_nulls` -> `g_qa_nulls`, `assert_reasonable_range` -> `g_qa_range`,
             `clean_readings` -> `g_tf_clean`, `to_fahrenheit` -> `g_tf_convert`,
             `enrich_with_timestamp` -> `g_tf_timestamp`), read directly from each test
             file against the real `gaps` rows before assigning a single marker.
             `test_transform.py` had no `import pytest` at all before this -- added,
             since the marker requires it.
Alternative: Derive gap_id from the test's NAME (e.g. a `test_g_ext_retry_*` prefix
             convention). Rejected: it would silently drift the moment a test is
             renamed for readability, with no mechanism to catch the drift -- a marker
             is checked at collection time (an unknown mark would warn; a mistyped
             gap_id still gets caught by the FK on test_results.gap_id at the write
             site), a name-prefix convention is checked by nothing.
Cost:        `master_version` is UNCHANGED by this entry (75b5b7867e4d, confirmed by
             re-running `seed_curriculum` after the retrofit) -- `_tree_version` hashes
             only the four STAGE files (extract/transform/load/quality.py), never the
             test files, so the nine already-seeded gaps' pinned line ranges are
             unaffected. Every project added after `weather_etl` must author its hidden
             tests with this marker from the start, or repeat this retrofit.
Defence:     "gap_id was NULL because nothing told the test runner which gap a test was
             for, and I was not going to invent a mapping that could be wrong in a way
             nothing would catch. A pytest marker is checked at collection time and
             enforced again by a real foreign key at the write site; a naming convention
             is checked by nothing. I verified the marker actually reaches the report
             before building on it, including on the case that matters most --
             a failing test, not just a passing one."

---

### D-047 — `assignments.concepts` protected from `roster.yaml` clobbering a curriculum
             assignment's gap-derived value, conditionally, per assignment
Date:        2026-08-25
Status:      DECIDED
Authority:   Anas
Context:     `scripts/seed_data.py::main()` runs `seed_curriculum()` FIRST (writes the
             correct, gap-derived `assignments.concepts` for curriculum assignments —
             D-035 C7: "tags live on the gap, not the assignment... assignments.
             concepts[] becomes the derived union") and then loads `roster.yaml` SECOND,
             doing `INSERT ... ON CONFLICT (assignment_id) DO UPDATE SET ... concepts =
             EXCLUDED.concepts` unconditionally. Investigated on direct question
             ("does anything actually READ roster.yaml's concepts field downstream, or
             is it purely documentation now"): confirmed by exhaustive grep that nothing
             in the codebase ever SELECTs `assignments.concepts`, and the only two
             Python consumers of an `assignment["concepts"]` key (`agents/code_agent.
             py`, `agents/echo_agent.py`) receive it as a caller-supplied argument —
             every real and test caller in the repo (`exec.py`,
             `tests/test_echo_agent.py`, `tests/test_code_agent.py`) hand-writes it,
             disconnected from both the DB and `roster.yaml` entirely. But the write
             path itself was a real, live bug: the four `weather_etl_*` assignments
             were about to be added to `roster.yaml` (needed for D-043's per-file
             attribution — one `collect_repo` call grouping all four assignment_ids for
             one repo), which would have made every future `seed_data` run silently
             overwrite the correct gap-derived concepts with whatever was typed in the
             roster file.
Decision:    `concepts` is set on every INSERT (a brand-new `assignment_id` — curriculum
             or legacy roster-only — gets it populated either way). On CONFLICT, it is
             protected THE SAME WAY `seed_curriculum`'s own `assignments` INSERT already
             protects `released_at` (that INSERT's own comment: "deliberately absent
             from this UPDATE SET ... must never be moved by a re-run once set") — except
             `concepts`' protection is CONDITIONAL, not absolute, because one INSERT
             statement here serves two populations sharing one table: a curriculum
             assignment (has rows in `gaps`) already has the correct value; a legacy
             roster-only assignment (`weather-etl-pipeline`, `csv-sales-analyzer` — no
             `gaps` rows at all) has NO other source of truth, so `roster.yaml` must keep
             updating it. A `CASE` inside the `SET`, not a `WHERE` on the whole
             `DO UPDATE`, is what keeps `repo_prefix`/`due_at` updating unconditionally
             while only `concepts` is conditional — a `WHERE` on the `DO UPDATE` would
             gate every column in the `SET` list, not just this one:

             ```sql
             INSERT INTO assignments (assignment_id, repo_prefix, released_at, due_at, concepts)
             VALUES %s ON CONFLICT (assignment_id) DO UPDATE SET
               repo_prefix = EXCLUDED.repo_prefix, released_at = EXCLUDED.released_at,
               due_at = EXCLUDED.due_at,
               concepts = CASE WHEN EXISTS (
                 SELECT 1 FROM gaps WHERE gaps.assignment_id = assignments.assignment_id
               ) THEN assignments.concepts ELSE EXCLUDED.concepts END
             ```
Alternative: Drop `concepts:` from `roster.yaml` entirely for the four `weather_etl_*`
             assignments, since nothing downstream reads the column anyway. Rejected:
             it fixes the symptom for four specific assignment_ids but leaves the
             clobbering bug live for the NEXT curriculum project's assignments the
             moment anyone lists them in `roster.yaml` too (e.g. for their GitHub
             telemetry) — fixing the write path once is cheaper than remembering the
             omission forever.
Alternative: Mark `concepts:` in `roster.yaml`'s header comment as a "snapshot that can
             drift" rather than fixing the SQL. Rejected: a comment is not a check: it
             relies on every future editor reading and honouring it, the exact failure
             mode this project's own "a comment is not a check" precedent (D-041's
             citation of `render_student_repo.py`'s real filesystem walk vs. a comment
             promising `tests/hidden` is never copied) already rejected once.
Cost:        One more place a reader has to know two different populations of
             `assignment_id` share the `assignments` table with different concepts
             semantics — mitigated by the in-file comment citing this entry and the
             `released_at` precedent by name, not by a second document.
Defence:     "`released_at` already had this exact problem and this exact fix, one
             column over. `concepts` needed the same protection but conditionally,
             because unlike `released_at` — which only ever means one thing, 'when the
             clock started, set once' — `concepts` means two different things depending
             on whether the assignment has gaps: a derived fact for curriculum
             assignments, a roster-declared fact for legacy ones. Proven both ways, not
             just reasoned about: a synthetic assignment with a `gaps` row resisted a
             deliberately conflicting write; one without a `gaps` row accepted it."

---

### D-048 — test_results wired to BKT/V5/V6 through memory.py only; `traces` confirmed
             append-only at the database level, changing how this gets tested
Date:        2026-08-25
Status:      DECIDED
Authority:   Anas
Context:     EXECUTION.md Stage C1 (corrected wording): "V1, V5, V6 all read every
             test_results row for a student/assignment across every commit, regardless
             of freeze state." Neither was wired -- V1 (`compute_features.py::_mastery`)
             built its own `MasteryEstimator` directly from `raw_workflow_runs`, a
             SEPARATE implementation from `memory.py`'s own trace-replay BKT; V5/V6
             (`_error_stats`) read only `raw_workflow_runs` too. Nothing read
             `test_results` at all.
Decision:    Four pieces, in dependency order.

             1. `memory.py`: `"test_result"` added to `KINDS` and `MASTERY_TRACE_KINDS`.
             Because `_replay_concept`, `_concepts_with_evidence` and
             `_failure_evidence_by_error_class` already key generically off
             `MASTERY_TRACE_KINDS`, this one line wires BKT replay for free. Payload
             carries `conclusion` (`ci_run`'s exact vocabulary) and `item_difficulty`
             (from `gaps.difficulty`); `error_class` is DELIBERATELY omitted -- it would
             wire the recurrence/weakness system, which was not asked for and whose
             "same mistake repeating" semantics (a classified error TEXT) is not the
             same signal a `gap_id` is. One new public method, `Memory.
             test_result_history(student_id, assignment_id=None)` -- V5/V6 need the raw
             sequence (time-to-fix, per-concept counts), which a replayed mastery state
             cannot give them, and CLAUDE.md's invariant 2 means that sequence is read
             through `Memory`, not a second raw query against `traces`.

             2. `assessment/test_runner.py`: after writing `test_results`, logs one
             `test_result` trace per genuinely-NEW, gap-tagged outcome, then calls
             `update_mastery` once per distinct concept touched -- the same two-step
             fast-path shape `agents/code_agent.py::grade` already uses (log, then
             update). "Genuinely new" is decided by `RETURNING (xmax = 0)`, the standard
             Postgres freshly-inserted-row idiom, on the `test_results` INSERT --
             re-grading an already-recorded commit must not log a second observation,
             which would silently inflate `n` (invariant 8).

             3. `compute_features.py::_mastery`/`_error_stats`: merge `raw_workflow_runs`
             with `Memory.test_result_history` CHRONOLOGICALLY (BKT is order-dependent)
             rather than replacing one source with the other -- `raw_workflow_runs`
             remains real evidence for repos outside the gap-based curriculum model.
             `_error_stats` keeps TWO views, not one flattened list: `runs` (one entry
             per real observation, for total_runs/time-to-fix) and `concept_events` (the
             same evidence fanned out per concept, for by_concept/opportunities) --
             flattening both into one list, as a first draft did, would have
             double-counted every multi-concept `test_result` observation in V6's
             aggregate rate. Caught before it shipped, by reasoning about what a gap
             tagged with two concepts should do to an AGGREGATE count versus a
             PER-CONCEPT histogram, not by a test failing.

             4. Tests: `traces` DELETE returns `rowcount: 0` -- confirmed live, not
             assumed -- a Postgres RULE (sql/05, invariant 1) makes it a silent no-op,
             not an error. Every existing synthetic-student test in this project used
             commit-then-DELETE teardown; that pattern is now permanently broken for any
             test that logs a real trace. Fixed by giving `grade_attempt` an optional
             `conn=` (mirroring `memory.py`'s own `_session` pattern) so a test can pass
             its OWN never-committed connection through setup, both `grade_attempt`
             calls, and every assertion, then roll the whole thing back at teardown --
             the same primitive `system/db.py::dry_run_cursor()` already exists for.
Alternative: Key the recurrence rule off `gap_id` by writing it into `error_class`,
             wiring weakness-opening for `test_result` traces in the same pass. Rejected:
             not asked for, and a real, unreviewed decision (is a repeated wrong-gap
             genuinely "the same mistake" in Becker's sense, or a different signal
             entirely) that deserves its own scrutiny, not a side effect of this one.
Alternative: Flatten `runs` and `concept_events` into one list in `_error_stats`, matching
             the pre-existing code's shape exactly. Rejected as a real correctness bug,
             not a style preference: `raw_workflow_runs.concept_id` is always singular,
             so the original code never had a multi-concept-per-row case to get wrong;
             `test_result` traces can be evidence for several concepts at once, and
             counting the same real observation as two "runs" would inflate V6's overall
             fail_ratio and errors-per-100-LOC for no real reason.
Cost:        `_test_runner` (the old test student, before `conn=` existed) is now a
             permanent orphan in the dev DB -- 5 real `test_result` traces, un-deletable
             by design, and the `students` row they reference can therefore never be
             removed either. Left in place rather than fought: deleting it would mean
             circumventing invariant 1, which this project does not do even for test
             hygiene. `tests/test_test_runner.py` now uses `_test_runner_v2` to avoid
             colliding with it.
Defence:     "Logging the trace was the easy half. The two real risks were inflating a
             count that should not inflate -- V6's aggregate rate if a multi-concept
             observation is counted twice, and BKT's `n` if a re-grade is counted as a
             second observation -- and I checked both before trusting the numbers, not
             after. The append-only discovery was not something I could have designed
             around in advance; the fix (roll back instead of delete) uses a primitive
             this project already had for exactly this reason, once I found it."

---

### D-049 -- Two-layer LLM fallback chain (within-provider primary, cross-provider
             secondary); Beat 6 (the Code Agent, live) proven for the first time
Date:        2026-08-25
Status:      DECIDED
Authority:   Anas
Context:     Beat 6's first live attempt (this session, earlier) failed on
             google.genai.errors.ClientError: 429 RESOURCE_EXHAUSTED -- "prepayment
             credits are depleted" on the paid Google key then in use. That key was
             swapped for a free Google AI Studio key, which changes the diagnosis
             entirely: a free key cannot hit billing exhaustion (there is no prepayment
             to deplete), so its real failure mode is per-model overload -- this project
             had already seen exactly this shape once before, months earlier, on the
             very first free Gemini attempt ("model not available, high traffic").
             Confirmed live again this session: gemini-3.7-flash returned a ServerError
             classified transient on 3 of 5 real attempts during this implementation.
Decision:    system/llm.py::_complete now walks a two-layer chain instead of calling
             one hardcoded (provider, model):

             Layer 1 (primary): within-provider model fallback. On a "transient"
             classification, retry the SAME provider's next model (_model_chain --
             primary model first, then every other MODEL_TIERS tier's REAL id for that
             provider, "TODO(verify)" placeholders filtered out, never an invented third
             model to round out the chain). This is the primary layer, not the
             secondary one, because it matches the actual failure mode measured: one
             free key serves every Gemini model, so the fix for "this one model is
             overloaded" is "ask a different model under the same key," not "find a
             different account."

             Layer 2 (secondary safety net): cross-provider fallback. Only reached once
             layer 1 is exhausted (every model in the primary provider's chain tried, or
             skipped outright for a "quota_billing" classification, since retrying a
             different model under an exhausted ACCOUNT cannot help). Tries other
             providers with a REAL key, checked LIVE every call
             (_providers_with_real_keys, reading os.environ fresh -- never assumed,
             never cached from import time) -- never Provider.OPENAI/QWEN_LOCAL, which
             are structural stubs with nothing to check a key for. Degrades to "nothing
             left to try" and a clear, attempt-by-attempt RuntimeError when no other
             provider has a key -- confirmed live this session, "no fallback provider
             configured" printed and the run still terminated cleanly, not a crash.

             Error classification (_classify_transport_error) is the reason this is not
             "retry on any exception." "quota_billing" (429 + credit/billing/quota
             language) skips layer 1 entirely. "transient" (503, or overload/rate-limit
             language) walks the model chain. "unknown" is not retried within a
             provider but still eligible for layer 2. Three exception types are NEVER
             classified or retried at all, propagating immediately: NotImplementedError
             (a stub -- every model under that provider is equally unimplemented, so
             "try another model" is meaningless and would mask "this isn't built yet"
             behind a fallback that looks like it worked) and ValueError/TypeError (a
             caller-side mistake -- D-025's temperature-rejection ValueError is the
             concrete case: silently retrying against a different model would
             substitute an answer the caller never agreed to, the exact failure D-025
             itself exists to prevent one field over). Found by two real tests failing
             during implementation (test_generate_raises_for_nonzero_temperature...,
             test_qwen_local_is_also_a_real_dispatch_branch...), not designed in
             advance.

             CallRecord gained a provider field -- before this chain existed, PROVIDER
             was one fixed constant for the whole process, so "which provider" was
             implicit; once one call can legitimately be served by a provider other than
             the one LLM_PROVIDER names, that becomes a real auditability fact.
             agents/code_agent.py's trace payload now carries both provider and model --
             confirmed live in a real trace (see below), not just returned to the
             caller. _cache_key gained provider too, and caches per-(provider, model)
             rather than under the originally-requested model's key -- a fallback
             response must never be served back later as if the primary model produced
             it, once it recovers.

             Beat 6 proven live, real submission, real model, real verdict:
             agents/code_agent.py::grade() graded anas's real rendered
             weather_etl_transform submission (the same one D-048's mastery demo used)
             against the real master reference. Provider/model confirmed FROM THE TRACE
             itself (trace_id=48238, not just the returned CallRecord): provider=google,
             model=gemini-3.7-flash -- the corrective retry's model, after the first
             attempt's fallback-to-gemini-3.5-flash-lite response failed schema
             validation (both attempts are in COST_LOG, attempt=1/attempt=2, correctly
             attributed to the model that actually produced each one). Verdict:
             correctness=0, approach=0, readability=2, idiomatic=0, confidence="high",
             evidence_failures=[] -- correctly identifying an unimplemented submission
             (raise NotImplementedError() in both required functions). Every evidence
             quote independently string-matched against the real submitted file
             (invariant 6), checked by a second, separate pass over the file text, not
             by trusting the empty evidence_failures list alone. Widened trace query
             (student_id + last hour, not filtered to one actor) returned 10 real rows,
             not empty -- the verdict trace, its two update_mastery-triggered
             profile_update traces, and the five test_result traces from the same
             session's earlier D-048 demo, all genuinely connected to the same student
             and submission.
Alternative: Retry the SAME model on any exception, uniformly, up to N times (simple
             exponential backoff). Rejected as the task itself named: a billing failure
             retried against the same account, any number of times, accomplishes
             nothing but burning wall-clock time -- confirmed live this session (the
             original 429 would never have recovered by retrying the same key).
Alternative: Cross-provider fallback as the PRIMARY layer, within-provider as secondary
             or absent. Rejected because it does not match the measured failure mode: a
             free key's problem is per-model, not per-account, so jumping providers
             first would abandon a perfectly good (if overloaded) account before trying
             the fix that actually addresses what is failing.
Cost:        Two live SchemaValidationErrors were raised during this same
             implementation session (both correctly attributed, cost-logged, never
             silently dropped) -- gemini-3.5-flash-lite produced text that failed
             schema validation in every observation this session (3 of 3). This is a
             real, small-sample finding about the lite model's JSON reliability against
             this specific Verdict schema, not a defect in the fallback chain itself
             (which correctly identified each transient failure and correctly fell
             back) -- reported here rather than tuned away, per this project's own rule
             that a disappointing measured result is a finding.
Defence:     "The fix had to match the failure, not the failure's category. A free
             key's real problem is 'this one model is busy,' so the primary fix tries a
             different model on the same key before it tries a different account
             entirely -- and the two error classes that would make blind retrying a bug
             instead of resilience (billing exhaustion, and a caller's own mistake) are
             each detected and each skip the retry, not just logged after the fact."

---

### D-050 -- benchmark/run_benchmark.py built (Stage C3, the buildable half); the free
             Google tier's real daily cap makes the M4 stability table currently
             unmeasurable, not merely inconvenient
Date:        2026-08-25
Status:      DECIDED
Authority:   Anas (chose "run the full sweep now anyway" knowing the risk, live)
Context:     `benchmark/ground_truth.json` (template, every score `null` -- Anas's own
             labels, his to decide) and `benchmark/run_benchmark.py` (grades every
             submission N times, reports self-consistency, compares against ground
             truth where filled in) were built this session. Isolated by design: every
             grade() call in one run shares one DB transaction, rolled back by default
             -- confirmed clean (zero rows for the synthetic `_benchmark` student)
             across five separate runs this session, including two that crashed
             mid-sweep before this decision's own resilience fix landed.
             Two real bugs were caught and fixed BEFORE the full sweep, not after:
             (1) a `ForeignKeyViolation` -- `traces.assignment_id` genuinely
             REFERENCES `assignments` on the live schema, confirmed with `\d
             assignments`, not assumed from CLAUDE.md's abbreviated table listing (the
             same wrong-assumption class of mistake this session's compute_features.py
             regression already made once); (2) an unhandled exception in ANY single
             call killed the entire sweep and discarded every already-printed result,
             which a per-call try/except now prevents -- the transaction-wide rollback
             still protects against a half-written trace, the try/except protects the
             SWEEP itself.
             The full sweep (5 submissions x 3 runs = 15 calls) was then run for real,
             with the fix in place, and completed end to end instead of crashing:
             14/15 calls failed, 1/15 succeeded. 13 of those 14 failures were
             `quota_billing` -- `gemini-3.7-flash`'s real, documented free-tier cap:
             `GenerateRequestsPerDayPerProjectPerModel-FreeTier, quotaValue: 20`. This
             session's cumulative real LLM calls (D-049's runs, `scripts/demo.py`'s two
             live runs, this decision's own smoke tests) had already spent most of that
             daily budget before the sweep even started. The remaining 1 failure was a
             transient `ServerError`.
Decision:    Ship both files now, with the sweep's real (mostly-failed) output as
             genuine evidence rather than waiting for a clean run to commit them. Per
             `BUILD_PLAN.md`'s own M4 DoD, sanctioned explicitly: "the stability target
             is met, OR the deviation is documented with its cause analysed" -- the
             second branch is not a consolation prize, it is a legitimate result, and
             this decision IS that documentation. The real cause is not judge
             instability (only one real verdict was ever produced to be unstable
             against) -- it is that a 20-requests-per-day-per-model free-tier cap is
             structurally too small for a 15-call benchmark sweep run in the same
             session as everything else this project's real usage already does with
             the same key. `benchmark/ground_truth.json` staying all-`null` is
             unaffected by any of this -- it was never blocked on API access, only on
             Anas's own reading of the five submissions.
Alternative: Retry immediately, repeatedly, until the quota resets. Rejected: a daily
             per-project-per-model quota does not reset within a session, so retrying
             now would only burn more calls for the same guaranteed failure -- the
             exact reasoning D-049 already established for `quota_billing`
             classification skipping the retry chain entirely, now confirmed from the
             outside (an entire day's cap exhausted) rather than from one call's error
             code.
Cost:        A real M3 "why this model" answer, sharpened: the free tier is fine for
             occasional live grading (this session's earlier single-call demos all
             succeeded) but cannot carry a same-day benchmark sweep on its own. Getting
             a real stability number needs either `ANTHROPIC_API_KEY` (a second,
             separately-quota'd provider -- also closes M3's "two providers" DoD
             clause for real, not just in the gateway code) or running the sweep on a
             later day against a fresh quota. Neither attempted this session --
             recorded as the concrete next step, not assumed.
Defence:     "The benchmark script itself is proven correct -- isolated, rollback-safe,
             resilient to a single call's failure, verified clean across five real runs
             including two that hit real bugs I fixed live. What it measured this
             session is not judge instability, it is a 20-request daily cap on one free
             model, and the honest thing to do with that result is report it as the
             real constraint it is, not paper over it with a smaller, cleaner-looking
             sample."

---

### D-051 -- system/llm.py enforces its own call-timeout (30s); google-genai's SDK
             cannot be fixed by tuning a parameter
Date:        2026-08-25
Status:      DECIDED
Authority:   Anas
Context:     A live `scripts/demo.py` run this session sat completely silent for 15
             minutes and had to be killed. Traced fully: Beat 6's primary model
             (`gemini-3.7-flash`) took a real 222.3s before failing transient -- not a
             bug in `demo.py`, confirmed by re-running unbuffered and watching every
             beat's output land progressively (`scripts/demo.py`'s own D-051-adjacent
             buffering fix, same session, separate commit). Anas confirmed via web
             search that this is a known, currently unfixed gap in `google-genai`'s
             Python SDK, not something this project's code was doing wrong: the client
             delegates timeout behavior to the server by default, and even explicit
             `http_options` timeout settings are documented as unreliable
             (googleapis/python-genai#911, #681). Cannot be fixed by tuning an SDK
             parameter.
Decision:    `system/llm.py` enforces its own ceiling around the ONE place every
             provider handler is already called (`_call_with_fallback`'s dispatch to
             `_PROVIDER_HANDLERS[provider]`), uniformly for all three real providers,
             not just Google -- `_call_with_timeout` wraps that single call in
             `concurrent.futures.ThreadPoolExecutor.submit(...).result(timeout=
             _PROVIDER_CALL_TIMEOUT_S)`. A timeout is raised as `_ProviderCallTimeout`
             (a plain `Exception`, not a provider SDK type) and classified
             `"transient"` by `_classify_transport_error` via an explicit `isinstance`
             check -- reuses the EXACT SAME layer-1-then-layer-2 fallback chain D-049
             already built for any other transient failure, deliberately not a new
             trigger.
             `_PROVIDER_CALL_TIMEOUT_S = 30`, chosen over the proposed 30-45s range:
             every real successful call observed this session took 2-10s, so 30s
             leaves large headroom before a genuinely-working-but-slow call is cut
             off, while keeping the fallback chain's worst case (up to 3 models x up
             to 3 providers) bounded in minutes rather than the 222s-times-several the
             original incident could have produced.
             Named limitation, stated rather than hidden: `Future.result(timeout=...)`
             bounds how long `_call_with_fallback` WAITS, not literally how long the
             abandoned OS thread keeps running -- Python cannot force-kill a running
             thread. A hung SDK call still consumes a thread from the pool until it
             eventually finishes or the process exits; this fix makes the CALLER move
             on, not the underlying call disappear. Matches `assessment/test_runner.py`'s
             own "process-level isolation only" honesty about what a mechanism does
             and does not control.
Alternative: Tune `google-genai`'s own `http_options` timeout parameter. Rejected --
             the whole point of Anas's web-search finding is that this parameter is
             documented as unreliable for this exact SDK, so tuning it would be
             solving nothing while looking like a fix.
Alternative: Per-provider timeout logic inside `_call_anthropic`/`_call_nvidia`/
             `_call_google` individually. Rejected -- `_call_with_fallback` already
             has one dispatch point every provider goes through
             (`_PROVIDER_HANDLERS[provider]`); wrapping there is one mechanism for
             three providers instead of three separately-maintained ones, and it
             costs nothing to also cover NVIDIA/Anthropic against the same class of
             SDK gap this session only observed on Google.
Cost:        Real, live re-confirmation the SAME session: a second Beat 6 run hit the
             identical slow-primary-model pattern, this time caught at 29.6s (this
             fix's own ceiling firing, not the SDK's eventual multi-minute error) and
             correctly fell back to `gemini-3.5-flash-lite` -- `trace_id=61332`, all
             seven `scripts/demo.py` beats PASS, exit 0. 8 new tests in
             `tests/test_llm.py` (no prior test file covered `_classify_transport_
             error`/`_call_with_fallback` at all -- grepped, zero hits before this):
             the new timeout classification, the three EXISTING classification rules
             (quota_billing/transient/unknown) confirmed unchanged, `_call_with_
             timeout` itself (fast handler returns normally, slow handler raises,
             caller-side `ValueError` still propagates unwrapped), and the full
             fallback chain moving to the next model after a timeout. `pytest -q`:
             441 passed (+8), 0 failed. `ruff check .`: clean. weather_etl's 8
             attempts / 6 variants confirmed unchanged.
Defence:     "This isn't a guess at an SDK misconfiguration -- Anas confirmed via web
             search that google-genai's own timeout handling is a known, currently
             open gap in the library itself, not something tunable away. So the fix
             owns the ceiling at the one place in this codebase every provider call
             already funnels through, reuses the exact fallback path already built
             for any other transient failure rather than inventing a second one, and
             was proven live within the same session: the exact failure that
             motivated this happened again, and this time it was caught in 29.6
             seconds instead of running 222."

---

### D-052 -- seed_curriculum()'s pipeline stage list is per-project, not one hardcoded
             global tuple
Date:        2026-08-25
Status:      DECIDED
Authority:   Anas
Context:     `scripts/seed_data.py`'s `PIPELINE_STAGES = ("extract", "transform",
             "load", "quality")` was a single module-level tuple, used by
             `seed_curriculum()` both to discover which stage files exist for a
             project AND to derive each assignment's `seq` (pipeline order) via
             `enumerate(PIPELINE_STAGES, start=1)`. Found before writing Project 2
             (`VDEL_TEN_PROJECT_CURRICULUM.md` §3, CSV Sales Analyzer): its real files
             are `ingest.py`/`clean.py`/`aggregate.py`/`load.py` -- only `load`
             overlaps `weather_etl`'s shape, and even that would have landed at the
             wrong `seq` position (third, not fourth) had the tuple simply been
             extended. This threatens invariant 15 (`master_version`/line-range
             pinning): a wrong `seq` or a silently-dropped stage file would desync
             `gaps`' pinned line ranges from what actually got hashed into
             `master_version`.
Decision:    `seed_curriculum(cur, project_id, stages: tuple[str, ...] =
             PIPELINE_STAGES)` -- the stage list becomes a per-call parameter,
             defaulting to the original tuple so `weather_etl`'s existing call
             (`seed_curriculum(cur, "weather_etl")`) is byte-identical to before.
             Project 2 calls `seed_curriculum(cur, "sales_analyzer", stages=
             ("ingest", "clean", "aggregate", "load"))`. Verified live, twice, before
             touching Project 2 at all: `weather_etl`'s `master_version`
             (`75b5b7867e4dc08538b92a76cef32e58822223ef`), 4-row `assignments` seq
             ordering, and all 9 `gaps` rows confirmed byte-for-byte identical before
             and after the change, via direct SQL query, not inferred. A whole-
             codebase grep for `PIPELINE_STAGES` and the literal stage-name strings
             confirmed only `scripts/seed_data.py` referenced either -- the fix is
             fully contained to one function's signature.
Alternative: Append the new stage names to the existing global tuple. Rejected --
             `seq` is derived from POSITION in the tuple, so appending `ingest`/
             `clean`/`aggregate` after `quality` would put `load` (position 3 in the
             global order) before `ingest`/`clean`/`aggregate` (positions 5-7) for
             Project 2's own pipeline, backwards from the real ingest-then-clean-
             then-aggregate-then-load order. A single global tuple cannot give correct
             relative ordering for two projects with genuinely different stage
             vocabularies at once.
Cost:        None going forward -- `pytest -q` 433 passed (post-Project-2), `ruff
             check .` clean, `weather_etl`'s 8 `attempts` / 6 `variants` rows
             unaffected. Unblocks every future curriculum project
             (`VDEL_TEN_PROJECT_CURRICULUM.md` lists ten) from needing this same fix
             discovered again under time pressure.
Defence:     "The fix was verified against the real stakes, not just read as correct:
             weather_etl already had 8 real attempts and 6 real variants pinned to
             its exact master_version hash before I touched anything, and I diffed
             that hash, the seq ordering, and every gap row, byte for byte, before
             and after -- not asserted, queried."

### D-053 -- DeepSeek was agreed as the demo's primary provider on 19 Aug but was never
             implemented; Google/Anthropic used instead for a plain reason -- no key
Date:        2026-08-31
Status:      DECIDED
Authority:   Anas
Context:     The 19 Aug supervision meeting agreed DeepSeek as the primary model for the
             demo. `system/llm.py` has Anthropic, NVIDIA and Google as live provider
             handlers (D-031, D-032) and OpenAI/Qwen as structural stubs, but no DeepSeek
             handler was ever added, and no decision record explained the gap -- flagged
             this session as a real risk: an unexplained divergence from a supervisor
             meeting's own decision reads badly at the defence if asked about directly.
             Checked before writing anything: `.env.example` defines exactly three
             provider key slots (`ANTHROPIC_API_KEY`, `NVIDIA_API_KEY`, `GOOGLE_API_KEY`)
             -- no `DEEPSEEK_API_KEY` slot exists at any layer of the config. Confirmed
             directly with Anas: no DeepSeek API key is available in this environment.
Decision:    Do not implement a DeepSeek handler now. `system/llm.py`'s existing
             Anthropic/NVIDIA/Google trio (D-031, D-032) stays the provider set for the
             demo; the reason DeepSeek isn't among them is access, not a judgement about
             the model itself -- no key was ever obtained after the 19 Aug meeting.
             `_PROVIDER_HANDLERS`' dispatch-by-enum shape (`system/llm.py:907`) is
             unchanged and still has an open seam for a fourth handler whenever a key
             exists; adding one later is additive, not a redesign.
Alternative: Implement the handler now with a placeholder/empty key so the code exists
             ahead of access. Rejected -- an untested handler with no key to run it
             against is unverifiable exactly the way invariant 5's "every LLM output is
             schema-validated" and this project's own "never invent numbers" rule warn
             against: it would be code nobody has watched make one real call, sitting in
             the same file as three handlers that have.
Cost:        None to what's built -- the gateway's live proof (D-049, two real trace_ids)
             is entirely on the Anthropic/Google fallback path already in place. The real
             cost is scope: the demo runs on whichever of the three already-keyed
             providers D-050's stability sweep favours, not on the provider the 19 Aug
             meeting named. Named here, not hidden, so it has a defensible written answer
             rather than surfacing as a surprise gap in a viva question.
Defence:     "DeepSeek was agreed on 19 Aug and I checked for it directly this session --
             it was never given a key, not skipped by oversight. `.env.example` has no
             slot for it at all, which is real evidence the gap predates this session
             too. The provider seam (`_PROVIDER_HANDLERS`) is still open for it; nothing
             about the current three-provider gateway would need to change to add a
             fourth handler the day a key exists."
