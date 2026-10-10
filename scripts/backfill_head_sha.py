"""scripts/backfill_head_sha.py -- fill raw_workflow_runs.head_sha for runs collected before it
existed (D-063).

Why: features/compute_features.py recognises a sync-triggered run (rule b) by joining the
run's head_sha to raw_commits.message. Runs collected before D-063 have head_sha NULL, so
until they are filled the rule cannot see them and they fail OPEN (counted as student runs).
The collector now stores head_sha for new runs; this script fills the old ones.

What it does, per run whose head_sha IS NULL: GET /repos/OWNER/REPO/actions/runs/RUN_ID for
each candidate repo (the roster's repos for that student, narrowed to the run's assignment
when it has one -- run ids are global, so exactly one repo answers 200), and read `head_sha`.

Safety, in order of importance:
  - NEVER overwrites. The write is `UPDATE ... WHERE run_id = %s AND head_sha IS NULL`; a run
    that already has a head_sha is not even fetched.
  - DRY-RUN is the default: GET requests only, no database write. `--apply` writes.
  - Only head_sha is written. No other column, no other table.
  - The token is read from the environment as scripts.collect does (python-dotenv loads the
    gitignored .env), goes only in the Authorization header, and is replaced by *** in every
    printed line.

Counts printed: runs total / already set / would fill (or filled) / not found / errors, and
how many of the filled runs hit a sync commit already in raw_commits, as
compute_features.sync_commit_sql defines one (those are the runs rule (b) will exclude).

Run (dry-run first):
    python -m scripts.backfill_head_sha [--student anas]
    python -m scripts.backfill_head_sha [--student anas] --apply
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field

import requests

from features.compute_features import sync_commit_sql
from scripts.publish_repo import GH_API, PublishRefused
from scripts.seed_data import load_roster
from scripts.sync_template import SyncRefused, _load_token, _Out
from system import db

_TIMEOUT_S = 60
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass
class Result:
    total: int = 0
    already_set: int = 0
    found: dict[int, str] = field(default_factory=dict)      # run_id -> head_sha
    not_found: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    filled: int = 0
    lost_race: int = 0
    sync_hits: list[int] = field(default_factory=list)       # runs whose commit is a sync commit


class RunsAPI:
    """One call. Token only goes in the Authorization header."""

    def __init__(self, token: str):
        self._h = {"Authorization": f"Bearer {token}",
                   "Accept": "application/vnd.github+json"}

    def head_sha(self, owner: str, repo: str, run_id: int) -> tuple[str, str | None]:
        """('ok', sha) | ('missing', None) when this repo has no such run | ('error', why)."""
        r = requests.request("GET", f"{GH_API}/repos/{owner}/{repo}/actions/runs/{run_id}",
                             headers=self._h, timeout=_TIMEOUT_S)
        if r.status_code == 404:
            return "missing", None
        if r.status_code != 200:
            return "error", f"HTTP {r.status_code}"
        body = r.json()
        sha = body.get("head_sha")
        if body.get("id") != run_id or not isinstance(sha, str) or not _SHA_RE.match(sha):
            return "error", "unexpected payload (id or head_sha missing/invalid)"
        return "ok", sha


def candidate_repos(student_id: str, assignment_id: str | None, roster: dict
                    ) -> list[tuple[str, str]]:
    """The student's roster repos, the run's own assignment's repo first. The rest follow
    because run ids are global (only one repo answers 200), so trying them is harmless and
    survives a roster that has moved on."""
    rows = [a for a in roster.get("assignments", []) if a.get("student_id") == student_id]
    own = [a for a in rows if assignment_id and a.get("assignment_id") == assignment_id]
    seen: list[tuple[str, str]] = []
    for a in [*own, *rows]:
        pair = (a["owner"], a["repo"])
        if pair not in seen:
            seen.append(pair)
    return seen


def backfill(conn, api: RunsAPI, roster: dict, out: _Out, *, apply: bool,
             student: str | None = None) -> Result:
    """Fill NULL head_sha values. The caller owns the transaction (commits or rolls back)."""
    res = Result()
    cur = conn.cursor()
    cur.execute("""
        SELECT run_id, student_id, assignment_id, head_sha FROM raw_workflow_runs
        WHERE (%s::text IS NULL OR student_id = %s) ORDER BY run_id
    """, (student, student))
    rows = cur.fetchall()
    res.total = len(rows)

    for run_id, student_id, assignment_id, head_sha in rows:
        if head_sha is not None:
            res.already_set += 1                    # never fetched, never touched
            continue
        sha, why = None, None
        for owner, repo in candidate_repos(student_id, assignment_id, roster):
            status, value = api.head_sha(owner, repo, run_id)
            if status == "ok":
                sha = value
                break
            if status == "error":
                why = f"{owner}/{repo}: {value}"
                break
        if sha is None:
            if why:
                res.errors.append(f"run {run_id}: {why}")
            else:
                res.not_found.append(run_id)
            continue
        res.found[run_id] = sha

    cur.execute(f"SELECT c.sha FROM raw_commits c WHERE {sync_commit_sql('c')}")
    sync_shas = {r[0] for r in cur.fetchall()}
    res.sync_hits = sorted(rid for rid, sha in res.found.items() if sha in sync_shas)

    if apply:
        for run_id, sha in sorted(res.found.items()):
            cur.execute("UPDATE raw_workflow_runs SET head_sha = %s "
                        "WHERE run_id = %s AND head_sha IS NULL", (sha, run_id))
            if cur.rowcount == 1:
                res.filled += 1
            else:
                res.lost_race += 1                  # someone filled it first; left alone

    mode = "APPLY" if apply else "DRY-RUN (GET only, nothing written)"
    out.say(f"backfill_head_sha {mode}")
    out.say(f"  runs in scope            : {res.total}")
    out.say(f"  already have head_sha    : {res.already_set}  (never fetched, never touched)")
    verb = "filled" if apply else "would fill"
    out.say(f"  {verb:25s}: {res.filled if apply else len(res.found)}")
    out.say(f"  not found in any repo    : {len(res.not_found)} {res.not_found or ''}".rstrip())
    out.say(f"  errors                   : {len(res.errors)}")
    for e in res.errors:
        out.say(f"    {e}")
    if apply and res.lost_race:
        out.say(f"  skipped (filled meanwhile): {res.lost_race}")
    out.say(f"  sync-triggered (rule b)  : {len(res.sync_hits)} {res.sync_hits or ''}".rstrip())
    if not apply:
        out.say("No write was made. Re-run with --apply to write exactly this.")
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--student", help="only this student_id")
    ap.add_argument("--apply", action="store_true", help="write (default is a dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="the default; accepted for clarity")
    args = ap.parse_args(argv)
    if args.apply and args.dry_run:
        ap.error("--apply and --dry-run are mutually exclusive")

    token = ""
    try:
        token = _load_token()
        out = _Out(token)
        roster = load_roster()
        conn = db._open()
        try:
            backfill(conn, RunsAPI(token), roster, out, apply=args.apply, student=args.student)
            if args.apply:
                conn.commit()
            else:
                conn.rollback()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
    except (PublishRefused, SyncRefused, requests.RequestException) as exc:
        print(f"REFUSED: {_Out(token).clean(str(exc))}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
