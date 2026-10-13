"""agents/feedback_agent.py -- the Feedback Agent (VDEL_REDESIGN.md C10). Writes to no database.

C10: "A deterministic diagnosis function produces {weakest_concept, attempts_per_stage,
recurrence_flags, failing_tests}; the LLM receives that plus ... and writes only the
explanation." So this agent is the five-stage skeleton (CLAUDE.md §8) with the judgement stage
reduced to wording:

    1 FACTS     assessment/diagnose.py + this commit's test_results (name + exception TYPE only,
                D-077) + the student's mastery slice read through Memory + candidate resources
    2 ASSEMBLE  agents/feedback_prompts.py -- facts, no student code, no hidden test source
    3 JUDGE     ONE call through the gateway (temperature 0, gateway fence stripping and schema
                retry), `FeedbackOutput`
    4 VALIDATE  `validate_output`: every cited test / concept is in the diagnosis, the resource
                is one of the candidates or null, no hidden source line, no statement that the
                code is correct or incorrect, no link, no mastery claim. One corrective retry on
                a rejection; a second rejection falls back to the deterministic v0 text
    5 RENDER    markdown. NOT persisted (see "Persistence")

INVARIANTS HELD
  - Correctness is decided only by executed tests (D-036, invariant 13): the agent is told so and
    its output is rejected if it asserts correctness. The failing-test list in the message is
    built by code from the test results, not written by the model.
  - LLM output never feeds mastery: nothing here reads or writes mastery except a read-only
    profile slice used for tone, and no trace kind that feeds BKT is involved.
  - The LLM never invents a resource: `resource_id` must be one of the candidate ids or null,
    and the title / locator / url shown to the student come from the candidate row, not from
    the model.
  - No hidden test source reaches a student: the existing guard (`scripts.post_feedback`'s
    `hidden_source_lines` / `assert_no_hidden_source`) is imported and applied to every text
    field and to the finished markdown (D-077).

WHAT IS NOT CALLED ON THE LLM (deliberate, tested): a commit whose status is `collection_error`,
`timeout` or `tooling`, and a commit with no failing check. Those get the deterministic v0 text
(plain words, never a mastery claim, not counted as wrong answers). An LLM adds nothing there
except risk, and the budget is not spent.

PERSISTENCE. This module has no database write. `FeedbackResult.to_trace_payload()` builds the
payload a caller could log; who logs it, under which actor/kind, and when, is an integration
request (docs/agents.md IR-3), because `memory/memory.py` belongs to the other branch.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from agents import budget as budget_mod
from agents import feedback_prompts as fp
from agents.resources import ResourceCandidate, select_candidates
from scripts import post_feedback as pf
from system import llm as llm_gateway

AGENT = "feedback_agent_v1"

OK, COLLECTION_ERROR, TIMEOUT, TOOLING = "ok", "collection_error", "timeout", "tooling"

# source of the final markdown
SOURCE_LLM = "llm"
SOURCE_STATUS = "deterministic_status"          # collection_error / timeout / tooling
SOURCE_NO_FAILURES = "deterministic_no_failures"
SOURCE_FALLBACK = "deterministic_v0_fallback"   # the LLM path was tried and rejected / failed

# calls: first judge, plus at most one corrective judge after a semantic rejection
MAX_JUDGE_CALLS = 2


# ---- Input contract -----------------------------------------------------------------------

@dataclass(frozen=True)
class FailedCheck:
    test_name: str                       # the node id, e.g. tests/hidden/test_x.py::test_y
    exception_type: str | None           # the class name only; never a message (D-077)
    gap_id: str | None = None

    @property
    def short_name(self) -> str:
        return self.test_name.rpartition("::")[2]


@dataclass(frozen=True)
class FeedbackInput:
    """Everything the agent may know. Built by `gather_input` (database) or `from_fixture`."""

    attempt_id: int
    commit_sha: str
    student_id: str
    assignment_id: str
    project_id: str | None
    attempt_no: int
    status: str                                   # ok | collection_error | timeout | tooling
    passed: int
    total: int
    failed: tuple[FailedCheck, ...]               # THIS commit's failing checks
    diagnosis_failing: tuple[str, ...]            # diagnose().failing_tests names (attempt level)
    weakest_concept: str | None
    recurring_gaps: tuple[str, ...]
    concepts: tuple[str, ...]                     # concept ids the answer may cite
    mastery: dict = field(default_factory=dict)   # {concept: {"p_mastery", "n"}}, tone only
    candidates: tuple[ResourceCandidate, ...] = ()

    @property
    def citable_tests(self) -> frozenset[str]:
        names = {f.short_name for f in self.failed}
        names |= {n.rpartition("::")[2] for n in self.diagnosis_failing}
        return frozenset(names)

    @classmethod
    def from_fixture(cls, data: dict,
                     candidates: Iterable[ResourceCandidate] = ()) -> FeedbackInput:
        """Build from a `tests/fixtures/agents` JSON (the shape `agents_export_fixtures` writes)."""
        failed = tuple(FailedCheck(c["test_name"], c["exception_type"], c["gap_id"])
                       for c in data["checks"] if not c["passed"])
        diag = data["diagnosis"]
        gap_concepts = data.get("gap_concepts", {})
        concepts: set[str] = set()
        for f in failed:
            concepts.update(gap_concepts.get(f.gap_id or "", ()))
        if diag.get("weakest_concept"):
            concepts.add(diag["weakest_concept"])
        return cls(
            attempt_id=data["attempt_id"], commit_sha=data["commit_sha"],
            student_id=data["student_id"], assignment_id=data["assignment_id"],
            project_id=data.get("project_id"), attempt_no=data["attempt_no"],
            status=data["status"], passed=data["passed"], total=data["total"],
            failed=failed,
            diagnosis_failing=tuple(t["test_name"] for t in diag.get("failing_tests", ())),
            weakest_concept=diag.get("weakest_concept"),
            recurring_gaps=tuple(sorted(g for g, flag in diag.get("recurrence_flags", {}).items()
                                        if flag)),
            concepts=tuple(sorted(concepts)),
            mastery={c: m for c, m in data.get("mastery", {}).items() if c in concepts},
            candidates=tuple(candidates),
        )


# ---- Output contract ----------------------------------------------------------------------

class FeedbackOutput(BaseModel):
    summary: str = Field(min_length=1, max_length=fp.MAX_SUMMARY_CHARS)
    what_to_check_next: list[str] = Field(min_length=1, max_length=fp.MAX_STEPS)
    cited_tests: list[str] = Field(default_factory=list)
    cited_concepts: list[str] = Field(default_factory=list)
    resource_id: str | None = None
    confidence: Literal["high", "medium", "low"]

    @field_validator("what_to_check_next")
    @classmethod
    def _steps_short_and_nonempty(cls, steps: list[str]) -> list[str]:
        for step in steps:
            if not step.strip() or len(step) > fp.MAX_STEP_CHARS:
                raise ValueError(f"each step must be 1..{fp.MAX_STEP_CHARS} characters")
        return steps


@dataclass(frozen=True)
class Rejection:
    rule: str
    detail: str


# ---- Validation ---------------------------------------------------------------------------

# Statements that the code is (in)correct, as a verdict. v1: a short list of patterns, not a
# proof; it is a safety net behind the prompt rule. Describing a check ("the check X failed") is
# fine; judging the code is not.
_NOUN = r"(?:code|solution|function|implementation|answer|program|script|logic|work|file)"
_CORRECTNESS_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    rf"\b(?:your|the|this)\s+{_NOUN}\b[^.!?\n]{{0,30}}?\b(?:is|are|was|looks|seems|appears)\b"
    r"\s+(?:\w+\s+)?(?:correct|incorrect|wrong|right|buggy|broken|flawless|perfect|bug[- ]free)\b",
    rf"\b(?:correct|incorrect|wrong|buggy|flawless|perfect)\s+{_NOUN}\b",
    r"\b(?:works|working|runs)\s+(?:correctly|perfectly|fine)\b",
    r"\b(?:does(?:\s*n\W?t| not)|do(?:\s*n\W?t| not))\s+work\b",
    r"\b(?:has|have|contains?|there(?:'s| is| are))\s+(?:a\s+|an\s+|no\s+|some\s+|the\s+)?"
    r"(?:bug|bugs|error|errors|mistake|mistakes)\b",
    r"\bbug[- ]free\b",
    r"\byou(?:'ve| have)?\s+(?:solved|nailed|got it (?:right|wrong))\b",
)]
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_MASTERY_WORDS = re.compile(r"\bmaster(?:y|ed|ing)?\b", re.IGNORECASE)


def _text_fields(out: FeedbackOutput) -> list[str]:
    return [out.summary, *out.what_to_check_next]


def _normalise_test_ref(ref: str) -> str:
    """`tests/x.py::test_a`, `test_a (test_x.py)` and `test_a` all name the same test."""
    name = ref.strip().rpartition("::")[2]
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()


def validate_output(out: FeedbackOutput, inp: FeedbackInput,
                    hidden: frozenset[str]) -> list[Rejection]:
    """Every reason `out` must not reach a student. Empty list = acceptable. Pure."""
    rejections: list[Rejection] = []

    unknown_tests = sorted({t for t in out.cited_tests
                            if _normalise_test_ref(t) not in inp.citable_tests})
    if unknown_tests:
        rejections.append(Rejection("unknown_test", "cited tests that are not among the failed "
                                    f"checks: {', '.join(unknown_tests)}"))

    unknown_concepts = sorted(set(out.cited_concepts) - set(inp.concepts))
    if unknown_concepts:
        rejections.append(Rejection("unknown_concept", "cited concepts that are not in the "
                                    f"diagnosis: {', '.join(unknown_concepts)}"))

    if out.resource_id is not None and out.resource_id not in {c.resource_id
                                                               for c in inp.candidates}:
        rejections.append(Rejection(
            "unknown_resource", f"resource_id {out.resource_id!r} is not a candidate"
            + (" (there are none: use null)" if not inp.candidates else "")))

    text = "\n".join(_text_fields(out))
    try:
        pf.assert_no_hidden_source(text, hidden)
    except pf.HiddenSourceLeak:
        # No detail on purpose: the offending line is hidden test source and must not be copied
        # into a retry prompt, a log or a trace.
        rejections.append(Rejection("hidden_source", "a line of hidden test code appeared"))

    for pattern in _CORRECTNESS_PATTERNS:
        found = pattern.search(text)
        if found:
            rejections.append(Rejection(
                "correctness_claim", f"do not state that the code is correct or incorrect "
                f"(matched {found.group(0)!r}); only the checks decide"))
            break

    if _URL.search(text):
        rejections.append(Rejection("link_in_text", "do not write links; use resource_id"))

    if _MASTERY_WORDS.search(text):
        rejections.append(Rejection("mastery_claim",
                                    "do not make claims about mastery"))
    return rejections


# ---- Rendering ----------------------------------------------------------------------------

def _model_lines(inp: FeedbackInput, out: FeedbackOutput) -> list[str]:
    """The part of the message that is the model's: summary, next steps, the chosen reading (its
    row comes from the table, not the model) and the AI-written disclaimer."""
    lines = [out.summary.strip(), "", "What to check next:"]
    lines += [f"{i}. {step.strip()}" for i, step in enumerate(out.what_to_check_next, 1)]
    chosen = next((c for c in inp.candidates if c.resource_id == out.resource_id), None)
    if chosen is not None:
        where = f", {chosen.locator}" if chosen.locator else ""
        link = f" {chosen.url}" if chosen.url else ""
        lines += ["", f"Suggested reading: **{chosen.title}**{where}.{link}".rstrip()]
    lines += ["", "_This note was written by an AI assistant from your check results. The "
                  "checks, not this note, decide whether your code is correct._", ""]
    return lines


def render_markdown(inp: FeedbackInput, out: FeedbackOutput) -> str:
    """The message for the student. Facts (counts, the failed-check list, the resource row) are
    written by code from the data; only the summary and the next steps are the model's words."""
    lines = [f"### VDEL feedback: `{inp.assignment_id}`, attempt {inp.attempt_no}, commit "
             f"`{inp.commit_sha[:7]}`", "",
             f"**{inp.passed} of {inp.total}** checks passed.", ""]
    if inp.failed:
        lines.append("Checks that failed on this commit:")
        for f in inp.failed:
            lines.append(f"- `{pf.short_test_name(f.test_name)}`: "
                         f"{f.exception_type or 'check failed'}")
        lines.append("")
    return "\n".join(lines + _model_lines(inp, out))


