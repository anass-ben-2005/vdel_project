"""agents/validation.py — M4 task 4.4. Invariant 6, made executable.

`BUILD_PLAN.md` calls `validate_evidence` "the most important function in M4", and the
reason is invariant 6: every rubric score carries verbatim evidence quotes, string-matched
against the actual submission, and a fabricated quote rejects the verdict. Everything else
the Code Agent does is a judgement. This is the one stage that produces a *fact* — it either
found the quoted text in the submission or it did not, and no model opinion enters.

That is also why this file has no LLM call, no database, and no I/O: it is a pure function
of `(verdict, code)`, so it is unit-testable without a provider key or a `PG_DSN`, and its
tests are the only ones in `agents/` that need neither.

Design source: `VDEL_Modules_3_9_Build.md` D.5. **Three deliberate deviations from D.5's
code**, each of which fixes a way D.5's version silently under-reports:

1. **Evidence entries may be `{"quote": ..., "why": ...}` mappings, not only
   `"quoted line + why"` strings.** D.5 recovers the quote with `q.split(" + ")[0]`, which
   truncates any quote containing `" + "` — in code, that is string concatenation and
   arithmetic, i.e. common. The mapping form removes the parse entirely. The string form
   stays supported so a D.5-shaped verdict still validates unchanged, and it is parsed with
   two candidates rather than one (see `_candidate_quotes`).

2. **A scored criterion with no evidence at all is a failure.** D.5 iterates
   `for q in quotes`, so an empty list yields no failures — a verdict scoring 4/4 with zero
   quotes passes D.5's check untouched. Invariant 6 says every score carries evidence;
   silence is precisely what it forbids, and silence is the cheapest way for a judge to
   avoid being caught fabricating.

3. **Matching is a two-level ladder and the level that succeeded is recorded.** An LLM that
   re-indents a quoted line has not fabricated anything, and rejecting it would train the
   prompt toward a false problem. Exact match is tried first; whitespace-normalised match is
   the only fallback, and it is reported as such so an auditor can see which quotes needed
   it. Nothing case-folds and nothing strips punctuation — identifiers are case-sensitive
   and `!=` is not `==`, so those normalisations would let real fabrications through.

**Known limitation, named rather than papered over.** A very short quote (`x`, `df`) will
match almost any submission, so it is weak evidence that still passes. The obvious guard is
a minimum quote length, which is exactly the kind of invented number `CLAUDE.md` §10
forbids. The honest fix is a prompt that asks for whole lines — `agents/prompts.py`'s job,
task 4.3 — not a magic constant here. Recorded so the gap is visible in the audit rather
than discovered in a viva.
"""
from __future__ import annotations

import re
from typing import Any

# Echo pins the four criteria and their order, and its docstring states that M4's prompt
# depends on that order to defend against halo bias.
#
# Declared here rather than imported from `agents.echo_agent` on purpose. Importing would
# pull `memory.memory` and psycopg2 in transitively, for the sake of a four-element tuple,
# and would cost this file the one property that makes it easy to trust: that it is a pure
# function with no database anywhere behind it. The copy cannot drift silently, because
# `tests/test_validation.py::test_criteria_match_echo` asserts the two are identical — the
# drift is caught by a test rather than prevented by a coupling.
CRITERIA = ("correctness", "approach", "readability", "idiomatic")

# ---- Failure kinds -----------------------------------------------------------------------
#
# Named constants rather than bare strings because these values land in a trace payload and
# are therefore schema: `traces` is append-only, so a renamed kind cannot be migrated.
UNMATCHED_QUOTE = "unmatched_quote"
MISSING_EVIDENCE = "missing_evidence"
UNKNOWN_CRITERION = "unknown_criterion"

# ---- Match levels ------------------------------------------------------------------------
MATCH_EXACT = "exact"
MATCH_WHITESPACE = "whitespace_normalised"

# Only fabrication rejects a verdict. Invariant 6's rejecting clause is specifically "a
# fabricated quote rejects the verdict"; it does not say the same of an unevidenced score,
# and D.6 resolves that case as "flagged for human review, not silently trusted". So a
# missing quote flags and a fabricated quote rejects. The asymmetry is deliberate and is an
# open question worth putting to Dr. Ezzatul alongside D-018, which asks the mirror-image
# question about Echo citing an event rather than a quote.
REJECTING_KINDS = frozenset({UNMATCHED_QUOTE})

_WHITESPACE = re.compile(r"\s+")

# Models routinely wrap a quoted line in quotes or backticks. Stripping these can only make
# a match easier, never harder, so it cannot turn a fabrication into a pass that a stricter
# reading would have caught — it can only fail to catch one that was already borderline.
_WRAPPERS = "\"'`"


def _normalise(text: str) -> str:
    """Collapse every whitespace run to a single space. The only normalisation applied."""
    return _WHITESPACE.sub(" ", text).strip()


def _candidate_quotes(entry: Any) -> list[str]:
    """The strings that might be the quoted code in one evidence entry, best candidate first.

    A mapping yields exactly one candidate — its `quote` — because the schema separated the
    quote from the explanation and there is nothing to guess.

    A string yields two: the whole string, then D.5's `split(" + ")[0]`. Whole-string first
    matters when the quote *is* code containing `" + "` (`total = a + b`), where D.5's split
    alone would silently shorten the quote to `total = a` and check less than it appears to.
    Falling back to D.5's segment preserves its behaviour for the `"quote + why"` form the
    prompt actually asks for.
    """
    if isinstance(entry, dict):
        quote = entry.get("quote", "")
        return [quote.strip().strip(_WRAPPERS)] if isinstance(quote, str) else []

    if not isinstance(entry, str):
        return []

    whole = entry.strip().strip(_WRAPPERS)
    candidates = [whole]
    head = entry.split(" + ")[0].strip().strip(_WRAPPERS)
    if head and head != whole:
        candidates.append(head)
    return [c for c in candidates if c]


