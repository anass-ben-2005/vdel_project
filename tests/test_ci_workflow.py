"""The CI workflow every rendered student repo ships with (D-060).

What went wrong in the first published repo: CI died at `ruff check .` with `ruff: command
not found` (exit 127) and `pytest tests/visible` never ran -- and a local run of the same
commands on a fresh render then showed a second, hidden failure: bare `pytest tests/visible`
cannot import the project (`ModuleNotFoundError: No module named 'weather_etl'`). So the
workflow is checked two ways: its STRUCTURE (parsed from the real generated YAML, not a
substring grep) and its BEHAVIOUR (the workflow's pytest command run against a real render).

The behavioural test renders inside a rolled-back transaction and skips when no database
is reachable.
"""
import ast
import shlex
import shutil
import subprocess
import sys

import pytest
import yaml

from assessment import test_runner as tr
from scripts.render_student_repo import _CI_WORKFLOW, render_student_repo
from system import db


def _steps() -> list[dict]:
    return yaml.safe_load(_CI_WORKFLOW)["jobs"]["test"]["steps"]


def _index(predicate, steps=None) -> int:
    steps = _steps() if steps is None else steps
    matches = [i for i, s in enumerate(steps) if predicate(s)]
    assert len(matches) == 1, f"expected exactly one matching step, got {len(matches)}"
    return matches[0]


def _run(step) -> str:
    return str(step.get("run", ""))


# --- structure -----------------------------------------------------------------------------

def test_the_workflow_installs_ruff_and_pytest_itself():
    """Not via the student's requirements.txt (runtime dependencies only): a dedicated step
    installs both tools, and it comes before anything that runs them."""
    install = _index(lambda s: _run(s).startswith("pip install")
                     and "ruff" in _run(s) and "pytest" in _run(s) and "-r" not in _run(s))
    lint = _index(lambda s: _run(s).startswith("ruff check"))
    tests = _index(lambda s: "pytest tests/visible" in _run(s))
    assert install < lint < tests


def test_the_students_runtime_dependencies_are_still_installed_from_requirements():
    assert any(_run(s) == "pip install -r requirements.txt" for s in _steps())


def test_the_ruff_step_cannot_block_pytest():
    """Lint is a signal, not a correctness gate (invariants 12/13). GitHub treats a failing
    step with `continue-on-error: true` as a success for the steps after it, so pytest
    still runs -- but only if that flag is on the RIGHT step."""
    steps = _steps()
    lint = steps[_index(lambda s: _run(s).startswith("ruff check"))]
    assert lint["continue-on-error"] is True


def test_a_failing_test_must_still_fail_the_run():
    """The mirror image: only lint is allowed to fail quietly. If pytest were also
    continue-on-error the run could never go red, and the signal would be worthless."""
    steps = _steps()
    tests = steps[_index(lambda s: "pytest tests/visible" in _run(s))]
    assert "continue-on-error" not in tests
    assert "if" not in tests               # nothing that could skip it


def test_only_the_lint_step_is_allowed_to_fail_quietly():
    quiet = [_run(s) for s in _steps() if s.get("continue-on-error")]
    assert quiet == ["ruff check ."]


def test_pytest_runs_as_python_dash_m_so_the_repo_root_is_importable():
    """Bare `pytest` does not put the repo root on sys.path; `python -m pytest` does."""
    tests = _steps()[_index(lambda s: "pytest tests/visible" in _run(s))]
    assert _run(tests) == "python -m pytest tests/visible"


# --- behaviour -----------------------------------------------------------------------------

def test_the_workflows_pytest_command_can_import_a_freshly_rendered_repo(tmp_path):
    """Render a real attempt and run the workflow's own pytest command in it. Failing
    visible tests are fine here (the gaps are stubs -- that is the student's work); what
    must not happen is a collection error. Exit code 2 / ModuleNotFoundError is exactly
    the failure the bare `pytest` command produced."""
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    try:
        conn.cursor().execute("INSERT INTO students VALUES ('_ci_test','_ci_test','vdel-2026')")
        repo = tmp_path / "repo"
        render_student_repo("weather_etl", "_ci_test", 1, repo, conn=conn)
    finally:
        conn.rollback()
        conn.close()

    # The command is READ FROM THE TEMPLATE, not retyped here: a copy of it in this test
    # would keep passing while the real workflow regressed to the bare `pytest` form.
    cmd = shlex.split(_run(_steps()[_index(lambda s: "pytest tests/visible" in _run(s))]))
    if cmd[0] == "python":
        cmd[0] = sys.executable
    else:
        exe = shutil.which(cmd[0])
        if exe is None:
            pytest.skip(f"{cmd[0]!r} is not on PATH here")
        cmd[0] = exe

    done = subprocess.run([*cmd, "-q"], cwd=repo, capture_output=True, text=True, timeout=120)

    output = done.stdout + done.stderr
    assert "ModuleNotFoundError" not in output
    assert done.returncode in (0, 1), f"collection/usage error (exit {done.returncode}):\n{output}"


