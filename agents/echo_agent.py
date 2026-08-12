"""agents/echo_agent.py — BUILD_PLAN 2.4. The tracer bullet.

Rule-based, no LLM, no network, no cost. Its only job is to prove the whole loop --
event -> verdict trace -> mastery update -> profile evolution -- *before any LLM exists*,
so that when `agents/code_agent.py` arrives in M4 it is an internals swap and not a
refactor. It is not throwaway work: it defines the agent interface M4 must honour.

The interface is designed against four consumers, not one, because Echo's signature is one
of the three integration seams (DEVELOPMENT_MAP.md D.3):

  1. `VDEL_Modules_3_9_Build.md` D.5 `grade()`  -- positional order and the return triple
  2. `system/orchestrator.py` (Modules_3_9 H)   -- module-level sync function named `grade`,
                                                   called via `asyncio.to_thread`
  3. `agents/reviewer.py`'s `detect_disagreement` -- the verdict OBJECT's attribute surface
  4. `memory/memory.py`                          -- the only door (invariant 2)

Four decisions were made while writing it. Each is recorded rather than silent:

**D-015 -- Echo matches the live door, not D.5's call to it.**
D.5 line 941 calls `mem.update_mastery(student_id, concept, correct=..., item_difficulty=...)`.
The live `update_mastery` takes NEITHER argument: it recomputes from the log instead of
folding an outcome onto state read back from the profile (D-007). D.5 predates that
decision, so transcribing it verbatim would raise `TypeError` on the first call. This is the
third place D-007's consequence propagates -- after `update_mastery` itself and
`rebuild_mastery_from_traces` -- and M4's Code Agent will hit it too: whoever writes
`code_agent.py` must log the evidence trace first and then call `update_mastery`, exactly as
this file does.

**Option A -- Echo does not invent the rubric -> BKT mapping.**
`memory.MASTERY_TRACE_KINDS` is `{"ci_run"}`, and `NON_MASTERY_KINDS["verdict"]` states in
prose that the mapping from a 0/2/4 rubric score to a BKT pass/fail "is a decision that has
not been made". So Echo logs its `verdict` as a CHILD of the `ci_run` it judges and then
calls `update_mastery`, which replays the `ci_run`. Mastery therefore moves because of the
CI event, not because of Echo's opinion -- the wiring is proven end to end without inventing
the mapping, and every existing rebuild test keeps its meaning. Adding `verdict` to
`MASTERY_TRACE_KINDS` (with D.5's `correctness >= 3` rule) is M4's decision to make, in the
same breath as the replay-set change it requires.

**`evidence_failures` lives on the model, not only in the return triple.**
`reviewer.detect_disagreement` reads `getattr(code_v, "evidence_failures", None)`, but D.5's
`Verdict` model declares no such field -- `grade` returns it as the third tuple element and
copies it into the trace payload. As written, the Reviewer's `evidence:code_agent_unmatched`
flag can therefore never fire. Declaring the field here (defaulting to `[]`) costs nothing
and keeps the third return value for D.5 compatibility. It makes that flag *reachable*, not
yet live: Echo never populates it, because it quotes nothing to fail a match. M4 is what
fills it, and M6 is what reads it.

**D-016 -- Echo scores only what CI actually evidences.**
A green CI run is evidence about correctness. It says nothing about readability, approach or
idiomatic Spark, so scoring those from a CI conclusion would be exactly the fabricated
judgement invariant 6 exists to prevent. The design document already has a convention for an
agent with no information -- `orchestrator._missing_perf_verdict()` uses the middle anchor 2
with `confidence="low"` -- and this file follows it exactly. BUILD_PLAN 2.4's literal
"failed -> 0, passed -> 0.75" is preserved in the payload as `echo_outcome`, so its scale
(a [0,1] scalar, not a rubric anchor) is recorded rather than quietly reinterpreted.
Correctness maps to 4/0 so that D.5's `correctness >= 3` rule reproduces Echo's binary intent
unchanged when M4 lands, exercising both branches.

**On invariant 6 -- OPEN, not settled (D-018).** Echo attaches no verbatim quotes, because it
reads no code. Its evidence is the `ci_run` trace itself, cited by `parent_trace_id` and
repeated in the payload's `evidence_source` -- a foreign key to the event, which cannot be
fabricated, there being no generative step to fabricate it. The reading this file operates
under is that invariant 6's string-matching clause governs LLM-authored verdicts, its named
defence being hallucination. **That reading is not authorised**: invariant 6 is written
unconditionally, and whether a deterministic agent satisfies it by citing an event is a
question for Dr. Ezzatul, logged OPEN alongside the Sara 0.47 finding. M4 must not lean on
this reading for its own no-quote cases until it is settled.

Known gaps and named choices, none silent:
  - Echo does NOT call `apply_recurrence_rule`. Opening weaknesses on repeated failures is
    the fast path's job (BUILD_PLAN 2.2), not a judge's. Echo would double-fire it.
  - `code_path`, `reference` and `profile_snapshot` are accepted and never read. They are
    M4's inputs, present so the swap changes no call site.
  - **No memory slice is computed or recorded.** An earlier draft built the
    `{mastery, open_weaknesses}` slice D.5 assembles for its prompt and wrote it into the
    verdict payload, to exercise the `profile_snapshot` seam. That was cut: Modules_3_9 H.2
    names the *grade* trace (M6's Reviewer) as where a judgement-time snapshot is recorded,
    and no document puts one on a verdict. Recording it here would have created a second
    candidate home for "what did the system believe when it graded this?" -- the same
    one-implementation argument D-007 and D-012 make elsewhere -- and baked an unsanctioned
    pattern into the tracer bullet that M4 would then inherit. The seam stays in the
    signature; filling it belongs to M4, which actually has a prompt to tone.
  - `confidence` is permanently "low", so the Reviewer will flag every Echo verdict as
    `low_confidence:code`. That is correct behaviour, not a defect: Echo is not a
    trustworthy judge and the aggregate should say so.
  - **D.5's parameters are keyword-only here.** D.5 writes `profile_snapshot=None,
    reference=None` with no `*`, so they are positional-or-keyword there; this file makes
    everything after `code_path` keyword-only. The parameter NAMES and the return triple are
    D.5's contract exactly, but the calling CONVENTION is narrower. Compatible with every
    call site in the documents -- the orchestrator passes both by keyword -- and the
    narrowing is deliberate, since a positional `profile_snapshot` would be indistinguishable
    from a positional `reference` at a glance.
  - **`ci_conclusion` is required, and the orchestrator as printed never passes it**
    (Modules_3_9 H, line 1818). That is not a break in practice, because of sequencing:
    `ci_conclusion` is Echo's stand-in for reading the submission, M4 replaces these
    internals with an agent that reads `code_path` instead and needs no such argument, and
    the orchestrator only arrives in M6 -- after Echo is gone. If Echo is ever driven by an
    orchestrator before then, that caller must supply it, exactly as `run_grading` already
    threads `ci_duration` through to the Performance Agent.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, conint

# Imported, never redefined: one definition of "which CI conclusions say anything about what
# the student knows". GitHub's vocabulary also includes cancelled, skipped, timed_out,
# neutral, action_required and stale, none of which are evidence about a person.
from memory.memory import OUTCOME, Memory

# D.5's `stability_check` iterates exactly these four, in this order. Kept as a tuple so the
# rubric's order -- correctness before readability, which M4's prompt relies on to defend
# against halo bias -- cannot drift.
CRITERIA = ("correctness", "approach", "readability", "idiomatic")

# BUILD_PLAN 2.4's literal numbers, on their own [0,1] scale. Preserved as provenance in the
# payload; deliberately NOT the rubric scores, which are anchored 0/2/4.
ECHO_OUTCOME = {True: 0.75, False: 0.0}

# The only criterion a CI conclusion evidences. 4/0 rather than 2/0 so that D.5's
# `correct = verdict.scores.correctness >= 3` reproduces this binary unchanged in M4.
CORRECTNESS_SCORE = {True: 4, False: 0}

# The middle anchor, for criteria this agent cannot see. Matches
# `orchestrator._missing_perf_verdict()`'s `PerfScores(efficiency=2)` + `confidence="low"`.
UNEVIDENCED_SCORE = 2

ACTOR = "code_agent"


class EchoScores(BaseModel):
    """D.5's `Scores`, field for field. M4 replaces the values, not the shape."""

    correctness: conint(ge=0, le=4)
    approach: conint(ge=0, le=4)
    readability: conint(ge=0, le=4)
    idiomatic: conint(ge=0, le=4)


