"""benchmark/run_real_benchmark.py -- the REAL benchmark run: billed calls, hard cap, no database.

    python -m benchmark.run_real_benchmark --max-calls N                       # plan, calls NOTHING
    python -m benchmark.run_real_benchmark --max-calls N --confirm-billed-run  # the real run

Grades `benchmark/submissions/*.py` `--runs` times each (default 3) with the Code Agent and
compares every verdict with `benchmark/ground_truth.json`: exact agreement and within-one-level
agreement per criterion, the confusion table, agreement with and without the non-applicable rows,
stability across runs, JSON validity, evidence validity, latency, tokens and (only if you pass
prices) an estimated cost. Everything goes to `benchmark/results/<timestamp>/` and
`benchmark/RECOMMENDATION.md` is generated from those numbers and nothing else (D-102).

THE MAXIMUM IS COMPUTED, NOT GUESSED (`plan_calls`, printed every time). One `judge()` scores all
four criteria at once, so the criteria multiply ROWS, not calls. Per `judge()`: up to 2 attempts
(the first, and ONE corrective retry if the JSON is invalid, `llm.judge`); each attempt walks the
configured provider's model chain (`llm._model_chain`): a transient failure moves to the next
model, so one attempt makes at most `len(chain)` handler calls. With exactly one provider key set
(checked) the gateway's cross-provider layer has nobody to go to. So:

    maximum = submissions x runs x 2 attempts x len(model chain)  (per model: subs x runs x 2)

The run is REFUSED when that maximum exceeds `--max-calls`, and the message says by how much.
`--allow-partial` is the explicit way to accept a cap below the worst case: the run then stops
cleanly at the cap and writes what it has (exit code 3). The cap is HARD: every provider handler is
wrapped (`scripts/llm_first_call.HardCap`), so the (cap+1)th real call is never made, whatever the
gateway's fallback chain tries.

SAME SAFETY RULES AS `scripts/llm_first_call.py`: refuses if `LLM_PROVIDER` is unset, if not
exactly one provider key is set (or it is not the key of `LLM_PROVIDER`), never prints a key.
`use_cache=False` (D-213). NOTHING is written to the database or to GitHub: this module opens no
connection (a no-op memory stands in for `Memory`; the verdict is not stored anywhere but the
results folder).

PRICES are not in the repo and are never invented (CLAUDE.md section 10): pass
`--price-in-per-mtok` and `--price-out-per-mtok` (USD per million tokens, from the provider's price
page, at the date of the run) to get an estimated cost; without them the report says "not
computed".

Exit codes: 0 complete (or plan only); 2 refused; 3 stopped at the cap, partial results written.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agents import prompts, validation
from agents.code_agent import grade
from benchmark.run_benchmark import (
    CONCEPTS,
    CRITERIA,
    GROUND_TRUTH_PATH,
    SUBMISSIONS_DIR,
    TASK,
    _exact_agreement,
    _gateway_stats,
    _load_ground_truth,
    _submissions,
)
from scripts.llm_first_call import HardCap, Refused, check_environment, key_variables
from system import llm as gateway

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RECOMMENDATION_PATH = Path(__file__).resolve().parent / "RECOMMENDATION.md"
STUDENT = "_benchmark"
LEVELS = (0, 2, 4)
ATTEMPTS_PER_JUDGE = 2                     # the first call and ONE corrective retry (llm.judge)
TARGET_EXACT = 0.80                        # BUILD_PLAN 4.5 / M4 DoD: ">=80% exact agreement"
EXIT_OK, EXIT_REFUSED, EXIT_CAPPED = 0, 2, 3
BANNER = "REAL RUN: billed provider calls, hard cap, nothing written to the database or GitHub"


# --- the plan: the exact maximum, with the arithmetic -----------------------------------------

@dataclass(frozen=True)
class CallPlan:
    provider: str
    models: tuple[str, ...]
    submissions: tuple[str, ...]
    runs: int

    @property
    def rows(self) -> int:
        return len(self.submissions) * len(CRITERIA)

    @property
    def judges(self) -> int:
        return len(self.submissions) * self.runs

    @property
    def attempts(self) -> int:
        return self.judges * ATTEMPTS_PER_JUDGE

    @property
    def per_model(self) -> int:
        return self.attempts                       # each model of the chain may serve every attempt

    @property
    def max_total(self) -> int:
        return self.attempts * len(self.models)

    def lines(self) -> list[str]:
        n_models = len(self.models)
        others = sorted(p for p in key_variables() if p != self.provider)
        out = [
            f"labelled rows: {self.rows} = {len(self.submissions)} submissions x "
            f"{len(CRITERIA)} criteria",
            f"one judge() scores all {len(CRITERIA)} criteria at once: the criteria multiply rows, "
            "not calls",
            f"judge() calls: {len(self.submissions)} submissions x {self.runs} runs = "
            f"{self.judges}",
            f"attempts per judge(): {ATTEMPTS_PER_JUDGE} (the first, plus ONE corrective retry if "
            f"the JSON is invalid)  ->  {self.judges} x {ATTEMPTS_PER_JUDGE} = {self.attempts}",
            f"model fallbacks: {self.provider} chain = [{', '.join(self.models)}] -> {n_models} "
            f"model(s); a transient failure moves to the next one, so one attempt makes at most "
            f"{n_models} call(s)",
            f"MAXIMUM provider calls: {self.attempts} x {n_models} = {self.max_total}",
            "per provider: " + f"{self.provider} {self.max_total}" + "".join(
                f", {p} 0" for p in others)
            + "   (exactly one key is set, so the cross-provider layer has nobody to go to)",
            "per model:    " + ", ".join(
                f"{m} {self.per_model} ({self.judges} judge() x {ATTEMPTS_PER_JUDGE} attempts)"
                for m in self.models),
        ]
        return out


def plan_calls(submissions: list[str], runs: int, provider: str) -> CallPlan:
    """The exact worst case for `provider`, from the gateway's own model chain."""
    prov = gateway.Provider(provider)
    primary = gateway.MODEL_TIERS["default"][prov]
    chain = tuple(gateway._model_chain(prov, primary, "default"))
    return CallPlan(provider, chain, tuple(submissions), runs)