def render_addendum(inp: FeedbackInput, out: FeedbackOutput) -> str:
    """Only the model's part (no header, no counts, no failed-check list), for posting UNDER the
    deterministic text, which stays the base of the message (IR-3/IR-4, D-099)."""
    return "\n".join(["**More detail** (written by an AI assistant)", "",
                      *_model_lines(inp, out)])


# ---- The run ------------------------------------------------------------------------------

@dataclass
class FeedbackResult:
    markdown: str
    source: str                                   # SOURCE_*
    output: FeedbackOutput | None = None          # the validated object, only when source == llm
    reasons: list[str] = field(default_factory=list)
    rejections: list[list[Rejection]] = field(default_factory=list)   # one list per judge call
    calls_made: int = 0
    judge_calls: int = 0
    status: str = OK
    model: str | None = None
    provider: str | None = None
    input: FeedbackInput | None = None       # the facts this result was built from

    @property
    def used_llm(self) -> bool:
        return self.source == SOURCE_LLM

    # D-108: what `agents.pipeline.persist_feedback` stores under. For v1 these are exactly what
    # that function used before (`fa.AGENT`, `used_llm`), so nothing changes with the flag off;
    # `agents.feedback_v2.FeedbackResultV2` overrides both.
    agent_id = AGENT

    @property
    def storable(self) -> bool:
        return self.used_llm

    def to_trace_payload(self, inp: FeedbackInput | None = None) -> dict[str, Any]:
        """What a caller would log (IR-3). Pure: builds a dict, writes nothing. Contains the
        validated output, never raw model text and never hidden source. `inp` defaults to the
        input the result was built from."""
        inp = inp or self.input
        if inp is None:
            raise ValueError("no FeedbackInput: pass one")
        return {
            "agent": AGENT, "prompt_version": fp.FEEDBACK_PROMPT_VERSION,
            "attempt_id": inp.attempt_id, "commit_sha": inp.commit_sha, "status": self.status,
            "source": self.source, "output": self.output.model_dump() if self.output else None,
            "reasons": list(self.reasons),
            "rejected_rules": [[r.rule for r in batch] for batch in self.rejections],
            "judge_calls": self.judge_calls, "provider_calls": self.calls_made,
            "model": self.model, "provider": self.provider,
        }


