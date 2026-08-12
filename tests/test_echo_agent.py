"""agents/echo_agent.py — BUILD_PLAN 2.4, the tracer bullet.

Two kinds of test here, and the first kind matters more than the second.

**Seam tests** pin the interface M4 must preserve (DEVELOPMENT_MAP.md D.3: "Design Echo's
interface as though the Code Agent already existed"). If Echo's signature drifts, M4 stops
being an internals swap and becomes a refactor -- and it would drift silently, because
nothing else in the repo calls this function yet. These tests are the only thing standing
between "M4 is a one-file change" and "M4 is a week of rewiring", so they assert the
contract literally, including reproducing `system/orchestrator.py`'s exact call shape.

**Behaviour tests** cover the rubric mapping (D-016) and Option A -- that mastery moves
because of the `ci_run` Echo points at, never because of Echo's own opinion.

Database conventions match tests/test_memory.py: every test drives a rolled-back connection,
because `traces` is append-only and a committed test trace could never be cleaned up.
"""
import inspect
import os

import pytest

from agents import echo_agent
from agents.echo_agent import (
    CORRECTNESS_SCORE,
    CRITERIA,
    ECHO_OUTCOME,
    UNEVIDENCED_SCORE,
    EchoVerdict,
    grade,
)
from memory.memory import Memory
from system import db

STUDENT = "_test_echo"
ASSIGNMENT = "_test_echo_a1"
CONCEPT = "spark.joins"

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; echo agent tests need a database"
)


@pytest.fixture
def conn():
    """A connection that is always rolled back. Seeds the FK parents traces needs."""
    try:
        c = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    try:
        with c.cursor() as cur:
            cur.execute(
                "INSERT INTO students (student_id, github_username, cohort)"
                " VALUES (%s, %s, 'vdel-2026')",
                (STUDENT, STUDENT),
            )
            cur.execute(
                "INSERT INTO assignments (assignment_id, repo_prefix, released_at, concepts)"
                " VALUES (%s, 'org/echo', '2026-03-02 09:00+00', ARRAY[%s])",
                (ASSIGNMENT, CONCEPT),
            )
        yield c
    finally:
        c.rollback()
        c.close()


@pytest.fixture
def mem():
    return Memory()


@pytest.fixture
def assignment():
    """The minimum `assignment` dict Echo reads. M4 adds `task`, `rubric`, `difficulty`."""
    return {"assignment_id": ASSIGNMENT, "concepts": [CONCEPT]}


def ci_run(mem, conn, conclusion, *, concept=CONCEPT, difficulty=0.5):
    """A `ci_run` trace, the only kind that feeds mastery (memory.MASTERY_TRACE_KINDS)."""
    return mem.log_trace(
        STUDENT, "system", "ci_run",
        {"conclusion": conclusion, "item_difficulty": difficulty, "error_class": None},
        concept_ids=[concept], assignment_id=ASSIGNMENT, conn=conn,
    )


def profile_mastery(mem, conn):
    return mem.get_profile(STUDENT, conn=conn)["mastery"]


# ---------- SEAM: the interface M4 must preserve ----------

def test_grade_takes_D5s_four_positional_parameters_in_order():
    """`VDEL_Modules_3_9_Build.md` D.5 line 906:
        def grade(mem, student_id, assignment, code_path, profile_snapshot=None, reference=None)

    The order is load-bearing: the orchestrator passes the first four positionally.
    """
    params = list(inspect.signature(grade).parameters.values())
    positional = [p.name for p in params
                  if p.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD]
    assert positional == ["mem", "student_id", "assignment", "code_path"]


def test_grade_accepts_D5s_optional_keywords():
    """`profile_snapshot` and `reference` are keyword-only here, which is compatible:
    the orchestrator passes both by keyword. Their presence is the contract, not their kind.
    """
    params = inspect.signature(grade).parameters
    for name in ("profile_snapshot", "reference"):
        assert name in params, f"D.5 contract parameter {name!r} is missing"
        assert params[name].default is None


