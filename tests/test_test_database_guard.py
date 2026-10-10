"""D-064 -- the guards that keep the test suite off the real database.

Almost everything here runs against FAKE connections: a refusal test that could reach a real
server would defeat its own purpose.
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extensions import make_dsn

from system import db
from tests import conftest as cft

REPO = Path(__file__).resolve().parent.parent


class FakeConn:
    """Stands in for a connection: records every statement, answers the advisory lock."""

    def __init__(self):
        self.executed: list = []
        self.autocommit = False
        self.closed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        self.executed.append(query)

    def fetchone(self):
        return (True,)

    def close(self):
        self.closed = True


def test_conftest_module_is_the_one_pytest_loaded():
    assert sys.modules["tests.conftest"] is cft


# --- check (1)(2)(3): each proven on its own ---------------------------------------------------

@pytest.mark.parametrize("target, real", [
    ("vdel", "vdel"),                  # the real name itself
    ("VDEL", "vdel"),                  # the real name, different case
    ("vdel_test", "vdel_test"),        # a real database that happens to be called vdel_test
    ("vdel_prod", "vdel"),             # no _test suffix
    ("postgres", "vdel"),              # the maintenance database
    ("other_test", "vdel"),            # ends with _test but is not derived from the real DSN
    ("vdel_test_x", "vdel"),
    ("", "vdel"),
    ("vdel_test", ""),                 # real name unknown
])
def test_drop_and_create_refuse_anything_but_the_derived_name(target, real):
    conn = FakeConn()
    with pytest.raises(cft.UnsafeTestDatabase):
        cft.drop_database(conn, target, real)
    with pytest.raises(cft.UnsafeTestDatabase):
        cft.create_database(conn, target, real)
    with pytest.raises(cft.UnsafeTestDatabase):
        cft.tune_database(conn, target, real)
    assert conn.executed == []         # refused BEFORE any statement reached the server


@pytest.mark.parametrize("real", ["vdel", "prod", "my_db"])
def test_the_derived_name_is_accepted_and_runs_exactly_one_statement(real):
    target = cft.derive_test_name(real)
    assert target == real + "_test"
    conn = FakeConn()
    cft.drop_database(conn, target, real)
    cft.create_database(conn, target, real)
    assert len(conn.executed) == 2


def test_check_1_derivation_fires_on_its_own():
    with pytest.raises(cft.UnsafeTestDatabase, match="not derived"):
        cft.assert_safe_target("other_test", "vdel")


def test_check_2_suffix_fires_on_its_own(monkeypatch):
    monkeypatch.setattr(cft, "derive_test_name", lambda real: real + "_prod")   # derived, no suffix
    with pytest.raises(cft.UnsafeTestDatabase, match="does not end with"):
        cft.assert_safe_target("vdel_prod", "vdel")


def test_check_3_difference_fires_on_its_own(monkeypatch):
    monkeypatch.setattr(cft, "derive_test_name", lambda real: real)             # derived, suffix ok
    monkeypatch.setattr(cft, "TEST_SUFFIX", "")
    with pytest.raises(cft.UnsafeTestDatabase, match="IS the real database"):
        cft.assert_safe_target("vdel", "vdel")


def test_the_checks_cannot_be_stripped_by_python_dash_O():
    source = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")
    body = source[source.index("def assert_safe_target"):source.index("def drop_database")]
    assert "assert " not in body.replace("assert_safe_target", "")   # explicit raises only


def test_building_with_the_real_name_by_mistake_is_refused_before_any_drop(monkeypatch):
    """Even the whole build step, handed the REAL name as its target, refuses."""
    if not cft.STATE.real_dsn:
        pytest.skip("no PG_DSN configured")
    fake = FakeConn()
    real = cft.STATE.real_name
    before = (cft.STATE.maint, dict(os.environ))
    with pytest.raises(cft.UnsafeTestDatabase):
        cft._build_test_database(fake, cft.STATE.real_dsn, real, real)
    assert fake.executed == []                        # not even a DROP was attempted
    assert (cft.STATE.maint, dict(os.environ)) == before   # no shared state touched


# --- the wrapped psycopg2.connect --------------------------------------------------------------

def test_a_connection_to_the_real_database_is_refused_and_counted(monkeypatch):
    if not cft.STATE.real_dsn:
        pytest.skip("no PG_DSN configured")
    monkeypatch.setattr(cft, "REFUSED", Counter())          # keep the session summary clean
    monkeypatch.setattr(cft, "CONNECTED", Counter())
    with pytest.raises(cft.UnsafeTestDatabase):
        psycopg2.connect(make_dsn(cft.STATE.real_dsn))
    with pytest.raises(cft.UnsafeTestDatabase):
        psycopg2.connect(make_dsn(cft.STATE.real_dsn, dbname=cft.STATE.real_name.upper()))
    with pytest.raises(cft.UnsafeTestDatabase):
        psycopg2.connect(host="localhost")                  # no database named at all
    assert cft.REFUSED[cft.STATE.real_name] == 1 and sum(cft.CONNECTED.values()) == 0


# --- system/db.py: the guard exists only under VDEL_TESTING=1 ---------------------------------

@pytest.mark.parametrize("dsn_value, ok", [
    ("dbname=vdel_test host=h", True),
    ("postgresql://u:p@h:5433/vdel_test", True),
    ("dbname=vdel host=h", False),
    ("postgresql://u:p@h:5433/vdel", False),
    ("host=h", False),
])
def test_check_test_mode_only_allows_a_test_database(monkeypatch, dsn_value, ok):
    monkeypatch.setenv("VDEL_TESTING", "1")
    if ok:
        db.check_test_mode(dsn_value)
    else:
        with pytest.raises(RuntimeError, match="does not end in"):
            db.check_test_mode(dsn_value)


def test_without_the_variable_db_open_behaves_exactly_as_before(monkeypatch):
    """The demo, the scripts and the pipeline never set VDEL_TESTING: _open() must pass the
    DSN straight to psycopg2.connect, unchanged, whatever database it names."""
    monkeypatch.delenv("VDEL_TESTING", raising=False)
    monkeypatch.setenv("PG_DSN", "dbname=vdel host=somewhere")
    calls = []
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: calls.append((a, k)) or "conn")
    assert db._open() == "conn"
    assert calls == [(("dbname=vdel host=somewhere",), {})]
    db.check_test_mode("dbname=vdel host=somewhere")          # no-op


def test_with_the_variable_db_open_refuses_a_real_name_before_connecting(monkeypatch):
    monkeypatch.setenv("VDEL_TESTING", "1")
    monkeypatch.setenv("PG_DSN", "dbname=vdel host=somewhere")
    calls = []
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: calls.append(a))
    with pytest.raises(RuntimeError, match="refusing to open"):
        db._open()
    assert calls == []


def test_only_the_conftest_sets_vdel_testing():
    """No source file outside tests/ may assign the variable (reading it, in system/db.py,
    is the point). Tests may monkeypatch it; those are inside tests/."""
    assign = re.compile(
        r"""(environ\[\s*['"]VDEL_TESTING['"]\s*\]\s*="""
        r"""|setenv\(\s*['"]VDEL_TESTING"""
        r"""|putenv\(\s*['"]VDEL_TESTING"""
        r"""|^\s*VDEL_TESTING\s*=)""", re.M)
    offenders = []
    for path in REPO.rglob("*.py"):
        parts = set(path.relative_to(REPO).parts)
        if parts & {"tests", ".venv", "venv", "site-packages", "__pycache__", "node_modules"}:
            continue
        if assign.search(path.read_text(encoding="utf-8", errors="replace")):
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == []
    conftest_source = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert 'os.environ["VDEL_TESTING"] = "1"' in conftest_source


# --- this very session ------------------------------------------------------------------------

def test_this_session_runs_against_the_throwaway_database():
    if not cft.STATE.test_name or cft.STATE.problem:
        pytest.skip("no test database in this session")
    with db.cursor() as cur:
        cur.execute("SELECT current_database()")
        name = cur.fetchone()[0]
    assert name == cft.STATE.test_name
    assert name.endswith("_test") and name.casefold() != cft.STATE.real_name.casefold()
    assert cft.CONNECTED.get(cft.STATE.real_name, 0) == 0


# --- fail closed -------------------------------------------------------------------------------

def test_failing_to_build_the_test_database_blanks_pg_dsn_so_nothing_can_fall_back(monkeypatch):
    """If the throwaway database cannot be built, the real DSN must NOT stay in the
    environment: database tests then skip, and nothing can reach the real database. Blank,
    not removed: system.db's load_dotenv() would re-add a removed variable from .env."""
    monkeypatch.setenv("PG_DSN", "dbname=vdel host=somewhere")
    monkeypatch.delenv("VDEL_REQUIRE_DB", raising=False)
    monkeypatch.setattr(cft.STATE, "problem", None)
    cft._fail_closed("server unreachable")
    assert os.environ["PG_DSN"] == "" and os.environ["VDEL_TESTING"] == "1"
    assert cft.STATE.problem == "server unreachable"


def test_dotenv_cannot_put_the_real_dsn_back_after_a_failed_build(monkeypatch, tmp_path):
    """The hole found live: with PG_DSN removed, importing system.db re-read .env."""
    from dotenv import load_dotenv
    env_file = tmp_path / ".env"
    env_file.write_text("PG_DSN=dbname=vdel host=real\n", encoding="utf-8")
    monkeypatch.setenv("PG_DSN", "")
    load_dotenv(env_file)                                 # what `import system.db` does
    assert os.environ["PG_DSN"] == ""


def test_require_db_turns_the_skip_into_an_error(monkeypatch):
    monkeypatch.setenv("PG_DSN", "dbname=vdel host=somewhere")
    monkeypatch.setenv("VDEL_REQUIRE_DB", "1")
    monkeypatch.setattr(cft.STATE, "problem", None)
    with pytest.raises(pytest.UsageError, match="no test database"):
        cft._fail_closed("server unreachable")