def run_feedback_agent(inp: FeedbackInput, llm: Any, budget: budget_mod.CallBudget | None, *,
                       hidden: frozenset[str],
                       fallback_markdown: Callable[[], str]) -> FeedbackResult:
    """The agent without a database. `llm` is any object with `system.llm.judge`'s signature
    (`system.llm` itself, or `agents.fake_llm.FakeLLM`). Never raises for an LLM-side problem:
    every such problem ends in the deterministic text, with the reason recorded."""
    if inp.status != OK:
        return FeedbackResult(fallback_markdown(), SOURCE_STATUS, status=inp.status, input=inp,
                              reasons=[f"status {inp.status}: plain-words explanation, no LLM"])
    if not inp.failed:
        return FeedbackResult(fallback_markdown(), SOURCE_NO_FAILURES, status=inp.status,
                              input=inp,
                              reasons=["no failing check: nothing to explain, no LLM"])

    result = FeedbackResult("", SOURCE_FALLBACK, status=inp.status, input=inp)
    prompt = fp.build_feedback_prompt(inp)
    last: list[Rejection] = []

    for attempt in range(1, MAX_JUDGE_CALLS + 1):
        sent = prompt if attempt == 1 else prompt + fp.corrective_note(last)
        if budget is not None:
            try:
                budget.charge(budget_mod.WORST_CASE_CALLS_PER_JUDGE, what="Feedback Agent")
            except budget_mod.BudgetExceeded as exc:
                result.reasons.append(f"budget_exceeded: {exc.cap} cap {exc.limit}")
                break
        try:
            out, record = llm.judge(sent, FeedbackOutput)
        except llm_gateway.SchemaValidationError as exc:
            result.judge_calls += 1
            if budget is not None:
                result.calls_made += budget.settle(budget_mod.WORST_CASE_CALLS_PER_JUDGE,
                                                   exc.records)
            result.reasons.append("schema_invalid_after_gateway_retry")
            break
        except Exception as exc:  # noqa: BLE001 -- a provider failure must not lose the feedback
            result.judge_calls += 1
            if budget is not None:
                budget.settle_unknown(budget_mod.WORST_CASE_CALLS_PER_JUDGE)
            result.reasons.append(f"provider_error: {type(exc).__name__}")
            break
        result.judge_calls += 1
        if budget is not None:
            result.calls_made += budget.settle(budget_mod.WORST_CASE_CALLS_PER_JUDGE, [record])
        result.model, result.provider = record.model, record.provider

        out = out.model_copy(update={
            "cited_tests": [_normalise_test_ref(t) for t in out.cited_tests]})
        last = validate_output(out, inp, hidden)
        result.rejections.append(last)
        if not last:
            markdown = render_markdown(inp, out)
            try:
                pf.assert_no_hidden_source(markdown, hidden)
            except pf.HiddenSourceLeak:
                result.reasons.append("hidden_source_in_rendered_markdown")
                break
            result.markdown = pf.redact(markdown, hidden)
            result.output = out
            result.source = SOURCE_LLM
            return result
        result.reasons.append("rejected: " + ", ".join(r.rule for r in last))

    result.markdown = fallback_markdown()
    result.source = SOURCE_FALLBACK
    return result


