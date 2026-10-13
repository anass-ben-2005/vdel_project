# CONTEXT_POLICY.md — Reading Wide, Carrying Little, Delivering Whole

> The §27.8 and §27.9 deliverables, made concrete for this repository.

---

# Part I — Context strategy

## 1. The principle

Reading is cheap. **Carrying** is expensive. Being wrong is the most expensive thing of all.

> Read wide once → compress into a durable artifact → work narrow forever after.

This project has an unusually strong case for the "read wide" half. Its three documented
failures — the invented `problems`/`attempts` schema, the inert BKT update, the fabricated
`duration_s` — were all *narrow* failures: code written from a partial picture, from
keyword matches, from a summary of a design rather than the design. None was caused by
reading too much.

## 2. Read wide — the six moments

Load aggressively. Whole files, whole directories, whole document sections.

| Moment | Why breadth is correct | Typical cost |
|---|---|---|
| **Initial repository analysis** (done once — produced `DEVELOPMENT_MAP.md`) | Breadth *is* the deliverable | up to ~50% |
| **First touch of a new component** — M2's `memory/`, M3's `system/llm.py`, M4's `agents/` | The whole design section, once, beats six greps | ~30% |
| **Any architectural decision spanning >2 files** — the agent interface, `memory.py`'s method surface | A wrong contract costs more than a full context window | ~40% |
| **Debugging where cause ≠ symptom** — mastery numbers moving oddly, `rebuild_from_traces` not reproducing | The pass-1 BKT bug lived exactly here | ~40% |
| **Integration work** (§26) | Cross-component behaviour *is* the point | high |
| **Reviewing a change to a shared data contract** | Schema, JSONB shape, the agent interface | moderate–high |

In these moments, **do not grep for fragments and reason from keyword matches.** Read the
files.

## 3. Read narrow — the default

Stay tight for routine implementation of an already-planned task, writing a test for a
function just written, documentation updates, formatting and renames, and routine git work.

**Working set: the target file, its direct test, the relevant `docs/reading/` artifact.
Nothing else.** That is most of this internship.

## 4. Whole files, not fragments

**Threshold: read whole under 800 lines.** Above it, read the interfaces, the entry points,
and the sections the task touches — **and state explicitly which parts were not read.** An
unmarked gap is worse than a marked one.

Almost every source file in this repo is under 800 lines, so the practical default is
"read it whole." The exceptions are the four module documents and `explanation.md`, which
are section-addressable by design.

Non-negotiable whole reads: `variables/*.py` (they are the math, and partial reads of
formula code are how transcription errors survive), `memory/memory.py` (it is the only door;
a partial read of the door is worthless), and `sql/*.sql` (short, and they are the contract).

## 5. Sub-agents as context firewalls

The single most valuable technique available, and the reason the main conversation stays
cheap.

```
Main thread                          Sub-agent (own context window)
-----------                          ------------------------------
"Read Modules_3_9 §Memory and    →   reads ~40K tokens of design document
 report memory.py's contract"        reasons across all of it
                                 ←   returns ≤1500 words: CONTRACTS + SURPRISES
main thread pays: ~1.5K
```

Three agents, each with a hard return cap: `explorer` (1500 words), `spec-verifier`
(1200), `reviewer` (1200). Use them for repository-wide exploration, "where is X used?",
reviewing a large diff, reading a long document section to answer one question, and
checking documentation drift across many files.

**Do not** use a sub-agent when the main thread needs the raw material afterwards to keep
editing it. A summary of code you are about to modify is worse than the code. This is
precisely why there is no planner agent — planning hands off to implementation, and
implementation needs the material.

## 6. Compress after every wide read

A wide read that isn't written down is a wide read you pay for again next session.

Run `compress-read` **before** moving on — not at end of day when the findings have gone
stale. Six fields into `docs/reading/YYYY-MM-DD-<topic>.md`, then point at it from
`HANDOFF.md`'s *Files NOT needed*, then **drop the raw material from context.**

## 7. Budgets per session phase

| Phase | Target | Rationale |
|---|---|---|
| Repository analysis | up to ~50% | breadth is the deliverable |
| Component planning | ~30% | one component + its contracts |
| Implementation | ~15% | target file, test, memory entry |
| Review / integration | moderate–high | cross-file reasoning is the point |
| Commit + documentation | minimal | the diff and the doc |

`/session-start` declares the budget out loud. **Exceeding it is a signal the task was
scoped too large — split it, do not silently spend more.**

## 8. Attention hygiene

