"""Stage 3 -- the agents fixtures are well formed and carry nothing a student must not see.

No database. The hidden-test guard is imported from scripts.post_feedback (D-077), not rewritten.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.post_feedback import hidden_source_lines

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "agents"
JSON_FILES = sorted((FIXTURES / "real").glob("*.json")) + sorted(
    p for p in (FIXTURES / "synthetic").glob("*.json") if not p.name.startswith("resources_"))
CODE_FILES = sorted((FIXTURES / "code").glob("*.py"))
STATUSES = {"ok", "collection_error", "timeout", "tooling"}
EXC_TYPE = re.compile(r"^[A-Z]\w*(Error|Exception|Exit|Interrupt)$")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_fixtures_exist():
    assert len(list((FIXTURES / "real").glob("*.json"))) >= 7
    assert len(list((FIXTURES / "synthetic").glob("*.json"))) >= 4
    assert len(CODE_FILES) >= 4
    assert (FIXTURES / "README.md").is_file()


@pytest.mark.parametrize("path", JSON_FILES, ids=lambda p: p.name)
def test_fixture_shape(path):
    data = _load(path)
    assert data["fixture_version"] == 1
    assert data["origin"] in {"real", "synthetic"}
    assert data["origin_note"]
    assert data["status"] in STATUSES
    assert set(data["diagnosis"]) == {"weakest_concept", "attempts_per_stage",
                                      "recurrence_flags", "failing_tests"}
    assert data["total"] == len(data["checks"])
    assert data["passed"] == sum(1 for c in data["checks"] if c["passed"])
    for check in data["checks"]:
        assert set(check) == {"test_name", "passed", "gap_id", "exception_type"}
        if check["passed"]:
            assert check["exception_type"] is None
        elif check["exception_type"] is not None:
            assert EXC_TYPE.match(check["exception_type"])


@pytest.mark.parametrize("path", JSON_FILES, ids=lambda p: p.name)
def test_fixture_stores_no_message_or_traceback(path):
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    for check in data["checks"]:
        assert "message" not in check
    assert "Traceback" not in text
    assert "assert " not in text and "def test_" not in text


@pytest.mark.parametrize("path", [*JSON_FILES, *CODE_FILES,
                                  *FIXTURES.joinpath("synthetic").glob("resources_*.json")],
                         ids=lambda p: p.name)
def test_no_hidden_test_line_in_any_fixture(path):
    # A bare `import x` / `from x import y` line is shared by every Python file about the same
    # library, hidden tests included; it carries no test content, so it is not a leak.
    hidden = {line for line in hidden_source_lines("weather_etl")
              if not line.startswith(("import ", "from "))}
    assert hidden, "the hidden-line set must not be empty or this test proves nothing"
    text = path.read_text(encoding="utf-8")
    leaked = [line for line in hidden if line in text]
    assert not leaked, f"{path.name} contains a hidden test line"


def test_real_fixtures_cover_the_named_situations():
    by_name = {p.name: _load(p) for p in (FIXTURES / "real").glob("*.json")}
    s2_extract = [d for n, d in by_name.items()
                  if d["student_id"] == "student2" and d["assignment_id"] == "weather_etl_extract"]
    assert sorted(d["status"] for d in s2_extract) == ["collection_error", "ok", "ok"]
    assert any(d["assignment_id"] == "weather_etl_load" and d["student_id"] == "student2"
               for d in by_name.values())
    assert any(d["student_id"] == "anas" for d in by_name.values())


def test_synthetic_fixtures_cover_timeout_and_empty_mastery():
    statuses = {_load(p)["status"] for p in (FIXTURES / "synthetic").glob("synthetic*.json")}
    assert "timeout" in statuses
    assert any(_load(p)["mastery"] == {} for p in (FIXTURES / "synthetic").glob("synthetic*.json"))


def test_resource_fixture_is_clearly_fake():
    data = _load(FIXTURES / "synthetic" / "resources_synthetic.json")
    for res in data["candidates"]:
        assert res["resource_id"].startswith("EXAMPLE-")
        assert ".invalid" in res["url"]


def test_synthetic_code_files_are_inert_text():
    """They are only ever read. (The syntax-error file must really not compile; the others
    must, so the 'situation' each one stands for is the one the README says.)"""
    by = {p.name: p.read_text(encoding="utf-8") for p in CODE_FILES}
    with pytest.raises(SyntaxError):
        compile(by["extract_syntax_error.py"], "x", "exec")
    for name in ("extract_retry_ok.py", "extract_no_retry.py", "extract_infinite_loop.py"):
        compile(by[name], name, "exec")      # compiling is not executing
