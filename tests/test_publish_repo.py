"""scripts/publish_repo.py -- render, publish, register.

Nothing here touches GitHub: a fake client stands in for the API, and pushes go to a LOCAL
bare repository through `remote_base`, so the real git flow (init/add/ls-files/commit/push)
runs for real. DB-backed tests use `run(conn=...)` and one rolled-back transaction (traces
are append-only, so rollback is the only cleanup) and skip when no database is reachable.
"""
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import publish_repo as pr
from scripts import seed_data
from system import db

STUDENT = "_pub_test"
PROJECT = "weather_etl"

ROSTER_TEXT = """\
# my roster -- hand edited, comments must survive
students:
  - student_id: anas
    github_username: someone      # real login
    cohort: vdel-2026

assignments:
  # legacy, not curriculum
  - assignment_id: weather-etl-pipeline
    owner: someone
    repo: legacy-repo
    student_id: anas
    released_at: 2026-08-11T01:15:00Z
    due_at: null
    concepts:
      - py.testing
      - py.data_structures
"""

STU = {"student_id": "stu2", "github_username": "stu2-gh", "cohort": "vdel-2026"}


def _rows(repo="vdel-weather-etl-gapfill-stu2", owner="someone"):
    return [
        {"assignment_id": aid, "owner": owner, "repo": repo, "student_id": "stu2",
         "released_at": "2026-10-07T12:00:00Z", "concepts": concepts}
        for aid, concepts in (("weather_etl_extract", ["py.data_structures"]),
                              ("weather_etl_load", ["sql.select_filter"]))
    ]


# --- names and the hidden-tests guard --------------------------------------------------------

def test_default_name_matches_the_one_real_repo():
    assert pr.default_repo_name("weather_etl", "anas") == "vdel-weather-etl-gapfill-anas"


def test_attempt_above_one_needs_an_explicit_name():
    assert pr.choose_repo_name("weather_etl", "anas", 1, None) == "vdel-weather-etl-gapfill-anas"
    assert pr.choose_repo_name("weather_etl", "anas", 2, "custom") == "custom"
    with pytest.raises(pr.PublishRefused):
        pr.choose_repo_name("weather_etl", "anas", 2, None)


@pytest.mark.parametrize("paths", [
    ["tests/hidden/test_extract.py"],
    ["tests/hidden/conftest.py", "weather_etl/extract.py"],
    ["tests/hidden"],                       # even a bare path component
    ["deep/er/hidden/x.py"],
])
def test_any_hidden_path_component_is_refused(paths):
    with pytest.raises(pr.PublishRefused):
        pr.check_no_hidden(paths)


def test_visible_tests_are_fine():
    pr.check_no_hidden(["tests/visible/test_extract.py", "weather_etl/extract.py",
                        ".github/workflows/ci.yml"])


# --- token scope preflight --------------------------------------------------------------------

def test_workflow_file_with_a_repo_only_token_is_refused_before_anything_is_created():
    tree = [".github/workflows/ci.yml", "weather_etl/extract.py"]
    with pytest.raises(pr.PublishRefused, match="workflow"):
        pr.preflight_scopes(tree, {"repo"})
    assert pr.preflight_scopes(tree, {"repo", "workflow"}) is None
    assert pr.preflight_scopes(["weather_etl/extract.py"], {"repo"}) is None   # no workflow file
    assert "not reported" in pr.preflight_scopes(tree, None)


# --- roster text editing ----------------------------------------------------------------------

def test_new_student_and_rows_are_appended_and_comments_survive():
    new, actions = pr.update_roster_text(ROSTER_TEXT, student=STU, rows=_rows())

    for kept in ("# my roster -- hand edited, comments must survive", "# real login",
                 "# legacy, not curriculum"):
        assert kept in new
    parsed = yaml.safe_load(new)
    assert [s["student_id"] for s in parsed["students"]] == ["anas", "stu2"]
    assert [(a["student_id"], a["assignment_id"]) for a in parsed["assignments"]] == [
        ("anas", "weather-etl-pipeline"), ("stu2", "weather_etl_extract"),
        ("stu2", "weather_etl_load")]
    # the pre-existing row is byte-for-byte untouched, nested concepts list included
    assert parsed["assignments"][0]["concepts"] == ["py.testing", "py.data_structures"]
    assert parsed["assignments"][1]["concepts"] == ["py.data_structures"]
    assert any("add student stu2" in a for a in actions)
    # and the result is something seed_data would accept
    assert seed_data.validate(parsed) == []


def test_nested_concept_lines_are_not_mistaken_for_new_items():
    """Regression for the first draft: `      - py.testing` matches a naive `- ` item
    regex. With it, an existing row looked like three items and updating one corrupted it."""
    text, _ = pr.update_roster_text(ROSTER_TEXT, student=STU, rows=_rows())
    again, _ = pr.update_roster_text(text, student=STU, rows=_rows(repo="moved-repo"))
    parsed = yaml.safe_load(again)
    stu_rows = [a for a in parsed["assignments"] if a["student_id"] == "stu2"]
    assert {a["repo"] for a in stu_rows} == {"moved-repo"}
    assert parsed["assignments"][0]["concepts"] == ["py.testing", "py.data_structures"]
    assert len(parsed["assignments"]) == 3


