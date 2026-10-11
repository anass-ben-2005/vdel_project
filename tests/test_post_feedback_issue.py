"""D-089 -- scripts/post_feedback.py issue mode, with a mocked GitHub (no network anywhere).

Two kinds of fake: an in-memory `FakeGH` standing in for `publish_repo.GitHub` (to test the
posting logic), and a fake `requests.request` under the REAL `GitHub` class (to test the status
mapping and the exact HTTP calls). Test database, one rolled-back transaction per test."""

from __future__ import annotations

import os

import pytest

from scripts import post_feedback as pf
from scripts import publish_repo as pr
from system import db
from tests.support import ensure_variant

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

S, ASG, USER = "_fbi_student", "weather_etl_extract", "octo-student"
SHA1, SHA2 = "1" * 40, "2" * 40
T_RETRY = "tests/hidden/test_extract.py::test_fetch_weather_retries_then_succeeds"
T_PARSE = "tests/hidden/test_extract.py::test_parse_response_missing_key_returns_none"
REPO_FOR = {(S, ASG): ("own", "rep")}
TITLE = "VDEL feedback - weather_etl_extract - attempt 1"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Anything that reaches the real HTTP layer fails the test; tests that want HTTP install
    their own fake over `requests.request`."""
    def boom(*a, **k):
        raise AssertionError("a test reached the network")

    monkeypatch.setattr(pr.requests, "request", boom)
    monkeypatch.setattr(pr.requests, "post", boom)
    monkeypatch.delenv(pf.GITHUB_WRITE_ENV_VAR, raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token-value")


@pytest.fixture
def world(monkeypatch):
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, USER))
    variant = ensure_variant(cur, ASG)
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl',%s,1,%s,1) RETURNING attempt_id",
                (S, ASG, variant))
    attempt_id = cur.fetchone()[0]
    for i, sha in enumerate((SHA1, SHA2)):
        cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                    " VALUES (%s,%s,%s,%s)", (sha, S, ASG, f"2026-08-25 0{i + 1}:00+00"))
    yield conn, cur, attempt_id
    conn.rollback()
    conn.close()


def result(cur, attempt_id, sha, name, gap, passed, message=None, status="ok"):
    cur.execute("INSERT INTO test_results (attempt_id, commit_sha, test_name, gap_id, passed,"
                " message, status) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (attempt_id, sha, name, gap, passed, message, status))


class FakeGH:
    """Stands in for publish_repo.GitHub; records every call."""

    def __init__(self, *, existing_issue=None, comments=(), fail=None):
        self.calls = []
        self.existing_issue = existing_issue
        self.comments = list(comments)
        self.fail = fail                     # a GitHubHTTPError raised by the first write
        self.next_issue = 7

    def find_issue(self, owner, repo, title, **kw):
        self.calls.append(("find_issue", owner, repo, title))
        return self.existing_issue

    def create_issue(self, owner, repo, title, body):
        self.calls.append(("create_issue", owner, repo, title, body))
        if self.fail:
            raise self.fail
        return {"number": self.next_issue, "html_url": f"https://x/{owner}/{repo}/issues/7"}

    def issue_comments(self, owner, repo, number, **kw):
        self.calls.append(("issue_comments", number))
        return self.comments

    def create_issue_comment(self, owner, repo, number, body):
        self.calls.append(("create_issue_comment", number, body))
        if self.fail:
            raise self.fail
        self.comments.append({"body": body})
        return {"html_url": f"https://x/{owner}/{repo}/issues/{number}#c{len(self.comments)}"}

    def names(self):
        return [c[0] for c in self.calls]


def plan(cur, attempt_id, sha):
    return pf.plan_issue_post(cur, attempt_id, sha, REPO_FOR)


def graded(world):
    _, cur, aid = world
    result(cur, aid, SHA1, T_RETRY, "g_ext_retry", False, "AssertionError: assert 32.0 == f(0)")
    result(cur, aid, SHA1, T_PARSE, "g_ext_parse", True)
    result(cur, aid, SHA2, T_RETRY, "g_ext_retry", True)
    result(cur, aid, SHA2, T_PARSE, "g_ext_parse", True)
    return aid


@pytest.fixture
def apply_env(monkeypatch):
    monkeypatch.setenv(pf.GITHUB_WRITE_ENV_VAR, "1")


# --- the text and the dry-run -----------------------------------------------------------------

def test_the_comment_mentions_the_student_carries_the_marker_and_no_assertion_text(world):
    _, cur, _ = world
    aid = graded(world)
    p = plan(cur, aid, SHA1)
    assert p.title == TITLE and (p.owner, p.repo) == ("own", "rep")
    assert p.comment_body.startswith(f"@{USER}\n\n### VDEL feedback:")
    assert pf.comment_marker(aid, SHA1) in p.comment_body
    assert "32.0" not in p.comment_body and "f(0)" not in p.comment_body   # D-077
    assert "AssertionError" in p.comment_body                              # the type is shown
    for line in pf.hidden_source_lines("weather_etl"):
        assert line not in p.comment_body


def test_a_dry_run_makes_no_call_and_writes_no_row(world):
    _, cur, _ = world
    aid = graded(world)
    gh = FakeGH()
    out = pf.post_issue_feedback(cur, plan(cur, aid, SHA1), apply=False, gh=gh)
    assert out.status == "dry_run" and gh.calls == []
    cur.execute("SELECT count(*) FROM feedback_issues")
    assert cur.fetchone()[0] == 0
    calls = pf.describe_calls(plan(cur, aid, SHA1))
    assert any(c.startswith("POST") and c.endswith("/issues   title='" + TITLE + "'   "
                                                     "(only if none was found)") for c in calls)


def test_apply_without_the_environment_flag_raises_before_any_call(world):
    _, cur, _ = world
    aid = graded(world)
    gh = FakeGH()
    with pytest.raises(pf.GitHubWriteNotEnabled):
        pf.post_issue_feedback(cur, plan(cur, aid, SHA1), apply=True, gh=gh)
    assert gh.calls == []
    with pytest.raises(pf.GitHubWriteNotEnabled):
        pf.require_github_write(False)


# --- posting ------------------------------------------------------------------------------------

def test_the_issue_is_created_once_and_reused_for_the_next_commit(world, apply_env):
    _, cur, aid = world
    graded(world)
    gh = FakeGH()
    first = pf.post_issue_feedback(cur, plan(cur, aid, SHA1), apply=True, gh=gh)
    second = pf.post_issue_feedback(cur, plan(cur, aid, SHA2), apply=True, gh=gh)
    assert (first.status, second.status) == ("posted", "posted")
    assert gh.names().count("create_issue") == 1 and gh.names().count("find_issue") == 1
    assert gh.names().count("create_issue_comment") == 2
    cur.execute("SELECT owner, repo, issue_number FROM feedback_issues WHERE attempt_id = %s",
                (aid,))
    assert cur.fetchall() == [("own", "rep", 7)]
    cur.execute("SELECT commit_sha, channel FROM feedback_posts WHERE attempt_id = %s"
                " ORDER BY commit_sha", (aid,))
    assert cur.fetchall() == [(SHA1, pf.ISSUE_CHANNEL), (SHA2, pf.ISSUE_CHANNEL)]


def test_a_second_run_posts_nothing(world, apply_env):
    _, cur, aid = world
    graded(world)
    gh = FakeGH()
    for sha in (SHA1, SHA2):
        pf.post_issue_feedback(cur, plan(cur, aid, sha), apply=True, gh=gh)
    before = list(gh.calls)
    assert pf.unposted_commits(cur, S) == []
    again = pf.post_issue_feedback(cur, plan(cur, aid, SHA1), apply=True, gh=gh)
    assert again.status == "skipped" and gh.calls == before


def test_an_existing_issue_with_the_title_is_reused_not_duplicated(world, apply_env):
    _, cur, aid = world
    graded(world)
    gh = FakeGH(existing_issue={"number": 3, "html_url": "https://x/3", "title": TITLE})
    out = pf.post_issue_feedback(cur, plan(cur, aid, SHA1), apply=True, gh=gh)
    assert out.status == "posted" and out.issue_number == 3
    assert "create_issue" not in gh.names()


def test_a_comment_already_on_github_is_recognised_by_its_marker(world, apply_env):
    """The crash window: GitHub has the comment, the database does not."""
    _, cur, aid = world
    graded(world)
    marker = pf.comment_marker(aid, SHA1)
    gh = FakeGH(existing_issue={"number": 3}, comments=[{"body": "x\n" + marker,
                                                          "html_url": "https://x/c"}])
    out = pf.post_issue_feedback(cur, plan(cur, aid, SHA1), apply=True, gh=gh)
    assert out.status == "recovered" and "create_issue_comment" not in gh.names()
    assert pf.unposted_commits(cur, S) == [(aid, SHA2)]


def test_a_placeholder_username_is_refused_and_nothing_is_contacted(world, apply_env,
                                                                    monkeypatch):
    _, cur, aid = world
    graded(world)
    cur.execute("UPDATE students SET github_username = 'student2-placeholder-local-render-only'"
                " WHERE student_id = %s", (S,))
    monkeypatch.setattr(pf, "GitHub", lambda token: (_ for _ in ()).throw(
        AssertionError("a client was built for a refused post")))
    p = plan(cur, aid, SHA1)
    assert p.refused and "placeholder" in p.problems[0]
    out = pf.post_issue_feedback(cur, p, apply=True)
    assert out.status == "refused"
    cur.execute("SELECT count(*) FROM feedback_posts")
    assert cur.fetchone()[0] == 0


def test_which_usernames_count_as_placeholders():
    for bad in (None, "", "_test_runner", "CHANGE_ME", "student2-placeholder-local-render-only",
                "has space", "-leading", "trailing-", "x" * 40):
        assert pf.is_placeholder_username(bad), bad
    for good in ("anass-ben-2005", "octo-student", "a", "Ab1"):
        assert not pf.is_placeholder_username(good), good


def test_a_missing_roster_entry_is_refused(world, apply_env):
    _, cur, aid = world
    graded(world)
    p = pf.plan_issue_post(cur, aid, SHA1, {})
    assert p.refused and "roster" in p.problems[0]
    assert pf.post_issue_feedback(cur, p, apply=True).status == "refused"


@pytest.mark.parametrize("status, needle", [(403, "forbidden"), (404, "not found"),
                                            (410, "disabled"), (422, "validation failed")])
def test_github_errors_end_as_a_failed_outcome_and_write_no_row(world, apply_env, status,
                                                                 needle):
    _, cur, aid = world
    graded(world)
    gh = FakeGH(fail=pr.GitHubHTTPError(status, f"creating: {needle}"))
    out = pf.post_issue_feedback(cur, plan(cur, aid, SHA1), apply=True, gh=gh)
    assert out.status == "failed" and str(status) in out.detail and needle in out.detail
    cur.execute("SELECT (SELECT count(*) FROM feedback_posts),"
                " (SELECT count(*) FROM feedback_issues WHERE attempt_id = %s)", (aid,))
    posts, issues = cur.fetchone()
    assert posts == 0 and issues == 0


# --- the real GitHub class under a fake HTTP layer ------------------------------------------------

class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


def install(monkeypatch, responses):
    calls = []

    def fake(method, url, **kw):
        calls.append((method, url, kw.get("json"), kw.get("params"),
                      kw.get("headers", {}).get("Authorization")))
        return responses.pop(0)

    monkeypatch.setattr(pr.requests, "request", fake)
    return calls


def test_the_real_client_sends_the_expected_requests(monkeypatch):
    calls = install(monkeypatch, [
        Resp(200, [{"title": "other", "number": 1}, {"title": TITLE, "number": 5,
                                                      "pull_request": {}},
                   {"title": TITLE, "number": 6}]),
        Resp(201, {"number": 9, "html_url": "u"}),
        Resp(200, [{"body": "a"}]),
        Resp(201, {"html_url": "c"}),
    ])
    gh = pr.GitHub("tok")
    assert gh.find_issue("own", "rep", TITLE)["number"] == 6         # the PR is skipped
    assert gh.create_issue("own", "rep", TITLE, "intro")["number"] == 9
    assert gh.issue_comments("own", "rep", 9) == [{"body": "a"}]
    assert gh.create_issue_comment("own", "rep", 9, "hello")["html_url"] == "c"
    assert [(c[0], c[1].replace("https://api.github.com", "")) for c in calls] == [
        ("GET", "/repos/own/rep/issues"), ("POST", "/repos/own/rep/issues"),
        ("GET", "/repos/own/rep/issues/9/comments"),
        ("POST", "/repos/own/rep/issues/9/comments")]
    assert calls[1][2] == {"title": TITLE, "body": "intro"} and calls[3][2] == {"body": "hello"}
    assert all(c[4] == "Bearer tok" for c in calls)


@pytest.mark.parametrize("response, status, needle", [
    (Resp(403, {"message": "Resource not accessible"}), 403, "forbidden"),
    (Resp(403, {"message": "rate"}, {"X-RateLimit-Remaining": "0"}), 403, "rate limit"),
    (Resp(404, {"message": "Not Found"}), 404, "not found"),
    (Resp(410, {"message": "gone"}), 410, "disabled"),
    (Resp(422, {"message": "Validation Failed"}), 422, "validation failed"),
    (Resp(500, None), 500, "creating"),
])
def test_the_real_client_maps_error_statuses(monkeypatch, response, status, needle):
    install(monkeypatch, [response])
    with pytest.raises(pr.GitHubHTTPError) as err:
        pr.GitHub("tok").create_issue("own", "rep", TITLE, "b")
    assert err.value.status == status and needle in err.value.reason


def test_the_token_is_never_in_an_error_or_an_outcome(world, apply_env, monkeypatch):
    _, cur, aid = world
    graded(world)
    install(monkeypatch, [Resp(404, {"message": "Not Found"})])
    out = pf.post_issue_feedback(cur, plan(cur, aid, SHA1), apply=True)   # real client, fake HTTP
    assert out.status == "failed"
    assert "secret-token-value" not in repr(out)


# --- the command ----------------------------------------------------------------------------------

class KeepOpen:
    """The fixture owns the connection; the command may rollback but must not close it."""

    def __init__(self, real):
        self.real = real

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self.real, name)


def test_the_cli_dry_run_prints_the_calls_and_the_text(world, monkeypatch, tmp_path, capsys):
    conn = world[0]
    graded(world)
    roster = tmp_path / "roster.yaml"
    roster.write_text(
        "assignments:\n"
        f"  - assignment_id: {ASG}\n    owner: own\n    repo: rep\n    student_id: {S}\n",
        encoding="utf-8")
    monkeypatch.setattr(pf.db, "_open", lambda: KeepOpen(conn))
    assert pf.main(["--student", S, "--issue", "--roster", str(roster)]) == 0
    out = capsys.readouterr().out
    assert "[DRY-RUN]" in out and f"@{USER}" in out and TITLE in out
    assert "POST /repos/own/rep" in out
    assert "secret-token-value" not in out


def test_the_cli_refuses_apply_without_the_flag_before_opening_the_database(monkeypatch,
                                                                            capsys):
    def boom():
        raise AssertionError("the database was opened although the write was refused")

    monkeypatch.setattr(pf.db, "_open", boom)
    assert pf.main(["--student", S, "--issue", "--apply"]) == 2
    assert "REFUSED" in capsys.readouterr().out


def test_a_database_without_the_feedback_tables_is_refused_before_any_github_call(world,
                                                                               apply_env):
    _, cur, aid = world
    graded(world)
    cur.execute("DROP TABLE feedback_issues")               # transactional DDL, rolled back
    p = plan(cur, aid, SHA1)
    assert p.refused and "init_db" in p.problems[0]
    gh = FakeGH()
    assert pf.post_issue_feedback(cur, p, apply=True, gh=gh).status == "refused"
    assert gh.calls == []
