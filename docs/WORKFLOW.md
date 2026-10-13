# WORKFLOW.md — Task → Commit

> The §27.12 deliverable: the exact loop, as it runs for **this** repository. Not a
> generic agile diagram — every step names the file, the agent, or the command that does it.

---

## The loop

```
                    /session-start
                          │
                          ▼
                   ┌─────────────┐
                   │    TASK     │  one logical unit, ends in one commit
                   └──────┬──────┘
                          ▼
                   ┌─────────────┐
                   │    PLAN     │  main thread · Sonnet, or Opus if one of the six
                   └──────┬──────┘  wide read? → explorer sub-agent → 1500 words back
                          ▼
                   ┌─────────────┐
                   │  IMPLEMENT  │  Sonnet · narrow context: target file + its test
                   └──────┬──────┘
                          ▼
                   ┌─────────────┐
                   │    TEST     │  pytest -q · ruff check .
                   └──────┬──────┘  a formula? → spec-verifier, and run the number
                          ▼
                   ┌─────────────┐
                   │   EXPLAIN   │  the seven points · worked example if numbers moved
                   └──────┬──────┘
                          ▼
                   ┌─────────────┐
                   │  DOCUMENT   │  docs/explanation.md · DECISIONS.md if a decision stuck
                   └──────┬──────┘
                          ▼
                   ┌─────────────┐
                   │   COMMIT    │  /commit → reviewer → conventional message
                   └──────┬──────┘
                          ▼
                   ┌─────────────┐
                   │   MEMORY    │  HANDOFF.md rewritten · STATUS.md if a DoD ran
                   └──────┬──────┘
                          ▼
                   next task, or /session-end
```

---

## Step by step, with the specific mechanism

### TASK

From `HANDOFF.md`'s *Next task*, or the next unticked item in the current milestone of
`BUILD_PLAN.md`.

**Sizing test:** can it be described as *"change file X so that Y, proven by test Z"*? If
not, it is two tasks. The target is one file plus one test. `BUILD_PLAN.md` is already
decomposed to roughly this granularity — 1.6, 2.1, 3.1 are each a few tasks, not one.

### PLAN

Main thread. Never a sub-agent — planning needs the raw material afterwards to keep editing
it, and a planner that hands back a summary throws away exactly what implementation needs.

Sonnet by default. Opus only for the six situations in `docs/MODEL_ROUTING.md` — designing
the M2 agent interface, `memory.py`'s method surface, an unresolved spec divergence,
cross-file debugging, a shared-contract review, M3/M4 core reasoning.

**Before writing any code, open the specification.** Most of M0–M4's code already exists in
the module documents. The default is transcribe-and-verify, not design-from-scratch. If you
believe the document's code needs changing, **stop and ask** — do not improve it silently.

If a wide read is needed, dispatch `explorer`. Its reading stays in its context; only
findings come back.

### IMPLEMENT

Narrow context by design: the target file, its direct test, the relevant `docs/reading/`
artifact. Nothing else. If the working set is growing past that, the task was scoped too
large — stop and split it.

Docstrings state the **why**, citing the design decision or the paper. Unknown values are
`None` or `TODO(verify)` — **never** a plausible-looking invented number. That specific
failure is in this repo's history twice.

### TEST

```bash
pytest -q          # baseline: 64 passed, 1 xfailed
ruff check .
```

If the change touches a formula transcribed from a module document, this step is not
finished until `spec-verifier` has run and a number has been reproduced by execution. The
pass-1 BKT bug was invisible to reading and obvious to running.

Never claim something works without testing it when testing is possible.

### EXPLAIN

The seven points from `/commit`. Scale to the change — a docstring fix does not need seven
paragraphs. Include a worked example whenever a number moved: one input, the intermediate
values, the output.

The worked example is not ceremony. It is how you find out whether you actually understand
the change, and it is what makes it defensible on a whiteboard on Wednesday.

### DOCUMENT

Same commit as the code. Not a follow-up.

| Changed | Update |
|---|---|
| A file's behaviour or responsibilities | `docs/explanation.md` |
| Architecture or an invariant | `CLAUDE.md` — **at a session boundary**, not mid-session |
| A decision that will need justifying | `docs/DECISIONS.md` |
| A milestone's DoD was run | `docs/STATUS.md`, via `dod-evidence` |
| A wide read happened | `docs/reading/`, via `compress-read` |

### COMMIT

`/commit`. It runs `reviewer`, applies the seven points, and writes a conventional message.
Small and atomic — never one enormous commit after a whole feature.

### MEMORY

`HANDOFF.md` gets rewritten at session end, but if a session spans several commits, update
*Next task* and *In progress* as you go. The record is only useful if it's true.

---

## Where this loop bends

**Milestone boundaries.** The last task of a milestone is followed by `dod-evidence`, not
by the next task. Run the DoD, capture the output, then stop and consider whether to compact
or start fresh.

**Integration work (§26).** Wide context is explicitly correct here — the point *is*
cross-component behaviour. Load the components involved, run the integration test, then
compress afterwards. The integration test that matters at every boundary is the same one:
wipe `learner_profile`, replay `traces`, deep-diff.

**The Tuesday stop.** `BUILD_PLAN.md`'s weekly rhythm overrides this loop on Tuesdays. Stop
building. Run the DoD, write up what happened, prepare the demo, send Dr. Ezzatul the update
*the day before* the meeting. A milestone that is functionally complete but undemonstrated
and undocumented reads, in a supervision meeting, as a milestone that did not happen. This is
the discipline that slips most easily and costs most.

---

## The three stop-and-ask triggers

These interrupt the loop entirely. They exist because each has already cost this project a
session:

1. **A task seems to need a new table, file, or approach not in `CLAUDE.md` or the module
   documents.** Do not invent structure. Ask.
2. **`spec-verifier` returns DIVERGENT and both sides look defensible.** Do not pick one and
   proceed. Log it in `DECISIONS.md` as `OPEN` and ask.
3. **A proposed change trades explainability for accuracy.** Auditability is a functional
   requirement here; a grade that cannot be explained is not a grade that can be defended.
   Ask before implementing.
