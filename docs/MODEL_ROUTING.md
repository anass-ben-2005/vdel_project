# MODEL_ROUTING.md — When Opus, When Sonnet

> The §5 / §27.7 deliverable. The rule is not "hard task → Opus." It is:
> **spend on reasoning that changes a decision, not on volume.**
>
> Reading a lot is not a reason to use Opus. A wide read handled by a Sonnet sub-agent
> that returns 1500 words is the cheap path, and it is the default way large amounts of
> material should enter this project. Long context and model choice are **independent
> decisions** — conflating them is the most common way this budget gets wasted.

---

## The default

**Sonnet.** Everything below the escalation line, including all three sub-agents, including
all wide reading.

## The escalation line

Escalate to **Opus** only when a wrong answer is expensive *and* the answer depends on
holding several things in mind at once. Concretely, for this project, that is six situations:

| # | Situation | Why it clears the bar |
|---|---|---|
| 1 | **Designing the M2 agent interface** | Echo defines the signature the Code Agent must honour in M4. Get it wrong and M4 becomes a refactor instead of an internals swap. One of the three integration seams |
| 2 | **`memory.py`'s method surface** | It is the only door to memory (invariant 2) and `rebuild_from_traces` is the project's central proof. Its shape has to be right the first time |
| 3 | **A genuine spec divergence with no obvious resolution** | When `spec-verifier` returns DIVERGENT and both sides are defensible — the Sara `0.47` situation. Deciding whether the code or the document is wrong is exactly the reasoning worth paying for |
| 4 | **Debugging where the symptom and the cause are in different files** | Especially anything where mastery numbers move but the update looks correct. The pass-1 BKT bug lived here |
| 5 | **Reviewing a change to a shared data contract** | Schema, `learner_features` JSONB shape, the agent interface, event-sourcing semantics. Reviewer escalates these itself |
| 6 | **M3's model-decision reasoning and M4's prompt architecture** | The least reversible decisions in the project, and the ones the dissertation has to defend |

Everything else — and that is most of the internship — is Sonnet.

## Explicitly Sonnet, even though it feels expensive

| Task | Why Sonnet is correct |
|---|---|
| Transcribing a formula from a module document | The hard part is fidelity, not reasoning. `spec-verifier` then checks it — a verifier catches transcription errors more reliably than a smarter transcriber avoids them |
| Any wide read (`explorer`) | The reasoning is in the conclusion, not the reading. §5 says this explicitly |
| Spec verification (`spec-verifier`) | It is comparison, not judgement. It is forbidden from proposing fixes precisely so it never needs to reason its way to an opinion |
| Routine diff review (`reviewer`) | Most commits here are one file plus one test |
| Writing tests, docstrings, documentation | Mechanical against an existing design |
| Git operations, DoD command runs, plotting | Deterministic |
| Authoring the 5 benchmark submissions | Writing, not architecture. Ground truth is *yours* to decide, not a model's |

## The three questions before escalating

1. **Would Opus's answer actually be different?** If the answer is written in a document and
   the task is finding and applying it, no. Use `explorer` or `spec-verifier` instead.
2. **Is the cost of being wrong high and hard to undo?** Data contracts, schemas, the agent
   interface: yes. A docstring, a test name, a plot label: no.
3. **Does this require holding 3+ components in mind at once?** If it fits in one file, it
   fits in Sonnet.

Two yeses → Opus. Otherwise Sonnet.

## Anti-patterns to avoid

- **Opus for a big read.** Reading is cheap-model work. Delegate it to a Sonnet sub-agent
  and let the main thread pay for 1500 words.
- **Opus because the session is important.** M2's DoD demo matters enormously and is almost
  entirely deterministic scripting.
- **Opus because the code is subtle.** Subtle-but-specified is `spec-verifier` work.
  Subtle-and-unspecified is Opus work. The distinction is whether a document exists.
- **Sonnet for the M2 interface design** to save money on the one decision that determines
  whether M4 is a swap or a rewrite. This is the false economy that matters most here.

## Practical session pattern

```
Session start (Sonnet)      /session-start, read HANDOFF, name the task
   │
   ├─ needs wide context? → dispatch explorer (Sonnet sub-agent) → 1500 words back
   │
   ├─ is it one of the six? → switch to Opus, plan in the MAIN thread
   │                          (never in a sub-agent — planning needs the raw
   │                           material afterwards to keep editing it)
   │
   ├─ implement (Sonnet)   ← almost always where the day is spent
   ├─ verify (spec-verifier, Sonnet)
   ├─ review (reviewer, Sonnet; escalates itself if the contract moved)
   └─ commit + /session-end (Sonnet)
```

Switch back to Sonnet as soon as the decision is made. Opus is for the decision, not for the
implementation that follows it.
