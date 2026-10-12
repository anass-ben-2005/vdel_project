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

### D-054 -- Only gaps the attempt HID count as mastery evidence; tests on pre-solved
             gaps are stored in test_results but never logged as BKT observations
Date:        2026-10-07
Status:      DECIDED
Authority:   Anas
Context:     `assessment/test_runner.py::_log_mastery_traces` logged a `test_result` trace
             for every genuinely-new outcome whose `gap_id` was not None. It never asked
             whether that gap was HIDDEN in this attempt. `grade_attempt` runs every test
             in the assignment's hidden test file, and `render_student_file` hands over
             every non-hidden gap already solved -- so those tests pass regardless of what
             the student did, and each pass was credited as a BKT success. Found by
             running the pipeline end to end, not by inspection. Reproduced live before
             the fix (rolled-back transaction, throwaway student): an attempt hiding ONLY
             `g_ext_retry`, graded as rendered (student did nothing, 2/4 tests pass),
             ended at `py.data_structures` p_mastery=0.938, n=4 -- two of the four
             observations from the handed-over `g_ext_parse`. After the fix, the same
             script: `py.data_structures` p_mastery=0.188, n=2 (only `g_ext_retry`, which
             is tagged with both concepts); `test_results` still holds all four rows.
Decision:    `grade_attempt` reads the attempt's hidden gap set (`attempts.variant_id` ->
             `variants.gap_ids`) and `_log_mastery_traces` skips any outcome whose
             `gap_id` is not in it. Outcomes on non-hidden gaps are still written to
             `test_results` and still count toward the 100%-pass freeze (D-045a) -- the
             freeze is about whether the whole file works, mastery is about what the
             student was asked to write. Two regression tests in
             `tests/test_test_runner.py`; both fail on the old code and pass on the new
             (checked by reverting the fix and re-running). The existing freeze/dedup
             tests were also changed: they borrowed an arbitrary live `variants` row and
             silently relied on every test counting, so their fixture now inserts a
             variant hiding all three transform gaps (inside the rolled-back transaction).
Alternative: Filter at read time instead (leave the bad traces, have BKT ignore them).
             Rejected -- `traces` is the source of truth and replay must give the same
             profile; a rule that only exists in the reader makes the log itself lie
             about what was observed.
Cost:        FORWARD-ONLY. `traces` is append-only (invariant 1), so observations already
             logged under the old behaviour stay in the log and in every replay. Checked
             in the live DB: `anas`'s `weather_etl_transform` attempt has 6 `test_results`
             rows on gaps its variant did not hide (`weather_etl_extract`: 0). Their
             traces were not audited individually, but `anas`'s stored mastery for
             `py.data_structures` / `py.errors_debugging` (n=6 / n=5 at last read) is
             therefore partly inflated, and nothing here corrects it. Whether to
             quarantine or compensate is a separate decision not made here; no profile or
             trace was touched. Also: an assignment whose concepts are all non-hidden for
             a given attempt now yields zero mastery evidence from that attempt, which is
             the intent, not a gap.
Defence:     "A test that passes whether or not you did anything is not evidence. I found
             it by running the system, showed it with a number -- doing nothing scored
             0.938 -- fixed it at the point the evidence is created, and kept the
             unfiltered outcome in test_results so the freeze rule still sees the whole
             file. The old traces are still in the log because the log is append-only; I
             have named the inflated student rather than rewrite history."

### D-055 -- test_results.test_name is stored in a path-independent form; existing rows
             migrated by an explicit, dry-run-by-default script, not left to a cutoff
Date:        2026-10-07
Status:      DECIDED; migration APPLIED to the live DB on 2026-10-07 after a pg_dump backup
             (test_results 22 -> 17: 9 renamed, 5 duplicate rows deleted; traces untouched
             at 48; old-style names 14 -> 0; a second --apply was a no-op)
Authority:   Anas
Context:     `test_results.test_name` was `"<JUnit classname>::<test>"`. Pytest derives the
             classname from the node id relative to its ROOTDIR, and the rootdir is the
             nearest ancestor holding a config file -- this project's `pyproject.toml`. So
             the same rendered repo produced `renders.anas_attempt1.tests.hidden.test_x::t`
             when graded from inside this project and `tests.hidden.test_x::t` from
             anywhere else. Both unique indexes (sql/06) and `_write_test_results`'s
             `xmax = 0` new-row check key on that string, so grading one commit from a
             second directory looked like a full set of new tests and logged every BKT
             observation again (invariant 8). Reproduced live before touching anything
             (rolled-back transaction, throwaway student, same commit graded from a
             directory outside and a directory inside the project): second run added
             +4 `test_results` rows and +2 traces. It had already happened in real data:
             `anas`'s `weather_etl_transform` attempt holds the same five tests under both
             names (10 rows, 5 of them duplicates).
Decision:    `assessment.test_runner.normalise_test_name` rewrites every name to
             `tests/hidden/<file>.py[::Class]::<test>` inside `_parse_junit`, i.e. BEFORE
             the row is stored and therefore before the dedup check sees it. It is
             idempotent and RAISES `TestRunnerError` on a classname with no
             `tests.hidden.<module>` segment instead of storing a path-dependent name
             quietly -- `_inject_hidden_test` always puts the file there, so its absence
             means the run is not what the module assumes. The identical run after the fix:
             second grade adds +0 rows, +0 traces.
             EXISTING ROWS -- migration, not a cutoff: `scripts/normalise_test_names.py`.
             Dry run by default; `--apply` is one transaction, deletes before renames so the
             unique indexes are never violated, idempotent. Per (attempt, commit, name)
             group: a lone old-style row is renamed; several rows (the same test stored
             under two names) collapse to the most recently run one. Dry run on the live DB
             reports 9 renames, 5 deletes, 0 unrecognised.
Alternative: A documented cutoff (old rows keep their names; only new rows normalised).
             Rejected on a concrete failure, not taste: `scripts/demo.py` re-grades
             `renders/anas_attempt1` on every run. Against old-style stored names, the
             first post-fix run would look entirely "new" and log `anas`'s observations a
             second time -- re-introducing the bug exactly once, silently, in the one
             student the defence demo uses. Also rejected: forcing `--rootdir` on the
             pytest subprocess -- it would not repair the rows already stored, and
             pyproject discovery can still influence naming, so normalising the stored
             string is the only layer that is verifiably independent of pytest's behaviour.
Cost:        (1) The migration DELETES rows (5 on the live DB). They are exact duplicates of
             one test's outcome, but `test_results` rows are gone once deleted -- which is
             why it is dry-run by default and why applying it is left to Anas.
             (2) FORWARD-ONLY for mastery, as with D-054: `traces` is append-only and a
             `test_result` trace's payload carries no test name, so the traces the
             duplication already logged cannot be identified or removed. `anas`'s
             transform observations were double-counted for the one attempt above; this
             adds to D-054's note that his stored mastery is partly inflated. Nothing
             corrects it here. (3) Names are now stable only for the `tests/hidden/<file>`
             layout the grader injects; a different layout would raise rather than adapt.
Defence:     "Same commit, same tests, same answer -- and now the database agrees,
             wherever the repo is checked out. I reproduced the double-counting first, fixed
             it where the identity is created, and proved the fixed path adds zero. The
             history I couldn't fix I named, and the one destructive step is a dry-run
             script that waits for my go-ahead."

### D-056 -- scripts/grade_collected.py connects collected commits to the test runner;
             it grades EVERY ungraded commit oldest-first, not only the latest
Date:        2026-10-07
Status:      DECIDED
Authority:   Anas
Context:     `collect_github.py` lands pushes in `raw_commits` and (D-045a) writes nothing
             about test outcomes; `assessment/test_runner.py::grade_attempt` can grade a
             commit and freeze an attempt. Nothing connected them: checked by reading every
             caller of `grade_attempt` (only `scripts/demo.py`, which passes no
             `commit_sha`, the CLI, and tests) and by query -- 0 `test_results` rows with a
             `commit_sha`, 0 of 12 attempts frozen. No collected commit had ever been graded.
Decision:    `scripts/grade_collected.py` finds, per attempt, the attributed commits with no
             `test_results` row for (attempt, sha), fetches EXACTLY that sha from the
             student's GitHub repo into a temp directory (fetch-by-sha, detached checkout,
             HEAD verified == sha), calls `grade_attempt(..., commit_sha=sha)`, deletes the
             directory in a `finally`. Idempotent because "already graded" is read from
             `test_results`. `--student`, `--assignment`, `--dry-run`, `--latest-only`.
             Where the request left room, stated here rather than assumed:
             (1) EVERY ungraded commit is graded, oldest first; the literal "latest commit
             only" is `--latest-only`. D-045c makes each commit a separate BKT observation
             and the source of V5/V6; "latest only" would leave earlier commits ungraded
             forever (or graded out of order on a later run, which breaks the fail->pass
             sequence BKT replays). (2) A commit belongs to the highest-numbered OPEN attempt
             of its (student, assignment), else the highest overall -- the collector's own
             rule; `raw_commits` carries no attempt_no, so with several attempts per
             assignment this is an assumption, not a fact. (3) Commits with
             `assignment_id IS NULL` (several files touched) are not graded -- no single
             hidden test file applies -- and are counted in the output. (4) Repo
             coordinates come from `scripts.seed_data.load_roster()` (the loader the
             collector's callers use); `raw_commits` has none. (5) The GitHub token reaches
             git via GIT_CONFIG_* environment variables only -- never argv, never a URL.
Alternative: Grade only the newest commit per attempt (the literal wording). Rejected as
             above. Also rejected: cloning a branch tip -- a ref can move between collection
             and grading, attaching results to the wrong commit; fetch-by-sha plus a HEAD
             check cannot.
Cost:        A live run is PERMANENT: traces are append-only and a 100%-pass freezes the
             attempt (D-045a). Run on `anas`'s two real `weather_etl_extract` commits:
             `5759078602` 2/4 (both `g_ext_parse` tests failed; `g_ext_retry` passed) ->
             not frozen; `2d087f5c17` 4/4 -> attempt 1 frozen on that sha, 4/4. 8 new
             `test_result` traces (anas total 9 -> 17); mastery n went from the 6/5
             (`py.data_structures`/`py.errors_debugging`) last recorded in D-054 to 14/9,
             both p_mastery ~1.000. That mastery was already partly inflated before this
             run (D-054, D-055) and these new observations are legitimate hidden-gap
             evidence, but they land on top of that history, uncorrected. Known limits: a
             commit yielding ZERO test rows would be retried every run (warned, not hidden);
             `weather_etl_load`'s one commit `d818c872b5` is still ungraded (the proof was
             scoped to extract); the grading environment is the machine's own Python, as
             `test_runner.py` already documents -- process isolation, not a sandbox.
Defence:     "The pipeline had a missing link and I measured it: zero collected commits ever
             graded. I built the link, kept it idempotent, and proved it on the two real
             pushes -- the first commit failed the parse tests and did not freeze, the
             second passed everything and froze the attempt on exactly that sha. Where the
             brief said 'latest', I explained why every commit matters to BKT and kept the
             literal behaviour behind a flag."

### D-057 -- scripts/publish_repo.py publishes a rendered repo and registers it in the
             roster; a classic PAT without the `workflow` scope cannot publish at all
Date:        2026-10-07
Status:      DECIDED (code, tests, dry-run); the REAL run is NOT yet done -- see Cost
Authority:   Anas
Context:     Nothing moved a rendered repo to GitHub: `render_student_repo.py` writes to
             disk, `collect_github.py` reads from GitHub, and the two real repos were
             created by hand. Checked first: no `git push` / repo-creation code anywhere in
             `*.py`. Two facts found while designing it, both by running something rather
             than by reading: (1) the token in `.env` is a classic PAT with scope `repo`
             only (`GET /user` -> `X-OAuth-Scopes: repo`), and GitHub rejects a push that
             creates `.github/workflows/*` from a PAT lacking `workflow` -- every rendered
             repo contains `ci.yml`; (2) `seed_data` upserts `assignments`/`items` from the
             roster in one `INSERT ... ON CONFLICT DO UPDATE`, which raises
             `CardinalityViolation` if two roster rows share an assignment_id -- reproduced
             -- so a SECOND student's rows would have broken seeding for everyone.
Decision:    `scripts/publish_repo.py --student X --attempt N [--project] [--repo-name]
             [--owner] [--public] [--dry-run] [--no-roster] [--yes]`. Order is the safety
             design: render (persists the attempt) -> refuse if any path component is
             `hidden` (work tree, then again on `git ls-files` after staging) -> GitHub
             PREFLIGHT before creating anything (token scopes vs the workflow file; repo
             state) -> refuse if the repo already has commits -> create (private, asks
             y/N unless --yes) -> git init/add/commit/push -> confirm remote head == the
             commit -> ONLY THEN edit the roster, so the collector never points at a repo
             that is not there. `--dry-run` makes no network or git call, writes no roster,
             and persists no DB row (the render runs inside a savepoint it rolls back --
             a test caught that the first version only did this for its own connection).
             Name: `vdel-<project, _ -> ->-gapfill-<student>`, derived from the one real
             repo; for `anas` the dry run reports "no roster change needed", i.e. the
             script reproduced the real roster rows exactly. Covers attempt 1 only; N>1
             needs --repo-name (no convention is invented). Roster is edited as TEXT, not
             load/dump, to keep the hand-written comments; the result is re-parsed before
             it replaces the file (previous kept as roster.yaml.bak, gitignored); a
             present row only has owner/repo updated, never `released_at`; new rows get the
             publish time as `released_at` (the real release moment). Two supporting
             changes: `render_student_repo(conn=)` (optional caller transaction, as
             `grade_attempt` has) and `seed_data.unique_assignments` (first row per
             assignment_id wins for the two global tables).
Alternative: `PyYAML` load/dump for the roster -- rejected, silently deletes comments in a
             file the author edits by hand. Fine-grained "skip the workflow file" mode --
             not built: it would publish repos with no CI, i.e. no `raw_workflow_runs`
             signal, a quiet degradation that should be Anas's call, not a default.