def test_the_orchestrators_exact_call_shape_works(mem, conn, assignment):
    """Reproduces `system/orchestrator.py` line 1818 literally, minus asyncio.to_thread:

        grade_code(mem, student_id, assignment, code_path,
                   profile_snapshot=snapshot, reference=reference)

    If this call ever stops working, M4 inherits a broken orchestrator.
    """
    snapshot = mem.snapshot_profile(STUDENT, conn=conn)
    verdict, trace_id, failures = grade(
        mem, STUDENT, assignment, "/nonexistent/submission.py",
        profile_snapshot=snapshot, reference=None,
        ci_conclusion="success", conn=conn,
    )
    assert isinstance(verdict, EchoVerdict)
    assert isinstance(trace_id, int)
    assert failures is None


def test_grade_returns_the_three_element_tuple(mem, conn, assignment):
    """D.5 returns `(verdict, tid, ev_failures or None)`; the orchestrator unpacks exactly
    three (`code_verdict, code_tid, _ = code_result`)."""
    result = grade(mem, STUDENT, assignment, "x.py", ci_conclusion="success", conn=conn)
    assert len(result) == 3


def test_the_verdict_exposes_every_attribute_the_reviewer_reads(mem, conn, assignment):
    """`agents/reviewer.py`'s `detect_disagreement` reads these off the verdict OBJECT.
    A missing attribute there fails at M6 integration, long after this file is written."""
    verdict, _, _ = grade(mem, STUDENT, assignment, "x.py",
                          ci_conclusion="failure", conn=conn)
    assert isinstance(verdict.scores.correctness, int)
    assert isinstance(verdict.scores.idiomatic, int)
    assert verdict.confidence in ("high", "medium", "low")
    assert verdict.feedback_for_student
    assert verdict.misconceptions == []


def test_evidence_failures_is_a_real_field_not_just_a_return_value(mem, conn, assignment):
    """The Reviewer does `getattr(code_v, "evidence_failures", None)`. D.5's `Verdict`
    declares no such field, so that flag could never fire. Declaring it makes M6's
    `evidence:code_agent_unmatched` live rather than dead code."""
    verdict, _, _ = grade(mem, STUDENT, assignment, "x.py",
                          ci_conclusion="success", conn=conn)
    assert getattr(verdict, "evidence_failures", None) == []
    assert "evidence_failures" in EchoVerdict.model_fields


def test_code_path_and_reference_are_accepted_and_never_read(mem, conn, assignment):
    """They are M4's inputs. Echo must accept them so the swap changes no call site --
    a path that does not exist proves nothing opens it."""
    verdict, _, _ = grade(
        mem, STUDENT, assignment, "/definitely/not/a/real/path.py",
        reference="SELECT 1;", ci_conclusion="success", conn=conn,
    )
    assert verdict.scores.correctness == CORRECTNESS_SCORE[True]


def test_grade_is_a_module_level_function_not_a_method():
    """The orchestrator does `from agents.code_agent import grade as grade_code` and hands
    it to `asyncio.to_thread`. A bound method or a class would break that import shape."""
    assert inspect.isfunction(echo_agent.grade)


# ---------- D-016: the rubric mapping ----------

def test_ci_failure_scores_correctness_zero(mem, conn, assignment):
    verdict, _, _ = grade(mem, STUDENT, assignment, "x.py",
                          ci_conclusion="failure", conn=conn)
    assert verdict.scores.correctness == 0


def test_ci_success_scores_correctness_four(mem, conn, assignment):
    verdict, _, _ = grade(mem, STUDENT, assignment, "x.py",
                          ci_conclusion="success", conn=conn)
    assert verdict.scores.correctness == 4


def test_a_ci_pass_maps_above_D5s_correct_threshold():
    """D.5 line 939 derives the BKT outcome as `correctness >= 3`. Echo's pass score must
    sit above that line and its fail score below it, so that when M4 turns verdicts into
    mastery evidence, Echo's binary intent survives the swap unchanged. This is the whole
    reason correctness maps to 4/0 rather than to 2/0."""
    assert CORRECTNESS_SCORE[True] >= 3
    assert CORRECTNESS_SCORE[False] < 3


