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
is `frozenset({"ci_run", "test_result"})` (memory.py:150) -- executed outcomes only -- and
`verdict` sits in `NON_MASTERY_KINDS` (memory.py:158-161) with a reason written in
anticipation of this milestone: *"M4. An agent verdict IS mastery evidence, but its payload
is a per-criterion 0/2/4 rubric rather than a pass/fail, so the mapping from rubric score to
BKT outcome is a decision that has not been made. Adding it here without that mapping would
silently score every verdict as a failure."* D.5 proposes the mapping (`correctness >= 3`),
and Echo chose 4/0 scores specifically so that threshold reproduces its binary unchanged --
but that mapping is NOT implemented, and since D-036 / invariant 13 the rubric's
`correctness` is the model's reading of the code, never an executed result. Making a verdict
move mastery means editing `memory.py`, the only door (invariant 2), and changing what
`rebuild_from_traces` produces, which is the M2 DoD's proof. That is a shared-contract change
and a stop-and-ask (D-061), not a side effect of writing this file. Until it is decided,
this agent calls `update_mastery`, which recomputes from the `ci_run` and `test_result`
traces already in the log, and the verdict itself moves nothing.

**D-103 hardening (prompt v3), the contract unchanged for existing callers.** `grade()` gained
keyword-only options, all off by default, so `scripts/demo.py` and the benchmarks call it exactly as
before:

* `criteria` / `rubric_table` -- judge a SUBSET of the four criteria (config/judging.yaml, for
  `weather_etl`: no "Idiomatic Spark/SQL"); the schema the gateway enforces, the prompt, the
  evidence rule and the stored `criteria` all follow it. A dropped criterion is stored as null.
* `scope` -- judge only the lines the student wrote inside the gaps plus a little context
  (`agents/scope.py`); BEFORE this the whole file went into the prompt. If the lines cannot be
  extracted the call is skipped (`SubmissionSkipped`) with the reason, never widened to the file.
* `attempt_id` + `commit_sha` (+ `conn`) -- the verdict is stored with them and ONE trace is kept
per
  pair: a second call finds the first and returns it without a provider call.
* `checkout_root` -- the checkout the file must stay inside (no symlink, no path outside it).

What is stored (payload): `attempt_id`, `commit_sha`, `submission_sha256` (a hash of the file, not
the file), `criteria`, `scope`, `prompt_version`, `provider`, `model`, `rejected`, `flagged`, the
scores, the evidence quotes (excerpts, never the whole text), the tool reports. `rejected` is true
when ANY evidence failure was found; `flagged` keeps the older meaning (a fabricated quote). Nothing
reads a verdict yet except the benchmark and the demo, and `scores.llm_correctness_opinion` is
research-only: tests keep it that way.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, Field, conint, create_model

from agents import budget as budget_mod
from agents import prompts, tools, validation
from agents import scope as scope_mod
from assessment.scope_check import filter_lint_findings
from memory.memory import Memory
from system import llm

# Same actor Echo writes under, so swapping the internals needs no trace migration and the
# causal forest stays continuous across the change.
ACTOR = "code_agent"
AGENT_ID = "code_agent_v3"

# The criteria and their order. Identical to Echo's and validation's by test, not by import.
CRITERIA = ("correctness", "approach", "readability", "idiomatic")

_Score = conint(ge=0, le=4)
_CORRECTNESS_ALIASES = AliasChoices("llm_correctness_opinion", "correctness")


class SubmissionSkipped(ValueError):
    """The file is not judged, and the message says why: refused by `tools.vet_source` (link,
    outside the checkout, too big), not valid UTF-8, or its gap lines cannot be extracted. Not an
    error of the
    system: the caller records the reason and moves on."""


