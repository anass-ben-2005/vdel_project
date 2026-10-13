"""agents/feedback_v2.py -- the Feedback Agent v2, behind `--agents-v2` (D-108). No database write.

The v1 agent (agents/feedback_agent.py) is untouched: with the flag off nothing here is imported by
the cycle and its prompt (`fb1`), output and stored trace are byte-identical (tests pin them).

WHAT v2 ADDS TO THE FACTS the model is given (all computed by code, none by the model):
  * the student's own gap lines plus 3 lines of context (`agents/scope.py`, the machinery the Code
    Agent uses), with `<<<` / `>>>` runs escaped as in D-103, capped at MAX_EXCERPT_CHARS;
  * the REVIEWED public description of each failing check (config/checks.yaml; a draft is invisible,
    `config/checks.py`);
  * for each failing check, on how many pushes of this attempt (up to and including this one) it
    has failed -- the recurrence count;
  * a hint LEVEL chosen from the recurrence of the focus check: 1 -> level 1 (expected behaviour),
    2 -> level 2 (point at one quoted line of the student's code), 3 or more -> level 3 (a strategy
    in words). Never code at any level.
The reference solution is NEVER in the prompt. It is read only by the validator, to reject a reply
that copies it.

THE VALIDATOR, on top of every v1 rule (unknown test / concept / resource, hidden source,
correctness claim, link, mastery claim):
  quotes          1 to 3, each a single line of at most MAX_QUOTE_CHARS, copied verbatim from the
                  excerpt (original or delimiter-escaped form), at least one a line of code and not
                  a comment;
  code            no fenced or indented block, no inline `span` above MAX_CODE_SPAN_CHARS;
  solution        the model's words must not contain OVERLAP_MAX of the 4-grams of the master body
                  of a failing gap;
  repetition      no "x of y", no "checks passed", no count of checks or tests, no test_* name:
                  the deterministic text already shows those.

NO PROVIDER CALL, a fixed text or the deterministic one, in two cases: every failing check is a
`NotImplementedError` (the student has not started: one fixed sentence), and no excerpt can be
cut out of the student's file (nothing to quote: the deterministic text alone, with the reason).

All numbers below are design choices, not measurements: CONFIRM in D-108.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from agents import budget as budget_mod
from agents import feedback_agent as fa
from agents import feedback_prompts as fp
from agents import scope as scope_mod
from agents import tools
from agents.prompts import escape_markers
from agents.resources import ResourceCandidate
from assessment.gap_parser import GapParseError, parse_master
from config import checks as checks_cfg
from scripts import post_feedback as pf
from system import llm as llm_gateway

AGENT_V2 = "feedback_agent_v2"

SOURCE_STUB = "deterministic_stub"
SOURCE_NO_EXCERPT = "deterministic_no_excerpt"

# --- design constants (CONFIRM) ------------------------------------------------------------
MAX_EXCERPT_CHARS = 4000  # same figure as the Code Agent's DEFAULT_CODE_PROMPT_CAP
OVERLAP_NGRAM = 4  # tokens per n-gram
OVERLAP_MAX = 0.25  # share of the master body's n-grams that may reappear in the reply
OVERLAP_MIN_NGRAMS = 3  # a body with fewer n-grams is too short to compare
STUB_EXCEPTION = "NotImplementedError"

STUB_SENTENCE = (
    "Every check that failed on this push is failing because the function it tests is still the "
    "starting stub: it raises NotImplementedError. Open the file listed in your ASSIGNMENT.md, "
    "replace the stub of the first gap with your own code, run the visible tests, and push again."
)


# --- level and focus -----------------------------------------------------------------------


def hint_level_for(failures: int) -> int:
    """1 push -> 1, 2 pushes -> 2, three or more -> 3 (CONFIRM)."""
    return 1 if failures <= 1 else 2 if failures == 2 else 3


def pick_focus(failed: Sequence[fa.FailedCheck], recurrence: dict[str, int]) -> str | None:
    """The failing check with the highest recurrence; a tie goes to the first by name."""
    if not failed:
        return None
    return sorted(failed, key=lambda f: (-recurrence.get(f.test_name, 1), f.test_name))[0].test_name


def is_stub_only(failed: Sequence[fa.FailedCheck]) -> bool:
    return bool(failed) and all(f.exception_type == STUB_EXCEPTION for f in failed)


# --- input ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class FeedbackInputV2(fa.FeedbackInput):
    recurrence: dict = field(default_factory=dict)  # test_name -> pushes it failed on
    descriptions: dict = field(default_factory=dict)  # test_name -> REVIEWED public description
    focus_check: str | None = None
    hint_level: int = 1
    excerpt: str | None = None  # escaped; what goes into the prompt
    excerpt_matchable: str = ""  # the shown student lines, unescaped
    excerpt_note: str = ""
    excerpt_reason: str | None = None  # why there is no excerpt
    master_bodies: dict = field(default_factory=dict)  # gap_id -> master body (validator only)

    @property
    def quotable(self) -> str:
        return self.excerpt_matchable


# --- output --------------------------------------------------------------------------------


class FeedbackOutputV2(fa.FeedbackOutput):
    quotes: list[str] = Field(min_length=1, max_length=fp.MAX_QUOTES)

    @field_validator("quotes")
    @classmethod
    def _quotes_are_strings(cls, quotes: list[str]) -> list[str]:
        return [q if isinstance(q, str) else str(q) for q in quotes]


# --- validation ----------------------------------------------------------------------------

_TOKEN = re.compile(r"[A-Za-z_]\w*|\d+|[^\s\w]")
_FENCE = re.compile(r"```|<pre\b|<code\b", re.IGNORECASE)
_INDENTED = re.compile(r"^(?: {4,}|\t)\S", re.MULTILINE)
_SPAN = re.compile(r"`([^`\n]*)`")
_COUNTS = re.compile(
    r"\b\d+\s*(?:of|/|out\s+of)\s*\d+\b|\bchecks?\s+(?:passed|failed)\b|"
    r"\b\d+\s+(?:checks?|tests?)\b|\b(?:all|every|both|none of the)\s+(?:the\s+)?checks?\s+"
    r"(?:passed|failed)\b",
    re.IGNORECASE,
)
_TEST_NAME = re.compile(r"\btest_[A-Za-z0-9_]+")


def ngrams(text: str, n: int = OVERLAP_NGRAM) -> set[tuple[str, ...]]:
    tokens = _TOKEN.findall(text.lower())
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def _code_only(body: str) -> str:
    return "\n".join(
        ln for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
    )


def overlap_ratio(master_body: str, reply: str) -> float | None:
    """Share of the master body's n-grams that reappear in `reply`; None when the body is too short
    to compare (fewer than OVERLAP_MIN_NGRAMS n-grams)."""
    master = ngrams(_code_only(master_body))
    if len(master) < OVERLAP_MIN_NGRAMS:
        return None
    return len(master & ngrams(reply)) / len(master)


def validate_output_v2(
    out: FeedbackOutputV2, inp: FeedbackInputV2, hidden: frozenset[str]
) -> list[fa.Rejection]:
    """Every reason `out` must not reach a student. Empty list = acceptable. Pure."""
    rejections = fa.validate_output(out, inp, hidden)  # every v1 rule first
    text = "\n".join([out.summary, *out.what_to_check_next])

    # -- quotes of the student's code
    shown = inp.quotable
    escaped = escape_markers(shown)
    bad_shape = [q for q in out.quotes if not q.strip() or "\n" in q or "\r" in q]
    too_long = [q for q in out.quotes if len(q) > fp.MAX_QUOTE_CHARS]
    unmatched = [
        q for q in out.quotes if q.strip() and "\n" not in q and q not in shown and q not in escaped
    ]
    if bad_shape:
        rejections.append(
            fa.Rejection(
                "quote_not_one_line", "each quote must be ONE non-empty line of the student's code"
            )
        )
    if too_long:
        rejections.append(
            fa.Rejection(
                "quote_too_long", f"each quote must be at most {fp.MAX_QUOTE_CHARS} characters"
            )
        )
    if unmatched:
        rejections.append(
            fa.Rejection(
                "quote_not_in_code",
                f"{len(unmatched)} quote(s) are not copied verbatim from the student's lines",
            )
        )
    matched = [q for q in out.quotes if q not in unmatched and q not in bad_shape]
    if not any(q.strip() and not q.strip().startswith("#") for q in matched):
        rejections.append(
            fa.Rejection(
                "no_code_quote",
                "at least one quote must be a line of code "
                "(not a comment) copied from the student's lines",
            )
        )

    # -- no code
    if _FENCE.search(text) or _INDENTED.search(text):
        rejections.append(fa.Rejection("code_block", "do not write a code block or indented code"))
    if any(len(span) > fp.MAX_CODE_SPAN_CHARS for span in _SPAN.findall(text)):
        rejections.append(
            fa.Rejection(
                "code_span_too_long",
                "an inline `code` span may be at most "
                f"{fp.MAX_CODE_SPAN_CHARS} characters; do not write code",
            )
        )

    # -- do not copy the reference solution (its content is never echoed back)
    gap_ids = {f.gap_id for f in inp.failed if f.gap_id}
    ratios = [
        r
        for g in gap_ids
        if (b := inp.master_bodies.get(g))
        if (r := overlap_ratio(b, text)) is not None
    ]
    if ratios and max(ratios) >= OVERLAP_MAX:
        rejections.append(
            fa.Rejection(
                "solution_overlap",
                "your wording is too close to a "
                "reference solution; describe the idea, not the code",
            )
        )

    # -- do not repeat the deterministic summary
    if _COUNTS.search(text) or _TEST_NAME.search(text):
        rejections.append(
            fa.Rejection(
                "repeats_summary",
                "do not repeat the counts or the names "
                "of the checks: the message already shows them",
            )
        )
    return rejections


# --- rendering -----------------------------------------------------------------------------


def shown_quote(out: FeedbackOutputV2) -> str | None:
    """The first quote that is a line of code (the one a level-2 message points at)."""
    return next(
        (q.strip() for q in out.quotes if q.strip() and not q.strip().startswith("#")), None
    )


def _level_lines(inp: FeedbackInputV2, out: FeedbackOutputV2) -> list[str]:
    """The sentences WRITTEN BY CODE for this level, before the model's words."""
    if inp.hint_level == 1:
        said = inp.descriptions.get(inp.focus_check or "")
        return [f"Expected behaviour: {said}", ""] if said else []
    if inp.hint_level == 2:
        quote = shown_quote(out)
        return [f"Look again at this line of your code: `{quote}`", ""] if quote else []
    return []