@pytest.mark.parametrize("conclusion", ["success", "failure"])
def test_criteria_ci_cannot_evidence_get_the_neutral_anchor(mem, conn, assignment,
                                                            conclusion):
    """D-016. A green CI run evidences correctness and nothing else; scoring readability
    from it would be fabricated judgement (invariant 6). The neutral anchor + low
    confidence is `orchestrator._missing_perf_verdict()`'s own convention for an agent
    with no information."""
    verdict, _, _ = grade(mem, STUDENT, assignment, "x.py",
                          ci_conclusion=conclusion, conn=conn)
    assert verdict.scores.approach == UNEVIDENCED_SCORE
    assert verdict.scores.readability == UNEVIDENCED_SCORE
    assert verdict.scores.idiomatic == UNEVIDENCED_SCORE


def test_confidence_is_always_low(mem, conn, assignment):
    """Echo is not a trustworthy judge and the aggregate should say so. The Reviewer will
    flag every Echo verdict `low_confidence:code`, which is correct behaviour."""
    for conclusion in ("success", "failure", "cancelled"):
        verdict, _, _ = grade(mem, STUDENT, assignment, "x.py",
                              ci_conclusion=conclusion, conn=conn)
        assert verdict.confidence == "low"


def test_echo_quotes_nothing_but_leaves_the_slot_for_M4(mem, conn, assignment):
    """Echo reads no code, so it has no verbatim quotes. The keys exist so M4 fills a slot
    rather than adding one, and so `validate_evidence` has the shape it expects."""
    verdict, _, _ = grade(mem, STUDENT, assignment, "x.py",
                          ci_conclusion="success", conn=conn)
    assert set(verdict.evidence) == set(CRITERIA)
    assert all(quotes == [] for quotes in verdict.evidence.values())


# ---------- Non-assessing conclusions ----------

@pytest.mark.parametrize("conclusion", ["cancelled", "skipped", "timed_out", "neutral"])
def test_a_non_assessing_conclusion_scores_nothing(mem, conn, assignment, conclusion):
    """GitHub's `conclusion` vocabulary is wider than pass/fail, and only two of its values
    say anything about what a student knows (memory.OUTCOME). A cancelled run is evidence
    about CI infrastructure, so correctness drops to the neutral anchor too -- scoring it 0
    would blame the student for a cancelled job."""
    verdict, _, _ = grade(mem, STUDENT, assignment, "x.py",
                          ci_conclusion=conclusion, conn=conn)
    assert verdict.scores.correctness == UNEVIDENCED_SCORE
    assert verdict.confidence == "low"


def test_a_missing_conclusion_raises_rather_than_grading_nothing(mem, conn, assignment):
    """Distinct from the case above: `None` is a caller who forgot to pass the one fact
    Echo grades on. Emitting a verdict about nothing would be a silent fabrication."""
    with pytest.raises(ValueError, match="requires ci_conclusion"):
        grade(mem, STUDENT, assignment, "x.py", conn=conn)


# ---------- Option A: what actually moves mastery ----------

def test_mastery_moves_from_the_ci_run_not_from_the_verdict(mem, conn, assignment):
    """Option A, stated as a test. `memory.MASTERY_TRACE_KINDS` is `{"ci_run"}` and
    `NON_MASTERY_KINDS["verdict"]` says the rubric->BKT mapping has not been decided. So
    the loop closes because Echo points at a `ci_run` and calls `update_mastery`, which
    replays it -- 0.8126 is the hand-computed one-pass BKT update from test_memory.py."""
    ci_trace = ci_run(mem, conn, "success")
    grade(mem, STUDENT, assignment, "x.py", ci_conclusion="success",
          parent_trace_id=ci_trace, conn=conn)

    mastery = profile_mastery(mem, conn)
    assert mastery[CONCEPT]["p_mastery"] == 0.8126
    assert mastery[CONCEPT]["n"] == 1


