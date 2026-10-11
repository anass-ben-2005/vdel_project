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

SANDBOX (D-065) -- what it does, and what it does NOT do. The student's tests run in a
throwaway COPY of the repo (the original is never modified), as a subprocess with an explicit
environment allowlist (none of GITHUB_TOKEN, PG_DSN or any other `.env` key reaches it), with
every `conftest.py`, pytest config and `sitecustomize.py` the student wrote removed and the
trusted root `conftest.py` (render_student_repo.TEMPLATE_FILES) put in their place, with
pytest pointed at a config of ours (`-c`), and with the JUnit report written outside the
student's directory under a random name. That closes the cheap ways to forge a grade (a
conftest hook, `addopts`, a config file) and to read secrets from the environment.

It does NOT make the grading safe for untrusted code. Still possible: reading `.env` by
absolute path; any network call; exhausting CPU, memory or processes (only a wall-clock timeout
on the direct child); writing anywhere the Windows/Linux user can write; and tampering from
INSIDE the test process (the student's own module is imported by the hidden test, so it can
patch pytest, or read the JUnit path from `sys.argv` and overwrite it). A container -- no
network, read-only filesystem, non-root user, resource limits, and the JUnit/judge outside it --
is REQUIRED before the first real student. Until then this is for a known curriculum run by
the person who owns the machine.

D-069 (addendum to D-066 and D-065): a `collection_error` or a `timeout` row is stored with its
status but writes NO `test_result` mastery trace, and a pytest timeout is recorded once instead
of raising out of the grader.

COLLECTION ERRORS (D-066): when the hidden test file cannot be imported, the traceback decides.
It points into the student's code -> a real failure (`collection_error`, every `@gap` test of
that file recorded as failed). It points into our test file or tooling -> `tooling`, which is
NOT a failure and is never mastery evidence. Neither crashes the grader or is retried forever.

`test_results.gap_id` is populated via `@pytest.mark.gap("g_id")`, read from JUnit XML
`<properties>` (D-046) -- STALE NOTE CORRECTED: an earlier version of this docstring said
gap_id was left NULL with no attribution mechanism; that was true before D-046 and is not
true now. `_gap_id_from_case` below is the real mechanism.

MASTERY WIRING (D-045/D-046, D-079). Every commit's test outcomes are logged as `test_result`
traces through `memory.Memory` -- never raw SQL to `traces` (invariant 2) -- as EVIDENCE for V5
(Error Response) and V6 (Error Frequency): traced ONLY for outcomes carrying a real `gap_id`, ONLY
for gaps this attempt actually HID (D-054: a pre-solved gap's tests pass whatever the student did),
ONLY for genuinely NEW `test_results` rows (`xmax = 0`), and never for a `collection_error` /
`timeout` (D-069).

They are NOT mastery evidence any more (D-079, formula v5). The BKT item is the GAP, observed once
per attempt: the FIRST pushed commit (non-null commit_sha, status ok) in which the gap was
attempted, i.e. none of its hidden tests failed with NotImplementedError. All of the gap's hidden
tests passed -> success, otherwise failure. That is written as ONE `mastery_observation` trace per
(attempt, gap) by `Memory.record_mastery_observation` (idempotent: a re-grade or a later commit
writes nothing), attributed to the gap's FIRST concept, timed at the commit. A local run
(commit_sha None) is never a mastery observation. "First" is decided at write time, so commits
must be graded oldest first, which `scripts/grade_collected.py` does.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from psycopg2.extras import execute_values

from assessment.gap_parser import render_student_file_with_ranges
from assessment.scope_check import scope_check
from memory.memory import Memory
from system import db

CURRICULUM_ROOT = Path(__file__).resolve().parent.parent / "curriculum" / "master"

log = logging.getLogger(__name__)


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
# hang the runner indefinitely -- the ONLY resource control there is, and it bounds the
# direct child only (see the module docstring's SANDBOX section for what is not covered).
_TIMEOUT_S = 120


@dataclass(frozen=True)
class TestOutcome:
    test_name: str
    passed: bool
    message: str | None
    gap_id: str | None    # D-046: from @pytest.mark.gap("g_..."), NOT from the test name
    status: str = "ok"    # D-066/D-069: ok | collection_error | tooling | timeout


@dataclass(frozen=True)
class RunResult:
    """What one `grade_attempt` call actually did -- returned, not just written to the
    DB, so a caller (or a demo script) can report it without a second query."""

    outcomes: tuple[TestOutcome, ...]
    tests_passed: int
    tests_total: int
    frozen: bool
    status: str = "ok"          # D-066/D-069: ok | collection_error | tooling | timeout
    detail: str | None = None   # why, for the two non-ok statuses


@dataclass(frozen=True)
class Evaluation:
    """What running the hidden tests produced -- everything `grade_attempt` needs EXCEPT
    the database. Separate so a dry run can show exactly what would be recorded."""

    outcomes: tuple[TestOutcome, ...]
    status: str
    detail: str | None


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


# D-065. The ONLY environment variables the grading subprocess receives. Everything else the
# parent has -- GITHUB_TOKEN, PG_DSN, every LLM key, every other `.env` entry -- is absent
# inside the student's test process. What is here is what Python and pytest need to start on
# Windows and Linux; HOME/USERPROFILE and TEMP/TMP are NOT passed through but pointed at empty
# directories inside the sandbox, so the real home directory is not handed over either.
_ENV_PASSTHROUGH = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "LANG", "LC_ALL", "LC_CTYPE", "TZ",
)

