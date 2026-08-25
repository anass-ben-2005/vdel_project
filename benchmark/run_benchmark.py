"""benchmark/run_benchmark.py -- the M3/M4 stability table and ground-truth agreement check.

EXECUTION.md Stage C3. Two things BUILD_PLAN asks for, both here:
  - M3 DoD: "re-running the benchmark reproduces the matrix" -- run twice, compare.
  - M4 DoD (4.5): "3 runs per benchmark submission... >=80% exact agreement, OR the
    deviation documented with its cause analysed."

Grades every file in `benchmark/submissions/` (except TASK.md) `--runs` times each
(default 3) against the real Code Agent, reports:
  1. Self-consistency -- exact-agreement rate ACROSS this script's own repeated runs of
     the SAME submission. This is measurable with no ground truth at all.
  2. Agreement against `benchmark/ground_truth.json`, IF it has real (non-null) values
     for a submission. Skipped, honestly, for anything still `null` -- Anas's own labels,
     his to decide, never a model's (CLAUDE.md 10). A template with every score `null`
     is not a missing feature here, it is the correct starting state.

Isolation, not pollution: every grade() call in one run of this script shares ONE
connection and is rolled back at the end by default (matching
scripts/prove_event_sourcing.py's own convention) -- a benchmark run must never leave
real traces/mastery evidence behind for a synthetic `_benchmark` actor, the same lesson
this session's compute_features.py regression just paid for the hard way. Pass --commit
only if you deliberately want the verdict traces to persist (e.g. to inspect one in the
DB afterward).

Run:  python -m benchmark.run_benchmark                    # 3 runs/submission, rolled back
      python -m benchmark.run_benchmark --runs 1 --only clean.py   # cheap smoke test
      python -m benchmark.run_benchmark --commit           # persist the verdict traces
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from agents.code_agent import grade
from memory.memory import Memory
from system import db

SUBMISSIONS_DIR = Path(__file__).resolve().parent / "submissions"
GROUND_TRUTH_PATH = Path(__file__).resolve().parent / "ground_truth.json"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
BENCHMARK_STUDENT = "_benchmark"
CRITERIA = ("correctness", "approach", "readability", "idiomatic")

# Paraphrased from TASK.md's own prompt block, per that file's own note ("paraphrased
# into the Code Agent's assembled prompt") -- not re-parsed from the markdown at runtime,
# matching this project's preference for one hand-written copy over a one-off parser.
TASK = (
    "You have a PySpark DataFrame `orders` with one row per order LINE: order_id, "
    "customer_id, order_date (YYYY-MM-DD), product_id, quantity (int), unit_price "
    "(float). One order can have several lines. Write "
    "compute_monthly_revenue(orders: DataFrame) -> DataFrame returning, for every "
    "customer and every calendar month they ordered in: customer_id, month "
    "('YYYY-MM'), total_revenue (sum of quantity*unit_price over every line that "
    "customer-month), order_count (number of DISTINCT ORDERS, not lines, that "
    "customer-month). One row per (customer_id, month) -- nothing else touches the "
    "row count."
)
CONCEPTS = ["spark.aggregation"]


def _load_ground_truth() -> dict:
    if not GROUND_TRUTH_PATH.exists():
        return {}
    return json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8")).get("submissions", {})


def _submissions() -> list[Path]:
    return sorted(p for p in SUBMISSIONS_DIR.glob("*.py"))


BENCHMARK_ASSIGNMENT = "benchmark_monthly_revenue"


def _ensure_benchmark_fixtures(cur) -> None:
    """A dedicated synthetic student and assignment for this script's own grading
    calls, INSERTed inside the same transaction every grade() call in this run shares
    -- never real telemetry, never left behind: the whole transaction rolls back by
    default (see module docstring). Both are real FK targets `traces`/`students`
    require (`traces.assignment_id REFERENCES assignments`, confirmed against the live
    schema, not assumed from CLAUDE.md's abbreviated table listing -- that assumption
    was wrong once already this session, in compute_features.py; checking the live
    schema this time instead of repeating it)."""
    cur.execute(
        "INSERT INTO students (student_id, github_username, cohort)"
        " VALUES (%s, %s, 'benchmark') ON CONFLICT (student_id) DO NOTHING",
        (BENCHMARK_STUDENT, BENCHMARK_STUDENT),
    )
    cur.execute(
        "INSERT INTO assignments (assignment_id, repo_prefix, released_at, concepts)"
        " VALUES (%s, 'benchmark/submissions', now(), %s)"
        " ON CONFLICT (assignment_id) DO NOTHING",
        (BENCHMARK_ASSIGNMENT, CONCEPTS),
    )


def _exact_agreement(score_sets: list[dict[str, int]]) -> dict[str, float]:
    """Per-criterion fraction of runs matching the single most common value -- the
    'exact agreement' BUILD_PLAN 4.5 asks for, computed per criterion since a judge can
    be stable on Correctness and noisy on Readability at once, and collapsing that into
    one number would hide exactly the thing worth knowing."""
    rates = {}
    for criterion in CRITERIA:
        values = [s[criterion] for s in score_sets]
        most_common_count = Counter(values).most_common(1)[0][1]
        rates[criterion] = most_common_count / len(values)
    return rates


def run(*, runs: int, only: str | None, commit: bool) -> dict:
    ground_truth = _load_ground_truth()
    submissions = _submissions()
    if only:
        submissions = [p for p in submissions if p.name == only]
        if not submissions:
            raise SystemExit(f"no submission named {only!r} in {SUBMISSIONS_DIR}")

    reference = (SUBMISSIONS_DIR / "clean.py").read_text(encoding="utf-8")
    mem = Memory()
    assignment = {"assignment_id": BENCHMARK_ASSIGNMENT, "task": TASK,
                  "concepts": CONCEPTS}

    conn = db._open()
    results: dict[str, dict] = {}
    try:
        with conn.cursor() as cur:
            _ensure_benchmark_fixtures(cur)

        for path in submissions:
            print(f"\n{path.name}")
            score_sets = []
            call_errors = []
            for i in range(runs):
                # BUILD_PLAN 4.5's own sanctioned outcome is "stability did not
                # converge, report the real number" -- which this script cannot do at
                # all if one provider hiccup on run 1 of 15 kills the whole sweep and
                # discards every printed-but-uncommitted result before it. A per-call
                # try/except is what makes "5/5 schema-validation failures this
                # session" a number this script can actually finish computing, instead
                # of a traceback. The transaction-wide rollback below still protects
                # against a HALF-written trace; this only protects the SWEEP.
                try:
                    verdict, trace_id, evidence_failures = grade(
                        mem, BENCHMARK_STUDENT, assignment, str(path),
                        reference=reference, conn=conn,
                    )
                except Exception as exc:  # noqa: BLE001 -- recorded, not swallowed
                    call_errors.append(f"{type(exc).__name__}: {exc}")
                    print(f"  run {i + 1}: FAILED -- {type(exc).__name__}: {exc}")
                    continue
                s = verdict.scores
                scores = {"correctness": s.correctness, "approach": s.approach,
                          "readability": s.readability, "idiomatic": s.idiomatic}
                score_sets.append(scores)
                print(f"  run {i + 1}: {scores}  trace_id={trace_id}"
                      f"  evidence_failures={evidence_failures or []}")

            if call_errors:
                print(f"  {len(call_errors)}/{runs} call(s) failed -- see above; this IS "
                      "a stability finding, not a script bug (BUILD_PLAN 4.5's sanctioned "
                      "'deviation documented with its cause analysed' branch)")
            if not score_sets:
                print("  self-consistency: N/A -- every run failed")
                results[path.name] = {"runs": [], "call_errors": call_errors,
                                       "self_consistency": None, "ground_truth_match": None}
                continue

            agreement = _exact_agreement(score_sets)
            print(f"  self-consistency (exact agreement across {len(score_sets)}/{runs} "
                  f"successful run(s)): {agreement}")

            truth = ground_truth.get(path.name, {})
            truth_known = {k: v for k, v in truth.items() if v is not None}
            if truth_known:
                # Ground truth compared against the FIRST run only -- BUILD_PLAN 4.5's
                # target is judge stability across runs, not "does the majority vote
                # happen to match Anas" (a second, different question).
                first = score_sets[0]
                matches = {k: (first[k] == v) for k, v in truth_known.items()}
                print(f"  vs ground_truth (run 1): {matches}")
            else:
                print("  vs ground_truth: skipped -- benchmark/ground_truth.json has no "
                      "real (non-null) values for this submission yet")

            results[path.name] = {
                "runs": score_sets,
                "call_errors": call_errors,
                "self_consistency": agreement,
                "ground_truth_match": matches if truth_known else None,
            }

        if commit:
            conn.commit()
            print("\ncommitted -- verdict traces persisted")
        else:
            conn.rollback()
            print("\nrolled back -- no real traces or mastery evidence left behind "
                  "(pass --commit to persist)")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return results


def _write_results(results: dict) -> Path:
    """Durable, even when the DB transaction rolls back (the default). A finding like
    D-050's 14/15 quota failures otherwise only exists in scrollback -- this is what
    lets `call_errors` survive the process exiting without requiring `--commit`."""
    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3,
                         help="grading runs per submission (BUILD_PLAN 4.5 default: 3)")
    parser.add_argument("--only", default=None,
                         help="grade a single submission file, e.g. clean.py")
    parser.add_argument("--commit", action="store_true",
                         help="persist verdict traces instead of rolling back")
    args = parser.parse_args(argv)

    results = run(runs=args.runs, only=args.only, commit=args.commit)
    out_path = _write_results(results)
    print(f"\nresults written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
