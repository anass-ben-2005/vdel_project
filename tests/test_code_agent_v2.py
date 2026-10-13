"""D-109 -- the Code Agent v2 (`--agents-v2`): production prompt, once per attempt, instructor
section, and the locked "Going further" section.

Fake LLM only: every provider handler is replaced by one that raises, the model is a `FakeLLM`,
nothing is posted anywhere, and the database is the throwaway test one in a rolled-back
transaction.
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agents import code_agent, going_further, prompts
from agents import fake_llm as fl
from agents.budget import CallBudget, UsageLedger
from config import judging
from memory.memory import Memory
from scripts import code_agent_report as report
from scripts import post_feedback as pf
from scripts import run_cycle as rc
from system import db
from tests.test_code_agent_hardening import submission_of
from tests.test_run_cycle import make_student, roster_for
from tests.test_with_code_agent import SolvedGitHub, TwoCommitGitHub, verdicts

ROOT = Path(__file__).resolve().parent.parent
TASK = "Return only records where record.get('temp') is not None."
CODE = "def f(records):\n    return [r for r in records if r.get('temp') is not None]\n"


@pytest.fixture(autouse=True)
def no_live_provider(monkeypatch, tmp_path):
    from system import llm as gateway

    def blocked(*args, **kwargs):
        raise AssertionError("LIVE PROVIDER CALL attempted in a test")

    for provider in list(gateway._PROVIDER_HANDLERS):
        monkeypatch.setitem(gateway._PROVIDER_HANDLERS, provider, blocked)
    monkeypatch.setattr(rc, "DEFAULT_LEDGER_PATH", tmp_path / "default_llm_usage.json")


needs_db = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; needs the test DB"
)


@pytest.fixture
def conn():
    try:
        c = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    yield c
    c.rollback()
    c.close()


def production_fake(*, approach=2, readability=4, feedback="Name the helper after what it does."):
    """Answers a PRODUCTION prompt (no correctness) or, if asked, a benchmark one."""

    def answer(prompt: str) -> str:
        benchmark = "llm_correctness_opinion" in prompt
        used = (["correctness"] if benchmark else []) + ["approach", "readability"]
        lines = [
            ln.strip()
            for ln in submission_of(prompt).splitlines()
            if ln.strip() and not ln.strip().startswith("[...")
        ]
        quote = max(lines, key=len)
        scores = {"approach": approach, "readability": readability}
        if benchmark:
            scores["llm_correctness_opinion"] = 2
        return json.dumps(
            {
                "evidence": {c: [{"quote": quote, "why": "w"}] for c in used},
                "scores": scores,
                "misconceptions": [],
                "feedback_for_student": feedback,
                "confidence": "low",
            }
        )

    return fl.FakeLLM(default=answer)


# --- the prompt: production versus benchmark --------------------------------------------------


def test_the_production_prompt_has_no_correctness_opinion_and_no_reference():
    text = prompts.build_grading_prompt(
        TASK, CODE, criteria=("approach", "readability"), production=True
    )
    assert "llm_correctness_opinion" not in text and "Reference solution" not in text
    assert "Judge correctness before readability" not in text
    assert "Every hidden check of the course has already PASSED" in text
    assert "Correctness\n  0" not in text and "Approach & logic" in text
    assert '"approach"' in text and '"readability"' in text
    assert prompts.PRODUCTION_PROMPT_VERSION == "v4" and prompts.PROMPT_VERSION == "v3"


def test_the_benchmark_prompt_keeps_both_and_is_the_old_text():
    text = prompts.build_grading_prompt(TASK, CODE, reference="REFERENCE-BODY")
    assert "llm_correctness_opinion" in text and "Reference solution" in text
    assert "REFERENCE-BODY" in text and "Judge correctness before readability" in text
    assert "Every hidden check of the course" not in text
    # no production flag, no change: identical to asking for production=False explicitly
    assert text == prompts.build_grading_prompt(
        TASK, CODE, reference="REFERENCE-BODY", production=False
    )


def test_the_production_prompt_refuses_a_reference_and_the_correctness_criterion():
    with pytest.raises(ValueError, match="reference"):
        prompts.build_grading_prompt(
            TASK, CODE, criteria=("approach",), reference="R", production=True
        )
    with pytest.raises(ValueError, match="correctness"):
        prompts.build_grading_prompt(TASK, CODE, production=True)  # all four criteria


@needs_db
def test_grade_in_production_mode_stores_a_v4_verdict_with_no_opinion(conn, tmp_path):
    make_student(conn, "_cyc_a")
    path = tmp_path / "f.py"
    path.write_text(CODE, encoding="utf-8")
    fake = production_fake()
    assignment = {
        "assignment_id": "weather_etl_transform",
        "task": TASK,
        "concepts": [],
        "criteria": ["correctness", "approach", "readability"],
    }
    verdict, trace_id, failures = code_agent.grade(
        Memory(),
        "_cyc_a",
        assignment,
        str(path),
        conn=conn,
        llm_client=fake,
        profile_snapshot={"mastery": {}},
        production=True,
    )
    assert failures is None and trace_id
    assert verdict.scores.llm_correctness_opinion is None
    assert (verdict.scores.approach, verdict.scores.readability) == (2, 4)
    prompt = fake.prompts[0]
    assert "llm_correctness_opinion" not in prompt and "Reference solution" not in prompt
    cur = conn.cursor()
    cur.execute("SELECT payload FROM traces WHERE trace_id = %s", (trace_id,))
    (payload,) = cur.fetchone()
    assert payload["agent"] == "code_agent_v4" and payload["prompt_version"] == "v4"
    assert payload["mode"] == "production" and payload["research_only"] == []
    assert payload["criteria"] == ["approach", "readability"]
    assert payload["scores"]["llm_correctness_opinion"] is None
    assert payload["reference_supplied"] is False


@needs_db
def test_grade_in_production_mode_refuses_a_reference_and_an_empty_criteria_list(conn, tmp_path):
    path = tmp_path / "f.py"
    path.write_text(CODE, encoding="utf-8")
    assignment = {"assignment_id": "weather_etl_transform", "task": TASK, "concepts": []}
    fake = fl.FakeLLM([])
    with pytest.raises(ValueError, match="reference"):
        code_agent.grade(
            Memory(),
            "_cyc_a",
            assignment,
            str(path),
            conn=conn,
            llm_client=fake,
            profile_snapshot={"mastery": {}},
            production=True,
            reference="R",
        )
    with pytest.raises(ValueError, match="no criterion left"):
        code_agent.grade(
            Memory(),
            "_cyc_a",
            assignment,
            str(path),
            conn=conn,
            llm_client=fake,
            profile_snapshot={"mastery": {}},
            production=True,
            criteria=["correctness"],
        )
    assert fake.call_count == 0


@needs_db
def test_the_default_path_is_still_the_v3_benchmark_mode(conn, tmp_path):
    """No `production`: the opinion is asked for, a reference is accepted, the payload is v3's."""
    make_student(conn, "_cyc_a")
    path = tmp_path / "f.py"
    path.write_text(CODE, encoding="utf-8")
    fake = production_fake()
    assignment = {"assignment_id": "weather_etl_transform", "task": TASK, "concepts": [],
                  "criteria": ["correctness", "approach", "readability"]}
    _, trace_id, _ = code_agent.grade(
        Memory(),
        "_cyc_a",
        assignment,
        str(path),
        conn=conn,
        llm_client=fake,
        profile_snapshot={"mastery": {}},
        reference="REFERENCE-BODY",
    )
    assert "llm_correctness_opinion" in fake.prompts[0] and "REFERENCE-BODY" in fake.prompts[0]
    cur = conn.cursor()
    cur.execute("SELECT payload FROM traces WHERE trace_id = %s", (trace_id,))
    (payload,) = cur.fetchone()
    assert payload["agent"] == "code_agent_v3" and payload["prompt_version"] == "v3"
    assert "mode" not in payload and payload["research_only"] == ["scores.llm_correctness_opinion"]
    assert payload["reference_supplied"] is True