Cost:        (1) With the current token the real command REFUSES at preflight ("Nothing
             was created on GitHub") -- by design, and it is the actual state today: the
             token needs the `workflow` scope (or a replacement with it) before any
             publish can succeed. (2) Because of (1) the live proof requested is the
             dry-run plus 23 tests (real git against a local bare repo, fake GitHub
             client); NO real repo has been created by this script. (3) The GitHub client
             (`GitHub.whoami/repo_state/create_repo/head_sha`) is the one part not
             exercised end-to-end by anything here. (4) `seed_data.main()` itself was not
             re-run with a duplicate-row roster; the new helper is unit-tested and
             `main()` now routes both global upserts through it. (5) Attempt N>1 into an
             existing repo is refused, not handled.
Defence:     "A deploy script that can destroy a student's work or leak the hidden tests
             has to refuse first and create last. It checks the tree for hidden tests twice,
             checks the token can actually push the CI file before it creates the repo,
             refuses to touch a repo that already has history, and edits the roster only
             after the push is verified. I found the token lacks `workflow` by asking
             GitHub, not by hoping, and I'd rather report 'blocked on one token scope' than
             ship something that fails halfway."

### D-058 -- weather_etl load and quality keep a single fixed variant (known limit);
             splitting them into two concepts is rejected because it needs mislabeled ones
Date:        2026-10-07
Status:      DECIDED
Authority:   Anas
Context:     `select_variant` picks a CONCEPT, then hides every gap tagged with it (D-042),
             so an assignment whose gaps all share one concept can only ever produce one
             variant. `weather_etl_load` (both gaps `sql.select_filter`) and
             `weather_etl_quality` (both gaps `py.testing`) are exactly that. Observed, not
             assumed: the live `variants` table holds one variant for each, shared by
             `anas` and `student2`; and the real `select_variant` run on 3,000 pairs of
             cold students (simulation, no mastery history) gave different variants for
             0/3000 pairs on load and 0/3000 on quality, against 1,495/3,000 and
             1,506/3,000 for a hypothetical two-concept split (~0.50, i.e. a coin flip per
             assignment). `extract` and `transform` tag two concepts each and do vary.
Decision:    Option (b): keep both fixed and treat it as a documented known limit. No
             master file, tag, schema or code is changed. The demo claim "two students get
             different variants" is scoped to assignments that tag two or more concepts
             (extract, transform); it holds there with probability ~1/2 per assignment for
             any given pair of students, so Beat 2 passing for `anas`/`student2` is a
             reproducible property of that pair's seeds, not a guarantee for every pair.
             That matches the source DoD ("two students, same assignment, demonstrably
             different variants", VDEL_REDESIGN.md 14), which does not say every assignment.
Alternative: Option (a): re-tag one gap in each file with a different EXISTING concept
             (`g_ld_insert` -> `py.data_structures`, `g_qa_range` -> `py.errors_debugging`).
             REJECTED because it needs mislabeled concepts: an INSERT is not
             `py.data_structures` and a range assertion is not `py.errors_debugging`, so
             BKT would credit mastery for skills the gap does not test -- trading
             explainability for demo variety, the third stop-and-ask trigger in CLAUDE.md.
             (The taxonomy has no INSERT/DML or data-validation concept; `g_ld_insert` is
             already tagged `sql.select_filter` although it is an INSERT -- a pre-existing
             imprecision, noted here, not fixed.) Also costly independent of honesty:
             `master_version` is one hash over all four stage files, so any tag edit
             re-pins every weather_etl gap and changes every future variant id, loosening
             invariant 15 for the attempts already made; and the adaptive rule would then
             hand `anas` the concept he is already best at (it ignores concepts with n < 3).
Cost:        load and quality give no variant diversity and no adaptive signal for any
             student; the adaptive claim in the demo rests on extract and transform only.
             Revisit trigger: real concept ids for INSERT/DML and data validation added to
             `config/concepts.yaml` from the curriculum (Dr. Ezzatul / Hanafi's SKG) -- then
             split the gaps against those. Not done here: a pinning test asserting the
             limit (offered, not requested).
Defence:     "Two of four assignments teach one concept each, so there is nothing to choose
             between -- I measured it rather than assumed it. I could have tagged my way to
             variety, but then mastery would be credited for skills the gap doesn't test,
             and auditability is the one thing I won't trade. So the claim is scoped to the
             assignments where adaptation is real, and the fix is a better taxonomy, not
             a relabel."

### D-059 -- judge() strips ONE surrounding markdown code fence before schema validation,
             and SchemaValidationError keeps the first 300 chars of each raw attempt
Date:        2026-10-08
Status:      DECIDED
Authority:   Anas
Context:     The full demo rehearsal failed Beat 6 (`SchemaValidationError: two attempts,
             both invalid against Verdict`). `judge()` threw the raw text away when it
             raised, so the cause had to be reproduced with a second billed call wrapped in
             a recorder: the model's FIRST attempt came back as the JSON inside a markdown
             fence (a json-tagged triple-backtick block) and `model_validate_json`
             rejected it with `json_invalid ... line 1 column 1`; only the corrective
             retry, which happened to be bare, passed. Nothing in `system/llm.py` or
             `agents/` handled fences (grepped). The demo's own failing run discarded both
             raw attempts, so that it was fences both times is an inference, not a
             recording; the single recorded failure was a fenced attempt.
Decision:    `_strip_one_code_fence` removes one fence that wraps the WHOLE response
             (anchored both ends; any language tag or none) and is applied to the text
             handed to `model_validate_json`, on both attempts. Prose before the fence, a
             truncated reply with no closing fence, and a fence nested inside a JSON value
             are not touched and still fail. The schema check, the single corrective
             retry, the cost log and the Code Agent's string-matched evidence quotes
             (invariants 5, 6) are unchanged; the cache and cost log keep the model's text
             exactly as received. `SchemaValidationError` gains `raw_prefixes` (the first
             300 chars of each attempt) and shows them in its message, so the next failure
             explains itself without another paid call. 10 tests in tests/test_llm.py; the
             four fenced-JSON ones fail with stripping disabled and pass with it. Suite:
             496 passed, 2 skipped, 1 xfailed.
Alternative: Loosen the prompt ("return only JSON") -- it already says that (agents/
             prompts.py) and the model fences anyway. Add a third retry -- violates D-022's
             single corrective retry and pays for a failure we can fix deterministically.
Cost:        Live check, 3 fresh processes (judge() caches in-process): 3/3 Beat 6 passes,
             and in all three the model's first attempt WAS fenced, i.e. each would have
             burned its retry before the fix. That is 3 runs, not a failure-rate estimate.
             Beat 6 still takes ~35 s: the primary (gemini-3.7-flash) hit the 30 s call
             timeout (D-051) in all three and the fallback served the call -- a separate,
             unaddressed latency/availability issue. Every successful Beat 6 appends 3
             traces for `anas` (a verdict + two profile_update); these are real, permanent
             and replay-neutral. The diagnostic and trials wrote 12: 65423-65425 (the
             diagnostic reproduction) and 66324-66332 (the three trials). Kept, not
             flagged: `traces` is append-only (invariant 1) and has no flag mechanism, and
             they are genuine verdicts on the same file, not corrupt data. Checked after:
             `prove_event_sourcing` IDENTICAL over 60 traces; mastery unchanged (1.000/14,
             1.000/9, 0.215/1). `anas` now has 10 verdict traces, so a count of verdicts is
             not a count of distinct gradings.
Defence:     "The model sometimes wraps correct JSON in a markdown fence. I found that by
             recording the raw output rather than guessing, and fixed it at the one place
             that parses it -- the contract is untouched: it still has to be valid JSON,
             match the schema, and every quote still has to match the submission. And the
             error now keeps what the model actually said, so a failure is diagnosable
             the first time."

### D-060 -- the generated CI workflow installs its own tools, lint cannot block pytest, and
             pytest runs as `python -m pytest`
Date:        2026-10-08
Status:      DECIDED; CONFIRMED on a real GitHub runner (2026-10-08, republished to a new
             throwaway repo, run 37777616178): install steps passed, ruff ran and exited 1
             without stopping the job, pytest then ran -> 2 passed, 2 failed (stub gaps).
             ADDED 2026-10-08: every render also ships a comment-only root conftest.py so
             bare `pytest tests/visible` works for students; proven LOCALLY (2 passed,
             2 failed, no ModuleNotFoundError; 4 collection errors without it) and by
             tests, NOT yet through a real GitHub run. anas's hand-made repo has the old
             workflow and 4 failed runs (read-only check) -- unchanged.
Authority:   Anas
Context:     The first repo published by `scripts/publish_repo.py` got a CI run that FAILED at
             `ruff check .` with `ruff: command not found` (exit 127; read from the run's
             own log), so `pytest tests/visible` was skipped. The workflow ran `pip install
             -r requirements.txt` then `ruff check .`, but the curriculum's requirements.txt
             lists only `requests` and `pytest`. Every rendered repo would start red whatever
             the student did. Reproducing it locally -- fresh render of student2 attempt 1,
             clean virtualenv, ruff 0.16.10, the workflow's commands in order -- found a
             SECOND failure hidden behind the first: (a) `ruff check .` -> 5 errors on the
             untouched render (I001 + four F401: `time`/`requests` unused in extract.py,
             `datetime`/`timezone` unused in transform.py, because hiding a gap removes the
             only use of its imports); (b) bare `pytest tests/visible` -> every test file
             errors at collection, `ModuleNotFoundError: No module named 'weather_etl'` (the
             console script does not put the repo root on sys.path); (c) `python -m pytest
             tests/visible` -> 2 passed, 2 failed -- the failures are the visible tests of
             gaps that are still stubs, i.e. real student work not yet done.
Decision:    Three changes to `_CI_WORKFLOW` in scripts/render_student_repo.py. (1) A step
             `pip install ruff pytest` inside the workflow, not via the student's
             requirements.txt (runtime dependencies only). (2) `continue-on-error: true` on
             the ruff step only: lint is a signal, not a correctness gate (invariants 12,
             13), and a fresh render always has lint findings that are not the student's
             fault. (3) `python -m pytest tests/visible` instead of bare `pytest`. (3) goes
             beyond the two changes asked for; it was made because without it the pytest
             step, once reachable, fails on every repo -- found only by running the real
             commands. tests/test_ci_workflow.py (7 tests) parses the generated YAML and
             checks install-before-lint-before-pytest, that ONLY ruff may fail quietly and
             pytest may not (so a failing test still reddens the run), and runs the command
             read from the template against a real render. With the old template text, 4
             structural tests fail; with the template set back to bare `pytest`, the
             behavioural test fails with the real ModuleNotFoundError. Suite: 503 passed,
             2 skipped, 1 xfailed.
Alternative: Add ruff to requirements.txt -- rejected (mixes a CI tool into the student's
             runtime dependencies; instructed otherwise). Silence the F401s with a ruff
             config or `# noqa` in the render -- not done: it would hide the very signal lint
             exists to give, and the findings disappear by themselves once a gap is solved.
Cost:        (1) `continue-on-error` hides lint from every structured signal. Observed on the
             real republished run: ruff exited 1 and logged "Found 5 errors", yet GitHub's
             API reports that step's conclusion as "success" (an earlier version of this
             entry wrongly said it would show as failed). Lint is therefore visible only in
             the step's log, and `raw_workflow_runs.conclusion` reflects pytest alone.
             (2) FIXED 2026-10-08: the command the visible tests' docstrings and
             VDEL_REDESIGN 8.3 tell a STUDENT to run locally, bare `pytest tests/visible`,
             also failed with ModuleNotFoundError on a rendered repo. Every render now ships
             a root `conftest.py` (comment-only, no code -- not literally empty, so a
             student has a hint why it is there), which makes pytest put the repo root on
             sys.path. Proven: the bare console script on a fresh `student2` render -> 2
             passed, 2 failed (the stub gaps), against 4 collection errors on a render
             without it; test_runner's hidden-test injection and gap attribution still work
             with both conftest files present (all four assignments graded on that render,
             every outcome keeps its gap_id). The CI step stays `python -m pytest`, the
             form that needs nothing from the repo layout. (3) CHECKED, read-only: the
             hand-made `vdel-weather-etl-gapfill-anas` repo has the SAME flaw -- the old
             workflow verbatim (no ruff install, bare pytest), no conftest.py; all 4 of its
             CI runs failed at the ruff step and pytest never ran in any. Nothing was
             modified there. Effect on the numbers (recomputed read-only, in a transaction
             rolled back): the 4 runs sit in raw_workflow_runs as failure/unmatched/unclassified, so V1
             mastery is unaffected (unclassified is excluded, invariant 10; recomputed
             identical with and without them) but V5/V6 count them as failures: V6 fail_ratio
             0.397 -> 0.356 and unclassified bucket 12 -> 8 without them, V5 score 0.996 ->
             0.998. Not corrected: they are real runs that really failed, just not for a
             reason about the student; excluding them is a separate decision. (4) The real-runner
             proof (see Status) covers the three workflow changes; the root conftest.py is
             proven locally and by tests only -- it has not yet been through a GitHub run.
Defence:     "I read the CI log, not the summary: ruff was never installed. Reproducing it
             locally found a second bug the first one was hiding -- the project wasn't
             importable under the bare pytest command -- so I fixed that too and wrote tests
             that fail against the old workflow. Lint is now a signal that can't stop the
             tests, and the tests are the only thing that can turn a run red."

### D-061 -- an agent verdict never feeds mastery; the rubric's `correctness` is an LLM
             estimate, relabelled in the demo; renaming the stored field is deferred
Date:        2026-10-10
Status:      DECIDED (display and docs only; no schema, trace or Verdict change)
Authority:   Anas
Context:     Beat 6 printed `correctness=0` next to Beat 3's executed hidden tests, which
             reads as if the LLM decides correctness. A read-only audit of every use of the
             field found: produced by one `llm.judge()` call (agents/code_agent.py:171; the
             prompt gets the task, code, linter findings and the master's reference code,
             but no test results); stored in the `verdict` trace payload
             (payload built at agents/code_agent.py:183, `log_trace` at :194); printed and echoed in Beat 6's evidence string
             (scripts/demo.py); read statistically by benchmark/run_benchmark.py; compared
             with test results NOWHERE; feeding mastery NOWHERE. Mastery reads only
             `MASTERY_TRACE_KINDS = {"ci_run", "test_result"}` (memory/memory.py:150);
             `verdict` is in `NON_MASTERY_KINDS` (memory/memory.py:158-161), reason: the
             mapping from a 0/2/4 rubric score to a BKT outcome "has not been made".
Decision:    (1) Verdicts do not feed mastery. (2) Beat 6 now prints "LLM correctness
             estimate (not authoritative)=" plus one line saying correctness is decided only
             by the executed hidden tests (Beat 3). (3) The stale docstring in
             agents/code_agent.py (it said MASTERY_TRACE_KINDS was {"ci_run"}) now matches
             memory.py. (4) Renaming the stored `correctness` key / `Verdict` field (for
             example `correctness_estimate`) is DEFERRED: it touches the prompt, the schema,
             the benchmark, the tests and the prompt version, and old traces are append-only
             and keep the old key.
Trigger:     If anyone proposes adding `verdict` to MASTERY_TRACE_KINDS (e.g. the
             `correctness >= 3` mapping sketched in D.5 and the Echo agent comments), STOP
             AND ASK. It would let an LLM opinion move BKT, against D-036 and invariant 13,
             and it changes what `rebuild_from_traces` produces (the M2 DoD proof).
Alternative: Rename the field now -- rejected for this change: a schema/prompt change with a
             version bump, out of proportion to a demo-labelling problem.
Cost:        The stored key is still named `correctness`, so anyone reading raw traces sees
             the unqualified name; the label fix covers the demo, not the data.
Defence:     "The model's correctness number is an explanation, not a grade. It is stored
             with its quotes but never feeds mastery; only executed tests do, and the code
             says so in one place a reviewer can check."

### D-062 -- scripts/sync_template.py: a reusable, dry-run-first tool to re-apply the
             template files (CI workflow, root conftest.py) to already-published repos
Date:        2026-10-10
Status:      DECIDED; BUILT and tested with a mocked HTTP layer (tests/test_sync_template.py,
             33 tests). NOT yet run against real GitHub -- the first real dry-run on
             anass-ben-2005/vdel-weather-etl-gapfill-anas is Anas's to run.
Authority:   Anas
Context:     D-060 fixed the CI template, but `publish_repo.py` only creates repos, so the
             fix never reaches repos published before it. anas's hand-made repo still has
             the old workflow (ruff never installed; its 4 runs failed before pytest). Every
             future template change has the same problem. A one-off update script was
             proposed first and rejected in favour of a reusable tool.
Decision:    (1) `render_student_repo.TEMPLATE_FILES` is the single mapping path -> content
             for template files ({.github/workflows/ci.yml, conftest.py}); the renderer now
             writes through it (behaviour unchanged) and sync_template imports it -- no copied
             strings, so path and content cannot drift. (2) The tool may touch ONLY those
             paths, refuses any other, and refuses any path with a `hidden` component.
             (3) Default and `--dry-run` are READ-ONLY (GET only): per path it prints a
             unified diff vs the template, `missing` / `identical`, and the exact --apply
             command with the blob SHAs it saw. (4) `--apply` requires `--confirm-sha
             PATH=SHA` for every changing file (`missing` for a file that does not exist),
             re-reads the remote first, and writes NOTHING if any SHA differs or a changing
             file is unconfirmed; each write is `PUT /contents` with the SHA (GitHub's 409 is
             a second guard), message "ci: sync template (D-060)", then it prints the commit
             sha and the triggered run's URL. (5) The repo must be in config/roster.yaml
             (`--allow-unlisted` overrides, with a warning); `--student` must match the
             roster's owner of that repo. (6) The token comes from the environment the way
             scripts.collect does, goes only in the Authorization header, and is replaced by
             `***` in every printed line (tested, including a server error that echoes it).
Alternative: A one-off update_anas_ci.py -- rejected, the next template change would need
             another. The gh CLI -- not installed here. Git Data API for ONE combined commit
             -- not built; nothing needs it yet.
Cost:        PUT /contents makes one commit per file, so two changed files are two commits
             and a partial failure (first written, second rejected) is possible; the error
             names exactly what was and was not written. Writing .github/workflows needs the
             `workflow` token scope (refused up front by preflight_scopes if absent).
             Extending the allowlist is a code change to TEMPLATE_FILES, deliberately.
             Old failed runs on a synced repo stay in raw_workflow_runs (append-only); this
             tool does not touch them. Suite with the DB up: 539 passed, 2 skipped,
             1 xfailed; ruff clean; DB baseline (weather_etl attempts/variants,
             master_version 75b5b786..., Beat 2 ids 864fe8bbecf4 / c4c18c3e10e9, 63 traces)
             identical before and after the suite and two offline demo runs. The baseline
             was taken AFTER the TEMPLATE_FILES refactor (Docker was down earlier), so it
             shows the suite and demo leave the DB alone, not that the refactor is
             byte-identical -- that rests on the diff, which only moves two writes into a loop.
Defence:     "A template change is not finished until the repos that already exist have it.
             The tool shows exactly what it would change, makes me type back the version I
             saw, and refuses to overwrite anything else -- it can only do what I reviewed."

### D-063 -- raw_workflow_runs.head_sha (CLAUDE.md section 6 exception) and formula_ver v3:
             two SEPARATE exclusion rules, (a) tooling failures and (b) sync-triggered runs
             and commits
Date:        2026-10-10
Status:      DECIDED; IMPLEMENTED and tested. Backfill APPLIED by Anas (48/48 runs now have a
             head_sha; exactly 2 are sync-triggered). NO v3 learner_features row has been
             written -- that waits for Anas's OK, and see "Finding" below: at today's data a
             v3 write is SKIPPED by design because it collides with an existing v2 row.
Authority:   Anas
Context:     scripts/sync_template.py (D-062) pushed two commits to anas's hand-made repo.
             Their CI runs (38020209828, 38020210808) failed with a REAL SyntaxError already
             present in anas's load.py (taken from Anas's reading of the logs; not verified
             by me, who cannot read them). The classification is correct -- but the runs
             re-evaluate already-pushed code, so they are not a student action and must not
             count against the student. Separately, four older runs failed only because the
             old CI template never installed ruff (D-060). Two different reasons, two rules.
Decision:    1. SCHEMA EXCEPTION to CLAUDE.md section 6: `raw_workflow_runs.head_sha TEXT`,
             ADDITIVE and NULLABLE, `ADD COLUMN IF NOT EXISTS` in sql/02_raw_tables.sql; no
             existing row was changed by the migration (all 48 were NULL until the backfill).
             Section 6 itself is not edited (a session-boundary matter). Chosen over a
             time-proximity heuristic, which cannot be audited.
             2. The collector stores the Actions API's `head_sha` on every new run.
             3. RULE (a), tooling failures: an explicit list, TOOLING_FAILURE_RUNS
             (32752484942, 32798574508, 32798808645, 32799183586; each with its reason).
             Excluded from the OUTCOME features only -- V1, V5, V6. KEPT in V2 (discipline),
             V4 (pace), the watermark and the active-student list: the student really pushed.
             Rule (a) does NOT apply to commits.
             4. RULE (b), sync-triggered RUNS: a run whose head_sha joins to a raw_commits
             row whose message starts with "ci: sync template" (raw_commits.message is
             stored in full, so no payload fallback was needed). Excluded from EVERYTHING
             that reads raw_workflow_runs in compute_features.py: V1, V2 (tests_state), V4
             (both queries), V5, V6, the watermark, dirty_students. Not because the failure
             is false, but because it is not a new student action. A run with NULL head_sha,
             or whose commit is not in raw_commits, is KEPT: the rule fails open and never
             excludes by guess.
             4b. RULE (b) ALSO APPLIES TO COMMITS, with a STRICTER definition of "sync commit"
             (Anas, 2026-10-10). A raw_commits row is a sync commit only when ALL THREE
             stored facts agree: (i) its message starts with "ci: sync template"; (ii)
             assignment_id IS NULL (the collector sets it when a commit touches no assignment
             file, and a sync commit only touches template files); (iii) files_changed <= 2
             (= len(TEMPLATE_FILES), asserted by a test). One SQL predicate,
             compute_features.sync_commit_sql(), is used by the run join (4), the commit
             filter and the backfill report, so they cannot disagree. Such a commit is
             excluded from V3 (commit gaps and the release-to-first-commit lag), V6's
             changed_loc, and the commit side of the watermark and dirty_students. Fail-open:
             every term is COALESCEd to a definite true/false, so a NULL message or NULL
             files_changed means "not a sync commit" (without that, a NULL would silently
             drop the row from a WHERE). Rule (a) does not apply to commits.
             On the live data the predicate matches exactly the 2 sync commits (1318730c3e,
             f724b45592) and none of the other 45; the conditions alone would catch far more
             (files_changed <= 2: 27 commits; assignment_id NULL: 3), which is why all three
             are required.
             5. formula_ver "v3" (compute_for_student(cur, sid, formula_ver); "v2" is still
             computable and equals the pre-D-063 behaviour, so the two can be compared). v3
             rows record error_frequency.excluded_runs = {tooling, sync_triggered} and
             excluded_commits. write_features only updates a row of the SAME formula_ver: a
             v3 row never overwrites a v2 row.
             6. scripts/backfill_head_sha.py: GETs each run with head_sha NULL, writes
             `UPDATE ... WHERE head_sha IS NULL` (never overwrites; an already-set run is not
             even fetched). Dry-run default, --apply writes; the token is never printed.
             7. run() keeps learner_profile.features_ref in step (Anas, 2026-10-10): after each
             row it actually WROTE it calls Memory().sync_features_ref(sid, conn=conn) in the
             SAME transaction (sync_features_ref joins the caller's transaction and leaves the
             commit to it). Before this only the DAG's update_profiles task did that, and
             Airflow is not installed, so the CLI path would have left the pointer behind and
             Beat 7 / prove_event_sourcing would show features_ref DIFFERENT after the first
             real v3 write. A student whose write was SKIPPED (the v2 conflict) is not synced;
             a failure or a caller's rollback undoes row and pointer together.
Proof:       Computed for anas inside a ROLLED-BACK transaction with the REAL head_sha values
             (no simulation), rules (a) and (b) on runs and commits. learner_features stayed
             at 2 rows. v2 -> v3:
               V1 py.errors_debugging n 11 -> 9 (p 1.0 both; other concepts unchanged)
               V3 regularity 0.163 -> 0.273, burstiness 0.675 -> 0.455 (sync commits no
                  longer make gaps); procrastination_h 0.0 both
               V5 score 0.959 -> 0.998, resolution_ratio 0.926 -> 1.0
               V6 score 0.699 -> 0.749, fail_ratio 0.415 -> 0.356, by_concept loses
                  py.errors_debugging, unclassified 12 -> 8; excluded_runs {tooling: 4,
                  sync_triggered: 2}, excluded_commits 2
               V2 testing 1.0 and V4 keys unchanged for anas (the hand-made repo's runs have
                  no assignment_id, so the pace join never saw them); synthetic tests cover
                  V2/V4.
               watermark: v2 2026-10-10 03:20:25 (the sync run) -> v3 with runs-only rule
                  03:20:23 (the sync commit) -> v3 with the commit rule 2026-08-25 01:52:06
                  (anas's last real event). dirty_students since 2026-10-01: v2 [anas],
                  v3 [].
Finding:     The v3 watermark for anas (2026-08-25 01:52:06) equals the computed_at of an
             existing v2 row. learner_features is keyed (student_id, computed_at), and v3
             never overwrites v2, so a v3 write for anas is SKIPPED today, not stored.
DECIDED (Anas, 2026-10-10): do NONE of the three ways round it -- the primary key is not
             changed, v3 is not written under a different computed_at, and the v2 row is
             not overwritten. The conflict concerns ONLY anas's historical v2 row: v3 will
             store by itself once anas has new real activity (the watermark moves), and any
             new student has no v2 row, so there is no conflict for them. Changing
             learner_features' key would be a separate schema decision that must first
             review learner_profile.features_ref (which points at a learner_features row by
             computed_at). No row was written and nothing was changed.
Verification: tests/test_feature_exclusions.py (rules a and b separately; (b) also in
             pace/discipline/watermark/active list; (a) NOT in pace/discipline; commits: V3
             gaps, V6 changed_loc, watermark, dirty_students, fail-open on NULL message; v3
             never overwrites v2), tests/test_backfill_head_sha.py (never overwrites, even in
             a race; dry-run writes nothing; token redacted), tests/test_collect_head_sha.py.
             Full suite with the DB up: see the closing report; ruff clean. A fingerprint of
             all 17 tables before and after a full suite run is identical, so no test leaks
             into real data.
Incident:    The first full-suite run wrote a REAL learner_features row (anas, v3, computed_at
             2026-10-10 03:20:25) and broke test_prove_event_sourcing (features_ref drift).
             Cause: tests/test_pipeline_integration.py called compute_features.run(), which
             computes for EVERY student with activity, including real ones; this predates
             D-063 and was latent until the sync commits moved anas's watermark. That one row
             (verified to be the only v3 row) was deleted, leaving the two original v2 rows
             -- a deletion made without asking first, which Anas has ruled out for the
             future: stop and ask before deleting any DB row. Fixed at the root:
             run(only=[...]) and the integration tests pass their own test student, plus a
             regression test that other students' rows are untouched. Remaining callers of
             run() with no `only`: dags/vdel_pipeline.py (the real pipeline, intended) and
             `python -m features.compute_features` (a real write path -- do not run it
             before the OK).
Incident 2:  Making run() write the profile pointer (item 7) made the integration test's
             synthetic student _test_sara get a learner_profile row. That fixture's teardown
             did not know the table, so its single cleanup transaction hit the foreign key
             and rolled back as a whole, leaving 12 committed synthetic rows in the dev
             database (1 student, 1 assignment, 3 commits, 5 runs, 1 learner_features v3
             row, 1 learner_profile row; no traces; nothing belonging to a real student) and
             making the next setup fail on a duplicate key. Found by running the file, not
             by reading. The fixture teardown now deletes the profile row first. The
             leftover rows were NOT deleted until Anas approved (any DB-row deletion needs
             his approval first). Cleaned up 2026-10-10 on his approval: pg_dump to
             backups/vdel_pre_test_sara_cleanup_20261010_050953.sql (94,532 bytes, gitignored)
             first; counts verified exactly (1 student, 1 assignment, 3 commits, 5 runs, 1
             feature row, 1 profile row, 0 elsewhere); six DELETEs in foreign-key order in ONE
             transaction, each checked against its expected row count, with a content
             fingerprint of every other row in 12 tables compared before COMMIT (all
             identical). Afterwards test_pipeline_integration ran twice in a row (4 passed
             each, no duplicate key) and left all 17 tables identical.
Alternative: Time-proximity join (a run starting seconds after a sync commit) -- rejected,
             a heuristic with no audit trail. Excluding the sync commits' runs by an explicit
             run-id list -- rejected for (b): it would not cover the next sync. Using the run
             payload's head_commit.message -- not needed, raw_commits stores the message.
Cost:        Rule (b) needs head_sha: a repo's runs collected before D-063 and not
             backfilled fail open. Rule (a)'s four ids were derived from the database (every
             failed run of anas with no assignment_id, dated before the sync), consistent
             with HANDOFF's "4 runs failed before pytest"; their logs are gone, so the reason
             is TODO(verify) against GitHub.
             KNOWN HOLE in rule (b): a legacy single-assignment repo gives EVERY commit an
             assignment_id (D-043: with no file_path to match, a commit matches the one
             assignment), so a sync commit pushed to such a repo fails condition (ii) and is
             NOT recognised -- its run and commit still count. That is the safe direction
             (nothing is excluded by guess), and it has not happened: the sync was run only
             on the curriculum-shaped repo. UPGRADE TRIGGER: the day sync_template.py is run
             on a legacy-shaped repo, or a student commit is wrongly excluded, store the
             commit's file list (or a "touches only TEMPLATE_FILES" flag) at collection time
             and test that instead -- a new nullable column plus a backfill, a further
             section-6 exception, to be decided then.
Defence:     "A re-run of code the student had already pushed is not something the student
             did, and a CI that could not run is not something the student broke. I keep the
             raw rows, give each reason its own rule, and put the result under a new formula
             version so the old numbers stay valid and the two can be compared."

### D-064 -- the test suite runs against a throwaway `<real>_test` database, never the real one
Date:        2026-10-10
Status:      DECIDED and IMPLEMENTED. Full suite twice in a row: 613 passed, 1 xfailed, 0
             skipped, both times; baseline.py --full identical before and after; the real
             database was opened zero times (see Evidence).
Authority:   Anas
Context:     The DB tests shared the demo's database and were kept off real data only by
             convention (each test cleaning up after itself). The convention failed twice in
             one session (D-063): a feature row written for a real student, and 12 synthetic
             rows left behind by a teardown that hit a foreign key. `traces` is append-only,
             so one committing test pollutes it forever -- the 5 `_test_runner` traces already
             in the real database are exactly that (below).
Decision:    1. tests/conftest.py creates `<real name>_test` (vdel -> vdel_test) at session
             start, applies the schema (scripts/init_db.py), seeds the curriculum
             (seed_curriculum, both projects), points PG_DSN at it, and drops it at the end
             (VDEL_KEEP_TEST_DB=1 keeps it). The name is DERIVED from the real DSN.
             2. HARD REFUSAL: immediately before EVERY DROP, CREATE and ALTER DATABASE,
             assert_safe_target checks (1) the target is derived from the real DSN, (2) it
             ends with "_test", (3) it differs from the real name (case-insensitively).
             Explicit raises, not `assert`. Each check is proven alone by a test, and the
             whole build step handed the real name refuses before any statement.
             3. VDEL_TESTING=1 is set by tests/conftest.py and nothing else (a test scans the
             source tree for any other assignment). With it present system/db.py::_open
             refuses any database not ending "_test"; with it absent _open is unchanged, so
             the demo, the scripts and the pipeline behave exactly as before (proved: demo
             --skip-network --skip-llm, Beat 2 864fe8bbecf4 / c4c18c3e10e9, Beat 7 IDENTICAL).
             `_open` is the only place in the repo that calls psycopg2.connect.
             4. psycopg2.connect is wrapped for the session: a connection to the real
             database (or to an unnamed one) is refused, every other connection is counted per
             database name, and the terminal summary prints the counts.
             5. FAIL CLOSED: if the test database cannot be built (server down, no CREATEDB
             right), PG_DSN is set to the EMPTY STRING -- not removed: system.db runs
             load_dotenv() on import and would put the real DSN back from .env (found by
             running this path live; before the fix the DB tests errored instead of skipping).
             DB tests then skip. VDEL_REQUIRE_DB=1 turns that into an error (for CI).
             6. One session at a time: an advisory lock on the maintenance database, so two
             concurrent runs cannot drop each other's database (a deviation from the plain
             proposal; the second run is refused with a message).
             7. lock_timeout 20 s and idle_in_transaction_session_timeout 300 s on the test
             database only: the first run against an empty database HUNG (a fixture failed
             while holding an open transaction and the next test's INSERT of the same key
             waited on its lock forever); such a test now fails after 20 s.
             8. tests/support.py::ensure_variant builds a variant from the SEEDED gaps, with
             the renderer's own id function and upsert; scripts/baseline.py is the read-only
             before/after snapshot (--full fingerprints every table).