A full context window is not an *attended* context window; material in the middle gets less
attention than material at the edges.

- **After a large read, restate the current objective** before acting on it.
- Stable material early (`CLAUDE.md`, `DEVELOPMENT_MAP.md`), volatile material last (the
  current task, the current diff).
- Drop failed command output, abandoned drafts, superseded plans. State the conclusion,
  discard the noise.
- **Never re-paste a file already in context.** Never paste `CLAUDE.md` — it is auto-loaded.

## 9. Cache discipline

Keep the stable prefix stable. `CLAUDE.md` and the architecture documentation should not be
rewritten mid-session — edit them at session boundaries, immediately before or after a
commit. Churning them invalidates cached context and makes every subsequent turn more
expensive. This is why `/commit` says to update `CLAUDE.md` "at a session boundary."

## 10. Compaction and session boundaries

- Compact only at **natural boundaries** — after a commit, after a milestone DoD. **Never
  mid-implementation.**
- Always write `HANDOFF.md` before compacting or ending.
- **Prefer a fresh session with a good handoff record over a heavily compacted long one.**
  A clean 5K-token handoff beats a lossy 100K-token history. This is the default here, and
  it is the whole reason `HANDOFF.md` is maintained so carefully.

## 11. Anti-patterns

Do not: re-read a file already in context · paste large files when a read would do · load
the whole repository for a one-line change · keep a long document after extracting what was
needed · use a sub-agent to summarise something you will immediately need in full · let
context accumulate across a whole day without a single compression step.

---

# Part II — Multi-part output conventions

## 1. The rule

If a deliverable does not fit comfortably in one response, it becomes a **multi-part
deliverable** — never a shorter, vaguer version of itself.

Forbidden without exception: *"…and so on for the remaining components"*, *"(abbreviated for
brevity)"*, placeholder bodies or `pass` or `TODO` where real content was requested, silently
dropping later sections, degrading depth in the last third to reach the end.

Note the asymmetry: **deliverables are never truncated; explanations are never padded.**
Completeness applies to artifacts, proportionality applies to prose.

## 2. Which deliverables are multi-part by default

- The final integration report (§26).
- Any full component implementation with its tests.
- A milestone write-up for a supervision meeting.
- `benchmark/RECOMMENDATION.md` with its measured matrix.

Most day-to-day work is *not* multi-part. One task, one commit, one response is the norm.

## 3. Manifest first

Before starting, output:

```text
DELIVERABLE: <name>
TOTAL PARTS: <n>

Part 1 — <contents>            → <files written>
Part 2 — <contents>            → <files written>

Each part is complete and independently valid on delivery.
```

Then deliver Part 1 and **stop**.

## 4. Where to split

**Semantic boundaries only:** a whole file, never half a file. A whole function or class.
A whole numbered section. A whole component.

Every part must leave the repository in a coherent state — **if Part 2 never arrives, what
Part 1 produced must still work.** Where possible, align part boundaries with **commit
boundaries**: a part that ends at a commit ends at a safe point, and is also the right
moment to compact.

## 5. Header and footer

```text
▌PART <k> of <n> — <title>
```

```text
── END PART <k>/<n> ──
Delivered:  <what this part completed>
Files:      <files created or modified>
State:      <repo state — committed? tests passing?>
Next:       <exactly what Part k+1 will contain>
Resume:     say "continue" to receive Part <k+1>
```

Then stop. **Do not begin the next part in the same response.**

## 6. Resuming

On "continue" / "next" / "part k+1": start immediately at the next part. Do **not**
re-summarise previous parts, repeat delivered content, or restate the manifest.

If context was compacted or the session is new, reconstruct position from `HANDOFF.md`'s
*Multi-part state* line and the last footer, state in one line where you are resuming from,
and continue.

## 7. Files over chat

For anything large and durable — code, documentation, design records — **write it to a file**
and keep the chat response to the manifest, the explanation, and the delta. Chat is for
understanding; files are for artifacts. This is better for the reader and dramatically
cheaper in context.

A part that writes three files and explains them in twenty lines is a good part. A part that
prints three files into the chat and explains nothing is a bad one.

## 8. Sizing

Roughly one of: one major document section fully developed · one component's implementation
plus its tests · 3–6 related files · one commit's worth of work.

If a single part would exceed that, the part itself should be split. **Prefer more, smaller,
complete parts over fewer large ones.**

## 9. Interruption

If a response is cut off mid-part, the next response must state the exact point of
interruption, resume from the last **complete semantic unit** — not the last character — and
never silently skip whatever was in flight.
