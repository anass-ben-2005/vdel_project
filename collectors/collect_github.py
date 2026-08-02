"""GitHub data collector with optimizations."""

import os
import sys
import time
from datetime import datetime
from typing import Optional

import psycopg2
import requests
from dotenv import load_dotenv
from psycopg2.extras import execute_values

load_dotenv()

class GitHubCollector:
    """Collect commits and workflow runs from GitHub."""

    def __init__(self):
        self.token = os.getenv('GITHUB_TOKEN')
        if not self.token:
            raise ValueError("GITHUB_TOKEN not set in .env")

        self.api_base = "https://api.github.com"
        self.dsn = os.getenv('PG_DSN')
        if not self.dsn:
            raise ValueError("PG_DSN not set in .env")

        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'token {self.token}',
            'Accept': 'application/vnd.github.v3+json'
        })

    def _get_rate_limit_info(self):
        """Get current rate limit status."""
        resp = self.session.get(f"{self.api_base}/rate_limit")
        return resp.json()

    def _check_rate_limit_and_backoff(self):
        """Check rate limit and backoff if needed."""
        try:
            info = self._get_rate_limit_info()
            remaining = info['resources']['core']['remaining']
            reset_time = info['resources']['core']['reset']

            if remaining < 10:
                sleep_time = reset_time - time.time() + 1
                if sleep_time > 0:
                    print(f"Rate limit low ({remaining} remaining). Sleeping {sleep_time:.0f}s...")
                    time.sleep(sleep_time)
        except Exception as e:
            print(f"Warning: could not check rate limit: {e}")

    def _get_last_collected_timestamp(self, owner: str, repo: str, student_id: str) -> Optional[datetime]:
        """Get the timestamp of the last collected commit for this repo (Optimization #2)."""
        try:
            conn = psycopg2.connect(self.dsn)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT MAX(committed_at) FROM raw_commits
                WHERE student_id = %s AND assignment_id LIKE %s
            """, (student_id, f"{owner}-{repo}%"))
            result = cursor.fetchone()
            cursor.close()
            conn.close()

            return result[0] if result[0] else None
        except Exception as e:
            print(f"Warning: could not get last collected timestamp: {e}")
            return None

    def collect_commits(self, owner: str, repo: str, student_id: str, assignment_id: str):
        """Collect commits from a repository."""
        print(f"Collecting commits from {owner}/{repo}...")

        try:
            self._check_rate_limit_and_backoff()

            # Optimization #2: Use incremental since=
            since = self._get_last_collected_timestamp(owner, repo, student_id)
            params = {'per_page': 100, 'sort': 'updated', 'direction': 'desc'}
            if since:
                params['since'] = since.isoformat() + 'Z'
                print(f"  Incremental since: {params['since']}")

            url = f"{self.api_base}/repos/{owner}/{repo}/commits"
            all_commits = []
            page = 1

            while True:
                params['page'] = page
                resp = self.session.get(url, params=params)
                resp.raise_for_status()

                commits = resp.json()
                if not commits:
                    break

                # Optimization #3: Check rate limit headers
                remaining = int(resp.headers.get('X-RateLimit-Remaining', 0))
                if remaining < 5:
                    reset_time = int(resp.headers.get('X-RateLimit-Reset', 0))
                    sleep_time = reset_time - time.time() + 1
                    if sleep_time > 0:
                        print(f"  Rate limit critical. Sleeping {sleep_time:.0f}s...")
                        time.sleep(sleep_time)

                all_commits.extend(commits)
                page += 1

            print(f"  Found {len(all_commits)} commits")

            # Optimization #1: Skip-if-present check before per-commit detail calls
            self._filter_existing_commits(all_commits, assignment_id)

            # Optimization #4: Batch upsert with execute_values
            self._batch_insert_commits(all_commits, student_id, assignment_id)

        except requests.RequestException as e:
            # Optimization #5: Per-repo isolation
            print(f"✗ Error collecting commits from {owner}/{repo}: {e}")

    def collect_workflow_runs(self, owner: str, repo: str, student_id: str, assignment_id: str):
        """Collect workflow runs from a repository."""
        print(f"Collecting workflow runs from {owner}/{repo}...")

        try:
            self._check_rate_limit_and_backoff()

            url = f"{self.api_base}/repos/{owner}/{repo}/actions/runs"
            all_runs = []
            page = 1

            while True:
                params = {'per_page': 100, 'page': page}
                resp = self.session.get(url, params=params)
                resp.raise_for_status()

                data = resp.json()
                runs = data.get('workflow_runs', [])
                if not runs:
                    break

                all_runs.extend(runs)
                page += 1

            print(f"  Found {len(all_runs)} workflow runs")

            # Optimization #4: Batch upsert
            self._batch_insert_workflow_runs(all_runs, student_id, assignment_id)

        except requests.RequestException as e:
            # Optimization #5: Per-repo isolation
            print(f"✗ Error collecting workflow runs from {owner}/{repo}: {e}")

    def _filter_existing_commits(self, commits, assignment_id):
        """Remove commits that already exist in the database (Optimization #1)."""
        try:
            conn = psycopg2.connect(self.dsn)
            cursor = conn.cursor()

            shas = [c['sha'] for c in commits]
            if not shas:
                cursor.close()
                conn.close()
                return

            # Check which ones exist
            placeholders = ','.join(['%s'] * len(shas))
            cursor.execute(f"SELECT sha FROM raw_commits WHERE sha IN ({placeholders})", shas)
            existing = set(row[0] for row in cursor.fetchall())

            cursor.close()
            conn.close()

            # Filter in-place
            commits[:] = [c for c in commits if c['sha'] not in existing]
            print(f"  After dedup: {len(commits)} new commits to insert")

        except Exception as e:
            print(f"Warning: could not filter existing commits: {e}")

    def _batch_insert_commits(self, commits, student_id, assignment_id):
        """Batch insert commits into raw_commits (Optimization #4)."""
        if not commits:
            return

        try:
            conn = psycopg2.connect(self.dsn)
            cursor = conn.cursor()

            data = []
            for c in commits:
                data.append((
                    c['sha'],
                    student_id,
                    assignment_id,
                    c['commit']['author']['date'],
                    c.get('stats', {}).get('additions', 0),
                    c.get('stats', {}).get('deletions', 0),
                    len(c.get('files', [])),
                    c['commit']['message']
                ))

            execute_values(cursor, """
                INSERT INTO raw_commits
                (sha, student_id, assignment_id, committed_at, additions, deletions, files_changed, message)
                VALUES %s
                ON CONFLICT (sha) DO NOTHING
            """, data)

            conn.commit()
            print(f"  Inserted {cursor.rowcount} new commits")

            cursor.close()
            conn.close()

        except Exception as e:
            print(f"✗ Error batch inserting commits: {e}")

    def _batch_insert_workflow_runs(self, runs, student_id, assignment_id):
        """Batch insert workflow runs (Optimization #4)."""
        if not runs:
            return

        try:
            conn = psycopg2.connect(self.dsn)
            cursor = conn.cursor()

            data = []
            for run in runs:
                data.append((
                    run['id'],
                    student_id,
                    assignment_id,
                    run['status'],
                    run['conclusion'],
                    run['created_at'],
                    run['updated_at'],
                    (run['run_number'] or 0) * 60,  # placeholder duration
                    None,  # error_class - filled by classifier
                    None   # concept_id - filled by classifier
                ))

            execute_values(cursor, """
                INSERT INTO raw_workflow_runs
                (run_id, student_id, assignment_id, status, conclusion, started_at, completed_at, duration_s, error_class, concept_id)
                VALUES %s
                ON CONFLICT (run_id) DO NOTHING
            """, data)

            conn.commit()
            print(f"  Inserted {cursor.rowcount} new workflow runs")

            cursor.close()
            conn.close()

        except Exception as e:
            print(f"✗ Error batch inserting workflow runs: {e}")

    def collect_for_repo(self, owner: str, repo: str, student_id: str, assignment_id: str):
        """Collect both commits and workflow runs for a repository."""
        self.collect_commits(owner, repo, student_id, assignment_id)
        self.collect_workflow_runs(owner, repo, student_id, assignment_id)


if __name__ == '__main__':
    collector = GitHubCollector()

    # Example: collect for a repo
    # collector.collect_for_repo('anas', 'kaggle-pipeline-1', 'anas-001', 'project-1')
    print("GitHub collector ready. Call collect_for_repo(owner, repo, student_id, assignment_id)")
