"""assessment/test_runner.py -- run one assignment's hidden tests against a real repo,
in a separate process, and record what actually happened.

This is the component D-045 makes load-bearing: an assignment freezes when, and only
when, its hidden tests reach 100% pass (D-045a). This module is where that freeze
happens -- collectors/collect_github.py deliberately does NOT write
attempts.commit_sha/submitted_at (it sees pushes, not test outcomes; an earlier version
froze on first push and was reverted, commit b9bc62b). Every commit's outcome, pass or
fail, is recorded to `test_results` keyed by commit (D-045c) so a student's pre-freeze
failure history survives -- that history is what V5/V6 are computed from (EXECUTION.md
Stage C1), and every test outcome is one BKT observation for V1, not just the freeze
event.

INVARIANT 12 / 13 BOUNDARY (CLAUDE.md, reconciled in EXECUTION.md 3.3): invariant 12 says
no AGENT ever executes submitted code; invariant 13 says correctness is decided by
EXECUTED tests, never asserted by an LLM. Both hold because they describe different
processes -- tests execute HERE, in a subprocess, never inside an agent's process; an
agent only ever reads the resulting `test_results` rows. This module is therefore not
merely conventionally separate from agents/ -- it imports NOTHING from agents/ or
system/llm.py, checked by grep before every commit that touches this file, so that
boundary is structural, not a comment someone has to remember to keep true.

Real limitation, stated rather than pretended away: subprocess isolation is
PROCESS-level only -- no container, no sandbox, no resource cap beyond a wall-clock
timeout. Acceptable for this project's v1 scope (a single known curriculum, run by the
person who owns the machine), not acceptable for untrusted multi-tenant grading. That
line is deliberately not crossed here.

`test_results.gap_id` is populated via `@pytest.mark.gap("g_id")`, read from JUnit XML
`<properties>` (D-046) -- STALE NOTE CORRECTED: an earlier version of this docstring said
gap_id was left NULL with no attribution mechanism; that was true before D-046 and is not
true now. `_gap_id_from_case` below is the real mechanism.

MASTERY WIRING (D-045/D-046, EXECUTION.md Stage C1): every commit's test outcomes are
also logged as `test_result` traces through `memory.Memory` -- never raw SQL to `traces`
(invariant 2) -- so V1 (BKT), V5 (Error Response) and V6 (Error Frequency) can read the
full pre-freeze failure history, not just whatever survives to the frozen commit. Traced
ONLY for outcomes carrying a real `gap_id` (untagged tests have no concept to attribute
evidence to -- see `_gap_id_from_case`) and ONLY for genuinely NEW `test_results` rows
(`_write_test_results`'s `xmax = 0` check) -- re-grading an already-recorded commit must
not silently inflate `n`, the observation count invariant 8 makes load-bearing.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from psycopg2.extras import execute_values

from memory.memory import Memory
from system import db

CURRICULUM_ROOT = Path(__file__).resolve().parent.parent / "curriculum" / "master"


@contextmanager
def _session(conn):
    """Join the caller's transaction, or own one for the duration of this call --
    memory.py's own `_session` pattern, replicated rather than imported (it is a
    module-private helper there, not part of `Memory`'s public surface).

    Why `grade_attempt` needs this at all: `traces` is append-only at the database
    level (a Postgres RULE makes DELETE a silent no-op, confirmed live -- `rowcount: 0`,
    no error), so once this function logs a real `test_result` trace there is no SQL
    that can ever clean it up. A test that calls the real `grade_attempt` therefore
    cannot use DELETE-based teardown the way every other synthetic-data test in this
    project does -- it must instead run inside a transaction that is ROLLED BACK, never
    committed, which is exactly what passing a `conn` through (and never calling
    `conn.commit()` on it) makes possible. Accepting `conn=None` and opening/committing
    an owned one is the live-path default; nothing about production grading changes.
    """
    if conn is not None:
        yield conn
    else:
        with db.connect() as owned:
            yield owned

# Wall-clock ceiling for one assignment's hidden-test run. Generous for four small ETL
# functions; exists so a student's accidental infinite loop or hung network call cannot
# hang the runner indefinitely -- the one resource control this process-level isolation
# does provide (see module docstring's stated limitation).
_TIMEOUT_S = 120


@dataclass(frozen=True)
class TestOutcome:
    test_name: str
    passed: bool
    message: str | None
    gap_id: str | None    # D-046: from @pytest.mark.gap("g_..."), NOT from the test name


@dataclass(frozen=True)
class RunResult:
    """What one `grade_attempt` call actually did -- returned, not just written to the
    DB, so a caller (or a demo script) can report it without a second query."""

    outcomes: tuple[TestOutcome, ...]
    tests_passed: int
    tests_total: int
    frozen: bool


class TestRunnerError(RuntimeError):
    """A grading run could not be completed at all -- no hidden test file for this
    assignment's stage, or pytest itself failed to produce a report. Distinct from a
    STUDENT's tests failing, which is not an error, it is the normal, expected outcome
    `RunResult` reports."""


def _hidden_test_file(project_id: str, file_path: str) -> Path:
    """The curriculum convention this session established: an assignment's hidden tests
    live at `tests/hidden/test_<stage>.py`, where `<stage>` is the stem of its
    `file_path` ('extract' from 'weather_etl/extract.py'). Verified against all four
    weather_etl assignments before being relied on here, not assumed from one example.
    """
    stage = Path(file_path).stem
    path = CURRICULUM_ROOT / project_id / "tests" / "hidden" / f"test_{stage}.py"
    if not path.exists():
        raise TestRunnerError(
            f"no hidden test file for project {project_id!r} stage {stage!r}: {path}"
        )
    return path


def _inject_hidden_test(repo_dir: Path, project_id: str, test_src: Path) -> str:
    """Copies the ONE hidden test file this assignment needs into the target repo, PLUS
    the shared `conftest.py` that turns its `@pytest.mark.gap(...)` markers into JUnit
    XML properties (D-046) -- without it, every gap_id would silently come back as None,
    since a bare marker with no hook does not reach --junitxml output at all (verified
    empirically before this convention was adopted; see conftest.py's own docstring).

    Never the whole tests/hidden/ directory otherwise -- render_student_repo.py's own
    invariant (never let tests/hidden reach a student) applies here with the same force:
    this function's caller is grading a real repo, not authoring a student's copy of it,
    but injecting every OTHER assignment's hidden tests too would leak them for no reason
    this single-assignment grading run needs.

    conftest.py is copied unconditionally on every call (cheap, idempotent overwrite) --
    simpler and safer than tracking whether it is "already there," and correct even if a
    project's conftest.py changes between two grading runs of the same repo.

    Returns the test file's path relative to `repo_dir`, in POSIX form, for the
    subprocess command line -- `Path` on Windows renders backslashes, which pytest
    accepts on the CLI but which would make the stored test identity
    platform-dependent for no reason.
    """
    dest_dir = repo_dir / "tests" / "hidden"
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / test_src.name
    dest.write_text(test_src.read_text(encoding="utf-8"), encoding="utf-8")

    conftest_src = CURRICULUM_ROOT / project_id / "tests" / "hidden" / "conftest.py"
    if conftest_src.exists():
        (dest_dir / "conftest.py").write_text(
            conftest_src.read_text(encoding="utf-8"), encoding="utf-8"
        )

    return f"tests/hidden/{test_src.name}"


def _run_pytest(repo_dir: Path, test_rel_path: str, junit_path: Path) -> None:
    """The one subprocess call in this module -- see the module docstring's invariant
    12/13 note for why this MUST be a real subprocess and never an in-process pytest.main()
    call: a separate process is what makes "executes here, not inside an agent" a fact
    about the operating system rather than a fact about which function called which.

    `sys.executable`, not a bare "python", so this runs under the SAME interpreter (and
    therefore the same installed packages) as the process that invoked grading -- a
    student repo has no venv of its own, it reuses this project's.

    Exit code is deliberately not checked here: pytest exits non-zero when tests FAIL,
    which is the normal, expected case this function exists to observe, not an error
    condition. `_parse_junit` is what decides pass/fail per test; a genuinely broken run
    (test file doesn't parse, no junit report written) is caught there instead.
    """
    subprocess.run(
        [sys.executable, "-m", "pytest", test_rel_path,
         f"--junitxml={junit_path}", "-q", "--tb=line"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
    )


def _gap_id_from_case(case: ET.Element) -> str | None:
    """D-046: the `<properties><property name="gap_id" value="..."/></properties>`
    child `conftest.py`'s `pytest_collection_modifyitems` writes from the test's
    `@pytest.mark.gap(...)`. A test with no marker has no `<properties>` element at all
    (verified, not assumed -- see conftest.py's docstring), so `None` here means
    honestly "this test declares no gap," never a parse failure disguised as one.
    """
    props = case.find("properties")
    if props is None:
        return None
    for prop in props.findall("property"):
        if prop.get("name") == "gap_id":
            return prop.get("value")
    return None


def _parse_junit(junit_path: Path) -> list[TestOutcome]:
    """JUnit XML, not stdout scraping -- pytest's own structured report, immune to `-q`
    output formatting changing between versions. A skipped test is EXCLUDED, not counted
    as either pass or fail: this curriculum's hidden tests are not written to skip, so a
    skip here is itself a signal something is wrong with the run, and folding it into
    tests_total either direction would misrepresent what 100%-pass actually means.
    """
    if not junit_path.exists():
        raise TestRunnerError(
            f"pytest produced no junit report at {junit_path} -- the run did not "
            "complete (see module docstring: this is distinct from tests failing)"
        )
    root = ET.parse(junit_path).getroot()
    outcomes = []
    for case in root.iter("testcase"):
        if case.find("skipped") is not None:
            continue
        failure = case.find("failure")
        error = case.find("error")
        message = None
        if failure is not None:
            message = (failure.get("message") or failure.text or "")[:2000]
        elif error is not None:
            message = (error.get("message") or error.text or "")[:2000]
        outcomes.append(TestOutcome(
            test_name=f"{case.get('classname')}::{case.get('name')}",
            passed=failure is None and error is None,
            message=message,
            gap_id=_gap_id_from_case(case),
        ))
    return outcomes


def _write_test_results(cur, attempt_id: int, commit_sha: str | None,
                         outcomes: list[TestOutcome]) -> set[str]:
    """One row per test per commit (D-045c) -- never overwrites a DIFFERENT commit's
    row, which is the entire point of keying by commit instead of by attempt.

    Two separate ON CONFLICT targets because commit_sha is nullable and the two partial
    unique indexes in sql/06 are mutually exclusive by construction (one WHERE commit_sha
    IS NOT NULL, one WHERE commit_sha IS NULL) -- a single ON CONFLICT clause cannot name
    both arbiter indexes at once, and every row in ONE call shares the same commit_sha
    (grade_attempt takes one commit_sha per call), so choosing the target once per call,
    not per row, is correct, not a shortcut.

    Returns the `test_name`s that were genuinely NEW this call (a real INSERT, not an
    UPDATE via the ON CONFLICT path) -- `xmax = 0` is the standard Postgres idiom for
    this (a freshly inserted row's `xmax` system column is 0; a row reached via
    ON CONFLICT DO UPDATE has a real one). This is how the caller avoids double-counting
    a re-grade of an already-recorded commit as a second BKT observation.
    """
    if not outcomes:
        return set()
    # D-046: gap_id is NOT validated against the real `gaps` table here -- the FK on
    # test_results.gap_id already enforces that a bogus value cannot land silently; a
    # violation surfaces as a real, loud FK error rather than this function guessing
    # what to do about it.
    rows = [
        (attempt_id, commit_sha, o.test_name, o.gap_id, o.passed, o.message)
        for o in outcomes
    ]
    if commit_sha is not None:
        result = execute_values(cur, """
            INSERT INTO test_results
                (attempt_id, commit_sha, test_name, gap_id, passed, message)
            VALUES %s
            ON CONFLICT (attempt_id, commit_sha, test_name) WHERE commit_sha IS NOT NULL
            DO UPDATE SET gap_id = EXCLUDED.gap_id, passed = EXCLUDED.passed,
                          message = EXCLUDED.message, ran_at = now()
            RETURNING test_name, (xmax = 0) AS is_new
        """, rows, fetch=True)
    else:
        result = execute_values(cur, """
            INSERT INTO test_results
                (attempt_id, commit_sha, test_name, gap_id, passed, message)
            VALUES %s
            ON CONFLICT (attempt_id, test_name) WHERE commit_sha IS NULL
            DO UPDATE SET gap_id = EXCLUDED.gap_id, passed = EXCLUDED.passed,
                          message = EXCLUDED.message, ran_at = now()
            RETURNING test_name, (xmax = 0) AS is_new
        """, rows, fetch=True)
    return {test_name for test_name, is_new in result if is_new}


def _gap_metadata(cur, gap_ids: set[str]) -> dict[str, tuple[list[str], float]]:
    """`(concept_ids, difficulty)` per gap_id, one query for every gap this run's
    outcomes touch -- not one query per outcome, which would turn a run of N tests into
    N round-trips for no reason."""
    if not gap_ids:
        return {}
    cur.execute(
        "SELECT gap_id, concept_ids, difficulty FROM gaps WHERE gap_id = ANY(%s)",
        (list(gap_ids),),
    )
    return {gid: (list(concept_ids), float(difficulty))
            for gid, concept_ids, difficulty in cur.fetchall()}


def _log_mastery_traces(mem: Memory, conn, student_id: str, assignment_id: str,
                         commit_sha: str | None, outcomes: list[TestOutcome],
                         new_test_names: set[str], gap_meta: dict) -> None:
    """One `test_result` trace per genuinely-new, gap-tagged outcome (EXECUTION.md Stage
    C1, memory.py's MASTERY_TRACE_KINDS docstring), THEN one `update_mastery` per
    concept touched -- through `memory.Memory` only, no raw SQL to `traces` or
    `learner_profile` here (invariant 2). Both steps, not just the first: logging a
    trace alone leaves the evidence sitting in the log unread until some later batch
    job replays it, and "a real mastery update, live" means `learner_profile.mastery`
    changes NOW, in this same transaction -- the same two-step fast-path shape
    `agents/code_agent.py::grade` already uses after logging its own verdict trace
    (`log_trace` then `for concept in concepts: mem.update_mastery(...)`).

    Two filters on WHICH traces get logged, both load-bearing, neither optional:
      - `new_test_names` (from `_write_test_results`'s `xmax = 0` check): re-grading an
        already-recorded commit must not log a second observation for the same evidence
        -- that would silently inflate `n`, which invariant 8 makes load-bearing.
      - `o.gap_id is not None`: an untagged test has no concept to attribute evidence
        to. Silently attributing it to nothing would be worse than not logging it.

    `conclusion` uses the exact two-value vocabulary `ci_run` already established
    (`memory.OUTCOME`'s keys) -- one vocabulary for "did this pass", not a second one
    that could drift from the first.

    `update_mastery` is called once per DISTINCT concept touched this call, not once
    per trace -- calling it twice for the same concept in one pass would be wasted work
    (it is idempotent, per its own docstring, so not WRONG, just redundant).
    """
    # concept -> the trace_id of the MOST RECENT outcome that touched it this call, so
    # each update_mastery below cites the specific evidence that most directly prompted
    # it, not an arbitrary "whichever trace happened to be logged last overall" -- this
    # only affects the causal-forest link (parent_trace_id), never the computed numbers
    # (update_mastery replays the whole log regardless of which trace_id it is given).
    concept_to_trace_id: dict[str, int] = {}
    for o in outcomes:
        if o.test_name not in new_test_names or o.gap_id is None:
            continue
        meta = gap_meta.get(o.gap_id)
        if meta is None:
            continue   # gap_id didn't resolve against `gaps` -- nothing to attribute
        concept_ids, difficulty = meta
        trace_id = mem.log_trace(
            student_id, "system", "test_result",
            {"conclusion": "success" if o.passed else "failure",
             "item_difficulty": difficulty},
            assignment_id=assignment_id, concept_ids=concept_ids, conn=conn,
        )
        for concept in concept_ids:
            concept_to_trace_id[concept] = trace_id

    for concept, trace_id in concept_to_trace_id.items():
        mem.update_mastery(student_id, concept, parent_trace_id=trace_id, conn=conn)


def _maybe_freeze(cur, attempt_id: int, commit_sha: str | None,
                   tests_passed: int, tests_total: int) -> bool:
    """D-045a, enforced here and ONLY here (collect_github.py explicitly does not).

    Freezing requires a REAL commit_sha: `attempts.commit_sha REFERENCES
    raw_commits(sha)` (sql/06), so a local run against a rendered-but-unpushed repo
    (commit_sha is None) can legitimately reach 100% pass without ever freezing -- there
    is no real commit yet to record as "the commit that froze this attempt"
    (attempts.commit_sha's own documented meaning). That is correct, not a bug: freeze
    means a real, pushed submission passed, not "the code on disk happens to pass."

    `WHERE submitted_at IS NULL` guards against re-grading an already-frozen attempt
    silently rewriting what it froze on -- the same discipline D-041 already established
    for render_student_repo.py's own ON CONFLICT guard, applied here to a second writer
    of the same columns.
    """
    if commit_sha is None or tests_total == 0 or tests_passed != tests_total:
        return False
    cur.execute("""
        UPDATE attempts
        SET commit_sha = %s, submitted_at = now(),
            tests_passed = %s, tests_total = %s
        WHERE attempt_id = %s AND submitted_at IS NULL
    """, (commit_sha, tests_passed, tests_total, attempt_id))
    return cur.rowcount == 1


def grade_attempt(
    project_id: str, assignment_id: str, repo_dir: str | Path, attempt_id: int,
    *, commit_sha: str | None = None, conn=None,
) -> RunResult:
    """Run one assignment's hidden tests against `repo_dir` and record the outcome.

    `commit_sha=None` means a LOCAL run -- against a freshly rendered or manually
    checked-out repo, before anything has been pushed. Results are still written to
    `test_results` (a local run is still a real observation) but can never freeze the
    attempt (see `_maybe_freeze`). Pass a real `commit_sha` -- one already present in
    `raw_commits`, i.e. after `collect_github` has landed it -- to grade an actual push
    and allow freezing.

    `conn`: join the caller's transaction instead of opening/committing an owned one --
    see `_session`'s own docstring for why this exists (traces cannot be deleted once
    written, so a test that must leave no trace behind has to roll one back instead).
    The live path never passes this; it is here for exactly one caller, tests.

    Two separate DB round-trips, not one held across the subprocess call: the pytest
    run can take up to `_TIMEOUT_S`, and holding a transaction open for that long for no
    reason is the wrong shape, the same reasoning render_student_repo.py's own two-block
    split (_load_project, then the write loop) already follows. The SECOND round-trip
    holds a real `conn` (not just a cursor) for its whole duration -- `test_results`,
    the `test_result` traces (D-045/D-046), and the freeze UPDATE are one transaction,
    so a crash between them cannot leave mastery evidence logged with no corresponding
    `test_results` row, or a frozen attempt with no trace of what froze it.
    """
    with db.cursor() as cur:
        cur.execute(
            "SELECT file_path FROM assignments WHERE assignment_id = %s", (assignment_id,)
        )
        row = cur.fetchone()
    if row is None:
        raise TestRunnerError(f"unknown assignment_id {assignment_id!r}")
    file_path = row[0]

    repo_dir = Path(repo_dir)
    test_src = _hidden_test_file(project_id, file_path)
    test_rel_path = _inject_hidden_test(repo_dir, project_id, test_src)

    with tempfile.TemporaryDirectory() as tmp:
        junit_path = Path(tmp) / "results.xml"
        _run_pytest(repo_dir, test_rel_path, junit_path)
        outcomes = _parse_junit(junit_path)

    tests_total = len(outcomes)
    tests_passed = sum(1 for o in outcomes if o.passed)

    mem = Memory()
    with _session(conn) as c, c.cursor() as cur:
        cur.execute("SELECT student_id FROM attempts WHERE attempt_id = %s", (attempt_id,))
        student_row = cur.fetchone()
        if student_row is None:
            raise TestRunnerError(f"unknown attempt_id {attempt_id!r}")
        student_id = student_row[0]

        new_test_names = _write_test_results(cur, attempt_id, commit_sha, outcomes)
        gap_meta = _gap_metadata(cur, {o.gap_id for o in outcomes if o.gap_id is not None})
        _log_mastery_traces(mem, c, student_id, assignment_id, commit_sha,
                            outcomes, new_test_names, gap_meta)
        frozen = _maybe_freeze(cur, attempt_id, commit_sha, tests_passed, tests_total)

    return RunResult(
        outcomes=tuple(outcomes), tests_passed=tests_passed,
        tests_total=tests_total, frozen=frozen,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("assignment_id")
    parser.add_argument("repo_dir")
    parser.add_argument("attempt_id", type=int)
    parser.add_argument("--commit-sha", default=None)
    args = parser.parse_args(argv)

    result = grade_attempt(
        args.project_id, args.assignment_id, args.repo_dir, args.attempt_id,
        commit_sha=args.commit_sha,
    )
    print(f"{result.tests_passed}/{result.tests_total} passed"
          f" -- frozen={result.frozen}")
    for o in result.outcomes:
        status = "PASS" if o.passed else "FAIL"
        print(f"  {status}  {o.test_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
