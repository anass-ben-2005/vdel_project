"""scripts/sync_template.py (D-062) -- HTTP mocked, no network, no database.

The fake GitHub below enforces the same rule the real Contents API does (a PUT over an
existing file must carry that file's current blob sha, else 409), so the tests check the
tool against the behaviour it relies on, not against its own assumptions.
"""

from __future__ import annotations

import base64
import hashlib

import pytest

from scripts import render_student_repo as rsr
from scripts import sync_template as st

CI = ".github/workflows/ci.yml"
CONFTEST = "conftest.py"
TOKEN = "ghp_SECRET_TOKEN_must_never_be_printed_0123456789"
OLD_CI = (
    "name: ci\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
    "      - uses: actions/checkout@v4\n      - run: pip install -r requirements.txt\n"
    "      - run: ruff check .\n      - run: pytest tests/visible\n"
)


def blob_sha(content: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        return self._body


class FakeGitHub:
    """files: {path: bytes}. Records every call as (method, path)."""

    def __init__(self, files=None, *, scopes="repo, workflow", put_error_on=None,
                 echo_token_in_error=False, runs=True):
        self.files = dict(files or {})
        self.calls: list[tuple[str, str]] = []
        self.puts: list[dict] = []
        self.scopes, self.put_error_on, self.runs = scopes, put_error_on, runs
        self.echo_token = echo_token_in_error
        self.commits = 0

    def __call__(self, method, url, headers=None, timeout=None, params=None, json=None):
        path = url.removeprefix(st.GH_API)
        self.calls.append((method, path))
        assert headers["Authorization"] == f"Bearer {TOKEN}"
        if path == "/user":
            return Resp(200, {"login": "x"}, {"X-OAuth-Scopes": self.scopes})
        if path.endswith("/actions/runs"):
            sha = params["head_sha"]
            body = {"workflow_runs": [{"html_url": f"https://github.com/o/r/actions/runs/{sha}"}]}
            return Resp(200, body if self.runs else {"workflow_runs": []})
        if "/contents/" in path:
            fpath = path.split("/contents/", 1)[1]
            if method == "GET":
                if fpath not in self.files:
                    return Resp(404, {"message": "Not Found"})
                data = self.files[fpath]
                return Resp(200, {"type": "file", "encoding": "base64", "sha": blob_sha(data),
                                  "content": base64.b64encode(data).decode()})
            self.puts.append({"path": fpath, **json})
            if self.put_error_on == fpath:
                msg = f"boom for {TOKEN}" if self.echo_token else "conflict"
                return Resp(409, {"message": msg})
            if fpath in self.files:
                if json.get("sha") != blob_sha(self.files[fpath]):
                    return Resp(409, {"message": "sha does not match"})
            elif "sha" in json:
                return Resp(422, {"message": "sha supplied for a new file"})
            self.files[fpath] = base64.b64decode(json["content"])
            self.commits += 1
            commit = {"commit": {"sha": f"c0mm17{self.commits:034d}"}}
            return Resp(200 if "sha" in json else 201, commit)
        if path.count("/") == 3:                                # /repos/o/r
            return Resp(200, {"default_branch": "main"})
        raise AssertionError(f"unexpected call {method} {path}")


@pytest.fixture
def gh(monkeypatch):
    def install(**kw):
        fake = FakeGitHub(**kw)
        monkeypatch.setattr(st.requests, "request", fake)
        return fake
    return install


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(st, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setattr(st, "load_roster", lambda: {"assignments": [
        {"owner": "o", "repo": "r", "student_id": "anas", "assignment_id": "a1"}]})


def client():
    return st.Contents(TOKEN)


def run_dry(fake_files, capsys, gh):
    fake = gh(files=fake_files)
    states = st.dry_run(client(), "o", "r", "main", st._Out(TOKEN), student=None)
    return fake, states, capsys.readouterr().out


# --- single source of truth -----------------------------------------------------------------

def test_allowlist_is_exactly_the_renderers_template_files():
    assert st.TEMPLATE_FILES is rsr.TEMPLATE_FILES
    assert sorted(st.TEMPLATE_FILES) == [CI, CONFTEST]
    assert rsr.TEMPLATE_FILES[CI] is rsr._CI_WORKFLOW
    assert rsr.TEMPLATE_FILES[CONFTEST] is rsr._ROOT_CONFTEST


# --- dry-run --------------------------------------------------------------------------------

def test_dry_run_diff_is_correct_and_sends_only_gets(gh, capsys):
    fake, _, out = run_dry({CI: OLD_CI.encode()}, capsys, gh)
    assert {m for m, _ in fake.calls} == {"GET"} and not fake.puts
    assert f"== {CI}: differs" in out and f"== {CONFTEST}: missing" in out
    assert "-      - run: pytest tests/visible" in out
    assert "+      - run: python -m pytest tests/visible" in out
    assert "+      - run: pip install ruff pytest" in out
    assert "+        continue-on-error: true" in out
    # the exact apply command carries the SHAs just observed, and `missing` for the new file
    assert f"--confirm-sha {CI}={blob_sha(OLD_CI.encode())}" in out
    assert f"--confirm-sha {CONFTEST}=missing" in out


def test_identical_files_are_reported_and_nothing_is_offered(gh, capsys):
    files = {p: t.encode() for p, t in st.TEMPLATE_FILES.items()}
    _, states, out = run_dry(files, capsys, gh)
    assert [s.status for s in states] == ["identical", "identical"]
    assert out.count("identical") >= 2 and "Nothing to apply" in out
    assert "--confirm-sha" not in out


def test_line_ending_only_difference_is_named(gh, capsys):
    crlf = st.TEMPLATE_FILES[CI].replace("\n", "\r\n").encode()
    _, states, out = run_dry({CI: crlf}, capsys, gh)
    assert states[0].line_endings_only and "(line endings only)" in out


# --- apply ----------------------------------------------------------------------------------

def test_apply_writes_exactly_the_template_with_the_confirmed_sha(gh, capsys):
    fake = gh(files={CI: OLD_CI.encode()})
    old_sha = blob_sha(OLD_CI.encode())
    commits = st.apply(client(), "o", "r", "main", st._Out(TOKEN),
                       confirmed={CI: old_sha, CONFTEST: "missing"}, message=st.DEFAULT_MESSAGE)
    assert len(commits) == 2
    by_path = {p["path"]: p for p in fake.puts}
    assert by_path[CI]["sha"] == old_sha and "sha" not in by_path[CONFTEST]
    assert all(p["message"] == "ci: sync template (D-060)" and p["branch"] == "main"
               for p in fake.puts)
    assert fake.files[CI] == st.TEMPLATE_FILES[CI].encode()
    assert fake.files[CONFTEST] == st.TEMPLATE_FILES[CONFTEST].encode()
    out = capsys.readouterr().out
    assert commits[0] in out and f"actions/runs/{commits[0]}" in out
    assert {p for _, p in fake.calls if "/contents/" in p} == {
        f"/repos/o/r/contents/{CI}", f"/repos/o/r/contents/{CONFTEST}"}   # nothing else touched


def test_sha_mismatch_aborts_and_writes_nothing(gh):
    fake = gh(files={CI: OLD_CI.encode()})
    with pytest.raises(st.SyncRefused, match="changed since the dry-run"):
        st.apply(client(), "o", "r", "main", st._Out(TOKEN),
                 confirmed={CI: "0" * 40, CONFTEST: "missing"}, message="m")
    assert fake.puts == []


def test_a_file_that_appeared_since_the_dry_run_aborts(gh):
    """Confirmed `missing`, but someone created conftest.py in between."""
    fake = gh(files={CI: OLD_CI.encode(), CONFTEST: b"# theirs\n"})
    with pytest.raises(st.SyncRefused, match="changed since the dry-run"):
        st.apply(client(), "o", "r", "main", st._Out(TOKEN),
                 confirmed={CI: blob_sha(OLD_CI.encode()), CONFTEST: "missing"}, message="m")
    assert fake.puts == []


def test_a_changing_file_without_confirmation_aborts(gh):
    fake = gh(files={CI: OLD_CI.encode()})
    with pytest.raises(st.SyncRefused, match="not confirmed"):
        st.apply(client(), "o", "r", "main", st._Out(TOKEN),
                 confirmed={CI: blob_sha(OLD_CI.encode())}, message="m")   # conftest missing
    assert fake.puts == []


def test_apply_without_any_confirmation_is_refused(gh):
    fake = gh(files={})
    with pytest.raises(st.SyncRefused, match="--confirm-sha"):
        st.apply(client(), "o", "r", "main", st._Out(TOKEN), confirmed={}, message="m")
    assert fake.puts == []


def test_a_token_without_workflow_scope_is_refused_before_any_write(gh):
    fake = gh(files={}, scopes="repo")
    with pytest.raises(st.SyncRefused, match="workflow"):
        st.apply(client(), "o", "r", "main", st._Out(TOKEN),
                 confirmed={CI: "missing", CONFTEST: "missing"}, message="m")
    assert fake.puts == []


def test_partial_failure_says_what_was_and_was_not_written(gh):
    fake = gh(files={}, put_error_on=CONFTEST)
    with pytest.raises(st.SyncRefused) as exc:
        st.apply(client(), "o", "r", "main", st._Out(TOKEN),
                 confirmed={CI: "missing", CONFTEST: "missing"}, message="m")
    assert "WRITTEN so far" in str(exc.value) and CI in str(exc.value)
    assert f"NOT written: ['{CONFTEST}']" in str(exc.value)
    assert CI in fake.files and CONFTEST not in fake.files


def test_run_url_falls_back_to_the_actions_page(gh, capsys):
    gh(files={}, runs=False)
    waits = []
    st.apply(client(), "o", "r", "main", st._Out(TOKEN),
             confirmed={CI: "missing", CONFTEST: "missing"}, message="m", sleep=waits.append)
    assert "https://github.com/o/r/actions" in capsys.readouterr().out
    assert waits                                  # it polled before giving up


# --- allowlist and hidden -------------------------------------------------------------------

@pytest.mark.parametrize("path", ["src/extract.py", "tests/visible/test_x.py", "README.md",
                                  ".github/workflows/other.yml", "../conftest.py", ""])
def test_non_allowlisted_paths_are_refused(path):
    with pytest.raises(st.SyncRefused, match="not a template file"):
        st.check_path_allowed(path)
    with pytest.raises(st.SyncRefused):
        st.parse_confirmations([f"{path}=abc"])


@pytest.mark.parametrize("path", ["tests/hidden/test_extract.py", "hidden/conftest.py",
                                  "tests/hidden/conftest.py"])
def test_any_hidden_path_is_refused_with_the_hidden_reason(path):
    with pytest.raises(st.SyncRefused, match="hidden"):
        st.check_path_allowed(path)


def test_allowlisted_paths_pass():
    for p in st.TEMPLATE_FILES:
        st.check_path_allowed(p)
    assert st.parse_confirmations([f"{CI}=abc", f"{CONFTEST}=missing"]) == {
        CI: "abc", CONFTEST: "missing"}


def test_confirm_sha_must_be_path_equals_sha():
    for bad in ("conftest.py", "=abc", "conftest.py="):
        with pytest.raises(st.SyncRefused):
            st.parse_confirmations([bad])


# --- roster ---------------------------------------------------------------------------------

ROSTER = {"assignments": [{"owner": "Anass-Ben-2005", "repo": "R", "student_id": "anas"}]}


def test_repo_not_in_the_roster_is_refused_unless_allowed():
    with pytest.raises(st.SyncRefused, match=r"not in config/roster\.yaml"):
        st.check_roster("o", "other", student=None, roster=ROSTER, allow_unlisted=False)
    warn = st.check_roster("o", "other", student=None, roster=ROSTER, allow_unlisted=True)
    assert warn and "NOT in config/roster.yaml" in warn[0]


def test_roster_match_is_case_insensitive_and_student_is_checked():
    assert st.check_roster("anass-ben-2005", "r", student="anas", roster=ROSTER,
                           allow_unlisted=False) == []
    with pytest.raises(st.SyncRefused, match="wrong student"):
        st.check_roster("anass-ben-2005", "r", student="student2", roster=ROSTER,
                        allow_unlisted=False)


# --- the CLI, and the token ------------------------------------------------------------------

def test_cli_dry_run_is_default_and_never_prints_the_token(gh, env, capsys):
    fake = gh(files={CI: OLD_CI.encode()})
    assert st.main(["--repo", "o/r", "--student", "anas"]) == 0
    cap = capsys.readouterr()
    assert TOKEN not in cap.out + cap.err and "DRY-RUN" in cap.out
    assert fake.puts == [] and {m for m, _ in fake.calls} == {"GET"}


def test_cli_apply_end_to_end(gh, env, capsys):
    fake = gh(files={CI: OLD_CI.encode()})
    rc = st.main(["--repo", "o/r", "--apply", "--confirm-sha", f"{CI}={blob_sha(OLD_CI.encode())}",
                  "--confirm-sha", f"{CONFTEST}=missing"])
    cap = capsys.readouterr()
    assert rc == 0 and len(fake.puts) == 2 and TOKEN not in cap.out + cap.err


def test_token_is_redacted_even_when_the_server_echoes_it(gh, env, capsys):
    gh(files={}, put_error_on=CI, echo_token_in_error=True)
    rc = st.main(["--repo", "o/r", "--apply", "--confirm-sha", f"{CI}=missing",
                  "--confirm-sha", f"{CONFTEST}=missing"])
    cap = capsys.readouterr()
    assert rc == 2 and "REFUSED" in cap.err and "boom for ***" in cap.err
    assert TOKEN not in cap.out + cap.err


def test_cli_refuses_a_non_allowlisted_confirm_path_without_any_request(gh, env, capsys):
    fake = gh(files={})
    rc = st.main(["--repo", "o/r", "--apply", "--confirm-sha", "README.md=abc"])
    assert rc == 2 and "not a template file" in capsys.readouterr().err
    assert fake.calls == []


def test_cli_unlisted_repo_is_refused_before_any_request(gh, env, capsys):
    fake = gh(files={})
    assert st.main(["--repo", "o/unknown"]) == 2
    assert "not in config/roster.yaml" in capsys.readouterr().err and fake.calls == []


def test_cli_confirm_sha_without_apply_is_refused(gh, env, capsys):
    fake = gh(files={})
    assert st.main(["--repo", "o/r", "--confirm-sha", f"{CI}=abc"]) == 2
    assert "--apply" in capsys.readouterr().err and fake.calls == []


def test_missing_token_is_refused(gh, env, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN")
    fake = gh(files={})
    assert st.main(["--repo", "o/r"]) == 2
    assert "GITHUB_TOKEN is not set" in capsys.readouterr().err and fake.calls == []


def test_malformed_repo_is_refused(env, capsys):
    assert st.main(["--repo", "not-a-repo"]) == 2
    assert "OWNER/NAME" in capsys.readouterr().err
