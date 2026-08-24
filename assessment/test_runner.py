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

Also a real, stated limitation: `test_results.gap_id` is left NULL. No naming convention
or manifest maps a hidden test to the specific gap it exercises, and inventing one now
would be exactly the kind of guessed structure CLAUDE.md's "never invent" rule forbids --
a wrong gap_id would misattribute a mastery signal to the wrong concept, which is worse
than an honest NULL. Per-test-to-gap attribution is future work, not a gap in this file.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from psycopg2.extras import execute_values

from system import db

CURRICULUM_ROOT = Path(__file__).resolve().parent.parent / "curriculum" / "master"

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


def _inject_hidden_test(repo_dir: Path, test_src: Path) -> str:
    """Copies the ONE hidden test file this assignment needs into the target repo.
    Never the whole tests/hidden/ directory -- render_student_repo.py's own invariant
    (never let tests/hidden reach a student) applies here with the same force: this
    function's caller is grading a real repo, not authoring a student's copy of it, but
    injecting every OTHER assignment's hidden tests too would leak them for no reason
    this single-assignment grading run needs.

    Returns the path relative to `repo_dir`, in POSIX form, for the subprocess command
    line -- `Path` on Windows renders backslashes, which pytest accepts on the CLI but
    which would make the stored test identity platform-dependent for no reason.
    """
    dest_dir = repo_dir / "tests" / "hidden"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / test_src.name
    dest.write_text(test_src.read_text(encoding="utf-8"), encoding="utf-8")
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
        ))
    return outcomes


def _write_test_results(cur, attempt_id: int, commit_sha: str | None,
                         outcomes: list[TestOutcome]) -> None:
    """One row per test per commit (D-045c) -- never overwrites a DIFFERENT commit's
    row, which is the entire point of keying by commit instead of by attempt.

    Two separate ON CONFLICT targets because commit_sha is nullable and the two partial
    unique indexes in sql/06 are mutually exclusive by construction (one WHERE commit_sha
    IS NOT NULL, one WHERE commit_sha IS NULL) -- a single ON CONFLICT clause cannot name
    both arbiter indexes at once, and every row in ONE call shares the same commit_sha
    (grade_attempt takes one commit_sha per call), so choosing the target once per call,
    not per row, is correct, not a shortcut.
    """
    if not outcomes:
        return
    rows = [(attempt_id, commit_sha, o.test_name, o.passed, o.message) for o in outcomes]
    if commit_sha is not None:
        execute_values(cur, """
            INSERT INTO test_results (attempt_id, commit_sha, test_name, passed, message)
            VALUES %s
            ON CONFLICT (attempt_id, commit_sha, test_name) WHERE commit_sha IS NOT NULL
            DO UPDATE SET passed = EXCLUDED.passed, message = EXCLUDED.message,
                          ran_at = now()
        """, rows)
    else:
        execute_values(cur, """
            INSERT INTO test_results (attempt_id, commit_sha, test_name, passed, message)
            VALUES %s
            ON CONFLICT (attempt_id, test_name) WHERE commit_sha IS NULL
            DO UPDATE SET passed = EXCLUDED.passed, message = EXCLUDED.message,
                          ran_at = now()
        """, rows)


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
    *, commit_sha: str | None = None,
) -> RunResult:
    """Run one assignment's hidden tests against `repo_dir` and record the outcome.

    `commit_sha=None` means a LOCAL run -- against a freshly rendered or manually
    checked-out repo, before anything has been pushed. Results are still written to
    `test_results` (a local run is still a real observation) but can never freeze the
    attempt (see `_maybe_freeze`). Pass a real `commit_sha` -- one already present in
    `raw_commits`, i.e. after `collect_github` has landed it -- to grade an actual push
    and allow freezing.

    Two separate DB cursor blocks, not one held across the subprocess call: the pytest
    run can take up to `_TIMEOUT_S`, and holding a transaction open for that long for no
    reason is the wrong shape, the same reasoning render_student_repo.py's own two-block
    split (_load_project, then the write loop) already follows.
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
    test_rel_path = _inject_hidden_test(repo_dir, test_src)

    with tempfile.TemporaryDirectory() as tmp:
        junit_path = Path(tmp) / "results.xml"
        _run_pytest(repo_dir, test_rel_path, junit_path)
        outcomes = _parse_junit(junit_path)

    tests_total = len(outcomes)
    tests_passed = sum(1 for o in outcomes if o.passed)

    with db.cursor() as cur:
        _write_test_results(cur, attempt_id, commit_sha, outcomes)
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