# Files removed from the sandbox copy wherever they sit: anything that can change how pytest
# collects, configures or reports, or run code before pytest starts.
_SANDBOX_REMOVE = frozenset({
    "conftest.py", "pytest.ini", ".pytest.ini", "tox.ini", "sitecustomize.py", "usercustomize.py",
})
# Shared config files are removed only when they carry a pytest section.
_SANDBOX_PYTEST_SECTIONS = {
    "setup.cfg": ("[tool:pytest]", "[pytest]"),
    "pyproject.toml": ("[tool.pytest",),
}
_SANDBOX_NOT_COPIED = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", ".pytest_cache", ".venv", "venv", "node_modules")


def grading_env(home: Path) -> dict[str, str]:
    """The explicit allowlist, built from scratch (never `os.environ.copy()`)."""
    env = {k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ}
    scratch = home / "tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    env.update({
        "HOME": str(home), "USERPROFILE": str(home),
        "TEMP": str(scratch), "TMP": str(scratch), "TMPDIR": str(scratch),
        "PYTHONPATH": "",                      # set by us: nothing inherited, nothing added
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",  # no third-party pytest plugin is loaded
    })
    return env


def _ignore_for_copy(directory: str, names: list[str]) -> set[str]:
    """Skip caches/VCS data AND every symlink -- a link is never followed or copied."""
    skip = set(_SANDBOX_NOT_COPIED(directory, names))
    skip.update(n for n in names if os.path.islink(os.path.join(directory, n)))
    return skip


def prepare_sandbox(src: Path, dst: Path) -> None:
    """Copy `src` to `dst` and strip everything a student could use to steer pytest.

    A COPY, never the original: the demo grades `renders/<student>_attempt1` in place, and
    deleting a student's conftest there would destroy their working copy. After this, `dst`
    holds the student's source and visible tests, no conftest of theirs, no pytest config,
    and the trusted root conftest.py -- the one the template ships to every student
    (render_student_repo.TEMPLATE_FILES), which only puts the repo root on sys.path.
    """
    from scripts.render_student_repo import TEMPLATE_FILES  # lazy: avoids an import cycle

    shutil.copytree(src, dst, ignore=_ignore_for_copy)
    shutil.rmtree(dst / "tests" / "hidden", ignore_errors=True)   # re-injected, never inherited
    for path in sorted(dst.rglob("*")):
        if not path.is_file():
            continue
        if path.name in _SANDBOX_REMOVE:
            path.unlink()
            continue
        markers = _SANDBOX_PYTEST_SECTIONS.get(path.name)
        if markers and any(m in path.read_text(encoding="utf-8", errors="replace")
                           for m in markers):
            path.unlink()
    (dst / "conftest.py").write_text(TEMPLATE_FILES["conftest.py"], encoding="utf-8")


