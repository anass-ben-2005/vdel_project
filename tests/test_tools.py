"""agents/tools.py — M4 task 4.2, the deterministic stage.

Two things are being protected here.

**That a linter which did not run is never reported as a clean one.** D.5 returns `"[]"` from
a bare `except Exception`, so an uninstalled linter and a spotless file are indistinguishable
downstream — and the prompt presents the result to the judge as verified fact. That is the
`duration_s = run_number * 60` failure mode from `DEVELOPMENT_MAP.md` §0 wearing a different
hat: a plausible number that was never measured. `test_unavailable_tool_*` pin it.

**That invariant 12 holds.** `test_never_executes_the_submission` runs the linters over a
file whose import would have an observable side effect, and asserts the side effect did not
happen. This is the only mechanical check in the repo that the no-execution boundary is real
rather than merely intended.

These tests need no database and no provider key, but they do shell out to ruff and sqlfluff,
so they skip cleanly on a machine where those are not installed.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agents.tools import (
    STATUS_ERROR,
    STATUS_OK,
    STATUS_TIMEOUT,
    STATUS_UNAVAILABLE,
    ToolReport,
    lint_submission,
    render_findings,
    run_ruff,
    run_sqlfluff,
)

CLEAN_PY = '''"""A module with nothing for ruff to complain about."""


def add(a, b):
    return a + b
'''

DIRTY_PY = '''import os
import sys


def f():
    return undefined_name_here
'''

DIRTY_SQL = "select a,b from tbl where x=1\n"


def _tool_installed(module: str) -> bool:
    try:
        subprocess.run([sys.executable, "-m", module, "--version"],
                       capture_output=True, timeout=30, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return True


needs_ruff = pytest.mark.skipif(not _tool_installed("ruff"), reason="ruff not installed")
needs_sqlfluff = pytest.mark.skipif(not _tool_installed("sqlfluff"),
                                    reason="sqlfluff not installed")


@pytest.fixture
def write(tmp_path):
    def _write(name: str, text: str) -> Path:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path
    return _write


# ---- The security boundary ---------------------------------------------------------------

@needs_ruff
def test_never_executes_the_submission(write, tmp_path):
    """Invariant 12, checked rather than asserted.

    The submission writes a marker file at import time. If any stage of the tool pipeline
    imported or executed it, the marker would exist. Linting must leave it absent.
    """
    marker = tmp_path / "EXECUTED"
    submission = write("malicious.py", f'''
from pathlib import Path
Path(r"{marker}").write_text("the submission ran")


def solution():
    return 1
''')

    reports = lint_submission(submission)
    render_findings(reports, str(submission))

    assert not marker.exists(), "the submission was executed — invariant 12 is broken"
    assert reports[0].ran


# ---- Deviation 1: a tool that did not run is never silence ------------------------------

def test_unavailable_tool_is_not_reported_as_clean(monkeypatch, write):
    """The whole point of the deviation: absence of findings must not read as absence of
    problems when the linter was never there."""
    def _boom(*_args, **_kwargs):
        raise FileNotFoundError("no such tool")

    monkeypatch.setattr(subprocess, "run", _boom)
    report = run_ruff(write("x.py", CLEAN_PY))

    assert report.status == STATUS_UNAVAILABLE
    assert report.ran is False
    assert report.findings == []          # empty, but...
    rendered = render_findings([report])
    assert "DID NOT RUN" in rendered      # ...never presented as a clean result
    assert "not evidence" in rendered


def test_timeout_is_not_reported_as_clean(monkeypatch, write):
    def _hang(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="ruff", timeout=15)

    monkeypatch.setattr(subprocess, "run", _hang)
    report = run_ruff(write("x.py", CLEAN_PY))

    assert report.status == STATUS_TIMEOUT
    assert "DID NOT RUN" in render_findings([report])


def test_unparseable_output_is_an_error_not_an_empty_result(monkeypatch, write):
    class _Result:
        stdout = "this is not json"
        stderr = ""
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())
    report = run_ruff(write("x.py", CLEAN_PY))

    assert report.status == STATUS_ERROR
    assert "DID NOT RUN" in render_findings([report])


@needs_ruff
def test_clean_file_is_reported_as_ran_with_zero_findings(write):
    """The other half of the distinction: a genuinely clean file must say so positively."""
    report = run_ruff(write("clean.py", CLEAN_PY))

    assert report.status == STATUS_OK
    assert report.findings == []
    rendered = render_findings([report])
    assert "ran, 0 findings" in rendered
    assert "DID NOT RUN" not in rendered


# ---- Deviation 2: findings are normalised, not raw stdout --------------------------------

@needs_ruff
def test_ruff_findings_are_normalised_to_five_fields(write):
    report = run_ruff(write("dirty.py", DIRTY_PY))

    assert report.status == STATUS_OK
    assert report.findings
    for finding in report.findings:
        assert set(finding) == {"code", "message", "line", "column", "severity"}
        assert isinstance(finding["line"], int)
    assert any(f["code"] == "F821" for f in report.findings), report.findings


@needs_sqlfluff
def test_sqlfluff_findings_are_normalised_and_carry_no_fix_spans(write):
    """sqlfluff's raw output is ~90% `fixes` and `timings`. None of it may reach the prompt."""
    report = run_sqlfluff(write("dirty.sql", DIRTY_SQL))

    assert report.status == STATUS_OK
    assert report.findings
    for finding in report.findings:
        assert set(finding) == {"code", "message", "line", "column", "severity"}
    rendered = render_findings([report])
    assert "fixes" not in rendered
    assert "timings" not in rendered