# ---- Database glue ------------------------------------------------------------------------

def gather_input(cur, attempt_id: int, commit_sha: str, *, memory: Any = None,
                 profile: dict | None = None,
                 candidates: Sequence[ResourceCandidate] | None = None) -> FeedbackInput:
    """Read-only: SELECTs through `cur`, `assessment.diagnose`, and the student's profile through
    Memory (`get_profile`, joined to `cur`'s transaction, never committing anything).

    `profile` bypasses Memory (tests). `candidates=None` selects them with
    `agents.resources.select_candidates` for the weakest concept; pass `[]` for none.
    """
    from assessment.diagnose import diagnose

    if pf.is_template_commit(cur, commit_sha):                       # D-098
        raise pf.TemplateCommit(f"commit {commit_sha[:10]} is the template push: no feedback")
    cur.execute("SELECT student_id, assignment_id, project_id, attempt_no FROM attempts"
                " WHERE attempt_id = %s", (attempt_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no attempt {attempt_id}")
    student_id, assignment_id, project_id, attempt_no = row

    cur.execute("SELECT test_name, passed, message, gap_id, status FROM test_results"
                " WHERE attempt_id = %s AND commit_sha = %s ORDER BY test_name",
                (attempt_id, commit_sha))
    rows = cur.fetchall()
    if not rows:
        raise ValueError(f"commit {commit_sha[:10]} has no graded results for attempt "
                         f"{attempt_id}")
    statuses = {r[4] for r in rows}
    status = (TOOLING if statuses == {"tooling"}
              else COLLECTION_ERROR if COLLECTION_ERROR in statuses
              else TIMEOUT if TIMEOUT in statuses else OK)
    checks = [r for r in rows if r[4] != "tooling"]
    # The assertion message is read ONLY to get the exception class, then dropped (D-077).
    failed = tuple(FailedCheck(name, pf.exception_type(message), gap)
                   for name, passed, message, gap, _ in checks if not passed)

    diag = diagnose(cur, attempt_id)
    gap_ids = sorted({f.gap_id for f in failed if f.gap_id} | set(diag.recurrence_flags))
    gap_concepts: dict[str, list[str]] = {}
    if gap_ids:
        cur.execute("SELECT gap_id, concept_ids FROM gaps WHERE gap_id = ANY(%s)", (gap_ids,))
        gap_concepts = {g: list(c) for g, c in cur.fetchall()}
    concepts = {c for f in failed for c in gap_concepts.get(f.gap_id or "", ())}
    if diag.weakest_concept:
        concepts.add(diag.weakest_concept)

    if profile is None:
        if memory is None:
            from memory.memory import Memory
            memory = Memory()
        profile = memory.get_profile(student_id, conn=cur.connection)
    mastery = {c: {"p_mastery": m.get("p_mastery"), "n": m.get("n")}
               for c, m in (profile.get("mastery") or {}).items() if c in concepts}

    if candidates is None:
        candidates = (select_candidates(cur, diag.weakest_concept)
                      if diag.weakest_concept else [])

    return FeedbackInput(
        attempt_id=attempt_id, commit_sha=commit_sha, student_id=student_id,
        assignment_id=assignment_id, project_id=project_id, attempt_no=attempt_no,
        status=status, passed=sum(1 for r in checks if r[1]), total=len(checks),
        failed=failed, diagnosis_failing=tuple(f.test_name for f in diag.failing_tests),
        weakest_concept=diag.weakest_concept,
        recurring_gaps=tuple(sorted(g for g, flag in diag.recurrence_flags.items() if flag)),
        concepts=tuple(sorted(concepts)), mastery=mastery, candidates=tuple(candidates),
    )


def build_feedback_with_llm(cur, attempt_id: int, commit_sha: str, llm: Any,
                            budget: budget_mod.CallBudget | None, *, memory: Any = None,
                            profile: dict | None = None,
                            candidates: Sequence[ResourceCandidate] | None = None
                            ) -> FeedbackResult:
    """The entry point: one graded commit -> `FeedbackResult` (validated object + markdown).

    NO database write by default or otherwise: `cur` is used for SELECTs only and nothing is
    committed. The caller owns persistence (IR-3). The fallback is `scripts.post_feedback.
    build_feedback`, imported and untouched.
    """
    inp = gather_input(cur, attempt_id, commit_sha, memory=memory, profile=profile,
                       candidates=candidates)
    hidden = pf.hidden_source_lines(inp.project_id) if inp.project_id else frozenset()
    return run_feedback_agent(
        inp, llm, budget, hidden=hidden,
        fallback_markdown=lambda: pf.build_feedback(cur, attempt_id, commit_sha).markdown)