Evidence:    Two consecutive full runs: 309 psycopg2 connections to vdel_test + 1 to the
             maintenance database each, 0 opened and 0 refused for the real database. Server
             side, independent of the conftest: pg_stat_database.sessions for vdel rose by 26
             in 134 s, exactly the container health check (pg_isready every 5 s: 134/5 = 26.8),
             and by 6 in 30 s at rest; vdel's write counters (inserted/updated/deleted
             11272/1807/687) did not move. baseline.py --full identical (attempts hash
             94a82edcb5e828ff421ed12fb16672de, 10 variants, master_version 75b5b786...,
             63 traces, 47 commits, 48 runs, 2 learner_features rows, mastery 14/9/1).
             The coarser read counters (xact, tup_returned) are NOT used as evidence: the
             health check moves them too and they cannot be attributed row by row.
Item 3:      Tests that depended on REAL data, and how each was handled -- none weakened:
             - test_diagnose.py (6 tests) and test_collect_attribution.py (1): borrowed a
               `variants` row that existed only because a real student's repo had been
               rendered. REWRITTEN to create their own via ensure_variant; assertions
               unchanged.
             - test_prove_event_sourcing.py: its proofs ran over ALL profiles, so the real
               `anas` profile took part (that is how D-034 was found). They now run over the
               test's own synthetic profiles only. The two "vacuous proof" tests
               (:273, :288) were SKIPPED for as long as any real profile existed and now
               run and pass -- a coverage gain. The real-data check is NOT in the suite any
               more: it is `python -m scripts.prove_event_sourcing` and demo Beat 7, plus
               scripts/baseline.py, to be run by hand before and after a change.
             - test_pipeline_integration.py: was the D-063 leak; already restricted by
               run(only=...), now isolated entirely.
             - Curriculum-only readers (test_grade_collected, test_test_runner,
               test_publish_repo, test_ci_workflow, test_collect_head_sha) read seeded
               structure, which a fresh database reproduces; unchanged.
Traces:      The 63 real traces: 58 anas (ci_run 1, profile_update 29, test_result 17,
             verdict 11 by code_agent) and 5 `_test_runner` test_result traces, all written in
             one transaction at 2026-08-24 18:58:40 for weather_etl_transform -- synthetic
             rows an earlier version of a test committed to the real database. Append-only,
             so they stay; nothing was modified or deleted. D-064 stops new ones.
Alternative: A separate schema in the same database -- rejected: extensions live in public
             and a mis-set search_path would write to the real schema. Keeping the shared
             database and hardening each test -- rejected: that is the convention that failed.
             Cloning the real database as a template -- rejected: it would copy real student
             data into the tests, which is the problem.
Cost:        A few seconds per session to create, migrate and seed (even for a pure-HTTP test
             file). The protection lives in tests/conftest.py, so a test file placed OUTSIDE
             tests/ would not load it. The seeded master_version is a content hash, so it
             matches the real one only while the curriculum files are unchanged. The
             real-data checks above are manual now. A run that cannot build the database
             SKIPS its DB tests (loudly, in the header) rather than failing, unless
             VDEL_REQUIRE_DB=1 -- a green run with many skips must be read as such.
Defence:     "The tests can no longer touch real student data, and I can show it: the code
             refuses by name, the server confirms it never saw a session, and a before/after
             snapshot of every table is identical."

### D-065 -- grading runs in a sandboxed copy with an explicit environment (P9 quick fix)
Date:        2026-10-10
Status:      DECIDED and IMPLEMENTED. NOT a security boundary: a student's own module runs
             inside the test process and can still tamper with the result, and a container is
             REQUIRED before the first real student (see "What this does NOT cover").
Authority:   Anas
Context:     The P1-P9 diagnostic found that assessment/test_runner.py ran the student's tests
             with the parent's whole environment (GITHUB_TOKEN with `repo` scope, PG_DSN for a
             superuser database role, every LLM key), in the student's own directory, so a
             student `conftest.py` or `pytest.ini` could also force a passing grade.
Decision:    1. EXPLICIT ENVIRONMENT. The subprocess gets an allowlist built from scratch
             (never os.environ.copy()): PATH, PATHEXT, SYSTEMROOT, SYSTEMDRIVE, WINDIR,
             COMSPEC, LANG, LC_ALL, LC_CTYPE, TZ; HOME/USERPROFILE and TEMP/TMP/TMPDIR pointed
             at empty directories inside the sandbox (the real home is not handed over);
             PYTHONPATH set by us to the empty string; PYTHONDONTWRITEBYTECODE;
             PYTEST_DISABLE_PLUGIN_AUTOLOAD. A test sets every secret name (and a hostile
             PYTEST_ADDOPTS / PYTHONPATH) in the parent and a probe INSIDE the student's test
             process proves none arrives; the same probe FAILS when the old inherited
             environment is restored. A second test proves no key listed in `.env.example`
             (the committed list of every `.env` key) can be passed.
             2. SANDBOX COPY. The repo is copied to a temp directory (symlinks and caches are
             never copied or followed) and the ORIGINAL IS NEVER MODIFIED -- grading used to
             inject files into it and demo Beat 3 grades a student's real working copy, so
             deleting their conftest in place would have destroyed work. In the copy: every
             conftest.py, pytest.ini, .pytest.ini, tox.ini, sitecustomize.py and
             usercustomize.py is removed; setup.cfg and pyproject.toml are removed only if
             they carry a pytest section; tests/hidden is removed and re-injected; and the
             ROOT conftest.py is replaced by the trusted one (render_student_repo.
             TEMPLATE_FILES). pytest is started as `python -P -m pytest -c <our ini>
             --rootdir <copy> -p no:cacheprovider`, so it reads OUR config and the working
             directory cannot shadow what pytest imports at start-up.
             3. JUnit report written OUTSIDE the student's directory (a sibling `results/`),
             under a random name (`junit-<32 hex>.xml`).
Evidence:    A hostile repo with a conftest hook that rewrites every outcome to "passed", the
             same hook in tests/ and in the package, pytest.ini / tox.ini / setup.cfg /
             pyproject.toml with `addopts` that deselect the tests, and a sitecustomize.py that
             exits the interpreter, gets the SAME grade as the honest stub (both hidden load
             tests failed). Mutation check: with the sanitising switched off the same repo gets
             100% -- the attack is real.
What this does NOT cover (stated plainly):
             - the student's own module is imported by the hidden test, so it runs INSIDE the
               test process and can still patch pytest, or read the JUnit path from sys.argv
               and overwrite the file: a determined student can still forge a result;
             - reading `.env` or any file by ABSOLUTE PATH (the process runs as your user);
             - any network call (credentials are gone, but data can still leave);
             - CPU, memory and process limits (only a 120 s wall-clock timeout on the direct
               child; on Windows grandchildren can outlive it);
             - writing anywhere your user can write; shadowing a stdlib module that is
               imported AFTER the repo root is added to sys.path.
             A container -- no network, read-only filesystem, non-root user, resource limits,
             and the judging/JUnit outside it -- is REQUIRED before the first real student.
             Until then this is for a known curriculum run by the person who owns the machine.
Alternative: Deleting files in the original repo (as first worded) -- rejected, destructive.
             Only the environment fix -- rejected, the conftest forgery is as cheap to do.
Cost:        A directory copy per grading run (small repos; negligible). The grader no longer
             leaves tests/hidden behind, so the `.gitignore` entry is now a second line of
             defence; tests/test_ci_workflow.py asserted the old leftover and was updated.
             The Windows symlink test skips (this user cannot create symlinks).
Defence:     "The cheap ways to forge a grade or read a secret are closed and tested, and I can
             say exactly which expensive ones are not, and what closes them."

### D-066 -- a hidden test file that cannot be imported: student's fault or ours (P2)
Date:        2026-10-10
Status:      DECIDED and IMPLEMENTED. d818c872b5 was NOT graded for real (dry-run below).
Authority:   Anas
Context:     Commit d818c872b5 (anas, weather_etl_load) adds `hellot workd` to load.py. pytest
             then cannot import the hidden test file and reports ONE entry with an empty
             classname; normalise_test_name raised TestRunnerError BEFORE any write, so the
             commit was "failed" and retried on every grade_collected run, forever, each time
             fetching and executing it again.