def _run_pytest(repo_dir: Path, test_rel_path: str, junit_path: Path,
                ini_path: Path | None = None) -> None:
    """The one subprocess call in this module -- see the module docstring's invariant
    12/13 note for why this MUST be a real subprocess and never an in-process pytest.main()
    call: a separate process is what makes "executes here, not inside an agent" a fact
    about the operating system rather than a fact about which function called which.

    `sys.executable`, not a bare "python", so this runs under the SAME interpreter (and
    therefore the same installed packages) as the process that invoked grading -- a
    student repo has no venv of its own, it reuses this project's.

    `--tb=short` (not `line`): a collection error is classified by WHERE its traceback points
    (D-066), and `line` drops the frames for an exception raised inside an imported module --
    found by observing it. Stored failure messages come from the report's `message`
    attribute, which does not depend on the traceback style.

    D-065: `-P` (do not put the working directory on sys.path -- a student `pytest.py` or
    `json.py` cannot shadow what pytest imports at start-up; the trusted root conftest adds
    the repo root afterwards), `-c <ours>` (pytest reads OUR config, not the student's, and
    `--rootdir` pins the root), no cache plugin, and `grading_env` instead of the parent's
    environment.

    Exit code is deliberately not checked here: pytest exits non-zero when tests FAIL,
    which is the normal, expected case this function exists to observe, not an error
    condition. `_parse_junit` is what decides pass/fail per test; a genuinely broken run
    (test file doesn't parse, no junit report written) is caught there instead.
    """
    results_dir = junit_path.parent
    if ini_path is None:
        ini_path = results_dir / "pytest-trusted.ini"
    ini_path.write_text("[pytest]\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, "-P", "-m", "pytest", test_rel_path,
         "-c", str(ini_path), "--rootdir", str(repo_dir),
         f"--junitxml={junit_path}", "-q", "--tb=short", "-p", "no:cacheprovider"],
        cwd=repo_dir,
        env=grading_env(results_dir / "home"),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
    )


def _expected_gap_tests(test_src: Path, test_rel_path: str) -> list[tuple[str, str]]:
    """`(test_name, gap_id)` for every `@pytest.mark.gap("g_...")` test in a hidden test
    file, read STATICALLY (ast; nothing is imported or run). Used only when the file could
    not be imported at all: the tests exist even though pytest could not collect them."""
    tree = ast.parse(test_src.read_text(encoding="utf-8"))
    found: list[tuple[str, str]] = []

    def gap_of(fn: ast.AST) -> str | None:
        for dec in getattr(fn, "decorator_list", []):
            if not isinstance(dec, ast.Call) or not dec.args:
                continue
            target = dec.func
            if isinstance(target, ast.Attribute) and target.attr == "gap" \
                    and isinstance(dec.args[0], ast.Constant):
                return str(dec.args[0].value)
        return None

    def walk(body, prefix: str) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                walk(node.body, f"{prefix}{node.name}::")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name.startswith("test"):
                gap = gap_of(node)
                if gap is not None:
                    found.append((f"{test_rel_path}::{prefix}{node.name}", gap))

    walk(tree.body, "")
    return found


_COLLECTION_FAILURE = "collection failure"
_FRAME = re.compile(r'File "([^"\n]+\.py)", line (\d+)|^\s*E?\s*(\S[^\n]*?\.py):(\d+):', re.M)
_EXC_LINE = re.compile(r"^\s*E?\s*((?:\w+\.)*\w*(?:Error|Exception))\b[:\s]?(.*)$", re.M)


