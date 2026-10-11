"""D-079 -- one mastery observation per (attempt, GAP), the first attempted pushed commit.

Everything runs in vdel_test inside one transaction that is rolled back (traces cannot be
deleted). The rule is exercised directly on synthetic outcomes (fast, exact) and, for the
end-to-end claim, through the real `grade_attempt` with the real hidden tests."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from assessment import test_runner as tr
from assessment.test_runner import TestOutcome
from memory.memory import OBS_RULE_VER, Memory
from scripts.prove_event_sourcing import prove
from system import db
from tests.support import ensure_variant

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

S, ASG = "_obs_student", "weather_etl_extract"
CURRICULUM_ROOT = Path(__file__).resolve().parent.parent / "curriculum" / "master"
T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
SHA = {1: "obs_sha_1", 2: "obs_sha_2", 3: "obs_sha_3"}
ED, DS = "py.errors_debugging", "py.data_structures"
RETRY, PARSE = "g_ext_retry", "g_ext_parse"     # RETRY lists [ED, DS]; PARSE lists [DS]
NIE = "NotImplementedError"


@pytest.fixture
def world():
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, S))
    variant = ensure_variant(cur, ASG)          # hides BOTH extract gaps
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl',%s,1,%s,1) RETURNING attempt_id",
                (S, ASG, variant))
    attempt_id = cur.fetchone()[0]
    for n, sha in SHA.items():
        cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                    " VALUES (%s,%s,%s,%s)", (sha, S, ASG, T0 + timedelta(hours=n)))
    yield conn, cur, attempt_id
    conn.rollback()
    conn.close()


def outcomes(retry=(), parse=(), status="ok"):
    """TestOutcomes for the two gaps. Each item is True (pass), False (assertion failure) or
    NIE (the stub)."""
    out = []
    for gap, results in ((RETRY, retry), (PARSE, parse)):
        for i, r in enumerate(results):
            passed = r is True
            message = None if passed else (NIE if r == NIE else "assert 1 == 2")
            out.append(TestOutcome(f"tests/hidden/test_extract.py::t_{gap}_{i}", passed,
                                   message, gap, status))
    return out


def observe(world, sha, outs):
    """Run the rule exactly as grade_attempt does; return the new trace ids."""
    conn, cur, attempt_id = world
    gap_meta = tr._gap_metadata(cur, {o.gap_id for o in outs if o.gap_id})
    hidden = tr._hidden_gap_ids(cur, attempt_id)
    return tr._log_mastery_observations(Memory(), conn, cur, S, ASG, attempt_id, sha, outs,
                                        gap_meta, hidden)


def observations(world):
    _, cur, _ = world
    cur.execute("SELECT payload, concept_ids FROM traces WHERE student_id=%s"
                " AND kind='mastery_observation' ORDER BY trace_id", (S,))
    return cur.fetchall()


# --- the rule ------------------------------------------------------------------------------

def test_the_first_attempted_commit_is_the_observation(world):
    # commit 1: parse attempted and passing, retry still a stub -> only parse is observed
    observe(world, SHA[1], outcomes(retry=[NIE, NIE], parse=[True, True]))
    rows = observations(world)
    assert [(p["gap_id"], p["conclusion"], p["commit_sha"]) for p, _ in rows] == \
        [(PARSE, "success", SHA[1])]
    # commit 2: retry attempted but wrong -> observed now, as a failure, at commit 2's time
    observe(world, SHA[2], outcomes(retry=[True, False], parse=[True, True]))
    rows = observations(world)
    assert [(p["gap_id"], p["conclusion"], p["commit_sha"]) for p, _ in rows] == \
        [(PARSE, "success", SHA[1]), (RETRY, "failure", SHA[2])]
    assert rows[1][0]["observed_at"] == (T0 + timedelta(hours=2)).isoformat()
    assert rows[1][0]["rule_ver"] == OBS_RULE_VER


def test_a_gap_with_any_notimplemented_test_is_not_attempted(world):
    assert observe(world, SHA[1], outcomes(retry=[True, NIE])) == []
    assert observations(world) == []


def test_a_collection_error_and_a_timeout_are_not_observations(world):
    for status in ("collection_error", "timeout", "tooling"):
        assert observe(world, SHA[1], outcomes(retry=[False, False], parse=[False],
                                               status=status)) == []
    assert observations(world) == []


def test_a_local_run_is_never_an_observation(world):
    assert observe(world, None, outcomes(retry=[True, True], parse=[True, True])) == []
    assert observations(world) == []


def test_a_commit_missing_from_raw_commits_writes_nothing_and_does_not_crash(world):
    assert observe(world, "no_such_commit", outcomes(retry=[True, True])) == []


def test_grading_the_same_commit_twice_writes_one_observation(world):
    outs = outcomes(retry=[True, True], parse=[True, True])
    first = observe(world, SHA[1], outs)
    assert len(first) == 2
    assert observe(world, SHA[1], outs) == []
    assert len(observations(world)) == 2


def test_a_later_commit_never_adds_a_second_observation_for_the_gap(world):
    observe(world, SHA[1], outcomes(retry=[True, False], parse=[True]))      # retry fails
    assert observe(world, SHA[2], outcomes(retry=[True, True], parse=[True])) == []   # now passes
    assert observe(world, SHA[3], outcomes(retry=[False, False], parse=[False])) == []
    rows = observations(world)
    assert [(p["gap_id"], p["conclusion"]) for p, _ in rows] == \
        [(PARSE, "success"), (RETRY, "failure")]          # gaps are written in gap_id order
    shapes = Memory().replay_mastery(S, conn=world[0])[0]
    assert shapes[ED]["n"] == 1 and shapes[DS]["n"] == 1            # one item each, ever


def test_several_gaps_in_one_attempt_are_observed_independently(world):
    new = observe(world, SHA[1], outcomes(retry=[True, True], parse=[True, True]))
    assert len(new) == 2
    shapes = Memory().get_profile(S, conn=world[0])["mastery"]
    # parse -> DS; retry lists [ED, DS] but only ED receives it: DS has ONE item, not two
    assert shapes[ED]["n"] == 1 and shapes[DS]["n"] == 1


def test_only_the_first_listed_concept_gets_the_observation(world):
    observe(world, SHA[1], outcomes(retry=[True, True]))
    ((payload, concept_ids),) = observations(world)
    assert concept_ids == [ED]
    assert payload["concept"] == ED and payload["concepts"] == [ED, DS]
    assert set(Memory().get_profile(S, conn=world[0])["mastery"]) == {ED}


def test_the_shape_carries_n_and_the_observation_rule(world):
    observe(world, SHA[1], outcomes(retry=[True, True]))
    shape = Memory().get_profile(S, conn=world[0])["mastery"][ED]
    assert shape["n"] == 1 and shape["obs_rule"] == OBS_RULE_VER and shape["param_set"] == "bkt_v1"


def test_test_result_traces_alone_no_longer_move_mastery(world):
    conn, _, _ = world
    Memory().log_trace(S, "system", "test_result",
                       {"conclusion": "success", "item_difficulty": 0.35},
                       assignment_id=ASG, concept_ids=[ED], conn=conn)
    assert Memory().replay_mastery(S, conn=conn)[0] == {}


def test_record_requires_a_timezone_aware_time(world):
    conn, _, attempt_id = world
    with pytest.raises(ValueError):
        Memory().record_mastery_observation(
            S, attempt_id=attempt_id, assignment_id=ASG, gap_id=RETRY, concept_ids=[ED],
            passed=True, item_difficulty=0.35, commit_sha="x", observed_at=datetime(2026, 1, 1),  # noqa: DTZ001
            conn=conn)


# --- replay: order, determinism, the Beat 7 proof -----------------------------------------------

def _record(world, gap, passed, hours):
    conn, _, attempt_id = world
    return Memory().record_mastery_observation(
        S, attempt_id=attempt_id, assignment_id=ASG, gap_id=gap, concept_ids=[ED], passed=passed,
        item_difficulty=0.35, commit_sha=f"c{hours}", observed_at=T0 + timedelta(hours=hours),
        conn=conn)


def test_replay_is_ordered_by_the_commit_time_not_by_when_the_trace_was_written(world):
    conn = world[0]
    # written (trace_id order): the LATER commit's failure first, then the earlier success
    _record(world, "g_late", False, 5)
    _record(world, "g_early", True, 1)
    by_time = Memory().replay_mastery(S, conn=conn)[0][ED]
    # the same two observations folded in commit-time order: success, then failure
    from memory.memory import _fold_payloads
    _, expected = _fold_payloads(ED, [
        {"conclusion": "success", "item_difficulty": 0.35},
        {"conclusion": "failure", "item_difficulty": 0.35}])
    assert by_time["p_mastery"] == pytest.approx(expected["p_mastery"], abs=1e-9)
    _, wrong_order = _fold_payloads(ED, [
        {"conclusion": "failure", "item_difficulty": 0.35},
        {"conclusion": "success", "item_difficulty": 0.35}])
    assert by_time["p_mastery"] != pytest.approx(wrong_order["p_mastery"], abs=1e-6)


def test_rebuild_is_deterministic_and_beat_7_stays_identical(world):
    conn = world[0]
    mem = Memory()
    observe(world, SHA[1], outcomes(retry=[True, False], parse=[True, True]))
    observe(world, SHA[2], outcomes(retry=[True, True], parse=[True, True]))
    mem.update_mastery(S, ED, conn=conn)
    mem.update_mastery(S, DS, conn=conn)
    stored = mem.get_profile(S, conn=conn)["mastery"]
    first = mem.rebuild_from_traces(S, conn=conn)["mastery"]
    second = mem.rebuild_from_traces(S, conn=conn)["mastery"]
    assert first == second == stored
    result = prove(conn)                     # wipe learner_profile, replay, compare
    assert result.identical and not result.vacuous and result.differences == []
    assert S in result.compared


def test_the_what_if_replay_equals_a_real_append_and_writes_nothing(world):
    conn, cur, _ = world
    mem = Memory()
    observe(world, SHA[1], outcomes(retry=[True, False]))
    extra = [{"concept": ED, "conclusion": "success", "item_difficulty": 0.35,
              "observed_at": (T0 + timedelta(hours=9)).isoformat()},
             {"concept": DS, "conclusion": "failure", "item_difficulty": 0.35,
              "observed_at": (T0 + timedelta(hours=9)).isoformat()}]
    cur.execute("SELECT count(*) FROM traces WHERE student_id=%s", (S,))
    before = cur.fetchone()[0]
    predicted = mem.replay_mastery_with(S, extra, conn=conn)
    cur.execute("SELECT count(*) FROM traces WHERE student_id=%s", (S,))
    assert cur.fetchone()[0] == before                                   # nothing written
    _record(world, "g_x", True, 9)
    Memory().record_mastery_observation(
        S, attempt_id=world[2], assignment_id=ASG, gap_id="g_y", concept_ids=[DS], passed=False,
        item_difficulty=0.35, commit_sha="cy", observed_at=T0 + timedelta(hours=9), conn=conn)
    assert mem.replay_mastery(S, conn=conn)[0] == predicted


# --- end to end through the real grade_attempt (real hidden tests, real subprocess) -------------

@pytest.fixture
def solved_extract_repo(tmp_path):
    src = CURRICULUM_ROOT / "weather_etl" / "weather_etl"
    (tmp_path / "weather_etl").mkdir()
    shutil.copyfile(src / "extract.py", tmp_path / "weather_etl" / "extract.py")
    shutil.copyfile(src / "__init__.py", tmp_path / "weather_etl" / "__init__.py")
    return tmp_path


def test_grade_attempt_writes_one_observation_per_gap_and_regrading_adds_none(
        world, solved_extract_repo):
    conn, _, attempt_id = world

    def run(sha):
        return tr.grade_attempt("weather_etl", ASG, solved_extract_repo, attempt_id,
                                commit_sha=sha, conn=conn)

    assert run(SHA[1]).tests_passed == 4
    assert [(p["gap_id"], p["conclusion"]) for p, _ in observations(world)] == \
        [(PARSE, "success"), (RETRY, "success")]
    run(SHA[1])                          # the same commit again
    run(SHA[2])                          # a later commit
    assert len(observations(world)) == 2
    profile = Memory().get_profile(S, conn=conn)["mastery"]
    assert profile[ED]["n"] == 1 and profile[DS]["n"] == 1


def test_grade_attempt_ignores_a_file_that_does_not_load(world, solved_extract_repo):
    conn, cur, attempt_id = world
    (solved_extract_repo / "weather_etl" / "extract.py").write_text(
        "def broken(:\n", encoding="utf-8")
    result = tr.grade_attempt("weather_etl", ASG, solved_extract_repo, attempt_id,
                              commit_sha=SHA[1], conn=conn)
    assert result.status == "collection_error"
    assert observations(world) == []
    cur.execute("SELECT count(*) FROM traces WHERE student_id=%s AND kind='test_result'", (S,))
    assert cur.fetchone()[0] == 0
