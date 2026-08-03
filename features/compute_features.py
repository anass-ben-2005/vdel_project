"""Raw tables -> the seven variables -> learner_features.

Idempotency (M1 DoD: "a deliberate re-run changes nothing") is structural here rather
than hoped for. `computed_at` is not now() -- it is the student's data watermark, the
timestamp of their most recent raw event. Re-running with no new activity produces the
same watermark, so the upsert targets the same primary key and rewrites the same values.
The previous version stamped now() and INSERTed, so every re-run added a row and the DoD
could not pass by construction.

Run:  python -m features.compute_features
"""

from __future__ import annotations

import os
from datetime import datetime

from psycopg2.extras import Json

from system import db
from variables import error_frequency as v6
from variables import error_response as v5
from variables import habits as v23
from variables import mastery as v1
from variables import pace as v4

WINDOW_DAYS = int(os.environ.get("FEATURE_WINDOW_DAYS", "14"))


def watermark(cur, student_id: str) -> datetime | None:
    """The student's most recent raw event, across both raw tables."""
    cur.execute(
        """
        SELECT max(ts) FROM (
            SELECT max(committed_at) AS ts FROM raw_commits        WHERE student_id = %s
            UNION ALL
            SELECT max(completed_at) AS ts FROM raw_workflow_runs  WHERE student_id = %s
        ) AS events
        """,
        (student_id, student_id),
    )
    return cur.fetchone()[0]


def dirty_students(cur) -> list[str]:
    """Students whose watermark is newer than their newest feature row.

    Compares against max(computed_at), not against every historical row. The previous
    version's LEFT JOIN fanned out over all feature rows, so once a student had two rows
    the OR-condition matched one of them and they were dirty forever.
    """
    cur.execute(
        """
        WITH events AS (
            SELECT student_id, max(committed_at) AS ts FROM raw_commits       GROUP BY 1
            UNION ALL
            SELECT student_id, max(completed_at) AS ts FROM raw_workflow_runs GROUP BY 1
        ),
        latest AS (
            SELECT student_id, max(ts) AS ts FROM events GROUP BY 1
        ),
        computed AS (
            SELECT student_id, max(computed_at) AS ts FROM learner_features GROUP BY 1
        )
        SELECT l.student_id
        FROM latest l
        LEFT JOIN computed c USING (student_id)
        WHERE l.ts IS NOT NULL AND (c.ts IS NULL OR l.ts > c.ts)
        ORDER BY 1
        """
    )
    return [row[0] for row in cur.fetchall()]


def compute_mastery(cur, student_id: str) -> dict:
    """V1 per concept, replaying every classified attempt in order.

    Invariant 10: runs with no concept_id update no mastery. The WHERE clause is where
    that invariant lives, so an unclassified error cannot silently move a score.
    """
    cur.execute(
        """
        SELECT r.concept_id,
               r.conclusion = 'success' AS passed,
               coalesce(i.difficulty, 0.5) AS difficulty
        FROM raw_workflow_runs r
        LEFT JOIN items i ON i.concept_id = r.concept_id
        WHERE r.student_id = %s AND r.concept_id IS NOT NULL
        ORDER BY r.completed_at
        """,
        (student_id,),
    )

    sequences: dict[str, list[bool]] = {}
    difficulties: dict[str, float] = {}
    for concept_id, passed, difficulty in cur.fetchall():
        sequences.setdefault(concept_id, []).append(bool(passed))
        difficulties[concept_id] = float(difficulty)

    return {
        concept_id: v1.replay(outcomes, difficulty=difficulties[concept_id]).to_dict()
        for concept_id, outcomes in sequences.items()
    }


