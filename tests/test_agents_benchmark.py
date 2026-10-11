"""Stage 9 -- benchmark preparation without a live call.

  9a  the labeling sheet (scripts/agents_make_labeling_sheet.py)
  9b  benchmark/run_benchmark.py run end to end against the scripted fake provider, in the test
      database (it INSERTs its own synthetic student and rolls back, as it always did)
"""
from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

import pytest

from agents import fake_llm as fl
from agents.code_agent import CRITERIA
from benchmark import run_benchmark as rb
from scripts import agents_make_labeling_sheet as ls
from scripts.post_feedback import hidden_source_lines
from system import llm

needs_db = pytest.mark.skipif(not os.environ.get("PG_DSN"), reason="PG_DSN not set")


# ---- 9a: the labeling sheet ---------------------------------------------------------------

def test_sheet_has_four_criteria_per_submission_and_empty_scores():
    rows = ls.sheet_rows()
    ids = [sid for sid, _ in ls.submissions()]
    assert len(rows) == 4 * len(ids) and len(ids) >= 9
    assert {r["criterion"] for r in rows} == set(CRITERIA)
    assert all(r["my_score"] == "" and r["my_note"] == "" for r in rows)
    assert {"clean.py", "subtly_wrong.py", "fixture:extract_retry_ok.py"} <= set(ids)


def test_sheet_files_exist_and_are_repo_relative():
    for row in ls.sheet_rows():
        assert not Path(row["file"]).is_absolute()
        assert (ls.ROOT / row["file"]).is_file()


def test_sheet_contains_no_hidden_test_content_and_no_code():
    hidden = {ln for ln in hidden_source_lines("weather_etl")
              if not ln.startswith(("import ", "from "))}
    assert hidden
    text = "\n".join(",".join(r.values()) for r in ls.sheet_rows())
    assert not [ln for ln in hidden if ln in text]
    assert "def " not in text and "import " not in text


def test_write_sheet_roundtrips_and_never_overwrites_without_force(tmp_path):
    path = tmp_path / "sheet.csv"
    assert ls.write_sheet(path) == len(ls.sheet_rows())
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames) == ls.COLUMNS
        assert len(list(reader)) == len(ls.sheet_rows())
    path.write_text("my labels", encoding="utf-8")
    with pytest.raises(FileExistsError):
        ls.write_sheet(path)
    assert path.read_text(encoding="utf-8") == "my labels"
    ls.write_sheet(path, force=True)


