"""agents/pipeline.py -- the agents entry point for one graded commit (`run_cycle --with-llm`).

    run_agents_for_commit(student_id, attempt_id, commit_sha, *, llm, budget, persist=False)

Runs the Code Agent and then the Feedback Agent, in that fixed order, on one commit that the
deterministic pipeline has already graded (test_results exist). Each agent runs inside its own
try/except: one failing never stops the other, and every outcome (ok / skipped / failed, with
the reason) is returned in a `PipelineSummary`. It is NOT the M6 orchestrator (no snapshot rule,
no Reviewer, no aggregation): it is the smallest honest wrapper that lets the main branch wire
`--with-llm` later (docs/agents.md, IR-4).

WRITES NOTHING. `persist=False` is the only implemented mode:
  - the Code Agent is given a `DryRunMemory`: profile reads go through, but `log_trace` and
    `update_mastery` only record what would have been written (in `summary.dry_run_traces`);
  - the Feedback Agent already writes nothing;
  - the database session this module opens itself is read-only at the Postgres level.
`persist=True` raises `IntegrationPending` before anything runs and before any LLM call.
Persistence is a separate step the CALLER takes after the run (D-099): `persist_feedback` below
logs the Feedback Agent's LLM answer through `Memory.log_trace` inside the caller's transaction;
`find_feedback_addendum` reads it back. `run_agents_for_commit` itself still writes nothing.

INPUTS THE CALLER MUST SUPPLY for the Code Agent: `code_path` (the student's file as of
`commit_sha`) and `assignment` (a dict with `assignment_id`, `task`, `concepts`). The task text is
not stored in the database (see code_agent.py, deviation 3) and the checkout of a graded commit
is temporary in `scripts/grade_collected.py`. If either is missing the Code Agent step is
`skipped` with that reason, and the Feedback Agent (which needs neither) still runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents import budget as budget_mod
from agents import code_agent
from agents import feedback_agent as fa
from config import judging as judging_config
from scripts import post_feedback as pf
from system import db

CODE_AGENT, FEEDBACK_AGENT = "code_agent", "feedback_agent"
ORDER = (CODE_AGENT, FEEDBACK_AGENT)           # fixed

OK, SKIPPED, FAILED = "ok", "skipped", "failed"


class IntegrationPending(RuntimeError):
    """`persist=True` was requested. Persistence is wired by the main branch, not here."""


@dataclass
class StepResult:
    name: str
    status: str                                 # ok | skipped | failed
    detail: str = ""
    error: str | None = None                    # "ExceptionType: message" when failed
    result: Any = None                          # Verdict triple / FeedbackResult
    provider_calls: int = 0


@dataclass
class PipelineSummary:
    student_id: str
    attempt_id: int
    commit_sha: str
    persisted: bool = False
    steps: dict[str, StepResult] = field(default_factory=dict)
    dry_run_traces: list[dict] = field(default_factory=list)
    budget: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(s.status != FAILED for s in self.steps.values())

    @property
    def feedback_markdown(self) -> str | None:
        step = self.steps.get(FEEDBACK_AGENT)
        return step.result.markdown if step and step.status == OK else None

    def to_dict(self) -> dict:
        return {
            "student_id": self.student_id, "attempt_id": self.attempt_id,
            "commit_sha": self.commit_sha, "persisted": self.persisted, "ok": self.ok,
            "steps": {n: {"status": s.status, "detail": s.detail, "error": s.error,
                          "provider_calls": s.provider_calls}
                      for n, s in self.steps.items()},
            "budget": self.budget,
        }


class DryRunMemory:
    """Stands in for `Memory` when `persist=False`: reads delegate, writes are recorded only."""

    def __init__(self, real: Any, sink: list[dict], conn: Any = None) -> None:
        self._real, self._sink, self._conn = real, sink, conn

    def get_profile(self, student_id: str, *, conn: Any = None) -> dict:
        return self._real.get_profile(student_id, conn=conn or self._conn)

    def log_trace(self, student_id: str, actor: str, kind: str, payload: dict, **kw: Any) -> int:
        self._sink.append({"student_id": student_id, "actor": actor, "kind": kind,
                           "payload": payload, **{k: v for k, v in kw.items() if k != "conn"}})
        return -len(self._sink)                 # a negative id can never be mistaken for a real one

    def update_mastery(self, student_id: str, concept: str, **kw: Any) -> None:
        self._sink.append({"student_id": student_id, "would": "update_mastery",
                           "concept": concept})


def persist_feedback(mem: Any, cur: Any, student_id: str, assignment_id: str | None,
                     result: fa.FeedbackResult) -> int | None:
    """Log the Feedback Agent's LLM answer as ONE `coach`/`intervention` trace (IR-3, D-099).

    Returns the new `trace_id`, or None when nothing was written: the answer did not come from the
    LLM (the deterministic text is reproducible, so it needs no row), or a row for this
    (attempt, commit) already exists. `intervention` is in `NON_MASTERY_KINDS`: this row can never
    feed BKT. The write goes through `mem.log_trace` on `cur`'s connection, inside the caller's
    transaction (no SQL INSERT here, no commit; invariant 2). The payload also carries
    `addendum_markdown`, the model-only paragraph the hourly phase may post under the
    deterministic text; it is stored already redacted and checked against the hidden tests."""
    if not result.used_llm or result.input is None:
        return None
    inp = result.input
    cur.execute("SELECT 1 FROM traces WHERE actor = 'coach' AND kind = 'intervention'"
                " AND payload->>'agent' = %s AND payload->>'commit_sha' = %s"
                " AND (payload->>'attempt_id')::bigint = %s", (fa.AGENT, inp.commit_sha,
                                                              inp.attempt_id))
    if cur.fetchone() is not None:
        return None
    payload = result.to_trace_payload()
    payload["addendum_markdown"] = checked_addendum(inp, result.output)
    return mem.log_trace(student_id, "coach", "intervention", payload,
                         assignment_id=assignment_id, concept_ids=list(inp.concepts),
                         conn=cur.connection)


def checked_addendum(inp: fa.FeedbackInput, out: fa.FeedbackOutput | None) -> str | None:
    """The model-only paragraph, redacted, or None if it cannot be shown safely."""
    if out is None:
        return None
    hidden = pf.hidden_source_lines(inp.project_id) if inp.project_id else frozenset()
    text = pf.redact(fa.render_addendum(inp, out), hidden)
    try:
        pf.assert_no_hidden_source(text, hidden)
    except pf.HiddenSourceLeak:
        return None
    return text


def find_feedback_addendum(cur: Any, attempt_id: int, commit_sha: str) -> str | None:
    """The stored LLM paragraph for one (attempt, commit), or None. Read-only."""
    cur.execute("SELECT payload->>'addendum_markdown' FROM traces"
                " WHERE actor = 'coach' AND kind = 'intervention'"
                " AND payload->>'agent' = %s AND payload->>'commit_sha' = %s"
                " AND (payload->>'attempt_id')::bigint = %s AND payload->>'source' = %s"
                " ORDER BY trace_id DESC LIMIT 1",
                (fa.AGENT, commit_sha, attempt_id, fa.SOURCE_LLM))
    row = cur.fetchone()
    return row[0] if row and row[0] else None


def load_assignment_inputs(cur: Any, assignment_id: str) -> tuple[dict, str | None]:
    """`(assignment dict, file_path)` for the Code Agent, read from the database the way
    `scripts/demo.py` Beat 6 does: the task text is the gaps' instructions in `gap_id` order
    (there is no `assignments.task` column), the concepts are `assignments.concepts`, and
    `file_path` is where the student's file lives inside the repo, and `criteria` come from
    `config/judging.yaml`. Read-only."""
    cur.execute("SELECT concepts, file_path FROM assignments WHERE assignment_id = %s",
                (assignment_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no assignment {assignment_id!r}")
    concepts, file_path = row
    # FILE order (line_start), not alphabetical gap_id (D-103): in extract.py the retry loop comes
    # first and the parse second, and `g_ext_parse` sorts before `g_ext_retry`.
    cur.execute("SELECT instruction FROM gaps WHERE assignment_id = %s ORDER BY line_start, gap_id",
                (assignment_id,))
    judging = judging_config.for_assignment(assignment_id)
    task = judging_config.compose_task(judging.statement, [r[0] for r in cur.fetchall()])
    assignment = {"assignment_id": assignment_id, "task": task, "concepts": list(concepts or []),
                  "criteria": list(judging.criteria)}
    return assignment, file_path


def _calls_since(budget: budget_mod.CallBudget | None, before: int) -> int:
    return 0 if budget is None else max(0, budget.used - before)


def _run_code_agent(summary, cur, *, llm, budget, code_path, assignment, reference, memory,
                    persist_verdict=False, scope=None, checkout_root=None):
    step = StepResult(CODE_AGENT, SKIPPED)
    summary.steps[CODE_AGENT] = step
    if not code_path or not assignment or not (assignment.get("task") or "").strip():
        step.detail = ("skipped: needs code_path and assignment['task'] from the caller "
                       "(not stored in the database)")
        return
    before = budget.used if budget is not None else 0
    try:
        # Persisting goes through the real Memory, in the caller's transaction, one trace per
        # (attempt, commit) (D-103). Otherwise the writes are only recorded in the summary.
        extra = {}
        if persist_verdict:
            mem = memory
            extra = {"attempt_id": summary.attempt_id, "commit_sha": summary.commit_sha,
                     "conn": cur.connection}
        else:
            mem = DryRunMemory(memory, summary.dry_run_traces, getattr(cur, "connection", None))
        verdict, trace_id, failures = code_agent.grade(
            mem, summary.student_id, assignment, str(code_path),
            reference=reference, llm_client=llm, budget=budget, scope=scope,
            checkout_root=checkout_root, **extra)
        step.status, step.result = OK, (verdict, failures)
        # The score itself is research-only data and is not read here (D-103).
        step.detail = (f"evidence failures: {len(failures or [])}; "
                       f"{'stored as trace ' + str(trace_id) if persist_verdict else 'not stored'}")
    except code_agent.SubmissionSkipped as exc:
        step.status, step.detail = SKIPPED, f"skipped: {exc}"
    except Exception as exc:  # noqa: BLE001 -- isolation: the other agent must still run
        step.status, step.error = FAILED, f"{type(exc).__name__}: {str(exc).strip()[:300]}"
    step.provider_calls = _calls_since(budget, before)


def _run_feedback_agent(summary, cur, *, llm, budget, memory):
    step = StepResult(FEEDBACK_AGENT, SKIPPED)
    summary.steps[FEEDBACK_AGENT] = step
    before = budget.used if budget is not None else 0
    try:
        result = fa.build_feedback_with_llm(
            cur, summary.attempt_id, summary.commit_sha, llm, budget, memory=memory)
        step.status, step.result = OK, result
        step.detail = f"source={result.source}" + (
            f"; {'; '.join(result.reasons)}" if result.reasons else "")
    except Exception as exc:  # noqa: BLE001 -- isolation
        step.status, step.error = FAILED, f"{type(exc).__name__}: {str(exc).strip()[:300]}"
    step.provider_calls = _calls_since(budget, before)


def run_agents_for_commit(student_id: str, attempt_id: int, commit_sha: str, *, llm: Any,
                          budget: budget_mod.CallBudget | None, persist: bool = False,
                          cur: Any = None, memory: Any = None, code_path: Any = None,
                          assignment: dict | None = None,
                          reference: str | None = None,
                          persist_code_verdict: bool = False,
                          scope: Any = None,
                          checkout_root: Any = None) -> PipelineSummary:
    """See the module docstring. `cur` (optional) is an existing cursor to read through (tests,
    or a caller already inside a transaction); without it a read-only session is opened and
    closed here. `llm` is `system.llm` or any object with its `judge` signature."""
    if persist:
        raise IntegrationPending(
            "persist=True is not implemented on the agents branch: which trace kind is written, "
            "and in which transaction, is decided when the main branch wires it "
            "(docs/agents.md, IR-3 and IR-4). Nothing was run and no LLM call was made.")

    if memory is None:
        from memory.memory import Memory
        memory = Memory()
    summary = PipelineSummary(student_id, attempt_id, commit_sha)

    if persist_code_verdict and cur is None:
        raise ValueError("persist_code_verdict needs the caller's cursor: the verdict is written "
                         "in the caller's transaction (a read-only session cannot)")
    owned = None
    try:
        if cur is None:
            owned = db._open()
            owned.set_session(readonly=True)         # Postgres itself refuses any write
            cur = owned.cursor()
        _run_code_agent(summary, cur, llm=llm, budget=budget, code_path=code_path,
                        assignment=assignment, reference=reference, memory=memory,
                        persist_verdict=persist_code_verdict, scope=scope,
                        checkout_root=checkout_root)
        _run_feedback_agent(summary, cur, llm=llm, budget=budget, memory=memory)
    finally:
        if owned is not None:
            owned.rollback()
            owned.close()
        if budget is not None:
            summary.budget = budget.summary()
    return summary