@needs_sqlfluff
def test_sqlfluff_severity_is_normalised_to_ruffs_vocabulary(write):
    report = run_sqlfluff(write("dirty.sql", DIRTY_SQL))
    assert {f["severity"] for f in report.findings} <= {"error", "warning"}


# ---- Deviation 3: no absolute paths reach the prompt -------------------------------------

@needs_ruff
def test_rendered_block_leaks_no_absolute_path(write, tmp_path):
    """Both tools report the full local path. The judge sees a basename at most."""
    submission = write("dirty.py", DIRTY_PY)
    rendered = render_findings(lint_submission(submission), str(submission))

    assert str(tmp_path) not in rendered
    assert "dirty.py" in rendered


@needs_ruff
def test_findings_carry_no_filename_field(write):
    report = run_ruff(write("dirty.py", DIRTY_PY))
    assert all("filename" not in f for f in report.findings)


# ---- Dispatch and rendering --------------------------------------------------------------

@needs_ruff
def test_dispatch_by_extension(write):
    assert [r.tool for r in lint_submission(write("a.py", CLEAN_PY))] == ["ruff"]


@needs_sqlfluff
def test_dispatch_sql(write):
    assert [r.tool for r in lint_submission(write("a.sql", DIRTY_SQL))] == ["sqlfluff"]


def test_unknown_extension_yields_no_reports_and_says_so(write):
    reports = lint_submission(write("a.txt", "hello"))
    assert reports == []
    rendered = render_findings(reports)
    assert "No deterministic linter" in rendered
    assert "0 findings" not in rendered   # must not imply a clean result


def test_to_dict_is_json_serialisable():
    """`ToolReport` lands in a verdict trace payload, which is JSONB."""
    report = ToolReport("ruff", STATUS_OK, findings=[{"code": "F401", "line": 1}])
    assert json.loads(json.dumps(report.to_dict()))["tool"] == "ruff"


@needs_ruff
def test_findings_appear_in_the_rendered_block_with_their_line(write):
    report = run_ruff(write("dirty.py", DIRTY_PY))
    rendered = render_findings([report])
    for finding in report.findings:
        assert f"line {finding['line']}" in rendered
        assert str(finding["code"]) in rendered
