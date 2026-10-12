"""D-097 -- a single-assignment repo ships only the visible tests it can import.

The bug (confirmed by running pytest in a copy of an attempt-1 repo with load.py, quality.py and
transform.py removed): `python -m pytest tests/visible` -- the command in the generated ci.yml --
ended with "3 errors during collection", "Interrupted", and test_extract.py did not run at all.
The attempt-2 render (D-090) holds ONE module but used to copy all four visible test files.

The renders below run inside a rolled-back transaction and skip when no database is reachable.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.render_student_repo import (
    CURRICULUM_ROOT,
    _project_modules_imported,
    render_student_repo,
)
from system import db

PROJECT = "weather_etl"
MASTER = CURRICULUM_ROOT / PROJECT
STAGES = {                       # assignment -> the visible test that belongs to it
    "weather_etl_extract": "test_extract.py",
    "weather_etl_transform": "test_transform.py",
    "weather_etl_load": "test_load.py",
    "weather_etl_quality": "test_quality.py",
}
ALL_FOUR = sorted(STAGES.values())


@pytest.fixture
def conn():
    try:
        connection = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    connection.cursor().execute("INSERT INTO students VALUES ('_vis','_vis','vdel-2026')")
    yield connection
    connection.rollback()
    connection.close()


def tests_in(repo: Path) -> list[str]:
    return sorted(p.name for p in (repo / "tests" / "visible").glob("*.py"))


def variants(conn, attempt_no: int) -> dict[str, str]:
    cur = conn.cursor()
    cur.execute("SELECT assignment_id, variant_id FROM attempts"
                " WHERE student_id = '_vis' AND attempt_no = %s", (attempt_no,))
    return dict(cur.fetchall())


# --- the import reader (no database) ---------------------------------------------------------

def test_the_import_reader_understands_every_form_of_project_import():
    src = (
        "import sqlite3\n"
        "import weather_etl.load\n"
        "from weather_etl.extract import parse_response\n"
        "from weather_etl.sub.deep import thing\n"
        "from weather_etl import quality, __version__\n"
        "from . import sibling\n"
        "from other_pkg.transform import nope\n"
    )
    assert _project_modules_imported(src, PROJECT, MASTER) == {"load", "extract", "sub", "quality"}
    assert _project_modules_imported("import os\n", PROJECT, MASTER) == set()


# --- a single-assignment render --------------------------------------------------------------

@pytest.mark.parametrize("assignment,expected", sorted(STAGES.items()))
def test_each_single_assignment_render_ships_only_its_own_visible_test(
        conn, tmp_path, assignment, expected):
    info = render_student_repo(PROJECT, "_vis", 2, tmp_path / "r", conn=conn,
                               only_assignment=assignment)
    assert tests_in(tmp_path / "r") == [expected]
    assert info["visible_tests"] == [expected]
    assert not list((tmp_path / "r").rglob("hidden"))          # no hidden path, anywhere
    # the one file that ships is the master's own, byte for byte
    assert ((tmp_path / "r" / "tests" / "visible" / expected).read_bytes()
            == (MASTER / "tests" / "visible" / expected).read_bytes())


def test_the_workflows_pytest_command_collects_and_runs_in_a_single_assignment_render(
        conn, tmp_path):
    """The command the generated ci.yml runs. Before the fix: exit 2, '3 errors during
    collection', nothing ran. Now: no collection error and test_extract.py really runs (its
    result depends on the student's gaps -- exit 0 or 1, never 2)."""
    render_student_repo(PROJECT, "_vis", 2, tmp_path / "r", conn=conn,
                        only_assignment="weather_etl_extract")
    done = subprocess.run([sys.executable, "-m", "pytest", "tests/visible", "-q"],
                          cwd=tmp_path / "r", capture_output=True, text=True, timeout=120)
    out = done.stdout + done.stderr
    assert "ModuleNotFoundError" not in out and "errors during collection" not in out
    assert done.returncode in (0, 1), out
    assert "test_extract.py" in out or "passed" in out or "failed" in out
    assert "no tests ran" not in out


def test_without_the_filter_the_same_render_would_have_failed_as_reported(conn, tmp_path):
    """Keeps the confirmed failure as a fact: all four test files next to one module."""
    render_student_repo(PROJECT, "_vis", 2, tmp_path / "r", conn=conn,
                        only_assignment="weather_etl_extract")
    for name in ALL_FOUR:                                    # put the unfiltered folder back
        (tmp_path / "r" / "tests" / "visible" / name).write_bytes(
            (MASTER / "tests" / "visible" / name).read_bytes())
    done = subprocess.run([sys.executable, "-m", "pytest", "tests/visible", "-q"],
                          cwd=tmp_path / "r", capture_output=True, text=True, timeout=120)
    out = done.stdout + done.stderr
    assert done.returncode == 2 and "3 errors during collection" in out
    assert "No module named 'weather_etl.load'" in out


# --- the whole-project render is unchanged ---------------------------------------------------

def test_a_four_assignment_render_still_ships_all_four_visible_tests_unchanged(conn, tmp_path):
    info = render_student_repo(PROJECT, "_vis", 1, tmp_path / "r", conn=conn)
    assert tests_in(tmp_path / "r") == ALL_FOUR
    assert info["visible_tests"] == sorted(
        p.relative_to(MASTER / "tests" / "visible").as_posix()
        for p in (MASTER / "tests" / "visible").rglob("*") if p.is_file())
    for name in ALL_FOUR:
        assert ((tmp_path / "r" / "tests" / "visible" / name).read_bytes()
                == (MASTER / "tests" / "visible" / name).read_bytes())
    assert not list((tmp_path / "r").rglob("hidden"))


def test_the_variants_do_not_depend_on_how_much_of_the_project_is_rendered(conn, tmp_path):
    """The variant id comes from select_variant alone; the visible-test filter must not touch it."""
    render_student_repo(PROJECT, "_vis", 1, tmp_path / "whole", conn=conn)
    whole = variants(conn, 1)
    assert set(whole) == set(STAGES)
    for assignment in STAGES:
        conn.cursor().execute("DELETE FROM attempts WHERE student_id='_vis' AND assignment_id=%s",
                              (assignment,))
        render_student_repo(PROJECT, "_vis", 1, tmp_path / assignment, conn=conn,
                            only_assignment=assignment)
        assert variants(conn, 1)[assignment] == whole[assignment]
