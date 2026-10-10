"""tests/conftest.py -- D-064: the test suite never touches the real database.

Before this, the DB tests ran against the SAME database as the demo and the pipeline, kept
out of real data only by convention (every test cleaning up after itself). The convention
failed twice (a feature row written for a real student; synthetic rows left behind by a
teardown that hit a foreign key), and `traces` is append-only, so one committing test would
pollute it forever. Now:

  - At session start this file creates a throwaway database named `<real name>_test`
    (so `vdel` -> `vdel_test`), applies the schema (scripts/init_db.py) and seeds the
    curriculum (scripts/seed_data.py::seed_curriculum), points PG_DSN at it, and sets
    VDEL_TESTING=1. At session end it drops it (VDEL_KEEP_TEST_DB=1 keeps it to inspect).
  - VDEL_TESTING=1 is set by THIS file and by nothing else. With the variable absent,
    system/db.py behaves exactly as before -- the demo, the scripts and the pipeline are
    unaffected. With it present, system/db.py::_open refuses any database not ending `_test`.
  - Hard refusal: the target of every DROP and CREATE DATABASE must (1) be derived from the
    real DSN, (2) end with `_test`, and (3) differ from the real database name. All three
    are checked IMMEDIATELY before each statement (`assert_safe_target`), not once at start.
  - `psycopg2.connect` is wrapped for the session: a connection to the real database name
    is refused, and every connection is counted per database name. The terminal summary
    prints the counts, so "the real database was never connected to" is a printed fact.
  - FAIL CLOSED: if the test database cannot be built (server down, no CREATEDB right, ...),
    PG_DSN is removed, so DB tests skip -- they can never fall back to the real database.
    Set VDEL_REQUIRE_DB=1 (CI) to make that a hard error instead of a skip.
  - One session at a time (an advisory lock on the maintenance database): two concurrent
    runs would otherwise drop each other's `vdel_test`.

LIMIT: this protects every test collected through tests/. A test file placed elsewhere would
not load this conftest.
"""

from __future__ import annotations

import contextlib
import io
import os
from collections import Counter

import psycopg2
import pytest
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extensions import make_dsn, parse_dsn

TEST_SUFFIX = "_test"
MAINTENANCE_DB = "postgres"
ADVISORY_LOCK_KEY = 640_201_064      # arbitrary constant: "one vdel test session at a time"

CONNECTED: Counter = Counter()       # connections actually opened, by database name
REFUSED: Counter = Counter()         # connections refused by the guard, by database name


class UnsafeTestDatabase(RuntimeError):
    """A DROP/CREATE/connect was about to touch something that is not a throwaway test DB."""


class _State:
    real_dsn: str | None = None
    real_name: str | None = None
    test_name: str | None = None
    maint = None                      # the maintenance connection; it holds the advisory lock
    problem: str | None = None
    real_connect = None               # psycopg2.connect before we wrapped it


STATE = _State()


# --- the hard refusal -------------------------------------------------------------------------

def derive_test_name(real_name: str) -> str:
    return real_name + TEST_SUFFIX


def assert_safe_target(target: str, real_name: str) -> None:
    """The three checks, run immediately before EVERY DROP and CREATE. Explicit raises, not
    `assert`, so `python -O` cannot strip them."""
    if not real_name:
        raise UnsafeTestDatabase("the real database name is unknown; refusing")
    if target != derive_test_name(real_name):
        raise UnsafeTestDatabase(
            f"target {target!r} is not derived from the real database {real_name!r} "
            f"(expected {derive_test_name(real_name)!r}); refusing")
    if not target.endswith(TEST_SUFFIX):
        raise UnsafeTestDatabase(f"target {target!r} does not end with {TEST_SUFFIX!r}; refusing")
    if target.casefold() == real_name.casefold():
        raise UnsafeTestDatabase(f"target {target!r} IS the real database; refusing")


