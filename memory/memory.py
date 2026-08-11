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

Piece 2 adds a fourth deviation, decided as D-007: **mastery is recomputed by replaying
the log, never by folding a new outcome onto state read back from the profile.** B.5 did
the latter and restored only `p_mastery` and `n_obs` of `MasteryState`'s five fields,
dropping the Beta posterior and the history -- which froze `confidence` at 0.286 no matter
how many observations accumulated, and made the incremental and rebuild paths disagree on
the same events. Replay means `update_mastery` and `rebuild_mastery_from_traces` are one
implementation, so the M2 DoD holds by construction instead of by two code paths agreeing.

Piece 3 adds a fifth and sixth deviation:

5. **The recurrence rule is `variables.error_frequency.recurrence_check`, called, not
   re-implemented** -- see the comment above the recurrence-rule section for the
   correction this went through (D-011, superseding D-009's first, incomplete reading).
6. **A weakness's id is `w-{trace_id}` of the trace that opened it**, not B.5's
   `f"w-{len(weaknesses)+1:03d}"` counter, which two concurrent opens could compute
   identically. `traces.trace_id` is a Postgres `BIGSERIAL`; collision-free by
   construction, the same argument D-007 made for mastery, applied here to identity (D-010).

Written for BUILD_PLAN 2.1. Known gaps, all deliberate and none silent:
  - `kt_params` rows are seeded but not read; see PARAM_SET for why that is currently a
    no-op and when it stops being one.
  - Nothing yet writes real `ci_run` traces. When something does, its payload must carry
    `conclusion`, `item_difficulty` AND `error_class` -- three requirements on piece 5 or
    later, not two; recurrence silently sees nothing without the third.
  - The 30-day staleness transition (`open` -> `stale`) is not implemented: it depends on
    elapsed time regardless of new events, so it belongs to a scheduled job (like
    `sessionize.py`'s), not the fast path. Piece 4 or later.
  - The broad `rebuild_from_traces` (all four profile columns, not just mastery) is piece 4.
  - `verdict` traces do not feed mastery yet -- see NON_MASTERY_KINDS for the reason.
  - `apply_recurrence_rule`'s dedup is check-then-act, not atomic against a second,
    genuinely concurrent caller for the same student -- accepted at today's scale (one
    fast-path writer processing one event at a time), the same category of accepted
    limitation as V4's cohort-of-one degeneracy. Revisit if concurrent writers arrive.

The reading artifact `docs/reading/2026-08-11-memory-py-method-surface.md` has the full
method surface and the divergences found while reading B.5.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

# Imported rather than redefined: one definition of the sentinel, so it cannot drift.
# error_classifier is a pure module (it imports only `re`), so this adds no I/O and no cycle.
from collectors.error_classifier import UNCLASSIFIED
from system import db
from variables.error_frequency import recurrence_check
from variables.mastery import MasteryEstimator

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

# ---- What mastery is replayed FROM (D-007) --------------------------------------------
#
# Mastery is recomputed by replaying the log, so this constant defines what counts as
# evidence of an assessed attempt. It is named, and paired with an exhaustive statement of
# what is deliberately excluded, because the failure mode it guards is silence: a kind that
# should feed mastery but doesn't produces a profile that is quietly wrong and still
# reconstructible-looking. `test_every_kind_is_classified` fails if any member of KINDS is
# in neither set, so a new kind cannot be added without a decision being made about it.
MASTERY_TRACE_KINDS = frozenset({"ci_run"})

# Every other kind, with the reason it is not evidence. Prose, because the reason is the
# point -- an unexplained exclusion is indistinguishable from an oversight.
NON_MASTERY_KINDS = {
    "commit": "activity, not an assessed attempt -- carries no pass/fail signal",
    "error_event": "no payload contract defines an outcome yet; ci_run is the canonical "
                   "carrier of pass/fail. Revisit when something actually writes one",
    "verdict": "M4. An agent verdict IS mastery evidence, but its payload is a per-criterion "
               "0/2/4 rubric rather than a pass/fail, so the mapping from rubric score to "
               "BKT outcome is a decision that has not been made. Adding it here without "
               "that mapping would silently score every verdict as a failure",
    "grade": "M6 aggregate of verdicts -- replaying it would double-count what it summarises",
    "intervention": "a hint given, not knowledge demonstrated",
    "session_summary": "derived from other traces -- would double-count them",
    "profile_update": "the RECORD of a mastery recompute, not evidence for one. Replaying it "
                      "would feed the output back into its own input",
    "reflection_run": "LLM narrative about the learner, not an observation of one attempt",
}

# GitHub's `conclusion` vocabulary is wider than pass/fail: cancelled, skipped, timed_out,
# neutral, action_required, stale. Only two of them say anything about what the student
# knows. Anything else is skipped rather than coerced -- B.5's `== "success"` would score a
# cancelled run as a failure, which is evidence about CI infrastructure, not about a person.
OUTCOME = {"success": True, "failure": False}

# Names the parameter set the numbers were produced under, per CLAUDE.md 8's stored shape.
# kt_params rows exist (seeded per concept) but are NOT read yet: every row currently holds
# the column defaults from sql/03 (p_l0 0.30, p_t 0.15, p_guess 0.20, p_slip 0.10), which are
# identical to BKTParams' defaults, so loading them today would change no number. That stops
# being true the moment any row is EM-fitted -- see the module docstring's known gaps.
PARAM_SET = "bkt_v1"

# ---- The recurrence rule (D-011, correcting D-009) ---------------------------------------
#
# "Same error class >=2 within one assignment -> open a weakness now" is
# `variables/error_frequency.py`'s `recurrence_check`, already transcribed from
# VDEL_Modules_1_2_Build.md Variable 6 and cited to Becker 2016 (Repeated Error Density).
# `apply_recurrence_rule` below calls it directly rather than re-implementing the ">=2"
# threshold -- D-007's argument again, applied to a second piece of math: one
# implementation of the check, not two that must be kept in agreement by hand.
#
# D-009 originally read "error class" as CONCEPT, reasoning that the weakness schema is
# concept-keyed and BUILD_PLAN 2.2 says "concept". That count was wrong: it never checked
# for an existing implementation, and `recurrence_check` -- live, tested, cited, and
# already named in `docs/explanation.md` §7.6 as "the seam [M2] will plug into" -- counts
# by the raw error_class string, not concept. Two error classes mapping to the SAME concept
# ("ambiguous column", "cartesian product|cross join" -> both spark.joins) occurring once
# each is not a recurrence under this rule, even though they share a concept: Becker's
# signal is the SAME mistake repeating, not merely the same topic area.
#
# "Within one assignment" is unchanged from D-009: traces.assignment_id, not a calendar
# span -- CLAUDE.md's assignments.concepts[] already scopes concepts per assignment, and
# no document specifies a duration.
#
# The resulting weakness is still concept-tagged (the schema has no error_class field);
# only the trigger's counting key changed.

# B.5's own cap on a weakness's `note` (`note[:120]`) -- named so `open_weakness`'s two
# call sites can't drift to different numbers.
WEAKNESS_NOTE_MAX_CHARS = 120

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


def _stored_shape(result: dict) -> dict[str, Any]:
    """The mastery shape CLAUDE.md 8 documents, built from MasteryEstimator.update()'s
    return value.

    Carries `n` (invariant 8: 0.9 from n=2 is a rumour, from n=20 it is a fact) and
    `p_correct_next`, which is the falsifiable quantity -- the prediction that can be
    checked against what the student actually does next, and the reason BKT was chosen over
    an EWMA whose output has no external referent.
    """
    return {
        "p_mastery": result["p_mastery"],
        "p_correct_next": result["p_correct_next"],
        "n": result["n_obs"],
        "confidence": result["confidence"],
        "ci90": result["ci90"],
        "trend": result["trend"],
        "param_set": PARAM_SET,
    }


def _replay_concept(conn, student_id: str, concept: str) -> dict[str, Any] | None:
    """Recompute one concept's mastery from the log. Returns None if there is no evidence.

    This is the single implementation of the mastery mathematics (D-007). `update_mastery`
    and `rebuild_mastery_from_traces` both call it, so the M2 DoD -- wipe the profile,
    replay, get the identical numbers -- holds by construction rather than because two
    implementations happen to agree. The previous design restored `p_mastery` and `n_obs`
    from the profile but not the Beta posterior (`a`, `b`) or `history`, which froze
    confidence at 0.286 regardless of n and made the two paths disagree.

    Ordered by (ts, trace_id): ts alone is not a total order, and BKT is order-dependent,
    so two traces sharing a timestamp would otherwise replay in whatever order the planner
    chose and the rebuild would not be reproducible.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT payload FROM traces
            WHERE student_id = %s
              AND kind = ANY(%s)
              AND concept_ids @> ARRAY[%s]::text[]
            ORDER BY ts, trace_id
            """,
            (student_id, sorted(MASTERY_TRACE_KINDS), concept),
        )
        payloads = [row[0] for row in cur.fetchall()]

    est = MasteryEstimator()
    result = None
    for payload in payloads:
        correct = OUTCOME.get((payload or {}).get("conclusion"))
        if correct is None:
            continue          # not an assessed outcome -- see OUTCOME
        # Absent difficulty falls back to the estimator's own neutral default rather than
        # guessing. This is a REQUIREMENT ON WHOEVER WIRES THE FAST PATH, not a description
        # of today: nothing in the repo writes ci_run traces yet, so every such trace is
        # currently hand-made in tests. That writer must set item_difficulty from the item
        # bank (this function) AND assignment_id (apply_recurrence_rule's window) AND
        # error_class (apply_recurrence_rule's counting key) -- three payload fields this
        # module depends on, none of them optional in practice even though the schema
        # allows all three to be absent. Absent difficulty flattens replay to the estimator's
        # default; absent assignment_id or error_class makes a real recurrence invisible.
        difficulty = (payload or {}).get("item_difficulty", 0.5)
        result = est.update(concept, correct, difficulty)

    return _stored_shape(result) if result is not None else None