def test_update_changes_owner_and_repo_but_never_released_at():
    text, _ = pr.update_roster_text(ROSTER_TEXT, student=STU, rows=_rows())
    later = [dict(r, released_at="2099-01-01T00:00:00Z", repo="moved") for r in _rows()]
    again, actions = pr.update_roster_text(text, student=STU, rows=later)
    row = next(a for a in yaml.safe_load(again)["assignments"]
               if a["assignment_id"] == "weather_etl_extract")
    assert row["repo"] == "moved"
    assert str(row["released_at"]).startswith("2026-10-07")        # the real, earlier date
    assert all(a.startswith("update") for a in actions)


def test_roster_edit_is_idempotent():
    once, _ = pr.update_roster_text(ROSTER_TEXT, student=STU, rows=_rows())
    twice, actions = pr.update_roster_text(once, student=STU, rows=_rows())
    assert twice == once and actions == []


def test_crlf_roster_stays_crlf():
    crlf = ROSTER_TEXT.replace("\n", "\r\n")
    new, _ = pr.update_roster_text(crlf, student=STU, rows=_rows())
    assert new.count("\n") == new.count("\r\n") > 0


def test_inline_list_is_refused_not_mangled():
    with pytest.raises(pr.PublishRefused, match="block"):
        pr.update_roster_text("students: []\nassignments: []\n", student=STU, rows=_rows())


def test_write_roster_keeps_a_backup(tmp_path):
    path = tmp_path / "roster.yaml"
    path.write_text("old", encoding="utf-8")
    pr.write_roster(path, "new")
    assert path.read_text() == "new" and (tmp_path / "roster.yaml.bak").read_text() == "old"


# --- seed_data: a second student must not break seeding ------------------------------------------

def test_unique_assignments_collapses_one_assignment_across_students():
    roster = {"assignments": [
        {"assignment_id": "a", "student_id": "s1", "repo": "r1"},
        {"assignment_id": "a", "student_id": "s2", "repo": "r2"},
        {"assignment_id": "b", "student_id": "s1", "repo": "r1"},
    ]}
    unique = seed_data.unique_assignments(roster)
    assert [(a["assignment_id"], a["student_id"]) for a in unique] == [("a", "s1"), ("b", "s1")]
    assert len(roster["assignments"]) == 3             # the roster itself is not mutated


# --- git, against a local bare repository -------------------------------------------------------

def _git_ok(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


@pytest.fixture
def git_identity():
    out = {k: _git_ok("config", k).stdout.strip() for k in ("user.name", "user.email")}
    if not all(out.values()):
        pytest.skip("git user.name/user.email not configured")


def _bare(tmp_path: Path, owner: str, name: str) -> Path:
    bare = tmp_path / "remote" / owner / f"{name}.git"
    bare.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    return bare


def test_git_publish_pushes_and_refuses_a_hidden_tree_before_committing(tmp_path, git_identity):
    bare = _bare(tmp_path, "o", "r")
    good = tmp_path / "good"
    (good / "tests" / "visible").mkdir(parents=True)
    (good / "tests" / "visible" / "t.py").write_text("x")
    (good / "a.py").write_text("y")
    sha = pr.git_publish(good, bare.as_uri(), "msg")
    assert _git_ok("--git-dir", str(bare), "rev-parse", "main").stdout.strip() == sha

    bad = tmp_path / "bad"
    (bad / "tests" / "hidden").mkdir(parents=True)
    (bad / "tests" / "hidden" / "t.py").write_text("secret")
    bare2 = _bare(tmp_path, "o", "r2")
    with pytest.raises(pr.PublishRefused, match="hidden"):
        pr.git_publish(bad, bare2.as_uri(), "msg")
    assert _git_ok("rev-parse", "HEAD", cwd=bad).returncode != 0          # nothing committed
    assert _git_ok("--git-dir", str(bare2), "rev-parse", "main").returncode != 0   # nor pushed


# --- the whole run, fake GitHub ------------------------------------------------------------------

class FakeGitHub:
    def __init__(self, tmp_path, *, state="missing", scopes=("repo", "workflow"), login="owner1"):
        self.tmp_path, self.state, self.scopes, self.login = tmp_path, state, set(scopes), login
        self.created: list[tuple] = []

    def whoami(self):
        return self.login, self.scopes

    def repo_state(self, owner, repo):
        return self.state

    def create_repo(self, owner, repo, *, login, private, description):
        self.created.append((owner, repo, private))
        _bare(self.tmp_path, owner, repo)              # "creating" it = an empty bare repo

    def head_sha(self, owner, repo, branch):
        bare = self.tmp_path / "remote" / owner / f"{repo}.git"
        done = _git_ok("--git-dir", str(bare), "rev-parse", branch)
        return done.stdout.strip() or None


@pytest.fixture
def txn():
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    conn.cursor().execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (STUDENT, STUDENT))
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def roster_file(tmp_path):
    path = tmp_path / "roster.yaml"
    path.write_text(ROSTER_TEXT, encoding="utf-8")
    return path


