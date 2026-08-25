"""Registers the `@pytest.mark.gap("g_id")` marker (D-046) and turns it into a JUnit XML
`<properties>` entry `assessment/test_runner.py` can read without parsing test names or
bodies -- a test's gap_id is declared once, on the test itself, not re-derived from a
naming convention that could silently drift from the real `gaps` table.

Identical to curriculum/master/weather_etl/tests/hidden/conftest.py -- per-project by
construction (`test_runner.py`'s `_inject_hidden_test` reads `CURRICULUM_ROOT /
project_id / "tests" / "hidden" / "conftest.py"`, not a shared global path), but the
logic itself is project-agnostic, so this is a verbatim copy, not a parallel
implementation.

Copied into every rendered repo's `tests/hidden/` alongside the single hidden test file
being graded (`test_runner.py::_inject_hidden_test`).

VERIFIED, not assumed, before this convention was adopted (see weather_etl's own
conftest.py): a bare `@pytest.mark.gap(...)` does NOT appear anywhere in `--junitxml`
output by default.
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
