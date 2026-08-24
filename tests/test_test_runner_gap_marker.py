"""Regression guard for D-046's actual mechanism -- that a bare `@pytest.mark.gap(...)`
does NOT reach --junitxml output on its own, and that the conftest.py hook
(curriculum/master/weather_etl/tests/hidden/conftest.py) is what makes it.

This does not touch the database (no PG_DSN skip, unlike tests/test_test_runner.py) --
it exercises `_run_pytest`/`_parse_junit` directly against a throwaway test file, because
what is being guarded here is the marker-to-property mechanism itself, which has nothing
to do with grading or freezing. Written after discovering the behaviour empirically this
session (a scratch probe with and without the conftest hook, on both a passing and a
failing marked test, and on an unmarked test) -- this turns that one-off check into a
permanent one.
"""
from pathlib import Path

from assessment import test_runner as tr

_CONFTEST = (
    Path(__file__).resolve().parent.parent
    / "curriculum" / "master" / "weather_etl" / "tests" / "hidden" / "conftest.py"
)


def _grade(tmp_path: Path, test_body: str) -> list[tr.TestOutcome]:
    hidden = tmp_path / "tests" / "hidden"
    hidden.mkdir(parents=True)
    (hidden / "test_probe.py").write_text(test_body, encoding="utf-8")
    (hidden / "conftest.py").write_text(_CONFTEST.read_text(encoding="utf-8"), encoding="utf-8")

    junit_path = tmp_path / "results.xml"
    tr._run_pytest(tmp_path, "tests/hidden/test_probe.py", junit_path)
    return tr._parse_junit(junit_path)


def test_marker_reaches_junit_via_the_real_conftest_when_passing(tmp_path):
    outcomes = _grade(tmp_path, '''
import pytest

@pytest.mark.gap("g_probe")
def test_something():
    assert True
''')
    assert len(outcomes) == 1
    assert outcomes[0].passed is True
    assert outcomes[0].gap_id == "g_probe"


def test_marker_reaches_junit_via_the_real_conftest_when_failing(tmp_path):
    """The property must survive a FAILURE -- most real hidden-test outcomes are
    failures (a student mid-attempt), so a mechanism that only worked for passing
    tests would silently lose gap_id on exactly the rows that matter most."""
    outcomes = _grade(tmp_path, '''
import pytest

@pytest.mark.gap("g_probe_fail")
def test_something():
    assert False
''')
    assert len(outcomes) == 1
    assert outcomes[0].passed is False
    assert outcomes[0].gap_id == "g_probe_fail"


def test_unmarked_test_reports_gap_id_none_not_an_error(tmp_path):
    """No marker means no property means None -- absence, not a guess and not a crash.
    This is the honest-NULL discipline CLAUDE.md invariant 10 applies to unclassified
    errors, applied here to an unmarked test."""
    outcomes = _grade(tmp_path, '''
def test_something():
    assert True
''')
    assert len(outcomes) == 1
    assert outcomes[0].gap_id is None
