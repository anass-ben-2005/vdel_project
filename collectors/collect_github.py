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

Per-file assignment attribution (D-043), added for the curriculum redesign (D-035
onward): one repo can now cover several `assignment_id`s (one per `assignments.
file_path`), so `collect_repo` takes a LIST of assignment_ids for its repo (grouped by
`collect_all`) instead of one scalar. Each commit's real changed-file list is matched
against each assignment's `file_path`; `raw_commits.assignment_id` is the single match
or NULL for zero/multiple (D-043); the actual multi-assignment record lands on
`attempts` instead, which already tolerates several rows sharing one `commit_sha`
(D-041). A group where no assignment declares a `file_path` (the original one-repo-
one-assignment shape, e.g. `config/roster.yaml`'s existing kaggle-pipeline rows) falls
back to the pre-D-043 behaviour exactly -- the whole commit/run attributed to that one
assignment, unconditionally, so nothing already collected changes shape.
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
    """ADDED: counters for the backfill-vs-incremental comparison (BUILD_PLAN 1.4).

    `commits_without_open_attempt` (D-043): a commit matched a real assignment by file,
    but that assignment had no unsubmitted `attempts` row to attach `commit_sha`/
    `submitted_at` to -- either nothing has been rendered for it yet, or the student's
    prior attempt there is already submitted. Counted rather than left as a silent
    0-row UPDATE (see D-043's Cost); not a defect to chase, the same way the V4/V2
    cohort-of-one degeneracy in STATUS.md is a named limitation, not a bug.
    """

    api_calls: int = 0
    detail_calls: int = 0
    commits_upserted: int = 0
    runs_upserted: int = 0
    commits_without_open_attempt: int = 0
    classifications: list = field(default_factory=list)
    failed_repos: list = field(default_factory=list)

    def summary(self) -> str:
        from collectors.error_classifier import match_rate
        return (f"api_calls={self.api_calls} detail_calls={self.detail_calls} "
                f"commits={self.commits_upserted} runs={self.runs_upserted} "
                f"commits_without_open_attempt={self.commits_without_open_attempt} "
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


def _assignment_file_paths(cur, assignment_ids):
    """D-043: real `file_path`s for this repo's assignments, straight from the DB --
    never re-derived or guessed, matching this project's `assessment/` modules' own
    rule of reading structure from its one real source rather than a second copy."""
    cur.execute(
        "SELECT assignment_id, file_path FROM assignments WHERE assignment_id = ANY(%s)",
        (list(assignment_ids),),
    )
    return dict(cur.fetchall())


def _match_assignments(filenames, file_paths):
    """D-043: which assignment_id(s) does this commit's changed-file list touch.

    `filenames`: the commit's real changed files (`detail["files"][i]["filename"]`,
    repo-relative, exact string -- same discipline as `assessment/scope_check.py`'s
    exact line-range matching, no fuzzy guessing).

    `file_paths`: {assignment_id: file_path_or_None} for this repo's assignments.
    An assignment with `file_path IS NULL` means the legacy one-repo-one-assignment
    shape (`config/roster.yaml`'s existing rows, seeded without a `file_path`) --
    there is nothing to file-match, so it is treated as matching every commit
    unconditionally, exactly as collect_repo behaved before D-043. This only applies
    when NO assignment in the group declares a `file_path`; a real per-file curriculum
    group (some/all `file_path`s set) never falls back, even for its own None entries,
    since a None inside an otherwise file-scoped group would silently swallow every
    commit into that one assignment -- worse than leaving it unmatched.
    """
    scoped = {aid: fp for aid, fp in file_paths.items() if fp is not None}
    if not scoped:
        return list(file_paths)
    return [aid for aid, fp in scoped.items() if fp in filenames]


def collect_repo(conn, owner, repo, student_id, assignment_ids):
    """D-043: `assignment_ids` is every assignment this ONE repo covers (grouped by
    `collect_all`), not a single scalar -- a repo is now, in the curriculum model, a
    project with several assignments in it, not one assignment per repo.
    """
    cur = conn.cursor()
    assignment_ids = list(assignment_ids)
    file_paths = _assignment_file_paths(cur, assignment_ids)

    # Flaw 1b: incremental — only commits since our last collection across this repo's
    # assignments. Ignores any commit already landed with assignment_id NULL (D-043,
    # ambiguous/unmatched) -- a conservative under-count: worst case a few already-seen
    # commits get re-listed, not re-fetched in detail, since the sha-level skip check
    # below still protects the expensive call.
    cur.execute("""SELECT MAX(committed_at) FROM raw_commits
                   WHERE student_id=%s AND assignment_id = ANY(%s)""",
                (student_id, assignment_ids))
    since = cur.fetchone()[0]
    params = {}
    if since:
        params["since"] = since.isoformat()

    commit_rows = []
    # One entry per (commit, assignment) match, duplicates intentional: a commit touching
    # two assignments contributes two. Only assignment_id is kept -- since D-045a the
    # collector writes nothing to `attempts`, so the sha is not needed here; the per-commit
    # record lives in `test_results`, written by whatever actually ran the tests.
    matched_assignments: list[str] = []
    for c in _paged(f"{GH}/repos/{owner}/{repo}/commits", params):
        sha = c["sha"]
        # Flaw 1a: skip the expensive detail call for commits we already have complete
        cur.execute("SELECT 1 FROM raw_commits WHERE sha=%s AND additions IS NOT NULL", (sha,))
        if cur.fetchone():
            continue
        detail = _get(c["url"]).json()                  # the expensive call, now rare
        _STATS.detail_calls += 1
        s = detail.get("stats", {})
        files = detail.get("files", [])
        filenames = {f["filename"] for f in files}
        matched = _match_assignments(filenames, file_paths)
        # D-043: a single match is real attribution; zero or several is honestly NULL
        # on raw_commits (the table can't hold "several"), with the real per-assignment
        # record written on `attempts` below instead.
        commit_assignment_id = matched[0] if len(matched) == 1 else None
        committed_at = c["commit"]["committer"]["date"]
        commit_rows.append((sha, student_id, commit_assignment_id, committed_at,
                            s.get("additions"), s.get("deletions"),
                            len(files),
                            c["commit"]["message"][:500]))
        matched_assignments.extend(matched)

    # Flaw 3: one batched upsert instead of N inserts. DO UPDATE now also refreshes
    # assignment_id (D-043) -- with one collect_repo call per repo (not per assignment,
    # per D-043's collect_all regrouping), a re-run recomputes the same match
    # deterministically, so overwriting it is correct, not the old first-writer-wins bug.
    if commit_rows:
        execute_values(cur, """
            INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at,
                                     additions, deletions, files_changed, message)
            VALUES %s ON CONFLICT (sha) DO UPDATE SET
              additions = EXCLUDED.additions, assignment_id = EXCLUDED.assignment_id
        """, commit_rows)
        _STATS.commits_upserted += len(commit_rows)

    # D-043: associate each matched commit with the assignment's current open attempt.
    #
    # D-045a CORRECTION: this deliberately does NOT write `submitted_at`, and no longer
    # writes `commit_sha` either. An attempt freezes only when its hidden tests reach 100%
    # pass -- never merely because the student pushed -- so the collector, which sees
    # pushes and knows nothing about test outcomes, is structurally the wrong component to
    # decide that. The earlier version set both columns on the first matched commit under a
    # `WHERE submitted_at IS NULL` guard, which froze the attempt on push number one and
    # then, because of that same guard, silently ignored every commit after it. That is
    # backwards twice over: it froze too early and then stopped collecting.
    #
    # `attempts.commit_sha`/`submitted_at` are now written by exactly one thing: whatever
    # observes a 100%-pass hidden-test run (the test runner, Stage B2). What the collector
    # contributes instead is the per-commit record in `test_results`, keyed by commit_sha
    # (D-045c) -- so a student's failing history accumulates instead of being overwritten,
    # which is what V5/V6 are computed from.
    #
    # The lookup still resolves which attempt a commit belongs to, and still counts the
    # case where no open attempt exists (nothing rendered yet, or already frozen), because
    # that count is what tells us telemetry is arriving with nowhere to attach.
    for assignment_id in matched_assignments:
        cur.execute("""
            SELECT attempt_id FROM attempts
            WHERE student_id = %s AND assignment_id = %s AND submitted_at IS NULL
            ORDER BY attempt_no DESC LIMIT 1
        """, (student_id, assignment_id))
        if cur.fetchone() is None:
            _STATS.commits_without_open_attempt += 1

    # Workflow runs (batched too). D-043: a CI run tests the whole repo, not one file,
    # so it can only be attributed when the repo covers exactly one assignment; NULL
    # otherwise (ambiguous), same convention as raw_commits.
    run_assignment_id = assignment_ids[0] if len(assignment_ids) == 1 else None
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
        run_rows.append((w["id"], student_id, run_assignment_id, w["status"],
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
    """Flaw 7: per-repo isolation — a broken repo is a logged warning, not an outage.

    D-043: groups `repos` by `(owner, repo, student_id)` before collecting, so a repo
    listed under several `assignment_id`s (one `config/roster.yaml` row per assignment,
    the curriculum model's four-assignments-one-repo shape) is fetched ONCE, with the
    full list of assignment_ids it covers -- not once per assignment, which was the
    actual root cause of the pre-D-043 bug (each call re-stamped the whole repo's
    commits with its own single assignment_id, and `ON CONFLICT (sha) DO UPDATE` never
    touched assignment_id, so whichever roster row happened to run first won forever).
    A repo with exactly one assignment_id in `repos` (the existing kaggle-pipeline rows)
    forms a group of size 1 and behaves exactly as before.
    """
    groups: dict[tuple, list] = {}
    for r in repos:
        key = (r["owner"], r["repo"], r["student_id"])
        groups.setdefault(key, [])
        if r["assignment_id"] not in groups[key]:
            groups[key].append(r["assignment_id"])

    ok, failed = 0, []
    for (owner, repo, student_id), assignment_ids in groups.items():
        try:
            collect_repo(conn, owner, repo, student_id, assignment_ids)
            ok += 1
        except Exception as e:  # noqa: BLE001 -- isolation is the point of Flaw 7
            failed.append({"repo": repo, "error": str(e)})
            conn.rollback()
    _STATS.failed_repos = failed
    return {"ok": ok, "failed": failed, "stats": _STATS.summary()}