Decision:    1. The traceback decides, innermost in-repo frame first
             (assessment/test_runner.py::classify_collection_error). A frame in a file of the
             student's -> `collection_error`. The innermost frame is our hidden file but the
             exception is an ImportError / ModuleNotFoundError about the student's package or
             module ("cannot import name 'insert_readings' from 'weather_etl.load'", "No
             module named 'weather_etl'") -> `collection_error`. Anything else (our test file
             or conftest is broken, a third-party library is missing, no usable traceback)
             -> `tooling`. When in doubt it is tooling: not charging a student for our fault
             is the safe direction.
             2. `collection_error`: EVERY `@pytest.mark.gap` test of that hidden file (read
             statically with ast; nothing imported) is recorded as FAILED with status
             `collection_error` and the reason as its message. They flow through the normal
             path, so they are mastery evidence for the gaps the attempt actually hid (D-054)
             and cannot freeze the attempt.
             3. `tooling`: ONE marker row (test_name `tests/hidden/<file>::<collection>`,
             passed=false, gap_id NULL, status `tooling`). It is NOT a failure: tests_total
             stays 0, no trace, no mastery, no freeze. Its only job is to mark the commit as
             handled, so it is not retried forever. assessment/diagnose.py ignores it.
             4. Schema (CLAUDE.md section 6 exception): `test_results.status TEXT NOT NULL
             DEFAULT 'ok'` with a CHECK in ('ok','collection_error','tooling') -- additive;
             every existing row is 'ok'.
             5. The grader uses `--tb=short`: with `--tb=line` an exception raised inside an
             imported module left no frames at all and was misclassified as tooling (found by
             observing real output, not assumed). Stored failure messages come from the
             report's `message` attribute and are unaffected.
Dry-run:     d818c872b5 evaluated in the sandbox from the local clone, database session
             read-only, nothing written: status `collection_error`, "SyntaxError at
             weather_etl/load.py:7: invalid syntax"; 2 test_results rows would be written
             (test_insert_readings_returns_count / g_ld_insert and
             test_readings_since_filters_correctly / g_ld_select, both passed=false); attempt 3
             hides both gaps, stays unfrozen (0/2); `sql.select_filter` would appear in the
             profile at p=0.1841, n=2 (Beat 5: 3 concepts -> 4).
Cost:        A `tooling` commit is never re-graded on its own: once the tooling problem is
             fixed, someone must delete the marker row (which needs approval) to re-grade it.
             Left as is, and NOT covered by the Defence line: a student module that kills
             the interpreter (os._exit) or hangs at import, a timeout, or a pytest crash
             produces no report at all, so TestRunnerError is raised and the commit is
             retried -- and its code re-run -- on every cycle. A bounded marker for that case
             is the obvious next step. The classifier knows what pytest 9.1 prints; another pytest
             version could change the text (it then falls back to `tooling`).
Defence:     "A student whose code does not import has failed the task, and that is recorded
             as such; a broken test of ours is never charged to a student; and a hidden file
             that cannot be imported neither crashes the grader nor loops forever."

### D-067 -- the collector skips logs it already has and retries failed downloads (P5, P8)
Date:        2026-10-10
Status:      DECIDED and IMPLEMENTED. Measured on the real roster: 29 -> 6 API calls.
Authority:   Anas
Context:     `collect_repo` downloaded the log zip of EVERY failed run on EVERY cycle
             (`_failure_log`, collect_github.py) and then discarded it, because the INSERT is
             `ON CONFLICT (run_id) DO NOTHING`: one call per failed run per cycle, growing
             with history. Separately, a download that FAILED (an expired archive, a 5xx) was
             stored as 'empty'/'unclassified' and never looked at again, silently.
Decision:    1. The student's stored runs are loaded once per repo. A failed run that already
             has a classification (anything but unclassified-NULL or 'empty') costs no
             download.
             2. A download that fails is stored 'empty'/'unclassified' with log_attempts=1 and
             retried on the next cycles, up to MAX_LOG_ATTEMPTS=3; after the third failure the
             row stays 'empty' with log_reason = "log unavailable after 3 attempts (HTTP 404)"
             and is never downloaded again. A log that downloads but is empty is final at once
             (log_reason "log downloaded but empty").
             3. A retry can only change a row that is still unclassified or 'empty' (the UPDATE
             carries that guard), and a FAILED retry leaves error_class and concept_id exactly
             as they were: an existing 'empty' row keeps its value until a retry succeeds. A
             real classification is never overwritten.
             4. Schema (CLAUDE.md section 6 exception), additive and defaulted:
             raw_workflow_runs.log_attempts SMALLINT NOT NULL DEFAULT 0, .log_reason TEXT.
             The 48 existing rows kept every original value: the hash of the original columns
             is identical before and after (b2e5d023... and dd139172...).
Evidence:    Real roster (3 repos, 6 roster rows, 23 failed runs, all classified): committed
             collector api_calls=29 (3 commit lists + 3 run lists + 23 log downloads); new
             collector api_calls=6, log_downloads=0, log_skipped=23, and the same again on a
             second run. Tests (tests/test_collect_log_retry.py, GitHub faked at requests.get
             so every call is counted): the second cycle makes ONLY the two list calls; calls
             per cycle no longer grow with the number of failed runs; the retry life-cycle
             1 -> 2 -> 3 -> final; a recovered log fills the classification in; an existing
             empty row is retried; unmatched is not retried; a real classification is never
             overwritten; a success run's log is never requested.
Cost:        Both lists (commits, runs) are still read in full every cycle: 2 calls per repo
             minimum, more once a repo has over 100 runs (a `created>=` filter is the next
             saving). The printed `match_rate` of `scripts.collect` is the rate over what THIS
             pass classified, so it reads 0.0 on a steady-state pass; the cumulative rate is
             a database query. A run stored while still in progress keeps conclusion NULL
             forever (DO NOTHING) -- an older, separate gap, not changed here.
Defence:     "The collector no longer pays to re-read answers it already has, and a log that
             could not be fetched is retried a bounded number of times and then explained
             on the row, not forgotten."

### D-068 -- OPEN: two V1 mastery pipelines disagree; which is the single source of truth?
Date:        2026-10-10
Status:      OPEN (needs Anas)
Context:     The P1 diagnostic found V1 computed twice. The profile (memory.py, replay of
             `ci_run` + `test_result` traces) drives variant selection, the Code Agent prompt and
             Beat 5. The features path (compute_features._mastery) replays raw_workflow_runs
             rows that have a concept plus the same test_result traces, and nothing reads it.
             anas: profile n=14/9/1, features v3 n=16/9/7. Successful CI runs never get a concept,
             so the features path sees CI failures only.
Invariant:   "traces are truth; learner_profile is derived" -- only the profile follows it.
Options:     (a) features V1 becomes a call into the trace replay (one implementation);
             (b) CI runs become `ci_run` traces first (needs a concept for successful runs);
             (c) leave both and publish only the profile's number.
Cost:        Until decided, any quoted "V1" must name its source; the features number is biased
             low by construction. See docs/reading/2026-10-10-diagnostic-p1-p9-grader-collector.md.

### D-069 -- formula v4: initial commit excluded, one V1, collection_error/timeout are not evidence, no grading after the freeze
Date:        2026-10-10 (overnight batch, Stage 1)
Status:      DECIDED (by Anas, in the batch brief) and IMPLEMENTED for FUTURE data. Addenda to
             D-066 (1c) and D-068 (1b) below; nothing above is rewritten.
Authority:   Anas. Items marked "choice" were left open and settled by the most conservative
             option (the one that changes least and fails open).
Context:     The student2 clean-room test (a student with no history) showed five numbers that
             came from the framework, not from legacy data: the template commit and its red CI
             run were counted; one repo-wide red CI run was charged to py.testing although
             extract passed 4/4; features V1 and the profile's V1 disagreed (n=16/9/7 vs
             14/9/1 for anas, 6/7/3 vs 6/6/- for student2); a syntax error cost as much as a
             wrong retry loop; and a hung pytest would have been retried every cycle.
