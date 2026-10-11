"""Stage 6 -- scripts/load_resources.py (validation, dry run, guarded apply) and the candidate
selector. Database tests use the test database inside a rolled-back transaction; the one CLI
test that commits cleans up after itself. The real database is never connected to.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import psycopg2
import pytest

from agents.resources import KINDS, LEVELS, ResourceCandidate, select_candidates
from scripts import load_resources as lr
from system import db

TEMPLATE = Path(__file__).resolve().parent.parent / "docs" / "resources_template.csv"
CONCEPTS = {"py.errors_debugging", "py.data_structures", "py.testing"}
needs_db = pytest.mark.skipif(not os.environ.get("PG_DSN"), reason="PG_DSN not set")


def row(**over):
    base = {"resource_id": "r-1", "concept_ids": "py.errors_debugging", "kind": "doc_page",
            "title": "A title", "locator": "section 1", "url": "https://docs.example.org/a",
            "level": "beginner"}
    base.update(over)
    return base


def check(rows):
    return lr.validate(rows, CONCEPTS)


def write_csv(path: Path, rows, fields=lr.COLUMNS, encoding="utf-8"):
    with open(path, "w", newline="", encoding=encoding) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


# ---- validation ---------------------------------------------------------------------------

def test_a_good_row_is_valid_and_optional_columns_may_be_empty():
    rows, errors = check([row(), row(resource_id="r-2", kind="", locator="", url="", level="",
                                     concept_ids="py.testing|py.data_structures")])
    assert errors == [] and len(rows) == 2
    assert rows[1].kind is None and rows[1].url is None and rows[1].level is None
    assert rows[1].concept_ids == ("py.testing", "py.data_structures")


@pytest.mark.parametrize("over, fragment", [
    ({"concept_ids": "py.nope"}, "unknown concept id 'py.nope'"),
    ({"concept_ids": "py.testing|sql.joins"}, "unknown concept id 'sql.joins'"),
    ({"concept_ids": "py.testing|py.testing"}, "listed twice"),
    ({"kind": "podcast"}, "kind 'podcast'"),
    ({"level": "expert"}, "level 'expert'"),
    ({"url": "example.org/a"}, "not a valid http(s) URL"),
    ({"url": "ftp://example.org/a"}, "not a valid http(s) URL"),
    ({"url": "https://"}, "not a valid http(s) URL"),
    ({"url": "https://exa mple.org"}, "not a valid http(s) URL"),
    ({"url": "https://localhost"}, "not a valid http(s) URL"),
    ({"resource_id": ""}, "resource_id is empty"),
    ({"resource_id": "bad id!"}, "resource_id 'bad id!' must be"),
    ({"title": ""}, "title is empty"),
    ({"concept_ids": ""}, "concept_ids is empty"),
])
def test_each_invalid_value_is_reported_with_its_line_number(over, fragment):
    rows, errors = check([row(**over)])
    assert rows == []
    assert any(e.startswith("line 2:") and fragment in e for e in errors), errors


def test_duplicates_are_reported_against_the_first_line():
    rows, errors = check([row(), row(), row(resource_id="r-2")])
    assert any("duplicate resource_id 'r-1' (first on line 2)" in e and e.startswith("line 3")
               for e in errors)
    assert any("duplicate url (first on line 2)" in e for e in errors)
    # only the first, valid occurrence survives; main() refuses to write anything while errors exist
    assert [r.resource_id for r in rows] == ["r-1"]


def test_all_errors_are_listed_not_just_the_first():
    _, errors = check([row(kind="x", level="y"), row(resource_id="r-2", url="nope")])
    assert len(errors) == 3


def test_every_valid_value_set_is_documented_in_the_selector_module():
    assert KINDS == ("book_section", "doc_page", "kaggle", "video")
    assert LEVELS == ("beginner", "intermediate", "advanced")


def test_validation_uses_the_real_taxonomy_by_default():
    rows, errors = lr.validate([row(concept_ids="py.errors_debugging|py.data_structures")])
    assert errors == [] and rows
    _, errors = lr.validate([row(concept_ids="py.not_a_concept")])
    assert errors


def test_the_template_is_valid_and_every_row_is_marked_example():
    raw = lr.read_rows(TEMPLATE)
    rows, errors = lr.validate(raw)
    assert errors == [] and len(rows) == 2
    assert all(r.is_example and r.resource_id.startswith("EXAMPLE") for r in rows)
    assert all("EXAMPLE" in r.title for r in rows)
    assert all(".invalid" in r.url for r in rows)         # no real URL was invented


def test_missing_column_is_a_file_error(tmp_path):
    path = write_csv(tmp_path / "x.csv", [{"resource_id": "a"}], fields=["resource_id"])
    with pytest.raises(lr.CsvError, match="missing column"):
        lr.read_rows(path)


def test_a_byte_order_mark_and_spaces_are_tolerated(tmp_path):
    path = write_csv(tmp_path / "x.csv", [row(title="  padded  ")], encoding="utf-8-sig")
    (parsed,) = lr.read_rows(path)
    assert parsed["title"] == "padded"
    assert lr.validate([parsed], CONCEPTS)[1] == []


# ---- the command: dry run by default, guarded apply ---------------------------------------

@pytest.fixture
def no_connect(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a database connection was attempted")
    monkeypatch.setattr(psycopg2, "connect", boom)


def test_default_is_a_dry_run_and_connects_to_nothing(tmp_path, no_connect, capsys):
    path = write_csv(tmp_path / "r.csv", [row()])
    assert lr.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "1 valid row" in out and "dry run" in out


def test_explicit_dry_run_flag_is_the_same(tmp_path, no_connect):
    assert lr.main([str(write_csv(tmp_path / "r.csv", [row()])), "--dry-run"]) == 0


def test_invalid_file_writes_nothing_and_exits_1(tmp_path, no_connect, capsys):
    path = write_csv(tmp_path / "r.csv", [row(), row(resource_id="r-2", kind="zzz")])
    assert lr.main([str(path), "--apply", "--dsn", "dbname=x_test"]) == 1
    assert "nothing was written" in capsys.readouterr().out


def test_apply_without_dsn_is_refused(tmp_path, no_connect, monkeypatch, capsys):
    monkeypatch.setenv("PG_DSN", "dbname=whatever_test")           # must be ignored
    assert lr.main([str(write_csv(tmp_path / "r.csv", [row()])), "--apply"]) == 2
    assert "needs --dsn" in capsys.readouterr().out


def test_apply_refuses_the_template_rows(no_connect, capsys):
    assert lr.main([str(TEMPLATE), "--apply", "--dsn", "dbname=x_test"]) == 1
    assert "refusing to apply template rows" in capsys.readouterr().out


def test_apply_refuses_a_database_that_is_not_a_test_database(tmp_path, no_connect):
    path = write_csv(tmp_path / "r.csv", [row()])
    with pytest.raises(SystemExit, match="does not end in '_test'"):
        lr.main([str(path), "--apply", "--dsn", "host=h dbname=vdel user=u"])


def test_check_target_rules():
    assert lr.check_target("dbname=vdel_test", allow_real_db=False) == "vdel_test"
    assert lr.check_target("dbname=vdel", allow_real_db=True) == "vdel"
    with pytest.raises(SystemExit):
        lr.check_target("dbname=vdel", allow_real_db=False)
    with pytest.raises(SystemExit):
        lr.check_target("host=localhost", allow_real_db=True)


def test_apply_and_dry_run_are_mutually_exclusive(tmp_path):
    with pytest.raises(SystemExit):
        lr.main([str(write_csv(tmp_path / "r.csv", [row()])), "--apply", "--dry-run"])


# ---- apply + selector, test database ------------------------------------------------------

@pytest.fixture
def cur():
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    c = conn.cursor()
    yield c
    conn.rollback()
    conn.close()


def rows_of(*specs):
    return check([row(**s) for s in specs])[0]


@needs_db
def test_apply_rows_inserts_then_updates_and_is_idempotent(cur):
    rows = rows_of({"resource_id": "T-1", "url": "https://t.example.org/1"},
                   {"resource_id": "T-2", "url": "https://t.example.org/2"})
    assert lr.apply_rows(cur, rows) == (2, 0)
    assert lr.apply_rows(cur, rows) == (0, 2)
    changed = rows_of({"resource_id": "T-1", "title": "New title",
                       "url": "https://t.example.org/1"})
    assert lr.apply_rows(cur, changed) == (0, 1)
    cur.execute("SELECT title, concept_ids FROM resources WHERE resource_id = 'T-1'")
    assert cur.fetchone() == ("New title", ["py.errors_debugging"])
    cur.execute("SELECT count(*) FROM resources WHERE resource_id IN ('T-1','T-2')")
    assert cur.fetchone()[0] == 2


@needs_db
def test_cli_apply_writes_to_the_named_test_database_only(tmp_path):
    path = write_csv(tmp_path / "r.csv", [row(resource_id="T-CLI-1",
                                              url="https://t.example.org/cli1")])
    dsn = os.environ["PG_DSN"]
    assert dsn.split("dbname=")[1].split()[0].endswith("_test")
    try:
        assert lr.main([str(path), "--apply", "--dsn", dsn]) == 0
        assert lr.main([str(path), "--apply", "--dsn", dsn]) == 0        # idempotent
        conn = db._open()
        c = conn.cursor()
        c.execute("SELECT count(*) FROM resources WHERE resource_id = 'T-CLI-1'")
        assert c.fetchone()[0] == 1
        conn.close()
    finally:
        conn = db._open()
        c = conn.cursor()
        c.execute("DELETE FROM resources WHERE resource_id = 'T-CLI-1'")
        conn.commit()
        conn.close()


def seed(cur, *specs):
    lr.apply_rows(cur, rows_of(*specs))


@needs_db
def test_selector_filters_by_concept_and_orders_easiest_first_then_by_id(cur):
    seed(cur,
         {"resource_id": "S-adv", "level": "advanced", "url": "https://s.example.org/1"},
         {"resource_id": "S-none", "level": "", "url": "https://s.example.org/2"},
         {"resource_id": "S-b2", "level": "beginner", "url": "https://s.example.org/3"},
         {"resource_id": "S-int", "level": "intermediate", "url": "https://s.example.org/4"},
         {"resource_id": "S-b1", "level": "beginner", "url": "https://s.example.org/5"},
         {"resource_id": "S-other", "concept_ids": "py.testing", "url": "https://s.example.org/6"})
    got = select_candidates(cur, "py.errors_debugging", limit=10)
    ids = [c.resource_id for c in got if c.resource_id.startswith("S-")]
    assert ids == ["S-b1", "S-b2", "S-int", "S-adv", "S-none"]
    assert all(isinstance(c, ResourceCandidate) for c in got)


@needs_db
def test_selector_is_deterministic_whatever_the_insertion_order(cur):
    specs = [{"resource_id": f"D-{n}", "level": "beginner", "url": f"https://d.example.org/{n}"}
             for n in (3, 1, 2)]
    seed(cur, *specs)
    first = [c.resource_id for c in select_candidates(cur, "py.errors_debugging", limit=50)
             if c.resource_id.startswith("D-")]
    seed(cur, *reversed(specs))
    second = [c.resource_id for c in select_candidates(cur, "py.errors_debugging", limit=50)
              if c.resource_id.startswith("D-")]
    assert first == second == ["D-1", "D-2", "D-3"]


@needs_db
def test_selector_level_filter_keeps_rows_with_no_level(cur):
    seed(cur,
         {"resource_id": "L-b", "level": "beginner", "url": "https://l.example.org/1"},
         {"resource_id": "L-a", "level": "advanced", "url": "https://l.example.org/2"},
         {"resource_id": "L-n", "level": "", "url": "https://l.example.org/3"})
    got = {c.resource_id for c in select_candidates(cur, "py.errors_debugging",
                                                    levels=["beginner"], limit=50)
           if c.resource_id.startswith("L-")}
    assert got == {"L-b", "L-n"}


@needs_db
def test_selector_limit_and_empty_results(cur):
    seed(cur, *[{"resource_id": f"M-{n}", "url": f"https://m.example.org/{n}"} for n in range(4)])
    assert len(select_candidates(cur, "py.errors_debugging", limit=2)) == 2
    assert select_candidates(cur, "py.errors_debugging", limit=0) == []
    assert select_candidates(cur, "no.such.concept") == []


@needs_db
def test_selector_matches_a_row_listing_several_concepts_by_any_of_them(cur):
    seed(cur, {"resource_id": "X-multi", "concept_ids": "py.testing|py.data_structures",
               "url": "https://x.example.org/1"})
    for concept in ("py.testing", "py.data_structures"):
        assert "X-multi" in [c.resource_id for c in select_candidates(cur, concept, limit=50)]
    assert "X-multi" not in [c.resource_id for c in
                             select_candidates(cur, "py.errors_debugging", limit=50)]


def test_selector_rejects_unknown_levels_and_negative_limits():
    class NoCursor:
        def execute(self, *a):
            raise AssertionError("no query expected")
    with pytest.raises(ValueError, match="unknown level"):
        select_candidates(NoCursor(), "py.testing", levels=["guru"])
    with pytest.raises(ValueError):
        select_candidates(NoCursor(), "py.testing", limit=-1)


@needs_db
def test_the_feedback_agent_default_path_uses_the_selector(cur):
    """gather_input(candidates=None) selects candidates for the weakest concept."""
    from agents import feedback_agent as fa
    from tests.support import ensure_variant

    cur.execute("INSERT INTO students VALUES ('_res_student','_res_student','vdel-2026')")
    variant = ensure_variant(cur, "weather_etl_extract")
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES ('_res_student','weather_etl','weather_etl_extract',"
                "1,%s,1) RETURNING attempt_id", (variant,))
    aid = cur.fetchone()[0]
    sha = "c" * 40
    cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                " VALUES (%s,'_res_student','weather_etl_extract','2026-08-25 01:00+00')", (sha,))
    cur.execute("INSERT INTO test_results (attempt_id, commit_sha, test_name, gap_id, passed,"
                " message, status) VALUES (%s,%s,'tests/hidden/test_extract.py::test_x',"
                "'g_ext_retry',false,'AssertionError: x','ok')", (aid, sha))
    seed(cur, {"resource_id": "G-1", "url": "https://g.example.org/1",
               "concept_ids": "py.errors_debugging|py.data_structures"})
    inp = fa.gather_input(cur, aid, sha, profile={"mastery": {}})
    # the gap lists two concepts at the same 0% rate: the alphabetically first one is the weakest
    assert inp.weakest_concept == "py.data_structures"
    assert "G-1" in [c.resource_id for c in inp.candidates]