def drop_database(conn, target: str, real_name: str) -> None:
    assert_safe_target(target, real_name)
    with conn.cursor() as cur:
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)")
                    .format(sql.Identifier(target)))


def create_database(conn, target: str, real_name: str) -> None:
    assert_safe_target(target, real_name)
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))


def tune_database(conn, target: str, real_name: str) -> None:
    """Timeouts for the throwaway database only. A fixture that fails while holding an open
    transaction used to freeze the whole run (the next test's INSERT of the same key waits on
    its lock forever, found when the suite was first run against an empty database). Now such
    a test FAILS after 20 s instead, and an abandoned transaction is cut after 5 minutes."""
    assert_safe_target(target, real_name)
    with conn.cursor() as cur:
        for setting, value in (("lock_timeout", "20s"),
                               ("idle_in_transaction_session_timeout", "300s")):
            cur.execute(sql.SQL("ALTER DATABASE {} SET {} = {}").format(
                sql.Identifier(target), sql.Identifier(setting), sql.Literal(value)))


# --- the connection audit + refusal -----------------------------------------------------------

def _dbname_of(dsn, kwargs) -> str | None:
    full = make_dsn(dsn, **kwargs) if (dsn or kwargs) else ""
    return parse_dsn(full).get("dbname") if full else None


def install_connection_guard(real_name: str) -> None:
    """Wrap psycopg2.connect: refuse the real database (or an unnamed one, which libpq would
    resolve from defaults we cannot see), count everything else."""
    STATE.real_connect = psycopg2.connect

    def guarded(dsn=None, *args, **kwargs):
        name = _dbname_of(dsn, kwargs)
        if name is None or name.casefold() == real_name.casefold():
            REFUSED[name] += 1
            raise UnsafeTestDatabase(
                f"refusing to connect to {name!r} during a test session: only "
                f"{derive_test_name(real_name)!r} and the maintenance database are allowed")
        CONNECTED[name] += 1
        return STATE.real_connect(dsn, *args, **kwargs)

    psycopg2.connect = guarded


def remove_connection_guard() -> None:
    if STATE.real_connect is not None:
        psycopg2.connect = STATE.real_connect
        STATE.real_connect = None


# --- session lifecycle ------------------------------------------------------------------------

def _fail_closed(reason: str) -> None:
    """No test database: make sure NOTHING can reach the real one. DB tests will skip.

    PG_DSN is set to the EMPTY string, not removed: system/db.py runs load_dotenv() on
    import, which would put the real DSN straight back from .env if the variable were
    absent -- but load_dotenv never overrides a variable that exists. An empty value is
    falsy for every skip check and for db.dsn(). (Found by running this path live: with
    the variable removed, DB tests errored instead of skipping.)"""
    STATE.problem = reason
    os.environ["PG_DSN"] = ""
    os.environ["VDEL_TESTING"] = "1"
    if os.environ.get("VDEL_REQUIRE_DB") == "1":
        raise pytest.UsageError(f"VDEL_REQUIRE_DB=1 but no test database: {reason}")


def _open_maintenance(real_dsn: str):
    """The maintenance connection. It holds the session-level advisory lock, so it must stay
    open for the whole session; the caller stores it (and nothing else mutates STATE.maint)."""
    maint = psycopg2.connect(make_dsn(real_dsn, dbname=MAINTENANCE_DB))
    maint.autocommit = True
    with maint.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
        if not cur.fetchone()[0]:
            maint.close()
            raise pytest.UsageError(
                "another test session is already running against this server; two "
                "concurrent runs would drop each other's test database")
    return maint