def test_default_output_is_in_a_gitignored_directory():
    ignore = (ls.ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "benchmark/results/" in ignore
    assert ls.DEFAULT_OUT.parent == ls.ROOT / "benchmark" / "results"


def fill(path: Path, scores: dict[tuple[str, str], str]):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["my_score"] = scores.get((row["submission_id"], row["criterion"]), "")
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ls.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def test_import_converts_a_filled_sheet_to_the_ground_truth_shape(tmp_path):
    sheet = tmp_path / "s.csv"
    ls.write_sheet(sheet)
    fill(sheet, {("clean.py", "correctness"): "4", ("clean.py", "approach"): "2",
                 ("fixture:extract_retry_ok.py", "correctness"): "4"})
    data, errors = ls.import_sheet(sheet)
    assert errors == []
    assert data["submissions"]["clean.py"] == {"correctness": 4, "approach": 2,
                                               "readability": None, "idiomatic": None}
    assert data["submissions"]["broken.py"] == dict.fromkeys(CRITERIA)
    assert "fixture:extract_retry_ok.py" not in data["submissions"]
    template = json.loads(ls.GROUND_TRUTH_TEMPLATE.read_text(encoding="utf-8"))
    assert set(data["submissions"]) == set(template["submissions"])
    assert data["concept"] == template["concept"]


@pytest.mark.parametrize("bad", ["3", "5", "four", "-2", "2.0"])
def test_import_rejects_scores_outside_0_2_4(tmp_path, bad):
    sheet = tmp_path / "s.csv"
    ls.write_sheet(sheet)
    fill(sheet, {("clean.py", "correctness"): bad})
    _, errors = ls.import_sheet(sheet)
    assert len(errors) == 1 and "must be empty, 0, 2 or 4" in errors[0]


def test_import_never_overwrites_the_template(tmp_path, capsys):
    sheet = tmp_path / "s.csv"
    ls.write_sheet(sheet)
    before = ls.GROUND_TRUTH_TEMPLATE.read_bytes()
    code = ls.main(["--import-sheet", str(sheet), "--ground-truth-out",
                    str(ls.GROUND_TRUTH_TEMPLATE)])
    assert code == 2 and ls.GROUND_TRUTH_TEMPLATE.read_bytes() == before
    out = tmp_path / "gt.json"
    assert ls.main(["--import-sheet", str(sheet), "--ground-truth-out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["submissions"]["clean.py"]


def test_legend_prints_the_anchors(capsys):
    assert ls.main(["--legend"]) == 0
    assert "Score each criterion 0, 2, or 4" in capsys.readouterr().out


def test_the_real_ground_truth_template_is_still_all_null():
    template = json.loads(ls.GROUND_TRUTH_TEMPLATE.read_text(encoding="utf-8"))
    assert all(v is None for s in template["submissions"].values() for v in s.values())


# ---- 9b: the benchmark end to end on the fake ---------------------------------------------

def submission_of(prompt: str) -> str:
    return prompt.split("<<<BEGIN SUBMISSION>>>")[1].split("<<<END SUBMISSION>>>")[0].strip()


def verdict_json(prompt: str, correctness: int = 4) -> str:
    """A well-formed verdict whose quotes are real lines of the submission in the prompt."""
    code_lines = [ln.strip() for ln in submission_of(prompt).splitlines() if ln.strip()]
    quote = max(code_lines, key=len)
    return json.dumps({
        "evidence": {c: [{"quote": quote, "why": "the longest line"}] for c in CRITERIA},
        "scores": {"llm_correctness_opinion": correctness, "approach": 2, "readability": 2,
                   "idiomatic": 2},
        "misconceptions": [], "feedback_for_student": "fake", "confidence": "low"})


@pytest.fixture
def results_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rb, "RESULTS_DIR", tmp_path / "results")
    return tmp_path / "results"


@needs_db
def test_benchmark_runs_end_to_end_on_the_fake_with_zero_live_calls(results_dir):
    fake = fl.FakeLLM(default=verdict_json)
    with fake.installed():
        results = rb.run(runs=3, only=None, commit=False)
    names = [p.name for p in rb._submissions()]
    assert set(results) == {*names, "_gateway"}
    for name in names:
        assert len(results[name]["runs"]) == 3 and results[name]["call_errors"] == []
        assert set(results[name]["self_consistency"].values()) == {1.0}     # a stable fake
        assert results[name]["ground_truth_match"] is None                  # labels are null
    assert fake.call_count == 3 * len(names)          # use_cache=False: every run really called
    assert {c.temperature for c in fake.calls} == {0.0}
    assert {c.provider for c in fake.calls} == {"anthropic"}                # the pinned fake


@needs_db
def test_benchmark_gateway_stats_come_from_the_cost_log(results_dir):
    fake = fl.FakeLLM(default=verdict_json)
    with fake.installed():
        results = rb.run(runs=2, only="clean.py", commit=False)
    g = results["_gateway"]
    assert g["provider_calls"] == 2 and g["cache_hits"] == 0
    assert g["json_retry_rate"] == 0.0 and g["first_attempt_valid_rate"] == 1.0
    assert g["calls_by_model"] == {llm.MODEL_TIERS["default"][llm.Provider.ANTHROPIC]: 2}
    assert g["tokens_in"] > 0 and g["tokens_out"] > 0


@needs_db
def test_benchmark_measures_instability_when_the_judge_is_noisy(results_dir):
    counter = {"n": 0}

    def noisy(prompt: str) -> str:
        counter["n"] += 1
        return verdict_json(prompt, correctness=4 if counter["n"] % 3 else 0)

    with fl.FakeLLM(default=noisy).installed():
        results = rb.run(runs=3, only="clean.py", commit=False)
    assert results["clean.py"]["self_consistency"]["correctness"] == pytest.approx(2 / 3)
    assert results["clean.py"]["self_consistency"]["approach"] == 1.0


@needs_db
def test_benchmark_counts_json_failures_as_a_finding_not_a_crash(results_dir):
    script = [fl.valid_json({"nope": 1}), fl.valid_json({"nope": 2})]      # run 1: invalid twice
    script += [fl.text(verdict_json)] * 2                                    # runs 2-3 are fine
    fake = fl.FakeLLM(script)
    with fake.installed():
        results = rb.run(runs=3, only="clean.py", commit=False)
    assert len(results["clean.py"]["call_errors"]) == 1
    assert "SchemaValidationError" in results["clean.py"]["call_errors"][0]
    assert len(results["clean.py"]["runs"]) == 2
    g = results["_gateway"]
    assert g["corrective_retries"] == 1 and g["flagged_after_retry"] == 1
    assert g["json_retry_rate"] == pytest.approx(1 / 3)


@needs_db
def test_benchmark_leaves_no_trace_behind_when_not_committed(results_dir):
    from system import db
    conn = db._open()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM traces")
    before = cur.fetchone()[0]
    with fl.FakeLLM(default=verdict_json).installed():
        rb.run(runs=1, only="clean.py", commit=False)
    cur.execute("SELECT count(*) FROM traces")
    assert cur.fetchone()[0] == before
    cur.execute("SELECT count(*) FROM students WHERE student_id = %s", (rb.BENCHMARK_STUDENT,))
    assert cur.fetchone()[0] == 0
    conn.close()


@needs_db
def test_benchmark_results_file_is_written_where_the_patch_says(results_dir):
    with fl.FakeLLM(default=verdict_json).installed():
        results = rb.run(runs=1, only="clean.py", commit=False)
    path = rb._write_results(results)
    assert path.parent == results_dir and json.loads(path.read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d{8}T\d{6}Z\.json", path.name)


def test_gateway_stats_arithmetic_is_pure():
    class R:
        def __init__(self, attempt, valid=True, flagged=False, cache=False):
            self.attempt, self.schema_valid, self.flagged = attempt, valid, flagged
            self.cache_hit, self.tokens_in, self.tokens_out, self.model = cache, 10, 5, "m"

    stats = rb._gateway_stats([R(1), R(1, valid=False), R(2, flagged=True, valid=False),
                               R(1, cache=True)])
    assert stats["provider_calls"] == 3 and stats["cache_hits"] == 1
    assert stats["first_attempts"] == 2 and stats["corrective_retries"] == 1
    assert stats["json_retry_rate"] == 0.5 and stats["first_attempt_valid_rate"] == 0.5
    assert stats["tokens_in"] == 30
    assert rb._gateway_stats([])["json_retry_rate"] is None