def _collection_errors(root: ET.Element) -> list[str]:
    """The text of every `collection failure` entry in a JUnit report."""
    out = []
    for case in root.iter("testcase"):
        error = case.find("error")
        if error is not None and (error.get("message") or "").startswith(_COLLECTION_FAILURE):
            out.append((error.get("message") or "") + "\n" + (error.text or ""))
    return out


def classify_collection_error(error_text: str, repo_dir: Path,
                              student_packages: tuple[str, ...] = ()) -> tuple[str, str]:
    """`("collection_error", why)` when the traceback is the STUDENT's fault, else
    `("tooling", why)`. Decided by where the traceback points, innermost in-repo frame first:

      - a frame in a file of the student's (anything in the repo that is not under
        tests/hidden/) -> the student's code does not import (SyntaxError, a name error at
        import time, ...): `collection_error`.
      - the innermost in-repo frame is our hidden test file, but the exception is an
        ImportError / ModuleNotFoundError about the STUDENT's own package ("cannot import
        name 'insert_readings' from 'weather_etl.load'", "No module named 'weather_etl'"):
        the student removed or renamed something the task requires -> `collection_error`.
      - everything else (our test file or conftest is broken, a third-party library is
        missing, no in-repo frame at all) -> `tooling`. When in doubt it is tooling: not
        charging a student for our fault is the safe direction.
    """
    root = repo_dir.resolve()
    frames: list[tuple[str, int]] = []
    for m in _FRAME.finditer(error_text):
        raw, line = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        p = Path(raw)
        p = p if p.is_absolute() else root / p
        try:
            rel = p.resolve().relative_to(root).as_posix()
        except (ValueError, OSError):
            continue                       # outside the repo: pytest / stdlib / site-packages
        frames.append((rel, int(line)))

    excs = _EXC_LINE.findall(error_text)
    exc_type, exc_msg = excs[-1] if excs else ("error", "")
    exc_msg = exc_msg.strip()
    where = ""

    if frames:
        rel, line = frames[-1]
        where = f" at {rel}:{line}"
        if not rel.startswith("tests/hidden/"):
            return "collection_error", f"{exc_type}{where}: {exc_msg}"[:500]

    # `student_packages` carries the project's own package name even when the student deleted
    # it ("No module named 'weather_etl'"): a missing package is the student's doing.
    student_modules = set(student_packages)
    student_modules |= {p.name for p in root.iterdir()
                        if p.is_dir() and (p / "__init__.py").exists() and p.name != "tests"}
    student_modules |= {p.stem for p in root.glob("*.py") if p.name != "conftest.py"}
    if exc_type.endswith(("ImportError", "ModuleNotFoundError")):
        quoted = re.findall(r"'([\w.]+)'", exc_msg)
        if any(q.split(".")[0] in student_modules for q in quoted):
            return "collection_error", f"{exc_type}{where}: {exc_msg}"[:500]

    if frames or exc_msg:
        return "tooling", f"{exc_type}{where}: {exc_msg}"[:500]
    return "tooling", "collection failure with no usable traceback"