def _model_part(inp: FeedbackInputV2, out: FeedbackOutputV2) -> list[str]:
    return [*_level_lines(inp, out), *fa._model_lines(inp, out)]


def render_markdown_v2(inp: FeedbackInputV2, out: FeedbackOutputV2) -> str:
    lines = [
        f"### VDEL feedback: `{inp.assignment_id}`, attempt {inp.attempt_no}, commit "
        f"`{inp.commit_sha[:7]}`",
        "",
        f"**{inp.passed} of {inp.total}** checks passed.",
        "",
    ]
    if inp.failed:
        lines.append("Checks that failed on this commit:")
        for f in inp.failed:
            lines.append(
                f"- `{pf.short_test_name(f.test_name)}`: {f.exception_type or 'check failed'}"
            )
        lines.append("")
    return "\n".join(lines + _model_part(inp, out))


def render_addendum_v2(inp: FeedbackInputV2, out: FeedbackOutputV2) -> str:
    return "\n".join(["**More detail** (written by an AI assistant)", "", *_model_part(inp, out)])


STUB_ADDENDUM = "\n".join(["**Where to start**", "", STUB_SENTENCE, ""])


# --- the result ----------------------------------------------------------------------------


@dataclass
class FeedbackResultV2(fa.FeedbackResult):
    hint_level: int = 1
    focus_check: str | None = None
    recurrence: dict = field(default_factory=dict)
    quotes: list[str] = field(default_factory=list)

    agent_id = AGENT_V2

    @property
    def storable(self) -> bool:
        """A trace is written for an LLM answer and for the fixed stub sentence (it must be posted
        too, and the poster reads traces); never for the other deterministic outcomes."""
        return self.source in (fa.SOURCE_LLM, SOURCE_STUB)

    def addendum_markdown(self) -> str | None:
        """The paragraph to post under the deterministic text (redacted, leak-checked), or None."""
        inp = self.input
        if inp is None:
            return None
        if self.source == SOURCE_STUB:
            return STUB_ADDENDUM
        if self.output is None:
            return None
        hidden = pf.hidden_source_lines(inp.project_id) if inp.project_id else frozenset()
        text = pf.redact(render_addendum_v2(inp, self.output), hidden)
        try:
            pf.assert_no_hidden_source(text, hidden)
        except pf.HiddenSourceLeak:
            return None
        return text

    def to_trace_payload(self, inp: fa.FeedbackInput | None = None) -> dict[str, Any]:
        inp = inp or self.input
        if inp is None:
            raise ValueError("no FeedbackInput: pass one")
        excerpt = getattr(inp, "excerpt_matchable", "") or ""
        return {
            "agent": AGENT_V2,
            "prompt_version": fp.FEEDBACK_PROMPT_VERSION_V2,
            "attempt_id": inp.attempt_id,
            "commit_sha": inp.commit_sha,
            "status": self.status,
            "source": self.source,
            "output": self.output.model_dump() if self.output else None,
            "reasons": list(self.reasons),
            "rejected_rules": [[r.rule for r in batch] for batch in self.rejections],
            "judge_calls": self.judge_calls,
            "provider_calls": self.calls_made,
            "model": self.model,
            "provider": self.provider,
            "hint_level": self.hint_level,
            "focus_check": self.focus_check,
            "recurrence": dict(self.recurrence),
            "quotes": list(self.quotes),
            "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
            if excerpt
            else None,
        }


