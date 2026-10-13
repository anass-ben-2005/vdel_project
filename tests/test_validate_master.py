"""D-107 -- scripts/validate_master.py, rule by rule, on a tiny curriculum in a temp directory.

Nothing is imported from or written to the real curriculum; no database, no network.
"""

import ast
from pathlib import Path

import pytest

from scripts import validate_master as vm

GOOD_STAGE = '''def f(x):
    """Doubles."""
    # @gap:id=g_one concepts=[py.testing] difficulty=0.3
    # @instruct: Return x doubled.
    return x * 2
    # @endgap
'''
GOOD_TEST = """import pytest
from demo.alpha import f


@pytest.mark.gap("g_one")
def test_doubles():
    assert f(2) == 4
"""
CHECKS = """version: 1
assignments:
  demo_alpha:
    - test: tests/hidden/test_alpha.py::test_doubles
      gap: g_one
      description: The function returns twice its input.
      status: reviewed
"""
JUDGING = """version: 1
default: {criteria: [correctness, approach]}
assignments:
  demo_alpha:
    criteria: [correctness]
    statement: {text: Doubles a number., status: reviewed}
"""
RESOURCES = (
    "resource_id,concept_ids,kind,title,locator,url,level\n"
    "r1,py.testing|py.data_structures,doc_page,T,,https://example.org/a,beginner\n"
)


@pytest.fixture
def world(tmp_path):
    """A one-stage project `demo` with everything in order; each test breaks one thing."""
    root = tmp_path / "curriculum"
    pkg = root / "demo" / "demo"
    (root / "demo" / "tests" / "hidden").mkdir(parents=True)
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "alpha.py").write_text(GOOD_STAGE, encoding="utf-8")
    (root / "demo" / "tests" / "hidden" / "test_alpha.py").write_text(GOOD_TEST, encoding="utf-8")
    files = {
        "checks": tmp_path / "checks.yaml",
        "judging": tmp_path / "judging.yaml",
        "resources": tmp_path / "resources.csv",
    }
    files["checks"].write_text(CHECKS, encoding="utf-8")
    files["judging"].write_text(JUDGING, encoding="utf-8")
    files["resources"].write_text(RESOURCES, encoding="utf-8")
    return root, files


def run(world, projects=None, **kw):
    from config import checks, judging

    checks._load.cache_clear()
    judging._load.cache_clear()
    root, files = world
    try:
        return vm.validate(
            projects,
            curriculum=root,
            checks_path=files["checks"],
            judging_path=files["judging"],
            resources_path=files["resources"],
            **kw,
        )
    finally:
        checks._load.cache_clear()
        judging._load.cache_clear()


def messages(findings, level=vm.ERROR):
    return [f.message for f in findings if f.level == level]


def stage(world, name="alpha"):
    return world[0] / "demo" / "demo" / f"{name}.py"


def test_a_complete_project_has_no_findings(world):
    assert run(world) == []


# --- 1, 3: marker syntax and concepts


def test_an_unclosed_gap_is_an_error_naming_the_file(world):
    stage(world).write_text(GOOD_STAGE.replace("    # @endgap\n", ""), encoding="utf-8")
    errors = messages(run(world))
    assert len(errors) == 1 and "alpha.py" in errors[0] and "unclosed" in errors[0]


def test_a_gap_with_no_instruction_or_an_empty_body_is_an_error(world):
    stage(world).write_text(
        GOOD_STAGE.replace("    # @instruct: Return x doubled.\n", ""), encoding="utf-8"
    )
    assert any("no @instruct" in m for m in messages(run(world)))


def test_an_unknown_concept_is_an_error(world):
    stage(world).write_text(GOOD_STAGE.replace("py.testing", "py.nonsense"), encoding="utf-8")
    assert any("py.nonsense" in m for m in messages(run(world)))


# --- 2: gap ids unique across the whole curriculum


