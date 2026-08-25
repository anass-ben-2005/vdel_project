"""tests/test_run_benchmark.py -- the pure-function half of benchmark/run_benchmark.py.

No DB, no LLM key needed: `_exact_agreement` is arithmetic over judge output already in
hand, and `_load_ground_truth`/`_submissions` are file reads. The parts that need a live
provider (`run()` itself) are exercised live, by hand, and recorded in
`docs/DECISIONS.md` D-050 -- not mocked here, matching this project's own preference for
real evidence over a mocked LLM call standing in for one.
"""
from __future__ import annotations

import json

from benchmark.run_benchmark import (
    CRITERIA,
    GROUND_TRUTH_PATH,
    _exact_agreement,
    _load_ground_truth,
    _submissions,
)


def test_exact_agreement_is_1_when_every_run_agrees():
    score_sets = [{"correctness": 4, "approach": 4, "readability": 2, "idiomatic": 2}] * 3
    assert _exact_agreement(score_sets) == dict.fromkeys(CRITERIA, 1.0)


def test_exact_agreement_is_per_criterion_not_one_collapsed_number():
    # Stable on correctness, split down the middle on readability -- the two numbers
    # must stay separate, which is the entire reason this function exists instead of
    # one all-criteria-at-once average (see its own docstring).
    score_sets = [
        {"correctness": 4, "approach": 4, "readability": 0, "idiomatic": 2},
        {"correctness": 4, "approach": 4, "readability": 4, "idiomatic": 2},
    ]
    result = _exact_agreement(score_sets)
    assert result["correctness"] == 1.0
    assert result["readability"] == 0.5


def test_exact_agreement_picks_the_most_common_value_not_the_first():
    score_sets = [
        {"correctness": 0, "approach": 0, "readability": 0, "idiomatic": 0},
        {"correctness": 4, "approach": 0, "readability": 0, "idiomatic": 0},
        {"correctness": 4, "approach": 0, "readability": 0, "idiomatic": 0},
    ]
    # correctness: 0 once, 4 twice -- majority (4) gives 2/3 agreement, not 1/3.
    assert _exact_agreement(score_sets)["correctness"] == 2 / 3


def test_submissions_finds_every_real_file_and_excludes_task_md():
    names = {p.name for p in _submissions()}
    assert names == {"clean.py", "subtly_wrong.py", "inefficient.py",
                      "copy_paste.py", "broken.py"}
    assert "TASK.md" not in names


def test_ground_truth_loads_the_real_template_with_every_score_null():
    # Pins the CURRENT state of the real file -- Stage C3's own contract (CLAUDE.md 10:
    # never invent a number). If this test starts failing because a real score landed,
    # that is Anas filling in his own labels, not a regression -- update the test then.
    truth = _load_ground_truth()
    assert set(truth) == {"clean.py", "subtly_wrong.py", "inefficient.py",
                           "copy_paste.py", "broken.py"}
    for submission_scores in truth.values():
        assert set(submission_scores) == set(CRITERIA)
        assert all(v is None for v in submission_scores.values())


def test_ground_truth_path_is_valid_json_with_a_submissions_key():
    # A structural smoke test independent of _load_ground_truth's own parsing, so a
    # hand-edit to the file that breaks its JSON syntax fails loudly here rather than
    # only inside run_benchmark.py's first live (LLM-costing) invocation.
    data = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    assert "submissions" in data
    assert set(data["submissions"]) == {p.name for p in _submissions()}
