"""End-to-end M1: raw tables -> the seven variables -> learner_features.

The unit tests check each formula in isolation; this checks the wiring between them,
which is where the previous implementation actually failed (the classifier was never
called, so concept_id was always NULL, so mastery was always empty -- every individual
formula was fine).

Uses Sara's A2 events from vdel_complete_design_document.md. Skips when no database is
reachable, so `pytest` still runs on a laptop with nothing started.
"""
import os

import pytest

from features.compute_features import run
from system import db

STUDENT = "_test_sara"
ASSIGNMENT = "_test_A2"

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)


@pytest.fixture
def sara():
    """Sara's A2 timeline. Rolled back afterwards so the test leaves no rows behind."""
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")

    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (STUDENT, STUDENT))
    cur.execute("INSERT INTO assignments VALUES (%s,'org/a2','2026-03-02 09:00+00',"
                "'2026-03-09 23:59+00', ARRAY['spark.joins','spark.aggregation'])",
                (ASSIGNMENT,))
    cur.executemany(
        f"INSERT INTO raw_commits VALUES (%s,'{STUDENT}','{ASSIGNMENT}',%s,%s,%s,%s,%s)",
        [("_c1", "2026-03-02 10:00+00", 120, 0, 3, "initial etl"),
         ("_c2", "2026-03-02 14:00+00", 45, 10, 2, "fix join keys"),
         ("_c3", "2026-03-02 18:00+00", 30, 5, 1, "fix agg grain")])
    cur.executemany(
        f"INSERT INTO raw_workflow_runs VALUES (%s,'{STUDENT}','{ASSIGNMENT}','completed',"
        "%s,%s,%s,180,%s,%s)",
        [(9001, "failure", "2026-03-02 10:05+00", "2026-03-02 10:08+00",
          "ambiguous column", "spark.joins"),
         (9002, "success", "2026-03-02 14:02+00", "2026-03-02 14:05+00", None, "spark.joins"),
         (9003, "failure", "2026-03-02 14:06+00", "2026-03-02 14:09+00",
          "AnalysisException.*group by", "spark.aggregation"),
         (9004, "failure", "2026-03-02 16:00+00", "2026-03-02 16:03+00",
          "AnalysisException.*group by", "spark.aggregation"),
         (9005, "success", "2026-03-02 18:30+00", "2026-03-02 18:33+00",
          None, "spark.aggregation")])
    conn.commit()
    cur.close()
    conn.close()

    yield

    with db.cursor() as c:
        c.execute("DELETE FROM learner_features WHERE student_id=%s", (STUDENT,))
        c.execute("DELETE FROM raw_workflow_runs WHERE student_id=%s", (STUDENT,))
        c.execute("DELETE FROM raw_commits WHERE student_id=%s", (STUDENT,))
        c.execute("DELETE FROM assignments WHERE assignment_id=%s", (ASSIGNMENT,))
        c.execute("DELETE FROM students WHERE student_id=%s", (STUDENT,))


def features_for(student_id):
    with db.cursor() as cur:
        cur.execute("""SELECT mastery, engineering_discipline, effort_regulation, pace,
                              error_response, error_frequency
                       FROM learner_features WHERE student_id=%s""", (student_id,))
        return cur.fetchone()


def test_all_seven_variables_are_written(sara):
    run()
    row = features_for(STUDENT)
    assert row is not None, "no learner_features row was written"
    mastery, discipline, effort, pace, v5, v6 = row

    # V1: both concepts present, each carrying its observation count (invariant 8).
    assert set(mastery) == {"spark.joins", "spark.aggregation"}
    assert mastery["spark.joins"]["n"] == 2
    assert mastery["spark.aggregation"]["n"] == 3

    # V2: the composite is withheld -- Cronbach's alpha cannot be computed for n=1.
    assert discipline["composite"] is None and discipline["composite_valid"] is False
    assert discipline["testing"] == 1.0          # CI is wired

    # V3: three commits give two gaps, enough for burstiness.
    assert effort["regularity"] is not None

    # V4: passed, and the cohort is a single student -- flagged, not hidden.
    assert pace[ASSIGNMENT]["censored"] is False
    assert pace[ASSIGNMENT]["cohort_n"] == 1

    # V5/V6 measure different things: response is a behaviour, frequency is a rate.
    assert v5["resolution_ratio"] == 1.0         # every failure was followed by a pass
    assert v6["by_concept"] == {"spark.joins": 1, "spark.aggregation": 2}
    assert v6["fail_ratio"] == pytest.approx(0.6)


def test_rerunning_changes_nothing(sara):
    """The M1 DoD: 'a deliberate re-run changes nothing'."""
    run()
    first = features_for(STUDENT)
    run()
    second = features_for(STUDENT)

    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM learner_features WHERE student_id=%s", (STUDENT,))
        assert cur.fetchone()[0] == 1, "a re-run added a second row"
    assert first == second


def test_unclassified_errors_move_no_mastery(sara):
    """Invariant 10, end to end rather than by inspection."""
    with db.cursor() as cur:
        cur.execute(f"""INSERT INTO raw_workflow_runs VALUES
            (9099,'{STUDENT}','{ASSIGNMENT}','completed','failure',
             '2026-03-03 09:00+00','2026-03-03 09:03+00',180,'unmatched','unclassified')""")
    run()
    mastery = features_for(STUDENT)[0]
    assert "unclassified" not in mastery
    assert set(mastery) == {"spark.joins", "spark.aggregation"}
