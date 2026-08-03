"""Collect commits and workflow runs from GitHub into the raw tables.

Land raw first (CLAUDE.md section 4): feature formulas will change and carry a
formula_ver, so history can only be recomputed if the raw events were kept. Nothing here
interprets anything -- classification and feature computation happen downstream.

The seven optimisations from BUILD_PLAN 1.3, in the priority order given there:
  1. Skip-if-present before the per-commit detail call. The list endpoint does not
     return additions/deletions/files, so each commit needs a second request; that
     request is the expensive one and this check is what avoids it.
  2. Incremental `since=` from the last collected timestamp.
  3. Rate-limit-header-aware backoff, read from the response already in hand.
  4. Batched execute_values upserts.
  5. Per-repo try/except isolation -- a broken repo is a warning, not an outage.

Idempotent throughout (invariant 9): re-running collects nothing new and changes nothing.
"""

from __future__ import annotations

import io
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

import requests
from psycopg2.extras import execute_values

from collectors.error_classifier import classify_run, match_rate
from system import db

API = "https://api.github.com"
TIMEOUT = 30


@dataclass
class Stats:
    """Counters so BUILD_PLAN 1.4 -- 'confirm the second run makes almost no API calls'
    -- can be answered with numbers instead of an impression."""

    api_calls: int = 0
    commits_seen: int = 0
    commits_inserted: int = 0
    commit_details_fetched: int = 0
    commit_details_skipped: int = 0
    runs_inserted: int = 0
    logs_fetched: int = 0
    classifications: list = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"api_calls={self.api_calls} "
            f"commits_inserted={self.commits_inserted}/{self.commits_seen} "
            f"detail_calls={self.commit_details_fetched} "
            f"(skipped {self.commit_details_skipped}) "
            f"runs_inserted={self.runs_inserted} "
            f"classifier_match_rate={match_rate(self.classifications)}"
        )


class GitHubClient:
    """Thin HTTP layer: auth, pagination, rate limiting, call counting."""

    def __init__(self, token: str, stats: Stats):
        self.stats = stats
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    def get(self, path: str, **params) -> requests.Response:
        resp = self.session.get(f"{API}{path}", params=params, timeout=TIMEOUT)
        self.stats.api_calls += 1
        self._respect_rate_limit(resp)
        resp.raise_for_status()
        return resp

    def _respect_rate_limit(self, resp: requests.Response) -> None:
        """Optimisation 3: sleep before hitting the wall.

        The headers arrive on every response, so this costs nothing. The previous
        version spent an extra API call on /rate_limit before each repo -- paying for
        the information it was trying to conserve.
        """
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is None or int(remaining) > 10:
            return
        reset = int(resp.headers.get("X-RateLimit-Reset", 0))
        wait = max(0.0, reset - time.time()) + 1
        if wait > 0:
            print(f"    rate limit at {remaining}; sleeping {wait:.0f}s")
            time.sleep(wait)

    def paginate(self, path: str, key: str | None = None, **params):
        """Yield items across pages, stopping at the first short page."""
        params.setdefault("per_page", 100)
        page = 1
        while True:
            payload = self.get(path, page=page, **params).json()
            items = payload if key is None else payload.get(key, [])
            if not items:
                return
            yield from items
            if len(items) < params["per_page"]:
                return
            page += 1


def _existing_shas(cur, shas: list[str]) -> set[str]:
    """Optimisation 1: which of these are already stored."""
    if not shas:
        return set()
    cur.execute("SELECT sha FROM raw_commits WHERE sha = ANY(%s)", (shas,))
    return {row[0] for row in cur.fetchall()}


def _watermark(cur, table: str, column: str, assignment_id: str) -> datetime | None:
    """Optimisation 2: the newest event already collected for this assignment."""
    cur.execute(
        f"SELECT max({column}) FROM {table} WHERE assignment_id = %s",
        (assignment_id,),
    )
    return cur.fetchone()[0]


