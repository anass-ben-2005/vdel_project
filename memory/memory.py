"""memory/memory.py — the ONLY interface agents use to touch memory (invariant 2).

Agents never write raw SQL to `traces` or `learner_profile`. One door means one place to
audit and one place to change when the schema moves; the moment anything reaches past it,
`rebuild_from_traces` stops being a proof and becomes an opinion.

Transcribed from VDEL_Modules_3_9_Build.md B.5, with three deliberate deviations, each
recorded rather than silent:

1. **No connection is held.** B.5 does `psycopg2.connect(dsn)` in `__init__` and keeps
   `self.conn` for the lifetime of the object. `system/db.py` exists precisely because
   that pattern produced "a collector run held no transaction boundary: a failure halfway
   through left some rows committed and some not", and its docstring makes it the single
   place `psycopg2.connect()` is called. So `Memory` is stateless and every public method
   is one explicit transaction.

2. **Every public method takes an optional `conn`.** Passing one joins the caller's
   transaction; omitting it opens and commits its own. This exists because the fast path
   must write the profile *and* its trace atomically -- a crash between them would leave a
   belief with no audit record, which is the one state event sourcing must make
   impossible. B.5 commits them separately.

3. **`__init__` takes no DSN.** `db.dsn()` already reads `PG_DSN` and fails loudly if it
   is unset; a second copy of that job is a second thing to keep in sync.

Written for M2.1 (BUILD_PLAN 2.1). The fast path (`update_mastery`), the recurrence rule
and `rebuild_from_traces` land in later pieces; the reading artifact
`docs/reading/2026-08-11-memory-py-method-surface.md` has the full method surface.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

from system import db

# The trace vocabulary, as the UNION of its two authorities -- each contains something the
# other lacks, so neither alone is safe to validate against:
#   - Modules_3_9 B.4 lists the `reviewer`/`student` actors and the `commit`, `ci_run`,
#     `grade`, `session_summary`, `profile_update` kinds. CLAUDE.md 6 omits all of them,
#     yet B.5 writes `profile_update`, B.6 writes `session_summary`, and the rebuild reads
#     `ci_run` -- so CLAUDE.md's list is abbreviated, not deliberately narrower.
#   - CLAUDE.md 6 lists `error_event`, which B.4 omits and `scripts/smoke_test.py` writes.
#
# Validated strictly, and that is the point: a typo'd kind (`ci-run` for `ci_run`) would
# insert cleanly and then sit silently outside the replay set, which is exactly how a
# profile stops being reconstructible. Adding a kind is meant to require a code change,
# because the replay set has to be updated in the same breath.
ACTORS = frozenset({
    "system", "student", "coach", "reviewer",
    "code_agent", "perf_agent", "pedagogy_agent",
})

KINDS = frozenset({
    "commit", "ci_run", "error_event", "verdict", "grade",
    "intervention", "session_summary", "profile_update", "reflection_run",
})

# learner_profile's JSONB columns, and the shape get_profile guarantees to its callers.
# Kept as a tuple because the SELECT order and the returned keys must not drift apart.
_PROFILE_COLUMNS = ("mastery", "weaknesses", "reflections", "session_digest")


def _empty_profile() -> dict[str, Any]:
    """A fresh profile for a student with no row yet.

    Built per call rather than shared from a module constant: callers mutate what they get
    back (the fast path does `profile["mastery"][concept] = ...`), and a shared default
    would silently accumulate one student's beliefs into every other student's.
    """
    return {"mastery": {}, "weaknesses": [], "reflections": [], "session_digest": []}


@contextmanager
def _session(conn):
    """Join the caller's transaction, or own one for the duration of this call.

    `db.connect()` commits on success and rolls back on any exception, so an owned
    transaction is atomic by construction. A joined one leaves the commit decision -- and
    therefore the atomicity guarantee -- with the caller.
    """
    if conn is not None:
        yield conn
    else:
        with db.connect() as owned:
            yield owned


def _require(value: str, allowed: frozenset[str], field: str) -> None:
    raise_if_unknown = value not in allowed
    if raise_if_unknown:
        raise ValueError(
            f"unknown {field} {value!r}. Allowed: {', '.join(sorted(allowed))}. "
            f"Adding one is a code change in memory/memory.py, deliberately -- see the "
            f"vocabulary comment there."
        )


def _insert_trace(conn, **fields) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO traces (parent_trace_id, session_id, student_id, actor,
                                kind, assignment_id, concept_ids, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING trace_id
            """,
            (fields["parent_trace_id"], fields["session_id"], fields["student_id"],
             fields["actor"], fields["kind"], fields["assignment_id"],
             list(fields["concept_ids"] or []), json.dumps(fields["payload"])),
        )
        return cur.fetchone()[0]


def _select_profile(conn, student_id: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(_PROFILE_COLUMNS)} FROM learner_profile WHERE student_id = %s",
            (student_id,),
        )
        row = cur.fetchone()
    if row is None:
        return _empty_profile()
    return dict(zip(_PROFILE_COLUMNS, row, strict=True))


class Memory:
    """The only door to memory.

    Deliberately stateless -- see this module's docstring. Construct one and share it;
    there is nothing to keep alive and nothing to close.
    """

    # ---------- WRITE: append-only trace ----------
    def log_trace(self, student_id: str, actor: str, kind: str, payload: dict, *,
                  assignment_id: str | None = None,
                  concept_ids: list[str] | None = None,
                  parent_trace_id: int | None = None,
                  session_id: int | None = None,
                  conn=None) -> int:
        """Append one event to the log and return its `trace_id`.

        The returned id is load-bearing, not a convenience: `parent_trace_id` uses it to
        turn a flat log into a causal forest, and weakness objects cite it as the evidence
        that justifies them.

        INSERT only (invariant 1). The append-only guarantee itself is enforced one layer
        down by the Postgres RULEs in sql/05 -- this method is the application-level door,
        not the mechanism.
        """
        _require(actor, ACTORS, "actor")
        _require(kind, KINDS, "kind")
        with _session(conn) as c:
            return _insert_trace(
                c, student_id=student_id, actor=actor, kind=kind, payload=payload,
                assignment_id=assignment_id, concept_ids=concept_ids,
                parent_trace_id=parent_trace_id, session_id=session_id,
            )

    # ---------- READ: current belief ----------
    def get_profile(self, student_id: str, *, conn=None) -> dict[str, Any]:
        """Current belief about a student.

        Returns populated empty structures for an unknown student rather than None, so no
        caller has to special-case a student's first event.

        `features_ref` is deliberately not returned: B.5 does not read it and nothing
        writes it yet. It stays out of the contract until something owns it, rather than
        appearing as a key that is always None.
        """
        with _session(conn) as c:
            return _select_profile(c, student_id)

    def snapshot_profile(self, student_id: str, *, conn=None) -> dict[str, Any]:
        """Frozen read for the orchestrator's snapshot rule (Modules_3_9 H.2).

        Identical to `get_profile` today, and named separately on purpose. H.2 requires
        every agent in one grading run to judge against the *same* belief state -- else the
        same submission is judged in two different contexts -- and requires that snapshot
        to be recorded in the grade trace, so "what did the system believe when it graded
        this?" is answerable by pointing at a row. The freezing arrives with the
        orchestrator in M6; naming the seam now means no agent changes when it does.
        """
        return self.get_profile(student_id, conn=conn)
