"""scripts/run_cycle.py -- one idempotent command that runs the whole student-side pipeline.

    python -m scripts.run_cycle [--student X] [--roster PATH] [--dry-run]
                                [--skip-network] [--plan] [--with-llm] [--with-code-agent]
                                [--llm-run-cap N] [--llm-daily-cap N] [--code-agent-max-chars N]

For every student in the roster (or just --student), in this order, each stage a separate
unit of work:

    1. collect     GitHub -> raw_commits / raw_workflow_runs      (collect_all, network)
    2. grade       ungraded commits -> test_results, traces       (grade_collected.run, network)
    3. features    learner_features, only for students whose latest event has no row yet
    4. profile     Memory.sync_features_ref, only when features_ref is stale
    5. llm         off by default; `--with-llm` runs the agents right after each graded commit

It reuses the existing functions and reimplements none of them (D-071). Idempotent: a second
run with nothing new on GitHub writes nothing -- the collector skips what it stored, the
grader skips commits that already have test_results, features are computed only when the
student's watermark has no row, and the profile pointer is synced only when stale.

Guarantees (each is a test in tests/test_run_cycle.py):
  - ONE cycle at a time: a Postgres advisory lock. A second cycle exits at once with code 3.
  - DB down: exits at once with code 2 and a plain message, before doing anything.
  - ISOLATION: a failure for one student (an exception in any stage, or a failed repo) is
    recorded and printed; the other students still run. Exit code 1 if any student failed.
  - `--dry-run`: reads only. No network, no INSERT/UPDATE/DELETE, no commit. It says what a
    cycle would do today. (The advisory lock is taken: it is not a table write.)
  - `--skip-network`: stages 1 and 2 are skipped (grading fetches the commit from GitHub);
    features and profile are computed from what the database already holds.

`--with-llm` (D-099, OFF by default) calls the Feedback Agent once per commit that has just been
graded with status `ok` and has a FAILING check, from inside the grade stage. Its LLM answer is
stored as ONE `coach`/`intervention` trace per (attempt, commit).

`--with-code-agent` (D-104, OFF by default, REFUSED unless `--with-llm` is also given, exit code 4)
adds the Code Agent for a commit whose checks ALL passed: it judges the quality of working code,
never of failing code. It runs only if the commit is not the template push (D-098), the assignment
has a judgeable file and its gap lines can be extracted from the student's file, and the judged
text is within `--code-agent-max-chars`; otherwise the log says `code_agent skipped, <reason>`. Its
verdict is stored (one `code_agent`/`verdict` trace per (attempt, commit), `agents/code_agent.py`),
is NEVER posted and is read by nothing. Each agent runs in its own SAVEPOINT.

Two caps, both counting PROVIDER calls and shared by both agents: `--llm-run-cap` (default 10) for
this run and `--llm-daily-cap` (default 20) for the day, kept in `.vdel/llm_usage.json`; they are
enforced at the provider handler too, so they hold when the gateway tries its fallback models.
Hitting a cap, a rejected answer, a provider error or any agent exception is reported on its line
and never fails the grading or the cycle. `--dry-run` calls no agent.

`--plan` reads and prints only (no network, no grading, no LLM call, no write): the stored commits
that would reach the hook and which agent each would run.

Exit codes: 0 all students ok (or dry-run, or plan); 1 some student failed; 2 database
unreachable; 3 another cycle holds the lock; 4 refused (`--with-code-agent` without `--with-llm`).
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from dataclasses import dataclass, field

from agents import code_agent
from agents import pipeline as agents_pipeline
from agents import scope as scope_mod
from agents.budget import DEFAULT_LEDGER_PATH, BudgetExceeded, CallBudget, UsageLedger
from assessment.test_runner import grade_attempt
from collectors.collect_github import collect_all
from features import compute_features as cf
from memory.memory import Memory
from scripts import grade_collected as gc
from scripts import post_feedback as pf
from scripts.llm_first_call import HardCap
from scripts.seed_data import load_roster, roster_repo_for, roster_repos
from system import db
from system.llm import SchemaValidationError

ADVISORY_LOCK_KEY = 640_201_071       # arbitrary constant: "one vdel cycle at a time"
EXIT_OK, EXIT_STUDENT_FAILED, EXIT_DB_DOWN, EXIT_LOCKED, EXIT_REFUSED = 0, 1, 2, 3, 4
# Chosen numbers (D-099), not measurements: a Feedback Agent run is at most 4 provider calls
# (agents/budget.py), so 10 is a run of about two commits.
DEFAULT_LLM_RUN_CAP = 10
DEFAULT_LLM_DAILY_CAP = 20
# CONFIRM (D-104): the most characters of judged lines plus context the Code Agent will put in a
# prompt. The largest excerpt in the curriculum today is 789 characters (weather_etl/extract), so
# 4000 is about five times that; a chosen number, not a measurement.
DEFAULT_CODE_PROMPT_CAP = 4000


@dataclass
class StudentResult:
    student_id: str
    commits_added: int = 0
    runs_added: int = 0
    graded: int = 0
    frozen: int = 0
    pending: int = 0
    post_freeze_skipped: int = 0
    features: str = "-"
    profile: str = "-"
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class CycleResult:
    exit_code: int
    students: list[StudentResult] = field(default_factory=list)
    message: str = ""


# --- plumbing ---------------------------------------------------------------------------------

@contextlib.contextmanager
def _unit(conn, name: str):
    """One stage of one student as an atomic unit of work.

    Production (`conn is None`): its own connection, committed on success, rolled back on
    error. Tests pass a `conn`: the unit is a SAVEPOINT inside that one transaction, so a
    failing stage is undone without losing the stages before it, and the whole test can still
    be rolled back at the end (traces are append-only; rollback is the only cleanup)."""
    if conn is None:
        with db.connect() as c:
            yield c
        return
    savepoint = f"cycle_{name}"
    cur = conn.cursor()
    cur.execute(f"SAVEPOINT {savepoint}")
    try:
        yield conn
    except Exception:
        cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        raise
    else:
        cur.execute(f"RELEASE SAVEPOINT {savepoint}")


def _count(cur, table: str, student_id: str) -> int:
    assert table in ("raw_commits", "raw_workflow_runs")
    cur.execute(f"SELECT count(*) FROM {table} WHERE student_id = %s", (student_id,))
    return cur.fetchone()[0]


def roster_warnings(cur, student_id: str, repo_for: dict) -> list[str]:
    """One line per OPEN attempt of the student that the roster cannot reach (D-105).

    An open attempt (`submitted_at IS NULL`) whose repo is not in the roster is never collected
    and so never graded: no error, no pending commit, no log line. That is how attempt 3 of
    weather_etl_extract sat unnoticed after its delivery. Two cases are reported:
      * no roster row for (student, assignment) at all;
      * attempt 2 or later whose roster repo is not the one `deliver_next_attempt` names for that
        attempt (the roster still points at an earlier attempt's repo). Attempt 1 is not compared:
        its repo predates the delivery naming rule, so a mismatch there proves nothing.
    Read-only. A report, never an error: a student can legitimately have an open attempt that has
    not been delivered yet."""
    from scripts.deliver_next_attempt import delivery_repo_name

    cur.execute("SELECT assignment_id, attempt_no, project_id FROM attempts"
                " WHERE student_id = %s AND submitted_at IS NULL"
                " ORDER BY assignment_id, attempt_no", (student_id,))
    lines = []
    for assignment_id, attempt_no, project_id in cur.fetchall():
        entry = repo_for.get((student_id, assignment_id))
        if entry is None:
            lines.append(f"open attempt {attempt_no} of {assignment_id} has no roster repo: "
                         "nothing is collected or graded for it "
                         "(not delivered yet, or scripts.roster_apply adds the row)")
            continue
        if attempt_no >= 2 and project_id:
            expected = delivery_repo_name(project_id, student_id, assignment_id, attempt_no)
            if entry[1] != expected:
                lines.append(f"open attempt {attempt_no} of {assignment_id}: the roster repo is "
                             f"{entry[0]}/{entry[1]} but the delivery names {expected}; commits "
                             "pushed to the new repo are not collected until the roster is updated")
    return lines


def _warn_unrostered(conn, student_id: str, repo_for: dict, out) -> None:
    try:
        with _unit(conn, "roster_check") as c:
            lines = roster_warnings(c.cursor(), student_id, repo_for)
    except Exception as exc:  # noqa: BLE001 -- a diagnostic must never stop a cycle
        out(f"  WARN      roster check could not run: {type(exc).__name__}: "
            f"{str(exc).strip()[:200]}")
        return
    for line in lines:
        out(f"  WARN      {line}")


def _needs_features(cur, student_id: str) -> bool:
    """True when the student has activity and no learner_features row sits at its watermark.

    Whatever the row's formula_ver: a v2/v3 row at the same watermark means "already
    computed" (write_features never overwrites another version -- D-063), so the cycle does
    not retry it every time."""
    mark = cf.watermark(cur, student_id)
    if mark is None:
        return False
    cur.execute("SELECT 1 FROM learner_features WHERE student_id = %s AND computed_at = %s",
                (student_id, mark))
    return cur.fetchone() is None


# --- the agents hook (--with-llm, and --with-code-agent) ---------------------------------------

class AgentsFailed(RuntimeError):
    """Several agents of ONE commit raised; the message holds each of them."""


class AgentsHook:
    """What runs right after a commit is graded, when `--with-llm` is on (D-099, D-104).

    One per cycle: it owns the `CallBudget`, so the run cap spans every student and BOTH agents.
    `bind(conn)` returns the `after_grade` callable for the grade stage's connection. Everything is
    read, and the traces are written, in the SAME transaction as the grading, each agent inside its
    OWN SAVEPOINT: an agent that raises (even in SQL) is rolled back alone, leaves the grading and
    the other agent's trace untouched, and is reported (never raised into the grading).

    Who runs on a commit (D-104). Neither, for the template push (D-098), for a commit with no test
    row, or (the caller's rule) for a status other than `ok`. Then:
      * at least one check FAILED -> the Feedback Agent (explains the failures; never judges code);
      * ALL checks passed and `code_agent` is on -> the Code Agent (judges the quality of working
        code); never for a failing commit, because correctness is decided by the tests, not by it.
    So one commit gets one agent, and its budgeted maximum is 4 provider calls (Feedback) or 2
    (Code). The Code Agent's verdict is stored and nothing else: never posted, read by nothing."""

    def __init__(self, llm, budget: CallBudget, mem, out, daily_cap: int, *,
                 code_agent: bool = False, code_prompt_cap: int = DEFAULT_CODE_PROMPT_CAP,
                 agents_v2: bool = False):
        self.llm, self.budget, self.mem, self.out, self.daily_cap = llm, budget, mem, out, daily_cap
        self.code_agent, self.code_prompt_cap = code_agent, code_prompt_cap
        self.agents_v2 = agents_v2             # D-108: the v2 agents

    def today(self) -> str:
        return f"calls today: {self.budget.ledger.day_total()}/{self.daily_cap}"

    def _say(self, p, text: str) -> None:
        self.out(f"  llm       {p.student_id}/{p.assignment_id} {p.sha[:7]}: {text}")

    @staticmethod
    def _guarded(conn, name: str, fn):
        """Run `fn(cursor)` in its own SAVEPOINT. Returns `(value, None)` or `(None, exception)`."""
        cur = conn.cursor()
        point = f"agents_{name}"
        cur.execute(f"SAVEPOINT {point}")
        try:
            value = fn(cur)
            cur.execute(f"RELEASE SAVEPOINT {point}")
            return value, None
        except Exception as exc:  # noqa: BLE001 -- reported by the caller, never raised into grading
            cur.execute(f"ROLLBACK TO SAVEPOINT {point}")
            return None, exc

    def bind(self, conn):
        def after_grade(p, repo_dir, result):
            reason, error = self._guarded(conn, "gate", lambda cur: self._gate(cur, p, result))
            if error is not None:
                raise error
            if reason:
                self._say(p, reason)
                return
            steps = [("feedback", lambda cur: self._feedback(cur, p, repo_dir))]
            if self.code_agent:
                steps.append(("code_agent", lambda cur: self._code(cur, p, repo_dir, result)))
            errors = [(name, err) for name, fn in steps
                      for _, err in [self._guarded(conn, name, fn)] if err is not None]
            if len(errors) == 1:
                raise errors[0][1]
            if errors:
                raise AgentsFailed("; ".join(f"{n}: {type(e).__name__}: {e}" for n, e in errors))
        return after_grade

    def _gate(self, cur, p, result) -> str | None:
        """The reason NO agent runs on this commit, or None."""
        if pf.is_template_commit(cur, p.sha):                 # D-098: not a student action
            return "template push, no agent"
        if not result.tests_total:
            return "no test rows, no agent"
        return None

    def _feedback(self, cur, p, repo_dir=None) -> None:
        if self.agents_v2:
            return self._feedback_v2(cur, p, repo_dir)
        # No assignment and no code_path: the pipeline marks the Code Agent step `skipped` and makes
        # no call (the Code Agent is run by `_code`, below, in its own savepoint). The Feedback
        # Agent reads only test_results, the diagnosis and the mastery slice.
        summary = agents_pipeline.run_agents_for_commit(
            p.student_id, p.attempt_id, p.sha, llm=self.llm, budget=self.budget, cur=cur,
            memory=self.mem)
        trace = None
        step = summary.steps.get(agents_pipeline.FEEDBACK_AGENT)
        if step is not None and step.status == agents_pipeline.OK:
            trace = agents_pipeline.persist_feedback(
                self.mem, cur, p.student_id, p.assignment_id, step.result)
        parts = [f"{name}={s.status}" + (f" ({s.error})" if s.error else "")
                 for name, s in summary.steps.items()]
        self._say(p, ", ".join(parts) + (f", coach trace {trace}" if trace else ", no trace")
                  + f"  ({self.today()})")

    def _feedback_v2(self, cur, p, repo_dir) -> None:
        """The Feedback Agent v2 (D-108): the student's lines, the reviewed check descriptions, the
        recurrence and a hint level go in; a stub-only commit or one with no excerpt makes no call.
        Stored as ONE coach/intervention trace (agent `feedback_agent_v2`) when it is an LLM answer
        or the fixed stub sentence."""
        from agents import feedback_v2 as fv2
        result = fv2.build_feedback_v2(cur, p.attempt_id, p.sha, self.llm, self.budget,
                                       repo_dir=repo_dir, memory=self.mem)
        trace = agents_pipeline.persist_feedback(self.mem, cur, p.student_id, p.assignment_id,
                                                 result)
        why = f" ({'; '.join(result.reasons)})" if result.reasons else ""
        self._say(p, f"feedback_agent_v2={result.source}, hint level {result.hint_level}, "
                     f"{result.calls_made} provider call(s){why}"
                     + (f", coach trace {trace}" if trace else ", no trace")
                     + f"  ({self.today()})")

    def _code(self, cur, p, repo_dir, result) -> None:
        """The Code Agent for ONE commit whose checks all passed. Every refusal is a logged
        `skipped, reason`; nothing here can fail the grading."""
        def skip(reason: str) -> None:
            self._say(p, f"code_agent skipped, {reason}")

        failed = result.tests_total - result.tests_passed
        if failed:
            return skip(f"{failed} of {result.tests_total} check(s) failed: a failing commit gets "
                        "the Feedback Agent, never the Code Agent")
        assignment, file_path = agents_pipeline.load_assignment_inputs(cur, p.assignment_id)
        if not file_path:
            return skip("the assignment has no judgeable file (no file_path)")
        found = code_agent.find_verdict(cur.connection, p.attempt_id, p.sha)
        if found is not None:
            return self._say(p, f"code_agent already judged this commit (trace {found[1]}): "
                                "no call")
        try:
            spec = scope_mod.scope_spec_for_attempt(cur, p.attempt_id)
        except scope_mod.ScopeUnavailable as exc:
            return skip(f"gap lines cannot be extracted: {exc}")
        try:
            _verdict, trace_id, failures = code_agent.grade(
                self.mem, p.student_id, assignment, str(repo_dir / file_path),
                conn=cur.connection, llm_client=self.llm, budget=self.budget, scope=spec,
                attempt_id=p.attempt_id, commit_sha=p.sha, checkout_root=repo_dir,
                max_prompt_chars=self.code_prompt_cap)
        except code_agent.SubmissionSkipped as exc:
            return skip(str(exc))
        except FileNotFoundError:
            return skip(f"{file_path} is not in the checkout")
        except BudgetExceeded as exc:
            return skip(f"the {exc.cap} call cap is reached ({exc.used}/{exc.limit}), no call made")
        except SchemaValidationError:
            return skip("the judge's answer was not valid twice: nothing stored")
        used = len(code_agent.resolve_criteria(None, assignment))
        self._say(p, f"code_agent stored trace {trace_id} (rejected={bool(failures)}, "
                     f"{used} criteria)  ({self.today()})")


def _make_hook(llm, run_cap, daily_cap, ledger, mem, out, *, code_agent_on=False,
               code_prompt_cap=DEFAULT_CODE_PROMPT_CAP, agents_v2=False) -> AgentsHook | None:
    """None (with the reason printed) when the agents cannot be set up: the cycle goes on without
    them. A bad ledger file fails CLOSED: unknown usage means no spending."""
    try:
        if llm is None:
            from system import llm as gateway  # only now: --with-llm is the only caller
            llm = gateway
        ledger = ledger if ledger is not None else UsageLedger(DEFAULT_LEDGER_PATH)
        budget = CallBudget(max_calls=run_cap, day_cap=daily_cap, ledger=ledger)
    except Exception as exc:  # noqa: BLE001 -- LedgerCorrupt, bad caps, no gateway
        out(f"llm: DISABLED for this cycle, no agent will run ({type(exc).__name__}: "
            f"{str(exc).strip()[:200]})")
        return None
    return AgentsHook(llm, budget, mem, out, daily_cap, code_agent=code_agent_on,
                      code_prompt_cap=code_prompt_cap, agents_v2=agents_v2)


# --- plan mode ----------------------------------------------------------------------------------

# What one commit can cost, by the rule of the hook (see AgentsHook): the Feedback Agent has up to
# two judge() calls of 2 reserved provider calls each; the Code Agent has one judge() of 2.
FEEDBACK_MAX_CALLS = 4
CODE_AGENT_MAX_CALLS = 2


def _plan_report(roster, student, *, with_llm, with_code_agent, run_cap, daily_cap,
                 code_prompt_cap, ledger, conn, env, out) -> CycleResult:
    """Say what a cycle WOULD do to the commits it can see, and which agent each would reach.

    Reads only: no collection, no network, no grading, no LLM call, no write of any kind (the
    session is read-only unless a test hands in its own connection). Commits that are still on
    GitHub and have not been collected are NOT listed: finding them takes a network call, which
    plan mode never makes.
    Commits that are already graded are not listed either: the hook runs at grading time only, so
    nothing will ever run an agent on them."""
    all_repos = roster_repos(roster)
    repo_for = roster_repo_for(roster)
    student_ids = list(dict.fromkeys(r["student_id"] for r in all_repos))
    if student is not None:
        student_ids = [s for s in student_ids if s == student]
        if not student_ids:
            msg = f"student {student!r} is not in the roster"
            out(msg)
            return CycleResult(EXIT_STUDENT_FAILED, message=msg)

    out("PLAN (read-only: nothing is collected, graded, called or written)")
    out(f"agents    : --with-llm {'ON' if with_llm else 'off'}, --with-code-agent "
        f"{'ON' if with_code_agent else 'off'}")
    provider = (env.get("LLM_PROVIDER") or "").strip() or "NOT SET"
    used_today = "unreadable"
    try:
        led = ledger if ledger is not None else UsageLedger(DEFAULT_LEDGER_PATH)
        used_today = str(led.day_total())
    except Exception as exc:  # noqa: BLE001 -- a bad ledger file is reported, not fatal here
        used_today = f"unreadable ({type(exc).__name__}), a real run would refuse to spend"
    out(f"calls     : run cap {run_cap}, daily cap {daily_cap}, used today {used_today}; "
        f"LLM_PROVIDER {provider}")
    out(f"per commit: a FAILING commit -> Feedback Agent, at most {FEEDBACK_MAX_CALLS} budgeted "
        f"calls; an all-PASSING commit -> Code Agent, at most {CODE_AGENT_MAX_CALLS}; never both "
        f"on one commit ({FEEDBACK_MAX_CALLS + CODE_AGENT_MAX_CALLS} if the rule ever allowed it)")
    out(f"size cap  : the Code Agent skips judged text above {code_prompt_cap} characters")

    own = conn is None
    try:
        c = db._open() if own else conn
        if own:
            c.set_session(readonly=True)
    except Exception as exc:  # noqa: BLE001
        msg = f"DATABASE UNREACHABLE: {type(exc).__name__}: {str(exc).strip()[:200]}"
        out(msg)
        return CycleResult(EXIT_DB_DOWN, message=msg)
    reaching = 0
    try:
        cur = c.cursor()
        for sid in student_ids:
            pending, skipped = gc.find_pending(cur, repo_for, student=sid)
            cur.execute("SELECT count(DISTINCT t.commit_sha) FROM test_results t"
                        " JOIN attempts a USING (attempt_id) WHERE a.student_id = %s", (sid,))
            graded = cur.fetchone()[0]
            out(f"[{sid}] {len(pending)} stored commit(s) waiting to be graded; {graded} already "
                f"graded (they never reach the hook); {skipped['unattributed_commits']} "
                f"unattributed, {skipped['post_freeze_commits_skipped']} after a freeze "
                "(not graded)")
            for p in pending:
                head = f"  {p.assignment_id} attempt {p.attempt_no}  {p.sha[:10]}  committed " \
                       f"{p.committed_at:%Y-%m-%d %H:%M}"
                if p.owner is None:
                    out(f"{head}\n      NOT graded: no roster entry for this student/assignment")
                    continue
                if pf.is_template_commit(cur, p.sha):
                    out(f"{head}\n      graded, then NO agent: template push (D-098; recognised "
                        "from its message and position, so a delivered repo's push is certain only "
                        "once graded)")
                    continue
                if not with_llm:
                    out(f"{head}\n      graded, then no agent (--with-llm is off)")
                    continue
                reaching += 1
                lines = [f"{head}", "      graded, then:",
                         f"        a check fails       -> Feedback Agent "
                         f"(<= {FEEDBACK_MAX_CALLS} calls)"]
                if with_code_agent:
                    lines.append("        all checks pass     -> Code Agent (<= "
                                 f"{CODE_AGENT_MAX_CALLS} calls), if " + _code_ready(cur, p))
                lines.append("        status not ok / no tests -> no agent")
                out("\n".join(lines))
    finally:
        if own:
            c.rollback()
            c.close()
    worst = reaching * FEEDBACK_MAX_CALLS
    out(f"total     : {reaching} stored commit(s) would reach the hook; worst case {worst} "
        f"budgeted call(s), and the run cap stops it at {run_cap}")
    out("not listed: commits still on GitHub and not yet collected (plan mode makes no network "
        "call)")
    return CycleResult(EXIT_OK)


def _code_ready(cur, p) -> str:
    """What can be said about a pending commit's Code Agent preconditions before its file exists."""
    try:
        assignment, file_path = agents_pipeline.load_assignment_inputs(cur, p.assignment_id)
    except ValueError as exc:
        return f"NOT judgeable ({exc})"
    if not file_path:
        return "NOT judgeable (the assignment has no file_path)"
    try:
        spec = scope_mod.scope_spec_for_attempt(cur, p.attempt_id)
    except scope_mod.ScopeUnavailable as exc:
        return f"NOT judgeable ({exc})"
    criteria = ", ".join(assignment["criteria"])
    return (f"the gap lines of {file_path} can be extracted ({len(spec.hide_gap_ids)} hidden "
            f"gap(s); criteria: {criteria}); the file itself and the size cap are checked at "
            "grading")


# --- the stages -------------------------------------------------------------------------------

def _stage_collect(res, sid, repos, conn, collect, dry_run, out):
    if dry_run:
        out(f"  collect   WOULD collect {len(repos)} roster row(s) from GitHub (dry-run: "
            "no network, nothing written)")
        return
    with _unit(conn, "collect") as c:
        cur = c.cursor()
        before = (_count(cur, "raw_commits", sid), _count(cur, "raw_workflow_runs", sid))
        outcome = collect(c, repos)
        after = (_count(cur, "raw_commits", sid), _count(cur, "raw_workflow_runs", sid))
    res.commits_added, res.runs_added = after[0] - before[0], after[1] - before[1]
    for failed in outcome.get("failed", []):
        res.errors.append(f"collect {failed['repo']}: {failed['error']}")
    out(f"  collect   +{res.commits_added} commit(s), +{res.runs_added} run(s)"
        + (f", {len(outcome.get('failed', []))} repo(s) FAILED" if outcome.get("failed") else ""))


def _stage_grade(res, sid, repo_for, conn, checkout, grade, dry_run, out, hook=None):
    with _unit(conn, "grade") as c:
        summary = gc.run(student=sid, dry_run=dry_run, repo_for=repo_for,
                         checkout=checkout, grade=grade, conn=c,
                         after_grade=hook.bind(c) if hook is not None and not dry_run else None)
    res.pending = summary["pending"]
    res.post_freeze_skipped = summary["post_freeze_commits_skipped"]
    if dry_run:
        out(f"  grade     WOULD grade {len(summary['would_grade'])} commit(s)"
            f" ({summary['unattributed_commits']} unattributed, "
            f"{summary['post_freeze_commits_skipped']} after a freeze, not graded)")
        return
    res.graded = len(summary["graded"])
    res.frozen = sum(1 for g in summary["graded"] if g[4])
    for label, err in summary["failed"]:
        res.errors.append(f"grade {label}: {err}")
    for label, err in summary["agent_errors"]:          # reported, never an error of the student
        out(f"  llm       AGENT ERROR {label}: {err}")
    out(f"  grade    {res.graded} graded, {res.frozen} attempt(s) frozen, "
        f"{len(summary['failed'])} failed, {len(summary['no_repo'])} without a repo, "
        f"{res.post_freeze_skipped} after a freeze (not graded)")


def _stage_features(res, sid, conn, dry_run, out):
    with _unit(conn, "features") as c:
        cur = c.cursor()
        if not _needs_features(cur, sid):
            res.features = "up to date"
            out("  features up to date (a row already sits at the watermark, or no activity)")
            return
        if dry_run:
            res.features = "would compute"
            out("  features WOULD compute a learner_features row")
            return
        cur.execute("SELECT count(*) FROM learner_features WHERE student_id = %s", (sid,))
        before = cur.fetchone()[0]
        cf.run(only=[sid], conn=c)
        cur.execute("SELECT count(*) FROM learner_features WHERE student_id = %s", (sid,))
        res.features = "written" if cur.fetchone()[0] > before else "skipped"
    out(f"  features {res.features}")


def _stage_profile(res, sid, mem, conn, dry_run, out):
    with _unit(conn, "profile") as c:
        if not mem.features_ref_is_stale(sid, conn=c):
            res.profile = "current"
            out("  profile   features_ref current")
            return
        if dry_run:
            res.profile = "would sync"
            out("  profile   WOULD sync features_ref")
            return
        mem.sync_features_ref(sid, conn=c)
        res.profile = "synced"
    out("  profile   features_ref synced")


# --- the cycle --------------------------------------------------------------------------------

def run_cycle(roster: dict, *, student: str | None = None, dry_run: bool = False,
              skip_network: bool = False, with_llm: bool = False, conn=None,
              collect=collect_all, checkout=gc.checkout_commit, grade=grade_attempt,
              out=print, llm_run_cap: int = DEFAULT_LLM_RUN_CAP,
              llm_daily_cap: int = DEFAULT_LLM_DAILY_CAP, llm=None, ledger=None,
              with_code_agent: bool = False, code_prompt_cap: int = DEFAULT_CODE_PROMPT_CAP,
              plan: bool = False, env=None, agents_v2: bool = False) -> CycleResult:
    """Run one cycle over `roster`. Never raises for a single student's failure.

    `conn`: tests only (see `_unit`). `collect` / `checkout` / `grade` are injectable so the
    tests use a fake GitHub layer: no network is needed to exercise the whole cycle. `llm` /
    `ledger`: tests only (a `FakeLLM` and an in-memory `UsageLedger`); the defaults are
    `system.llm` and the `.vdel/llm_usage.json` file. `env`: the environment plan mode reports on
    (default `os.environ`).

    `with_code_agent` (D-104) and `agents_v2` (D-108) are refused unless `with_llm` is also set.
    `plan=True` reads and prints only (see `_plan_report`)."""
    if agents_v2 and not with_llm:
        msg = ("REFUSED: --agents-v2 runs only together with --with-llm (it changes how the agents "
               "work, behind the same call caps). Nothing was done.")
        out(msg)
        return CycleResult(EXIT_REFUSED, message=msg)
    if with_code_agent and not with_llm:
        msg = ("REFUSED: --with-code-agent runs only together with --with-llm (the Code Agent is a "
               "second agent of the same hook, behind the same call caps). Nothing was done.")
        out(msg)
        return CycleResult(EXIT_REFUSED, message=msg)
    if plan:
        return _plan_report(roster, student, with_llm=with_llm, with_code_agent=with_code_agent,
                            run_cap=llm_run_cap, daily_cap=llm_daily_cap,
                            code_prompt_cap=code_prompt_cap, ledger=ledger, conn=conn,
                            env=os.environ if env is None else env, out=out)
    lock_conn = None
    try:
        lock_conn = db._open()                  # also the fail-fast "is the database there?"
        lock_conn.autocommit = True
        with lock_conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
            acquired = cur.fetchone()[0]
    except Exception as exc:  # noqa: BLE001 -- any failure to connect is the same message
        if lock_conn is not None:
            lock_conn.close()
        msg = f"DATABASE UNREACHABLE: {type(exc).__name__}: {str(exc).strip()[:200]}"
        out(msg)
        return CycleResult(EXIT_DB_DOWN, message=msg)
    if not acquired:
        lock_conn.close()
        msg = ("ANOTHER CYCLE IS RUNNING (advisory lock held): exiting without doing "
               "anything. Wait for it to finish.")
        out(msg)
        return CycleResult(EXIT_LOCKED, message=msg)

    try:
        return _run_locked(roster, student, dry_run, skip_network, with_llm, conn,
                           collect, checkout, grade, out,
                           {"llm": llm, "run_cap": llm_run_cap, "daily_cap": llm_daily_cap,
                            "ledger": ledger, "code_agent": with_code_agent,
                            "code_prompt_cap": code_prompt_cap, "agents_v2": agents_v2})
    finally:
        lock_conn.close()                 # closing the session releases the advisory lock


def _run_student(sid, repos, repo_for, mem, conn, skip_network, dry_run,
                 collect, checkout, grade, out, hook=None) -> StudentResult:
    """All stages for ONE student. An exception in a stage is recorded on the result and the
    next stage still runs; nothing here can stop another student."""
    out(f"[{sid}]")
    res = StudentResult(sid)
    _warn_unrostered(conn, sid, repo_for, out)
    stages = []
    if not skip_network:
        stages.append(("collect", lambda: _stage_collect(
            res, sid, repos, conn, collect, dry_run, out)))
        stages.append(("grade", lambda: _stage_grade(
            res, sid, repo_for, conn, checkout, grade, dry_run, out, hook)))
    else:
        out("  collect/grade skipped (--skip-network)")
    stages.append(("features", lambda: _stage_features(res, sid, conn, dry_run, out)))
    stages.append(("profile", lambda: _stage_profile(res, sid, mem, conn, dry_run, out)))
    for name, stage in stages:
        try:
            stage()
        except Exception as exc:  # noqa: BLE001 -- isolation: record and carry on
            res.errors.append(f"{name}: {type(exc).__name__}: {str(exc).strip()[:300]}")
            out(f"  {name:<9} FAILED: {type(exc).__name__}: {str(exc).strip()[:300]}")
    return res


def _run_locked(roster, student, dry_run, skip_network, with_llm, conn,
                collect, checkout, grade, out, llm_settings=None) -> CycleResult:
    all_repos = roster_repos(roster)
    repo_for = roster_repo_for(roster)
    student_ids = list(dict.fromkeys(r["student_id"] for r in all_repos))
    if student is not None:
        student_ids = [s for s in student_ids if s == student]
        if not student_ids:
            msg = f"student {student!r} is not in the roster"
            out(msg)
            return CycleResult(EXIT_STUDENT_FAILED, message=msg)

    mode = "DRY-RUN (reads only)" if dry_run else "LIVE"
    out(f"cycle: {len(student_ids)} student(s), {mode}"
        + (", network skipped" if skip_network else ""))
    mem = Memory()
    hook = None
    if with_llm and dry_run:
        out("llm: dry-run, no agent will be called")
    elif with_llm and skip_network:
        out("llm: grading is skipped (--skip-network), so no commit reaches an agent")
    elif with_llm:
        cfg = llm_settings or {}
        run_cap, daily_cap = cfg.get("run_cap", 0), cfg.get("daily_cap", 0)
        hook = _make_hook(cfg.get("llm"), run_cap, daily_cap, cfg.get("ledger"), mem, out,
                          code_agent_on=cfg.get("code_agent", False),
                          code_prompt_cap=cfg.get("code_prompt_cap", DEFAULT_CODE_PROMPT_CAP),
                          agents_v2=cfg.get("agents_v2", False))
        if hook is not None:
            out(f"llm: ON, run cap {run_cap}, daily cap {daily_cap} provider call(s) "
                f"({hook.today()}); Code Agent {'ON' if hook.code_agent else 'off'}"
                + ("; agents v2 ON" if hook.agents_v2 else ""))
    # The real ceiling (D-104): every provider handler is wrapped for the run, so the run cap and
    # what is left of the daily cap hold even when the gateway walks its fallback chain, which the
    # budget (it counts answers, not failed attempts) cannot see.
    ceiling = None
    if hook is not None:
        left = max(0, hook.daily_cap - hook.budget.ledger.day_total())
        ceiling = HardCap(min(hook.budget.max_calls, left))
    with ceiling if ceiling is not None else contextlib.nullcontext():
        results = [_run_student(sid, [r for r in all_repos if r["student_id"] == sid], repo_for,
                                mem, conn, skip_network, dry_run, collect, checkout, grade, out,
                                hook)
                   for sid in student_ids]
    if ceiling is not None:
        counted = sum(hook.budget.by_model.values())
        extra = ceiling.count - counted
        if extra > 0:                       # failed fallback attempts the gateway does not record
            hook.budget.ledger.add({"uncounted_fallback_attempts": extra})
        out(f"llm: {ceiling.count} real provider call(s) this run"
            + (f" ({extra} not in the gateway's records, added to today's count)" if extra > 0
               else "") + f"  ({hook.today()})")

    out("")
    out(f"{'student':<14}{'+commits':>9}{'+runs':>7}{'graded':>8}{'frozen':>8}"
        f"  {'features':<14}{'profile':<12}status")
    for r in results:
        out(f"{r.student_id:<14}{r.commits_added:>9}{r.runs_added:>7}{r.graded:>8}"
            f"{r.frozen:>8}  {r.features:<14}{r.profile:<12}{'ok' if r.ok else 'FAILED'}")
        for e in r.errors:
            out(f"    ! {e}")
    failed = [r for r in results if not r.ok]
    code = EXIT_STUDENT_FAILED if failed else EXIT_OK
    out(f"cycle done: {len(results) - len(failed)} ok, {len(failed)} failed -> exit {code}")
    return CycleResult(code, results)


def add_llm_arguments(parser: argparse.ArgumentParser) -> None:
    """The three agent options, shared with run_hourly so the two commands cannot drift."""
    parser.add_argument("--with-llm", action="store_true",
                        help="after each graded commit run the Feedback Agent (OFF by default; "
                             "makes billed provider calls)")
    parser.add_argument("--with-code-agent", action="store_true",
                        help="ALSO run the Code Agent on a commit whose checks all passed (OFF by "
                             "default; needs --with-llm; its verdict is stored, never posted)")
    parser.add_argument("--agents-v2", action="store_true",
                        help="use the v2 agents (OFF by default; needs --with-llm): the Feedback "
                             "Agent sees the student's own lines and gives a hint ladder")
    parser.add_argument("--code-agent-max-chars", type=int, default=DEFAULT_CODE_PROMPT_CAP,
                        help="skip the Code Agent when the judged lines plus context are longer "
                             "than this (default %(default)s)")
    parser.add_argument("--llm-run-cap", type=int, default=DEFAULT_LLM_RUN_CAP,
                        help="max provider calls in this run (default %(default)s)")
    parser.add_argument("--llm-daily-cap", type=int, default=DEFAULT_LLM_DAILY_CAP,
                        help="max provider calls per day, all runs (default %(default)s)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--student", help="only this student_id")
    parser.add_argument("--roster", default=None,
                        help="roster file (default config/roster.yaml)")
    parser.add_argument("--dry-run", action="store_true",
                        help="read only: say what a cycle would do, write nothing")
    parser.add_argument("--skip-network", action="store_true",
                        help="skip collect and grade (both need GitHub)")
    parser.add_argument("--plan", action="store_true",
                        help="read only: list the stored commits that WOULD reach the hook and "
                             "which agent each would run; no network, no grading, no LLM")
    add_llm_arguments(parser)
    args = parser.parse_args(argv)
    result = run_cycle(load_roster(args.roster), student=args.student, dry_run=args.dry_run,
                       skip_network=args.skip_network, with_llm=args.with_llm,
                       llm_run_cap=args.llm_run_cap, llm_daily_cap=args.llm_daily_cap,
                       with_code_agent=args.with_code_agent,
                       code_prompt_cap=args.code_agent_max_chars, plan=args.plan,
                       agents_v2=args.agents_v2)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
