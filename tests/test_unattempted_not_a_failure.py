"""D-084 -- a hidden test of a gap that is still a NotImplementedError stub is not a failure in
V5/V6 (formula v6 on). vdel_test, one rolled-back transaction.

The definition of "unattempted" is `assessment.test_runner.gap_observation` (D-079); these tests
never re-implement it, they check that the trace flag and the computation honour it. Versions up
to v5 keep counting such a test, so their stored rows stay reproducible."""

from __future__ import annotations

import os

import pytest

from assessment import test_runner as tr
from assessment.test_runner import TestOutcome
from features import compute_features as cf
from memory.memory import Memory
from system import db
from tests.support import ensure_variant

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

S, ASG = "_d084", "weather_etl_extract"
RETRY, PARSE = "g_ext_retry", "g_ext_parse"      # RETRY: [errors_debugging, data_structures]
NIE = "NotImplementedError"
SHA1, SHA2 = "d084_sha_1", "d084_sha_2"


@pytest.fixture
def world():
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, S))
    variant = ensure_variant(cur, ASG)
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl',%s,1,%s,1) RETURNING attempt_id",
                (S, ASG, variant))
    attempt_id = cur.fetchone()[0]
    yield conn, cur, attempt_id
    conn.rollback()
    conn.close()


def outcomes(retry=(), parse=()):
    """Each item: True (pass), False (assertion failure) or NIE (the stub)."""
    out = []
    for gap, results in ((RETRY, retry), (PARSE, parse)):
        for i, r in enumerate(results):
            passed = r is True
            message = None if passed else (NIE if r == NIE else "assert 1 == 2")
            out.append(TestOutcome(f"tests/hidden/test_extract.py::t_{gap}_{i}", passed,
                                   message, gap))
    return out


def log(world, sha, outs):
    """Write the test_result traces exactly as grade_attempt does."""
    conn, cur, attempt_id = world
    gap_meta = tr._gap_metadata(cur, {o.gap_id for o in outs})
    hidden = tr._hidden_gap_ids(cur, attempt_id)
    tr._log_test_result_traces(Memory(), conn, S, ASG, attempt_id, sha, outs,
                               {o.test_name for o in outs}, gap_meta, hidden)


def v6(world, version):
    return cf.compute_for_student(world[1], S, version)["error_frequency"]


def history(world):
    return Memory().test_result_history(S, conn=world[0])


# --- the trace says whether the gap was attempted --------------------------------------------

def test_the_trace_flags_a_stub_gap_as_not_attempted_for_every_test_of_that_gap(world):
    # retry: one stub, one test that passes for free -> the GAP is unattempted, both flagged
    log(world, SHA1, outcomes(retry=[NIE, True], parse=[True, False]))
    flags = {(h["gap_id"], h["passed"]): h["attempted"] for h in history(world)}
    assert flags == {(RETRY, False): False, (RETRY, True): False,
                     (PARSE, True): True, (PARSE, False): True}


# --- V5/V6 -------------------------------------------------------------------------------------

def test_an_unattempted_stub_is_not_counted_as_a_failure_from_v6_on(world):
    log(world, SHA1, outcomes(retry=[NIE, NIE], parse=[True, True]))
    old, new = v6(world, "v5"), v6(world, "v6")
    assert old["fail_ratio"] == 0.5 and set(old["by_concept"]) == {
        "py.errors_debugging", "py.data_structures"}                 # v5 still counts the stub
    assert new["fail_ratio"] == 0.0 and new["by_concept"] == {}      # v6 does not
    assert len(history(world)) == 4                                  # still stored as evidence


def test_a_real_assertion_error_is_still_counted(world):
    log(world, SHA1, outcomes(retry=[True, False], parse=[True, True]))
    new = v6(world, "v6")
    assert new["fail_ratio"] == 0.25
    assert new["by_concept"] == {"py.errors_debugging": 1, "py.data_structures": 1}
    assert new == v6(world, "v5")                                    # nothing to exclude here


def test_a_gap_that_was_a_stub_in_one_commit_and_then_passed(world):
    log(world, SHA1, outcomes(retry=[NIE, NIE]))                     # not attempted yet
    log(world, SHA2, outcomes(retry=[True, True]))                   # then solved
    new, old = v6(world, "v6"), v6(world, "v5")
    assert new["fail_ratio"] == 0.0 and new["by_concept"] == {}      # 2 passes, 0 failures
    assert old["fail_ratio"] == 0.5  # v5: 2 stubs + 2 passes


# --- traces written before the flag existed ----------------------------------------------------

def test_an_older_trace_that_names_its_commit_is_resolved_from_test_results(world):
    conn, cur, attempt_id = world
    for name in ("t_a", "t_b"):
        cur.execute("INSERT INTO test_results (attempt_id, commit_sha, test_name, gap_id, passed,"
                    " message, status) VALUES (%s,%s,%s,%s,false,%s,'ok')",
                    (attempt_id, SHA1, name, RETRY, NIE))
    # as written on 2026-10-11, between D-079 and D-084: identity in the payload, no `attempted`
    Memory().log_trace(S, "system", "test_result",
                       {"conclusion": "failure", "item_difficulty": 0.35,
                        "attempt_id": attempt_id, "commit_sha": SHA1, "gap_id": RETRY,
                        "test_name": "t_a"},
                       assignment_id=ASG, concept_ids=["py.errors_debugging"], conn=conn)
    assert history(world)[0]["attempted"] is None
    assert v6(world, "v5")["fail_ratio"] == 1.0
    assert v6(world, "v6")["fail_ratio"] == 0.0


def test_a_trace_that_names_nothing_cannot_be_resolved_and_is_kept(world):
    conn, _, _ = world
    Memory().log_trace(S, "system", "test_result",
                       {"conclusion": "failure", "item_difficulty": 0.35},
                       assignment_id=ASG, concept_ids=["py.errors_debugging"], conn=conn)
    assert v6(world, "v6")["fail_ratio"] == 1.0                      # never dropped by guess


def test_older_formula_versions_are_unchanged():
    assert [cf._excludes_unattempted(v) for v in ("v2", "v3", "v4", "v5", "v6")] == \
        [False, False, False, False, True]
    assert cf.UNATTEMPTED_EXCLUDED_FROM == "v6" and cf.FORMULA_VER >= "v6"
