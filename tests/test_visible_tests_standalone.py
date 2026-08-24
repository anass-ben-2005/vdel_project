"""Structural guard: curriculum/master/*/tests/visible/ must stay genuinely standalone.

VDEL_REDESIGN.md 8.3: "Visible smoke tests the student can run locally (`pytest
tests/visible`)" -- a bare command, on the student's own machine, before anything is
pushed. tests/hidden/ is the opposite: never given to the student, injected at grading
time by assessment/test_runner.py alongside a conftest.py that reads @pytest.mark.gap.

This test does not run the visible tests (tests/test_test_runner_gap_marker.py and this
session's manual proof already did that, both directions -- failing against an unsolved
render, passing against the real solved master). It guards the STRUCTURAL property that
makes standalone execution possible at all: no tests/visible/ directory may contain a
conftest.py of its own, and no test file in it may reference the gap-marking convention
or import from assessment/ -- either would silently make "the student can run this
alone" stop being true, without any test that exercises the tests actually catching it.
"""
from pathlib import Path

CURRICULUM_ROOT = Path(__file__).resolve().parent.parent / "curriculum" / "master"


def _visible_dirs():
    return list(CURRICULUM_ROOT.glob("*/tests/visible"))


def test_at_least_one_visible_suite_exists():
    # A guard that silently passes on zero directories is worthless -- if this ever
    # trips because a project has no tests/visible yet, that is real information, not a
    # reason to relax the check.
    assert _visible_dirs(), "no curriculum/master/*/tests/visible directory found"


def test_no_visible_directory_has_its_own_conftest():
    for visible_dir in _visible_dirs():
        assert not (visible_dir / "conftest.py").exists(), (
            f"{visible_dir} has a conftest.py -- visible tests must run standalone, "
            "with nothing injected (VDEL_REDESIGN.md 8.3)"
        )


def test_no_visible_test_references_the_gap_marker_or_assessment_package():
    """Checks actual CODE lines only -- `import`/`from` statements and the marker
    decorator itself -- never the raw file text. A naive substring check on the whole
    file would false-positive on this repo's own docstrings, which explain the
    independence by NAMING what is absent ("no assessment/test_runner.py involvement"),
    and a check that cannot tell prose from code is worse than no check at all."""
    for visible_dir in _visible_dirs():
        for test_file in visible_dir.glob("test_*.py"):
            for lineno, line in enumerate(
                test_file.read_text(encoding="utf-8").splitlines(), start=1
            ):
                stripped = line.strip()
                # startswith, not "in": a real decorator use is always the first token
                # on its own line. A bare "in" check also matches this project's own
                # docstring PROSE naming the absent convention ("no @pytest.mark.gap,
                # no assessment/test_runner.py involvement") -- caught live, twice, by
                # actually running this test rather than trusting it on sight.
                assert not stripped.startswith("@pytest.mark.gap"), (
                    f"{test_file}:{lineno} uses @pytest.mark.gap -- that convention is "
                    "for tests/hidden/ (D-046), graded by assessment/test_runner.py; a "
                    "visible test coupled to it would no longer run standalone"
                )
                is_import = stripped.startswith(("import ", "from "))
                assert not (is_import and "assessment" in stripped), (
                    f"{test_file}:{lineno} imports from assessment/ -- visible tests "
                    "must not depend on any grading-time machinery"
                )
