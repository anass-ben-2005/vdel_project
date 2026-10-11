"""D-090 -- scripts/deliver_next_attempt.py: the delivery chain of attempt N+1, with a mocked GitHub
(a local bare repository for the push; an in-memory fake for the API). No network. Test database,
one rolled-back transaction per test (traces and attempts cannot be deleted)."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from scripts import deliver_next_attempt as dna
from scripts import grade_collected as gc
from scripts import publish_repo as pr
from scripts.post_feedback import GITHUB_WRITE_ENV_VAR
from scripts.render_student_repo import render_student_repo
from system import db
from tests.support import ensure_variant

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

S, ASG, USER, PROJECT = "_dlv_student", "weather_etl_extract", "octo-student", "weather_etl"
OLD_REPO = "vdel-weather-etl-gapfill-" + S
NEW_REPO = f"{OLD_REPO}-extract-attempt2"
ROSTER_TEXT = (
    "students:\n"
    f"  - student_id: {S}\n    github_username: {USER}\n    cohort: vdel-2026\n"
    "assignments:\n"
    f"  - assignment_id: {ASG}\n    owner: owner1\n    repo: {OLD_REPO}\n"
    f"    student_id: {S}\n    released_at: 2026-08-25T00:00:00Z\n    due_at: null\n"
    "    concepts: []\n"
)


def _git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a test reached the network")

    monkeypatch.setattr(pr.requests, "request", boom)
    monkeypatch.delenv(GITHUB_WRITE_ENV_VAR, raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token-value")


@pytest.fixture
def git_identity():
    if not all(_git("config", k).stdout.strip() for k in ("user.name", "user.email")):
        pytest.skip("git user.name/user.email not configured")


class FakeGH:
    """publish_repo.GitHub + the issue / collaborator calls, over local bare repositories."""

    def __init__(self, tmp_path, *, fail_create=False):
        self.tmp_path = tmp_path
        self.fail_create = fail_create
        self.created, self.invited, self.comments, self.issues = [], [], [], []
        self.repos: dict[tuple, str] = {}

    def _bare(self, owner, repo):
        return self.tmp_path / "remote" / owner / f"{repo}.git"

    def whoami(self):
        return "owner1", {"repo", "workflow"}

    def repo_state(self, owner, repo):
        if (owner, repo) not in self.repos:
            return "missing"
        has = _git("--git-dir", str(self._bare(owner, repo)), "rev-parse", "main").returncode == 0
        return "has_commits" if has else "empty"

    def create_repo(self, owner, repo, *, login, private, description):
        if self.fail_create:
            raise pr.GitHubHTTPError(403, "creating: forbidden")
        self.created.append((owner, repo, private))
        self.repos[(owner, repo)] = "empty"
        bare = self._bare(owner, repo)
        bare.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)

    def head_sha(self, owner, repo, branch):
        done = _git("--git-dir", str(self._bare(owner, repo)), "rev-parse", branch)
        return done.stdout.strip() or None

    def invite_collaborator(self, owner, repo, username, permission="push"):
        again = (owner, repo, username) in self.invited
        self.invited.append((owner, repo, username))
        return "already" if again else "invited"

    def find_issue(self, owner, repo, title, **kw):
        return next((i for i in self.issues if i["title"] == title), None)

    def create_issue(self, owner, repo, title, body):
        issue = {"number": 7, "title": title, "html_url": "https://x/7"}
        self.issues.append(issue)
        return issue

    def issue_comments(self, owner, repo, number, **kw):
        return [{"body": b} for _, _, n, b in self.comments if n == number]

    def create_issue_comment(self, owner, repo, number, body):
        self.comments.append((owner, repo, number, body))
        return {"html_url": "https://x/c"}


@pytest.fixture
def world(tmp_path):
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, USER))
    variant = ensure_variant(cur, ASG)
    cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                " VALUES ('dlv_sha_1', %s, %s, '2026-08-25 01:00+00')", (S, ASG))
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed, commit_sha, submitted_at, tests_passed, tests_total)"
                " VALUES (%s,%s,%s,1,%s,1,'dlv_sha_1','2026-08-25 01:00+00',4,4)"
                " RETURNING attempt_id", (S, PROJECT, ASG, variant))
    attempt_id = cur.fetchone()[0]
    roster = tmp_path / "roster.yaml"
    roster.write_text(ROSTER_TEXT, encoding="utf-8")
    yield conn, cur, attempt_id, roster, tmp_path
    conn.rollback()
    conn.close()


def go(world, gh=None, **kw):
    conn, _, _, roster, tmp_path = world
    lines: list[str] = []
    kw.setdefault("apply", False)
    code = dna.run(student=S, assignment=ASG, roster_path=roster, gh=gh,
                   remote_base=(tmp_path / "remote").as_uri(), conn=conn, out=lines.append, **kw)
    return code, "\n".join(lines)


def count(cur, table="attempts"):
    cur.execute(f"SELECT count(*) FROM {table} WHERE student_id = %s", (S,))
    return cur.fetchone()[0]


# --- the rules ----------------------------------

def test_the_repo_name_carries_the_stage_so_two_stages_never_collide():
    assert dna.delivery_repo_name("weather_etl", "s", "weather_etl_extract", 2) == \
        "vdel-weather-etl-gapfill-s-extract-attempt2"
    assert dna.delivery_repo_name("weather_etl", "s", "weather_etl_load", 2) != \
        dna.delivery_repo_name("weather_etl", "s", "weather_etl_extract", 2)


def test_a_current_attempt_that_is_not_frozen_is_refused(world):
    _, cur, aid, _, _ = world
    cur.execute("UPDATE attempts SET submitted_at = NULL, commit_sha = NULL WHERE attempt_id = %s",
                (aid,))
    code, out = go(world)
    assert code == 2 and "REFUSED" in out and "still open" in out
    code, out = go(world, apply=True)
    assert code == 2


def test_force_is_refused_without_i_understand_and_allowed_with_it(world):
    _, cur, aid, _, _ = world
    cur.execute("UPDATE attempts SET submitted_at = NULL, commit_sha = NULL WHERE attempt_id = %s",
                (aid,))
    code, out = go(world, force=True)
    assert code == 2 and "--i-understand" in out and "closed_at" in out
    code, out = go(world, force=True, i_understand=True)
    assert code == 0 and "FORCED" in out                       # the dry-run goes through


def test_a_placeholder_username_is_shown_in_the_dry_run_and_refused_on_apply(world, monkeypatch):
    _, cur, _, _, _ = world
    cur.execute("UPDATE students SET github_username = 'student2-placeholder-local-render-only'"
                " WHERE student_id = %s", (S,))
    code, out = go(world)
    assert code == 0 and "WOULD REFUSE" in out and "placeholder" in out
    monkeypatch.setenv(GITHUB_WRITE_ENV_VAR, "1")
    code, out = go(world, apply=True)
    assert code == 2 and "REFUSED" in out and "placeholder" in out


def test_apply_without_the_environment_flag_is_refused_before_anything_happens(world):
    _, cur, _, _, _ = world
    before = count(cur)
    code, out = go(world, apply=True)
    assert code == 2 and GITHUB_WRITE_ENV_VAR in out
    assert count(cur) == before


# --- the dry-run ----------------------------------

def test_the_dry_run_records_nothing_contacts_nothing_and_prints_the_plan(world, git_identity):
    _, cur, _, roster, _ = world
    before = roster.read_text(encoding="utf-8")
    code, out = go(world)
    assert code == 0
    assert count(cur) == 1                                         # no attempt 2
    assert NEW_REPO in out and "(private)" in out
    assert f"PUT  /repos/owner1/{NEW_REPO}/collaborators/{USER}" in out
    assert f"@{USER} attempt 1 of `{ASG}` is complete." in out
    assert f"https://github.com/owner1/{NEW_REPO}" in out
    assert "update weather_etl_extract -> owner1/" + NEW_REPO in out    # the roster rows to add
    assert "DRY-RUN: nothing was created" in out
    assert roster.read_text(encoding="utf-8") == before            # never edited
    assert "secret-token-value" not in out


# --- the real run (fake GitHub) ----------------------------------

def test_the_real_run_delivers_attempt_2_and_never_edits_the_roster(world, git_identity,
                                                                    monkeypatch):
    _, cur, old_attempt, roster, tmp_path = world
    monkeypatch.setenv(GITHUB_WRITE_ENV_VAR, "1")
    before = roster.read_text(encoding="utf-8")
    gh = FakeGH(tmp_path)
    code, out = go(world, gh, apply=True)
    assert code == 0, out
    # the attempt exists, stamped with its start
    cur.execute("SELECT attempt_no, started_at IS NOT NULL FROM attempts WHERE student_id = %s"
                " AND assignment_id = %s ORDER BY attempt_no", (S, ASG))
    assert cur.fetchall() == [(1, False), (2, True)]
    # a private repo with only this stage's file, no hidden test
    assert gh.created == [("owner1", NEW_REPO, True)]
    files = _git("--git-dir", str(gh._bare("owner1", NEW_REPO)), "ls-tree", "-r",
                 "--name-only", "main").stdout.split()
    assert "weather_etl/extract.py" in files and "weather_etl/load.py" not in files
    assert not [f for f in files if "hidden" in f.split("/")]
    # the student is invited, and the old attempt's issue gets the link
    assert gh.invited == [("owner1", NEW_REPO, USER)]
    ((owner, repo, number, body),) = gh.comments
    assert (owner, repo) == ("owner1", OLD_REPO) and f"https://github.com/owner1/{NEW_REPO}" in body
    cur.execute("SELECT owner, repo, issue_number FROM feedback_issues WHERE attempt_id = %s",
                (old_attempt,))
    assert cur.fetchall() == [("owner1", OLD_REPO, number)]
    # the roster is PRINTED, not written
    assert "roster rows to add by hand" in out and NEW_REPO in out
    assert roster.read_text(encoding="utf-8") == before


def test_the_owner_of_the_repositories_is_not_invited_to_their_own_repo(world, git_identity,
                                                                         monkeypatch):
    """The trusted student may own the repos: GitHub refuses that invitation."""
    _, cur, _, _, tmp_path = world
    monkeypatch.setenv(GITHUB_WRITE_ENV_VAR, "1")
    cur.execute("UPDATE students SET github_username = 'OWNER1' WHERE student_id = %s", (S,))
    code, out = go(world, apply=False)
    assert code == 0 and "owns the repository" in out and "PUT" not in out
    gh = FakeGH(tmp_path)
    code, out = go(world, gh, apply=True)
    assert code == 0, out
    assert gh.invited == [] and gh.created == [("owner1", NEW_REPO, True)]
    assert len(gh.comments) == 1


def test_a_failure_in_publish_can_be_finished_with_resume_and_is_idempotent(world, git_identity,
                                                                            monkeypatch):
    _, cur, _, _, tmp_path = world
    monkeypatch.setenv(GITHUB_WRITE_ENV_VAR, "1")
    broken = FakeGH(tmp_path, fail_create=True)
    code, out = go(world, broken, apply=True)
    assert code == 1 and "--resume" in out and "forbidden" in out
    assert count(cur) == 2                                          # attempt 2 was recorded

    # without --resume the unfinished attempt blocks a new start (it is open)
    code, out = go(world, FakeGH(tmp_path), apply=True)
    assert code == 2

    gh = FakeGH(tmp_path)
    code, out = go(world, gh, apply=True, resume=True)
    assert code == 0, out
    assert count(cur) == 2 and gh.created == [("owner1", NEW_REPO, True)]
    assert len(gh.comments) == 1

    again = FakeGH(tmp_path)
    again.repos = dict(gh.repos)
    again.issues, again.comments = list(gh.issues), list(gh.comments)
    code, out = go(world, again, apply=True, resume=True)
    assert code == 0 and "already has commits; skipped" in out
    assert again.created == [] and len(again.comments) == 1         # nothing new
    assert "skipped" in out


def test_resume_refuses_an_attempt_that_already_has_graded_work(world, monkeypatch):
    _, cur, _, _, _ = world
    monkeypatch.setenv(GITHUB_WRITE_ENV_VAR, "1")
    variant = ensure_variant(cur, ASG)
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,%s,%s,2,%s,1) RETURNING attempt_id",
                (S, PROJECT, ASG, variant))
    a2 = cur.fetchone()[0]
    cur.execute("INSERT INTO test_results (attempt_id, commit_sha, test_name, gap_id, passed)"
                " VALUES (%s,'dlv_sha_1','t','g_ext_retry',true)", (a2,))
    code, out = go(world, resume=True)
    assert code == 2 and "not an undelivered attempt" in out


# --- attempts.started_at: what makes the grading of attempt 2 possible ---------------

def test_a_new_attempt_is_stamped_once_and_a_re_render_does_not_move_it(world, tmp_path):
    conn, cur, _, _, _ = world
    render_student_repo(PROJECT, S, 2, tmp_path / "r1", conn=conn, only_assignment=ASG)
    cur.execute("SELECT started_at FROM attempts WHERE student_id = %s AND attempt_no = 2", (S,))
    first = cur.fetchone()[0]
    assert first is not None
    cur.execute("UPDATE attempts SET started_at = %s WHERE student_id = %s AND attempt_no = 2",
                (first - timedelta(days=1), S))
    render_student_repo(PROJECT, S, 2, tmp_path / "r2", conn=conn, only_assignment=ASG)
    cur.execute("SELECT started_at FROM attempts WHERE student_id = %s AND attempt_no = 2", (S,))
    assert cur.fetchone()[0] == first - timedelta(days=1)             # untouched
    cur.execute("SELECT started_at FROM attempts WHERE student_id = %s AND attempt_no = 1", (S,))
    assert cur.fetchone()[0] is None                                   # old rows keep NULL


def test_commits_older_than_the_attempt_are_not_pending_for_it(world):
    _, cur, _, _, _ = world
    variant = ensure_variant(cur, ASG)
    now = datetime.now(UTC)
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed, started_at) VALUES (%s,%s,%s,2,%s,1,%s)",
                (S, PROJECT, ASG, variant, now))
    for sha, when in (("dlv_old", now - timedelta(days=2)), ("dlv_new", now + timedelta(hours=1))):
        cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                    " VALUES (%s,%s,%s,%s)", (sha, S, ASG, when))
    pending, _ = gc.find_pending(cur, {(S, ASG): ("o", "r")}, student=S)
    assert [p.sha for p in pending if p.attempt_no == 2] == ["dlv_new"]


def test_an_attempt_without_a_start_keeps_the_old_behaviour(world):
    _, cur, aid, _, _ = world
    cur.execute("UPDATE attempts SET submitted_at = NULL, commit_sha = NULL WHERE attempt_id = %s",
                (aid,))
    cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                " VALUES ('dlv_any', %s, %s, '2020-01-01 00:00+00')", (S, ASG))
    pending, _ = gc.find_pending(cur, {(S, ASG): ("o", "r")}, student=S)
    assert {p.sha for p in pending} == {"dlv_sha_1", "dlv_any"}


def test_the_filter_is_fail_open_when_the_column_does_not_exist(world):
    _, cur, aid, _, _ = world
    cur.execute("UPDATE attempts SET submitted_at = NULL, commit_sha = NULL WHERE attempt_id = %s",
                (aid,))
    cur.execute("ALTER TABLE attempts DROP COLUMN started_at")        # transactional, rolled back
    pending, _ = gc.find_pending(cur, {(S, ASG): ("o", "r")}, student=S)
    assert [p.sha for p in pending] == ["dlv_sha_1"]
