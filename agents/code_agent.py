"""agents/code_agent.py — M4 task 4.1. The first real judge.

The five-stage agent skeleton from `CLAUDE.md` §8, with the LLM as **one stage in the
middle** rather than the whole thing (`VDEL_Modules_3_9_Build.md` D.1):

    1 TOOLS     ruff / sqlfluff over the submission — free facts, zero variance
    2 ASSEMBLE  task + rubric + tool findings + memory slice + submission -> one prompt
    3 JUDGE     ONE call through system/llm.py at temperature 0   <- the only judgement
    4 VALIDATE  schema (in the gateway) + evidence string-match (here)
    5 COMMIT    verdict trace + fast-path mastery update

Every stage that is not stage 3 replaces an unreliable judgement with a deterministic one.
This agent is stateless; all state is on the blackboard.

**It replaces Echo's internals, not Echo's interface.** `grade()` keeps D.5's contract —
the first four positional parameters, the `profile_snapshot` / `reference` keyword names, and
the `(verdict, trace_id, failures)` return triple — so the orchestrator, the traces, the
mastery updates and the plots keep working untouched. `agents/echo_agent.py`'s docstrings
state that its shapes exist for this swap: `EchoScores` is "D.5's `Scores`, field for field.
M4 replaces the values, not the shape", and its empty `evidence` dict exists "so M4 fills a
slot rather than adding one". `tests/test_code_agent.py` asserts the two signatures agree.

**Deviations from D.5's `grade()`, and why each one is forced rather than chosen:**

1. **`llm.judge()` replaces `llm_call()` plus a hand-rolled retry.** D.5 calls a function
   named `llm_call` that does not exist in this repo, then implements its own one-shot
   corrective retry around it. `system/llm.py` already owns that: `judge()` takes no
   `temperature` parameter at all (invariant 4 enforced by absence, not by a default), and
   performs exactly one corrective retry before raising `SchemaValidationError` (invariant 5,
   D-022). Re-implementing the retry here would put two copies of the invariant in the repo,
   and the second copy is the one that drifts.

2. **No `correct=` / `item_difficulty=` on `update_mastery`.** D.5 calls
   `mem.update_mastery(student_id, concept, correct=..., item_difficulty=...)`. That signature
   does not exist: `memory.update_mastery` takes **no outcome argument, deliberately** (D-007
   — folding a passed-in outcome onto partial state is what lost the Beta posterior and froze
   confidence at 0.286 regardless of n). Evidence comes from the log; the caller logs first
   and calls after. Echo already does it this way and this file matches it exactly.

3. **`task` and `rubric` are not read from the `assignments` table.** D.5 reads
   `assignment["task"]` and `assignment["rubric"]`, but neither is a column — the schema
   (`CLAUDE.md` §6) has only `assignment_id`, `repo_prefix`, `released_at`, `due_at` and
   `concepts[]`. The rubric is a versioned constant in `agents/prompts.py`; the task text is
   passed in the assignment dict by the caller and is required, with a loud error if missing.
   Inventing an `assignments.task` column would be exactly the structure invention
   `CLAUDE.md` §11 names as the failure mode to avoid.

**The open decision this file deliberately does not resolve.** `memory.MASTERY_TRACE_KINDS`
is `frozenset({"ci_run"})`, and `verdict` sits in `NON_MASTERY_KINDS` with a reason written
in anticipation of this milestone: *"M4. An agent verdict IS mastery evidence, but its payload
is a per-criterion 0/2/4 rubric rather than a pass/fail, so the mapping from rubric score to
BKT outcome is a decision that has not been made. Adding it here without that mapping would
silently score every verdict as a failure."* D.5 proposes the mapping (`correctness >= 3`),
and Echo chose 4/0 scores specifically so that threshold reproduces its binary unchanged — so
the pieces line up, but making a verdict move mastery means editing `memory.py`, the only door
(invariant 2), and changing what `rebuild_from_traces` produces, which is the M2 DoD's proof.
That is a shared-contract change and a stop-and-ask, not a side effect of writing this file.
Until it is decided, this agent behaves exactly as Echo does: it calls `update_mastery`, which
recomputes from the `ci_run` traces already in the log, and the verdict itself moves nothing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, conint

from agents import prompts, tools, validation
from memory.memory import Memory
from system import llm

# Same actor Echo writes under, so swapping the internals needs no trace migration and the
# causal forest stays continuous across the change.
ACTOR = "code_agent"

# The criteria and their order. Identical to Echo's and validation's by test, not by import.
CRITERIA = ("correctness", "approach", "readability", "idiomatic")


class Scores(BaseModel):
    """D.5's `Scores`, field for field — the same shape as `EchoScores`.

    Anchored 0/2/4, but typed 0..4 rather than restricted to {0, 2, 4}: a judge that returns
    3 has said something real about the submission, and coercing it to an anchor would hide
    that the anchors are not discriminating. `tests/test_code_agent.py` records off-anchor
    scores as a thing to watch in the benchmark rather than a thing to reject.
    """

    correctness: conint(ge=0, le=4)
    approach: conint(ge=0, le=4)
    readability: conint(ge=0, le=4)
    idiomatic: conint(ge=0, le=4)


class Verdict(BaseModel):
    """D.5's `Verdict` plus `evidence_failures`, matching `EchoVerdict`'s shape exactly.

    Field order matters and is not incidental: `evidence` precedes `scores` so the judge
    commits to what it saw before it commits to a number. `agents/prompts.py` asks for the
    fields in this order for the same reason.
    """

    evidence: dict[str, list[Any]] = Field(default_factory=dict)
    scores: Scores
    misconceptions: list[dict[str, str]] = Field(default_factory=list)
    feedback_for_student: str
    confidence: str
    evidence_failures: list[dict[str, str]] = Field(default_factory=list)


def grade(mem: Memory, student_id: str, assignment: dict, code_path: str, *,
          profile_snapshot: dict[str, Any] | None = None,
          reference: str | None = None,
          parent_trace_id: int | None = None,
          conn=None) -> tuple[Verdict, int, list | None]:
    """Judge one submission. Returns `(verdict, trace_id, evidence_failures or None)`.

    The signature Echo defined and M4 preserves. `conn` exists for the reason `memory.py`'s
    deviation 2 gives: passing one makes the verdict trace and the mastery updates a single
    transaction, and lets tests roll back rather than pollute an append-only log.

    Raises `ValueError` if the assignment carries no `task`, and `FileNotFoundError` if the
    submission is missing — both are callers who forgot to supply the thing being graded, and
    both should fail loudly rather than emit a verdict about nothing. `SchemaValidationError`
    from the gateway propagates: two invalid attempts is a flagged failure, never a silent
    default verdict (invariant 5).
    """
    task = (assignment.get("task") or "").strip()
    if not task:
        raise ValueError(
            "code_agent.grade requires assignment['task'] -- the judge cannot assess whether "
            "code solves a problem it was never shown. There is no assignments.task column; "
            "the caller supplies it (see this module's deviation 3)."
        )

    path = Path(code_path)
    if not path.is_file():
        raise FileNotFoundError(f"submission not found: {code_path}")
    code = path.read_text(encoding="utf-8")

    # ---- 1 TOOLS -------------------------------------------------------------------------
    # Static analysis only. `agents/tools.py` never executes the submission (invariant 12).
    reports = tools.lint_submission(path)
    linter_findings = tools.render_findings(reports, str(path))

    # ---- 2 ASSEMBLE ----------------------------------------------------------------------
    profile = profile_snapshot if profile_snapshot is not None else mem.get_profile(
        student_id, conn=conn
    )
    concepts = list(assignment.get("concepts") or [])
    mastery_slice = {c: (profile.get("mastery") or {}).get(c) for c in concepts}
    weakness_notes = [
        w.get("note") for w in (profile.get("weaknesses") or [])
        if w.get("concept") in concepts and w.get("status") == "open"
    ]

    prompt = prompts.build_grading_prompt(
        task, code,
        linter_findings=linter_findings,
        reference=reference,
        mastery_slice=mastery_slice,
        weakness_notes=weakness_notes,
    )

    # ---- 3 JUDGE -------------------------------------------------------------------------
    # The only judgement stage. Temperature 0 and the single corrective retry are the
    # gateway's job, not this file's -- see deviation 1.
    verdict, record = llm.judge(prompt, Verdict)

    # ---- 4 VALIDATE ----------------------------------------------------------------------
    # Invariant 6, mechanically. A quote that is not in the submission was invented.
    failures = validation.validate_evidence(verdict, code)
    rejected = validation.rejects_verdict(failures)
    verdict = verdict.model_copy(update={"evidence_failures": failures})

    # ---- 5 COMMIT ------------------------------------------------------------------------
    # A rejected verdict is still written. Invariant 5 forbids dropping it silently, and a
    # flagged verdict with its reasons attached is the auditable form -- deleting the record
    # of a judge that fabricated a quote destroys the evidence that it did.
    payload = {
        **verdict.model_dump(),
        "agent": "code_agent_v1",
        "prompt_version": prompts.PROMPT_VERSION,
        "model": record.model,
        "flagged": rejected,
        "tool_reports": [r.to_dict() for r in reports],
        "reference_supplied": reference is not None,
    }

    trace_id = mem.log_trace(
        student_id, ACTOR, "verdict", payload,
        assignment_id=assignment["assignment_id"], concept_ids=concepts,
        parent_trace_id=parent_trace_id, conn=conn,
    )

    # Recomputes from the `ci_run` traces already in the log; the verdict itself moves
    # nothing until the open decision in this module's docstring is made. Idempotent, so
    # calling it is safe whether or not anything changed.
    for concept in concepts:
        mem.update_mastery(student_id, concept, parent_trace_id=trace_id, conn=conn)

    return verdict, trace_id, (failures or None)