# --- the root conftest.py: bare `pytest` must work too (D-060) ------------------------------

@pytest.fixture
def rendered(tmp_path):
    """A real render of a throwaway student's attempt 1. The transaction stays open (and is
    rolled back at teardown) so `grade_attempt` can join it -- traces are append-only, so
    rollback is the only cleanup."""
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    conn.cursor().execute("INSERT INTO students VALUES ('_ci_test2','_ci_test2','vdel-2026')")
    repo = tmp_path / "repo"
    render_student_repo("weather_etl", "_ci_test2", 1, repo, conn=conn)
    yield conn, repo
    conn.rollback()
    conn.close()


# What the bare `pytest` console script does to sys.path: the directory it lives in is
# first, the current directory is NOT there. `python -c` puts '' (cwd) first, so popping it
# reproduces the console script's import behaviour without depending on PATH.
_BARE_PYTEST = ("import sys; sys.path.pop(0); import pytest; "
                "sys.exit(pytest.main(['tests/visible', '-q']))")


def _run_bare_pytest(repo):
    return subprocess.run([sys.executable, "-c", _BARE_PYTEST], cwd=repo,
                          capture_output=True, text=True, timeout=120)


def test_every_render_ships_a_root_conftest_with_no_code(rendered):
    _, repo = rendered
    text = (repo / "conftest.py").read_text(encoding="utf-8")
    assert text.strip(), "an empty file gives a student no hint why it is there"
    assert ast.parse(text).body == []          # comments only: nothing that can differ per student


def test_bare_pytest_can_import_a_render_only_because_of_the_root_conftest(rendered):
    """The documented student command is bare `pytest tests/visible`. With the file it
    collects and runs (the stub gaps FAIL, which is right -- exit 1, never a collection
    error); with the file removed, the very same invocation dies with ModuleNotFoundError,
    so this test cannot pass by accident."""
    _, repo = rendered

    with_file = _run_bare_pytest(repo)
    assert "ModuleNotFoundError" not in with_file.stdout + with_file.stderr
    assert with_file.returncode == 1, with_file.stdout + with_file.stderr

    (repo / "conftest.py").unlink()
    without_file = _run_bare_pytest(repo)
    assert without_file.returncode == 2
    assert "ModuleNotFoundError: No module named 'weather_etl'" in (
        without_file.stdout + without_file.stderr)


def test_hidden_test_injection_and_grading_still_work_with_the_root_conftest(rendered):
    """tests/hidden/ gets its OWN conftest.py injected by assessment/test_runner.py (it turns
    @pytest.mark.gap into JUnit properties). Two conftest.py files in one run must not break
    that: every outcome must still carry its gap_id."""
    conn, repo = rendered
    cur = conn.cursor()
    cur.execute("SELECT attempt_id FROM attempts WHERE student_id='_ci_test2'"
                " AND assignment_id='weather_etl_extract'")
    (attempt_id,) = cur.fetchone()

    result = tr.grade_attempt("weather_etl", "weather_etl_extract", repo, attempt_id,
                              commit_sha=None, conn=conn)

    assert result.tests_total == 4
    assert all(o.gap_id is not None for o in result.outcomes)
    assert {o.gap_id for o in result.outcomes} == {"g_ext_parse", "g_ext_retry"}
    # D-065: grading runs on a COPY, so the injected hidden conftest is no longer left in the
    # student's directory (it used to be -- the leak the generated .gitignore guards against),
    # and the student's own root conftest.py is untouched. That both conftests worked together
    # is what the gap_id assertions above prove.
    assert not (repo / "tests" / "hidden").exists()
    assert (repo / "conftest.py").is_file()