def evaluate(project_id: str, file_path: str, repo_dir: str | Path) -> Evaluation:
    """Run one assignment's hidden tests against a COPY of `repo_dir` and say what happened.
    Touches no database -- this is the whole of "grading" except recording it, which is what
    lets a dry run show the exact rows `grade_attempt` would write."""
    repo_dir = Path(repo_dir)
    test_src = _hidden_test_file(project_id, file_path)
    with tempfile.TemporaryDirectory(prefix="vdel_grade_") as tmp:
        tmp = Path(tmp)
        work = tmp / "repo"
        prepare_sandbox(repo_dir, work)
        test_rel_path = _inject_hidden_test(work, project_id, test_src)

        results = tmp / "results"          # outside the student's directory
        results.mkdir()
        junit_path = results / f"junit-{secrets.token_hex(16)}.xml"
        try:
            _run_pytest(work, test_rel_path, junit_path)
        except subprocess.TimeoutExpired:
            # D-069: a hung or endless student module. Recorded ONCE (each @gap test of the
            # file failed, status "timeout"): the commit then has test_results rows, so
            # grade_collected does not pick it up again next cycle. Before this the exception
            # escaped, nothing was written, and the same commit hung the grader every cycle.
            expected = _expected_gap_tests(test_src, test_rel_path)
            detail = f"hidden tests did not finish within {_TIMEOUT_S}s"
            if not expected:
                return Evaluation((), "tooling", f"{detail} (but no @gap test found)")
            return Evaluation(
                tuple(TestOutcome(name, False, f"timeout: {detail}", gap, "timeout")
                      for name, gap in expected),
                "timeout", detail)

        if not junit_path.exists():
            raise TestRunnerError(
                f"pytest produced no junit report at {junit_path} -- the run did not "
                "complete (see module docstring: this is distinct from tests failing)"
            )
        errors = _collection_errors(ET.parse(junit_path).getroot())
        if not errors:
            return Evaluation(tuple(_parse_junit(junit_path)), "ok", None)

        status, detail = classify_collection_error("\n".join(errors), work, (project_id,))
        if status == "tooling":
            return Evaluation((), "tooling", detail)
        expected = _expected_gap_tests(test_src, test_rel_path)
        if not expected:
            return Evaluation((), "tooling",
                              f"{detail} (but no @gap test found in the hidden file)")
        message = f"collection error: {detail}"[:2000]
        return Evaluation(
            tuple(TestOutcome(name, False, message, gap, "collection_error")
                  for name, gap in expected),
            "collection_error", detail)


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


# `tests.hidden.<stem>` -- the part of a JUnit classname that is the same wherever the repo
# sits, because `_inject_hidden_test` always puts the file at tests/hidden/<name>.py.
# Everything BEFORE it is a path prefix (the render directory, relative to wherever
# pytest decided its rootdir was) and is not part of the test's identity.
_HIDDEN_MODULE = re.compile(r"(?:^|\.)tests\.hidden\.([^.:]+)((?:\.[^.:]+)*)$")
_ALREADY_NORMALISED = re.compile(r"^tests/hidden/[^:]+\.py::")