class Scores(BaseModel):
    """D.5's `Scores`, the same four criteria as `EchoScores`, one field renamed (prompt v2).

    `llm_correctness_opinion` is the model's READING of the code. It is not a test result: since
    D-036 / invariant 13 correctness is decided only by executed hidden tests, so the field is
    named for what it is and no reader can mistake it for ground truth. It is RESEARCH-ONLY data
    (D-103): stored with the verdict, read by the benchmark and the demo, by nothing else. Old
    traces were written with the key `correctness`; reading accepts both (`validation_alias`), and
    `correctness` stays available as a read-only property for code that still uses the attribute.
    Writing always uses the new key.

    Anchored 0/2/4, but typed 0..4 rather than restricted to {0, 2, 4}: a judge that returns
    3 has said something real about the submission, and coercing it to an anchor would hide
    that the anchors are not discriminating. `tests/test_code_agent.py` records off-anchor
    scores as a thing to watch in the benchmark rather than a thing to reject.

    Every field may be null here, because an assignment can be judged on a subset of the criteria
    and a dropped one is stored as null. What the JUDGE must return is stricter:
    `verdict_model(criteria)` makes exactly the asked criteria required, and that is the schema the
    gateway validates against.
    """

    llm_correctness_opinion: _Score | None = Field(
        default=None, validation_alias=_CORRECTNESS_ALIASES)
    approach: _Score | None = None
    readability: _Score | None = None
    idiomatic: _Score | None = None

    @property
    def correctness(self) -> int | None:
        """Read-only alias of `llm_correctness_opinion`. Still an opinion, not a result."""
        return self.llm_correctness_opinion


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


_VERDICT_MODELS: dict[tuple[str, ...], type[Verdict]] = {}


def resolve_criteria(criteria, assignment: dict | None = None) -> tuple[str, ...]:
    """The criteria to judge, in canonical order: the argument, else `assignment["criteria"]`, else
    all four. Raises `ValueError` for an empty list or an unknown name."""
    raw = criteria if criteria is not None else (assignment or {}).get("criteria")
    if raw is None:
        return CRITERIA
    raw = tuple(raw)
    unknown = [c for c in raw if c not in CRITERIA]
    if unknown or not raw:
        raise ValueError(
            f"criteria must be a non-empty subset of {list(CRITERIA)}, got {list(raw)}")
    return tuple(c for c in CRITERIA if c in raw)


def verdict_model(criteria=CRITERIA) -> type[Verdict]:
    """The schema the gateway validates the judge's reply against: a `Verdict` whose `scores`
    REQUIRE
    exactly these criteria. For all four it is as strict as the old `Verdict` was."""
    used = tuple(c for c in CRITERIA if c in criteria)
    if used not in _VERDICT_MODELS:
        fields: dict[str, Any] = {}
        for criterion in used:
            if criterion == "correctness":
                fields["llm_correctness_opinion"] = (
                    _Score, Field(validation_alias=_CORRECTNESS_ALIASES))
            else:
                fields[criterion] = (_Score, ...)
        scores = create_model("Scores", __base__=Scores, **fields)
        name = "Verdict" if used == CRITERIA else "Verdict[" + "+".join(used) + "]"
        _VERDICT_MODELS[used] = create_model(name, __base__=Verdict, scores=(scores, ...))
    return _VERDICT_MODELS[used]


def _validate(verdict: Verdict, matchable: str, used: tuple[str, ...]) -> list[dict[str, str]]:
    """Evidence failures. A quote counts if it is in the text the judge was shown, either as the
    student wrote it or as the prompt showed it with marker sequences escaped (`[LT3]`), so a file
    that contains `<<<` can still be quoted."""
    failures = validation.validate_evidence(verdict, matchable, used)
    shown = prompts.escape_markers(matchable)
    if shown == matchable or not failures:
        return failures
    still = {(f["kind"], f["criterion"], f.get("unmatched_quote", ""))
             for f in validation.validate_evidence(verdict, shown, used)}
    return [f for f in failures
            if (f["kind"], f["criterion"], f.get("unmatched_quote", "")) in still]