def _run(txn, tmp_path, roster_file, gh, **kw):
    kw.setdefault("assume_yes", True)
    return pr.run(student=STUDENT, attempt_no=1, project=PROJECT, owner="owner1",
                  roster_path=roster_file, gh=gh, remote_base=(tmp_path / "remote").as_uri(),
                  conn=txn, **kw)


def test_real_run_creates_pushes_and_registers_without_hidden_tests(
    txn, tmp_path, roster_file, git_identity
):
    gh = FakeGitHub(tmp_path)

    out = _run(txn, tmp_path, roster_file, gh)

    name = "vdel-weather-etl-gapfill-" + STUDENT
    assert gh.created == [("owner1", name, True)]                      # created private
    bare = tmp_path / "remote" / "owner1" / f"{name}.git"
    files = _git_ok("--git-dir", str(bare), "ls-tree", "-r", "--name-only", "main").stdout.split()
    assert ".github/workflows/ci.yml" in files and "weather_etl/extract.py" in files
    assert not [f for f in files if "hidden" in f.split("/")]          # the point of it all
    assert gh.head_sha("owner1", name, "main") == out["sha"]

    parsed = yaml.safe_load(roster_file.read_text(encoding="utf-8"))
    mine = [a for a in parsed["assignments"] if a["student_id"] == STUDENT]
    assert {a["assignment_id"] for a in mine} == {
        "weather_etl_extract", "weather_etl_transform", "weather_etl_load", "weather_etl_quality"}
    assert {(a["owner"], a["repo"]) for a in mine} == {("owner1", name)}
    assert (tmp_path / "roster.yaml.bak").exists()
    assert seed_data.validate(parsed) == []
    # the attempt exists because render persisted it (inside this rolled-back txn)
    cur = txn.cursor()
    cur.execute("SELECT count(*) FROM attempts WHERE student_id=%s", (STUDENT,))
    assert cur.fetchone()[0] == 4


def test_existing_repo_with_history_is_never_pushed_over(txn, tmp_path, roster_file, git_identity):
    gh = FakeGitHub(tmp_path, state="has_commits")
    before = roster_file.read_text(encoding="utf-8")
    with pytest.raises(pr.PublishRefused, match="already has commits"):
        _run(txn, tmp_path, roster_file, gh)
    assert gh.created == [] and roster_file.read_text(encoding="utf-8") == before


def test_missing_workflow_scope_stops_before_the_repo_is_created(
    txn, tmp_path, roster_file, git_identity
):
    gh = FakeGitHub(tmp_path, scopes=("repo",))
    with pytest.raises(pr.PublishRefused, match="workflow"):
        _run(txn, tmp_path, roster_file, gh)
    assert gh.created == []                              # nothing left behind on GitHub


def test_declining_the_prompt_creates_nothing(txn, tmp_path, roster_file, git_identity):
    gh = FakeGitHub(tmp_path)
    with pytest.raises(pr.PublishRefused, match="not confirmed"):
        _run(txn, tmp_path, roster_file, gh, assume_yes=False, confirm=lambda _prompt: "n")
    assert gh.created == []


def test_a_render_that_contains_hidden_tests_is_refused(
    txn, tmp_path, roster_file, git_identity, monkeypatch
):
    def leaky_render(project_id, student_id, attempt_no, out_dir, *, conn=None):
        (Path(out_dir) / "tests" / "hidden").mkdir(parents=True)
        (Path(out_dir) / "tests" / "hidden" / "test_x.py").write_text("secret")
        return {"hidden_gap_count": 0}

    monkeypatch.setattr(pr, "render_student_repo", leaky_render)
    gh = FakeGitHub(tmp_path)
    with pytest.raises(pr.PublishRefused, match="hidden"):
        _run(txn, tmp_path, roster_file, gh)
    assert gh.created == []


def test_dry_run_touches_nothing(txn, tmp_path, roster_file, capsys):
    class Forbidden:
        def __getattr__(self, name):
            raise AssertionError(f"dry-run called GitHub: {name}")

    before = roster_file.read_bytes()
    out = _run(txn, tmp_path, roster_file, Forbidden(), dry_run=True)

    assert roster_file.read_bytes() == before and not (tmp_path / "roster.yaml.bak").exists()
    assert not (tmp_path / "remote").exists()
    assert any(a.startswith("add student") for a in out["roster_actions"])
    cur = txn.cursor()                      # the dry-run render left no attempts behind
    cur.execute("SELECT count(*) FROM attempts WHERE student_id=%s", (STUDENT,))
    assert cur.fetchone()[0] == 0
    assert "nothing was created" in capsys.readouterr().out