class EchoVerdict(BaseModel):
    """D.5's `Verdict`, plus the `evidence_failures` field the Reviewer already reads.

    `evidence` stays an empty list per criterion here: Echo quotes nothing because it reads
    nothing. The key exists so M4 fills a slot rather than adding one.
    """

    scores: EchoScores
    evidence: dict[str, list[str]] = Field(default_factory=dict)
    misconceptions: list[dict[str, str]] = Field(default_factory=list)
    feedback_for_student: str
    confidence: str
    evidence_failures: list[dict[str, str]] = Field(default_factory=list)


def _verdict_for(passed: bool | None) -> EchoVerdict:
    """The rubric mapping (D-016).

    `passed is None` means the CI run reached a conclusion that assesses nothing --
    cancelled, skipped, timed_out. That is a real-world event, not a caller error, so Echo
    returns an all-neutral verdict rather than raising: refusing to grade would abort the
    orchestrator's whole run over an infrastructure hiccup. Correctness drops to the same
    middle anchor as the other three, because in that case CI evidences nothing at all.
    """
    correctness = (UNEVIDENCED_SCORE if passed is None
                   else CORRECTNESS_SCORE[passed])
    if passed is None:
        feedback = ("[echo] The CI run reached no pass/fail conclusion, so this submission "
                    "was not assessed. No score here reflects your work.")
    elif passed:
        feedback = ("[echo] CI passed. This is a placeholder verdict from the rule-based "
                    "Echo agent: only correctness is evidenced, by the CI result itself.")
    else:
        feedback = ("[echo] CI failed. This is a placeholder verdict from the rule-based "
                    "Echo agent: only correctness is evidenced, by the CI result itself.")

    return EchoVerdict(
        scores=EchoScores(
            correctness=correctness,
            approach=UNEVIDENCED_SCORE,
            readability=UNEVIDENCED_SCORE,
            idiomatic=UNEVIDENCED_SCORE,
        ),
        evidence={criterion: [] for criterion in CRITERIA},
        misconceptions=[],
        feedback_for_student=feedback,
        confidence="low",
    )