# --- once per attempt, on the commit that freezes it -----------------------------------------


def cycle(conn, gh, sid, *, fake, **kw):
    lines: list[str] = []
    result = rc.run_cycle(
        roster_for(sid),
        student=sid,
        conn=conn,
        collect=gh.collect,
        checkout=gh.checkout,
        out=lines.append,
        llm=fake,
        ledger=UsageLedger(),
        with_llm=True,
        with_code_agent=True,
        **kw,
    )
    return result, lines


@needs_db
def test_v2_judges_the_commit_that_freezes_the_attempt_once(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = TwoCommitGitHub(tmp_path)  # push 1 fails two checks (stubs), push 2 passes all
    fake = production_fake()

    result, lines = cycle(conn, gh, "_cyc_a", fake=fake, agents_v2=True)

    assert (
        result.exit_code == 0 and result.students[0].graded == 2 and result.students[0].frozen == 1
    )
    ((_, payload),) = verdicts(conn, "_cyc_a")
    assert payload["commit_sha"] == "e" * 40 and payload["agent"] == "code_agent_v4"
    assert payload["mode"] == "production" and "production v4" in "\n".join(lines)
    code_prompts = [p for p in fake.prompts if "<<<BEGIN SUBMISSION>>>" in p]
    assert len(code_prompts) == 1 and "llm_correctness_opinion" not in code_prompts[0]
    # the failing push got the v2 Feedback Agent (stubs only here: no provider call at all)
    assert "feedback_agent_v2=deterministic_stub" in "\n".join(lines)
    again, _ = cycle(conn, gh, "_cyc_a", fake=fake, agents_v2=True)
    assert again.students[0].graded == 0 and len(verdicts(conn, "_cyc_a")) == 1


@needs_db
def test_v2_does_not_judge_a_passing_commit_that_did_not_freeze_the_attempt(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = SolvedGitHub(tmp_path)
    fake = production_fake()
    cycle(conn, gh, "_cyc_a", fake=fake)  # v1 first: it judges (flag off)
    cur = conn.cursor()
    cur.execute("SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a'")
    (attempt_id,) = cur.fetchone()
    hook = rc.AgentsHook(
        fake,
        CallBudget(max_calls=10),
        Memory(),
        lambda text: lines.append(text),
        20,
        code_agent=True,
        agents_v2=True,
    )
    lines: list[str] = []
    p = SimpleNamespace(
        student_id="_cyc_a",
        assignment_id="weather_etl_transform",
        attempt_id=attempt_id,
        sha="f" * 40,
    )
    not_frozen = SimpleNamespace(tests_total=5, tests_passed=5, frozen=False)
    hook._code(cur, p, tmp_path, not_frozen)
    assert any(
        "did not freeze this attempt" in ln or "did not freeze the attempt" in ln for ln in lines
    )
    # the attempt already has a verdict (the v1 one): a frozen commit is not judged again either
    frozen = SimpleNamespace(tests_total=5, tests_passed=5, frozen=True)
    lines.clear()
    calls = fake.call_count
    hook._code(cur, p, tmp_path, frozen)
    assert any("already judged this attempt" in ln for ln in lines)
    assert fake.call_count == calls


@needs_db
def test_flag_off_the_code_agent_is_the_d104_one(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = SolvedGitHub(tmp_path)
    fake = production_fake()
    cycle(conn, gh, "_cyc_a", fake=fake)  # --with-code-agent, no --agents-v2
    ((_, payload),) = verdicts(conn, "_cyc_a")
    assert payload["agent"] == "code_agent_v3" and payload["prompt_version"] == "v3"
    assert "mode" not in payload
    assert "llm_correctness_opinion" in next(p for p in fake.prompts if "<<<BEGIN" in p)


# --- the instructor section ------------------------------------------------------------------


def row(**over):
    base = {
        "trace_id": 1,
        "student": "anas",
        "assignment": "weather_etl_transform",
        "attempt_id": 3,
        "commit": "abcdef1234",
        "scores": {"approach": 2, "readability": 4},
        "rejected": False,
        "tests": (5, 5),
        "prompt_version": "v4",
        "marked": True,
        "approach_note": "'return x': works but awkward",
    }
    base.update(over)
    return base


def test_the_instructor_section_lists_correct_but_weak_approach_rows():
    lines = report.instructor_section(
        [
            row(),
            row(trace_id=2, marked=False, student="no"),
            row(trace_id=3, rejected=True, student="zz_rej"),
        ]
    )
    text = "\n".join(lines)
    assert "CORRECT BUT APPROACH <= 2" in text and "instructor only" in text
    assert "trace 1  anas  weather_etl_transform  attempt 3  commit abcdef1234" in text
    assert "approach 2  readability 4  tests 5/5  prompt v4" in text
    assert "judge: 'return x': works but awkward" in text
    assert "no" not in [ln.split()[3] for ln in lines if ln.startswith("- trace")]  # not marked
    assert "zz_rej" not in text and "(1 rejected row(s) not listed)" in text


def test_the_instructor_section_says_none_when_there_is_nothing():
    assert "none" in "\n".join(report.instructor_section([row(marked=False)]))
    assert "none (1 rejected row(s) not listed)" in "\n".join(
        report.instructor_section([row(rejected=True)])
    )


def test_the_report_script_prints_the_section_and_stays_read_only():
    source = (ROOT / "scripts" / "code_agent_report.py").read_text(encoding="utf-8")
    assert "instructor_section(found)" in source and "readonly=True" in source


@needs_db
def test_the_report_rows_carry_the_judges_reason(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = SolvedGitHub(tmp_path)
    cycle(conn, gh, "_cyc_a", fake=production_fake(), agents_v2=True)
    cur = conn.cursor()
    mine = list(report.rows(cur, student="_cyc_a"))
    assert mine and mine[0]["marked"] and mine[0]["approach_note"]
    assert "CORRECT BUT APPROACH <= 2" in "\n".join(report.instructor_section(mine))


# --- "Going further": built, locked, posted by nothing ---------------------------------------


def block(exact):
    return {"with_non_applicable": {"exact": exact}}


def result_file(
    root: Path, name: str, *, overall=0.9, approach=0.9, readability=0.9, ok=15, stopped=False
):
    (root / name).mkdir(parents=True)
    (root / name / "summary.json").write_text(
        json.dumps(
            {
                "meta": {"judge_runs_ok": ok, "stopped_at_cap": stopped},
                "agreement": {
                    "overall": block(overall),
                    "per_criterion": {
                        "approach": block(approach),
                        "readability": block(readability),
                    },
                },
            }
        ),
        encoding="utf-8",
    )


ON = judging.PostReview(True, 0.80)


def test_the_shipped_config_is_disabled_with_the_documented_threshold():
    cfg = judging.post_review()
    assert cfg.enabled is False and cfg.min_benchmark_agreement == 0.80
    decision = going_further.check_gate()
    assert decision.allowed is False and "enabled is false" in decision.reason


def test_enabled_with_no_result_file_is_refused(tmp_path):
    decision = going_further.check_gate(config=ON, results_root=tmp_path)
    assert not decision.allowed and "no usable benchmark result" in decision.reason


def test_enabled_but_below_the_threshold_is_refused_and_says_where(tmp_path):
    result_file(
        tmp_path, "r1", overall=0.85, approach=0.60, readability=1.0
    )  # the real run's shape
    decision = going_further.check_gate(config=ON, results_root=tmp_path)
    assert not decision.allowed
    assert "approach 60%" in decision.reason and "overall 85%" in decision.reason
    with pytest.raises(going_further.GoingFurtherRefused, match="min_benchmark_agreement"):
        going_further.require_allowed(config=ON, results_root=tmp_path)


def test_enabled_and_met_on_overall_approach_and_readability_is_allowed(tmp_path):
    result_file(tmp_path, "old", overall=0.5, approach=0.5, readability=0.5)
    result_file(tmp_path, "new", overall=0.85, approach=0.80, readability=0.93)
    decision = going_further.check_gate(config=ON, results_root=tmp_path)
    assert decision.allowed and decision.evidence.endswith("summary.json")


def test_a_partial_or_empty_run_and_a_run_missing_a_criterion_never_open_the_gate(tmp_path):
    result_file(tmp_path, "a_cap", stopped=True)
    result_file(tmp_path, "b_empty", ok=0)
    (tmp_path / "c_broken").mkdir()
    (tmp_path / "c_broken" / "summary.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "d_no_criteria").mkdir()
    (tmp_path / "d_no_criteria" / "summary.json").write_text(
        json.dumps(
            {
                "meta": {"judge_runs_ok": 5},
                "agreement": {"overall": {"with_non_applicable": {"exact": 1.0}}},
            }
        ),
        encoding="utf-8",
    )
    assert not going_further.check_gate(config=ON, results_root=tmp_path).allowed


def test_the_one_real_benchmark_result_does_not_meet_the_gate():
    real = sorted((ROOT / "benchmark" / "results").glob("*/summary.json"))
    if not real:
        pytest.skip("no real benchmark result on this machine")
    summary = json.loads(real[-1].read_text(encoding="utf-8"))
    approach = summary["agreement"]["per_criterion"]["approach"]["with_non_applicable"]["exact"]
    if approach >= 0.80:
        pytest.skip("the recorded run now meets the threshold on approach")
    # the recorded run reached 60% exact on approach: the gate must stay closed on it
    assert not going_further.check_gate(config=ON).allowed


def verdict_payload(**over):
    payload = {
        "rejected": False,
        "flagged": False,
        "scores": {"approach": 2, "readability": 4, "llm_correctness_opinion": None},
        "feedback_for_student": "Consider naming the helper after what it returns, so the "
        "call site reads like a sentence.",
    }
    payload.update(over)
    return payload


ALLOWED = going_further.Decision(True, "test", "synthetic")


def test_the_section_is_refused_while_the_gate_is_closed_which_is_the_default():
    with pytest.raises(going_further.GoingFurtherRefused):
        going_further.build_section(verdict_payload())
    with pytest.raises(going_further.GoingFurtherRefused):
        going_further.build_section(
            verdict_payload(), decision=going_further.Decision(False, "closed")
        )


def test_an_open_gate_builds_a_section_with_no_score_and_a_disclaimer():
    text = going_further.build_section(verdict_payload(), decision=ALLOWED)
    assert text.startswith("### Going further (optional, written by an AI assistant)")
    assert "naming the helper" in text and "not a grade" in text
    assert "decide whether your code is correct" in text
    assert "llm_correctness_opinion" not in text
    assert not any(ch.isdigit() for ch in text)  # no score, no number at all


@pytest.mark.parametrize(
    "over",
    [
        {"rejected": True},
        {"flagged": True},
        {"scores": {"approach": 4, "readability": 4}},
        {"feedback_for_student": ""},
        {"feedback_for_student": "See https://example.org for the idea."},
        {"feedback_for_student": "Your code is correct but could be shorter."},
        {"feedback_for_student": "You have mastered list comprehensions."},
        {"feedback_for_student": "I would give this approach 2/4 as it stands."},
        {"feedback_for_student": " ".join(["word"] * (going_further.MAX_WORDS + 1))},
    ],
)
def test_unsafe_or_useless_verdicts_yield_no_section(over):
    assert going_further.build_section(verdict_payload(**over), decision=ALLOWED) is None


def test_hidden_test_source_in_the_text_yields_no_section():
    hidden = pf.hidden_source_lines("weather_etl")
    line = sorted(hidden, key=len)[-1]
    payload = verdict_payload(feedback_for_student=f"Try it like this: {line}")
    assert going_further.build_section(payload, decision=ALLOWED, hidden=hidden) is None


def test_nothing_else_in_the_repository_calls_the_section():
    found = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", ".venv", "venv/", "build/")) or "site-packages" in rel:
            continue
        if "going_further" in path.read_text(encoding="utf-8") and rel != "agents/going_further.py":
            found.append(rel)
    assert found == [], found
    for script in (ROOT / "scripts").rglob("*"):
        if script.suffix in (".py", ".ps1"):
            assert "going_further" not in script.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "raw, needle",
    [
        ({"enabled": "yes"}, "true or false"),
        ({"min_benchmark_agreement": 0}, "must be a number in"),
        ({"min_benchmark_agreement": 1.5}, "must be a number in"),
        ({"min_benchmark_agreement": True}, "must be a number in"),
        ({"extra": 1}, "expected"),
        ("on", "expected"),
    ],
)
def test_a_malformed_post_review_section_fails_loudly(tmp_path, raw, needle):
    import yaml

    p = tmp_path / "j.yaml"
    p.write_text(yaml.safe_dump({"version": 1, "post_review": raw}), encoding="utf-8")
    judging._load_post_review.cache_clear()
    with pytest.raises(judging.JudgingError, match=needle):
        judging.post_review(p)
    judging._load_post_review.cache_clear()


def test_a_missing_post_review_section_means_disabled(tmp_path):
    p = tmp_path / "j.yaml"
    p.write_text("version: 1\n", encoding="utf-8")
    judging._load_post_review.cache_clear()
    assert judging.post_review(p) == judging.PostReview(False, 0.80)
    judging._load_post_review.cache_clear()