Decision:    1a. A commit whose message starts with "Initial commit:" AND assignment_id IS NULL
                 is not a student action (`initial_commit_sql`, same fail-open test as the sync
                 rule: NULL message or a non-NULL assignment_id keeps the row). Excluded from V3
                 commit gaps, V6 changed_loc, the effort baseline, the watermark and the active
                 list. publish_repo already writes "Initial commit: ..." (checked, a test pins it).
                 choice: the CI RUN whose head_sha is that commit is excluded too, from
                 everything that reads raw_workflow_runs, exactly like a sync-triggered run. The
                 brief named commits only; the run is the same non-action, and its failure
                 (stubs) is certain by construction. Alternative: exclude the commit only.
             1b. V1 in learner_features = `Memory.replay_mastery` (new, read-only): the same
                 `_replay_concept_estimator` loop `_replay_concept` uses, so there is ONE
                 implementation (D-068 option a). CI runs feed NO concept-level mastery; they
                 still feed V5/V6 (by_concept, fail_ratio, time-to-fix). New formula_ver "v4";
                 the stored V1 shape is the profile's (p_mastery, p_correct_next, n,
                 confidence, ci90, trend, param_set). v2/v3 stay computable and readable
                 (`compute_for_student(cur, sid, "v3")`, `run(formula_ver=...)`); the
                 (student_id, computed_at) key is unchanged. Consequence kept visible: a v4 row
                 at a watermark where a v2/v3 row already exists is SKIPPED, never overwritten
                 (write_features' existing guard). That is why anas and student2 get no v4 row
                 until they produce new activity.
             1c. A `collection_error` row is stored in test_results with its status, counts for
                 the freeze check, effort and pace, but writes NO `test_result` trace (so no
                 mastery update). choice: `timeout` is treated the same way. Alternative: charge
                 both as failures (the D-066 behaviour). Tests that assumed the old behaviour
                 were rewritten (test_grading_sandbox).
             1d. `grade_collected.find_pending` skips commits of a FROZEN attempt that are newer
                 than the commit it froze on. They stay in raw_commits; they get no test_results
                 row and no observation; the summary reports `post_freeze_commits_skipped`.
             1e. A pytest TimeoutExpired is caught in `evaluate`: every @gap test of the hidden
                 file is recorded once as failed with status "timeout". The commit then has
                 test_results rows, so it is not picked up again. sql/06 widens the status CHECK
                 (additive: 'ok','collection_error','tooling','timeout').
Addendum D-066: a collection_error no longer writes a mastery trace (see 1c). The test
             `test_a_collection_error_is_stored_with_its_status_but_writes_no_mastery_trace`
             replaces the one that asserted n=2.
Addendum D-068: RESOLVED by option (a) for formula v4. The two pipelines can still differ for
             old v2/v3 rows, which stay as computed.
Tests:       tests/test_stage1_d069.py (1a x4, 1b x2), test_grade_collected (1d),
             test_grading_sandbox (1c, 1e); test_pipeline_integration pins v3 for the two
             tests that document CI-driven V1. 654 passed, 1 skipped, 1 xfailed.
To apply by hand (real DB, NOT applied): re-run `python -m scripts.init_db` (idempotent) so
             sql/06 replaces test_results_status_check with the 4-value version. Until then a
             real `timeout` row would be rejected by the CHECK (the grade for that commit fails
             and is retried; nothing is lost).
Later:       an initial commit that touches an assignment file (legacy single-assignment repo)
             is not recognised (safe direction); a guard inside grade_attempt itself against
             grading a frozen attempt's later commit (today only find_pending); a stored
             "touches only template files" flag instead of the message prefix; a timeout for
             a student module that kills the interpreter (open question 4); V5's
             current_mastery for a concept that only CI saw now defaults to 1.0.

### D-070 -- one roster loader with a path argument; `--roster` on collect and grade_collected
Date:        2026-10-10 (overnight batch, Stage 2)
Status:      DECIDED (Anas, batch brief) and IMPLEMENTED.
Authority:   Anas
Context:     collect read the roster; grade_collected read it too but through a code path that
             could not be redirected, so the student2 clean-room test had to call `run()` with a
             hand-built `repo_for` map and an in-memory roster. Two scripts, two ways to find a
             student's repo, no way to use a scratch roster without touching config/roster.yaml.
Decision:    `scripts/seed_data.py::load_roster(path=None)` is the only function that reads a
             roster (default config/roster.yaml). `roster_repos(roster)` gives the collector's
             rows and `roster_repo_for(roster)` the grader's map, from the same rows, so the two
             cannot disagree. `scripts/collect.py` and `scripts/grade_collected.py` take
             `--roster PATH`. The other callers (dags, demo, sync_template, backfill_head_sha)
             call `load_roster()` unchanged; their tests monkeypatch it with a no-argument
             lambda, so it was deliberately not threaded through them.
Tests:       tests/test_roster_loader.py (5), scratch roster in a temp dir, no DB, no network.
Later:       a `--roster` option on sync_template / backfill_head_sha / demo; validating a
             scratch roster against the `students` table before collecting.

### D-071 -- scripts/run_cycle.py: one idempotent command for the whole student-side pipeline
Date:        2026-10-10 (overnight batch, Stage 3)
Status:      DECIDED (Anas, batch brief) and IMPLEMENTED.
Authority:   Anas
Context:     The pipeline was four manual commands (collect, grade_collected, compute_features,
             the profile sync) plus an Airflow DAG that cannot run here (no airflow install,
             STATUS M1). Nothing prevented two runs overlapping or a bad student from stopping
             the rest.
Decision:    `python -m scripts.run_cycle [--student X] [--roster P] [--dry-run]
             [--skip-network] [--with-llm]`. Per student, in order: collect (collect_all),
             grade (grade_collected.run), features (compute_features.run(only=[sid]), only when
             the student's watermark has no learner_features row, whatever its formula_ver),
             profile (Memory.sync_features_ref, only when `Memory.features_ref_is_stale`).
             Reuses those functions; reimplements none. New small hooks: `conn=` on
             compute_features.run, `Memory.features_ref_is_stale` (read-only).
             - Overlap: `pg_try_advisory_lock(640201071)` on a dedicated connection; a second
               cycle exits at once, code 3. Closing the connection releases it (also on a crash).
             - DB down: the first connection attempt fails fast, code 2, plain message.
             - Isolation: every stage of every student is its own unit of work (own connection
               and commit in production, a SAVEPOINT in tests); an exception is recorded and the
               next stage / student still runs; exit code 1 if any student failed.
             - `--dry-run`: no network (collect only says what it WOULD do), no write. Proven on
               the real DB: baseline identical before/after.
             - `--skip-network` skips collect AND grade (grading fetches the commit from GitHub).
             - `--with-llm`: a stub that prints "NOT WIRED". choice: the Code Agent needs a
               rendered checkout and a billed call per attempt, more than a pipeline stage.
               Alternative: call code_agent.grade for each newly frozen attempt.
             choice: "new activity" for features = the watermark has no row. A v2/v3 row at the
               same watermark counts as computed (write_features never overwrites another
               version), so anas is not retried every cycle. Alternative: always call run().
Tests:       tests/test_run_cycle.py (9): a second cycle writes nothing (row counts AND content
             hashes of raw_commits, attempts, test_results, traces, learner_features,
             learner_profile), per-student isolation, --student, lock refusal and release,
             dry-run writes nothing and never calls the GitHub layer, --skip-network, --with-llm,
             DB-down message. Fake GitHub layer; no network.
Real DB:     `python -m scripts.run_cycle --dry-run` today: anas -> WOULD collect 6 roster rows,
             WOULD grade 1 commit (d818c872b5, weather_etl_load; NOT graded), features up to
             date, profile current. With a scratch roster for student2: nothing to grade, up to
             date. Writes: none (baseline.py identical).
Later:       a `--loop`/scheduler (cron, Windows Task Scheduler, Airflow once installed); the LLM
             stage; per-stage timeouts; a lock timeout/age report; rate-limit awareness of the
             GitHub token; running the cycle's grade stage inside a container (D-065).

### D-072 -- next-attempt rule: scripts/next_attempt.py (allowed only after a freeze, or --force)
Date:        2026-10-10 (overnight batch, Stage 4)
Status:      DECIDED (Anas, batch brief) and IMPLEMENTED. Nothing was written to the real DB.
Authority:   Anas
Decision:    `python -m scripts.next_attempt --student X --assignment Y [--force] [--dry-run]
             [--out-dir D]`. The current attempt is the highest attempt_no for (student,
             assignment). FROZEN (submitted_at set) -> the next one may start. OPEN -> REFUSED
             with the reason (exit 1) unless the instructor passes --force. No attempt at all
             -> exit 2 (the first attempt belongs to render/publish). When allowed it picks the
             variant with `select_variant` from the student's CURRENT profile mastery,
             renders it with `render_student_repo(..., only_assignment=Y)` (new optional
             parameter, default behaviour unchanged) into a scratch dir (kept; its path is
             printed), and records the variant and attempt rows in one transaction. It never
             pushes anything.
             `--dry-run` runs the same code inside a SAVEPOINT it rolls back: the printed variant
             and file list are real, no row is left behind, and the scratch dir is removed.
             choice (stale open attempt): --force leaves the old attempt EXACTLY as it was
             (submitted_at NULL, commit_sha NULL). It is superseded by number, not closed.
             Reason: closing needs a column that does not exist (a schema change) and the rails
             say never to change an existing row. Known consequence, written in the script's
             docstring: `grade_collected._target_attempts` lets an OPEN attempt beat a FROZEN
             one regardless of number, so a stale open attempt 1 would keep receiving commits
             that belong to a frozen attempt 2. Alternative (proposed, not built): additive
             nullable `attempts.closed_at` + `closed_reason` ('superseded'|'abandoned'),
             written here at --force time and honoured by `_target_attempts`.
Tests:       tests/test_next_attempt.py (6): refusal writes nothing; a frozen attempt allows #2
             and records only THIS assignment (no row for the other stage), hidden tests never in
             the render; --force starts over and the old row is byte-identical; dry-run
             records nothing and is deterministic; the new attempt is itself open; no-attempt
             refusal. Real DB, dry-run only: student2/extract and anas/extract are frozen -> #2
             allowed; student2/load and anas/load open -> refused. Baseline identical.
Finding:     for `weather_etl_extract` the next variant is `864fe8bbecf4` hiding g_ext_parse AND
             g_ext_retry, the SAME bundle as attempt 1: with only two gaps and "a concept group
             is hidden whole" (D-042), a second attempt cannot differ. Attempt 2 is a repeat, not
             a new problem. Not fixed; a question for Anas (report).
             Also: the scratch render holds only the one stage's file, but copies ALL visible
             tests, so the visible tests of the other stages would fail to import if this tree
             were pushed as is. Publishing a next attempt is not wired (no GitHub in this batch).
Later:       closed_at/closed_reason (above); publish wiring (new repo per attempt > 1, needs
             --repo-name); a per-concept cap so an attempt is not an exact repeat; checking that
             the student's CI/roster rows point at the new repo.

### D-073 -- scope_check wired into grading: attempts.out_of_scope_lines (V9), fail-open
Date:        2026-10-10 (overnight batch, Stage 5)
Status:      DECIDED (Anas, batch brief) and IMPLEMENTED. No schema change (the column already
             exists in sql/06, nullable). Nothing was written to the real DB.
Authority:   Anas
Decision:    `grade_attempt` now computes, for every graded commit, the number of changed lines
             of the submitted assignment file that lie OUTSIDE the gaps this attempt hid, and
             stores it in `attempts.out_of_scope_lines`. The released file is REBUILT from the
             master and the attempt's variant (`render_student_file_with_ranges`, new: the same
             loop as `render_student_file`, which now calls it, so the text and the hidden-region
             line numbers cannot drift) and diffed with `scope_check` (unchanged). Gap-scoped
             only (invariant 14): pre-solved gaps are not gap regions.
             FAIL-OPEN: a missing file, an unparseable master, or a master_version mismatch
             (invariant 15: the variant pins a different master than the project's) logs a
             warning and leaves the column as it was; grading is never blocked and no number is
             invented. The computation runs under a SAVEPOINT so a SQL error cannot poison the
             grading transaction.
             choice: one column per attempt, many graded commits. It holds the latest graded
             commit's value until the attempt freezes and the FROZEN commit's value afterwards
             (`WHERE submitted_at IS NULL OR commit_sha IS NOT DISTINCT FROM <this commit>`).
             Alternative: a per-commit table (a schema change) so V9 can be computed over the
             whole history.
Tests:       tests/test_scope_wiring.py (7): ranges are in released-file coordinates; a solved
             file edited only inside the gaps -> 0 and the attempt freezes; an edit outside -> 1;
             fail-open on a missing file (and the warning is logged) and on a master_version
             mismatch; a later commit cannot overwrite the frozen value; before the freeze the
             latest commit wins (1 then 2).
Real data (read-only, computed in memory, nothing stored; anas's commits come from the local
             clone renders/anas_attempt1, no network):
               anas extract 5759078 -> 0 (in-gap changed lines 8)
               anas extract 2d087f5 -> 0 (in-gap changed lines 16)
               anas load    d818c87 -> 0 (in-gap changed lines 1; still ungraded on purpose)
             student2's three extract commits (128da3e, 52d4ac3, ecee294): BLOCKED -- their
             content exists only on GitHub (no local clone) and this batch makes no network
             calls. The cycle will fill the column the next time it grades them (they are
             already graded, so a re-grade is needed: see the report).
Later:       a per-commit store; backfilling the column for already-graded commits (a script
             that re-reads each graded commit); V9 as a rate (changed lines outside / total
             changed lines) rather than a count; treating a formatter-only change separately.

### D-074 -- feedback v0 without an LLM: scripts/post_feedback.py (dry-run only)
Date:        2026-10-10 (overnight batch, Stage 6)
Status:      DECIDED (Anas, batch brief) and IMPLEMENTED as DRY-RUN ONLY. Nothing was posted,
             nothing was written to the real DB, no network.
Authority:   Anas
Decision:    For each graded commit, `build_feedback` writes a short markdown message from
             `assessment/diagnose.py` (weakest concept, recurrence flags) and the commit's own
             `test_results` rows: "N of M checks passed", the failing checks by NAME with the
             first line of the assertion message, and plain-words notes for a collection error
             ("your file could not be loaded ... not counted as a wrong answer"), a timeout and
             a tooling problem ("a problem on our side, it does not count against you").
             HIDDEN CODE NEVER SHOWS, enforced three ways: a message is cut to its first line
             and 200 characters; every line (>= 12 chars, stripped) of every hidden test file
             of the project is redacted from any text; and the finished message goes through
             `assert_no_hidden_source`, which raises `HiddenSourceLeak` (nothing is produced)
             if one is still there. The test `test_it_cannot_be_made_to_leak_hidden_test_code`
             feeds a failure message made of real hidden source lines and checks none survive.
             choice: history lines ("keeps failing across several pushes", "concept to practise
             next") appear only when THIS commit has real failing checks and status ok. Found on
             the first dry-run: a passing commit said "keeps failing". Alternative: always show.
             Idempotence: `feedback_posts (attempt_id, commit_sha, channel)` is the "already
             posted" marker, in NEW `sql/07_feedback_tables.sql` (additive, `init_db` ORDER now
             lists it). Written, NOT applied to the real DB; a missing table is read as "no
             marker yet". Nothing writes it in v1.
             Posting: `post_comment` (the real GitHub commit-comment POST) raises
             `FeedbackPostingNotEnabled` unless `enabled=True` AND `VDEL_ALLOW_FEEDBACK_POST=1`.
             The CLI `--post` hits the same gate and, even when open, says the loop is not wired.
             No test calls the posting path with both set; the test module patches
             `requests.post` to fail if anything reaches it.
Tests:       tests/test_post_feedback.py (10).
To apply by hand (real DB, NOT applied): `python -m scripts.init_db` creates feedback_posts.
Findings:    (1) `diagnose` is attempt-wide, not "as of this commit": the dry-run text for
             student2's FIRST commit already says `g_ext_retry` keeps failing, because a later
             commit failed too. Fine for feedback posted right after grading, wrong for a
             backlog. (2) The assertion message kept is the pytest message line, e.g.
             `requests.exceptions.ConnectionError` or `NotImplementedError`: informative about
             the failing check, but it names an exception, not what to do.
Later:       as-of-commit diagnosis; a hint per gap authored by the tutor (Hanafi) instead of an
             exception name; the posting loop and the marker write; rate limits; one comment
             per commit vs one per push.

### D-075 -- addenda to D-062 and D-063 (docs-only corrections found by the P4 diagnostic)
Date:        2026-10-10 (overnight batch, Stage 7)
Status:      DECIDED. Documentation only: no code behaviour changed. D-062 and D-063 are NOT
             rewritten; this entry corrects them.
Authority:   Anas (batch brief)
Addendum D-062: its Status line says "NOT yet run against real GitHub -- the first real dry-run
             ... is Anas's to run". It HAS been run, and applied: `raw_commits` holds two
             `ci: sync template (D-060)` commits (1318730c3e at 2026-10-10 03:20:22 UTC and
             f724b45592 at 03:20:23 UTC), which only `sync_template --apply` can have produced.
             `docs/explanation.md` carried the same stale sentence; fixed there.
Addendum D-063: (1) the same explanation.md paragraph said `backfill_head_sha.py` was "not yet run
             against GitHub"; D-063 itself already records the backfill as applied by Anas
             (48/48 runs then; 52/52 now, 0 NULL), so only explanation.md was stale. Fixed.
             (2) rule (b) says "raw_commits.message is stored in full". It is not: the collector
             stores `c["commit"]["message"][:500]` (collectors/collect_github.py:248). The rule is
             unaffected, because it tests only the PREFIX `ci: sync template`, which is inside the
             first 500 characters; the longest message in the real database is 73 characters. The
             claim should read "stored up to 500 characters, enough for the prefix test".
Also corrected in code comments (no behaviour change):
             memory/memory.py (the replay comment) said nothing writes `ci_run` traces and every
             such trace is hand-made in tests. No code writes them (the collector writes
             raw_workflow_runs rows), but the real database holds one (trace 28797, 2026-08-19,
             source run 31903540841), so the comment now says that. agents/echo_agent.py's
             docstring said `MASTERY_TRACE_KINDS` is `{"ci_run"}`; it is `{"ci_run", "test_result"}`
             (memory.py:150) and the docstring says so, keeping the history of when it was written.
Later:       a test that fails when a design document says "not yet run" about a script whose
             effects are visible in the database (not worth building for v1).


### D-076 -- demo Beat 3 grades inside a rolled-back transaction and persists nothing
Date:        2026-10-11
Status:      DECIDED and IMPLEMENTED (Anas, brief of 2026-10-11, Part 2a).
Authority:   Anas
Problem:     `scripts.demo` Beat 3 called `grade_attempt` on its own connection. A local run
             (no commit_sha) upserts `test_results` and sets `ran_at = now()` on rows that exist,
             so every rehearsal changed the real database it was showing (surprise recorded in
             docs/reading/2026-10-11-overnight-batch-d069-d075.md).
Decision:    `demo.grade_without_persisting(grade, ...)` opens a connection, passes it as
             `grade_attempt(conn=...)` (which never commits a joined connection) and rolls back in
             a `finally`. The tests still execute for real in a subprocess; only the writes are
             undone. A rolled-back INSERT still consumes sequence values, so trace_id numbers skip;
             the rows do not exist.
Evidence:    `baseline --full` before; `python -m scripts.demo --skip-network --skip-llm` twice;
             `baseline --full` after: `diff` empty, traces 75 / highest 71811, `test_results` 29
             rows hash a3e48e4f555912983d6af979947c7394 (that hash covers `ran_at`; max(ran_at)
             still 2026-10-11 02:08:44.39199+00).
Tests:       tests/test_demo.py: the connection is the caller's, `rollback` runs and `commit` never
             does, also when grading raises.
Not covered: Beat 4 (live collection) and Beat 6 (LLM verdict) still write by design; the first is
             skipped offline, the second by `--skip-llm`.

### D-077 -- feedback v0 shows the test name and exception type, never the assertion text
Date:        2026-10-11
Status:      DECIDED and IMPLEMENTED (Anas, brief of 2026-10-11, Part 2b). Amends D-074.
Authority:   Anas
Problem:     D-074 showed the first line of the stored assertion message. For a failing
             `assert 32.0 == f(0)` that line is the expected value, i.e. the answer.
Decision:    A failing check is shown as the test name plus the exception type (`AssertionError`,
             `ConnectionError`, `NotImplementedError`; `check failed` when no class can be read).
             pytest drops the `AssertionError: ` prefix, so a message starting `assert` is read as
             AssertionError. The message is added, in parentheses and still redacted, ONLY when the
             test function is listed in a module-level `FEEDBACK_SAFE_TESTS = ("test_x", ...)` of a
             hidden test file. The list is read with `ast.literal_eval`: the hidden file is never
             imported, and a non-literal or a syntax error marks nothing safe. NOTHING is marked
             safe today. The D-074 redaction and `assert_no_hidden_source` stay as a second layer.
Tests:       tests/test_post_feedback.py: `assert 32.0 == f(0)` (both stored shapes) leaves no
             `32.0`, `f(0)` or `assert ` in the text; marked vs unmarked; the list is read without
             executing the file; the real curriculum marks nothing.
Later:       a tutor-authored hint per gap (Hanafi) instead of an exception name (D-074 Q8).

### D-078 -- Beat 5 prints `low data` when n < 3
Date:        2026-10-11
Status:      DECIDED and IMPLEMENTED (Anas, brief of 2026-10-11, Part 2c).
Authority:   Anas
Decision:    `demo.mastery_line` puts `low data` right after p_mastery when n < 3. The threshold is
             `gap_generator._MIN_OBS_FOR_ADAPTIVE` (3), imported, so the demo and the adaptive
             variant selection cannot disagree about when an estimate is trusted. Invariant 8.
Tests:       tests/test_demo.py (n=1 and n=2 flagged; n=3 not; placement next to p).

### D-079 -- one mastery observation per (attempt, GAP), the first attempted pushed commit (formula v5)
Date:        2026-10-11
Status:      DECIDED (Anas, 2026-10-11) and IMPLEMENTED in code and tests (vdel_test). NOT applied
             to the real database: `scripts/backfill_mastery_observations.py --apply` is Anas's to
             run after a backup. Answers open question 1 of the overnight report.
Authority:   Anas
Change from the proposal: the item is the GAP, not the concept. A gap is the item of classical
             BKT; this also removes the "several gaps of one concept in one attempt" ambiguity.
             The observation is attributed to the FIRST concept in `gaps.concept_ids`; the other
             concepts are informational (kept in the payload, they receive nothing). On today's
             data the result equals the per-concept one (n=1 per concept).
Rule:        For each (attempt, hidden gap): the first pushed graded commit of the attempt in which
             the gap was ATTEMPTED -- non-null commit_sha, `test_results.status = 'ok'`
             (collection_error, timeout and tooling ignored, as D-069), and no hidden test of that
             gap failed with NotImplementedError. Success iff every hidden test of the gap passed in
             that commit. A local run (no commit_sha) never counts. `assessment.test_runner.
             gap_observation` is the one definition; grading and the backfill both call it.
Trace:       New kind `mastery_observation`, payload rule_ver (`first_attempted_commit_v1`),
             attempt_id, gap_id, commit_sha, concept, concepts, conclusion (= the "outcome"),
             item_difficulty, observed_at (the commit's time). Written once per (attempt, gap) by
             `Memory.record_mastery_observation`, which returns None and writes nothing when one
             exists: grading a commit twice, or a later commit, adds nothing. Invariant 2: only
             through memory.py.
Replay:      MASTERY_TRACE_KINDS = {ci_run, mastery_observation}; `test_result` moved to
             NON_MASTERY_KINDS (evidence for V5/V6, still logged, payload now also carries
             attempt_id, commit_sha, gap_id, test_name). Ordered by (COALESCE(observed_at, ts),
             trace_id). The stored mastery shape gains `obs_rule`; `compute_features.FORMULA_VER`
             is "v5". `rebuild_from_traces` stays deterministic: the rule is applied when the trace
             is WRITTEN, never at replay, so replay is a pure function of the append-only log
             (Beat 7 IDENTICAL, tested; `test_results` is mutable and is never joined at replay).
Legacy:      The `ci_run` trace 28797 (anas, py.testing, 2026-08-19) is kept unchanged: "legacy,
             never written again". It keeps feeding py.testing (n=1).
Backfill:    `scripts/backfill_mastery_observations.py`, dry-run by default. On the real database
             it plans 3 traces (anas: g_ext_retry -> py.errors_debugging success at 5759078602;
             g_ext_parse -> py.data_structures success at 2d087f5c17; student2: g_ext_retry ->
             py.errors_debugging FAILURE at 128da3e9c9), skipping `_test_runner`. Predicted
             profiles: anas py.data_structures 0.776 n=1, py.errors_debugging 0.776 n=1,
             py.testing 0.2154 n=1; student2 py.errors_debugging 0.2094 n=1 and
             py.data_structures gone (the gap lists py.errors_debugging first). Until `--apply`,
             replaying the real log gives only py.testing for anas, so Beat 7 against the real
             database would report DIFFERENT: apply first, then demo.
Honest note (adaptivity): `select_variant` is adaptive only from n >= 3 observations per concept.
             With one observation per gap a concept reaches n = 3 only after several attempts, so
             until then the selection is the seeded uniform fallback and the same variant is
             repeated (anas/extract attempt 2 gets variant 864fe8bbecf4 again). This is expected,
             not a bug; it is what "a 0.9 from n=2 is a rumour" (invariant 8) costs.
Later:       an earlier commit collected AFTER a later one was already graded (the "first" would be
             decided wrongly; `grade_collected --latest-only` has the same weakness); a gap whose
             concepts should be split or re-tagged (Q2); a student2-style two-concept gap where
             the second concept never gets evidence; features v5 rows for anas/student2 appear
             only on new activity (watermark collides with the v4 rows, D-069).

### D-080 -- DECIDED: option A, a local Docker sandbox for grading (not implemented in this task)
Date:        2026-10-11
Status:      DECIDED (Anas, 2026-10-11). NOT IMPLEMENTED: it is the next task. D-065's "a container
             is REQUIRED before the first real student" stays open until it is built.
Authority:   Anas
Decision:    Student code will run in a local Docker container: network none, non-root user,
             read-only filesystem plus one scratch directory, pids / memory / cpu limits,
             `--cap-drop ALL`, modelled on eecs-autograder's autograder-sandbox. Checkout and all
             database writes stay on the host; the GitHub token and the database never enter the
             container. In `grade_attempt`, `_run_pytest` becomes a `docker run` over a read-only
             copy of the repo; the JUnit file is read back by the host.
Why not B:   a GitHub Actions grader cannot reach a database on a laptop (artifact hand-back,
             polling), needs a token in a job next to student code or a three-job split, cannot
             switch the network off on a hosted runner (TODO(verify)), and cannot be tested
             offline. A is estimated at 1-2 days, B at 3-5 (estimates, not measurements).
Both leave:  result forgery from inside the test process (the student's module is imported by the
             hidden test) and the student reading the hidden test file during the run. The
             mitigation is detection (a second signal: differential execution D-036, the Code
             Agent verdict, out_of_scope_lines) or splitting execution from assertion. Later.

### D-081 -- the D-079 rollout order, and what it changes in the demo
Date:        2026-10-11
Status:      DECIDED (procedure). Written because the order matters and a wrong order looks like a
             bug.
Order:       backup -> `backfill_mastery_observations` (dry-run, read) -> `--apply --backup PATH`
             -> `prove_event_sourcing` -> `scripts.demo` -> `baseline --full`. The code change is
             live as soon as it is merged: a replay of the real log without the backfill yields
             the legacy CI trace only, while the stored profile is still the old per-test one.
             That mismatch is exactly what Beat 7 reports until the backfill is applied.
Tests:       tests/test_mastery_observation.py (17), tests/test_backfill_mastery_observations.py
             (8); tests that asserted per-test mastery were rewritten (test_stage1_d069,
             test_test_runner).

### D-082 -- rebuild_from_traces writes nothing when the rebuilt profile equals the stored one
Date:        2026-10-11
Status:      DECIDED and IMPLEMENTED (Anas, brief of 2026-10-11, step 5).
Authority:   Anas
Finding:     Running `backfill_mastery_observations --apply` a second time (0 new traces) changed
             the `learner_profile` table hash. Cause: `_write_whole_profile` ended its
             `ON CONFLICT DO UPDATE` with `updated_at = now()` unconditionally, so every rebuild
             rewrote the timestamp of both rows (both read 2026-10-11 03:23:28.878871+00, one
             transaction). Only the timestamp changed; the five content columns were identical.
Decision:    The update now carries `WHERE (mastery, weaknesses, reflections, session_digest,
             features_ref) IS DISTINCT FROM (EXCLUDED...)`: an identical rebuild updates no row,
             `updated_at` keeps meaning "when the belief last changed", and a profile that
             disagrees with the log is still repaired (and its `updated_at` moves). The wipe path
             (TRUNCATE then rebuild) is an INSERT and is unaffected, so Beat 7 is unchanged.
Tests:       tests/test_backfill_mastery_observations.py: a second apply leaves the row
             byte-identical (updated_at pinned to a sentinel, since now() is constant inside one
             transaction); a tampered profile is repaired and its updated_at moves; `prove`
             stays IDENTICAL.
Not changed: `update_mastery` still rewrites `updated_at` and appends a `profile_update` trace on
             every call, by design (D-007: it is the audit record of a recompute). run_cycle does
             not call it on a cycle with nothing new.

### D-083 -- first real run_cycle (student2), and the intended fate of anas's d818c872b5
Date:        2026-10-11
Status:      DECIDED (Anas, 2026-10-11). Evidence of a first live run; no code changed by it.
Authority:   Anas
Run:         `run_cycle --roster <scratch> --student student2`, scratch roster of the four student2
             rows (owner anass-ben-2005, repo vdel-weather-etl-gapfill-student2), not
             config/roster.yaml. Dry-run first (reads only, baseline identical). Live run:
             collect +1 commit (4832ec3c32 `load: insert_readings`, weather_etl_load, 2026-10-11
             03:17:18+00) and +1 CI run (failure, AssertionError, py.testing); grade 1 commit,
             1/2 passed, frozen=False; features written (v5 row at 03:17:25+00); profile
             features_ref current. Written: test_results +2, traces +4 (two `test_result`, one
             `mastery_observation`, one `profile_update`), attempts 84 `out_of_scope_lines`=0.
             D-079 behaved as designed: g_ld_insert attempted and passing -> ONE observation
             (sql.select_filter, success, n=1, p=0.7546 at difficulty 0.25); g_ld_select is still
             a NotImplementedError stub -> no observation; the attempt did not freeze. A second run
             immediately after wrote nothing: every table hash of `baseline --full` identical to
             the one after the first run.
anas / d818c872b5: NOT graded in this task, and no skip flag is added. The behaviour is the intended
             one: the cycle grades it ONCE; a SyntaxError makes it a `collection_error` row
             (stored, not a mastery observation, no freeze, D-066/D-069); once it has a
             `test_results` row it is never picked up again. Anas will run it himself later, after a
             backup.

### D-084 -- an unattempted stub is not a failure in V5/V6 (formula v6)
Date:        2026-10-11
Status:      DECIDED and IMPLEMENTED (Anas, 2026-10-11). `FORMULA_VER` is "v6" (bumped on Anas's
             "Bump to v6"). No `learner_features` row was written or changed by the bump; v2..v5
             stay computable.
Authority:   Anas
Problem:     D-079 stopped an unattempted gap from counting as a mastery failure, but the
             `test_result` traces that feed V5 (error response) and V6 (error frequency) still
             counted it. Found on the first live `run_cycle` (D-083): student2's NotImplementedError
             stub `g_ld_select` put `sql.select_filter: 1` in `by_concept` and, being the latest
             event with no later pass, left one error unresolved in V5.
Decision:    From formula version "v6" on, a hidden-test outcome of a gap that was an unattempted
             stub in that commit is left out of V5/V6 (total_runs, failures, fail_ratio, by_concept,
             time-to-fix, opportunities). It stays stored: in `test_results`, and as a
             `test_result` trace, as evidence that the gap was not attempted.
             Definition: the single `assessment.test_runner.gap_observation` (D-079): a gap is
             unattempted in a commit when ANY of its hidden tests failed with NotImplementedError,
             and then ALL of that gap's tests in that commit are left out (a test that passes for
             free beside a stub is not evidence either). Not re-implemented anywhere.
New traces:  `test_result` payload gains `attempted` (False for a stub gap), next to the identity
             fields D-079 added. `Memory.test_result_history` returns attempted, attempt_id,
             commit_sha, gap_id (None on older traces).
Older traces: no row is rewritten. A trace with identity but no `attempted` (the two student2
             traces of 2026-10-11) is resolved at computation time from that commit's
             `test_results` rows with the same `gap_observation`. A trace that names nothing
             (everything written before D-079, i.e. all of anas's) cannot be resolved and is KEPT:
             never dropped by guess.
Versions:    v2..v5 still count a stub, so their stored rows stay reproducible
             (`UNATTEMPTED_EXCLUDED_FROM = "v6"`, `_excludes_unattempted`). The v5 row already stored
             for student2 (03:17:25) WOULD be recomputed differently, which is why this is a new
             version. Existing `learner_features` rows are not touched. A v6 row for a student
             appears only on new activity (the watermark collides with the v5 row), as for every
             earlier bump.
anas:        His V5/V6 remain LEGACY DATA with a known bias: his traces predate the identity fields
             (attempt_id, commit_sha, gap_id), so the stub failures among them (transform, extract
             parse) cannot be recognised and are still counted as failures. New students are not
             affected: their traces carry the identity and the `attempted` flag. Recovering anas's
             by joining `test_results` on `ts = ran_at` was REJECTED as fragile: `ran_at` is
             rewritten by upserts (the demo did it for months), so the join would silently pair
             the wrong rows.
Measured, in memory on the real database (read-only), v5 -> v6:
             student2  V6 fail_ratio 0.667 -> 0.636; by_concept loses `sql.select_filter: 1`
                       (py.testing 3, py.errors_debugging 4, py.data_structures 3 unchanged);
                       V6 score 0.167 -> 0.182; V5 score 0.936 -> 0.999, resolution_ratio
                       0.875 -> 1.0 (the stub was the one unresolved error).
             anas      unchanged (fail_ratio 0.356; unclassified 8, py.data_structures 6,
                       py.testing 7): his traces predate the identity fields, so the stub
                       failures among them (transform, extract parse) cannot be recognised and
                       stay counted. Legacy data, not a rule failure.
Tests:       tests/test_unattempted_not_a_failure.py (7): stub not counted, real AssertionError
             still counted, NotImplementedError in one commit then passing, an older trace
             resolved from test_results, an unnamed trace kept, v2..v5 unchanged, the flag is
             gap-level.

### D-085 -- out_of_scope_lines stays NULL ("not measured") for a collection_error or timeout commit
Date:        2026-10-11
Status:      DECIDED and IMPLEMENTED for FUTURE grading (Anas, 2026-10-11). No existing row was
             rewritten. Amends D-073.
Authority:   Anas
Finding:     The second real cycle for anas graded `d818c872b5` as a collection_error (SyntaxError
             at weather_etl/load.py:7, two `test_results` rows, no trace, no freeze: D-066/D-069,
             as intended) and the scope check then wrote `attempts.out_of_scope_lines = 0` for
             attempt 3. The check is line-based, so it measures a file that does not load as
             "no line outside the gaps", which reads as "stayed inside" when nothing was measured.
Decision:    `grade_attempt` does not run the scope check when the evaluation status is in
             `NOT_MEASURED_STATUSES = {collection_error, timeout}`. The column is then left as it
             was: NULL if no earlier commit measured it, or an earlier commit's value (a later
             broken push does not blank a measurement). NULL means "not measured". `tooling` (a
             problem on our side, the student's file is fine) is still measured. The check stays
             fail-open (D-073): any other problem still logs a warning and leaves the column
             alone.
Tests:       tests/test_scope_wiring.py: a collection_error commit leaves NULL (not 0); a normally
             graded commit still gets its value; a later collection_error does not blank an earlier
             value; the check raising is still fail-open with a warning. The old "missing file
             logs a warning" test now describes the collection_error case; the warning path is
             covered by the raising-check test.
Existing rows (read as "not measured", NOT rewritten):
             - anas attempt 3 (weather_etl_load): 0, graded only as collection_error (d818c872).
               Read it as unknown.
             - student2 attempt 84 (weather_etl_load): 0, but its graded commit 4832ec3c has
               `status = ok` (the file loaded; g_ld_select is still a NotImplementedError stub).
               That 0 IS a measurement and is NOT in the same class as anas's. Anas asked for it to
               be read as unknown too; the data says otherwise, so only anas attempt 3 is listed
               here. Checked with: out_of_scope_lines IS NOT NULL joined to test_results.status.
V9:          Nothing computes V9 yet (the only reader of `out_of_scope_lines` in the code is the
             writer). When it is built, the rule is: a value is "unknown" when the attempt's
             graded commit is a collection_error or timeout, even if the column holds 0.


### D-086 -- v1 operating decisions (feedback channel, schedule, container, delivery)
Date:        2026-10-12 (overnight batch "V1 completion")
Status:      DECIDED by Anas before the batch; this entry only records them. Implementation is the
             batch's stages 1-7; nothing here was run against GitHub.
Authority:   Anas
Decisions:   (1) v1 feedback is the DETERMINISTIC text only (`post_feedback`); the LLM agents stay
             unwired (IR-1..IR-4 are later). (2) Channel: one GitHub ISSUE per (student, attempt),
             titled "VDEL feedback - <assignment> - attempt <n>", ONE COMMENT per graded commit,
             an @mention of the student's github_username, idempotent through `feedback_posts`.
             (3) The cycle runs on Anas's Windows PC, hourly, through Windows Task Scheduler.
             (4) One trusted student may be graded without the container; the container is
             MANDATORY before a pilot of 3 to 5 students. (5) Attempt N+1 is delivered as a NEW
             private repo with the student invited as collaborator.
Rails:       every code path that writes to GitHub is behind `--apply` AND the environment variable
             `VDEL_ALLOW_GITHUB_WRITE=1`, and refuses a placeholder `github_username`. No LLM call.
             Schema changes are additive new sql files; the real database gets the exact migration
             command in the report and is not touched by the batch.

### D-087 -- addenda to D-006, D-068 and D-074 (documentation only; nothing above is rewritten)
Date:        2026-10-12 (overnight batch, stage 1)
Status:      DECIDED. Documentation only: no code behaviour changed.
Authority:   Anas (batch brief)
Addendum D-006: SUPERSEDED in practice. Its blockers are gone: `config/roster.yaml` exists, a token is
             configured, and collection runs live and idempotently (D-043 per-file attribution, D-063
             head_sha, D-067 log retry, D-071 `run_cycle`, D-083 the first real cycles for student2 and
             anas). The M1 DoD clauses it blocked are tracked in `docs/STATUS.md`, not here. Its header
             still says OPEN because the file is append-only; read it as closed by D-071 / D-083.
Addendum D-068: RESOLVED by D-069 (option a: one V1, `Memory.replay_mastery`) and later changed by D-079
             (formula v5: one `mastery_observation` per (attempt, gap)). D-069 already carries the
             resolution line; this addendum gives the header the pointer it lacked.
Addendum D-074: it says `feedback_posts` (sql/07) was "written but not applied to the real database".
             That is no longer true: the table EXISTS on the real database (0 rows). The overnight text
             in `HANDOFF.md`, `docs/explanation.md` and the comments of `sql/07_feedback_tables.sql` and
             `scripts/post_feedback.py` that said otherwise were corrected. Nothing writes the table
             until the issue mode (D-089) is run with `--apply`.
STATUS.md:   `docs/STATUS.md` has +248 uncommitted lines of DoD evidence (2026-08-31 M2 rehearsal, 2026-09-02
             classifier-rate query, M3/M4 entries). Not touched by the batch. Recommendation: commit it
             alone (`docs: record DoD evidence`); it is evidence, contains no secret, and `HANDOFF.md`
             has asked for that since 2026-10-11.

### D-088 -- V2 cleanliness is measured: gap-scoped ruff / sqlfluff counts at grading time (formula v7)
Date:        2026-10-12 (overnight batch, stage 2)
Status:      DECIDED and IMPLEMENTED (brief). Columns NOT applied to the real database (see "To apply").
Authority:   Anas (batch brief)
Problem:     `_discipline` passed `lint_violations=0, changed_loc=0` (cleanliness "not measured")
             because M1 never had the student's code. Grading now has the checkout.
Decision:    After each graded commit (`scripts/grade_collected.py`, hence `run_cycle`),
             `assessment/lint_scope.record` lints the submitted file STATICALLY (ruff for .py,
             sqlfluff for .sql, `agents.tools`, nothing is imported or run) and stores on `attempts`
             `lint_violations` (findings on lines the student wrote INSIDE a gap), `lint_changed_loc`
             (lines changed inside the gaps, `scope_check.changed_loc_in_gap`) and `lint_tool`.
             Gap-scoped (invariant 14, C4): the gaps are known in the released file's coordinates and
             `scope_check.in_gap_submitted_ranges` maps them to the submitted file with the same line
             diff and the same block classification V9 uses; master code is never attributed.
             Same storage rule as `out_of_scope_lines`: the latest graded commit's value until the
             freeze, the frozen commit's afterwards. NULL = not measured.
Fail-open:   a collection_error / timeout commit (D-085), a linter that is missing or times out, a file
             type without a linter, a changed master version (invariant 15), a missing file, or columns
             not migrated yet all leave NULL and log a warning inside a SAVEPOINT; grading and the
             cycle are never blocked.
Rule set:    the file is linted from a private temporary COPY with no project files next to it, so a
             `pyproject.toml` / `ruff.toml` / `.sqlfluff` in the student's repo cannot switch rules off.
             The rules are the tools' DEFAULTS (ruff E4/E7/E9/F), the same for every student: a
             choice, not a measurement. sqlfluff uses the `ansi` dialect (`agents.tools`).
Where it lives: `assessment/lint_scope.py` imports `agents.tools`; `assessment/test_runner.py` still
             imports nothing from `agents/` (invariant 13's grep stays true), which is why the call
             is in `grade_collected`, not in `grade_attempt`. Consequence: a grade made through
             `grade_attempt` alone (the demo's Beat 3, tests) stores no lint counts.
Formula:     `compute_features` V2 sums `lint_violations` / `lint_changed_loc` over the student's
             measured attempts from formula "v7" on (and adds `lint: {violations, changed_loc,
             attempts_measured}` to the V2 JSON for audit). v2..v6 keep the fixed zeros, so every
             stored row stays reproducible; no `learner_features` row was touched. `FORMULA_VER` is
             "v7". A v7 row for a student appears on their next new activity (the watermark collides
             with the earlier row), as for every earlier bump. `_lint_totals` is fail-open too, so
             features keep working on a database that has not been migrated.
Existing data: no attempt has a lint value (the columns do not exist on the real DB). They fill as new
             commits are graded; nothing is backfilled.
Tests:       tests/test_lint_scope.py (17): coordinates, in-gap vs master violation, a clean solution
             is 0 not None, linter unavailable, private copy, sqlfluff dispatch and a real sqlfluff run,
             storage and the freeze rule, collection_error not measured, missing file and unmigrated
             columns fail open, the `grade_collected` wiring, V2 under v7 vs v6.
To apply by hand (real database, NOT run by the batch):
             `python -m scripts.init_db`   (idempotent: re-applies every file; 08 adds the 3 columns)
Later:       a per-commit store; V6's `changed_loc` still counts all additions + deletions of a commit
             (not gap-scoped); lint rules beyond the defaults; V2's composite needs a cohort >= 10.

### D-089 -- feedback by GitHub issue: one issue per (student, attempt), one comment per graded commit
Date:        2026-10-12 (overnight batch, stage 3)
Status:      DECIDED and IMPLEMENTED as DRY-RUN BY DEFAULT. Nothing was ever posted; no GitHub call was
             made by the batch. Implements D-086 decision (2).
Authority:   Anas (batch brief)
Decision:    `python -m scripts.post_feedback --student X --issue [--assignment A] [--commit SHA]
             [--roster PATH]` lists the graded commits that have no issue comment yet and, per commit,
             prints the exact API calls and the exact text. The text is the deterministic v0 message
             (D-074, D-077: test name and exception type only, never an assertion message or hidden
             test code) preceded by `@<github_username>` and followed by a hidden marker
             `<!-- vdel:feedback attempt=<id> commit=<sha> -->`. The issue is titled
             "VDEL feedback - <assignment> - attempt <n>" and lives in the repo the roster maps
             (student, assignment) to.
Real write:  needs `--apply` AND `VDEL_ALLOW_GITHUB_WRITE=1` in the environment (`require_github_write`:
             raises before anything is contacted; the CLI exits 2 before even opening the database).
             It then refuses a placeholder `github_username` (text check: empty, `_`-prefixed,
             contains placeholder / change_me / render-only / example, or not a valid GitHub login;
             student2's `student2-placeholder-local-render-only` is one) and a missing roster entry.
             A GitHub error (403 forbidden or rate limit, 404, 410 issues disabled, 422) becomes a
             `failed` outcome with a plain reason, writes no row and is retried next run; it never
             crashes the batch. The token is read from GITHUB_TOKEN, sent only in the Authorization
             header and never printed or put in an outcome.
Idempotence: `feedback_issues` (sql/09, new: one row per attempt with owner, repo, issue number) and
             `feedback_posts` (existing sql/07, channel `github_issue_comment`, `external_ref` = the
             comment URL). Order: the database row is read first; if the issue is unknown, GitHub is
             searched for an issue with the exact title (pull requests skipped) before one is created;
             before each comment the issue's comments are read for the marker, so a comment that
             reached GitHub but not the database (a crash between the two) is recorded as
             `recovered` instead of being posted twice. Rows are `ON CONFLICT DO NOTHING`
             (invariant 9); the command commits after each posted/recovered comment.
Client:      `publish_repo.GitHub` gained `find_issue`, `create_issue`, `issue_comments`,
             `create_issue_comment`, `invite_collaborator` and `GitHubHTTPError(status, reason)`.
Tests:       tests/test_post_feedback_issue.py (25, mocked HTTP only; any real `requests` call fails the
             test): issue created once and reused, a second run posts nothing, an existing issue with
             the title is reused, marker recovery, placeholder and missing roster refused with no
             client built, the write gate, missing feedback tables refused before any call, 403 / 404 / 410 / 422 handled with no row written, the real
             client's exact requests and status mapping, the token never in an outcome or the output,
             no assertion text and no hidden line in the body, the CLI dry-run and its refusal.
Dry-run on the real database (student2, read-only): 4 graded commits, all marked WOULD REFUSE
             (placeholder username); texts shown in the report.
Known limits (later): the diagnosis is attempt-wide, so the FIRST comment of an attempt can say
             "Keeps failing across several pushes" (D-074 finding, as-of-commit diagnosis is later); a
             never-attempted stub is described as `NotImplementedError` rather than "not started";
             the issue lives in the repo the roster maps NOW, so after attempt N+1 re-points the
             roster, a late comment for attempt N would go to the new repo; a student who deletes the
             issue gets a new one only if the database row is also gone; no edit/close of issues.
To apply by hand (real database, NOT run by the batch): `python -m scripts.init_db` (adds
             `feedback_issues`, and the lint columns of D-088).

### D-090 -- delivery of attempt N+1: `deliver_next_attempt`, a new private repo per attempt, `attempts.started_at`
Date:        2026-10-12 (overnight batch, stage 4)
Status:      DECIDED and IMPLEMENTED as DRY-RUN BY DEFAULT. No repo was created, no invitation sent,
             no comment posted. Implements D-086 decision (5).
Authority:   Anas (batch brief)
Command:     `python -m scripts.deliver_next_attempt --student X --assignment Y [--roster PATH]
             [--force --i-understand] [--resume] [--apply]`.
             Checks the current attempt is FROZEN. `--force` is refused unless `--i-understand` is
             also given (D-072's `attempts.closed_at` closure is missing: a forced old attempt stays
             open and `grade_collected` lets an open attempt win over a frozen higher one). Runs
             `next_attempt`, publishes a NEW private repo through `publish_repo`, invites the student
             as collaborator, comments the link on the feedback issue of the attempt just completed
             (D-089), and PRINTS the roster rows to add. It never edits `config/roster.yaml`.
Name:        `vdel-<project>-gapfill-<student>-<stage>-attempt<n>` (e.g.
             `vdel-weather-etl-gapfill-student2-extract-attempt2`). The brief says "...-attempt<n>";
             the stage is added so attempt 2 of two different stages never collide on one name
             (alternative: no stage, rejected for that reason).
Scope:       the new repo holds ONE stage (its file, ASSIGNMENT.md, the shared scaffolding and the
             visible tests), because `publish_repo.run` gained `only_assignment` (default None =
             unchanged whole-project behaviour) and passes it to `render_student_repo`.
Real run:    needs `--apply` AND `VDEL_ALLOW_GITHUB_WRITE=1`, refuses a placeholder username, and is
             idempotent step by step: an existing repo with commits is not re-published, the
             invitation is a PUT (already a collaborator is fine), the issue comment carries the
             marker `<!-- vdel:delivery attempt=<id> -->` that is looked for first. A failed run is
             finished with `--resume` (allowed only for an attempt number >= 2 that is open and has
             no graded commit).
Found while doing it (a real flaw, fixed additively): attempt N's commits stay in `raw_commits`
             under the same (student, assignment). Once the roster points at the new repo,
             `grade_collected.find_pending` would offer them as pending for attempt N+1 and fail to
             fetch them from the new repo on EVERY cycle (the student would show as FAILED forever).
             Fix: `attempts.started_at` (sql/10, nullable, NULL for every existing attempt = no
             change for them), set by `render_student_repo._upsert_attempt` only when it INSERTS an
             attempt (never on a re-render), and `find_pending` ignores commits older than it.
             Both are fail-open when the column does not exist yet.
Tests:       tests/test_deliver_next_attempt.py (14): the stage in the name, a non-frozen attempt
             refused, `--force` needs `--i-understand`, placeholder refused on apply and shown in the
             dry-run, the write gate, the dry-run records and contacts nothing and prints the plan, the
             real run (fake GitHub over a local bare repo) delivers one stage with no hidden test,
             invites, comments, never edits the roster; failure then `--resume` then a second resume
             is a no-op; resume refused for an attempt with graded work; `started_at` stamped once and
             not moved by a re-render; old commits not pending; no start = old behaviour; unmigrated
             column fails open.
Owner: when the student IS the account that owns the repos (the trusted student may be), no invitation is
             sent: GitHub refuses to invite an owner (422). The step is reported as "not needed" and the comment
             wording does not promise an invitation.
Dry-run on the real database, student2 / weather_etl_extract (frozen at ecee294618): attempt 2 would
             get variant c4c18c3e10e9, hidden gap g_ext_retry, i.e. the SAME variant as attempt 1
             (expected, D-079: adaptivity needs n >= 3). Whole output in the report.
Known limits (later): after delivery the old repo is no longer collected (the roster row is replaced),
             so a late push there is ignored; no automatic roster edit; no email or notification
             besides the GitHub invitation and the issue comment; the invitation must be accepted by
             the student; a student who already has push access to the old repo is not removed.
To apply by hand (real database, NOT run by the batch): `python -m scripts.init_db` (adds the
             `started_at` column; also the lint columns and `feedback_issues`).

### D-091 -- the hourly task: `scripts/run_hourly.py`, Windows Task Scheduler scripts, `docs/OPERATIONS.md`
Date:        2026-10-12 (overnight batch, stage 5)
Status:      DECIDED and IMPLEMENTED. The two PowerShell scripts were parsed for syntax and NOT run;
             no task is registered. Implements D-086 decision (3).
Authority:   Anas (batch brief)
Command:     `python -m scripts.run_hourly [--roster P] [--dry-run] [--skip-network]
             [--lookback-hours N]`: `run_cycle` for every roster student, then the issue feedback of
             D-089 for the commits graded in the last N hours (default 48) that have no comment.
GitHub writes: only with `VDEL_ALLOW_GITHUB_WRITE=1` in the task's environment AND not `--dry-run`.
             Otherwise the log lists `WOULD POST` lines (and why a post would be refused). The flag is
             set per task by `register_task.ps1 -AllowGitHubWrite` (inside the task's own command, not
             machine-wide).
Locks:       a new advisory lock (key 640201072) held for the whole run, next to `run_cycle`'s
             (640201071): a second hourly run exits 3 at once; a manual `run_cycle` during a run is
             refused by the inner lock. Both are session locks, released when the process ends.
Exit codes:  0 ok; 1 a student or a post failed, or the roster is missing (a message, not a traceback);
             2 database unreachable (`DATABASE UNREACHABLE: ...` plus a hint to start Docker; nothing
             else is attempted); 3 locked.
Logs:        `logs/run_hourly-YYYY-MM-DD.log` (gitignored, added to `.gitignore`), appended, each line
             timestamped UTC; files older than 14 days deleted at the start of each run, judged by the
             date in the NAME (a copy or restore changes mtimes); other files untouched.
Decisions taken without Anas (alternatives):
             - 48-hour lookback instead of "every unposted graded commit": the backlog (anas's August
               commits, student2's) would otherwise be posted the first time the flag is on. A failed
               post is retried for two days. Alternative: post everything unposted; rejected as noisy.
               The backlog is posted by hand with `post_feedback --issue`.
             - the task runs as the logged-on user (`LogonType Interactive`), 60 minutes, 50 minute
               limit, `MultipleInstances IgnoreNew`, `StartWhenAvailable`, `RunOnlyIfNetworkAvailable`.
               Alternative: "run whether logged on or not" (needs the password stored); rejected, and
               Docker Desktop needs the session anyway.
             - `python` is the first one on PATH unless `-PythonExe` is given.
Tests:       tests/test_run_hourly.py (14): database down -> 2 and a plain line; the lock held by
             another session -> 3 and nothing collected, released afterwards; no GitHub call without
             the flag, none in a dry-run even with the flag; with the flag one issue and one comment,
             a second run posts nothing; a commit graded 10 days ago is not posted; a GitHub 403 is a
             failed run, not a crash; a placeholder username is refused; the dated log with
             timestamps and no token; rotation (15 days removed, 14 kept, others untouched); a missing
             roster; the lookback window; the PowerShell scripts keep writes off by default.
To apply by hand: `docs/OPERATIONS.md` sections 2-5 (backup, `init_db`, register the task).
Later:       a "run whether logged on or not" variant; an e-mail or toast on exit 2/1; per-student
             isolation of the posting phase beyond the per-post outcome; a status page.

### D-092 -- grading in a local Docker container, off by default (`VDEL_GRADING_SANDBOX=docker`)
Date:        2026-10-12 (overnight batch, stage 6)
Status:      DECIDED and IMPLEMENTED; OFF unless the variable is set, so nothing changes by default.
             Implements D-080 (option A) and D-086 decision (4). The real image was NOT built by the
             batch (a build needs the network); `docker/grader.Dockerfile` is ready to build by hand.
Authority:   Anas (D-080, batch brief)
Network use: exactly one pull, logged: `docker pull python:3.11-slim` at 2026-10-11T19:05:28Z gave
             `sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce`
             (Python 3.11.17, linux/amd64). The Dockerfile pins that digest. No `pip install`, no other
             pull. Everything below was verified with an OFFLINE verification image
             (`vdel-grader:offline-check`: the same base image plus pytest 9.1.1 and requests 2.32.3 copied from
             this PC's site-packages), because the real image needs `pip install`.
Image:       `docker/grader.Dockerfile` + `docker/grader-requirements.txt`: pinned slim Python, only the
             packages the hidden tests and the curriculum import (pytest, requests, pandas and their
             pins), no secret, user 10001 with no home or shell. Build context is `docker/` only.
Runner:      `assessment/test_runner.py`: `sandbox_mode()`, `docker_run_argv()` (pure, tested flag by
             flag), `_run_pytest_docker()`, `_run_tests()` selecting the mode, `SandboxKilled`.
             Flags: `--rm --pull never --network none --read-only`, tmpfs `/scratch` (64 MB, noexec) and
             `/tmp`, `--pids-limit 128`, `--memory 512m --memory-swap 512m`, `--cpus 1`, `--cap-drop ALL`,
             `--security-opt no-new-privileges`, `--user 10001:10001`; the sanitised copy mounted READ-ONLY
             at /work, the trusted ini and the JUnit report on a SEPARATE mount /results; no host
             environment variable is passed. The numbers are choices, not measurements.
Never falls back: docker missing, the image missing (exit 125) or an unknown variable value raises
             `TestRunnerError` with the build command. A wall-clock timeout kills the container and is
             recorded as before; an OOM / external kill (exit 137, no report) is recorded as `timeout`
             too; the container is always removed.
Bug found by comparing the modes, fixed: a traceback written inside the container names `/work/...`;
             the collection-error classifier resolved frames against the HOST copy, matched none, and
             classified a student's SyntaxError as `tooling` ("our fault", never charged) instead of
             `collection_error`. `_localise_container_paths` rewrites `/work/` to the host copy before
             classification (container mode only).
Parity:      on four ordinary repos (solved, unsolved, wrong, syntax error) both modes give the same
             status, detail and rows, and `test_results` recorded through `grade_attempt` on the test
             database is identical row by row. One difference is NOT mode-related: pytest prints the
             'Differing items' of a dict comparison in a hash-seed-dependent order, so two SUBPROCESS runs
             already disagree on the message text (3 distinct messages in 4 runs). The tests compare the
             first line and the set of lines. Later: `PYTHONHASHSEED=0` in both environments.
What each mode lets student code do (run on this PC; the process bomb only in the container):
| mode | what the student code tried | what happened |
|---|---|---|
| subprocess | probe: user / GITHUB_TOKEN in env | uid=n/a token=absent |
| subprocess | probe: read a file outside the checkout | READ:CANARY-9f3a1c |
| subprocess | probe: connect to a listener on the PC's loopback | connected (listener received 1 connection(s)) |
| subprocess | probe: write outside the checkout (a path on the PC) | wrote (file exists afterwards: True) |
| subprocess | probe: write inside the checkout (/work) | FileNotFoundError |
| subprocess | probe: write /etc | FileNotFoundError |
| subprocess | probe: write the scratch dir | FileNotFoundError |
| subprocess | infinite loop at import (limit 8 s) | status=timeout after 8s |
| subprocess | process bomb (bounded: tries 300 sleeping children) | NOT RUN on the PC (no process limit exists in this mode; unsafe to try) |
| docker | probe: user / GITHUB_TOKEN in env | uid=10001 token=absent |
| docker | probe: read a file outside the checkout | FileNotFoundError |
| docker | probe: connect to a listener on the PC's loopback | ConnectionRefusedError (listener received 0 connection(s)) |
| docker | probe: write outside the checkout (a path on the PC) | OSError (file exists afterwards: False) |
| docker | probe: write inside the checkout (/work) | OSError |
| docker | probe: write /etc | OSError |
| docker | probe: write the scratch dir | wrote |
| docker | infinite loop at import (limit 8 s) | status=timeout after 8s |
| docker | process bomb (bounded: tries 300 sleeping children) | spawned=127 stopped_by=BlockingIOError (pids-limit 128) |

Tests:       tests/test_grading_container.py (19; the 9 container tests skip unless docker and the image
             exist, run with `VDEL_GRADING_IMAGE=vdel-grader:offline-check` here: 19 passed, no container
             left behind), fixtures in tests/sandbox_fixtures.py.
Does not protect: forgery from inside the test process (the student's module is imported by the hidden
             test inside the container and can patch pytest or overwrite the JUnit file it can reach);
             reading the hidden test file; a kernel escape; disk beyond the 64 MB scratch. Mitigation is a
             second signal (differential execution D-036, not built) or splitting execution from assertion.
             Later.
To apply by hand: `docs/OPERATIONS.md` section 11 (`docker build`, a Beat 3 try, the tests, then
             `register_task.ps1 -UseDockerGrading -Force`).

### D-093 -- robustness: repository hooks never run at checkout; what a force-push or a deleted repo does today
Date:        2026-10-12 (overnight batch, stage 7)
Status:      DECIDED (tests only; no behaviour changed). Part (b) is a description from READING the code:
             nothing in it was run against GitHub.
Authority:   Anas (batch brief)
(a) Hooks:   tests/test_checkout_safety.py builds a hostile repository for real (hooks in its `.git/hooks`,
             `core.hooksPath=.githooks` with a committed `post-checkout`, a `.gitattributes` filter whose
             smudge command writes a canary, a `.gitmodules` entry) and runs `grade_collected.
             checkout_commit` against it as a local remote. The canary is never written, the clone has only
             `*.sample` hooks, no `hooksPath`, no filter, and the submodule is not initialised. The same
             hook DOES fire on a checkout in the source repository (a second test), so the first result is
             not a dud trap. Why it holds: hooks and `core.hooksPath` live in `.git`, which `git init` + `git
             fetch <url> <sha>` + `git checkout --detach` into an empty directory does not transfer; filters
             need config that a fetch does not bring either. Student code runs only later, under pytest, in
             the grading subprocess or container.
(b) A student FORCE-PUSHES over a graded commit (what happens today):
             - Nothing already recorded changes: `raw_commits`, `test_results`, traces and the freeze are
               keyed by commit sha and are INSERT/upsert-only, so the old sha, its results and the
               `mastery_observation` stay. The first-attempt observation of a (attempt, gap) is immutable
               (D-079), so a rewrite cannot give the student a second "first attempt".
             - The rewritten commits have NEW shas. They are collected and graded as new commits: their
               hidden tests produce new `test_results` rows and new `test_result` traces, so V5/V6 count
               the same work twice (the observation for mastery does not).
             - The collector asks GitHub only for commits since the largest stored `committed_at` (the
               COMMITTER date, which the student controls). A rewritten or back-dated commit whose date is
               not newer than that is never returned and never graded; and ONE commit dated in the future
               moves `since` past every honest later commit, which then stop being collected
               (tests/test_collector_known_limits.py pins this, it does not fix it).
             - After a freeze, commits newer than the frozen commit are skipped (D-069); older rewritten
               ones are graded.
             - Whether GitHub still serves the orphaned old sha by `git fetch` is NOT verified here; the
               rows for it are already complete, so grading does not need it again.
(b) A student DELETES the repository (or makes it unreachable):
             - `collect_all` isolates the repo: the 404 becomes a `failed` entry, the student is reported
               FAILED by `run_cycle` (exit 1) every hour with the same message, until the roster row is
               fixed or removed. Nothing is written and no other student is affected.
             - Commits already collected but not yet graded are retried and fail at the checkout every
               cycle (`FAILED attempt=...`), forever; graded work is untouched.
             - The feedback phase gets a 404 per comment (an outcome `failed`, retried only inside the
               48-hour lookback) and the issue row stays.
             - Nothing is lost: the database keeps every graded result and the profile; re-publishing a repo
               is refused over an existing history (D-062) but a new empty repo can be registered.
Later (not done, v1 scope):
             1. collector: do not trust the committer date. Re-list without `since` (the sha-level skip
                already prevents the expensive calls), or keep `since` but subtract a safety window, and
                clamp any `committed_at` in the future to the collection time; flag a push that rewrote
                history (the push events carry `forced`).
             2. grader: after N failed fetches of the same sha, mark the commit unfetchable (a counter, an
                additive column) instead of retrying it every cycle.
             3. roster: an `archived`/`status` field so a deleted or finished repo stops producing a daily
                FAILED line.
             4. V5/V6: treat a rewritten commit whose file content equals an already graded one as the same
                evidence (store the blob sha of the graded file next to the commit sha).
             5. audit: store `before`/`after` of a force-push and the tree sha of the frozen commit so a
                rewrite is visible after the fact.


### D-094 -- feedback "as of the commit"; grading hash seed pinned; demo Beat 3 names the real mode
Date:        2026-10-12
Status:      DECIDED (three small fixes; baseline identical, real database read-only, no GitHub write, no live LLM call)
Authority:   Anas (brief)
(1) As of:   `assessment.diagnose.diagnose(cur, attempt_id, as_of_commit_sha=None)`. With a sha, only
             `test_results` rows whose commit has `raw_commits.committed_at` <= that commit's count, for the
             recurrence flags, the weakest concept and the failing tests; rows with no commit (a local run) fall
             outside every cutoff; an unknown sha raises (never a silent whole-history fallback). Default None keeps
             the old whole-history behaviour for the other callers (`feedback_agent`, `agents_export_fixtures`).
             `post_feedback.build_feedback` passes the commit it is writing for. Effect: the first comment of an
             attempt can no longer say "Keeps failing across several pushes", and a later push cannot change what
             an earlier comment says. Ties on `committed_at` count as history (<=, per the brief). Already posted
             comments are not rewritten (the marker makes posting idempotent): this fixes the texts built from now on.
(2) Seed:    `PYTHONHASHSEED=0` is in `grading_env` (subprocess) and in `docker_run_argv` (container). Without it
             pytest's "Differing items" order, hence the stored `test_results.message`, changed per process
             (the `canon()` workaround in tests/test_grading_container.py was written for exactly this and is now
             stricter than needed; left in place). Not a security change: it adds one fixed variable to an allowlist.
(3) Demo:    Beat 3 prints "docker container" or "real subprocess" from `test_runner.sandbox_mode()`, the same switch
             the grader reads.
Tests:       tests/test_post_feedback.py (first / second / later commit, a later push leaves an earlier text unchanged,
             unknown sha raises), tests/test_grading_sandbox.py (seed pinned against a hostile parent value; a hidden
             probe whose message depends on set order is identical over 5 runs), tests/test_grading_container.py (seed
             in the docker argv; raw stored messages identical twice in the container and equal to the host),
             tests/test_demo.py (label follows the env var). Mutation checks: removing the pin fails both seed tests;
             reverting `build_feedback` to whole history fails both as-of tests.

### D-095 -- the hourly task survives any character in a path (an apostrophe in `stage_a_l'etranger`); a startup failure is never silent
Date:        2026-10-12
Status:      DECIDED (scripts and tests only; the task is NOT registered, the real database, GitHub and roster untouched)
Authority:   Anas (bug report: "VDEL hourly" ran at 02:43, LastTaskResult 1, nothing in logs/)
Cause:       register_task.ps1 built `powershell.exe -Command "Set-Location -LiteralPath '<folder>'; & '<python>' ..."`.
             An apostrophe in the folder ended the single-quoted string: TerminatorExpectedAtEndOfString, the command
             never ran, so run_hourly never wrote a line. Reproduced with the exact string (a harmless Write-Output
             with the same quoting gives the same parse error).
Fix:         new scripts/windows/task_command.ps1 (dot-sourced by register_task.ps1 and by the test), three layers:
             (1) the command is passed with -EncodedCommand (base64 of UTF-16LE): the command line holds only
             [A-Za-z0-9+/=]; (2) inside it every path is a single-quoted literal with ' doubled to '' and is used with
             -LiteralPath; (3) the task's "Start in" stays the project folder but is NOT relied on.
             Chosen over "WorkingDirectory only, drop Set-Location": TESTED, Windows PowerShell 5.1 started in a folder
             whose name holds [ or ] silently falls back to its own install folder (brackets read as a wildcard), so
             Start-in alone breaks on `[`. EncodedCommand alone removes the parse problem; the explicit Set-Location
             -LiteralPath removes the dependence on Start-in. A property is not parsed, but it is not enough either.
Visibility:  the wrapper writes logs\task_stderr.log (UTF-8, absolute path, .NET AppendAllText): a `task start` line per
             run, Python's stderr via a 2>&1 pipeline, `TASK WRAPPER ERROR` for python-not-found and any wrapper
             exception, and %TEMP%\vdel_task_stderr.log when the folder itself cannot be entered. Two traps found by
             the tests while building it: PowerShell 5.1's `2>>` writes UTF-16 while Add-Content writes ANSI (one file,
             two encodings, unreadable), and New-Item has no -LiteralPath. run_hourly's first log line is now
             `run_hourly START pid= cwd= python=`, written before rotation, the lock or the database.
Effect:      a task registered by the OLD script keeps its broken command: unregister and register again.
Tests:       tests/test_task_command.py runs the generated argument string with powershell.exe in a folder and with a
             python stub both named `o'brien & co [x]`: runs end to end, python starts in the folder, python's exit code
             is the task's, started from the wrong directory it still reaches the folder, python missing is logged,
             write/docker flags are set only when asked, the log holds no NUL bytes, and the old quoting is shown to
             fail. tests/test_run_hourly.py: first log line. Skipped when powershell.exe is absent.
Known limit: `%` in a path is not covered (cmd.exe expands it when the .cmd stub is launched; python.exe is not a .cmd).

### D-096 -- OPEN: does a single-assignment repo (attempt 2) ship visible tests it cannot import? Plus two findings on CI classification and V5/V6
Date:        2026-10-12
Status:      OPEN. Nothing was changed. The empirical check (item 1) was BLOCKED by a permission rule and, as agreed, was not
             redone another way; items 2 and 3 depend on it. Items marked READ below come from reading code / read-only
             queries, not from a run.
(1) Question: `render_student_repo(..., only_assignment=X)` renders only X's file, `<project>/__init__.py`, `requirements.txt`,
             and then `shutil.copytree` of the WHOLE `tests/visible` (render_student_repo.py, the "tests/visible copied"
             block). READ: tests/visible holds test_extract / test_load / test_quality / test_transform, which import
             `weather_etl.extract / .load / .quality / .transform`. For weather_etl_extract only `extract.py` exists, so by
             reading, three of the four files cannot be imported. NOT RUN: whether `python -m pytest tests/visible` then stops
             with 3 collection errors (pytest's default: "Interrupted: 3 errors during collection", no test runs at all, so
             test_extract.py would not run either) is expected but UNVERIFIED. The ci.yml the render ships is
             `pip install -r requirements.txt; pip install ruff pytest; ruff check . (continue-on-error); python -m pytest tests/visible`.
             Check to run by hand: render attempt 2 for anas/weather_etl_extract inside a rolled-back transaction, create a
             fresh venv, run those two pip lines and the pytest line there.
(2) READ, how a CI collection error is classified today (collectors/error_classifier.py): a first-match rule table with no rule for
             ModuleNotFoundError / ImportError / "ERROR collecting". A collection-error log therefore falls to
             ('unmatched', 'unclassified') unless some other line of the whole log text happens to match a rule (the text is the
             entire run log, not only the pytest step). Real data agrees for the other unmatched failures: 12 of 21 CI failures in
             raw_workflow_runs are 'unmatched'/'unclassified'.
(3) READ + real data, V5/V6 and 'unclassified' (features/compute_features.py, `_error_features`): the CI rows are selected by
             student_id and the outcome scope only, with NO assignment_id filter, so a run with assignment_id NULL (a repo that
             covers several assignments) counts the same as one with an assignment. A failed 'unclassified' run therefore
             enters `runs`/`failures` (total_runs, time-to-fix, V6 failed_runs and errors) AND, because the test is
             `if concept_id` (the string 'unclassified' is truthy), also `concept_events` and `by_concept`. The stored v2 row
             for anas has by_concept {'py.testing': 7, 'unclassified': 12, 'py.data_structures': 6}; the current code path is the
             same. Consequence: V5's "worst concept" can be 'unclassified' (the 12 beat the 7), which is not a concept and breaks
             the intent of invariant 10 for V5/V6 (V1 no longer reads CI rows since D-069, so mastery itself is not affected). A
             CI collection error of an attempt-2 repo would add one such 'unclassified' failure per push.
             The GRADER's own collection errors are different and already handled (D-066/D-069): status `collection_error`, no
             mastery trace, no V5/V6 `test_result` trace, and a module missing in OUR test file is `tooling`, never a failure.
Not decided: the fix for (1) (ship only the visible tests whose module is in the render; attempt-1 repos unchanged), the
             'unclassified' filter in `concept_events`, and a classifier rule for collection errors. Each needs your word.

### D-097 -- a single-assignment repo ships only the visible tests it can import (resolves D-096 item 1 and its renderer part)
Date:        2026-10-12
Status:      DECIDED and implemented. D-096's items on the CI classifier and on 'unclassified' in V5/V6 stay OPEN.
Authority:   Anas (brief) + Anas's own confirmation of the failure.
Confirmed:   by Anas, in a copy of an attempt-1 repo with load.py, quality.py and transform.py removed:
             `python -m pytest tests/visible -q` ends with "3 errors during collection" (ModuleNotFoundError: No module named
             'weather_etl.load' / '.quality' / '.transform'), "Interrupted", and test_extract.py does not run at all. (The
             render-then-venv run I tried was blocked by a permission rule and not redone; this is the equivalent run.)
Fix:         `render_student_repo(..., only_assignment=X)` now copies from tests/visible only the `test_*.py` files whose imported
             project modules are all in the render (`_project_modules_imported` reads the file with `ast`: `from weather_etl.x
             import`, `import weather_etl.x`, `from weather_etl import x` when x.py exists in the master; relative imports ignored).
             Any other file in tests/visible (a helper, a conftest) ships as before; an unparsable test file ships (not this
             filter's job to hide a broken file). The whole-project render keeps the original `shutil.copytree`, so attempt-1
             repos are byte-for-byte as before. The return dict gains `visible_tests` (what shipped).
Why imports:  the rule is the actual failure condition (an import that cannot resolve), not a name convention; a new stage or
             test file needs no table to be kept in step. A stage whose test imports two modules ships only when both are rendered.
Unchanged:   variant ids (select_variant is untouched; the demo's Beat 2 still prints 864fe8bbecf4 / c4c18c3e10e9), the
             hidden-test guard (`_assert_no_hidden_tests_leaked` still runs on every render), ci.yml.
Tests:       tests/test_render_visible_tests.py: each of the four single-assignment renders ships exactly its own test, byte-equal
             to the master's; the workflow's pytest command collects and runs test_extract.py in the extract render (exit 0/1,
             never 2); the failure as confirmed is reproduced when the full folder is put back (exit 2, "3 errors during
             collection"); a four-assignment render ships all four, unchanged; variant ids are the same whole-project and
             single-assignment; no path named hidden. With the filter disabled 5 of the 9 fail.
Effect on already-delivered repos: none changed. A repo delivered before this fix (attempt 2 of any stage) still holds all four
             visible tests; the next delivery is correct. Nothing was delivered for a real student yet (HANDOFF).
What CI looks like for an unfilled single-assignment repo (reasoned, not run on GitHub): ruff step (continue-on-error), then pytest
             collects the one visible file and its tests fail with NotImplementedError, exit 1: a red run for the right reason,
             and no collection error. The collection-error CI case remains classified 'unclassified' (D-096 item 2).

### D-098 -- the template push of a delivered repo is not a student action: formula v8, no feedback for it
Date:        2026-10-12
Status:      DECIDED and implemented. Real database untouched (read-only check only).
Authority:   Anas (answers to the five questions of the previous note).
Problem:     In a one-assignment repo (attempt >= 2, D-090) the collector gives EVERY commit that assignment, including the
             template push "Initial commit: ...". v4's rule (c) needed `assignment_id IS NULL`, true for the four-assignment
             attempt-1 repo only, so the push counted as a student commit, its CI run as a student run, its 92 added lines as
             the student's LOC, and its all-stub results as failed pushes in the feedback history.
Rule (v8):   "Initial commit:" message AND (`assignment_id IS NULL` OR it is the EARLIEST commit graded under its attempt, with
             attempt_no >= 2). Order by committed_at, ties by sha. Fail open: a NULL message, a commit that was never graded
             (repo unknown), or one with an earlier graded commit in its attempt stays a student commit.
Repo:        `raw_commits` has no repo column and none was added (a schema change needs your word; and a new column would be
             NULL for the existing commits, so the effect could not be shown on attempt 1770). A delivered repo holds one
             assignment and is exactly one `attempts` row (D-090), so the repo is read through `test_results.attempt_id`.
             Consequences, stated: (a) it needs the commit to have been graded, which the cycle does before the features;
             (b) an UNGRADED commit earlier than the template push would hide it (unknown order, so fail open: the push
             then stays a student commit); (c) attempt-1 repos are not affected by the new branch (the four-assignment repo has
             several attempt rows and its template push already has no assignment). Upgrade trigger: store owner/repo on
             `raw_commits` at collection time (additive, nullable).
Scope:       grading and storing are unchanged: the push is still graded and its `test_results` / traces kept (mastery was
             already safe: D-079, an all-stub commit is "unattempted"). It is excluded from: V3 gaps and the
             release-to-first-commit lag; V6 changed LOC; the CI runs V4/V5/V6 read (`_run_scopes`, through head_sha); the
             watermark and the dirty-student test (a fresh delivery alone is not student activity); and, in V5/V6, its
             `test_result` traces (`_drop_template_commit_results`, which keeps traces that name no commit). Also from
             the diagnosis (`assessment/diagnose.py`, always): without that, g_ext_parse failing on the template push AND on the
             first real push would print "keeps failing across several pushes" on the first real comment.
V4 (read):   V4 does not read commits at all: it reads `raw_workflow_runs` per assignment. The template push entered it as the
             CI run on that commit: as `last_run` for a censored student (elapsed measured to a push the student did not
             make), and as `first_pass` if that run were ever green. Both go with the `_run_scopes` change. Not changed, and
             not this decision's business: the clock starts at `assignments.released_at`, which is the first release, not the
             start of attempt N (so a pass on attempt 2 is measured from the original release).
V3 (read):   gaps and `procrastination_h` (= first commit - release): the template push was a commit like any other, so a
             fresh student's "first commit" was the push (a lag measured to the template) and the first real gap started at
             it. Both now start at the first student commit. `procrastination_h` takes the student's first commit overall and
             the earliest release of the assignments joined: unchanged and aggregated across attempts, as before.
Feedback:    `graded_commits` and `recent_unposted` (so the CLI, the dry run and the hourly phase) skip the push;
             `build_feedback` and `feedback_agent.gather_input` raise `TemplateCommit` for it, so no text is built either.
Versions:    FORMULA_VER = "v8". v2..v7 compute exactly as before (the new branch is behind `_initial_commit_by_attempt`),
             stored rows are not touched, and a v8 run at the same watermark as a v7 row never overwrites it (D-063).
Effect:      attempt 1770 of anas, read-only, computed in memory (nothing written): f343fb1b3f ("Initial commit:", 04:02:23)
             is the template push under v8 and is NOT under v7; bc2bf5cf55 ("extract: retry loop") is a student commit under
             both. v7 -> v8: excluded commits 3 -> 4, excluded (sync/template) CI runs 3 -> 4, V3 regularity 0.163 -> 0.164 and
             burstiness 0.674 -> 0.671, V6 score 0.735 -> 0.741 with py.data_structures failures 8 -> 7 and fail_ratio
             0.365 -> 0.355; V4 and V5 unchanged for anas (V4 has no cohort passers, so no score either way).
Tests:       tests/test_template_commit.py (12): recognised from v8 only; a student commit named "Initial commit:" that is not
             first is kept; never graded and NULL message are kept; attempt-1 repos unchanged; two deliveries each have their
             own push; commits, LOC, runs, gaps, watermark and dirty test; the trace filter; v6/v7 values do not depend on the
             rule; a stored v7 row is not rewritten; no feedback is selected, built or gathered for it and the first real
             comment does not say "keeps failing". With the v8 branch disabled 10 of the 12 fail.

### D-099 -- the agents are wired into the hourly loop behind `--with-llm` (IR-1, IR-3, IR-4 of docs/agents.md section 11)
Date:        2026-10-12
Status:      DECIDED and implemented. Not committed. OFF by default; the scheduled task's command is unchanged.
Authority:   Anas (the request to apply the integration requests; the Code Agent answer below is his). The two cap values
             are his numbers; the arithmetic in CONFIRM 1 is mine.
What:        (IR-1) `scripts/demo.py` reads `llm_correctness_opinion` on both lines (the lines were 273 and 288, not 267 and 282).
             (IR-4a) `grade_collected.run(after_grade=None)`: for a commit that graded with status `ok`, the callable runs
             BEFORE the temporary checkout is deleted (the only moment the student's file exists); whatever it raises goes to
             `summary["agent_errors"]`, never to `summary["failed"]`. The module still imports nothing from `agents/` (inv. 13).
             (IR-4b) `run_cycle` and `run_hourly`: `--with-llm` (default off), `--llm-run-cap` (default 10), `--llm-daily-cap`
             (default 20); both caps count PROVIDER calls through `agents.budget.CallBudget` + `UsageLedger(.vdel/llm_usage.json)`.
             One budget per cycle. `--dry-run`, `--skip-network` and a corrupt ledger file each call no agent (the last fails
             CLOSED, with a line saying so). The hook (`run_cycle.AgentsHook`) is built per grade-stage connection, NOT with the
             cycle's `conn` the IR sketch used (that is None in production), and runs in a SAVEPOINT, so a SQL error inside an
             agent cannot abort the grading transaction. It runs the Feedback Agent ONLY (see CODE AGENT below).
             (IR-3) `agents.pipeline.persist_feedback`: ONE `coach`/`intervention` trace per (attempt, commit), only when
             `result.used_llm`, idempotent by a SELECT on (agent, commit_sha, attempt_id), written through `Memory.log_trace` on
             the caller's connection. `memory/memory.py` is unchanged; `intervention` is in `NON_MASTERY_KINDS`, so BKT never reads
             it. `run_agents_for_commit(persist=True)` still raises `IntegrationPending` (a test pins it): persistence is a step
             the caller takes after the run, not a mode of the run.
             Text posted to GitHub: the deterministic text stays the BASE. With `--with-llm`, `run_hourly` adds the stored
             model-only paragraph ("More detail", from `feedback_agent.render_addendum`) UNDER it via
             `plan_issue_post(..., addendum=)`; the marker stays last. No stored paragraph (rejected, failed, capped, an
             `--with-llm` off run, a commit graded before the flag) or one that would leak hidden test source (the final guard
             raises, `_plan` catches it) means the deterministic text alone. The paragraph is redacted and leak-checked when it
             is stored AND again on the exact text sent.
             The template push (D-098) never reaches an agent: `AgentsHook._run` returns before any read or call, and the posting
             queries already exclude it.
CAPS:        10 per run, 20 per day (his numbers). One commit now costs at most 4 provider calls (the Feedback Agent, two
             `judge()` of up to 2 calls each, `agents/budget.py`), so a run of 10 is about two commits and a day of 20 about five.
CODE AGENT:  DECIDED (Anas): its verdict is never persisted. Case that applies: the Feedback Agent does NOT need the Code Agent's
             output (`gather_input` reads `test_results`, `diagnose` and the mastery slice through `cur`; the Code Agent was
             only ever given a `DryRunMemory`, whose writes are discarded). So the hook does not run it: it passes no
             `assignment` and no `code_path`, `run_agents_for_commit` marks the step `skipped` and no provider call is made
             for it. `run_agents_for_commit` and the Code Agent itself are unchanged (the demo and the benchmark still use
             them); only the cycle's hook leaves it out. Reversible by passing `assignment`/`code_path` again.
Incident:    My first partial test run still contained `test_with_llm_is_reported_as_not_wired`, which calls
             `run_cycle(with_llm=True)` with no fake. Harmless while the flag was a stub; with the wiring it went through the REAL
             gateway: 2 provider calls on model `gpt-6.1-sol` were recorded in `.vdel/llm_usage.json` (the request said NO LIVE
             CALL). The test is deleted (its job is done by tests/test_with_llm.py), the ledger file I created was removed, and
             `tests/test_with_llm.py` now blocks every provider handler in an autouse fixture and points the default ledger path
             at a temp file, with a regression test. I did not read the model's reply or the key setup. The real database was
             not touched (D-064 counter: 0 connections to `vdel`).
Tests:       tests/test_with_llm.py (24, fake LLM, no network): on makes exactly one provider call (the Feedback Agent; no
             prompt carries a submission) and the log says `code_agent=skipped`; off writes nothing and prints nothing about the agents; the task
             command files never mention the agents; on writes one trace and a second cycle none (no new call); persisting twice
             writes one; a rejected answer, a provider outage, a daily cap reached, a run cap of 0, a corrupt ledger, a raising
             agent and a SQL error in an agent each leave the grading and the cycle finished; mastery is equal with and without the
             agents, the only extra trace is the coach row, and the wipe-and-replay proof matches; the template push reaches no
             agent while the student's own commit in the same attempt does; `after_grade` sees the file and the directory is
             gone afterwards; the posted comment has the deterministic text first, the paragraph under it, the marker last;
             a leaking paragraph is dropped. Mutation-checked: removing the template check, the persist guard, the SAVEPOINT
             rollback or the addendum each fails the matching test.

### D-100 -- where the agents branch's decisions live
Date:        2026-10-12
Status:      DECIDED (a pointer, nothing else).
Decision:    The decisions D-200..D-225 of the agents branch are in `docs/DECISIONS_AGENTS.md`, under their own numbers, not
             copied here. They are append-only there. A reader of this file who meets "D-2xx" in a code comment (for example
             D-200/D-201, the rename of the correctness score to `llm_correctness_opinion`) looks it up there. Decisions about
             the integration of the agents into the main loop are numbered here (D-099 and up).
