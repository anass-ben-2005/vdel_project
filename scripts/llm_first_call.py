"""scripts/llm_first_call.py -- the FIRST real LLM call, by hand, on one stored commit. DRY RUN.

    python -m scripts.llm_first_call --student X --attempt-id N --commit-sha SHA [--call-cap 3]

For ONE graded (attempt, commit) it reads the stored grading data (read-only), runs ONLY the
Feedback Agent through the gateway (`system/llm.py`, temperature 0), and prints what it found: the
provider, the model, the number of provider calls, the tokens, the deterministic text, the LLM
paragraph that `run_hourly --with-llm` would add under it, and whether the output validator
accepted or rejected the answer (with the reason). It is a way to LOOK at one real answer before
`--with-llm` is ever switched on (D-101). The student does not see anything.

DRY RUN, NOTHING STORED, NOTHING POSTED. The database session is opened `readonly` (Postgres itself
refuses any write) and rolled back; no trace, no `feedback_posts` row, no GitHub call, no usage
ledger file (the budget lives in memory). The source of this file contains no INSERT, UPDATE,
DELETE or commit, and a test keeps it that way.

REFUSES TO RUN (exit code 2, nothing called) when:
  - `LLM_PROVIDER` is not set. The default of the gateway (anthropic) is not accepted silently on a
    first paid call.
  - not exactly ONE provider key is set, or the one set is not the key of `LLM_PROVIDER`. The
    gateway falls back to any other provider that has a key; for this call there must be nothing
    to fall back to. The refusal names the VARIABLES, never a value.
  - `--call-cap` is not 2 or 3. 3 is the hard maximum; one `judge()` reserves 2 calls (its own
    corrective retry, `agents/budget.py`), so a cap of 1 could never make a call.
  - the attempt does not belong to `--student`, the commit has no graded results for the attempt,
    its status is collection_error / timeout / tooling, it is the template push (D-098), or it has
    no failing check. The agents already make no LLM call for those; here they are refused loudly.

THE CAP IS HARD. `CallBudget(max_calls=cap)` reserves before each call, and in addition every
provider handler of the gateway is wrapped by `HardCap` for the duration, which raises on the
(cap+1)th real provider call. That second layer is what stops a transient failure from walking the
gateway's model fallback chain past the cap.

KEYS. They are read by the gateway (`.env` is loaded when `system.llm` is imported, and the check
runs after that, on what the gateway will actually see). They are never printed, logged or put in
an error message. A key set in `.env` cannot be removed from PowerShell (`$env:X = ''` deletes the
variable and `.env` refills it): empty it in `.env` (`X=`) or comment it out for this session.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from collections.abc import Mapping

from system import db
from system import llm as gateway

MAX_CALL_CAP = 3
MIN_CALL_CAP = 2
BANNER = "DRY RUN, nothing stored, nothing posted"
EXIT_OK, EXIT_REFUSED = 0, 2


class Refused(RuntimeError):
    """The run must not start. The message is shown to the user and holds no secret."""


# --- the checks that need no database and no network -----------------------------------------

def key_variables() -> dict[str, str]:
    """provider name -> the environment variable holding its key (the gateway's own table)."""
    return {str(p): var for p, var in gateway._FALLBACK_KEY_ENV_VARS.items()}


def check_environment(env: Mapping[str, str]) -> str:
    """Return the provider name, or raise `Refused`. Only variable NAMES are ever mentioned."""
    chosen = (env.get("LLM_PROVIDER") or "").strip().lower()
    if not chosen:
        raise Refused("LLM_PROVIDER is not set. Set it explicitly for this call (for example "
                      "$env:LLM_PROVIDER = 'openai'); the gateway's silent default is not "
                      "accepted on a first paid call.")
    table = key_variables()
    if chosen not in table:
        raise Refused(f"LLM_PROVIDER is {chosen!r}: it has no API key to check. Allowed: "
                      f"{', '.join(sorted(table))}.")
    present = sorted(var for var in table.values() if env.get(var))
    if len(present) > 1:
        raise Refused(
            "more than one provider key is set (" + ", ".join(present) + "). The gateway would "
            "fall back to another provider if the first one fails. Blank every key except "
            f"{table[chosen]} for this session. If they are in .env, empty or comment them there "
            "(a PowerShell $env:NAME = '' deletes the variable and .env refills it).")
    if present != [table[chosen]]:
        found = present[0] if present else "no key"
        raise Refused(f"LLM_PROVIDER is {chosen!r} so {table[chosen]} must be set, and only it; "
                      f"found {found}.")
    return chosen


def check_call_cap(cap: int) -> int:
    if cap > MAX_CALL_CAP:
        raise Refused(f"--call-cap {cap} is above the hard maximum of {MAX_CALL_CAP}.")
    if cap < MIN_CALL_CAP:
        raise Refused(f"--call-cap {cap} is too small: one judge() reserves 2 calls (its own "
                      f"corrective retry), so nothing could run. Use {MIN_CALL_CAP} or "
                      f"{MAX_CALL_CAP}.")
    return cap


# --- the hard ceiling at the provider handler ------------------------------------------------

class CapReached(RuntimeError):
    """The (cap+1)th real provider call was about to be made. It was not."""


class HardCap:
    """Count REAL provider calls (every handler shares one counter) and refuse the one after
    `cap`. A context manager: the gateway's handlers are restored on exit."""

    def __init__(self, cap: int):
        self.cap, self.count, self.blocked, self._saved = cap, 0, 0, {}

    def _wrap(self, handler):
        def guarded(*args, **kwargs):
            if self.count >= self.cap:
                self.blocked += 1                      # a call that was refused, never made
                raise CapReached(f"call cap {self.cap} reached: this call was not made")
            self.count += 1
            return handler(*args, **kwargs)
        return guarded

    def __enter__(self) -> HardCap:
        self._saved = dict(gateway._PROVIDER_HANDLERS)
        for provider, handler in self._saved.items():
            gateway._PROVIDER_HANDLERS[provider] = self._wrap(handler)
        return self

    def __exit__(self, *exc) -> None:
        gateway._PROVIDER_HANDLERS.clear()
        gateway._PROVIDER_HANDLERS.update(self._saved)


# --- the run -----------------------------------------------------------------------------------

def open_readonly():
    """A connection whose session Postgres itself keeps read-only."""
    conn = db._open()
    conn.set_session(readonly=True)
    return conn


def _resolve_commit(cur, attempt_id: int, student: str, prefix: str) -> str:
    cur.execute("SELECT student_id FROM attempts WHERE attempt_id = %s", (attempt_id,))
    row = cur.fetchone()
    if row is None:
        raise Refused(f"no attempt {attempt_id}.")
    if row[0] != student:
        raise Refused(f"attempt {attempt_id} does not belong to student {student!r}.")
    cur.execute("SELECT DISTINCT commit_sha FROM test_results WHERE attempt_id = %s"
                " AND commit_sha LIKE %s", (attempt_id, prefix.lower() + "%"))
    found = [r[0] for r in cur.fetchall()]
    if not found:
        raise Refused(f"commit {prefix[:10]} has no graded results for attempt {attempt_id}.")
    if len(found) > 1:
        raise Refused(f"{prefix!r} matches {len(found)} graded commits; give more characters.")
    return found[0]


def _token_totals(records) -> tuple[int, int]:
    live = [r for r in records if not r.cache_hit]
    return sum(r.tokens_in for r in live), sum(r.tokens_out for r in live)


def run(*, student: str, attempt_id: int, commit_sha: str, call_cap: int = MAX_CALL_CAP,
        env: Mapping[str, str], llm=None, cur=None, out=print) -> int:
    """The whole command. `env`: the environment to check. `llm`: `system.llm` by default, a
    `FakeLLM` in tests. `cur`: a caller's cursor (tests); None opens a read-only session."""
    from agents import budget as budget_mod
    from agents import feedback_agent as fa
    from agents import pipeline
    from scripts import post_feedback as pf

    try:
        provider = check_environment(env)
        check_call_cap(call_cap)
    except Refused as exc:
        out(f"REFUSED: {exc}")
        out(f"({BANNER}; no call was made)")
        return EXIT_REFUSED

    out(f"*** {BANNER} ***")
    llm = llm if llm is not None else gateway
    owned = None
    try:
        if cur is None:
            owned = open_readonly()
            cur = owned.cursor()
        try:
            sha = _resolve_commit(cur, attempt_id, student, commit_sha)
            inp = fa.gather_input(cur, attempt_id, sha)
            if inp.status != fa.OK:
                raise Refused(f"the grading status of this commit is {inp.status}: the Feedback "
                              "Agent never calls the LLM for it (plain-words text only).")
            if not inp.failed:
                raise Refused("no check failed on this commit: there is nothing to explain and "
                              "no call would be made.")
        except pf.TemplateCommit:
            out("REFUSED: this commit is the template push of a delivered repo (D-098): it is "
                "not a student action and no feedback is built for it.")
            return EXIT_REFUSED
        except (Refused, ValueError) as exc:
            out(f"REFUSED: {exc}")
            return EXIT_REFUSED

        hidden = pf.hidden_source_lines(inp.project_id) if inp.project_id else frozenset()
        deterministic = pf.build_feedback(cur, attempt_id, sha).markdown
        budget = budget_mod.CallBudget(max_calls=call_cap)        # in memory: no ledger file
        log = getattr(llm, "cost_log", None)
        if log is None:
            log = gateway.COST_LOG
        first_record = len(log)

        out(f"student {student}  attempt {attempt_id}  commit {sha[:10]}  "
            f"{inp.assignment_id}  ({inp.passed}/{inp.total} checks passed)")
        out(f"configured provider: {provider}   call cap: {call_cap} (hard)")
        with HardCap(call_cap) as ceiling:
            result = fa.run_feedback_agent(inp, llm, budget, hidden=hidden,
                                           fallback_markdown=lambda: deterministic)
        records = list(log[first_record:])
        tokens_in, tokens_out = _token_totals(records)
        served = sorted({f"{r.provider}/{r.model}" for r in records}) or ["(none)"]

        out("")
        out(f"provider: {result.provider or provider}")
        out(f"model:    {result.model or 'none answered'}   (records: {', '.join(served)})")
        out(f"provider calls: {result.calls_made} counted by the budget, "
            f"{ceiling.count} real handler call(s) (cap {call_cap})")
        out(f"tokens:   {tokens_in} in, {tokens_out} out")
        out("")
        out("--- deterministic text (what is posted today) " + "-" * 30)
        out(deterministic.rstrip())
        out("")
        out("--- LLM paragraph (what --with-llm would add under it) " + "-" * 20)
        paragraph = (pipeline.checked_addendum(inp, result.output)
                     if result.used_llm else None)
        if paragraph:
            out(paragraph.rstrip())
        else:
            out("(none: the comment would be the deterministic text alone)")
        out("")
        if result.used_llm and paragraph:
            out("VALIDATOR: ACCEPTED (schema valid; cited tests and concepts known; resource is "
                "a candidate or null; no hidden test line; no claim the code is correct or "
                "wrong; no link; no mastery claim)")
        elif result.used_llm:
            out("VALIDATOR: accepted the answer, but the paragraph could not be shown safely "
                "(hidden test source after rendering): it would be dropped.")
        else:
            out("VALIDATOR: REJECTED / NOT USED")
            for reason in result.reasons:
                out(f"  reason: {reason}")
            for number, batch in enumerate(result.rejections, 1):
                for rejection in batch:
                    out(f"  judge call {number}: rule {rejection.rule}: {rejection.detail}")
        out("")
        out(f"*** {BANNER} ***")
        return EXIT_OK
    finally:
        if owned is not None:
            owned.rollback()
            owned.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--student", required=True)
    parser.add_argument("--attempt-id", required=True, type=int)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--call-cap", type=int, default=MAX_CALL_CAP,
                        help=f"max real provider calls, {MIN_CALL_CAP} or {MAX_CALL_CAP} "
                             "(default %(default)s, the hard maximum)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with contextlib.suppress(AttributeError):
        sys.stdout.reconfigure(line_buffering=True)
    return run(student=args.student, attempt_id=args.attempt_id, commit_sha=args.commit_sha,
               call_cap=args.call_cap, env=os.environ)


if __name__ == "__main__":
    sys.exit(main())