def collect_commits(gh, cur, owner, repo, student_id, assignment_id, stats: Stats) -> None:
    since = _watermark(cur, "raw_commits", "committed_at", assignment_id)
    params = {"since": since.isoformat()} if since else {}
    if since:
        print(f"    incremental since {since.isoformat()}")

    listed = list(gh.paginate(f"/repos/{owner}/{repo}/commits", **params))
    stats.commits_seen += len(listed)
    if not listed:
        return

    known = _existing_shas(cur, [c["sha"] for c in listed])
    stats.commit_details_skipped += len(known)

    rows = []
    for entry in listed:
        sha = entry["sha"]
        if sha in known:
            continue  # optimisation 1: never pay for the detail call twice
        detail = gh.get(f"/repos/{owner}/{repo}/commits/{sha}").json()
        stats.commit_details_fetched += 1
        commit_stats = detail.get("stats", {})
        rows.append(
            (
                sha,
                student_id,
                assignment_id,
                entry["commit"]["author"]["date"],
                commit_stats.get("additions"),
                commit_stats.get("deletions"),
                len(detail.get("files", [])),
                entry["commit"]["message"],
            )
        )

    if rows:
        execute_values(
            cur,
            "INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at,"
            " additions, deletions, files_changed, message) VALUES %s"
            " ON CONFLICT (sha) DO NOTHING",
            rows,
        )
        stats.commits_inserted += cur.rowcount


def _failure_log(gh, owner: str, repo: str, run_id: int, stats: Stats) -> str | None:
    """Download and flatten a failed run's logs so the classifier has something to read.

    Only for failures: successful runs carry no error to classify, and the logs endpoint
    returns a zip archive that is expensive to fetch. Without this the classifier can
    never run, which is why the previous version always stored concept_id = NULL and
    therefore always produced an empty mastery object.
    """
    try:
        resp = gh.get(f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs")
        stats.logs_fetched += 1
        with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
            return "\n".join(
                archive.read(name).decode("utf-8", errors="replace")
                for name in archive.namelist()[:20]
            )
    except (requests.RequestException, zipfile.BadZipFile, KeyError) as exc:
        # Logs expire after 90 days; a missing archive is normal, not an outage.
        print(f"    no logs for run {run_id}: {type(exc).__name__}")
        return None


def collect_workflow_runs(gh, cur, owner, repo, student_id, assignment_id, stats: Stats) -> None:
    since = _watermark(cur, "raw_workflow_runs", "completed_at", assignment_id)
    params = {"created": f">={since.date().isoformat()}"} if since else {}

    rows = []
    for run in gh.paginate(f"/repos/{owner}/{repo}/actions/runs", key="workflow_runs", **params):
        started, completed = run.get("run_started_at"), run.get("updated_at")

        # Real elapsed time. The previous version stored run_number * 60 as a
        # "placeholder duration", writing an invented number into the database.
        duration = None
        if started and completed:
            # fromisoformat parses the trailing "Z" natively from Python 3.11.
            duration = int(
                (
                    datetime.fromisoformat(completed) - datetime.fromisoformat(started)
                ).total_seconds()
            )

        conclusion = run.get("conclusion")
        log = _failure_log(gh, owner, repo, run["id"], stats) if conclusion == "failure" else None
        error_class, concept_id = classify_run(conclusion, log)
        stats.classifications.append((error_class, concept_id))

        rows.append(
            (
                run["id"], student_id, assignment_id, run.get("status"), conclusion,
                started, completed, duration, error_class, concept_id,
            )
        )

    if rows:
        execute_values(
            cur,
            "INSERT INTO raw_workflow_runs (run_id, student_id, assignment_id, status,"
            " conclusion, started_at, completed_at, duration_s, error_class, concept_id)"
            " VALUES %s ON CONFLICT (run_id) DO UPDATE SET"
            "   status = EXCLUDED.status, conclusion = EXCLUDED.conclusion,"
            "   completed_at = EXCLUDED.completed_at, duration_s = EXCLUDED.duration_s,"
            "   error_class = EXCLUDED.error_class, concept_id = EXCLUDED.concept_id",
            rows,
        )
        stats.runs_inserted += len(rows)


def collect(token: str, targets: list[tuple[str, str, str, str]]) -> Stats:
    """Collect every (owner, repo, student_id, assignment_id) target.

    One connection and one transaction per repo, so a repo either lands completely or
    not at all.
    """
    stats = Stats()
    gh = GitHubClient(token, stats)

    for owner, repo, student_id, assignment_id in targets:
        print(f"  {owner}/{repo} -> {assignment_id}")
        try:
            with db.cursor() as cur:  # optimisation 5: per-repo isolation
                collect_commits(gh, cur, owner, repo, student_id, assignment_id, stats)
                collect_workflow_runs(gh, cur, owner, repo, student_id, assignment_id, stats)
        except Exception as exc:  # noqa: BLE001 -- optimisation 5 is exactly this: one
            # broken repo must not end the run, so every failure mode is caught, recorded
            # and reported in the summary rather than allowed to propagate.
            message = f"{owner}/{repo}: {type(exc).__name__}: {exc}"
            stats.errors.append(message)
            print(f"    FAILED {message}")

    return stats