# --- the run -------------------------------------------------------------------------------


def run_feedback_agent_v2(
    inp: FeedbackInputV2,
    llm: Any,
    budget: budget_mod.CallBudget | None,
    *,
    hidden: frozenset[str],
    fallback_markdown: Callable[[], str],
) -> FeedbackResultV2:
    """The agent without a database. Same contract as `fa.run_feedback_agent`: never raises for an
    LLM-side problem; every one ends in a deterministic text with the reason recorded."""
    common = {
        "status": inp.status,
        "input": inp,
        "hint_level": inp.hint_level,
        "focus_check": inp.focus_check,
        "recurrence": dict(inp.recurrence),
    }
    if inp.status != fa.OK:
        return FeedbackResultV2(
            fallback_markdown(),
            fa.SOURCE_STATUS,
            **common,
            reasons=[f"status {inp.status}: plain-words explanation, no LLM"],
        )
    if not inp.failed:
        return FeedbackResultV2(
            fallback_markdown(),
            fa.SOURCE_NO_FAILURES,
            **common,
            reasons=["no failing check: nothing to explain, no LLM"],
        )
    if is_stub_only(inp.failed):
        return FeedbackResultV2(
            fallback_markdown() + "\n\n" + STUB_ADDENDUM,
            SOURCE_STUB,
            **common,
            reasons=[
                "every failing check is a NotImplementedError in a stub: "
                "a fixed sentence, no provider call"
            ],
        )
    if inp.excerpt is None:
        return FeedbackResultV2(
            fallback_markdown(),
            SOURCE_NO_EXCERPT,
            **common,
            reasons=[
                f"no excerpt of the student's lines "
                f"({inp.excerpt_reason}): nothing to quote, no provider "
                "call"
            ],
        )

    result = FeedbackResultV2("", fa.SOURCE_FALLBACK, **common)
    prompt = fp.build_feedback_prompt_v2(inp)
    last: list[fa.Rejection] = []
    for attempt in range(1, fa.MAX_JUDGE_CALLS + 1):
        sent = prompt if attempt == 1 else prompt + fp.corrective_note(last)
        if budget is not None:
            try:
                budget.charge(budget_mod.WORST_CASE_CALLS_PER_JUDGE, what="Feedback Agent v2")
            except budget_mod.BudgetExceeded as exc:
                result.reasons.append(f"budget_exceeded: {exc.cap} cap {exc.limit}")
                break
        try:
            out, record = llm.judge(sent, FeedbackOutputV2)
        except llm_gateway.SchemaValidationError as exc:
            result.judge_calls += 1
            if budget is not None:
                result.calls_made += budget.settle(
                    budget_mod.WORST_CASE_CALLS_PER_JUDGE, exc.records
                )
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

        out = out.model_copy(
            update={"cited_tests": [fa._normalise_test_ref(t) for t in out.cited_tests]}
        )
        last = validate_output_v2(out, inp, hidden)
        result.rejections.append(last)
        if not last:
            markdown = render_markdown_v2(inp, out)
            try:
                pf.assert_no_hidden_source(markdown, hidden)
            except pf.HiddenSourceLeak:
                result.reasons.append("hidden_source_in_rendered_markdown")
                break
            result.markdown = pf.redact(markdown, hidden)
            result.output = out
            result.quotes = list(out.quotes)
            result.source = fa.SOURCE_LLM
            return result
        result.reasons.append("rejected: " + ", ".join(r.rule for r in last))

    result.markdown = fallback_markdown()
    result.source = fa.SOURCE_FALLBACK
    return result