def find_verdict(conn, attempt_id: int, commit_sha: str) -> tuple[Verdict, int] | None:
    """The verdict already stored for this (attempt, commit), or None. Read-only."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT trace_id, payload FROM traces WHERE actor = %s AND kind = 'verdict'"
            " AND payload->>'attempt_id' = %s AND payload->>'commit_sha' = %s"
            " ORDER BY trace_id LIMIT 1", (ACTOR, str(attempt_id), commit_sha))
        row = cur.fetchone()
    if row is None:
        return None
    trace_id, payload = row
    return Verdict.model_validate(payload), trace_id


def grade(mem: Memory, student_id: str, assignment: dict, code_path: str, *,
          profile_snapshot: dict[str, Any] | None = None,
          reference: str | None = None,
          parent_trace_id: int | None = None,
          conn=None,
          llm_client=None,
          budget: budget_mod.CallBudget | None = None,
          use_cache: bool = True,
          criteria=None,
          rubric_table: str | None = None,
          scope: scope_mod.ScopeSpec | None = None,
          attempt_id: int | None = None,
          commit_sha: str | None = None,
          checkout_root: str | Path | None = None,
          max_prompt_chars: int | None = None) -> tuple[Verdict, int, list | None]:
    """Judge one submission. Returns `(verdict, trace_id, evidence_failures or None)`.

    The signature Echo defined and M4 preserves. `conn` exists for the reason `memory.py`'s
    deviation 2 gives: passing one makes the verdict trace and the mastery updates a single
    transaction, and lets tests roll back rather than pollute an append-only log.

    `llm_client` (default: `system.llm`) is any object with `system.llm.judge`'s signature; tests
    pass `agents.fake_llm.FakeLLM`. `budget` (default: none) is an `agents.budget.CallBudget`:
    the call is reserved before it is made and `BudgetExceeded` is raised, with no provider
    reached, if it does not fit. `use_cache=False` is for the benchmark (llm.py: with the cache
    on, a re-run replays stored strings and "stability" would measure a dict). All of these are
    keyword-only additions; the D.5 contract (first four positionals, `profile_snapshot`,
    `reference`, the return triple) is unchanged.

    The D-103 options (module docstring): `criteria` (else `assignment["criteria"]`, else all
    four), `rubric_table` (else `assignment["rubric"]`, else built from the criteria), `scope`,
    `attempt_id` + `commit_sha` (both or neither; they need `conn`), `checkout_root` and
    `max_prompt_chars` (D-104: skip, with the reason, when the text that would go into the prompt
    -- the judged lines plus context, or the whole file -- is longer than this).

    Raises `ValueError` if the assignment carries no `task`, `FileNotFoundError` if the submission
    is missing -- both are callers who forgot to supply the thing being graded, and both should fail
    loudly rather than emit a verdict about nothing -- and `SubmissionSkipped(reason)` when the file
    is refused or its gap lines cannot be extracted. `SchemaValidationError` from the gateway
    propagates: two invalid attempts is a flagged failure, never a silent default verdict
    (invariant 5).
    """
    task = (assignment.get("task") or "").strip()
    if not task:
        raise ValueError(
            "code_agent.grade requires assignment['task'] -- the judge cannot assess whether "
            "code solves a problem it was never shown. There is no assignments.task column; "
            "the caller supplies it (see this module's deviation 3)."
        )
    used = resolve_criteria(criteria, assignment)
    if rubric_table is None:
        rubric_table = assignment.get("rubric") or None
    persisting = attempt_id is not None or commit_sha is not None
    if persisting and (attempt_id is None or commit_sha is None or conn is None):
        raise ValueError("attempt_id, commit_sha and conn go together: one verdict is kept per "
                         "(attempt, commit) and the check for an existing one needs the connection")

    if not Path(code_path).exists():
        raise FileNotFoundError(f"submission not found: {code_path}")
    try:
        resolved = tools.vet_source(code_path, checkout_root)
        code = resolved.read_text(encoding="utf-8")
    except tools.SourceRefused as exc:
        raise SubmissionSkipped(str(exc)) from None
    except UnicodeDecodeError:
        raise SubmissionSkipped("the file is not valid UTF-8") from None
    submission_sha256 = hashlib.sha256(code.encode("utf-8")).hexdigest()

    # ---- idempotence: one verdict per (attempt, commit), no second provider call ---------------
    if persisting:
        existing = find_verdict(conn, attempt_id, commit_sha)
        if existing is not None:
            stored, stored_id = existing
            return stored, stored_id, (stored.evidence_failures or None)

    # ---- 0 SCOPE: which lines are judged --------------------------------------------------------
    excerpt = None
    if scope is not None:
        try:
            excerpt = scope_mod.judged_excerpt(scope, code)
        except scope_mod.ScopeUnavailable as exc:
            raise SubmissionSkipped(f"gap lines cannot be extracted: {exc}") from None
    shown = excerpt.text if excerpt is not None else code
    matchable = excerpt.matchable if excerpt is not None else code
    if max_prompt_chars is not None and len(shown) > max_prompt_chars:
        raise SubmissionSkipped(
            f"the judged text is {len(shown)} characters, above the cap of {max_prompt_chars}")

    # ---- 1 TOOLS -------------------------------------------------------------------------------
    # Static analysis only, on a private copy, isolated from every config file (agents/tools.py).
    reports = tools.lint_submission(code_path, root=checkout_root)
    if excerpt is not None:
        reports = [
            replace(r, findings=filter_lint_findings(r.findings, excerpt.gap_ranges),
                    detail="findings limited to the lines the student wrote inside the gaps")
            if r.ran else r
            for r in reports
        ]
    linter_findings = tools.render_findings(reports, str(code_path))

    # ---- 2 ASSEMBLE ----------------------------------------------------------------------------
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
        task, shown,
        rubric_table=rubric_table,
        criteria=used,
        scope_note=excerpt.note if excerpt is not None else None,
        linter_findings=linter_findings,
        reference=reference,
        mastery_slice=mastery_slice,
        weakness_notes=weakness_notes,
    )

    # ---- 3 JUDGE -------------------------------------------------------------------------------
    # The only judgement stage. Temperature 0 and the single corrective retry are the
    # gateway's job, not this file's -- see deviation 1.
    client = llm_client if llm_client is not None else llm
    if budget is not None:
        budget.charge(budget_mod.WORST_CASE_CALLS_PER_JUDGE, what="Code Agent judge call")
    try:
        verdict, record = client.judge(prompt, verdict_model(used), use_cache=use_cache)
    except llm.SchemaValidationError as err:
        if budget is not None:
            budget.settle(budget_mod.WORST_CASE_CALLS_PER_JUDGE, err.records)
        raise
    except Exception:
        # A provider or transport failure: how many attempts reached a provider is unknown, so
        # the whole reservation is counted (over-counting is the safe direction).
        if budget is not None:
            budget.settle_unknown(budget_mod.WORST_CASE_CALLS_PER_JUDGE)
        raise
    if budget is not None:
        budget.settle(budget_mod.WORST_CASE_CALLS_PER_JUDGE, [record])

    # ---- 4 VALIDATE ----------------------------------------------------------------------------
    # Invariant 6, mechanically. A quote that is not in the text the judge was shown was invented.
    failures = _validate(verdict, matchable, used)
    flagged = validation.rejects_verdict(failures)
    rejected = bool(failures)
    verdict = verdict.model_copy(update={"evidence_failures": failures})

    # ---- 5 COMMIT ------------------------------------------------------------------------------
    # A rejected verdict is still written. Invariant 5 forbids dropping it silently, and a
    # flagged verdict with its reasons attached is the auditable form -- deleting the record
    # of a judge that fabricated a quote destroys the evidence that it did. `rejected: true` is
    # what keeps any reader away from it; today none exists (tests/test_code_agent_hardening.py).
    # The payload never holds the student's file: a hash of it, and the quotes the judge chose.
    payload = {
        **verdict.model_dump(),
        "agent": AGENT_ID,
        "prompt_version": prompts.PROMPT_VERSION,
        "provider": record.provider,   # D-04X: which provider actually served this call --
        "model": record.model,         # may differ from LLM_PROVIDER if the fallback fired
        "criteria": list(used),
        "attempt_id": attempt_id,
        "commit_sha": commit_sha,
        "submission_sha256": submission_sha256,
        "scope": ({"mode": "gap_lines", "gap_ranges": [list(r) for r in excerpt.gap_ranges],
                   "context_lines": scope_mod.CONTEXT_LINES, "lines_shown": excerpt.lines_shown,
                   "file_lines": excerpt.file_lines}
                  if excerpt is not None else {"mode": "whole_file"}),
        "rejected": rejected,
        "flagged": flagged,
        "research_only": ["scores.llm_correctness_opinion"],
        "tool_reports": [r.to_dict() for r in reports],
        "reference_supplied": reference is not None,
    }

    trace_id = mem.log_trace(
        student_id, ACTOR, "verdict", payload,
        assignment_id=assignment["assignment_id"], concept_ids=concepts,
        parent_trace_id=parent_trace_id, conn=conn,
    )

    # Recomputes from the `ci_run`/`test_result` traces already in the log; the verdict itself moves
    # nothing until the open decision in this module's docstring is made. Idempotent, so
    # calling it is safe whether or not anything changed.
    for concept in concepts:
        mem.update_mastery(student_id, concept, parent_trace_id=trace_id, conn=conn)

    return verdict, trace_id, (failures or None)
