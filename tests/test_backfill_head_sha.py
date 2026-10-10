"""scripts/backfill_head_sha.py (D-063) -- HTTP mocked, database real but always rolled back.

The property that matters most: it fills head_sha ONLY where it is NULL and never changes a
value that is already there. The rest: dry-run writes nothing, the token never reaches the
output, a run no repo knows is counted not guessed, and sync-commit hits are reported.
"""

import os

import pytest

from scripts import backfill_head_sha as bf
from scripts.sync_template import _Out
from system import db

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

TOKEN = "ghp_BACKFILL_SECRET_must_never_be_printed_9876543210"
STUDENT = "_bf_stu"
ASSIGNMENT = "_bf_A"
SYNC_SHA = "7" * 40
WORK_SHA = "8" * 40
OLD_SHA = "9" * 40           # a value that is already stored and must survive
NEW_SHA = "b" * 40           # what GitHub would (wrongly) say for that same run

ROSTER = {"assignments": [
    {"student_id": STUDENT, "assignment_id": ASSIGNMENT, "owner": "o", "repo": "repo-a"},
    {"student_id": STUDENT, "assignment_id": "_other", "owner": "o", "repo": "repo-b"},
]}
RUN_NULL_SYNC, RUN_NULL_WORK, RUN_SET, RUN_UNKNOWN = 9_700_001, 9_700_002, 9_700_003, 9_700_004


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeActions:
    """GitHub: which repo owns which run, and what its head_sha is."""

    def __init__(self, runs, *, fail_with=None):
        self.runs = runs                      # {(owner, repo, run_id): head_sha}
        self.calls: list[tuple[str, str]] = []
        self.fail_with = fail_with

    def __call__(self, method, url, headers=None, timeout=None, **kw):
        self.calls.append((method, url))
        assert headers["Authorization"] == f"Bearer {TOKEN}"
        parts = url.removeprefix(bf.GH_API).split("/")        # ['', repos, o, r, actions, runs, id]
        owner, repo, run_id = parts[2], parts[3], int(parts[6])
        if self.fail_with:
            return Resp(self.fail_with, {"message": f"boom {TOKEN}"})
        sha = self.runs.get((owner, repo, run_id))
        if sha is None:
            return Resp(404, {"message": "Not Found"})
        return Resp(200, {"id": run_id, "head_sha": sha})


@pytest.fixture
def conn():
    try:
        c = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = c.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (STUDENT, STUDENT))
    cur.execute("INSERT INTO assignments VALUES (%s,'org/a','2026-01-01 00:00+00',NULL,"
                "ARRAY['py.testing'])", (ASSIGNMENT,))
    cur.execute("INSERT INTO raw_commits VALUES (%s,%s,NULL,'2026-01-01 08:00+00',1,0,1,"
                "'ci: sync template (D-060)')", (SYNC_SHA, STUDENT))   # NULL: as collected
    cur.execute("INSERT INTO raw_commits VALUES (%s,%s,%s,'2026-01-01 09:00+00',1,0,1,"
                "'my work')", (WORK_SHA, STUDENT, ASSIGNMENT))
    for run_id, head in ((RUN_NULL_SYNC, None), (RUN_NULL_WORK, None), (RUN_SET, OLD_SHA),
                         (RUN_UNKNOWN, None)):
        cur.execute("INSERT INTO raw_workflow_runs (run_id, student_id, assignment_id, status,"
                    " conclusion, started_at, head_sha) VALUES (%s,%s,%s,'completed','failure',"
                    "'2026-01-02 10:00+00',%s)", (run_id, STUDENT, ASSIGNMENT, head))
    yield c
    c.rollback()
    c.close()


def heads(conn):
    cur = conn.cursor()
    cur.execute("SELECT run_id, head_sha FROM raw_workflow_runs WHERE student_id=%s", (STUDENT,))
    return dict(cur.fetchall())


@pytest.fixture
def github(monkeypatch):
    fake = FakeActions({
        ("o", "repo-a", RUN_NULL_SYNC): SYNC_SHA,
        ("o", "repo-b", RUN_NULL_WORK): WORK_SHA,       # only the SECOND candidate knows it
        ("o", "repo-a", RUN_SET): NEW_SHA,              # GitHub "disagrees" with what is stored
    })
    monkeypatch.setattr(bf.requests, "request", fake)
    return fake


def run_backfill(conn, *, apply):
    return bf.backfill(conn, bf.RunsAPI(TOKEN), ROSTER, _Out(TOKEN), apply=apply,
                       student=STUDENT)