def compute_for_student(cur, student_id: str) -> dict:
    """All seven variables for one student."""
    # V2/V3 inputs.
    cur.execute(
        "SELECT committed_at FROM raw_commits"
        " WHERE student_id = %s AND committed_at > now() - make_interval(days => %s)"
        " ORDER BY committed_at",
        (student_id, WINDOW_DAYS),
    )
    commit_times = [row[0] for row in cur.fetchall()]

    cur.execute(
        "SELECT conclusion FROM raw_workflow_runs"
        " WHERE student_id = %s AND completed_at IS NOT NULL"
        " ORDER BY completed_at DESC LIMIT 1",
        (student_id,),
    )
    latest = cur.fetchone()
    tests_green = (latest[0] == "success") if latest else None

    # V5/V6 inputs.
    cur.execute(
        "SELECT completed_at, conclusion = 'success', concept_id FROM raw_workflow_runs"
        " WHERE student_id = %s AND completed_at IS NOT NULL",
        (student_id,),
    )
    runs = [(ts, bool(ok), cid) for ts, ok, cid in cur.fetchall()]
    attempts = len(runs)
    failures = sum(1 for _, ok, _ in runs if not ok)

    # V4, per assignment.
    cur.execute(
        """
        SELECT a.assignment_id, a.released_at, a.due_at,
               min(c.committed_at) AS first_commit,
               min(r.completed_at) FILTER (WHERE r.conclusion = 'success') AS first_pass,
               count(r.run_id) AS attempts
        FROM assignments a
        LEFT JOIN raw_commits c
               ON c.assignment_id = a.assignment_id AND c.student_id = %s
        LEFT JOIN raw_workflow_runs r
               ON r.assignment_id = a.assignment_id AND r.student_id = %s
        GROUP BY a.assignment_id, a.released_at, a.due_at
        HAVING count(r.run_id) > 0 OR min(c.committed_at) IS NOT NULL
        """,
        (student_id, student_id),
    )
    pace = {
        row[0]: v4.learning_pace(
            released_at=row[1], due_at=row[2], first_commit_at=row[3],
            first_pass_at=row[4], attempts=row[5],
        )
        for row in cur.fetchall()
    }

    return {
        "mastery": compute_mastery(cur, student_id),
        "engineering_discipline": v23.engineering_discipline(
            # TODO(verify): M1 never checks out the student's code, so ruff/sqlfluff
            # cannot run yet and lint density is genuinely unmeasured. None, not a
            # fabricated count. Wire this up when the Code Agent's tools land in M4.
            lint_findings=None,
            lines_of_code=None,
            tests_present=None,
            # Proxy: a green CI run implies tests ran and passed. Weaker than inspecting
            # the test job directly; flagged so it is not mistaken for a direct reading.
            tests_green=tests_green,
        ),
        "effort_regulation": v23.effort_regulation(commit_times),
        "pace": pace,
        "error_response": v5.error_response(runs),
        "error_frequency": v6.error_frequency(attempts, failures),
        "help_seeking": None,  # V7 seam: needs the coach, which does not exist yet.
    }


def run() -> int:
    """Compute features for every dirty student. Returns the number written."""
    with db.cursor() as cur:
        students = dirty_students(cur)
        print(f"{len(students)} student(s) with new activity")

        for student_id in students:
            stamp = watermark(cur, student_id)
            features = compute_for_student(cur, student_id)
            cur.execute(
                """
                INSERT INTO learner_features
                    (student_id, computed_at, window_days, mastery, engineering_discipline,
                     effort_regulation, pace, error_response, error_frequency, help_seeking)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (student_id, computed_at) DO UPDATE SET
                    window_days            = EXCLUDED.window_days,
                    mastery                = EXCLUDED.mastery,
                    engineering_discipline = EXCLUDED.engineering_discipline,
                    effort_regulation      = EXCLUDED.effort_regulation,
                    pace                   = EXCLUDED.pace,
                    error_response         = EXCLUDED.error_response,
                    error_frequency        = EXCLUDED.error_frequency,
                    help_seeking           = EXCLUDED.help_seeking
                """,
                (
                    student_id, stamp, WINDOW_DAYS,
                    # Json(), not str(). str(dict) writes a Python repr with single
                    # quotes, which is not JSON and which JSONB rejects or mangles.
                    Json(features["mastery"]),
                    Json(features["engineering_discipline"]),
                    Json(features["effort_regulation"]),
                    Json(features["pace"]),
                    Json(features["error_response"]),
                    Json(features["error_frequency"]),
                    Json(features["help_seeking"]) if features["help_seeking"] else None,
                ),
            )
            print(f"  {student_id} @ {stamp:%Y-%m-%d %H:%M} "
                  f"({len(features['mastery'])} concepts)")

        return len(students)


if __name__ == "__main__":
    run()
