"""D-098 -- the template push of a delivered repo is not a student action (formula v8).

A delivered repo (attempt >= 2, ONE assignment, D-090) gives its "Initial commit: ..." push the
repo's assignment, so v4's rule (`assignment_id IS NULL`) never saw it. From v8 the commit is also
recognised when it is the earliest commit graded under its attempt. Everything runs in one
rolled-back transaction on the test database.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from agents import feedback_agent as fa
from features import compute_features as cf
from scripts import post_feedback as pf
from system import db
from tests.support import ensure_variant

pytestmark = pytest.mark.skipif(not os.environ.get("PG_DSN"),
                                reason="PG_DSN not set; integration test needs a database")

S = "_tpl_student"
ASG = "weather_etl_extract"
OTHER = "weather_etl_load"
T0 = datetime(2026, 10, 12, 4, 0, tzinfo=UTC)
TEMPLATE_MSG = "Initial commit: weather_etl gapfill for _tpl_student (attempt 2)"
_T = "tests/hidden/test_extract.py::"
GAP_TESTS = {"g_ext_retry": _T + "test_fetch_weather_retries_then_succeeds",
             "g_ext_parse": _T + "test_parse_response_missing_key_returns_none"}


@pytest.fixture
def world():
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, S))
    yield conn, cur
    conn.rollback()
    conn.close()


def attempt(cur, attempt_no: int, assignment: str = ASG) -> int:
    variant = ensure_variant(cur, assignment)
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl',%s,%s,%s,1) RETURNING attempt_id",
                (S, assignment, attempt_no, variant))
    return cur.fetchone()[0]


def commit(cur, sha: str, minutes: int, message: str | None, assignment: str | None = ASG,
           additions: int = 8, deletions: int = 1, files: int = 1) -> str:
    cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at, additions,"
                " deletions, files_changed, message) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (sha, S, assignment, T0 + timedelta(minutes=minutes), additions, deletions,
                 files, message))
    return sha


def graded(cur, attempt_id: int, sha: str, passed: dict[str, bool]) -> None:
    for gap, ok in passed.items():
        cur.execute("INSERT INTO test_results (attempt_id, commit_sha, test_name, gap_id, passed,"
                    " message, status) VALUES (%s,%s,%s,%s,%s,%s,'ok')",
                    (attempt_id, sha, GAP_TESTS[gap], gap, ok,
                     None if ok else "NotImplementedError"))


def flag(cur, sha: str, formula_ver: str) -> bool:
    cur.execute(f"SELECT {cf.initial_commit_sql('c', formula_ver)} FROM raw_commits c"
                " WHERE c.sha = %s", (sha,))
    return cur.fetchone()[0]


def delivered(cur):
    """attempt 2 of one assignment: the template push, then two student pushes."""
    a2 = attempt(cur, 2)
    template = commit(cur, "tpl_template", 0, TEMPLATE_MSG, additions=92, deletions=0, files=8)
    first = commit(cur, "tpl_first", 16, "extract: retry loop")
    second = commit(cur, "tpl_second", 40, "extract: parse")
    graded(cur, a2, template, {"g_ext_retry": False, "g_ext_parse": False})
    graded(cur, a2, first, {"g_ext_retry": True, "g_ext_parse": False})
    graded(cur, a2, second, {"g_ext_retry": True, "g_ext_parse": False})
    return a2, template, first, second


# --- recognition -----------------------------------------------------------------------------

def test_a_single_assignment_repo_template_push_is_recognised_from_v8_only(world):
    _, cur = world
    _, template, first, second = delivered(cur)
    assert flag(cur, template, "v8") is True
    assert [flag(cur, template, v) for v in ("v4", "v5", "v6", "v7")] == [False] * 4   # old rule
    assert flag(cur, first, "v8") is False and flag(cur, second, "v8") is False


def test_a_student_commit_named_initial_commit_that_is_not_the_first_is_kept(world):
    _, cur = world
    a2, template, _, _ = delivered(cur)
    later = commit(cur, "tpl_named", 90, "Initial commit: my own restart")
    graded(cur, a2, later, {"g_ext_retry": True})
    assert flag(cur, later, "v8") is False                # an earlier commit exists in the repo
    assert flag(cur, template, "v8") is True              # and the real template push still is


def test_a_student_commit_named_initial_commit_is_kept_when_it_is_the_first_of_no_repo(world):
    """Fail open: never graded, so its repo and its order are unknown."""
    _, cur = world
    delivered(cur)
    ungraded = commit(cur, "tpl_ungraded", -30, TEMPLATE_MSG)       # earlier than everything
    assert flag(cur, ungraded, "v8") is False
    assert flag(cur, commit(cur, "tpl_nomsg", 200, None), "v8") is False   # unknown message


def test_attempt_1_repos_are_unchanged(world):
    """The four-assignment repo's template push has no assignment (v4's rule, still true); an
    attempt-1 commit named "Initial commit:" that does touch a file is NOT taken for it."""
    _, cur = world
    a1 = attempt(cur, 1, OTHER)
    no_assignment = commit(cur, "tpl_a1_template", 0, TEMPLATE_MSG, assignment=None, files=12)
    named = commit(cur, "tpl_a1_named", 5, "Initial commit: first real push", assignment=OTHER)
    graded(cur, a1, named, {"g_ext_retry": False})
    for version in ("v7", "v8"):
        assert flag(cur, no_assignment, version) is True
        assert flag(cur, named, version) is False


def test_two_deliveries_each_have_their_own_template_push(world):
    _, cur = world
    delivered(cur)
    a3 = attempt(cur, 3)
    template3 = commit(cur, "tpl_template3", 300, TEMPLATE_MSG)
    real3 = commit(cur, "tpl_real3", 320, "extract: again")
    graded(cur, a3, template3, {"g_ext_retry": False})
    graded(cur, a3, real3, {"g_ext_retry": True})
    assert flag(cur, template3, "v8") is True and flag(cur, real3, "v8") is False


# --- the features -----------------------------------------------------------------------------

def run(cur, sha: str, minutes: int, conclusion: str) -> None:
    cur.execute("INSERT INTO raw_workflow_runs (run_id, student_id, assignment_id, status,"
                " conclusion, started_at, completed_at, head_sha)"
                " VALUES (%s,%s,%s,'completed',%s,%s,%s,%s)",
                (abs(hash(sha)) % 10**9, S, ASG, conclusion,
                 T0 + timedelta(minutes=minutes), T0 + timedelta(minutes=minutes + 1), sha))


def test_v8_leaves_the_template_push_out_of_commits_loc_runs_and_gaps(world):
    _, cur = world
    _, template, first, second = delivered(cur)
    run(cur, template, 1, "failure")
    run(cur, first, 17, "failure")
    run(cur, second, 41, "success")

    v7 = cf.compute_for_student(cur, S, "v7")
    v8 = cf.compute_for_student(cur, S, "v8")
    assert v7["error_frequency"]["excluded_commits"] == 0
    assert v8["error_frequency"]["excluded_commits"] == 1            # the template push
    assert v7["error_frequency"]["excluded_runs"]["sync_triggered"] == 0
    assert v8["error_frequency"]["excluded_runs"]["sync_triggered"] == 1   # its CI run
    # V3: three commits give two gaps (regularity defined); two real commits give one (undefined)
    assert v7["effort_regulation"]["regularity"] is not None
    assert v8["effort_regulation"]["regularity"] is None
    # the watermark follows the last STUDENT event, and the template push is not "activity"
    assert cf.watermark(cur, S, "v8") == T0 + timedelta(minutes=41)


def test_a_fresh_delivery_with_only_the_template_push_is_not_student_activity(world):
    """Right after a delivery nothing the student did exists yet: the pipeline must not treat the
    student as active, nor move the watermark, because of the template push and its CI run."""
    _, cur = world
    a2 = attempt(cur, 2)
    template = commit(cur, "tpl_only", 0, TEMPLATE_MSG, additions=92, deletions=0, files=8)
    graded(cur, a2, template, {"g_ext_retry": False, "g_ext_parse": False})
    run(cur, template, 1, "failure")
    since = (T0 - timedelta(hours=1)).isoformat()
    assert S in cf.dirty_students(cur, since, "v7") and cf.watermark(cur, S, "v7") is not None
    assert S not in cf.dirty_students(cur, since, "v8") and cf.watermark(cur, S, "v8") is None
    assert cf.compute_for_student(cur, S, "v8")["pace"] == {}   # no student run, so no pace row


def test_v8_drops_the_template_push_outcomes_from_v5_v6(world):
    _, cur = world
    delivered(cur)
    from memory.memory import Memory
    mem = Memory()
    for sha in ("tpl_template", "tpl_first"):
        mem.log_trace(S, "system", "test_result",
                      {"conclusion": "failure", "item_difficulty": 0.35, "attempt_id": None,
                       "commit_sha": sha, "gap_id": "g_ext_parse", "attempted": True},
                      assignment_id=ASG, concept_ids=["py.data_structures"], conn=cur.connection)
    mem.log_trace(S, "system", "test_result",              # an old trace that names no commit
                  {"conclusion": "failure", "item_difficulty": 0.35},
                  assignment_id=ASG, concept_ids=["py.data_structures"], conn=cur.connection)
    kept = cf._drop_template_commit_results(cur, mem.test_result_history(S, conn=cur.connection))
    assert sorted(str(r["commit_sha"]) for r in kept) == ["None", "tpl_first"]   # unknown is kept


def test_v6_and_v7_values_do_not_depend_on_the_new_rule(world):
    """Same data, once with the template push and once with its message changed so that NO
    version can recognise it: v6 and v7 must be identical, v8 must not be."""
    _, cur = world
    _, template, first, second = delivered(cur)
    run(cur, template, 1, "failure")
    run(cur, first, 17, "failure")
    run(cur, second, 41, "success")
    before = {v: cf.compute_for_student(cur, S, v) for v in ("v6", "v7", "v8")}
    cur.execute("UPDATE raw_commits SET message = 'student push' WHERE sha = %s", (template,))
    after = {v: cf.compute_for_student(cur, S, v) for v in ("v6", "v7", "v8")}
    assert before["v6"] == after["v6"] and before["v7"] == after["v7"]
    assert before["v8"] != after["v8"]


def test_a_stored_v7_row_is_not_rewritten_by_a_v8_run(world):
    _, cur = world
    delivered(cur)
    run(cur, "tpl_second", 41, "success")
    payload7 = cf.compute_for_student(cur, S, "v7")
    assert cf.write_features(cur, S, payload7, "v7") is True
    cur.execute("SELECT formula_ver, effort_regulation, error_frequency FROM learner_features"
                " WHERE student_id = %s", (S,))
    stored = cur.fetchall()
    payload8 = cf.compute_for_student(cur, S, "v8")
    assert payload8 != payload7
    wrote = cf.write_features(cur, S, payload8, "v8")
    cur.execute("SELECT formula_ver, effort_regulation, error_frequency FROM learner_features"
                " WHERE student_id = %s AND formula_ver = 'v7'", (S,))
    assert cur.fetchall() == stored                      # the v7 row is byte-for-byte what it was
    if cf.watermark(cur, S, "v7") == cf.watermark(cur, S, "v8"):
        assert wrote is False                            # same watermark: v8 never overwrites v7


# --- feedback ---------------------------------------------------------------------------------

def test_no_feedback_is_selected_built_or_gathered_for_the_template_push(world):
    _, cur = world
    a2, template, first, second = delivered(cur)
    listed = [sha for _, sha in pf.graded_commits(cur, S)]
    assert template not in listed and listed == [first, second]
    assert [sha for _, sha in pf.recent_unposted(cur, S, 24)] == [first, second]
    assert [sha for _, sha in pf.unposted_commits(cur, S, commit=template[:8])] == []
    with pytest.raises(pf.TemplateCommit):
        pf.build_feedback(cur, a2, template)
    with pytest.raises(pf.TemplateCommit):
        fa.gather_input(cur, a2, template, profile={}, candidates=[])
    assert pf.build_feedback(cur, a2, first).markdown        # a student push still gets its text


def test_the_first_real_comment_does_not_count_the_template_push_as_a_failed_push(world):
    """g_ext_parse failed on the template push AND on the first real push. Counting the template
    would say 'keeps failing across several pushes' on the very first comment."""
    _, cur = world
    a2, _template, first, second = delivered(cur)
    assert "Keeps failing" not in pf.build_feedback(cur, a2, first).markdown
    assert "Keeps failing across several pushes: `g_ext_parse`" in pf.build_feedback(
        cur, a2, second).markdown                            # two REAL pushes: now it does
    from assessment.diagnose import diagnose
    # g_ext_retry failed ONLY on the template push, so it is not in the history at all any more
    assert diagnose(cur, a2, as_of_commit_sha=first).recurrence_flags == {"g_ext_parse": False}
