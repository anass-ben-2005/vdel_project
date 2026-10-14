"""D-102 -- benchmark/run_real_benchmark.py, tested with the FAKE LLM only.

No test can reach a provider (every handler is replaced by one that raises, and
`FakeLLM.installed()` swaps its own in), no key from the real environment is used (the checks take
a dict), the database is made unreachable on purpose (`db._open` and `psycopg2.connect` raise), and
the results go to a temp folder. The ground truth is the REAL `benchmark/ground_truth.json`,
read-only.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import psycopg2
import pytest

from agents import fake_llm as fl
from benchmark import run_real_benchmark as rr
from benchmark.run_benchmark import CRITERIA, _load_ground_truth, _submissions
from system import db
from system import llm as gateway
from tests.test_agents_benchmark import verdict_json

SECRET = "sk-SECRET-BENCH-1111"
OTHER_SECRET = "sk-SECRET-OTHER-2222"
ENV = {"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": SECRET}
NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC)
FILES = [p.name for p in _submissions()]
ANTHROPIC_CHAIN = list(gateway._model_chain(
    gateway.Provider.ANTHROPIC, gateway.MODEL_TIERS["default"][gateway.Provider.ANTHROPIC],
    "default"))
WORST_3_RUNS = len(FILES) * 3 * 2 * len(ANTHROPIC_CHAIN)


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    def blocked(*args, **kwargs):
        raise AssertionError("LIVE PROVIDER CALL attempted in a test")

    def no_database(*args, **kwargs):
        raise AssertionError("the real benchmark must not open a database connection")

    for provider in list(gateway._PROVIDER_HANDLERS):
        monkeypatch.setitem(gateway._PROVIDER_HANDLERS, provider, blocked)
    monkeypatch.setattr(db, "_open", no_database)
    monkeypatch.setattr(psycopg2, "connect", no_database)
    monkeypatch.setattr(rr, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(rr, "RECOMMENDATION_PATH", tmp_path / "RECOMMENDATION.md")


def go(fake=None, **kw):
    lines: list[str] = []
    args = {"runs": 3, "only": None, "max_calls": WORST_3_RUNS, "env": ENV, "confirm": True,
            "out": lines.append, "now": NOW}
    args.update(kw)
    if fake is None:
        code = rr.run(**args)
    else:
        with fake.installed():                       # handlers are the fake's; HardCap wraps them
            code = rr.run(**args)
    return code, "\n".join(lines)


def run_dir(tmp_path) -> Path:
    (path,) = (tmp_path / "results").iterdir()
    return path


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- the exact maximum, with the arithmetic ------------------------------------------------------

def test_the_plan_prints_the_arithmetic_and_the_exact_maximum(tmp_path):
    fake = fl.FakeLLM(default=verdict_json)
    code, text = go(fake, confirm=False)
    assert code == rr.EXIT_OK and fake.call_count == 0
    n_models = len(ANTHROPIC_CHAIN)
    assert "labelled rows: 20 = 5 submissions x 4 criteria" in text
    assert "the criteria multiply rows, not calls" in text
    assert "judge() calls: 5 submissions x 3 runs = 15" in text
    assert "15 x 2 = 30" in text                                  # attempts
    assert f"MAXIMUM provider calls: 30 x {n_models} = {30 * n_models}" in text
    assert f"per provider: anthropic {30 * n_models}, " in text
    for other in ("google 0", "nvidia 0", "openai 0"):
        assert other in text
    for model in ANTHROPIC_CHAIN:
        assert f"{model} 30 (15 judge() x 2 attempts)" in text
    assert "PLAN ONLY: nothing was called, nothing was written" in text
    assert not (tmp_path / "results").exists()                    # not even the folder


@pytest.mark.parametrize("provider", [p.value for p in gateway._FALLBACK_KEY_ENV_VARS])
def test_the_maximum_follows_the_gateways_own_model_chain(provider):
    prov = gateway.Provider(provider)
    chain = gateway._model_chain(prov, gateway.MODEL_TIERS["default"][prov], "default")
    plan = rr.plan_calls(FILES, 3, provider)
    assert plan.models == tuple(chain)
    assert plan.max_total == 5 * 3 * 2 * len(chain)
    assert plan.per_model == 5 * 3 * 2


def test_it_refuses_when_the_worst_case_exceeds_the_cap_and_says_by_how_much(tmp_path):
    fake = fl.FakeLLM(default=verdict_json)
    code, text = go(fake, max_calls=WORST_3_RUNS - 7)
    assert code == rr.EXIT_REFUSED and fake.call_count == 0
    assert f"the worst case is {WORST_3_RUNS} provider calls" in text and "by 7" in text
    assert "--allow-partial" in text and "nothing was called, nothing was written" in text
    assert not (tmp_path / "results").exists()
    code, _ = go(fake, max_calls=WORST_3_RUNS, confirm=False)      # exactly the maximum: accepted
    assert code == rr.EXIT_OK


# --- the same safety rules as llm_first_call -----------------------------------------------------

def test_it_refuses_with_two_keys_without_a_provider_and_never_prints_a_key(tmp_path):
    fake = fl.FakeLLM(default=verdict_json)
    two = {**ENV, "OPENAI_API_KEY": OTHER_SECRET}
    code, text = go(fake, env=two)
    assert code == rr.EXIT_REFUSED and "more than one provider key" in text
    assert "ANTHROPIC_API_KEY" in text and "OPENAI_API_KEY" in text
    assert SECRET not in text and OTHER_SECRET not in text
    code, text = go(fake, env={"ANTHROPIC_API_KEY": SECRET})
    assert code == rr.EXIT_REFUSED and "LLM_PROVIDER is not set" in text and SECRET not in text
    assert fake.call_count == 0 and not (tmp_path / "results").exists()


def test_it_refuses_a_run_with_no_complete_labels_or_an_off_scale_label(monkeypatch):
    nulls = {f: dict.fromkeys(CRITERIA) for f in FILES}
    monkeypatch.setattr(rr, "_load_ground_truth", lambda: nulls)
    code, text = go(fl.FakeLLM(default=verdict_json))
    assert code == rr.EXIT_REFUSED and "no complete labels" in text
    off = {f: dict.fromkeys(CRITERIA, 3) for f in FILES}
    monkeypatch.setattr(rr, "_load_ground_truth", lambda: off)
    code, text = go(fl.FakeLLM(default=verdict_json))
    assert code == rr.EXIT_REFUSED and "outside 0/2/4" in text


def test_it_refuses_a_bad_cap_a_bad_runs_and_a_bad_only():
    for kw, needle in (({"max_calls": 0}, "--max-calls"), ({"runs": 0}, "--runs"),
                       ({"only": "nope.py"}, "no submission named"),
                       ({"reference": "nope.py"}, "--reference")):
        code, text = go(fl.FakeLLM(default=verdict_json), **kw)
        assert code == rr.EXIT_REFUSED and needle in text


# --- a full run ----------------------------------------------------------------------------------

def expected_pairs(criterion: str) -> list[tuple[int, int]]:
    """Independent of the module: the fake always answers 4 / 2 / 2 / 2."""
    fixed = {"correctness": 4, "approach": 2, "readability": 2, "idiomatic": 2}
    truth = _load_ground_truth()
    return [(truth[f][criterion], fixed[criterion]) for f in FILES for _ in range(3)]


def test_a_full_run_writes_everything_and_uses_no_cache_and_no_database(tmp_path):
    fake = fl.FakeLLM(default=verdict_json)
    code, text = go(fake)
    assert code == rr.EXIT_OK
    assert fake.call_count == 15 and fake._cache == {}      # use_cache=False: every run called
    assert "*** REAL RUN: billed provider calls" in text and SECRET not in text

    folder = run_dir(tmp_path)
    assert re.fullmatch(r"20261012T120000Z", folder.name)
    assert {p.name for p in folder.iterdir()} == {
        "plan.txt", "raw_runs.jsonl", "summary.json", "confusion.csv", "RECOMMENDATION.md"}
    rows = jsonl(folder / "raw_runs.jsonl")
    assert len(rows) == 15 and {r["status"] for r in rows} == {"ok"}
    first = rows[0]
    assert set(first["scores"]) == set(CRITERIA) and first["verdict"]["evidence"]
    assert first["records"] and first["records"][0]["tokens_in"] > 0
    assert (tmp_path / "RECOMMENDATION.md").read_text("utf-8") == \
        (folder / "RECOMMENDATION.md").read_text("utf-8")

    summary = json.loads((folder / "summary.json").read_text("utf-8"))
    for crit in CRITERIA:
        pairs = expected_pairs(crit)
        entry = summary["agreement"]["per_criterion"][crit]["with_non_applicable"]
        assert entry["n"] == 15
        assert entry["exact_n"] == sum(t == j for t, j in pairs)
        assert entry["within_one_n"] == sum(abs(t - j) <= 2 for t, j in pairs)
        table = summary["agreement"]["per_criterion"][crit]["confusion"]
        assert sum(sum(row.values()) for row in table.values()) == 15
        without = summary["agreement"]["per_criterion"][crit]["without_non_applicable"]
        assert without == entry                                   # no non-applicable row here
    assert summary["agreement"]["overall"]["with_non_applicable"]["n"] == 60
    assert summary["gateway"]["provider_calls"] == 15 and summary["gateway"]["cache_hits"] == 0
    assert summary["gateway"]["tokens_in"] > 0 and summary["gateway"]["tokens_out"] > 0
    assert summary["meta"]["calls_made"] == 15 and summary["meta"]["stopped_at_cap"] is False
    assert summary["estimated_cost_usd"] is None and "not computed" in summary["cost_text"]
    assert summary["stability"]["per_criterion"]["correctness"]["min"] == 1.0   # a stable fake

    csv_rows = (folder / "confusion.csv").read_text("utf-8").splitlines()
    assert csv_rows[0] == "criterion,label,judge_0,judge_2,judge_4" and len(csv_rows) == 1 + 5 * 3


def test_the_recommendation_comes_from_the_numbers_and_states_its_limits(tmp_path):
    go(fl.FakeLLM(default=verdict_json))
    text = (tmp_path / "RECOMMENDATION.md").read_text("utf-8")
    summary = json.loads((run_dir(tmp_path) / "summary.json").read_text("utf-8"))
    overall = summary["agreement"]["overall"]["with_non_applicable"]
    assert f"{overall['exact_n']}/{overall['n']}" in text
    assert "PARTIAL RUN" not in text and "ONE provider" in text
    for limit in ("pre-labelled by an LLM", "claude-code-llm", "human-reviewed on a 10-row sample",
                  "docstrings reveal the planted bug",
                  "The task given to the judge is a hand-kept paraphrase",
                  "not re-parsed at run time from `benchmark/submissions/TASK.md`",
                  "Non-applicable rows in this ground truth: 0"):
        assert limit in text, limit
    assert "Estimated cost | not computed" in text
    assert "TODO(measure)" not in text                            # nothing left as a placeholder
    assert "80% exact" in text                                     # the one documented target


def test_an_estimated_cost_appears_only_when_prices_are_given(tmp_path):
    go(fl.FakeLLM(default=verdict_json), price_in=3.0, price_out=15.0)
    summary = json.loads((run_dir(tmp_path) / "summary.json").read_text("utf-8"))
    g = summary["gateway"]
    expected = g["tokens_in"] / 1e6 * 3.0 + g["tokens_out"] / 1e6 * 15.0
    assert summary["estimated_cost_usd"] == pytest.approx(expected) and expected > 0
    assert "USD" in summary["cost_text"] and "supplied by the user" in summary["cost_text"]


def test_the_judge_is_always_called_without_the_cache(monkeypatch):
    seen = []
    real = rr.grade

    def spy(*args, **kwargs):
        seen.append(kwargs.get("use_cache"))
        return real(*args, **kwargs)

    monkeypatch.setattr(rr, "grade", spy)
    go(fl.FakeLLM(default=verdict_json), runs=2, only="clean.py")
    assert seen == [False, False]


def test_nothing_reaches_a_memory_or_a_database(monkeypatch):
    memory = rr.NullMemory()
    monkeypatch.setattr(rr, "NullMemory", lambda: memory)
    go(fl.FakeLLM(default=verdict_json), runs=1, only="clean.py")
    assert memory.writes == 1 and memory.log_trace() < 0           # written to nothing
    source = Path(rr.__file__).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+(psycopg2|memory\b|system\.db|system import db)",
                         source, re.MULTILINE)


# --- the cap -------------------------------------------------------------------------------------

def test_the_cap_is_hard_and_partial_results_are_written(tmp_path):
    fake = fl.FakeLLM(default=verdict_json)
    code, text = go(fake, max_calls=7, allow_partial=True)
    assert code == rr.EXIT_CAPPED
    assert fake.call_count == 7                                    # never an 8th call
    assert "CAP REACHED (7/7)" in text
    rows = jsonl(run_dir(tmp_path) / "raw_runs.jsonl")
    assert len(rows) == 7 and {r["status"] for r in rows} == {"ok"}
    summary = json.loads((run_dir(tmp_path) / "summary.json").read_text("utf-8"))
    assert summary["meta"]["stopped_at_cap"] is True and summary["meta"]["judge_runs_ok"] == 7
    assert summary["agreement"]["overall"]["with_non_applicable"]["n"] == 28
    assert "PARTIAL RUN" in (tmp_path / "RECOMMENDATION.md").read_text("utf-8")


def test_a_call_refused_in_the_middle_of_a_judge_is_recorded_and_not_made(tmp_path):
    calls = {"n": 0}

    def alternate(prompt: str) -> str:               # odd call: broken JSON, even call: a verdict
        calls["n"] += 1
        return "not json at all" if calls["n"] % 2 else verdict_json(prompt)

    fake = fl.FakeLLM(default=alternate)
    code, text = go(fake, max_calls=3, allow_partial=True)
    assert code == rr.EXIT_CAPPED and fake.call_count == 3         # 2 for judge 1, 1 for judge 2
    rows = jsonl(run_dir(tmp_path) / "raw_runs.jsonl")
    assert [r["status"] for r in rows] == ["ok", "interrupted_by_cap"]
    assert "CAP REACHED (3/3)" in text and "refused, not made" in text
    summary = json.loads((run_dir(tmp_path) / "summary.json").read_text("utf-8"))
    assert summary["meta"]["judge_runs_ok"] == 1 and summary["meta"]["judge_runs_failed"] == 0
    assert summary["gateway"]["provider_calls"] == 3


def test_a_run_where_every_judge_fails_writes_its_rows_but_not_the_recommendation(tmp_path):
    fake = fl.FakeLLM(default=lambda prompt: "not json at all")
    code, text = go(fake, runs=1, only="clean.py")
    assert code == rr.EXIT_OK                                      # failures are findings
    rows = jsonl(run_dir(tmp_path) / "raw_runs.jsonl")
    assert [r["status"] for r in rows] == ["call_error"]
    assert "SchemaValidationError" in rows[0]["error"]
    assert not (tmp_path / "RECOMMENDATION.md").exists()           # nothing to base it on
    assert "NOT written: no run finished" in text
    summary = json.loads((run_dir(tmp_path) / "summary.json").read_text("utf-8"))
    assert summary["meta"]["judge_runs_failed"] == 1
    assert "No judge run finished" in (run_dir(tmp_path) / "RECOMMENDATION.md").read_text("utf-8")


# --- the arithmetic, pure ------------------------------------------------------------------------

def test_agreement_exact_and_within_one_level():
    pairs = [(4, 4), (4, 2), (4, 0), (0, 0), (2, 4)]
    a = rr.agreement(pairs)
    assert (a["n"], a["exact_n"], a["within_one_n"]) == (5, 2, 4)  # 4->0 is two levels off
    assert a["exact"] == 0.4 and a["within_one"] == 0.8
    assert rr.agreement([]) == {"n": 0, "exact_n": 0, "within_one_n": 0, "exact": None,
                                "within_one": None}


def test_confusion_counts_label_by_judge():
    table = rr.confusion([(4, 4), (4, 2), (4, 2), (0, 4)])
    assert table["4"] == {"0": 0, "2": 2, "4": 1} and table["0"]["4"] == 1
    assert sum(sum(r.values()) for r in table.values()) == 4


def test_agreement_with_and_without_the_non_applicable_rows():
    truth = {"a.py": {"correctness": 4, "approach": 4, "readability": 4, "idiomatic": 2},
             "b.py": {"correctness": 4, "approach": 4, "readability": 4, "idiomatic": 2}}
    right = {"correctness": 4, "approach": 4, "readability": 4, "idiomatic": 0}   # idiomatic wrong
    obs = [{"submission": s, "run": 1, "scores": right} for s in truth]
    na = {("a.py", "idiomatic"), ("b.py", "idiomatic")}
    result = rr.compare(obs, truth, na)
    idio = result["per_criterion"]["idiomatic"]
    assert idio["with_non_applicable"]["exact_n"] == 0 and idio["with_non_applicable"]["n"] == 2
    assert idio["without_non_applicable"]["n"] == 0
    assert idio["without_non_applicable"]["exact"] is None
    overall = result["overall"]
    assert overall["with_non_applicable"]["exact"] == 6 / 8
    assert overall["without_non_applicable"]["exact"] == 1.0
    assert overall["without_non_applicable"]["n"] == 6
    assert result["non_applicable_rows"] == ["a.py:idiomatic", "b.py:idiomatic"]


def test_stability_reports_the_minimum_and_the_mean_over_submissions():
    obs = [{"submission": "a.py", "run": r, "scores": dict.fromkeys(CRITERIA, v)}
           for r, v in ((1, 4), (2, 4), (3, 0))]
    obs += [{"submission": "b.py", "run": r, "scores": dict.fromkeys(CRITERIA, 2)} for r in (1, 2)]
    obs += [{"submission": "c.py", "run": 1, "scores": dict.fromkeys(CRITERIA, 2)}]  # one run
    s = rr.stability(obs)
    assert set(s["per_submission"]) == {"a.py", "b.py"}
    assert s["per_criterion"]["correctness"]["min"] == pytest.approx(2 / 3)
    assert s["per_criterion"]["correctness"]["mean"] == pytest.approx((2 / 3 + 1) / 2)


def test_cost_is_none_without_both_prices():
    assert rr.estimate_cost(1000, 1000, None, 1.0) is None
    assert rr.estimate_cost(1000, 1000, 1.0, None) is None
    assert rr.estimate_cost(2_000_000, 1_000_000, 3.0, 15.0) == pytest.approx(21.0)


def test_the_cli_requires_max_calls_and_defaults_to_a_plan():
    parser = rr.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    args = parser.parse_args(["--max-calls", "50"])
    assert (args.confirm_billed_run, args.allow_partial, args.runs) == (False, False, 3)
    assert args.reference == "clean.py"
