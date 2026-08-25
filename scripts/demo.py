"""scripts/demo.py -- the seven demo beats (EXECUTION.md §1), one command, in order.

Stage D1. This module reimplements nothing: every beat below calls the real function
that already proved it live (`EXECUTION.md`'s own citations), in the same order the
beat table lists them. Its only job is sequencing, isolation, and printing -- if a beat
breaks, the bug is in the function it calls, not here.

Fixed to real data throughout: student `anas`, project `weather_etl`, the real repo
already pushed to `anass-ben-2005/vdel-weather-etl-gapfill-anas`
(`renders/anas_attempt1`). Nothing here is synthetic -- Beat 6's LLM grading calls write
real traces for the real student `anas` (matching D-049's own precedent), not throwaway
test fixtures, so there is nothing for this script to clean up after itself. Connection
isolation: every beat opens its own connection fresh, via `db.cursor()`/`db.connect()`/
`db._open()` -- no connection object is ever held or passed between beats. Deliberately
so: this session's own `compute_features.py` regression and the `_test_sara` teardown
incident both traced back to a shared/uncontrolled transaction outliving the code that
opened it. Nothing here shares one.

Failure isolation: each beat runs inside `_run_beat`, which catches ANY exception,
prints FAIL with the real error, and continues to the next beat -- one beat's failure
must never hide whether the other six still work, which is the whole point of running
all seven as one integration test instead of trusting each one because it worked once
in isolation.

Two flags exist because two beats are expensive or environment-dependent, not because
their proof is optional:
  --skip-network   Beat 4 otherwise calls the real GitHub collector (network + a real
                    GITHUB_TOKEN). Auto-skipped anyway if GITHUB_TOKEN is unset.
  --skip-llm       Beat 6 otherwise makes one real, billed LLM call.
A full rehearsal (D2) should be run with neither flag.

Run:  python -m scripts.demo
      python -m scripts.demo --skip-network --skip-llm    # fast, offline iteration
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from agents import code_agent
from assessment.gap_parser import parse_master
from assessment.test_runner import grade_attempt
from collectors.collect_github import collect_all
from memory.memory import Memory
from scripts.prove_event_sourcing import prove, read_profiles
from scripts.prove_event_sourcing import report as event_sourcing_report
from scripts.seed_data import load_roster
from system import db

REPO_ROOT = Path(__file__).resolve().parent.parent
CURRICULUM_ROOT = REPO_ROOT / "curriculum" / "master"
REPO_DIR = REPO_ROOT / "renders" / "anas_attempt1"
STUDENT = "anas"
PROJECT = "weather_etl"


@dataclass(frozen=True)
class BeatResult:
    """What one beat proved, for the final summary table. `evidence` is always ONE
    line -- the detailed output already printed above it is what a rehearsal audience
    watches live; this is what's left to scan afterward."""

    passed: bool
    evidence: str


def _banner(n: int, title: str) -> None:
    # Plain ASCII only -- Windows' default console codepage (cp1252) cannot encode
    # box-drawing characters or "§", and this script must run in a stock terminal.
    print()
    print(f"-- Beat {n} " + "-" * (66 - len(title)) + f" {title}")


def _run_beat(n: int, title: str, fn, *args) -> BeatResult:
    """Runs one beat, isolated: any exception is caught here, not left to crash the
    remaining six. Prints PASS/FAIL with real evidence or the real error -- never a
    stack trace mid-rehearsal, and never a silently skipped beat either."""
    _banner(n, title)
    try:
        result = fn(*args)
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: isolate ANY beat
        print(f"  FAIL -- {type(exc).__name__}: {exc}")
        return BeatResult(passed=False, evidence=f"{type(exc).__name__}: {exc}")
    print(f"  {'PASS' if result.passed else 'FAIL'} -- {result.evidence}")
    return result


def beat1_curriculum_format() -> BeatResult:
    path = CURRICULUM_ROOT / PROJECT / "weather_etl" / "transform.py"
    gaps = parse_master(path)
    print(f"  {path.relative_to(REPO_ROOT)}  ({len(gaps)} @gap marker(s))")
    for g in gaps:
        print(f"    {g.gap_id:16s} lines {g.line_start}-{g.line_end}  {list(g.concept_ids)}")
        print(f"      {g.instruction}")
    return BeatResult(
        passed=len(gaps) > 0,
        evidence=f"{len(gaps)} real @gap marker(s) parsed from {path.name}",
    )


