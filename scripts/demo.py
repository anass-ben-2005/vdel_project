"""scripts/demo.py -- the seven demo beats (EXECUTION.md §1), one command, in order.

Stage D1. This module reimplements nothing: every beat below calls the real function
that already proved it live (`EXECUTION.md`'s own citations), in the same order the
beat table lists them. Its only job is sequencing and printing -- if a beat breaks,
the bug is in the function it calls, not here.

Fixed to real data throughout: student `anas`, project `weather_etl`, the real repo
already pushed to `anass-ben-2005/vdel-weather-etl-gapfill-anas`
(`renders/anas_attempt1`). Nothing here is synthetic.

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


def _banner(n: int, title: str) -> None:
    # Plain ASCII only -- Windows' default console codepage (cp1252) cannot encode
    # box-drawing characters or "§", and this script must run in a stock terminal.
    print()
    print(f"-- Beat {n} " + "-" * (66 - len(title)) + f" {title}")


def beat1_curriculum_format() -> None:
    _banner(1, "the curriculum format is real, not a mock-up")
    path = CURRICULUM_ROOT / PROJECT / "weather_etl" / "transform.py"
    gaps = parse_master(path)
    print(f"  {path.relative_to(REPO_ROOT)}  ({len(gaps)} @gap marker(s))")
    for g in gaps:
        print(f"    {g.gap_id:16s} lines {g.line_start}-{g.line_end}  {list(g.concept_ids)}")
        print(f"      {g.instruction}")


def beat2_variant_selection() -> None:
    _banner(2, "two students, different variants, same assignment")
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
    if len(rows) == 2 and rows[0][1] != rows[1][1]:
        print("  -> different variant_ids, both reproducible from (seed, master_version)")
    else:
        print("  -> WARNING: expected two distinct variant_ids, did not find them")


def beat3_hidden_tests():
    _banner(3, "hidden tests run for real; correctness is executed, not asserted (inv. 13)")
    with db.cursor() as cur:
        cur.execute(
            "SELECT attempt_id FROM attempts"
            " WHERE student_id = %s AND assignment_id = 'weather_etl_extract'",
            (STUDENT,),
        )
        attempt_id = cur.fetchone()[0]
    result = grade_attempt(PROJECT, "weather_etl_extract", REPO_DIR, attempt_id)
    print(f"  {result.tests_passed}/{result.tests_total} passed  (frozen={result.frozen})")
    for o in result.outcomes:
        print(f"    {'PASS' if o.passed else 'FAIL'}  {o.test_name}")
    return result


def beat4_attribution(skip_network: bool) -> None:
    _banner(4, "results land per-assignment, attributed by file (D-043)")
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
            result = collect_all(conn, repos)
        print(f"  collector: {result['stats']}")

    with db.cursor() as cur:
        cur.execute(
            "SELECT sha, assignment_id, committed_at FROM raw_commits"
            " WHERE student_id = %s ORDER BY committed_at DESC LIMIT 3",
            (STUDENT,),
        )
        for sha, assignment_id, committed_at in cur.fetchall():
            label = assignment_id or "NULL (ambiguous)"
            print(f"    {sha[:10]}  assignment_id={label:22s} {committed_at}")


def beat5_mastery() -> None:
    _banner(5, "mastery moves -- BKT, with n, with a confidence interval")
    profile = Memory().get_profile(STUDENT)
    for concept, m in sorted(profile["mastery"].items()):
        print(f"  {concept:24s} p_mastery={m['p_mastery']:.3f}  n={m['n']}  "
              f"ci90={m.get('ci90')}  trend={m.get('trend')}")


def beat6_code_agent(skip_llm: bool) -> None:
    _banner(6, "the Code Agent grades; every score carries a string-matched quote (inv. 6)")
    if skip_llm:
        print("  (skipped -- pass without --skip-llm to make the real LLM call)")
        return
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
    for criterion, quotes in verdict.evidence.items():
        for q in quotes:
            print(f"    [{criterion}] \"{q}\"")


def beat7_event_sourcing() -> bool:
    _banner(7, "wipe learner_profile -> replay traces -> identical")
    conn = db._open()
    try:
        result = prove(conn)
        event_sourcing_report(result, read_profiles(conn))
        conn.rollback()
    finally:
        conn.close()
    return result.identical and not result.vacuous


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-network", action="store_true",
                         help="skip Beat 4's live GitHub collection")
    parser.add_argument("--skip-llm", action="store_true",
                         help="skip Beat 6's real LLM call")
    args = parser.parse_args(argv)

    print("VDEL -- the seven demo beats (EXECUTION.md section 1)")
    print(f"student={STUDENT}  project={PROJECT}")

    beat1_curriculum_format()
    beat2_variant_selection()
    beat3_hidden_tests()
    beat4_attribution(args.skip_network)
    beat5_mastery()
    beat6_code_agent(args.skip_llm)
    identical = beat7_event_sourcing()

    print()
    print("DEMO COMPLETE" + ("" if identical else " -- Beat 7 did not report IDENTICAL, see above"))
    return 0 if identical else 1


if __name__ == "__main__":
    sys.exit(main())