# --- no database: a memory that stores nothing ------------------------------------------------

class NullMemory:
    """Stands in for `Memory` so the Code Agent's trace and mastery writes go nowhere."""

    def __init__(self) -> None:
        self.writes = 0

    def get_profile(self, student_id, *, conn=None):
        return {"mastery": {}, "weaknesses": []}

    def log_trace(self, *args, **kwargs) -> int:
        self.writes += 1
        return -self.writes                 # a negative id can never be mistaken for a real trace

    def update_mastery(self, *args, **kwargs) -> None:
        return None


# --- pure arithmetic over the verdicts --------------------------------------------------------

def agreement(pairs: list[tuple[int, int]]) -> dict:
    """pairs of (ground truth, judge). Exact match, and within one level of the 0/2/4 scale."""
    n = len(pairs)
    exact = sum(1 for t, j in pairs if t == j)
    near = sum(1 for t, j in pairs if abs(t - j) <= 2)
    return {"n": n, "exact_n": exact, "within_one_n": near,
            "exact": exact / n if n else None, "within_one": near / n if n else None}


def confusion(pairs: list[tuple[int, int]]) -> dict[str, dict[str, int]]:
    table = {str(t): {str(j): 0 for j in LEVELS} for t in LEVELS}
    for t, j in pairs:
        table[str(t)][str(j)] += 1
    return table


def compare(observations: list[dict], truth: Mapping[str, Mapping[str, int | None]],
            not_applicable: set[tuple[str, str]]) -> dict:
    """Agreement with the ground truth, per criterion and overall, with and without the rows the
    ground truth marks non-applicable. Every successful run is one observation per criterion."""
    def pairs_for(criterion: str | None, *, drop_na: bool) -> list[tuple[int, int]]:
        pairs = []
        for obs in observations:
            for crit in ([criterion] if criterion else CRITERIA):
                wanted = truth.get(obs["submission"], {}).get(crit)
                if wanted is None or (drop_na and (obs["submission"], crit) in not_applicable):
                    continue
                pairs.append((wanted, obs["scores"][crit]))
        return pairs

    out = {"per_criterion": {}, "overall": {}, "non_applicable_rows": sorted(
        f"{s}:{c}" for s, c in not_applicable)}
    for crit in (*CRITERIA, None):
        with_na, without_na = pairs_for(crit, drop_na=False), pairs_for(crit, drop_na=True)
        entry = {"with_non_applicable": agreement(with_na),
                 "without_non_applicable": agreement(without_na),
                 "confusion": confusion(with_na)}
        if crit is None:
            out["overall"] = entry
        else:
            out["per_criterion"][crit] = entry
    return out