def normalise_test_name(raw: str) -> str:
    """Path-independent identity for a stored test: `tests/hidden/<file>.py[::Class]::<test>`.

    D-055: pytest's JUnit `classname` is derived from the test's node id relative to
    pytest's ROOTDIR, and the rootdir is whatever ancestor holds a config file
    (`pyproject.toml`). The same rendered repo therefore produced
    `renders.anas_attempt1.tests.hidden.test_x::t` when it sat inside this project and
    `tests.hidden.test_x::t` anywhere else. `test_results` and the `xmax = 0` new-row check
    both key on that string, so grading one commit from two directories looked like two
    sets of new tests and logged every BKT observation twice (invariant 8).

    `raw` is `"<classname>::<name>"` exactly as `_parse_junit` builds it. Idempotent: an
    already-normalised name is returned unchanged, which is what lets the migration script
    reuse this function on rows that may or may not have been rewritten yet.

    Raises TestRunnerError on a classname with no `tests.hidden.<stem>` module in it rather
    than storing a path-dependent name silently -- the hidden file is always injected at
    that location (`_inject_hidden_test`), so its absence means the run is not what this
    module thinks it is, and a loud failure beats a quietly wrong identity.
    """
    if _ALREADY_NORMALISED.match(raw):
        return raw
    classname, sep, name = raw.partition("::")
    match = _HIDDEN_MODULE.search(classname)
    if not sep or match is None:
        raise TestRunnerError(
            f"cannot derive a path-independent test name from {raw!r}: expected the "
            "classname to contain 'tests.hidden.<module>'"
        )
    stem, class_path = match.group(1), match.group(2)
    return f"tests/hidden/{stem}.py" + class_path.replace(".", "::") + f"::{name}"


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
            test_name=normalise_test_name(f"{case.get('classname')}::{case.get('name')}"),
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
        (attempt_id, commit_sha, o.test_name, o.gap_id, o.passed, o.message, o.status)
        for o in outcomes
    ]
    if commit_sha is not None:
        result = execute_values(cur, """
            INSERT INTO test_results
                (attempt_id, commit_sha, test_name, gap_id, passed, message, status)
            VALUES %s
            ON CONFLICT (attempt_id, commit_sha, test_name) WHERE commit_sha IS NOT NULL
            DO UPDATE SET gap_id = EXCLUDED.gap_id, passed = EXCLUDED.passed,
                          message = EXCLUDED.message, status = EXCLUDED.status,
                          ran_at = now()
            RETURNING test_name, (xmax = 0) AS is_new
        """, rows, fetch=True)
    else:
        result = execute_values(cur, """
            INSERT INTO test_results
                (attempt_id, commit_sha, test_name, gap_id, passed, message, status)
            VALUES %s
            ON CONFLICT (attempt_id, test_name) WHERE commit_sha IS NULL
            DO UPDATE SET gap_id = EXCLUDED.gap_id, passed = EXCLUDED.passed,
                          message = EXCLUDED.message, status = EXCLUDED.status,
                          ran_at = now()
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


def _hidden_gap_ids(cur, attempt_id: int) -> frozenset[str]:
    """The gaps this attempt actually HID: `attempts.variant_id` -> `variants.gap_ids`
    (sql/06). Only these were left for the student to write; every other gap in the file
    was handed over already solved (render_student_file keeps its original body).
    `attempts.variant_id` is NOT NULL, so the join always resolves for a real attempt."""
    cur.execute(
        "SELECT v.gap_ids FROM attempts a JOIN variants v USING (variant_id)"
        " WHERE a.attempt_id = %s",
        (attempt_id,),
    )
    row = cur.fetchone()
    return frozenset(row[0]) if row else frozenset()


_NOT_IMPLEMENTED = re.compile(r"^(?:\w+\.)*NotImplementedError\b")


def _raised_not_implemented(outcome: TestOutcome) -> bool:
    """A failing test whose stored message is a NotImplementedError: the student's stub."""
    return (not outcome.passed and bool(outcome.message)
            and _NOT_IMPLEMENTED.match(outcome.message.strip()) is not None)


def gap_observation(tests: list[TestOutcome]) -> bool | None:
    """The D-079 rule for ONE gap in ONE commit: None when the gap was not attempted (one of
    its hidden tests failed with NotImplementedError), otherwise True when every hidden test
    of the gap passed and False when not. The one definition: the grading path and
    scripts/backfill_mastery_observations.py both call it, so a backfill cannot disagree with
    what grading would have written."""
    if any(_raised_not_implemented(t) for t in tests):
        return None
    return all(t.passed for t in tests)


def _log_test_result_traces(mem: Memory, conn, student_id: str, assignment_id: str,
                            attempt_id: int, commit_sha: str | None,
                            outcomes: list[TestOutcome], new_test_names: set[str],
                            gap_meta: dict, hidden_gap_ids: frozenset[str]) -> None:
    """One `test_result` trace per genuinely-new, gap-tagged outcome of a HIDDEN gap: evidence
    for V5/V6 (D-079: no longer mastery). Through `memory.Memory` only (invariant 2).

    Filters, all load-bearing: `new_test_names` (re-grading a recorded commit must not log a
    second trace), `gap_id is not None` (an untagged test has no concept), `gap_id in
    hidden_gap_ids` (D-054: a pre-solved gap passes whatever the student does), and
    `status == "ok"` (D-069: a collection error or timeout is not evidence). The payload keeps
    the old two keys and adds attempt_id, commit_sha, gap_id and test_name, so the trace can be
    audited without a join to the mutable `test_results` table."""
    for o in outcomes:
        if (o.test_name not in new_test_names or o.gap_id is None
                or o.gap_id not in hidden_gap_ids or o.status != "ok"):
            continue
        meta = gap_meta.get(o.gap_id)
        if meta is None:
            continue   # gap_id didn't resolve against `gaps` -- nothing to attribute
        concept_ids, difficulty = meta
        mem.log_trace(
            student_id, "system", "test_result",
            {"conclusion": "success" if o.passed else "failure",
             "item_difficulty": difficulty, "attempt_id": attempt_id,
             "commit_sha": commit_sha, "gap_id": o.gap_id, "test_name": o.test_name},
            assignment_id=assignment_id, concept_ids=concept_ids, conn=conn,
        )


def _log_mastery_observations(mem: Memory, conn, cur, student_id: str, assignment_id: str,
                              attempt_id: int, commit_sha: str | None,
                              outcomes: list[TestOutcome], gap_meta: dict,
                              hidden_gap_ids: frozenset[str]) -> list[int]:
    """D-079: the BKT observations this commit produces, then one `update_mastery` per concept
    touched. Returns the new trace ids.

    For each HIDDEN gap with outcomes in this commit: it was ATTEMPTED unless one of its hidden
    tests failed with NotImplementedError; if attempted, the observation is `success` when every
    hidden test of the gap passed. `Memory.record_mastery_observation` writes it only if the
    (attempt, gap) has none yet, so this is the first attempted pushed commit by construction
    and a re-grade is a no-op. Nothing is written for a local run, a status other than ok, or a
    commit with no `raw_commits` row (its time is the observation's time; skipped with a
    warning rather than invented)."""
    if commit_sha is None:
        return []
    cur.execute("SELECT committed_at FROM raw_commits WHERE sha = %s", (commit_sha,))
    row = cur.fetchone()
    by_gap: dict[str, list[TestOutcome]] = {}
    for o in outcomes:
        if o.status == "ok" and o.gap_id in hidden_gap_ids and o.gap_id in gap_meta:
            by_gap.setdefault(o.gap_id, []).append(o)
    if not by_gap:
        return []
    if row is None:
        log.warning("no raw_commits row for %s: no mastery observation written", commit_sha[:10])
        return []
    committed_at = row[0]

    written: list[int] = []
    for gap_id in sorted(by_gap):
        passed = gap_observation(by_gap[gap_id])
        if passed is None:
            continue                      # the student has not attempted this gap yet
        concept_ids, difficulty = gap_meta[gap_id]
        trace_id = mem.record_mastery_observation(
            student_id, attempt_id=attempt_id, assignment_id=assignment_id, gap_id=gap_id,
            concept_ids=concept_ids, passed=passed,
            item_difficulty=difficulty, commit_sha=commit_sha, observed_at=committed_at,
            conn=conn)
        if trace_id is not None:
            written.append(trace_id)
            mem.update_mastery(student_id, concept_ids[0], parent_trace_id=trace_id, conn=conn)
    return written


def _out_of_scope_lines(cur, project_id: str, file_path: str, repo_dir: Path,
                        attempt_id: int) -> int | None:
    """D-073 (V9): how many changed lines of the submitted file lie OUTSIDE the gaps this
    attempt hid, or None when that cannot be computed. FAIL-OPEN: any problem (file missing,
    master changed, parse error) logs a warning and returns None, so the column stays NULL --
    it never blocks grading and never invents a number.

    Gap-scoped only (invariant 14): the released file is rebuilt from the master and the
    attempt's hidden gaps (`render_student_file_with_ranges`, which also gives the hidden
    regions in THE RELEASED FILE's line numbers); only a diff against it is read. Nothing is
    attributed to the student from code the master already contained. Pre-solved gaps are not
    gap regions here: the student was not asked to touch them.

    Invariant 15: skipped when the attempt's variant pins a different master_version than the
    project's current one, because the rebuilt released file would not be what the student got.
    """
    cur.execute("SAVEPOINT scope_check")
    try:
        cur.execute(
            "SELECT v.gap_ids, v.master_version, p.master_version FROM attempts a"
            " JOIN variants v USING (variant_id) JOIN projects p ON p.project_id = a.project_id"
            " WHERE a.attempt_id = %s", (attempt_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError("no variant/project for the attempt")
        gap_ids, variant_master, project_master = row
        if variant_master != project_master:
            raise ValueError(f"variant pins master {variant_master[:10]}, project is at "
                             f"{project_master[:10]}")
        master_text = (CURRICULUM_ROOT / project_id / file_path).read_text(encoding="utf-8")
        released, ranges = render_student_file_with_ranges(master_text, gap_ids)
        submitted = (Path(repo_dir) / file_path).read_text(encoding="utf-8")
        count = scope_check(released, submitted, ranges).out_of_scope_lines_changed
        cur.execute("RELEASE SAVEPOINT scope_check")
        return count
    except Exception as exc:  # noqa: BLE001 -- fail-open is the contract
        cur.execute("ROLLBACK TO SAVEPOINT scope_check")
        log.warning("scope check skipped for attempt %s (out_of_scope_lines left as it was): "
                    "%s: %s", attempt_id, type(exc).__name__, exc)
        return None


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

    # D-065/D-066: the tests run in a sandboxed COPY of repo_dir (nothing is injected into, or
    # deleted from, the original), and a hidden file that cannot be imported no longer raises.
    evaluation = evaluate(project_id, file_path, repo_dir)
    outcomes = list(evaluation.outcomes)
    tests_total = len(outcomes)
    tests_passed = sum(1 for o in outcomes if o.passed)

    to_record = outcomes
    if evaluation.status == "tooling":
        # NOT a failure and never mastery evidence (no gap_id, not in `outcomes`, so
        # tests_total stays 0 and nothing can freeze). The marker row exists so the commit
        # counts as handled: without a row the grader would pick it up again every cycle.
        marker = f"tests/hidden/test_{Path(file_path).stem}.py::<collection>"
        to_record = [TestOutcome(marker, False, evaluation.detail, None, "tooling")]

    mem = Memory()
    with _session(conn) as c, c.cursor() as cur:
        cur.execute("SELECT student_id FROM attempts WHERE attempt_id = %s", (attempt_id,))
        student_row = cur.fetchone()
        if student_row is None:
            raise TestRunnerError(f"unknown attempt_id {attempt_id!r}")
        student_id = student_row[0]

        new_test_names = _write_test_results(cur, attempt_id, commit_sha, to_record)
        gap_meta = _gap_metadata(cur, {o.gap_id for o in outcomes if o.gap_id is not None})
        hidden_gap_ids = _hidden_gap_ids(cur, attempt_id)
        _log_test_result_traces(mem, c, student_id, assignment_id, attempt_id, commit_sha,
                                outcomes, new_test_names, gap_meta, hidden_gap_ids)
        _log_mastery_observations(mem, c, cur, student_id, assignment_id, attempt_id,
                                  commit_sha, outcomes, gap_meta, hidden_gap_ids)
        frozen = _maybe_freeze(cur, attempt_id, commit_sha, tests_passed, tests_total)
        # D-073. One column per attempt: it holds the latest graded commit's value until the
        # attempt freezes, and the frozen commit's value afterwards (the WHERE keeps a later
        # grading call from overwriting it).
        out_of_scope = _out_of_scope_lines(cur, project_id, file_path, Path(repo_dir), attempt_id)
        if out_of_scope is not None:
            cur.execute(
                "UPDATE attempts SET out_of_scope_lines = %s WHERE attempt_id = %s"
                " AND (submitted_at IS NULL OR commit_sha IS NOT DISTINCT FROM %s)",
                (out_of_scope, attempt_id, commit_sha))

    return RunResult(
        outcomes=tuple(outcomes), tests_passed=tests_passed,
        tests_total=tests_total, frozen=frozen,
        status=evaluation.status, detail=evaluation.detail,
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