def test_the_same_gap_id_in_two_stages_is_an_error(world):
    other = GOOD_STAGE
    (world[0] / "demo" / "demo" / "beta.py").write_text(other, encoding="utf-8")
    (world[0] / "demo" / "tests" / "hidden" / "test_beta.py").write_text(
        GOOD_TEST.replace("alpha", "beta"), encoding="utf-8"
    )
    errors = [
        f
        for f in run(world)
        if f.level == vm.ERROR and "g_one" in f.message and "places" in f.message
    ]
    assert len(errors) == 1
    assert "demo/alpha" in errors[0].message and "demo/beta" in errors[0].message
    assert errors[0].where == "curriculum"


def test_the_same_gap_id_in_two_projects_is_an_error(world):
    root, _ = world
    twin = root / "twin"
    (twin / "twin").mkdir(parents=True)
    (twin / "tests" / "hidden").mkdir(parents=True)
    (twin / "twin" / "alpha.py").write_text(GOOD_STAGE, encoding="utf-8")
    (twin / "tests" / "hidden" / "test_alpha.py").write_text(GOOD_TEST, encoding="utf-8")
    assert any("defined in 2 places" in m for m in messages(run(world)))


# --- 4, 5: hidden tests and gaps


def test_a_gap_no_hidden_test_covers_is_an_error(world):
    stage(world).write_text(
        GOOD_STAGE + GOOD_STAGE.replace("g_one", "g_two").replace("f(x)", "g(x)"), encoding="utf-8"
    )
    errors = messages(run(world))
    assert any("gap g_two is covered by no hidden test" in m for m in errors)
    assert not any("g_one" in m and "covered" in m for m in errors)


def test_a_test_without_a_marker_is_a_warning_and_an_unknown_marker_an_error(world):
    test = world[0] / "demo" / "tests" / "hidden" / "test_alpha.py"
    test.write_text(
        GOOD_TEST + "\n\ndef test_unmarked():\n    assert True\n\n\n"
        '@pytest.mark.gap("g_ghost")\ndef test_ghost():\n    assert True\n',
        encoding="utf-8",
    )
    findings = run(world)
    assert any("test_unmarked has no gap marker" in m for m in messages(findings, vm.WARN))
    assert any("test_ghost names gap g_ghost" in m for m in messages(findings))


def test_a_missing_hidden_test_file_is_an_error(world):
    (world[0] / "demo" / "tests" / "hidden" / "test_alpha.py").unlink()
    assert any("no hidden test file" in m for m in messages(run(world)))


def test_a_class_based_test_is_found(world):
    test = world[0] / "demo" / "tests" / "hidden" / "test_alpha.py"
    test.write_text(
        GOOD_TEST.replace(
            '@pytest.mark.gap("g_one")\ndef test_doubles():\n    assert f(2) == 4',
            'class TestF:\n    @pytest.mark.gap("g_one")\n'
            "    def test_doubles(self):\n        assert f(2) == 4",
        ),
        encoding="utf-8",
    )
    names = [t.stored_name for t in vm.hidden_tests(test)]
    assert names == ["tests/hidden/test_alpha.py::TestF::test_doubles"]


# --- 6: checks.yaml


def test_a_hidden_test_with_no_checks_entry_is_an_error(world):
    world[1]["checks"].write_text("version: 1\nassignments: {}\n", encoding="utf-8")
    assert any("test_doubles has no entry in config/checks.yaml" in m for m in messages(run(world)))


def test_a_checks_entry_for_a_test_that_does_not_exist_is_an_error(world):
    world[1]["checks"].write_text(
        CHECKS
        + CHECKS.split("assignments:\n  demo_alpha:\n")[1].replace("test_doubles", "test_gone"),
        encoding="utf-8",
    )
    assert any("lists tests/hidden/test_alpha.py::test_gone" in m for m in messages(run(world)))


def test_a_checks_entry_whose_gap_disagrees_with_the_marker_is_an_error(world):
    world[1]["checks"].write_text(CHECKS.replace("gap: g_one", "gap: g_other"), encoding="utf-8")
    assert any(
        "checks.yaml says gap g_other, the test is marked g_one" in m for m in messages(run(world))
    )


def test_a_malformed_checks_file_is_one_clear_error(world):
    world[1]["checks"].write_text("version: 9\n", encoding="utf-8")
    errors = [f for f in run(world) if f.level == vm.ERROR]
    assert any(f.where == "config/checks.yaml" and "version must be 1" in f.message for f in errors)