def stability(observations: list[dict]) -> dict:
    """Self-consistency per submission (`_exact_agreement`), and per criterion the minimum and the
    mean over the submissions that have at least two successful runs."""
    by_sub: dict[str, list[dict]] = defaultdict(list)
    for obs in observations:
        by_sub[obs["submission"]].append(obs["scores"])
    per_sub = {s: _exact_agreement(sets) for s, sets in by_sub.items() if len(sets) >= 2}
    summary = {}
    for crit in CRITERIA:
        values = [r[crit] for r in per_sub.values()]
        summary[crit] = {"min": min(values), "mean": sum(values) / len(values)} if values else None
    return {"per_submission": per_sub, "per_criterion": summary}


def estimate_cost(tokens_in: int, tokens_out: int, price_in: float | None,
                  price_out: float | None) -> float | None:
    if price_in is None or price_out is None:
        return None
    return tokens_in / 1_000_000 * price_in + tokens_out / 1_000_000 * price_out


# --- the report -------------------------------------------------------------------------------

def _pct(count: int, n: int) -> str:
    return f"{count}/{n} ({count / n:.0%})" if n else "n/a"


def render_recommendation(summary: dict) -> str:
    """benchmark/RECOMMENDATION.md, from the numbers in `summary` and nothing else."""
    meta, cmp_, gw = summary["meta"], summary["agreement"], summary["gateway"]
    stab, ev = summary["stability"], summary["evidence"]
    overall = cmp_["overall"]["with_non_applicable"]
    lines = ["# Judge model recommendation: measured run", ""]
    if meta["stopped_at_cap"]:
        lines += [f"> **PARTIAL RUN.** Stopped at the call cap ({meta['calls_made']}/"
                  f"{meta['max_calls']} calls); {meta['judge_runs_ok']} of "
                  f"{meta['judge_runs_planned']} planned judge() runs finished. Every number below "
                  "is over the finished runs only.", ""]
    lines += [
        "> Generated by `benchmark/run_real_benchmark.py` from `" + meta["results_dir"] + "`. "
        "Every number is copied from that run; nothing is estimated except where a price was "
        "supplied. Reproduce with the command in section 1.", "",
        "## 1. What was run", "",
        "| Item | Value |", "|---|---|",
        f"| Date (UTC) | {meta['started_at']} |",
        f"| Provider | {meta['provider']} |",
        f"| Models that served calls | {', '.join(meta['models_served']) or 'none'} |",
        f"| Prompt version | {meta['prompt_version']} |",
        "| Temperature | 0 (`judge()` has no temperature parameter) |",
        "| Cache | off (`use_cache=False`, D-213) |",
        f"| Submissions | {', '.join(meta['submissions'])} |",
        f"| Runs per submission | {meta['runs']} |",
        f"| Reference solution given to the judge | {meta['reference']} |",
        f"| Provider calls made / cap / worst case | {meta['calls_made']} / {meta['max_calls']} / "
        f"{meta['worst_case']} |",
        f"| Command | `{meta['command']}` |", "",
        "## 2. Agreement with the ground truth", "",
        "Exact = the judge's 0/2/4 equals the label. Within one level = differs by at most one "
        "step of the scale (0, 2, 4). Every successful run counts as one observation.", "",
        "| Criterion | n | Exact | Within one level | Exact without non-applicable rows | "
        f"Target {TARGET_EXACT:.0%} exact |",
        "|---|---|---|---|---|---|"]
    for crit in (*CRITERIA, "overall"):
        entry = cmp_["overall"] if crit == "overall" else cmp_["per_criterion"][crit]
        a, b = entry["with_non_applicable"], entry["without_non_applicable"]
        met = "n/a" if a["exact"] is None else ("met" if a["exact"] >= TARGET_EXACT else "NOT met")
        lines.append(f"| {crit} | {a['n']} | {_pct(a['exact_n'], a['n'])} | "
                     f"{_pct(a['within_one_n'], a['n'])} | {_pct(b['exact_n'], b['n'])} "
                     f"(n={b['n']}) | {met} |")
    na = cmp_["non_applicable_rows"]
    lines += ["", f"Non-applicable rows in this ground truth: {len(na)}"
              + (f" ({', '.join(na)})" if na else "")
              + ". With none, the two exact columns are the same number.", "",
              "## 3. Confusion tables (rows = label, columns = judge)", ""]
    for crit in (*CRITERIA, "overall"):
        table = (cmp_["overall"] if crit == "overall" else cmp_["per_criterion"][crit])["confusion"]
        lines += [f"**{crit}**", "", "| label \\ judge | 0 | 2 | 4 |", "|---|---|---|---|"]
        lines += [f"| {t} | {table[str(t)]['0']} | {table[str(t)]['2']} | {table[str(t)]['4']} |"
                  for t in LEVELS]
        lines.append("")
    lines += ["## 4. Stability across runs", "",
              "Per criterion: the fraction of a submission's runs equal to its most common value; "
              "minimum and mean over the submissions that have at least two finished runs.", "",
              "| Criterion | Minimum | Mean |", "|---|---|---|"]
    for crit in CRITERIA:
        s = stab["per_criterion"][crit]
        cells = f"{s['min']:.2f} | {s['mean']:.2f} |" if s else "n/a | n/a |"
        lines.append(f"| {crit} | {cells}")
    lines += ["", "## 5. JSON validity, evidence, latency, tokens, cost", "",
              "| Measure | Value |", "|---|---|",
              f"| Provider calls made | {gw['provider_calls']} |",
              f"| First-attempt valid rate | {_rate(gw['first_attempt_valid_rate'])} |",
              f"| Corrective-retry rate | {_rate(gw['json_retry_rate'])} |",
              f"| Flagged after retry | {gw['flagged_after_retry']} |",
              f"| Judge runs that failed (call errors) | {meta['judge_runs_failed']} |",
              "| Verdicts with at least one unmatched quote | "
              f"{_pct(ev['with_unmatched_quote'], ev['verdicts'])} |",
              f"| Mean call latency | {_secs(summary['latency_mean_s'])} |",
              f"| Tokens in / out (total) | {gw['tokens_in']} / {gw['tokens_out']} |",
              f"| Tokens in / out per finished judge() run | {summary['tokens_per_run']} |",
              f"| Tokens by model | {summary['tokens_by_model_text']} |",
              f"| Estimated cost | {summary['cost_text']} |", "",
              "## 6. Reading of the numbers", ""]
    if overall["n"] == 0:
        lines.append("No judge run finished, so there is nothing to read.")
    else:
        weak = [c for c in CRITERIA
                if cmp_["per_criterion"][c]["with_non_applicable"]["exact"] is not None
                and cmp_["per_criterion"][c]["with_non_applicable"]["exact"] < TARGET_EXACT]
        verdict = "meets" if overall["exact"] >= TARGET_EXACT else "does NOT meet"
        lines += [
            f"* Code Agent on `{meta['provider']}` ({', '.join(meta['models_served'])}): overall "
            "exact "
            f"agreement {_pct(overall['exact_n'], overall['n'])}, within one level "
            f"{_pct(overall['within_one_n'], overall['n'])}. It {verdict} the one documented "
            "target "
            f"({TARGET_EXACT:.0%} exact, BUILD_PLAN 4.5) on this benchmark."
            + (f" Criteria below the target: {', '.join(weak)}." if weak
               else " No criterion is below the target."),
            "* This run measured ONE provider. It is not a comparison between models: repeat it "
            "with each candidate, then compare the sections 2 to 5 tables.",
            "* The Feedback Agent is not measured by this benchmark.",
            "* A disappointing number is a finding, not a failure (CLAUDE.md section 10); do not "
            "tune the labels or the prompt to this result."]
    lines += ["", "## 7. Limits (read before using any number above)", "",
              "* **The ground truth was pre-labelled by an LLM** (`claude-code-llm`, from the code "
              "and the rubric, without test results) and **human-reviewed on a 10-row sample "
              "only** "
              "(`benchmark/results/review_sample.txt`); the other rows were not individually "
              "reviewed. Agreement with these labels is agreement with another model's reading, "
              "which can share its biases. If the judged model is from the same family as the "
              "labeller, agreement is probably inflated.",
              "* **The files' docstrings reveal the planted bug** (archetype and defect are "
              "written "
              "at the top of each benchmark file), so a judge can read the answer instead of "
              "finding it. One docstring is also wrong (PySpark has a `groupby` alias).",
              "* **`benchmark/TASK.md` is missing.** The task given to the judge is the paraphrase "
              "held in `benchmark/run_benchmark.py` (`TASK`); the original file the paraphrase "
              "refers to cannot be checked.",
              f"* One task, {len(meta['submissions'])} submissions, {meta['runs']} runs: small. "
              "Percentages move by several points with one verdict.",
              f"* The reference solution option was **{meta['reference']}**: if it is `clean.py`, "
              "that file was judged with itself as the reference.",
              "* The provider's fallback can change the serving model mid-run: see the models "
              "line in section 1 (taken from the call records, not from the configuration).",
              "* Prices are not in the repository; the cost line is computed only from prices "
              "passed on the command line."]
    return "\n".join(lines) + "\n"


