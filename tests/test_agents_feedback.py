"""Stage 5 -- the Feedback Agent, over the fixtures, with the scripted fake provider.

No live call, no network. The pure core (`run_feedback_agent`) is driven by fixtures; one block at
the end uses the test database (one rolled-back transaction) to prove the database glue reads and
writes nothing.
"""
from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

from agents import budget as budget_mod
from agents import fake_llm as fl
from agents import feedback_agent as fa
from agents import feedback_prompts as fp
from agents.budget import CallBudget
from agents.feedback_agent import (
    FeedbackInput,
    FeedbackOutput,
    ResourceCandidate,
    run_feedback_agent,
    validate_output,
)
from scripts import post_feedback as pf
from system import db

FIX = Path(__file__).resolve().parent / "fixtures" / "agents"
V0 = "V0-DETERMINISTIC-TEXT"
RETRY = "test_fetch_weather_retries_then_succeeds"


def fixture(name_part: str) -> dict:
    (path,) = [p for p in FIX.rglob("*.json") if name_part in p.name]
    return json.loads(path.read_text(encoding="utf-8"))


def candidates() -> tuple[ResourceCandidate, ...]:
    data = json.loads((FIX / "synthetic" / "resources_synthetic.json").read_text("utf-8"))
    return tuple(ResourceCandidate(c["resource_id"], c["title"], c["kind"], c["level"],
                                   tuple(c["concept_ids"]), c["locator"], c["url"])
                 for c in data["candidates"])


def inp(name_part="a82__128da3e9", *, cands=True) -> FeedbackInput:
    return FeedbackInput.from_fixture(fixture(name_part), candidates() if cands else ())


HIDDEN = pf.hidden_source_lines("weather_etl")


def good(**over) -> dict:
    body = {
        "summary": "The retry check failed with a ConnectionError, so the retry part of your "
                   "file is the place to look first.",
        "what_to_check_next": ["Re-read the retry instruction in your file.",
                               "Follow what happens after the first failed attempt."],
        "cited_tests": [RETRY],
        "cited_concepts": ["py.errors_debugging"],
        "resource_id": "EXAMPLE-R1",
        "confidence": "medium",
    }
    body.update(over)
    return body


def run(fake, i=None, budget=None, hidden=HIDDEN):
    return run_feedback_agent(i or inp(), fake, budget, hidden=hidden,
                              fallback_markdown=lambda: V0)


# ---- input contract -----------------------------------------------------------------------

def test_input_is_built_from_the_fixture():
    i = inp()
    assert (i.status, i.passed, i.total) == ("ok", 3, 4)
    assert [f.short_name for f in i.failed] == [RETRY]
    assert i.failed[0].exception_type == "ConnectionError"
    assert i.weakest_concept == "py.errors_debugging"
    assert "py.errors_debugging" in i.concepts and "py.data_structures" in i.concepts
    assert i.recurring_gaps == ("g_ext_retry",)
    assert i.citable_tests == {RETRY}


def test_prompt_has_names_and_exception_types_and_nothing_else():
    prompt = fp.build_feedback_prompt(inp())
    assert f"{RETRY}: ConnectionError" in prompt
    assert "EXAMPLE-R1" in prompt and "py.errors_debugging" in prompt
    for forbidden in ("tests/hidden", "Traceback", "def fetch_weather", "assert ", "Error:"):
        assert forbidden not in prompt
    assert not [ln for ln in HIDDEN if ln in prompt]
    assert "EXAMPLE-R1" in prompt and "or null" in prompt


def test_prompt_describes_mastery_as_tone_only_and_handles_an_empty_slice():
    p_empty = fp.build_feedback_prompt(inp("no_mastery"))
    assert "no data for this student" in p_empty
    p_full = fp.build_feedback_prompt(FeedbackInput.from_fixture(
        fixture("multi_failure"), candidates()))
    assert "estimate 0.35" in p_full and "tone only" in p_full


# ---- happy path ---------------------------------------------------------------------------

def test_happy_path_returns_the_validated_object_and_markdown():
    fake = fl.FakeLLM([fl.valid_json(good())])
    budget = CallBudget(max_calls=6)
    res = run(fake, budget=budget)
    assert res.used_llm and res.source == fa.SOURCE_LLM and res.output is not None
    assert isinstance(res.output, FeedbackOutput)
    assert (fake.call_count, fake.judge_count, res.judge_calls, res.calls_made) == (1, 1, 1, 1)
    assert budget.used == 1
    md = res.markdown
    assert "**3 of 4** checks passed." in md
    assert f"- `{RETRY} (test_extract.py)`: ConnectionError" in md      # built by code
    assert "place to look first" in md                                  # the model's words
    assert "Suggested reading: **EXAMPLE: Handling exceptions**" in md  # row from the table
    assert "https://example.invalid/errors" in md
    assert "decide whether your code is correct" in md
    assert res.model and res.provider == "anthropic"