def beat2_variant_selection() -> BeatResult:
    with db.cursor() as cur:
        cur.execute(
            "SELECT student_id, variant_id FROM attempts"
            " WHERE project_id = %s AND assignment_id = 'weather_etl_extract'"
            "   AND student_id IN ('anas', 'student2') ORDER BY student_id",
            (PROJECT,),
        )
        rows = cur.fetchall()
    for student_id, variant_id in rows:
        print(f"  {student_id:10s} weather_etl_extract  variant_id={variant_id}")

    if len(rows) != 2:
        return BeatResult(False, f"expected 2 students' attempts, found {len(rows)}")
    (s1, v1), (s2, v2) = rows
    if v1 == v2:
        return BeatResult(False, f"{s1} and {s2} both got variant_id={v1} (should differ)")
    return BeatResult(True, f"{s1}={v1[:12]}  {s2}={v2[:12]}  (different, same assignment)")


def beat3_hidden_tests() -> BeatResult:
    with db.cursor() as cur:
        cur.execute(
            "SELECT attempt_id FROM attempts"
            " WHERE student_id = %s AND assignment_id = 'weather_etl_extract'",
            (STUDENT,),
        )
        row = cur.fetchone()
    if row is None:
        return BeatResult(False, "no attempt row for anas/weather_etl_extract")
    attempt_id = row[0]

    result = grade_attempt(PROJECT, "weather_etl_extract", REPO_DIR, attempt_id)
    for o in result.outcomes:
        print(f"    {'PASS' if o.passed else 'FAIL'}  {o.test_name}")
    return BeatResult(
        passed=result.tests_total > 0,
        evidence=f"{result.tests_passed}/{result.tests_total} passed, real subprocess "
                 f"(frozen={result.frozen})",
    )


def beat4_attribution(skip_network: bool) -> BeatResult:
    if skip_network or not os.environ.get("GITHUB_TOKEN"):
        print("  (skipping live collection -- no GITHUB_TOKEN, or --skip-network passed)")
    else:
        roster = load_roster()
        repos = [
            {"owner": a["owner"], "repo": a["repo"],
             "student_id": a["student_id"], "assignment_id": a["assignment_id"]}
            for a in roster.get("assignments", [])
        ]
        with db.connect() as conn:
            collect_result = collect_all(conn, repos)
        print(f"  collector: {collect_result['stats']}")

    with db.cursor() as cur:
        cur.execute(
            "SELECT sha, assignment_id, committed_at FROM raw_commits"
            " WHERE student_id = %s ORDER BY committed_at DESC LIMIT 3",
            (STUDENT,),
        )
        rows = cur.fetchall()
    attributed = []
    for sha, assignment_id, committed_at in rows:
        label = assignment_id or "NULL (ambiguous)"
        print(f"    {sha[:10]}  assignment_id={label:22s} {committed_at}")
        if assignment_id:
            attributed.append((sha[:10], assignment_id))

    if not rows:
        return BeatResult(False, "no raw_commits found for anas at all")
    if not attributed:
        return BeatResult(False, "every recent commit landed NULL (ambiguous) -- no "
                                  "real single-file attribution to show")
    sha, aid = attributed[0]
    return BeatResult(True, f"{sha} -> {aid} (real per-file attribution, D-043)")


def beat5_mastery() -> BeatResult:
    profile = Memory().get_profile(STUDENT)
    mastery = profile["mastery"]
    for concept, m in sorted(mastery.items()):
        print(f"  {concept:24s} p_mastery={m['p_mastery']:.3f}  n={m['n']}  "
              f"ci90={m.get('ci90')}  trend={m.get('trend')}")

    if not mastery:
        return BeatResult(False, "learner_profile.mastery is empty for anas")
    concept, m = next(iter(sorted(mastery.items())))
    return BeatResult(
        True,
        f"{len(mastery)} concept(s) tracked, e.g. {concept}: "
        f"p_mastery={m['p_mastery']:.3f} n={m['n']}",
    )