def _rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _secs(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f} s"


# --- the run ----------------------------------------------------------------------------------

def _record_dicts(records) -> list[dict]:
    return [{"provider": r.provider, "model": r.model, "tokens_in": r.tokens_in,
             "tokens_out": r.tokens_out, "elapsed_s": r.elapsed_s, "attempt": r.attempt,
             "schema_valid": r.schema_valid, "flagged": r.flagged, "cache_hit": r.cache_hit}
            for r in records]


def _non_applicable() -> set[tuple[str, str]]:
    """Optional top-level `"non_applicable": [["file.py", "criterion"], ...]` of the truth file."""
    if not GROUND_TRUTH_PATH.exists():
        return set()
    data = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    return {(s, c) for s, c in data.get("non_applicable", [])}


def run(*, runs: int, only: str | None, max_calls: int, env: Mapping[str, str],
        confirm: bool = False, allow_partial: bool = False, reference: str = "clean.py",
        price_in: float | None = None, price_out: float | None = None, out=print,
        now: datetime | None = None, recommendation_path: Path | None = None,
        command: str = "python -m benchmark.run_real_benchmark") -> int:
    try:
        provider = check_environment(env)
        if max_calls < 1:
            raise Refused("--max-calls must be at least 1.")
        if runs < 1:
            raise Refused("--runs must be at least 1.")
        files = _submissions()
        if only:
            files = [p for p in files if p.name == only]
            if not files:
                raise Refused(f"no submission named {only!r} in {SUBMISSIONS_DIR}.")
        truth = _load_ground_truth()
        incomplete = [p.name for p in files
                      if any(truth.get(p.name, {}).get(c) is None for c in CRITERIA)]
        if incomplete:
            raise Refused("the ground truth has no complete labels for " + ", ".join(incomplete)
                          + ": a real run would spend money with nothing to compare against.")
        bad = [(p.name, c) for p in files for c in CRITERIA if truth[p.name][c] not in LEVELS]
        if bad:
            raise Refused(f"ground truth scores outside 0/2/4: {bad}")
        if reference not in ("none", *[p.name for p in _submissions()]):
            raise Refused(f"--reference must be 'none' or a submission file, not {reference!r}.")
        plan = plan_calls([p.name for p in files], runs, provider)
        for line in plan.lines():
            out(line)
        if plan.max_total > max_calls and not allow_partial:
            raise Refused(
                f"the worst case is {plan.max_total} provider calls, above --max-calls "
                f"{max_calls} by {plan.max_total - max_calls}. Raise --max-calls to "
                f"{plan.max_total}, lower --runs, or pass --allow-partial to accept a run that "
                "stops cleanly at the cap and writes partial results.")
    except Refused as exc:
        out(f"REFUSED: {exc}")
        out("(nothing was called, nothing was written)")
        return EXIT_REFUSED

    if not confirm:
        out(f"PLAN ONLY: nothing was called, nothing was written. Worst case {plan.max_total} "
            f"call(s), cap {max_calls}. Add --confirm-billed-run to start the real run.")
        return EXIT_OK

    started = now or datetime.now(UTC)
    run_dir = RESULTS_DIR / f"{started:%Y%m%dT%H%M%SZ}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "plan.txt").write_text("\n".join(plan.lines()) + "\n", encoding="utf-8")
    out(f"*** {BANNER} ***")
    out(f"cap {max_calls}; results in {run_dir}")

    reference_text = ((SUBMISSIONS_DIR / reference).read_text(encoding="utf-8")
                      if reference != "none" else None)
    assignment = {"assignment_id": "benchmark_monthly_revenue", "task": TASK,
                  "concepts": CONCEPTS}
    memory = NullMemory()
    log = gateway.COST_LOG
    log_start = len(log)
    observations: list[dict] = []
    raw_rows: list[dict] = []
    stopped = False
    failed = 0
    unmatched_verdicts = 0
    raw_path = run_dir / "raw_runs.jsonl"

    with HardCap(max_calls) as cap, raw_path.open("w", encoding="utf-8") as raw_file:
        for path in files:
            if stopped:
                break
            for i in range(1, runs + 1):
                if cap.count >= max_calls:
                    stopped = True
                    out(f"CAP REACHED ({cap.count}/{max_calls}): stopping before "
                        f"{path.name} run {i}; partial results are written.")
                    break
                before = len(log)
                row = {"submission": path.name, "run": i}
                try:
                    verdict, _trace, failures = grade(
                        memory, STUDENT, assignment, str(path), reference=reference_text,
                        profile_snapshot={"mastery": {}, "weaknesses": []},
                        use_cache=False)
                except Exception as exc:  # noqa: BLE001 -- recorded; the sweep goes on or stops
                    row.update(status="interrupted_by_cap" if cap.blocked else "call_error",
                               error=f"{type(exc).__name__}: {str(exc)[:300]}",
                               records=_record_dicts(log[before:]))
                    failed += 0 if cap.blocked else 1
                    out(f"  {path.name} run {i}: {row['status'].upper()} -- {row['error'][:120]}")
                    if cap.blocked:
                        stopped = True
                        out(f"CAP REACHED ({cap.count}/{max_calls}): the call in progress was "
                            "refused, not made; partial results are written.")
                else:
                    s = verdict.scores
                    scores = {"correctness": s.llm_correctness_opinion, "approach": s.approach,
                              "readability": s.readability, "idiomatic": s.idiomatic}
                    unmatched = any(f.get("kind") == validation.UNMATCHED_QUOTE
                                    for f in (failures or []))
                    unmatched_verdicts += unmatched
                    observations.append({"submission": path.name, "run": i, "scores": scores})
                    row.update(status="ok", scores=scores, verdict=verdict.model_dump(),
                               evidence_failures=failures or [],
                               records=_record_dicts(log[before:]))
                    out(f"  {path.name} run {i}: {scores}"
                        + (" (unmatched quote)" if unmatched else ""))
                raw_rows.append(row)
                raw_file.write(json.dumps(row, ensure_ascii=False) + "\n")
                raw_file.flush()                       # a crash or Ctrl-C still leaves the rows
                if stopped:
                    break

    records = list(log[log_start:])
    stats = _gateway_stats(records)
    live = [r for r in records if not r.cache_hit]
    tokens_by_model: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in live:
        tokens_by_model[r.model][0] += r.tokens_in
        tokens_by_model[r.model][1] += r.tokens_out
    ok_runs = len(observations)
    cost = estimate_cost(stats["tokens_in"], stats["tokens_out"], price_in, price_out)
    summary = {
        "meta": {
            "started_at": f"{started:%Y-%m-%d %H:%M}", "provider": provider,
            "models_served": sorted({r.model for r in live}),
            "prompt_version": prompts.PROMPT_VERSION,
            "submissions": [p.name for p in files], "runs": runs, "reference": reference,
            "calls_made": cap.count, "max_calls": max_calls, "worst_case": plan.max_total,
            "stopped_at_cap": stopped, "judge_runs_planned": plan.judges,
            "judge_runs_ok": ok_runs, "judge_runs_failed": failed,
            "results_dir": str(run_dir.relative_to(Path(__file__).resolve().parent.parent))
            if run_dir.is_relative_to(Path(__file__).resolve().parent.parent) else str(run_dir),
            "command": command,
        },
        "agreement": compare(observations, truth, _non_applicable()),
        "stability": stability(observations),
        "gateway": stats,
        "evidence": {"verdicts": ok_runs, "with_unmatched_quote": unmatched_verdicts},
        "latency_mean_s": (sum(r.elapsed_s for r in live) / len(live)) if live else None,
        "tokens_per_run": (f"{stats['tokens_in'] // ok_runs} / {stats['tokens_out'] // ok_runs}"
                           if ok_runs else "n/a"),
        "tokens_by_model": {m: {"in": v[0], "out": v[1]} for m, v in tokens_by_model.items()},
        "tokens_by_model_text": "; ".join(f"{m}: {v[0]} in, {v[1]} out"
                                          for m, v in sorted(tokens_by_model.items())) or "none",
        "estimated_cost_usd": cost,
        "cost_text": (f"{cost:.4f} USD at {price_in} / {price_out} USD per million tokens in / out "
                      "(prices supplied by the user, not verified by the repo)"
                      if cost is not None else
                      "not computed: no verified price supplied (TODO(verify)); recompute from the "
                      "tokens by model"),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (run_dir / "confusion.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["criterion", "label", "judge_0", "judge_2", "judge_4"])
        for crit in (*CRITERIA, "overall"):
            table = (summary["agreement"]["overall"] if crit == "overall"
                     else summary["agreement"]["per_criterion"][crit])["confusion"]
            for t in LEVELS:
                writer.writerow([crit, t, *(table[str(t)][str(j)] for j in LEVELS)])
    text = render_recommendation(summary)
    (run_dir / "RECOMMENDATION.md").write_text(text, encoding="utf-8")
    if ok_runs:
        (recommendation_path or RECOMMENDATION_PATH).write_text(text, encoding="utf-8")
    out("")
    out(f"provider calls made: {cap.count} (cap {max_calls}); judge runs finished: {ok_runs}/"
        f"{plan.judges}; tokens {stats['tokens_in']} in, {stats['tokens_out']} out")
    out(f"results: {run_dir}")
    out(f"recommendation: {recommendation_path or RECOMMENDATION_PATH}"
        + ("" if ok_runs else " (NOT written: no run finished)"))
    out(f"*** {BANNER} ***")
    return EXIT_CAPPED if stopped else EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--max-calls", type=int, required=True,
                        help="hard cap on real provider calls (required)")
    parser.add_argument("--runs", type=int, default=3,
                        help="judge runs per submission (default 3, BUILD_PLAN 4.5)")
    parser.add_argument("--only", default=None, help="one submission file, e.g. clean.py")
    parser.add_argument("--confirm-billed-run", action="store_true",
                        help="really call the provider (without it: print the plan, call nothing)")
    parser.add_argument("--allow-partial", action="store_true",
                        help="accept a cap below the worst case: stop cleanly at the cap")
    parser.add_argument("--reference", default="clean.py",
                        help="submission given to the judge as the reference solution, or 'none' "
                             "(default clean.py, as run_benchmark.py)")
    parser.add_argument("--price-in-per-mtok", type=float, default=None,
                        help="USD per million input tokens (from the provider's price page)")
    parser.add_argument("--price-out-per-mtok", type=float, default=None,
                        help="USD per million output tokens")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = "python -m benchmark.run_real_benchmark " + " ".join(argv or sys.argv[1:])
    return run(runs=args.runs, only=args.only, max_calls=args.max_calls, env=os.environ,
               confirm=args.confirm_billed_run, allow_partial=args.allow_partial,
               reference=args.reference, price_in=args.price_in_per_mtok,
               price_out=args.price_out_per_mtok, command=command.strip())


if __name__ == "__main__":
    sys.exit(main())