def _match_level(quote: str, code: str, normalised_code: str) -> str | None:
    """The ladder. Returns the level that matched, or None for no match at any level."""
    if quote in code:
        return MATCH_EXACT
    if _normalise(quote) in normalised_code:
        return MATCH_WHITESPACE
    return None


def _evidence_of(verdict: Any) -> dict[str, Any]:
    """The `evidence` mapping, from a pydantic verdict or a plain dict.

    Accepts both so this function can validate a `code_agent.Verdict`, an `EchoVerdict`, or
    a payload already read back out of a trace — the audit path reads dicts, not models, and
    an auditor re-checking a stored verdict is exactly who this function exists for.
    """
    evidence = getattr(verdict, "evidence", None)
    if evidence is None and isinstance(verdict, dict):
        evidence = verdict.get("evidence")
    return evidence if isinstance(evidence, dict) else {}


def evidence_report(verdict: Any, code: str) -> list[dict[str, Any]]:
    """Every evidence quote, with how it matched the submission. The audit view.

    One record per quote: `criterion`, `quote`, and `match_level` — `exact`,
    `whitespace_normalised`, or `None` when it matched at no level. `validate_evidence` is
    this function filtered to the failures, so there is one implementation of the matching
    and two views of it, rather than two implementations that agree by luck.

    This is the function to show in a demo. "Every quote in this verdict, and here is the
    one that needed whitespace normalisation" is a stronger claim than "no failures", and
    it is the difference between asserting the check ran and showing what it saw.
    """
    records: list[dict[str, Any]] = []
    normalised_code = _normalise(code)

    for criterion in CRITERIA:
        for entry in _entries_for(verdict, criterion):
            candidates = _candidate_quotes(entry)
            if not candidates:
                continue

            level = None
            matched = candidates[0]
            for candidate in candidates:
                level = _match_level(candidate, code, normalised_code)
                if level is not None:
                    matched = candidate
                    break

            records.append({
                "criterion": criterion,
                "quote": matched,
                "match_level": level,
            })

    return records


def _entries_for(verdict: Any, criterion: str) -> list[Any]:
    """One criterion's evidence entries, tolerating a lone entry where a list was expected."""
    entries = _evidence_of(verdict).get(criterion) or []
    if isinstance(entries, (str, dict)):
        return [entries]
    return list(entries) if isinstance(entries, (list, tuple)) else []


def validate_evidence(verdict: Any, code: str) -> list[dict[str, str]]:
    """Every quoted evidence string must actually appear in the submission.

    Returns a list of failure records, empty when the verdict is fully evidenced. D.5's
    return shape is preserved: each record still carries `criterion` and, for a fabrication,
    `unmatched_quote`, so any reader written against D.5 keeps working. `kind` and
    `match_level` are additions, never replacements.

    The three failure kinds:

    - `unmatched_quote` — a quote that appears nowhere in the submission at any level of the
      ladder. This is hallucination, caught mechanically, and it rejects the verdict.
    - `missing_evidence` — a criterion in `CRITERIA` with no usable quote at all. Deviation
      2 above; flags rather than rejects.
    - `unknown_criterion` — evidence filed under a name that is not one of the four. Reported
      because it means the model answered a question that was not asked, and because the
      quotes underneath it are not checked by the per-criterion pass.

    Note what is deliberately *not* checked here: whether the quote actually supports the
    score. That is a judgement, and this file only produces facts. A quote that is real but
    irrelevant passes this check and is caught, if at all, by a human reading the verdict.
    """
    failures: list[dict[str, str]] = []
    report = evidence_report(verdict, code)

    for criterion in CRITERIA:
        records = [r for r in report if r["criterion"] == criterion]

        for record in records:
            if record["match_level"] is None:
                failures.append({
                    "kind": UNMATCHED_QUOTE,
                    "criterion": criterion,
                    "unmatched_quote": record["quote"],
                })

        if not any(r["match_level"] is not None for r in records):
            failures.append({
                "kind": MISSING_EVIDENCE,
                "criterion": criterion,
                "unmatched_quote": "",
            })

    for criterion in _evidence_of(verdict):
        if criterion not in CRITERIA:
            failures.append({
                "kind": UNKNOWN_CRITERION,
                "criterion": str(criterion),
                "unmatched_quote": "",
            })

    return failures


def rejects_verdict(failures: list[dict[str, str]]) -> bool:
    """Whether these failures mean the verdict must not stand. Invariant 6's rejecting clause.

    A named predicate rather than an `if failures:` at each call site, because the
    flag-versus-reject distinction is a policy decision and policy that lives in one function
    can be changed and tested in one place. `code_agent.grade` still records every failure in
    the trace regardless of what this returns — invariant 5 forbids dropping any of it
    silently, and a flagged verdict with its reasons attached is the auditable form.
    """
    return any(f.get("kind") in REJECTING_KINDS for f in failures)