# --- database glue -------------------------------------------------------------------------


def failure_counts(
    cur, attempt_id: int, commit_sha: str, test_names: Sequence[str]
) -> dict[str, int]:
    """For each test: on how many distinct graded pushes of this attempt, up to and including
    `commit_sha` (by commit time), it failed. Counts only status `ok` rows. Read-only."""
    if not test_names:
        return {}
    cur.execute(
        "SELECT t.test_name, count(DISTINCT t.commit_sha) FROM test_results t"
        " JOIN raw_commits c ON c.sha = t.commit_sha"
        " WHERE t.attempt_id = %s AND t.status = 'ok' AND NOT t.passed AND t.test_name = ANY(%s)"
        "   AND c.committed_at <= (SELECT committed_at FROM raw_commits WHERE sha = %s)"
        " GROUP BY t.test_name",
        (attempt_id, list(test_names), commit_sha),
    )
    counts = {name: int(n) for name, n in cur.fetchall()}
    return {name: max(1, counts.get(name, 0)) for name in test_names}


def master_bodies(project_id: str, file_path: str, gap_ids: Sequence[str]) -> dict[str, str]:
    """The master's solution text of each given gap, for the validator only. {} if unreadable."""
    path = scope_mod.CURRICULUM_ROOT / project_id / file_path
    try:
        gaps = parse_master(path)
    except (OSError, GapParseError):
        return {}
    wanted = set(gap_ids)
    return {
        g.gap_id: (g.body if isinstance(g.body, str) else "\n".join(g.body))
        for g in gaps
        if g.gap_id in wanted
    }


