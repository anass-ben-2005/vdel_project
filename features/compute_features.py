"""Compute the seven variables from raw events."""

import os
import sys
from datetime import datetime, timedelta
from typing import Dict, Optional, List

import psycopg2
from dotenv import load_dotenv

from variables.mastery import update as bkt_update, MasteryState, BKTParams
from variables.habits import compute_discipline, compute_effort, discipline_score, effort_score
from variables.pace import compute_pace, pace_score
from variables.error_response import compute_error_response, error_response_score
from variables.error_frequency import compute_error_frequency, error_frequency_score

load_dotenv()


class FeatureComputer:
    """Compute the seven variables for each student."""

    def __init__(self):
        self.dsn = os.getenv('PG_DSN')
        if not self.dsn:
            raise ValueError("PG_DSN not set")
        self.window_days = int(os.getenv('FEATURE_WINDOW_DAYS', '14'))

    def get_connection(self):
        """Create a database connection."""
        return psycopg2.connect(self.dsn)

    def get_dirty_students(self) -> List[str]:
        """
        Get students with new activity since last feature computation.

        Dirty-student filter: only recompute students with new activity.
        Optimization: unchanged inputs produce unchanged features.
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        # Students with commits newer than last feature computation
        cursor.execute("""
            SELECT DISTINCT rc.student_id
            FROM raw_commits rc
            LEFT JOIN learner_features lf ON rc.student_id = lf.student_id
            WHERE lf.computed_at IS NULL OR rc.committed_at > lf.computed_at
            UNION
            SELECT DISTINCT rw.student_id
            FROM raw_workflow_runs rw
            LEFT JOIN learner_features lf ON rw.student_id = lf.student_id
            WHERE lf.computed_at IS NULL OR rw.completed_at > lf.computed_at
        """)

        dirty_students = [row[0] for row in cursor.fetchall()]
        cursor.close()
        conn.close()

        return dirty_students

    def compute_for_student(self, student_id: str) -> Dict:
        """Compute all seven variables for a student."""
        conn = self.get_connection()
        cursor = conn.cursor()

        # Get assignments for this student
        cursor.execute("""
            SELECT assignment_id FROM assignments
        """)
        assignments = [row[0] for row in cursor.fetchall()]

        # Compute each variable
        mastery = self._compute_mastery(cursor, student_id, assignments)
        discipline = self._compute_discipline(cursor, student_id)
        effort = self._compute_effort(cursor, student_id)
        pace = self._compute_pace(cursor, student_id, assignments)
        error_response = self._compute_error_response(cursor, student_id)
        error_frequency = self._compute_error_frequency(cursor, student_id)

        cursor.close()
        conn.close()

        return {
            'student_id': student_id,
            'computed_at': datetime.utcnow(),
            'mastery': mastery,
            'engineering_discipline': discipline,
            'effort_regulation': effort,
            'pace': pace,
            'error_response': error_response,
            'error_frequency': error_frequency,
            'help_seeking': {},  # V7 seam, nullable
        }

    def _compute_mastery(self, cursor, student_id: str, assignments: List[str]) -> Dict:
        """Compute V1: Concept mastery using BKT."""
        mastery = {}

        for assignment_id in assignments:
            # Get workflow runs for this assignment
            cursor.execute("""
                SELECT conclusion, concept_id
                FROM raw_workflow_runs
                WHERE student_id = %s AND assignment_id = %s
                ORDER BY completed_at ASC
            """, (student_id, assignment_id))

            runs = cursor.fetchall()
            if not runs:
                continue

            # For each concept tested, update mastery via BKT
            concepts_by_id = {}
            for conclusion, concept_id in runs:
                if not concept_id:
                    continue

                outcome = 1 if conclusion == 'success' else 0

                if concept_id not in concepts_by_id:
                    concepts_by_id[concept_id] = {
                        'outcomes': [],
                        'params': BKTParams(),
                    }

                concepts_by_id[concept_id]['outcomes'].append(outcome)

            # Compute BKT for each concept
            for concept_id, data in concepts_by_id.items():
                prior = MasteryState(p_mastery=0.3, n=0)  # Start with prior
                for outcome in data['outcomes']:
                    prior = bkt_update(prior, outcome, params=data['params'])

                if concept_id not in mastery:
                    mastery[concept_id] = prior.to_dict()
                elif prior.n > mastery[concept_id].get('n', 0):
                    mastery[concept_id] = prior.to_dict()

        return mastery

    def _compute_discipline(self, cursor, student_id: str) -> Dict:
        """Compute V2: Engineering discipline."""
        cursor.execute("""
            SELECT COUNT(*), SUM(additions + deletions)
            FROM raw_commits
            WHERE student_id = %s
            AND committed_at > now() - interval '%s days'
        """, (student_id, self.window_days))

        count, total_loc = cursor.fetchone()
        total_loc = total_loc or 0

        # Placeholder: would integrate with ruff output
        # For now, assume 5 violations per 100 commits
        violations = count // 20 if count > 0 else 0

        state = compute_discipline(
            commit_messages=[''] * (count or 0),
            files_modified=0,
            code_lines=total_loc,
            linter_violations=violations,
            tests_exist=True,  # TODO: verify from commits
            tests_passing=True,  # TODO: verify from workflow runs
        )

        return {
            'ruff_issues_per_100_loc': state.ruff_issues_per_100_loc,
            'tests_present': state.tests_present,
            'tests_passing': state.tests_passing,
            'score': discipline_score(state),
            'n': state.n,
        }

    def _compute_effort(self, cursor, student_id: str) -> Dict:
        """Compute V3: Effort regulation."""
        cursor.execute("""
            SELECT committed_at FROM raw_commits
            WHERE student_id = %s
            AND committed_at > now() - interval '%s days'
            ORDER BY committed_at ASC
        """, (student_id, self.window_days))

        timestamps = [row[0] for row in cursor.fetchall()]

        if len(timestamps) < 2:
            return {'mean_gap_hours': 0, 'burstiness_ratio': 0, 'score': 0.5, 'n': 0}

        state = compute_effort(timestamps)

        return {
            'mean_gap_hours': state.mean_gap_hours,
            'gap_stddev_hours': state.gap_stddev_hours,
            'max_gap_hours': state.max_gap_hours,
            'burstiness_ratio': state.burstiness_ratio,
            'score': effort_score(state),
            'n': state.n,
        }

    def _compute_pace(self, cursor, student_id: str, assignments: List[str]) -> Dict:
        """Compute V4: Learning pace."""
        pace_data = {}

        for assignment_id in assignments:
            cursor.execute("""
                SELECT released_at, due_at FROM assignments WHERE assignment_id = %s
            """, (assignment_id,))
            result = cursor.fetchone()
            if not result:
                continue

            released_at, due_at = result

            # Get first commit and first pass
            cursor.execute("""
                SELECT MIN(committed_at) FROM raw_commits
                WHERE student_id = %s AND assignment_id = %s
            """, (student_id, assignment_id))
            first_commit = cursor.fetchone()[0]

            cursor.execute("""
                SELECT MIN(completed_at) FROM raw_workflow_runs
                WHERE student_id = %s AND assignment_id = %s AND conclusion = 'success'
            """, (student_id, assignment_id))
            first_pass = cursor.fetchone()[0]

            # Get attempt counts
            cursor.execute("""
                SELECT COUNT(*), SUM(CASE WHEN conclusion = 'success' THEN 1 ELSE 0 END)
                FROM raw_workflow_runs
                WHERE student_id = %s AND assignment_id = %s
            """, (student_id, assignment_id))
            attempts, passes = cursor.fetchone()
            passes = passes or 0

            state = compute_pace(
                released_at=released_at,
                due_at=due_at,
                first_commit_at=first_commit,
                first_pass_at=first_pass,
                total_attempts=attempts or 0,
                total_passes=passes,
            )

            pace_data[assignment_id] = {
                'days_to_first_pass': state.days_to_first_pass,
                'pass_rate': state.pass_rate,
                'is_censored': state.is_censored,
                'score': pace_score(state),
            }

        return pace_data or {'aggregate': {'score': 0.5}}

    def _compute_error_response(self, cursor, student_id: str) -> Dict:
        """Compute V5: Error response."""
        cursor.execute("""
            SELECT COUNT(*) FROM raw_workflow_runs
            WHERE student_id = %s AND conclusion = 'failure'
        """, (student_id, ))
        failures = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM raw_workflow_runs
            WHERE student_id = %s AND conclusion = 'success'
        """, (student_id, ))
        successes = cursor.fetchone()[0]

        # Simplified: no wheel-spin detection yet
        state = compute_error_response([], [])

        return {
            'successes_after_fail': successes,
            'failures_after_fail': failures,
            'wheel_spin_detected': False,
            'score': error_response_score(state),
            'n': failures,
        }

    def _compute_error_frequency(self, cursor, student_id: str) -> Dict:
        """Compute V6: Error frequency."""
        cursor.execute("""
            SELECT COUNT(*), SUM(CASE WHEN conclusion = 'failure' THEN 1 ELSE 0 END)
            FROM raw_workflow_runs
            WHERE student_id = %s
            AND completed_at > now() - interval '%s days'
        """, (student_id, self.window_days))

        attempts, failures = cursor.fetchone()
        attempts = attempts or 0
        failures = failures or 0

        state = compute_error_frequency(
            total_attempts=attempts,
            total_failures=failures,
        )

        return {
            'error_rate': state.error_rate,
            'error_rate_normalized': state.error_rate_normalized,
            'score': error_frequency_score(state),
            'n': state.n,
        }

    def run(self):
        """Run feature computation for dirty students."""
        dirty = self.get_dirty_students()
        print(f"Found {len(dirty)} dirty students")

        for student_id in dirty:
            try:
                features = self.compute_for_student(student_id)
                self._insert_features(features)
                print(f"✓ {student_id}")
            except Exception as e:
                print(f"✗ {student_id}: {e}")

    def _insert_features(self, features: Dict):
        """Insert computed features into database."""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO learner_features
                (student_id, computed_at, window_days, mastery, engineering_discipline,
                 effort_regulation, pace, error_response, error_frequency, help_seeking)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                features['student_id'],
                features['computed_at'],
                self.window_days,
                str(features['mastery']),
                str(features['engineering_discipline']),
                str(features['effort_regulation']),
                str(features['pace']),
                str(features['error_response']),
                str(features['error_frequency']),
                str(features['help_seeking']),
            ))
            conn.commit()
        finally:
            cursor.close()
            conn.close()


if __name__ == '__main__':
    computer = FeatureComputer()
    computer.run()