def test_fenced_reply_is_accepted():
    fake = fl.FakeLLM([fl.fenced_json(good())])
    assert run(fake).used_llm and fake.call_count == 1


def test_resource_null_is_accepted_and_shows_no_reading_line():
    res = run(fl.FakeLLM([fl.valid_json(good(resource_id=None))]))
    assert res.used_llm and "Suggested reading" not in res.markdown


def test_test_reference_forms_are_normalised():
    ref = "tests/hidden/test_extract.py::" + RETRY
    res = run(fl.FakeLLM([fl.valid_json(good(cited_tests=[ref]))]))
    assert res.used_llm and res.output.cited_tests == [RETRY]
    res2 = run(fl.FakeLLM([fl.valid_json(good(cited_tests=[f"{RETRY} (test_extract.py)"]))]))
    assert res2.used_llm


def test_all_calls_are_temperature_zero():
    fake = fl.FakeLLM([fl.valid_json(good(cited_tests=["test_nope"])), fl.valid_json(good())])
    run(fake)
    assert {c.temperature for c in fake.calls} == {0.0}


# ---- each rejection rule: one corrective retry, then success ------------------------------

HIDDEN_LINE = min((ln for ln in HIDDEN
                   if len(ln) >= 20 and not ln.startswith(("import ", "from "))), key=len)

BAD = {
    "unknown_test": good(cited_tests=["test_not_in_the_diagnosis"]),
    "unknown_concept": good(cited_concepts=["sql.joins"]),
    "unknown_resource": good(resource_id="EXAMPLE-INVENTED"),
    "hidden_source": good(summary=f"Look at this: {HIDDEN_LINE}"),
    "correctness_claim": good(summary="Your code is correct apart from one retry check."),
    "link_in_text": good(summary="See https://docs.python.org/3/ for the details."),
    "mastery_claim": good(summary="You have not mastered error handling yet."),
}


@pytest.mark.parametrize("rule", sorted(BAD))
def test_a_rejection_triggers_one_corrective_retry_and_then_succeeds(rule):
    fake = fl.FakeLLM([fl.valid_json(BAD[rule]), fl.valid_json(good())])
    res = run(fake)
    assert res.used_llm
    assert [r.rule for r in res.rejections[0]] == [rule]
    assert res.rejections[1] == []
    assert (fake.judge_count, fake.call_count) == (2, 2)
    assert "rejected by an automatic check" in fake.prompts[1] and rule in fake.prompts[1]


@pytest.mark.parametrize("rule", sorted(BAD))
def test_two_rejections_fall_back_to_the_deterministic_text(rule):
    fake = fl.FakeLLM([fl.valid_json(BAD[rule]), fl.valid_json(BAD[rule])])
    res = run(fake)
    assert res.source == fa.SOURCE_FALLBACK and res.markdown == V0 and res.output is None
    assert fake.call_count == 2                       # never a third call
    assert any(r.startswith("rejected") for r in res.reasons)


def test_a_retry_that_fixes_one_rule_but_breaks_another_still_falls_back():
    fake = fl.FakeLLM([fl.valid_json(BAD["unknown_test"]), fl.valid_json(BAD["link_in_text"])])
    res = run(fake)
    assert res.source == fa.SOURCE_FALLBACK and fake.call_count == 2


def test_several_rules_are_reported_together():
    both = good(cited_tests=["test_nope"], resource_id="EXAMPLE-INVENTED")
    rules = {r.rule for r in validate_output(FeedbackOutput(**both), inp(), HIDDEN)}
    assert rules == {"unknown_test", "unknown_resource"}


# ---- hidden source never leaks ------------------------------------------------------------

def test_a_hidden_line_is_never_copied_into_the_retry_prompt_the_trace_or_the_output():
    fake = fl.FakeLLM([fl.valid_json(BAD["hidden_source"]), fl.valid_json(BAD["hidden_source"])])
    res = run(fake)
    assert res.source == fa.SOURCE_FALLBACK
    assert HIDDEN_LINE not in fake.prompts[1]                       # the retry prompt
    payload = json.dumps(res.to_trace_payload(inp()))
    assert HIDDEN_LINE not in payload and HIDDEN_LINE not in res.markdown
    assert all(HIDDEN_LINE not in r.detail for batch in res.rejections for r in batch)


