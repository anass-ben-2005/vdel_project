"""Database access.

One connection helper for the whole repo. The previous version opened a fresh
connection inside every method (six copies of the same six lines), which meant a
collector run held no transaction boundary: a failure halfway through left some rows
committed and some not.

Note on layout: CLAUDE.md section 5 fixes the repository tree and does not list this
file. It goes in system/ because that is where infrastructure lives (llm.py,
observability.py). It is the only addition to the tree.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def dsn() -> str:
    """Read PG_DSN, failing loudly rather than at the first query."""
    value = os.environ.get("PG_DSN")
    if not value:
        raise RuntimeError("PG_DSN is not set. Copy .env.example to .env and fill it in.")
    return value


def _open():
    """psycopg2.connect, with libpq's error message made readable.

    On a Windows install whose locale is not English, libpq returns connection errors in
    the OS codepage (cp1252 here) while psycopg2 decodes them as UTF-8. Any connection
    failure then surfaces as `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9`
    with the real cause -- wrong password, wrong host, server down -- destroyed. It cost
    an hour to find that the actual message was "authentification par mot de passe
    echouee". Decoding it here means the next person reads the cause instead.
    """
    try:
        return psycopg2.connect(dsn())
    except UnicodeDecodeError as exc:
        detail = exc.object.decode("cp1252", errors="replace").strip()
        raise psycopg2.OperationalError(detail) from None


@contextmanager
def connect():
    """A connection that commits on success and rolls back on any exception."""
    conn = _open()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def cursor():
    """The common case: one cursor, one transaction."""
    with connect() as conn, conn.cursor() as cur:
        yield cur


@contextmanager
def dry_run_cursor():
    """A cursor whose work is always rolled back.

    For checks that must write in order to prove something (the smoke test writes a
    trace to prove traces rejects UPDATE) but must leave no trace behind.
    """
    conn = _open()
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.rollback()
        conn.close()