def grade(mem: Memory, student_id: str, assignment: dict, code_path: str, *,
          profile_snapshot: dict[str, Any] | None = None,
          reference: str | None = None,
          ci_conclusion: str | None = None,
          parent_trace_id: int | None = None,
          conn=None) -> tuple[EchoVerdict, int, list | None]:
    """Judge one submission from its CI conclusion. Returns `(verdict, trace_id, failures)`.

    The signature M4 must preserve. The first four parameters, the names
    `profile_snapshot` and `reference`, and the return triple are D.5's contract; the
    keyword-only narrowing is this file's, and is recorded in the module docstring.
    `code_path`, `reference` and `profile_snapshot` are accepted and unread here.

    `ci_conclusion` and `parent_trace_id` are Echo's own keyword-only inputs, following the
    convention the orchestrator already uses for agent-specific facts (it passes
    `ci_duration=` to the Performance Agent the same way). `parent_trace_id` is the `ci_run`
    trace being judged; passing it is what makes the verdict a child in the causal forest and
    what lets a reader get from a mastery number back to the event that moved it.

    `conn` is an addition to D.5, for the reason `memory.py`'s deviation 2 gives: passing one
    makes the verdict trace and the mastery updates a single transaction, and lets tests roll
    back rather than pollute an append-only log. The orchestrator never passes it, so the
    default preserves D.5's behaviour exactly.

    Raises `ValueError` if `ci_conclusion` is None -- that is a caller who forgot to supply
    the one fact Echo grades on, and it should fail loudly rather than emit a verdict about
    nothing. A conclusion that is present but non-assessing (`cancelled`, `skipped`) is a
    different case, handled in `_verdict_for`.
    """
    if ci_conclusion is None:
        raise ValueError(
            "echo_agent.grade requires ci_conclusion -- it is the only evidence this agent "
            "grades on. Pass the `conclusion` of the raw_workflow_runs row being judged."
        )

    concepts = list(assignment.get("concepts") or [])
    passed = OUTCOME.get(ci_conclusion)
    verdict = _verdict_for(passed)

    payload = {
        **verdict.model_dump(),
        # BUILD_PLAN 2.4's own numbers, kept on their own scale (D-016). None when the run
        # assessed nothing, so a reader can tell "failed" from "never ran".
        "echo_outcome": None if passed is None else ECHO_OUTCOME[passed],
        # Invariant 6, Echo's form of it -- and an OPEN question, see D-018: the citation is
        # the event, not a quote.
        "evidence_source": {"kind": "ci_run", "conclusion": ci_conclusion,
                            "trace_id": parent_trace_id},
        "agent": "echo_v1",
    }

    trace_id = mem.log_trace(
        student_id, ACTOR, "verdict", payload,
        assignment_id=assignment["assignment_id"], concept_ids=concepts,
        parent_trace_id=parent_trace_id, conn=conn,
    )

    # The fast path. Mastery is recomputed from the log, so what moves it is the `ci_run`
    # this verdict points at -- not the verdict itself (Option A). `update_mastery` is
    # idempotent, so calling it here is safe even if BUILD_PLAN 2.2's wiring already did.
    for concept in concepts:
        mem.update_mastery(student_id, concept, parent_trace_id=trace_id, conn=conn)

    return verdict, trace_id, (verdict.evidence_failures or None)