def _build_test_database(maint, real_dsn: str, real_name: str, test_name: str) -> None:
    """Create, tune, migrate and seed the throwaway database through `maint`. Takes the
    connection as an argument and mutates no shared state until the checks have passed."""
    drop_database(maint, test_name, real_name)
    create_database(maint, test_name, real_name)
    tune_database(maint, test_name, real_name)

    os.environ["VDEL_TESTING"] = "1"
    os.environ["PG_DSN"] = make_dsn(real_dsn, dbname=test_name)

    # Imported only now, after PG_DSN points at the test database.
    from scripts.init_db import main as init_schema
    from scripts.seed_data import seed_curriculum
    from system import db

    with contextlib.redirect_stdout(io.StringIO()):
        init_schema()
    with db.cursor() as cur:
        seed_curriculum(cur, "weather_etl")
    with db.cursor() as cur:
        seed_curriculum(cur, "sales_analyzer", stages=("ingest", "clean", "aggregate", "load"))

    with db.cursor() as cur:                       # last check: where are we, really?
        cur.execute("SELECT current_database()")
        actual = cur.fetchone()[0]
    if actual != test_name or actual.casefold() == real_name.casefold():
        raise UnsafeTestDatabase(f"connected to {actual!r}, expected {test_name!r}")


def pytest_configure(config):
    load_dotenv()
    real_dsn = os.environ.get("PG_DSN")
    STATE.real_dsn = real_dsn
    if not real_dsn:
        return                                      # nothing configured: DB tests skip, as before
    STATE.real_name = parse_dsn(real_dsn).get("dbname")
    STATE.test_name = derive_test_name(STATE.real_name or "")

    if config.getoption("collectonly", default=False):
        _fail_closed("collect-only: no database is opened")
        return
    install_connection_guard(STATE.real_name)
    try:
        STATE.maint = _open_maintenance(real_dsn)
        _build_test_database(STATE.maint, real_dsn, STATE.real_name, STATE.test_name)
    except (UnsafeTestDatabase, pytest.UsageError):
        raise
    except Exception as exc:  # noqa: BLE001 -- any failure to build it means "fail closed"
        _fail_closed(f"{type(exc).__name__}: {exc}".strip())


def pytest_unconfigure(config):
    """Drop the throwaway database (checked again), release the lock, unwrap psycopg2."""
    maint = STATE.maint
    try:
        if maint is not None and not maint.closed:
            if os.environ.get("VDEL_KEEP_TEST_DB") != "1":
                drop_database(maint, STATE.test_name, STATE.real_name)
            with maint.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
            maint.close()
    finally:
        STATE.maint = None
        remove_connection_guard()


def pytest_report_header(config):
    if STATE.problem:
        return (f"vdel test database: UNAVAILABLE ({STATE.problem}) -- PG_DSN removed, "
                "database tests will SKIP; the real database is not used")
    if STATE.test_name and os.environ.get("VDEL_TESTING") == "1":
        return (f"vdel test database: {STATE.test_name} (created for this session); "
                f"the real database {STATE.real_name!r} is never opened")
    return "vdel test database: none configured (PG_DSN unset) -- database tests will skip"


def pytest_terminal_summary(terminalreporter):
    if not STATE.real_name:
        return
    tr = terminalreporter
    tr.write_sep("-", "D-064 database access during this session")
    tr.write_line(f"psycopg2 connections opened, by database: {dict(CONNECTED) or '{}'}")
    tr.write_line(f"connections to the real database {STATE.real_name!r}: "
                  f"{CONNECTED.get(STATE.real_name, 0)} opened, "
                  f"{REFUSED.get(STATE.real_name, 0)} refused")
    if STATE.problem:
        tr.write_line(f"test database was UNAVAILABLE: {STATE.problem}")


@pytest.fixture(autouse=True)
def _tests_run_against_a_test_database():
    """Cheap per-test check that nothing re-pointed the environment at a real database."""
    dsn_value = os.environ.get("PG_DSN")
    if dsn_value is not None:
        name = parse_dsn(dsn_value).get("dbname", "")
        if os.environ.get("VDEL_TESTING") == "1" and not name.endswith(TEST_SUFFIX):
            pytest.fail(f"PG_DSN points at {name!r}, not a *{TEST_SUFFIX} database, "
                        "during a test session", pytrace=False)
    yield
