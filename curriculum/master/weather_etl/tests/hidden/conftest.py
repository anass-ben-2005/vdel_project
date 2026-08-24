"""Registers the `@pytest.mark.gap("g_id")` marker (D-046) and turns it into a JUnit XML
`<properties>` entry `assessment/test_runner.py` can read without parsing test names or
bodies -- a test's gap_id is declared once, on the test itself, not re-derived from a
naming convention that could silently drift from the real `gaps` table.

Copied into every rendered repo's `tests/hidden/` alongside the single hidden test file
being graded (`test_runner.py::_inject_conftest`) -- pytest auto-discovers a `conftest.py`
in the same directory as the tests it collects; no import, no path manipulation needed,
and this happens even though only ONE test module in that directory is named on the
command line.

VERIFIED, not assumed, before this convention was adopted: a bare `@pytest.mark.gap(...)`
does NOT appear anywhere in `--junitxml` output by default. Checked directly -- a marked
test with no hook produced a `<testcase>` with no `<properties>` at all. `pytest`'s
junitxml plugin only emits `<properties>` from `item.user_properties`, which is exactly
what `pytest_collection_modifyitems` below writes. Also checked on a FAILING marked test
(the property survives, appearing before `<failure>` in the same `<testcase>`) and on an
unmarked test (correctly produces no `<properties>` element -- absence, not an empty one).
"""


def pytest_configure(config):
    # Avoids PytestUnknownMarkWarning. This project's own pyproject.toml cannot register
    # the marker here -- this conftest runs inside a STUDENT repo, a different filesystem
    # location that may have no pyproject.toml of its own at all, not inside this
    # project's tree.
    config.addinivalue_line(
        "markers",
        "gap(gap_id): the gaps.gap_id (sql/06_assessment_tables.sql) this test exercises",
    )


def pytest_collection_modifyitems(items):
    for item in items:
        marker = item.get_closest_marker("gap")
        if marker is not None:
            item.user_properties.append(("gap_id", marker.args[0]))