def test_hidden_line_in_a_next_step_is_caught_too():
    bad = good(what_to_check_next=[HIDDEN_LINE[:200]])
    rules = {r.rule for r in validate_output(FeedbackOutput(**bad), inp(), HIDDEN)}
    assert "hidden_source" in rules


def test_the_guard_is_the_existing_one():
    assert fa.pf.assert_no_hidden_source is pf.assert_no_hidden_source
    assert fa.pf.hidden_source_lines is pf.hidden_source_lines


@pytest.mark.parametrize("text", [
    "Your solution is wrong.", "This code is incorrect.", "The function looks perfect.",
    "Your implementation works correctly.", "There is a bug in the loop.",
    "It contains an error.", "You've nailed it.", "This is bug-free.", "A wrong answer here.",
    "Your code does not work.",
])
def test_correctness_claims_are_rejected(text):
    rules = {r.rule for r in validate_output(FeedbackOutput(**good(summary=text)), inp(), HIDDEN)}
    assert "correctness_claim" in rules, text


@pytest.mark.parametrize("text", [
    "The retry check failed with a ConnectionError.",
    "Three of four checks passed; look at the one that failed.",
    "Re-read the instruction about waiting between attempts.",
    "The check named above did not pass on this push.",
])
def test_describing_the_checks_is_not_a_correctness_claim(text):
    assert validate_output(FeedbackOutput(**good(summary=text)), inp(), HIDDEN) == []


# ---- other failure modes of the model -----------------------------------------------------

def test_schema_invalid_twice_falls_back():
    fake = fl.FakeLLM([fl.invalid_json(), fl.invalid_json()])
    res = run(fake)
    assert res.source == fa.SOURCE_FALLBACK and res.markdown == V0
    assert "schema_invalid_after_gateway_retry" in res.reasons
    assert fake.call_count == 2                       # the gateway's own retry, nothing more


def test_too_many_steps_or_a_long_step_is_a_schema_failure():
    for bad in (good(what_to_check_next=[]), good(what_to_check_next=["a", "b", "c", "d"]),
                good(what_to_check_next=["x" * (fp.MAX_STEP_CHARS + 1)]),
                good(confidence="certain"), good(summary="")):
        fake = fl.FakeLLM([fl.valid_json(bad), fl.valid_json(bad)])
        assert run(fake).source == fa.SOURCE_FALLBACK


def test_provider_down_falls_back_without_raising():
    res = run(fl.FakeLLM([fl.provider_error(sticky=True)]))
    assert res.source == fa.SOURCE_FALLBACK and res.markdown == V0
    assert res.reasons == ["provider_error: RuntimeError"]


def test_timeout_falls_back_without_raising():
    res = run(fl.FakeLLM([fl.timeout(sticky=True)]))
    assert res.source == fa.SOURCE_FALLBACK


def test_a_slow_first_model_is_served_by_the_next_one():
    res = run(fl.FakeLLM([fl.slow(0.6), fl.valid_json(good())]))
    assert res.used_llm


# ---- statuses and cases that must not call the model -------------------------------------

def test_collection_error_gets_plain_words_and_no_llm_call():
    fake = fl.FakeLLM()
    res = run(fake, inp("52d4ac3d"))
    assert res.source == fa.SOURCE_STATUS and res.status == "collection_error"
    assert res.markdown == V0 and res.output is None
    assert fake.call_count == 0 and fake.judge_count == 0


def test_timeout_status_gets_plain_words_and_no_llm_call():
    fake = fl.FakeLLM()
    res = run(fake, inp("__timeout"))
    assert res.source == fa.SOURCE_STATUS and res.status == "timeout" and fake.call_count == 0


def test_tooling_status_is_never_a_student_problem_and_calls_nothing():
    data = dict(fixture("a82__128da3e9"), status="tooling")
    fake = fl.FakeLLM()
    res = run(fake, FeedbackInput.from_fixture(data, candidates()))
    assert res.source == fa.SOURCE_STATUS and fake.call_count == 0


def test_a_commit_with_nothing_failing_calls_nothing():
    fake = fl.FakeLLM()
    res = run(fake, inp("a82__ecee2946"))
    assert res.source == fa.SOURCE_NO_FAILURES and fake.call_count == 0 and res.markdown == V0


def test_status_paths_make_no_mastery_claim_by_construction():
    """They never reach the model, so the only text is the deterministic v0 text."""
    for part in ("52d4ac3d", "__timeout", "a82__ecee2946"):
        assert run(fl.FakeLLM(), inp(part)).markdown == V0