def test_dry_run_reads_but_writes_nothing(conn, github, capsys):
    before = heads(conn)
    res = run_backfill(conn, apply=False)
    assert heads(conn) == before                          # no write at all
    assert res.found == {RUN_NULL_SYNC: SYNC_SHA, RUN_NULL_WORK: WORK_SHA}
    assert res.filled == 0 and {m for m, _ in github.calls} == {"GET"}
    assert "DRY-RUN" in capsys.readouterr().out


def test_apply_fills_only_null_and_never_overwrites(conn, github):
    res = run_backfill(conn, apply=True)
    got = heads(conn)
    assert got[RUN_NULL_SYNC] == SYNC_SHA and got[RUN_NULL_WORK] == WORK_SHA
    assert got[RUN_SET] == OLD_SHA                        # untouched although GitHub said NEW_SHA
    assert got[RUN_UNKNOWN] is None                       # no repo knows it: left NULL, not guessed
    assert res.filled == 2 and res.already_set == 1 and res.not_found == [RUN_UNKNOWN]
    # an already-set run is not even fetched
    assert not any(str(RUN_SET) in url for _, url in github.calls)


def test_a_value_set_between_the_read_and_the_write_is_left_alone(conn, github, monkeypatch):
    """The UPDATE itself carries `AND head_sha IS NULL`, so even a race cannot overwrite."""
    real = bf.RunsAPI.head_sha

    def racing(self, owner, repo, run_id):
        out = real(self, owner, repo, run_id)
        if run_id == RUN_NULL_SYNC:
            conn.cursor().execute("UPDATE raw_workflow_runs SET head_sha=%s WHERE run_id=%s",
                                  (OLD_SHA, run_id))      # someone else fills it first
        return out

    monkeypatch.setattr(bf.RunsAPI, "head_sha", racing)
    res = run_backfill(conn, apply=True)
    assert heads(conn)[RUN_NULL_SYNC] == OLD_SHA          # the other writer's value stands
    assert res.lost_race == 1 and res.filled == 1


def test_reports_which_filled_runs_are_sync_triggered(conn, github, capsys):
    res = run_backfill(conn, apply=True)
    assert res.sync_hits == [RUN_NULL_SYNC]               # RUN_NULL_WORK's commit is "my work"
    assert "sync-triggered (rule b)  : 1" in capsys.readouterr().out


def test_candidate_repos_put_the_runs_own_assignment_first_without_duplicates():
    assert bf.candidate_repos(STUDENT, ASSIGNMENT, ROSTER) == [("o", "repo-a"), ("o", "repo-b")]
    assert bf.candidate_repos(STUDENT, "_other", ROSTER) == [("o", "repo-b"), ("o", "repo-a")]
    assert bf.candidate_repos(STUDENT, None, ROSTER) == [("o", "repo-a"), ("o", "repo-b")]
    assert bf.candidate_repos("nobody", None, ROSTER) == []


def test_token_never_reaches_the_output_even_if_the_server_echoes_it(conn, monkeypatch, capsys):
    monkeypatch.setattr(bf.requests, "request", FakeActions({}, fail_with=500))
    res = run_backfill(conn, apply=False)
    cap = capsys.readouterr()
    assert res.errors and TOKEN not in cap.out + cap.err
    assert "HTTP 500" in cap.out and heads(conn)[RUN_NULL_SYNC] is None


def test_a_malformed_payload_is_an_error_not_a_write(conn, monkeypatch):
    class Bad(FakeActions):
        def __call__(self, method, url, headers=None, timeout=None, **kw):
            run_id = int(url.rsplit("/", 1)[1])
            return Resp(200, {"id": run_id, "head_sha": "not-a-sha"})

    monkeypatch.setattr(bf.requests, "request", Bad({}))
    res = run_backfill(conn, apply=True)
    assert res.errors and res.filled == 0 and heads(conn)[RUN_NULL_SYNC] is None


def test_cli_dry_run_is_default_and_rolls_back(conn, github, monkeypatch, capsys):
    monkeypatch.setattr(bf, "_load_token", lambda: TOKEN)
    monkeypatch.setattr(bf, "load_roster", lambda: ROSTER)

    commits: list[int] = []

    class Borrowed:
        """The fixture owns the connection and its uncommitted seed rows, so main()'s
        rollback/close are no-ops here; commit is recorded to prove a dry-run never commits."""
        cursor = staticmethod(conn.cursor)
        commit = staticmethod(lambda: commits.append(1))
        rollback = staticmethod(lambda: None)
        close = staticmethod(lambda: None)

    monkeypatch.setattr(bf.db, "_open", lambda: Borrowed)
    assert bf.main(["--student", STUDENT]) == 0
    cap = capsys.readouterr()
    assert "DRY-RUN" in cap.out and TOKEN not in cap.out + cap.err
    assert heads(conn)[RUN_NULL_SYNC] is None and commits == []
