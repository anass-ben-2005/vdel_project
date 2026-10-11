"""D-070 -- one roster loader, a roster-path argument, and `--roster` on collect and
grade_collected. No database, no network: the scratch roster lives in a temp directory and the
two scripts are exercised with their heavy calls replaced."""
import pytest
import yaml

from scripts import collect, grade_collected
from scripts import seed_data as sd

ROWS = [
    {"assignment_id": "weather_etl_extract", "owner": "o", "repo": "r2",
     "student_id": "student2"},
    {"assignment_id": "weather_etl_load", "owner": "o", "repo": "r2", "student_id": "student2"},
]


@pytest.fixture
def scratch(tmp_path):
    path = tmp_path / "scratch_roster.yaml"
    path.write_text(yaml.safe_dump({"students": [], "assignments": ROWS}), encoding="utf-8")
    return path


def test_load_roster_reads_the_given_path_and_the_default_is_config_roster(scratch, tmp_path,
                                                                           monkeypatch):
    assert sd.load_roster(scratch)["assignments"] == ROWS
    assert sd.load_roster(str(scratch))["assignments"] == ROWS          # str accepted too
    assert sd.ROSTER.name == "roster.yaml" and sd.ROSTER.parent.name == "config"
    other = tmp_path / "default.yaml"
    other.write_text("assignments: []\n", encoding="utf-8")
    monkeypatch.setattr(sd, "ROSTER", other)                            # path=None -> default
    assert sd.load_roster() == {"assignments": []}


def test_a_missing_roster_path_exits_with_the_path_in_the_message(tmp_path):
    with pytest.raises(SystemExit) as exc:
        sd.load_roster(tmp_path / "nope.yaml")
    assert "nope.yaml" in str(exc.value)


def test_collector_and_grader_inputs_come_from_the_same_rows(scratch):
    roster = sd.load_roster(scratch)
    repos = sd.roster_repos(roster)
    repo_for = sd.roster_repo_for(roster)
    assert [(r["student_id"], r["assignment_id"]) for r in repos] == list(repo_for)
    assert repo_for[("student2", "weather_etl_load")] == ("o", "r2")


def test_collect_main_takes_a_roster_option(scratch, monkeypatch):
    seen = {}

    def fake_collect_all(conn, repos):
        seen["repos"] = repos
        return {"stats": "ok", "failed": []}

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setattr(collect, "collect_all", fake_collect_all)
    monkeypatch.setattr(collect.db, "connect", lambda: _Conn())
    assert collect.main(["--roster", str(scratch)]) == 0
    assert [r["assignment_id"] for r in seen["repos"]] == [
        "weather_etl_extract", "weather_etl_load"]


def test_grade_collected_main_takes_a_roster_option_and_needs_no_repo_for_workaround(
        scratch, monkeypatch):
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return {"pending": 0, "graded": [], "failed": [], "no_repo": [], "would_grade": [],
                "unattributed_commits": 0, "post_freeze_commits_skipped": 0}

    monkeypatch.setattr(grade_collected, "run", fake_run)
    assert grade_collected.main(["--roster", str(scratch), "--dry-run"]) == 0
    assert seen["repo_for"][("student2", "weather_etl_extract")] == ("o", "r2")
    assert seen["dry_run"] is True