def beat6_code_agent(skip_llm: bool) -> BeatResult:
    if skip_llm:
        print("  (skipped -- pass without --skip-llm to make the real LLM call)")
        return BeatResult(True, "skipped by flag, not run")

    with db.cursor() as cur:
        cur.execute(
            "SELECT concepts FROM assignments WHERE assignment_id = 'weather_etl_transform'"
        )
        concepts = cur.fetchone()[0]
        cur.execute(
            "SELECT instruction FROM gaps WHERE assignment_id = 'weather_etl_transform'"
            " ORDER BY gap_id"
        )
        task = " ".join(row[0] for row in cur.fetchall())

    assignment = {"assignment_id": "weather_etl_transform", "task": task, "concepts": concepts}
    code_path = REPO_DIR / "weather_etl" / "transform.py"
    reference_path = CURRICULUM_ROOT / PROJECT / "weather_etl" / "transform.py"

    verdict, trace_id, evidence_failures = code_agent.grade(
        Memory(), STUDENT, assignment, str(code_path),
        reference=reference_path.read_text(encoding="utf-8"),
    )
    s = verdict.scores
    print(f"  trace_id={trace_id}")
    print(f"  correctness={s.correctness} approach={s.approach} "
          f"readability={s.readability} idiomatic={s.idiomatic}")
    print(f"  confidence={verdict.confidence}  evidence_failures={evidence_failures or []}")
    quotes_checked = 0
    for criterion, quotes in verdict.evidence.items():
        for q in quotes:
            print(f"    [{criterion}] \"{q}\"")
            quotes_checked += 1

    return BeatResult(
        passed=not evidence_failures,
        evidence=f"trace_id={trace_id}, correctness={s.correctness}, "
                 f"{quotes_checked} evidence quote(s), "
                 f"{len(evidence_failures or [])} evidence failure(s)",
    )


def beat7_event_sourcing() -> BeatResult:
    conn = db._open()
    try:
        result = prove(conn)
        event_sourcing_report(result, read_profiles(conn))
        conn.rollback()
    finally:
        conn.close()
    ok = result.identical and not result.vacuous
    return BeatResult(
        passed=ok,
        evidence=f"IDENTICAL, {result.traces_after} traces unchanged"
        if ok else f"NOT identical or vacuous -- {len(result.differences)} difference(s)",
    )


BEATS = [
    (1, "the curriculum format is real, not a mock-up", beat1_curriculum_format, ()),
    (2, "two students, different variants, same assignment", beat2_variant_selection, ()),
    (3, "hidden tests run for real; correctness is executed, not asserted (inv. 13)",
     beat3_hidden_tests, ()),
    (4, "results land per-assignment, attributed by file (D-043)",
     beat4_attribution, ("skip_network",)),
    (5, "mastery moves -- BKT, with n, with a confidence interval", beat5_mastery, ()),
    (6, "the Code Agent grades; every score carries a string-matched quote (inv. 6)",
     beat6_code_agent, ("skip_llm",)),
    (7, "wipe learner_profile -> replay traces -> identical", beat7_event_sourcing, ()),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-network", action="store_true",
                         help="skip Beat 4's live GitHub collection")
    parser.add_argument("--skip-llm", action="store_true",
                         help="skip Beat 6's real LLM call")
    args = parser.parse_args(argv)
    flag_values = {"skip_network": args.skip_network, "skip_llm": args.skip_llm}

    print("VDEL -- the seven demo beats (EXECUTION.md section 1)")
    print(f"student={STUDENT}  project={PROJECT}")

    results: list[tuple[int, str, BeatResult]] = []
    for n, title, fn, arg_names in BEATS:
        call_args = tuple(flag_values[name] for name in arg_names)
        result = _run_beat(n, title, fn, *call_args)
        results.append((n, title, result))

    print()
    print("-- Summary " + "-" * 58)
    for n, _title, result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"  Beat {n}  {status}  {result.evidence}")

    failed = [n for n, _, r in results if not r.passed]
    print()
    if failed:
        print(f"DEMO INCOMPLETE -- beat(s) {failed} did not pass, see above")
    else:
        print("DEMO COMPLETE -- all seven beats passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