def test_a_verdict_with_no_ci_run_behind_it_moves_no_mastery(mem, conn, assignment):
    """The other half of Option A, and the one that would fail if `verdict` were quietly
    added to MASTERY_TRACE_KINDS: Echo's opinion alone is not evidence about a student."""
    grade(mem, STUDENT, assignment, "x.py", ci_conclusion="failure", conn=conn)
    assert profile_mastery(mem, conn) == {}


def test_echo_does_not_invent_an_outcome_when_ci_disagrees_with_it(mem, conn, assignment):
    """Belt and braces on Option A. Echo is told "failure" but the log holds a passing
    `ci_run`; mastery must follow the LOG, not the argument. If this ever fails, someone
    has wired the outcome into the mastery update -- the exact D-007 mistake."""
    ci_trace = ci_run(mem, conn, "success")
    grade(mem, STUDENT, assignment, "x.py", ci_conclusion="failure",
          parent_trace_id=ci_trace, conn=conn)

    assert profile_mastery(mem, conn)[CONCEPT]["p_mastery"] == 0.8126


def test_grading_twice_does_not_count_as_two_attempts(mem, conn, assignment):
    """`update_mastery` is idempotent because it replays the log rather than folding an
    outcome onto stored state. That property is what makes it safe for Echo to call it even
    though BUILD_PLAN 2.2's fast path may already have."""
    ci_trace = ci_run(mem, conn, "success")
    for _ in range(3):
        grade(mem, STUDENT, assignment, "x.py", ci_conclusion="success",
              parent_trace_id=ci_trace, conn=conn)

    assert profile_mastery(mem, conn)[CONCEPT]["n"] == 1


# ---------- The trace Echo writes ----------

def test_the_verdict_trace_is_a_child_of_the_ci_run_it_judges(mem, conn, assignment):
    """The causal forest. Without parentage, a reader can see that mastery moved but not
    which event moved it -- which is the audit story this project is built to defend."""
    ci_trace = ci_run(mem, conn, "failure")
    _, trace_id, _ = grade(mem, STUDENT, assignment, "x.py", ci_conclusion="failure",
                           parent_trace_id=ci_trace, conn=conn)

    with conn.cursor() as cur:
        cur.execute("SELECT parent_trace_id FROM traces WHERE trace_id = %s", (trace_id,))
        assert cur.fetchone()[0] == ci_trace


def test_the_trace_is_logged_as_a_verdict_by_the_code_agent_actor(mem, conn, assignment):
    """`actor="code_agent"`, not a new `echo_agent` actor: M4 replaces this file's internals
    and must not orphan the traces Echo already wrote. `memory.ACTORS` would reject an
    unregistered actor anyway, which is the vocabulary guard working."""
    _, trace_id, _ = grade(mem, STUDENT, assignment, "x.py",
                           ci_conclusion="success", conn=conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT actor, kind, assignment_id, concept_ids FROM traces WHERE trace_id = %s",
            (trace_id,),
        )
        assert cur.fetchone() == ("code_agent", "verdict", ASSIGNMENT, [CONCEPT])


def test_the_payload_preserves_BUILD_PLANs_own_numbers(mem, conn, assignment):
    """D-016: BUILD_PLAN 2.4 says "CI failed -> outcome 0, passed -> 0.75". Those are on a
    [0,1] scale, not the anchored 0/2/4 rubric, so they are recorded as provenance rather
    than silently reinterpreted as rubric scores."""
    _, pass_trace, _ = grade(mem, STUDENT, assignment, "x.py",
                             ci_conclusion="success", conn=conn)
    _, fail_trace, _ = grade(mem, STUDENT, assignment, "x.py",
                             ci_conclusion="failure", conn=conn)

    with conn.cursor() as cur:
        cur.execute("SELECT payload FROM traces WHERE trace_id = ANY(%s) ORDER BY trace_id",
                    ([pass_trace, fail_trace],))
        passed_payload, failed_payload = (row[0] for row in cur.fetchall())

    assert passed_payload["echo_outcome"] == ECHO_OUTCOME[True] == 0.75
    assert failed_payload["echo_outcome"] == ECHO_OUTCOME[False] == 0.0