def test_drafts_are_notes_unless_reviewed_is_required(world):
    world[1]["checks"].write_text(CHECKS.replace("reviewed", "draft"), encoding="utf-8")
    world[1]["judging"].write_text(JUDGING.replace("reviewed", "draft"), encoding="utf-8")
    findings = run(world)
    assert messages(findings) == []
    assert len(messages(findings, vm.INFO)) == 2
    strict = run(world, require_reviewed=True)
    assert len(messages(strict)) == 2 and all("still draft" in m for m in messages(strict))


# --- 7: judging.yaml


def test_a_missing_judging_entry_is_an_error_and_a_missing_statement_a_warning(world):
    world[1]["judging"].write_text(
        "version: 1\ndefault: {criteria: [correctness]}\n", encoding="utf-8"
    )
    assert any("no entry for demo_alpha in config/judging.yaml" in m for m in messages(run(world)))
    world[1]["judging"].write_text(
        "version: 1\ndefault: {criteria: [correctness]}\nassignments:\n"
        "  demo_alpha: {criteria: [correctness]}\n",
        encoding="utf-8",
    )
    findings = run(world)
    assert messages(findings) == []
    assert any("no task statement" in m for m in messages(findings, vm.WARN))


# --- 8: resources


def test_a_concept_without_a_resource_is_an_error_and_example_rows_do_not_count(world):
    world[1]["resources"].write_text(
        "resource_id,concept_ids,kind,title,locator,url,level\n"
        "EXAMPLE-1,py.testing,doc_page,T,,https://example.invalid/a,beginner\n",
        encoding="utf-8",
    )
    errors = messages(run(world))
    assert any("concept py.testing has no resource" in m for m in errors)
    world[1]["resources"].write_text(
        "resource_id,concept_ids,kind,title,locator,url,level\n", encoding="utf-8"
    )
    assert any("py.testing has no resource" in m for m in messages(run(world)))


# --- the command


def test_main_exit_codes_and_output(world, tmp_path):
    root, files = world
    args = [
        "--curriculum",
        str(root),
        "--checks",
        str(files["checks"]),
        "--judging",
        str(files["judging"]),
        "--resources",
        str(files["resources"]),
    ]
    lines: list[str] = []
    assert vm.main(args, out=lines.append) == 0
    assert lines[-1].strip().startswith("0 error(s)")
    assert vm.main([*args, "nonexistent"], out=lines.append) == 2
    stage(world).write_text(GOOD_STAGE.replace("py.testing", "py.nonsense"), encoding="utf-8")
    lines.clear()
    assert vm.main(args, out=lines.append) == 1
    assert lines[0].startswith("ERROR") and "py.nonsense" in lines[0]


def test_the_validator_touches_no_database_and_no_network():
    tree = ast.parse(Path(vm.__file__).read_text(encoding="utf-8"))
    imported = {
        n.names[0].name if isinstance(n, ast.Import) else n.module
        for n in ast.walk(tree)
        if isinstance(n, (ast.Import, ast.ImportFrom))
    }
    assert not {
        m
        for m in imported
        if m
        and m.split(".")[0] in {"psycopg2", "requests", "urllib", "socket", "system", "subprocess"}
    }


# --- the real curriculum


def test_weather_etl_has_no_errors_with_the_shipped_files():
    from config import checks, judging

    checks._load.cache_clear()
    judging._load.cache_clear()
    findings = vm.validate(["weather_etl"])
    assert [f.line() for f in findings if f.level == vm.ERROR] == []
    assert [f.line() for f in findings if f.level == vm.WARN] == []


def test_every_shipped_weather_etl_test_has_exactly_one_checks_entry():
    from config import checks

    expected = set()
    for stage_name in ("extract", "transform", "load", "quality"):
        path = vm.CURRICULUM / "weather_etl" / "tests" / "hidden" / f"test_{stage_name}.py"
        expected |= {t.stored_name for t in vm.hidden_tests(path)}
    listed = [c.test for c in checks.entries(include_drafts=True)]
    assert sorted(listed) == sorted(expected) and len(listed) == len(set(listed)) == 15