def _merge_mastery(conn, student_id: str, concept: str, shape: dict[str, Any]) -> None:
    """Write one concept's mastery into the profile without disturbing the others.

    The merge happens in SQL (`||` on jsonb) rather than by reading the profile into
    Python, mutating it and writing it back. Read-modify-write would make two concurrent
    updates on different concepts race, with the slower write silently discarding the
    faster one's concept.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO learner_profile (student_id, mastery)
            VALUES (%s, %s::jsonb)
            ON CONFLICT (student_id) DO UPDATE
            SET mastery = learner_profile.mastery || EXCLUDED.mastery,
                updated_at = now()
            """,
            (student_id, json.dumps({concept: shape})),
        )


def _concepts_with_evidence(conn, student_id: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT unnest(concept_ids) AS concept FROM traces
            WHERE student_id = %s AND kind = ANY(%s)
            ORDER BY concept
            """,
            (student_id, sorted(MASTERY_TRACE_KINDS)),
        )
        return [row[0] for row in cur.fetchall() if row[0] != UNCLASSIFIED]


def _failure_evidence_by_error_class(conn, student_id: str,
                                     assignment_id: str) -> dict[str, list[int]]:
    """This assignment's `ci_run` failures, grouped by `error_class`, oldest first.

    One query for the whole assignment rather than one per error_class: `recurrence_check`
    wants a full `{error_class: count}` dict anyway, and this shape gives both the counts
    (via `len`) and each qualifying class's evidence trace_ids from a single pass.

    Traces without an `error_class` in their payload (nothing currently writes real
    `ci_run` traces -- see the module docstring) contribute to no count; there is nothing
    to attribute them to. Reuses `MASTERY_TRACE_KINDS`/`OUTCOME` rather than a second
    definition of "what counts as a failure" for this purpose.

    ALSO REQUIRES `assignment_id` ON THE TRACE ITSELF, not just in payload: a `ci_run`
    trace logged without one will silently never count toward any assignment's recurrence,
    the same caution as `item_difficulty` in `_replay_concept`.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT trace_id, payload FROM traces
            WHERE student_id = %s AND assignment_id = %s AND kind = ANY(%s)
            ORDER BY ts, trace_id
            """,
            (student_id, assignment_id, sorted(MASTERY_TRACE_KINDS)),
        )
        rows = cur.fetchall()

    grouped: dict[str, list[int]] = {}
    for trace_id, payload in rows:
        payload = payload or {}
        if OUTCOME.get(payload.get("conclusion")) is False:
            error_class = payload.get("error_class")
            if error_class:
                grouped.setdefault(error_class, []).append(trace_id)
    return grouped


def _has_open_weakness(conn, student_id: str, concept: str) -> bool:
    profile = _select_profile(conn, student_id)
    return any(w["concept"] == concept and w["status"] == "open"
               for w in profile["weaknesses"])


def _append_weakness(conn, student_id: str, weakness: dict) -> None:
    """SQL-side array append, matching `_merge_mastery`'s reasoning: a Python
    read-modify-write of the whole `weaknesses` array would make two concurrent opens for
    different concepts race, with the slower write silently discarding the faster one's.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO learner_profile (student_id, weaknesses)
            VALUES (%s, %s::jsonb)
            ON CONFLICT (student_id) DO UPDATE
            SET weaknesses = learner_profile.weaknesses || EXCLUDED.weaknesses,
                updated_at = now()
            """,
            (student_id, json.dumps([weakness])),
        )


def _link_intervention_sql(conn, student_id: str, weakness_id: str,
                           intervention_trace_id: int) -> bool:
    """Atomic: find `weakness_id` inside the JSONB array and append to its
    `interventions` sub-array, entirely in one SQL statement rather than a Python
    read-modify-write -- same race `_merge_mastery`/`_append_weakness` avoid, applied to a
    mutation *inside* one array element instead of the array itself.

    The `WHERE ... @>` containment check means the UPDATE only touches a row that actually
    contains a weakness with this id, so `cur.rowcount` doubles as "did it exist" without a
    separate SELECT. The CASE's own containment check on `interventions` makes a second
    call with the same ids a no-op, matching `update_mastery`'s idempotence.

    Returns whether a matching weakness existed.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE learner_profile
            SET weaknesses = (
                    SELECT jsonb_agg(
                        CASE WHEN elem->>'id' = %(wid)s
                                  AND NOT (elem->'interventions' @> to_jsonb(%(tid)s::bigint))
                             THEN jsonb_set(elem, '{interventions}',
                                    (elem->'interventions') || to_jsonb(%(tid)s::bigint))
                             ELSE elem
                        END
                    )
                    FROM jsonb_array_elements(weaknesses) AS elem
                ),
                updated_at = now()
            WHERE student_id = %(sid)s
              AND weaknesses @> jsonb_build_array(jsonb_build_object('id', %(wid)s::text))
            """,
            {"wid": weakness_id, "tid": intervention_trace_id, "sid": student_id},
        )
        return cur.rowcount == 1


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

    # ---------- FAST PATH: deterministic mastery update ----------
    def update_mastery(self, student_id: str, concept: str, *,
                       parent_trace_id: int | None = None,
                       conn=None) -> dict[str, Any] | None:
        """Recompute one concept's mastery from the log and refresh the cached profile.

        **Takes no outcome argument, deliberately.** The evidence is whatever is already in
        `traces`, so the caller logs the attempt first (a `ci_run` trace carrying
        `conclusion` and `item_difficulty`) and then calls this. B.5 instead passed the
        outcome in and folded it onto partial state read back from the profile, which is
        what lost the Beta posterior and froze confidence at 0.286 regardless of n (D-007).

        Two properties follow from taking the evidence from the log rather than from
        arguments, and both are tested:

        - **Idempotent.** Calling it twice recomputes the same numbers, because it is a
          pure function of the log. An outcome-taking version counts a second call as a
          second attempt.
        - **Identical to a rebuild.** This is `rebuild_mastery_from_traces` restricted to
          one concept -- the same function, not a parallel implementation of it.

        Returns the stored shape, or None when the concept has no assessed evidence yet
        (the profile is then left untouched rather than written as empty).

        The profile write and the `profile_update` trace go in ONE transaction: a crash
        between them would leave a belief in the profile with no audit record of where it
        came from, which is the single state event sourcing exists to make impossible.
        Pass `parent_trace_id` (the `ci_run` that prompted this) to record causality.
        """
        if concept == UNCLASSIFIED:
            # Invariant 10: an unclassified error updates no mastery. Better to update
            # nothing than to move the wrong concept.
            return None

        with _session(conn) as c:
            shape = _replay_concept(c, student_id, concept)
            if shape is None:
                return None
            _merge_mastery(c, student_id, concept, shape)
            _insert_trace(
                c, student_id=student_id, actor="system", kind="profile_update",
                payload={"concept": concept, **shape}, assignment_id=None,
                concept_ids=[concept], parent_trace_id=parent_trace_id, session_id=None,
            )
        return shape

    # ---------- AUDIT: rebuild mastery from traces ----------
    def rebuild_mastery_from_traces(self, student_id: str, *,
                                    conn=None) -> dict[str, dict[str, Any]]:
        """Recompute the whole mastery vector from the log. The event-sourcing proof.

        Writes no `profile_update` traces: a rebuild recomputes what the log already
        implies, it is not new evidence about the student. Logging one per rebuild would
        grow the log every time the proof was run, making the proof observable in its own
        output.

        This is the mastery half of the M2 DoD. The other profile columns are piece 4 --
        `weaknesses` are likewise recomputed, but `reflections` can only be *recovered*
        from their `reflection_run` payloads, because an LLM wrote them and an LLM is not a
        deterministic function.
        """
        with _session(conn) as c:
            rebuilt: dict[str, dict[str, Any]] = {}
            for concept in _concepts_with_evidence(c, student_id):
                shape = _replay_concept(c, student_id, concept)
                if shape is not None:
                    rebuilt[concept] = shape
                    _merge_mastery(c, student_id, concept, shape)
            return rebuilt

    # ---------- FAST PATH: open a weakness (the raw primitive) ----------
    def open_weakness(self, student_id: str, concept: str, note: str,
                      evidence_trace_ids: list[int], *, conn=None) -> str:
        """Append a structured weakness. Unconditional -- the decision about WHEN to call
        this belongs to `apply_recurrence_rule`; this method just does it, so it stays
        callable directly (BUILD_PLAN 2.1 names it as one of the door's methods) without
        forcing every caller through the recurrence rule's threshold and dedup logic.

        Two deviations from B.5:

        - **The id is `w-{trace_id}` of the trace this call writes**, not a
          `len(weaknesses)+1` counter. `traces.trace_id` is a Postgres `BIGSERIAL`, so this
          is collision-free by construction. B.5's counter is not: two concurrent opens for
          the same student could both read the same length and mint the same id -- the same
          category of bug replay fixed for mastery (D-007), applied here to identity instead
          of arithmetic.
        - **`opened_at` is a real timestamp**, not B.5's literal string `"now"`.

        Logs the trace before appending the weakness, not after, precisely because the
        weakness's own id depends on it.
        """
        with _session(conn) as c:
            trace_id = _insert_trace(
                c, student_id=student_id, actor="system", kind="profile_update",
                payload={"action": "weakness_opened", "concept": concept,
                         "note": note[:WEAKNESS_NOTE_MAX_CHARS],
                         "evidence": list(evidence_trace_ids)},
                assignment_id=None, concept_ids=[concept],
                parent_trace_id=None, session_id=None,
            )
            wid = f"w-{trace_id}"
            _append_weakness(c, student_id, {
                "id": wid, "concept": concept, "status": "open",
                "note": note[:WEAKNESS_NOTE_MAX_CHARS],
                "evidence": list(evidence_trace_ids),
                "opened_at": datetime.now(UTC).isoformat(),
                "interventions": [],
            })
        return wid

    # ---------- FAST PATH: the recurrence rule ----------
    def apply_recurrence_rule(self, student_id: str, assignment_id: str,
                              error_class: str, concept: str, *,
                              conn=None) -> str | None:
        """The same `error_class` recurring within one assignment opens a weakness.

        Wired to `variables.error_frequency.recurrence_check` -- the module-level comment
        above explains why this call exists instead of a second ">=2" check, and what
        changed from this method's first draft (D-011, correcting D-009).

        Takes BOTH `error_class` and `concept` because a caller always has both together:
        they are `collectors.error_classifier.classify_error()`'s return value, produced
        by classifying the one failure that just happened. `error_class` decides whether
        this is a recurrence; `concept` is what the resulting weakness gets tagged with,
        since the weakness schema has no `error_class` field.

        Deduplicates against any currently-**open** weakness for the concept -- not
        closed, escalated or stale ones. A concept recurring after its weakness was closed
        is new evidence, not a repeat of old evidence, and deserves a new weakness.

        **Idempotent**, deliberately: calling it after every failure (not just the one that
        first crosses the threshold) is safe, because it no-ops once a weakness is already
        open. That lets the fast path call it unconditionally rather than tracking whether
        it already fired for this student and concept.

        Returns the newly opened weakness's id, or `None` if nothing changed this call:
        the concept is unclassified, `error_class` hasn't recurred yet, or a weakness for
        the concept is already open.
        """
        if concept == UNCLASSIFIED or not error_class:
            return None
        with _session(conn) as c:
            if _has_open_weakness(c, student_id, concept):
                return None
            grouped = _failure_evidence_by_error_class(c, student_id, assignment_id)
            counts = {ec: len(ids) for ec, ids in grouped.items()}
            if error_class not in recurrence_check(counts):
                return None
            evidence = grouped[error_class]
            note = f"{len(evidence)}x {error_class!r} in assignment {assignment_id}"
            return self.open_weakness(student_id, concept, note, evidence, conn=c)

    # ---------- Close the loop: link a coach hint to the weakness it targeted ----------
    def link_intervention(self, student_id: str, weakness_id: str,
                          intervention_trace_id: int, *, conn=None) -> None:
        """Record that a coach hint targeted a weakness.

        This is the array (`weaknesses[i].interventions`) that makes "after we intervened,
        did verdicts on that concept improve?" answerable later -- the reflection job's
        golden question (Modules_3_9 B.4). Without this link, "we gave 40 hints" and "did
        they work" are two different, disconnected claims.

        **Raises if `weakness_id` does not exist**, rather than silently doing nothing as
        B.5 does: its loop falls through on no match with no error, and still re-writes an
        unchanged `weaknesses` array. A hint recorded against a typo'd weakness id is a
        broken link that would otherwise surface only when the reflection job's own
        validation catches it, days later.
        """
        with _session(conn) as c:
            found = _link_intervention_sql(c, student_id, weakness_id, intervention_trace_id)
            if not found:
                raise ValueError(
                    f"unknown weakness_id {weakness_id!r} for student {student_id!r}"
                )
            _insert_trace(
                c, student_id=student_id, actor="system", kind="profile_update",
                payload={"action": "intervention_linked", "weakness_id": weakness_id,
                         "intervention_trace_id": intervention_trace_id},
                assignment_id=None, concept_ids=None,
                parent_trace_id=intervention_trace_id, session_id=None,
            )