def test_the_payload_cites_the_event_instead_of_quoting_code(mem, conn, assignment):
    """Echo's form of invariant 6. It quotes nothing because it reads nothing; its citation
    is a foreign key to the `ci_run`, which cannot be fabricated because there is no
    generative step to fabricate it."""
    ci_trace = ci_run(mem, conn, "failure")
    _, trace_id, _ = grade(mem, STUDENT, assignment, "x.py", ci_conclusion="failure",
                           parent_trace_id=ci_trace, conn=conn)

    with conn.cursor() as cur:
        cur.execute("SELECT payload FROM traces WHERE trace_id = %s", (trace_id,))
        payload = cur.fetchone()[0]

    assert payload["evidence_source"] == {"kind": "ci_run", "conclusion": "failure",
                                          "trace_id": ci_trace}


def test_the_verdict_payload_records_no_memory_slice(mem, conn, assignment):
    """Deliberately absent. An earlier draft wrote the `{mastery, open_weaknesses}` slice
    into this payload to exercise the `profile_snapshot` seam; it was cut because
    Modules_3_9 H.2 names the *grade* trace (M6's Reviewer) as where a judgement-time
    snapshot belongs, and a second home for "what did the system believe when it graded
    this?" is the duplication D-007 and D-012 argue against everywhere else.

    Pinned as a test rather than left as an absence, so that if M4 adds a slice it is a
    decision someone makes and records, not a line someone reintroduces by habit."""
    ci_run(mem, conn, "success")
    mem.update_mastery(STUDENT, CONCEPT, conn=conn)

    _, trace_id, _ = grade(mem, STUDENT, assignment, "x.py",
                           ci_conclusion="success", conn=conn)
    with conn.cursor() as cur:
        cur.execute("SELECT payload FROM traces WHERE trace_id = %s", (trace_id,))
        payload = cur.fetchone()[0]

    assert "memory_slice" not in payload


def test_a_supplied_snapshot_is_accepted_and_changes_nothing(mem, conn, assignment):
    """`profile_snapshot` is part of D.5's contract, so Echo must accept it -- but Echo
    reads no memory, so supplying one must not alter the verdict OR appear in the trace
    payload. A snapshot that changed either would mean Echo had grown a memory dependency
    the tracer bullet does not have and M4 would then have to reproduce."""
    frozen = {"mastery": {CONCEPT: {"p_mastery": 0.123}}, "weaknesses": []}
    with_snapshot, with_tid, _ = grade(
        mem, STUDENT, assignment, "x.py",
        ci_conclusion="success", profile_snapshot=frozen, conn=conn,
    )
    without, _, _ = grade(mem, STUDENT, assignment, "x.py",
                          ci_conclusion="success", conn=conn)

    assert with_snapshot.model_dump() == without.model_dump()

    with conn.cursor() as cur:
        cur.execute("SELECT payload FROM traces WHERE trace_id = %s", (with_tid,))
        payload = cur.fetchone()[0]
    assert "memory_slice" not in payload
    assert "mastery" not in payload  # the frozen snapshot's own key, absent by construction


def test_a_rejected_grade_writes_no_trace(mem, conn, assignment):
    """Validation happens before the INSERT, mirroring log_trace's own guarantee."""
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM traces WHERE student_id = %s", (STUDENT,))
        before = cur.fetchone()[0]

    with pytest.raises(ValueError):
        grade(mem, STUDENT, assignment, "x.py", conn=conn)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM traces WHERE student_id = %s", (STUDENT,))
        assert cur.fetchone()[0] == before


def test_an_assignment_with_no_concepts_still_grades(mem, conn):
    """Degenerate but legal: `assignments.concepts[]` could be empty. The verdict is still
    a verdict; there is simply no mastery to move."""
    verdict, trace_id, _ = grade(
        mem, STUDENT, {"assignment_id": ASSIGNMENT, "concepts": []}, "x.py",
        ci_conclusion="success", conn=conn,
    )
    assert verdict.scores.correctness == 4
    with conn.cursor() as cur:
        cur.execute("SELECT concept_ids FROM traces WHERE trace_id = %s", (trace_id,))
        assert cur.fetchone()[0] == []