def gather_input_v2(
    cur,
    attempt_id: int,
    commit_sha: str,
    *,
    repo_dir: Path | str,
    memory: Any = None,
    profile: dict | None = None,
    candidates: Sequence[ResourceCandidate] | None = None,
    checks_path: Path | str | None = None,
) -> FeedbackInputV2:
    """Read-only: the v1 facts plus recurrence, reviewed descriptions and the student's lines."""
    base = fa.gather_input(
        cur, attempt_id, commit_sha, memory=memory, profile=profile, candidates=candidates
    )
    names = [f.test_name for f in base.failed]
    recurrence = failure_counts(cur, attempt_id, commit_sha, names)
    path_kw = {} if checks_path is None else {"path": checks_path}
    descriptions = {
        n: d for n in names if (d := checks_cfg.description_for(base.assignment_id, n, **path_kw))
    }
    focus = pick_focus(base.failed, recurrence)
    level = hint_level_for(recurrence.get(focus, 1)) if focus else 1

    excerpt = matchable = None
    note, reason = "", None
    cur.execute("SELECT file_path FROM assignments WHERE assignment_id = %s", (base.assignment_id,))
    row = cur.fetchone()
    file_path = row[0] if row else None
    try:
        if not file_path:
            raise scope_mod.ScopeUnavailable("the assignment has no file_path")
        spec = scope_mod.scope_spec_for_attempt(cur, attempt_id)
        source = tools.vet_source(Path(repo_dir) / file_path, repo_dir)
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise scope_mod.ScopeUnavailable("the file is not UTF-8 text") from None
        ex = scope_mod.judged_excerpt(spec, text)
        shown = escape_markers(ex.text)
        if len(shown) > MAX_EXCERPT_CHARS:
            raise scope_mod.ScopeUnavailable(
                f"the student's lines are {len(shown)} characters, above the cap of "
                f"{MAX_EXCERPT_CHARS}"
            )
        excerpt, matchable, note = shown, ex.matchable, ex.note
    except scope_mod.ScopeUnavailable as exc:
        reason = str(exc)
    except tools.SourceRefused as exc:
        reason = f"the file cannot be read safely: {exc}"

    bodies = {}
    if file_path and base.project_id:
        bodies = master_bodies(
            base.project_id, file_path, [f.gap_id for f in base.failed if f.gap_id]
        )
    values = {k: getattr(base, k) for k in fa.FeedbackInput.__dataclass_fields__}
    return FeedbackInputV2(
        **values,
        recurrence=recurrence,
        descriptions=descriptions,
        focus_check=focus,
        hint_level=level,
        excerpt=excerpt,
        excerpt_matchable=matchable or "",
        excerpt_note=note,
        excerpt_reason=reason,
        master_bodies=bodies,
    )


def build_feedback_v2(
    cur,
    attempt_id: int,
    commit_sha: str,
    llm: Any,
    budget: budget_mod.CallBudget | None,
    *,
    repo_dir: Path | str,
    memory: Any = None,
    profile: dict | None = None,
    candidates: Sequence[ResourceCandidate] | None = None,
    checks_path: Path | str | None = None,
) -> FeedbackResultV2:
    """One graded commit -> `FeedbackResultV2`. SELECTs only; the caller owns persistence."""
    inp = gather_input_v2(
        cur,
        attempt_id,
        commit_sha,
        repo_dir=repo_dir,
        memory=memory,
        profile=profile,
        candidates=candidates,
        checks_path=checks_path,
    )
    hidden = pf.hidden_source_lines(inp.project_id) if inp.project_id else frozenset()
    return run_feedback_agent_v2(
        inp,
        llm,
        budget,
        hidden=hidden,
        fallback_markdown=lambda: pf.build_feedback(cur, attempt_id, commit_sha).markdown,
    )