# ---- candidates ---------------------------------------------------------------------------

def test_no_candidates_means_null_is_the_only_valid_resource():
    i = inp(cands=False)
    assert "(none: use null for resource_id)" in fp.build_feedback_prompt(i)
    ok = run(fl.FakeLLM([fl.valid_json(good(resource_id=None))]), i)
    assert ok.used_llm
    bad = validate_output(FeedbackOutput(**good(resource_id="EXAMPLE-R1")), i, HIDDEN)
    assert [r.rule for r in bad] == ["unknown_resource"] and "none" in bad[0].detail


def test_the_resource_shown_comes_from_the_table_not_from_the_model():
    res = run(fl.FakeLLM([fl.valid_json(good(resource_id="EXAMPLE-R2"))]))
    assert "EXAMPLE: Working with dictionaries" in res.markdown
    assert "https://example.invalid/dicts" in res.markdown


# ---- budget -------------------------------------------------------------------------------

def test_budget_too_small_falls_back_before_any_call():
    fake = fl.FakeLLM([fl.valid_json(good())])
    budget = CallBudget(max_calls=1)
    res = run(fake, budget=budget)
    assert res.source == fa.SOURCE_FALLBACK and fake.call_count == 0
    assert res.reasons[0].startswith("budget_exceeded")


def test_budget_runs_out_between_the_first_call_and_the_corrective_one():
    fake = fl.FakeLLM([fl.valid_json(BAD["unknown_test"]), fl.valid_json(good())])
    budget = CallBudget(max_calls=2)
    res = run(fake, budget=budget)
    assert res.source == fa.SOURCE_FALLBACK
    assert fake.call_count == 1 and budget.used == 1
    assert any(r.startswith("budget_exceeded") for r in res.reasons)


def test_budget_is_charged_for_the_gateway_retry_inside_a_judge():
    fake = fl.FakeLLM([fl.invalid_json(), fl.valid_json(good())])
    budget = CallBudget(max_calls=6)
    res = run(fake, budget=budget)
    assert res.used_llm and res.calls_made == 2 and budget.used == 2


def test_no_budget_given_means_no_limit_object_is_needed():
    assert run(fl.FakeLLM([fl.valid_json(good())]), budget=None).used_llm


def test_default_budget_covers_one_full_agent_run():
    assert budget_mod.DEFAULT_MAX_CALLS_PER_RUN >= 2 * budget_mod.WORST_CASE_CALLS_PER_JUDGE


# ---- shape and constants ------------------------------------------------------------------

def test_prompt_caps_match_the_model():
    schema = FeedbackOutput.model_json_schema()["properties"]
    assert schema["summary"]["maxLength"] == fp.MAX_SUMMARY_CHARS
    assert schema["what_to_check_next"]["maxItems"] == fp.MAX_STEPS
    assert str(fp.MAX_STEP_CHARS) in fp.OUTPUT_SCHEMA_BLOCK


def test_prompt_schema_block_names_every_output_field():
    for name in FeedbackOutput.model_fields:
        assert f'"{name}"' in fp.OUTPUT_SCHEMA_BLOCK


def test_agent_never_calls_generate_and_has_no_sdk_import():
    src = Path(fa.__file__).read_text(encoding="utf-8")
    assert "generate(" not in src and "import anthropic" not in src and "import openai" not in src
    with pytest.raises(fl.GenerateForbidden):
        fl.FakeLLM().generate("x", temperature=0.5)


def test_trace_payload_is_json_and_holds_no_raw_model_text():
    res = run(fl.FakeLLM([fl.valid_json(good())]))
    payload = res.to_trace_payload(inp())
    json.dumps(payload)
    assert payload["agent"] == "feedback_agent_v1" and payload["source"] == "llm"
    assert payload["output"]["resource_id"] == "EXAMPLE-R1"


def test_result_remembers_its_input_so_the_payload_needs_no_argument():
    res = run(fl.FakeLLM([fl.valid_json(good())]))
    assert res.input is not None and res.to_trace_payload() == res.to_trace_payload(res.input)
    for part in ("52d4ac3d", "a82__ecee2946"):
        assert run(fl.FakeLLM(), inp(part)).input is not None
    assert fa.FeedbackResult("x", "llm").input is None
    with pytest.raises(ValueError):
        fa.FeedbackResult("x", "llm").to_trace_payload()


def test_run_feedback_agent_takes_no_cursor():
    assert "cur" not in inspect.signature(run_feedback_agent).parameters


# ---- database glue (test database, one rolled-back transaction) ---------------------------

