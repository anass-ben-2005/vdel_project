"""
collectors/collect_github.py — rate-aware, incremental, batched, isolated GitHub collector.

Optimizations (see Module 2 optimization pass):
  1. skip-if-present + incremental `since=`  -> ~99% fewer detail calls after backfill
  2. rate-limit-header-aware backoff          -> avoids the hard 5000/h wall + abuse-ban
  3. batched execute_values upserts           -> 10-50x fewer DB round-trips
  7. per-repo failure isolation               -> one bad repo != total outage

Transcribed from VDEL_Modules_1_2_Build.md Part D. Three additions, each marked ADDED
below and none altering the documented logic:
  - a call counter, so BUILD_PLAN 1.4 ("confirm the second run makes almost no API
    calls") can be answered with numbers rather than an impression;
  - classification of failed runs at collection time, so error_class/concept_id are
    populated -- the document defines classify_error but its collector never calls it,
    and without the call concept_id stays NULL and mastery stays empty;
  - lazy header/token reading, so importing this module does not require GITHUB_TOKEN.
"""
import io
import os
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime as dt

import requests
from psycopg2.extras import execute_values

from collectors.error_classifier import classify_error

GH = "https://api.github.com"


def _headers():
    """ADDED: read the token per call rather than at import.

    The document has HEADERS as a module constant built from os.environ['GITHUB_TOKEN'],
    which raises KeyError on import -- so `import collectors.collect_github` fails in
    tests and in CI, where no token exists.
    """
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is not set. See .env.example.")
    return {"Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"}


@dataclass
class Stats:
    """ADDED: counters for the backfill-vs-incremental comparison (BUILD_PLAN 1.4)."""

    api_calls: int = 0
    detail_calls: int = 0
    commits_upserted: int = 0
    runs_upserted: int = 0
    classifications: list = field(default_factory=list)
    failed_repos: list = field(default_factory=list)

    def summary(self) -> str:
        from collectors.error_classifier import match_rate
        return (f"api_calls={self.api_calls} detail_calls={self.detail_calls} "
                f"commits={self.commits_upserted} runs={self.runs_upserted} "
                f"classified={len(self.classifications)} "
                f"match_rate={match_rate(self.classifications)}")


_STATS = Stats()


def _get(url, params=None):
    """Single GET with rate-limit awareness (Flaw 2)."""
    r = requests.get(url, headers=_headers(), params=params, timeout=30)
    _STATS.api_calls += 1
    remaining = int(r.headers.get("X-RateLimit-Remaining", 1))
    if remaining < 50:                                  # back off before the wall
        reset = int(r.headers.get("X-RateLimit-Reset", time.time()))
        time.sleep(max(0, reset - time.time()) + 1)
    r.raise_for_status()
    return r


def _paged(url, params=None):
    params = dict(params or {}, per_page=100)
    page = 1
    while True:
        batch = _get(url, dict(params, page=page)).json()
        items = batch.get("workflow_runs", batch) if isinstance(batch, dict) else batch
        if not items:
            return
        yield from items
        if len(items) < 100:
            return
        page += 1


def _failure_log(owner, repo, run_id):
    """ADDED: fetch a failed run's logs so classify_error has text to match on.

    Only for failures -- a successful run has no error to classify, and the logs
    endpoint returns a zip that is expensive to pull. Logs expire after 90 days, so a
    missing archive is normal and returns None (which classifies as 'empty').
    """
    try:
        r = _get(f"{GH}/repos/{owner}/{repo}/actions/runs/{run_id}/logs")
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            return "\n".join(z.read(n).decode("utf-8", errors="replace")
                             for n in z.namelist()[:20])
    except (requests.RequestException, zipfile.BadZipFile, KeyError):
        return None


def collect_repo(conn, owner, repo, student_id, assignment_id):
    cur = conn.cursor()

    # Flaw 1b: incremental — only commits since our last collection
    cur.execute("""SELECT MAX(committed_at) FROM raw_commits
                   WHERE student_id=%s AND assignment_id=%s""",
                (student_id, assignment_id))
    since = cur.fetchone()[0]
    params = {}
    if since:
        params["since"] = since.isoformat()

    commit_rows = []
    for c in _paged(f"{GH}/repos/{owner}/{repo}/commits", params):
        sha = c["sha"]
        # Flaw 1a: skip the expensive detail call for commits we already have complete
        cur.execute("SELECT 1 FROM raw_commits WHERE sha=%s AND additions IS NOT NULL", (sha,))
        if cur.fetchone():
            continue
        detail = _get(c["url"]).json()                  # the expensive call, now rare
        _STATS.detail_calls += 1
        s = detail.get("stats", {})
        commit_rows.append((sha, student_id, assignment_id,
                            c["commit"]["committer"]["date"],
                            s.get("additions"), s.get("deletions"),
                            len(detail.get("files", [])),
                            c["commit"]["message"][:500]))

    # Flaw 3: one batched upsert instead of N inserts
    if commit_rows:
        execute_values(cur, """
            INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at,
                                     additions, deletions, files_changed, message)
            VALUES %s ON CONFLICT (sha) DO UPDATE SET additions = EXCLUDED.additions
        """, commit_rows)
        _STATS.commits_upserted += len(commit_rows)

    # Workflow runs (batched too)
    run_rows = []
    for w in _paged(f"{GH}/repos/{owner}/{repo}/actions/runs"):
        dur = None
        if w.get("run_started_at") and w.get("updated_at"):
            f = "%Y-%m-%dT%H:%M:%SZ"
            dur = int((dt.strptime(w["updated_at"], f)
                       - dt.strptime(w["run_started_at"], f)).total_seconds())
        # ADDED: classify at collection time so concept_id is populated.
        error_class, concept_id = (None, None)
        if w["conclusion"] == "failure":
            error_class, concept_id = classify_error(_failure_log(owner, repo, w["id"]))
            _STATS.classifications.append((error_class, concept_id))
        run_rows.append((w["id"], student_id, assignment_id, w["status"],
                         w["conclusion"], w["run_started_at"], w["updated_at"], dur,
                         error_class, concept_id))
    if run_rows:
        execute_values(cur, """
            INSERT INTO raw_workflow_runs (run_id, student_id, assignment_id, status,
                                           conclusion, started_at, completed_at, duration_s,
                                           error_class, concept_id)
            VALUES %s ON CONFLICT (run_id) DO NOTHING
        """, run_rows)
        _STATS.runs_upserted += len(run_rows)

    conn.commit()


def collect_all(conn, repos):
    """Flaw 7: per-repo isolation — a broken repo is a logged warning, not an outage."""
    ok, failed = 0, []
    for repo in repos:
        try:
            collect_repo(conn, **repo)
            ok += 1
        except Exception as e:  # noqa: BLE001 -- isolation is the point of Flaw 7
            failed.append({"repo": repo.get("repo"), "error": str(e)})
            conn.rollback()
    _STATS.failed_repos = failed
    return {"ok": ok, "failed": failed, "stats": _STATS.summary()}