needs_db = pytest.mark.skipif(not os.environ.get("PG_DSN"), reason="PG_DSN not set")
S, ASG = "_fbagent_student", "weather_etl_extract"
SHA1, SHA2 = "a" * 40, "b" * 40
T_RETRY = "tests/hidden/test_extract.py::" + RETRY
T_PARSE = "tests/hidden/test_extract.py::test_parse_response_missing_key_returns_none"


@pytest.fixture
def world():
    from tests.support import ensure_variant
    conn = db._open()
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, S))
    variant = ensure_variant(cur, ASG)
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl',%s,1,%s,1) RETURNING attempt_id",
                (S, ASG, variant))
    attempt_id = cur.fetchone()[0]
    for i, sha in enumerate((SHA1, SHA2)):
        cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                    " VALUES (%s,%s,%s,%s)", (sha, S, ASG, f"2026-08-25 0{i + 1}:00+00"))
    yield conn, cur, attempt_id
    conn.rollback()
    conn.close()


def _result(cur, aid, sha, name, gap, passed, message=None, status="ok"):
    cur.execute("INSERT INTO test_results (attempt_id, commit_sha, test_name, gap_id, passed,"
                " message, status) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (aid, sha, name, gap, passed, message, status))


def _counts(cur):
    out = {}
    for table in ("traces", "test_results", "learner_profile", "attempts", "feedback_posts"):
        cur.execute(f"SELECT count(*) FROM {table}")
        out[table] = cur.fetchone()[0]
    return out


@needs_db
def test_glue_reads_the_database_and_writes_nothing(world):
    _, cur, aid = world
    secret = "AssertionError: assert 32.0 == f(0)\n + where 32.0 = expected"
    _result(cur, aid, SHA1, T_RETRY, "g_ext_retry", False, secret)
    _result(cur, aid, SHA1, T_PARSE, "g_ext_parse", True)
    before = _counts(cur)
    fake = fl.FakeLLM([fl.valid_json(good(resource_id=None))])
    res = fa.build_feedback_with_llm(cur, aid, SHA1, fake, CallBudget(6),
                                     profile={"mastery": {}}, candidates=[])
    assert res.used_llm and "1 of 2" in res.markdown
    assert _counts(cur) == before
    prompt = fake.prompts[0]
    assert "AssertionError" in prompt                       # the type is allowed
    for token in ("7731.5", "f(912)", "SECRETWORD"):            # nothing from the message
        assert token not in prompt and token not in res.markdown


@needs_db
def test_glue_fallback_is_the_real_v0_text(world):
    _, cur, aid = world
    _result(cur, aid, SHA1, T_RETRY, "g_ext_retry", False, "AssertionError: x")
    fake = fl.FakeLLM([fl.invalid_json(), fl.invalid_json()])
    res = fa.build_feedback_with_llm(cur, aid, SHA1, fake, CallBudget(6),
                                     profile={"mastery": {}}, candidates=[])
    assert res.source == fa.SOURCE_FALLBACK
    assert res.markdown == pf.build_feedback(cur, aid, SHA1).markdown


@needs_db
def test_glue_collection_error_makes_no_llm_call(world):
    _, cur, aid = world
    _result(cur, aid, SHA2, T_RETRY, "g_ext_retry", False, "collection error: SyntaxError",
            status="collection_error")
    fake = fl.FakeLLM()
    res = fa.build_feedback_with_llm(cur, aid, SHA2, fake, CallBudget(6),
                                     profile={"mastery": {}}, candidates=[])
    assert res.source == fa.SOURCE_STATUS and fake.call_count == 0
    assert "could not be loaded" in res.markdown


@needs_db
def test_glue_reads_the_mastery_slice_through_memory_without_writing(world):
    _, cur, aid = world
    _result(cur, aid, SHA1, T_RETRY, "g_ext_retry", False, "AssertionError: x")

    calls = []

    class SpyMemory:
        def get_profile(self, student_id, *, conn=None):
            calls.append((student_id, conn is not None))
            return {"mastery": {"py.errors_debugging": {"p_mastery": 0.4, "n": 2}}}

    i = fa.gather_input(cur, aid, SHA1, memory=SpyMemory(), candidates=[])
    assert calls == [(S, True)]                             # joined to the caller's transaction
    assert i.mastery == {"py.errors_debugging": {"p_mastery": 0.4, "n": 2}}


@needs_db
def test_glue_unknown_commit_raises(world):
    _, cur, aid = world
    with pytest.raises(ValueError):
        fa.gather_input(cur, aid, "f" * 40, profile={"mastery": {}}, candidates=[])
