"""D-108 -- the Feedback Agent v2 (`--agents-v2`), with the fake LLM only.

No live call, no network: every provider handler is replaced by one that raises, and the model is a
`FakeLLM` that answers from a script. The first half is pure (no database); the second half drives
the cycle's hook on the throwaway test database.
"""

import hashlib
import json
import os
from pathlib import Path

import pytest

from agents import budget as budget_mod
from agents import fake_llm as fl
from agents import feedback_agent as fa
from agents import feedback_prompts as fp
from agents import feedback_v2 as fv2
from agents.budget import CallBudget, UsageLedger
from assessment.gap_parser import render_student_file
from scripts import post_feedback as pf
from scripts import run_cycle as rc
from system import db
from tests import test_agents_feedback as base
from tests.test_run_cycle import CURRICULUM, FakeGitHub, make_student, roster_for

V0 = "V0-DETERMINISTIC-TEXT"
RETRY = "test_fetch_weather_retries_then_succeeds"
RETRY_FULL = "tests/hidden/test_extract.py::" + RETRY
HIDDEN = pf.hidden_source_lines("weather_etl")
DESCRIPTION = "When the first request fails with a connection error, a later success is returned."
LINE = "        r = requests.get(url, params=params)"
EXCERPT = (
    "def fetch_weather(url, params):\n"
    "    for attempt in range(1, MAX_ATTEMPTS + 1):\n"
    f"{LINE}\n"
    "        return r.json()\n"
)
MASTER = fv2.master_bodies("weather_etl", "weather_etl/extract.py", ["g_ext_retry"])


@pytest.fixture(autouse=True)
def no_live_provider(monkeypatch, tmp_path):
    from system import llm as gateway

    def blocked(*args, **kwargs):
        raise AssertionError("LIVE PROVIDER CALL attempted in a test")

    for provider in list(gateway._PROVIDER_HANDLERS):
        monkeypatch.setitem(gateway._PROVIDER_HANDLERS, provider, blocked)
    monkeypatch.setattr(rc, "DEFAULT_LEDGER_PATH", tmp_path / "default_llm_usage.json")


def make_input(level=1, recurrence=2, *, excerpt=EXCERPT, failed=None, descriptions=None):
    v1 = base.inp()
    values = {k: getattr(v1, k) for k in fa.FeedbackInput.__dataclass_fields__}
    if failed is not None:
        values["failed"] = failed
    return fv2.FeedbackInputV2(
        **values,
        recurrence={RETRY_FULL: recurrence},
        descriptions={RETRY_FULL: DESCRIPTION} if descriptions is None else descriptions,
        focus_check=RETRY_FULL,
        hint_level=level,
        excerpt=excerpt,
        excerpt_matchable=excerpt or "",
        excerpt_note="Only your own lines are shown.",
        excerpt_reason=None if excerpt else "no excerpt in this test",
        master_bodies=MASTER,
    )


def good(**over) -> dict:
    body = {
        "summary": "Your loop stops at the first connection error. Think about what should happen "
        "after a request fails before the last allowed attempt.",
        "what_to_check_next": [
            "Follow the loop by hand when the first request fails.",
            "Decide what the loop does on its final turn.",
        ],
        "quotes": [LINE],
        "cited_tests": [RETRY],
        "cited_concepts": ["py.errors_debugging"],
        "resource_id": "EXAMPLE-R1",
        "confidence": "medium",
    }
    body.update(over)
    return body


def run(fake, inp=None, budget=None):
    return fv2.run_feedback_agent_v2(
        inp or make_input(), fake, budget, hidden=HIDDEN, fallback_markdown=lambda: V0
    )


def rules(result):
    return [[r.rule for r in batch] for batch in result.rejections]


# --- the ladder ------------------------------------------------------------------------------


@pytest.mark.parametrize("failures, level", [(1, 1), (2, 2), (3, 3), (9, 3)])
def test_the_hint_level_follows_the_recurrence(failures, level):
    assert fv2.hint_level_for(failures) == level


def test_the_focus_is_the_most_recurrent_failing_check_ties_by_name():
    a = fa.FailedCheck("tests/hidden/t.py::a", "AssertionError", "g1")
    b = fa.FailedCheck("tests/hidden/t.py::b", "AssertionError", "g2")
    assert fv2.pick_focus([b, a], {a.test_name: 1, b.test_name: 1}) == a.test_name
    assert fv2.pick_focus([a, b], {a.test_name: 1, b.test_name: 4}) == b.test_name
    assert fv2.pick_focus([], {}) is None


def test_level_1_gives_the_expected_behaviour_and_does_not_point_at_a_line():
    fake = fl.FakeLLM([fl.valid_json(good())])
    result = run(fake, make_input(level=1, recurrence=1))
    assert result.source == fa.SOURCE_LLM and result.hint_level == 1
    assert f"Expected behaviour: {DESCRIPTION}" in result.markdown
    assert "Look again at this line" not in result.markdown
    assert LINE.strip() not in result.markdown  # the quote is evidence, not shown
    assert "LEVEL 1 - expected behaviour" in fake.prompts[0]


def test_level_2_points_at_one_quoted_line_written_by_code():
    fake = fl.FakeLLM([fl.valid_json(good())])
    result = run(fake, make_input(level=2, recurrence=2))
    assert result.hint_level == 2
    assert f"Look again at this line of your code: `{LINE.strip()}`" in result.markdown
    assert "Expected behaviour:" not in result.markdown
    assert "LEVEL 2 - point at one line" in fake.prompts[0]


def test_level_3_is_a_strategy_in_words_with_no_line_and_no_behaviour_sentence():
    fake = fl.FakeLLM([fl.valid_json(good())])
    result = run(fake, make_input(level=3, recurrence=3))
    assert result.hint_level == 3
    assert "Expected behaviour:" not in result.markdown and "Look again" not in result.markdown
    assert LINE.strip() not in result.markdown
    assert "LEVEL 3 - strategy" in fake.prompts[0]


def test_the_prompt_holds_the_facts_and_never_the_solution_or_hidden_source():
    fake = fl.FakeLLM([fl.valid_json(good())])
    run(fake, make_input(level=2, recurrence=2))
    prompt = fake.prompts[0]
    assert "<<<BEGIN STUDENT LINES>>>" in prompt and LINE in prompt
    assert f"public description: {DESCRIPTION}" in prompt
    assert "failed on 2 push(es) of this attempt so far" in prompt
    for line in (
        "response.raise_for_status()",
        "time.sleep(2 ** attempt)",
        "except requests.RequestException:",
        "response = requests.get(url, params=params, timeout=10)",
    ):
        assert line in MASTER["g_ext_retry"] and line not in prompt  # the solution stays out
    for hidden_line in list(HIDDEN)[:50]:
        assert hidden_line not in prompt


def test_a_check_with_no_reviewed_description_says_so_to_the_model():
    fake = fl.FakeLLM([fl.valid_json(good())])
    result = run(fake, make_input(level=1, recurrence=1, descriptions={}))
    assert "(none reviewed yet)" in fake.prompts[0]
    assert "Expected behaviour:" not in result.markdown  # nothing invented for the student


# --- the validator, rule by rule -------------------------------------------------------------


def rejected_then_fixed(bad: dict, rule: str):
    """First answer breaks `rule`, the corrective call is fine: one rejection, then accepted."""
    fake = fl.FakeLLM([fl.valid_json(bad), fl.valid_json(good())])
    result = run(fake)
    assert result.source == fa.SOURCE_LLM and result.judge_calls == 2
    assert rule in rules(result)[0] and rules(result)[1] == []
    assert rule in fake.prompts[1]  # the corrective note names it
    return result


def always_rejected(bad: dict, rule: str):
    fake = fl.FakeLLM([fl.valid_json(bad), fl.valid_json(bad)])
    result = run(fake)
    assert result.source == fa.SOURCE_FALLBACK and result.markdown == V0
    assert rule in rules(result)[0] and rule in rules(result)[1]
    assert result.output is None and fake.call_count == 2


def test_a_quote_not_copied_from_the_students_lines_is_rejected():
    always_rejected(good(quotes=["        r = fetch(url)"]), "quote_not_in_code")
    rejected_then_fixed(good(quotes=["return json"]), "quote_not_in_code")


def test_a_quote_may_be_the_escaped_form_of_a_line_holding_a_delimiter_run():
    line = "        x = '[LT3]'"
    excerpt = "def f():\n        x = '<<<'\n"
    inp = make_input(excerpt=fv2.escape_markers(excerpt))
    inp = fv2.FeedbackInputV2(**{**inp.__dict__, "excerpt_matchable": excerpt})
    fake = fl.FakeLLM([fl.valid_json(good(quotes=[line]))])
    assert run(fake, inp).source == fa.SOURCE_LLM


def test_a_quote_longer_than_the_threshold_or_on_several_lines_is_rejected():
    long_line = "x = " + "a" * (fp.MAX_QUOTE_CHARS + 5)
    excerpt = f"def f():\n    {long_line}\n    y = 1\n"
    inp = make_input(excerpt=excerpt)
    fake = fl.FakeLLM(
        [fl.valid_json(good(quotes=[long_line])), fl.valid_json(good(quotes=[long_line]))]
    )
    out = run(fake, inp)
    assert "quote_too_long" in rules(out)[0]
    fake = fl.FakeLLM([fl.valid_json(good(quotes=["def f():\n    y = 1"]))] * 2)
    out = run(fake, make_input(excerpt="def f():\n    y = 1\n"))
    assert "quote_not_one_line" in rules(out)[0]


def test_a_comment_is_not_a_line_of_code():
    excerpt = "    # TODO write the loop\n    x = 1\n"
    inp = make_input(excerpt=excerpt)
    always = fl.FakeLLM([fl.valid_json(good(quotes=["    # TODO write the loop"]))] * 2)
    assert "no_code_quote" in rules(run(always, inp))[0]
    ok = fl.FakeLLM([fl.valid_json(good(quotes=["    # TODO write the loop", "    x = 1"]))])
    assert run(ok, inp).source == fa.SOURCE_LLM


def test_a_missing_quote_fails_the_schema_and_ends_in_the_deterministic_text():
    fake = fl.FakeLLM([fl.valid_json(good(quotes=[])), fl.valid_json(good(quotes=[]))])
    result = run(fake)
    assert result.source == fa.SOURCE_FALLBACK and result.markdown == V0
    assert "schema_invalid_after_gateway_retry" in result.reasons


@pytest.mark.parametrize(
    "summary",
    [
        "Try this:\n```python\nfor i in range(3):\n    pass\n```",
        "Try this:\n    for i in range(3):\n        pass",
    ],
)
def test_a_code_block_is_rejected(summary):
    always_rejected(good(summary=summary), "code_block")


def test_an_inline_code_span_over_the_threshold_is_rejected_a_short_one_is_fine():
    long_span = "`" + "x" * (fp.MAX_CODE_SPAN_CHARS + 1) + "`"
    always_rejected(good(what_to_check_next=[f"Compare with {long_span}"]), "code_span_too_long")
    short = fl.FakeLLM([fl.valid_json(good(what_to_check_next=["Print `attempt` each turn."]))])
    assert run(short).source == fa.SOURCE_LLM


def test_a_reply_that_copies_the_reference_solution_is_rejected_and_the_note_does_not_echo_it():
    copied = (
        "Write for attempt in range(1, MAX_ATTEMPTS + 1): try: response = requests.get(url, "
        "params=params, timeout=10) response.raise_for_status() return response.json()"
    )
    fake = fl.FakeLLM([fl.valid_json(good(summary=copied)), fl.valid_json(good(summary=copied))])
    result = run(fake)
    assert "solution_overlap" in rules(result)[0] and result.source == fa.SOURCE_FALLBACK
    assert "response.raise_for_status" not in fake.prompts[1]  # never repeated to the model
    assert "range(1, MAX_ATTEMPTS" not in fake.prompts[1].split("rejected by an automatic check")[1]


def test_the_overlap_measure_and_its_blind_spot_for_a_short_body():
    body = MASTER["g_ext_retry"]
    assert fv2.overlap_ratio(body, "think about the idea of retrying politely") == 0
    assert fv2.overlap_ratio(body, body) == 1.0
    assert fv2.overlap_ratio("return x", "return x") is None  # too short to compare
    assert fv2.overlap_ratio("# only a comment\n", "anything") is None


@pytest.mark.parametrize(
    "text",
    [
        "You passed 3 of 4 checks.",
        "3/4 checks are green.",
        "Some checks passed already.",
        "2 checks failed.",
        "Look at test_fetch_weather_retries_then_succeeds again.",
    ],
)
def test_repeating_the_counts_or_the_test_list_is_rejected(text):
    always_rejected(good(summary=text), "repeats_summary")


def test_every_v1_rule_still_applies():
    always_rejected(good(cited_tests=["test_never_failed"]), "unknown_test")
    always_rejected(good(summary="Your code is wrong in the loop."), "correctness_claim")
    always_rejected(good(summary="See https://example.org for the idea."), "link_in_text")
    always_rejected(good(summary="You have mastered retries."), "mastery_claim")
    always_rejected(good(resource_id="made-up"), "unknown_resource")


# --- no provider call at all -----------------------------------------------------------------


def test_a_commit_whose_only_failures_are_not_implemented_stubs_gets_the_fixed_sentence():
    stub = fa.FailedCheck(RETRY_FULL, "NotImplementedError", "g_ext_retry")
    fake = fl.FakeLLM([])
    result = run(fake, make_input(failed=(stub,)))
    assert fake.call_count == 0 and result.calls_made == 0
    assert result.source == fv2.SOURCE_STUB and result.storable
    assert fv2.STUB_SENTENCE in result.markdown and result.markdown.startswith(V0)
    assert result.addendum_markdown() == fv2.STUB_ADDENDUM
    assert result.to_trace_payload()["agent"] == "feedback_agent_v2"
    fake.assert_exhausted()


def test_one_other_failure_among_the_stubs_goes_to_the_model():
    stub = fa.FailedCheck(RETRY_FULL, "NotImplementedError", "g_ext_retry")
    other = fa.FailedCheck("tests/hidden/test_extract.py::test_x", "AssertionError", "g_ext_parse")
    fake = fl.FakeLLM([fl.valid_json(good())])
    assert run(fake, make_input(failed=(stub, other))).source == fa.SOURCE_LLM
    assert fv2.is_stub_only([stub]) and not fv2.is_stub_only([stub, other])
    assert not fv2.is_stub_only([])


def test_with_no_excerpt_there_is_nothing_to_quote_and_no_call():
    fake = fl.FakeLLM([])
    result = run(fake, make_input(excerpt=None))
    assert fake.call_count == 0 and result.source == fv2.SOURCE_NO_EXCERPT
    assert result.markdown == V0 and not result.storable
    assert "no excerpt" in result.reasons[0] and "no provider call" in result.reasons[0]


def test_other_statuses_and_no_failures_make_no_call_either():
    fake = fl.FakeLLM([])
    for status in ("collection_error", "timeout", "tooling"):
        inp = make_input()
        inp = fv2.FeedbackInputV2(**{**inp.__dict__, "status": status})
        assert run(fake, inp).source == fa.SOURCE_STATUS
    inp = make_input(failed=())
    assert run(fake, inp).source == fa.SOURCE_NO_FAILURES
    assert fake.call_count == 0


def test_a_spent_budget_ends_in_the_deterministic_text_with_no_call():
    fake = fl.FakeLLM([fl.valid_json(good())])
    result = run(fake, budget=CallBudget(max_calls=1))
    assert fake.call_count == 0 and result.source == fa.SOURCE_FALLBACK
    assert result.reasons[0].startswith("budget_exceeded")


def test_the_calls_are_counted_and_a_provider_failure_does_not_lose_the_text():
    budget = CallBudget(max_calls=6)
    fake = fl.FakeLLM([fl.valid_json(good(summary="Your code is wrong.")), fl.valid_json(good())])
    result = run(fake, budget=budget)
    assert result.source == fa.SOURCE_LLM and result.calls_made == 2 == budget.used
    down = fl.FakeLLM([fl.provider_error(sticky=True)])
    out = run(down)
    assert out.source == fa.SOURCE_FALLBACK and out.markdown == V0
    assert out.reasons[0].startswith("provider_error")


def test_the_payload_carries_the_level_the_quotes_and_a_hash_never_the_code():
    result = run(fl.FakeLLM([fl.valid_json(good())]), make_input(level=2, recurrence=2))
    payload = result.to_trace_payload()
    assert payload["agent"] == "feedback_agent_v2" and payload["prompt_version"] == "fb2"
    assert payload["hint_level"] == 2 and payload["focus_check"] == RETRY_FULL
    assert payload["recurrence"] == {RETRY_FULL: 2} and payload["quotes"] == [LINE]
    assert payload["excerpt_sha256"] == hashlib.sha256(EXCERPT.encode()).hexdigest()
    assert EXCERPT not in json.dumps(payload) or LINE in json.dumps(payload)
    assert "def fetch_weather" not in json.dumps(payload)


def test_a_line_of_hidden_source_in_the_model_words_is_still_rejected():
    secret = next(iter(sorted(HIDDEN, key=len, reverse=True)))
    always_rejected(good(summary=f"Look at {secret} in the checks."), "hidden_source")


# --- flag off: v1 is byte-identical ----------------------------------------------------------

GOLDEN = {
    "prompt": "60fdf658a0b62c1ba927b779667b6c0ad476c5acaa0def436f69ea1e48510cdf",
    "markdown": "d7cf9ab373c83ca3be3657a135577138e99b2e6b39b2cc62880aae28a558b011",
    "payload": "bae74b10e060b939b45568b53e3ce8ec10d072ccbc1825e93fe48c22deaaddab",
    "addendum": "0842f171c7316d605148420c9af00395266b0ddf0528d460fa853525c7196391",
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_the_v1_prompt_markdown_payload_and_addendum_are_byte_identical_to_before_v2():
    """Captured from the code BEFORE this change (D-108). A v2 edit that touches v1 turns it red."""
    inp = base.inp()
    assert sha(fp.build_feedback_prompt(inp)) == GOLDEN["prompt"]
    result = base.run(fl.FakeLLM([fl.valid_json(base.good())]))
    assert sha(result.markdown) == GOLDEN["markdown"]
    assert sha(json.dumps(result.to_trace_payload(), sort_keys=True)) == GOLDEN["payload"]
    assert sha(fa.render_addendum(inp, result.output)) == GOLDEN["addendum"]
    assert fp.FEEDBACK_PROMPT_VERSION == "fb1" and fa.AGENT == "feedback_agent_v1"
    assert result.agent_id == "feedback_agent_v1" and result.storable == result.used_llm


def test_the_v1_module_does_not_import_v2_and_the_flag_off_lookup_is_unchanged():
    import inspect

    source = inspect.getsource(fa)
    assert "import feedback_v2" not in source and "from agents.feedback_v2" not in source
    from agents import pipeline

    source = inspect.getsource(pipeline.find_feedback_addendum)
    assert source.count("cur.execute(") == 2 and "if agents_v2:" in source


# --- the database: the hook, the trace, the poster -------------------------------------------

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


class AttemptedGitHub(FakeGitHub):
    """The checkout holds a file where one gap is attempted but wrong (`return records`, so a check
    FAILS with an AssertionError) and another is still the stub (NotImplementedError): so the commit
    is not stub-only."""

    def __init__(self, tmp_path, *, stubs_only=False):
        super().__init__(tmp_path)
        master = (self.root / "weather_etl" / "transform.py").read_text(encoding="utf-8")
        text = render_student_file(master, hide_gap_ids=["g_tf_clean", "g_tf_convert"])
        if not stubs_only:
            text = text.replace("    raise NotImplementedError()", "    return records", 1)
        self.attempted = text

    def checkout(self, owner, repo, sha, dest):
        super().checkout(owner, repo, sha, dest)
        (Path(dest) / "weather_etl" / "transform.py").write_text(self.attempted, encoding="utf-8")


def answer_for(prompt_quote: str):
    body = good(quotes=[prompt_quote], cited_tests=[], cited_concepts=[], resource_id=None)

    def answer(prompt: str) -> str:
        return json.dumps(body)

    return fl.FakeLLM(default=answer)


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
        **kw,
    )
    return result, lines


def coach(conn, sid):
    cur = conn.cursor()
    cur.execute(
        "SELECT trace_id, payload FROM traces WHERE student_id = %s AND actor = 'coach'"
        " AND kind = 'intervention' ORDER BY trace_id",
        (sid,),
    )
    return cur.fetchall()


@needs_db
def test_the_hook_runs_v2_stores_one_trace_and_the_poster_finds_it(conn, tmp_path):
    from agents import pipeline

    make_student(conn, "_cyc_a")
    gh = AttemptedGitHub(tmp_path)
    fake = answer_for("    return records")

    result, lines = cycle(conn, gh, "_cyc_a", fake=fake, agents_v2=True)

    assert result.exit_code == 0 and result.students[0].graded == 1
    ((trace_id, payload),) = coach(conn, "_cyc_a")
    assert payload["agent"] == "feedback_agent_v2" and payload["source"] == "llm"
    assert payload["prompt_version"] == "fb2" and payload["hint_level"] == 1
    assert payload["quotes"] == ["    return records"] and payload["recurrence"]
    assert payload["addendum_markdown"].startswith("**More detail**")
    assert "return records" not in payload["addendum_markdown"]  # level 1: the quote is not shown
    assert fake.call_count == 1
    prompt = fake.prompts[0]
    assert "<<<BEGIN STUDENT LINES>>>" in prompt and "    return records" in prompt
    shown = prompt.split("<<<BEGIN STUDENT LINES>>>")[1].split("<<<END STUDENT LINES>>>")[0]
    assert "def clean_readings" in shown  # three lines of context
    assert "[... " in shown and "line(s) not shown" in shown  # lines left out are marked
    text = "\n".join(lines)
    assert "agents v2 ON" in text and f"coach trace {trace_id}" in text
    cur = conn.cursor()
    cur.execute("SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a'")
    (attempt_id,) = cur.fetchone()
    sha_ = "a" * 40
    assert (
        pipeline.find_feedback_addendum(cur, attempt_id, sha_, agents_v2=True)
        == payload["addendum_markdown"]
    )
    assert pipeline.find_feedback_addendum(cur, attempt_id, sha_) is None  # flag off: v1 rows only


@needs_db
def test_the_hook_gives_the_fixed_sentence_with_no_call_for_stubs_and_stores_it_once(
    conn, tmp_path
):
    make_student(conn, "_cyc_a")
    gh = AttemptedGitHub(tmp_path, stubs_only=True)
    fake = fl.FakeLLM([])

    result, lines = cycle(conn, gh, "_cyc_a", fake=fake, agents_v2=True)

    assert result.exit_code == 0 and fake.call_count == 0
    ((_, payload),) = coach(conn, "_cyc_a")
    assert payload["agent"] == "feedback_agent_v2" and payload["source"] == "deterministic_stub"
    assert payload["addendum_markdown"] == fv2.STUB_ADDENDUM and payload["provider_calls"] == 0
    assert "feedback_agent_v2=deterministic_stub" in "\n".join(lines)
    again, _ = cycle(conn, gh, "_cyc_a", fake=fake, agents_v2=True)
    assert again.students[0].graded == 0 and len(coach(conn, "_cyc_a")) == 1


@needs_db
def test_the_flag_off_cycle_is_the_v1_cycle_and_never_imports_v2(conn, tmp_path):
    make_student(conn, "_cyc_a")
    gh = AttemptedGitHub(tmp_path)
    fake = fl.FakeLLM(
        default=lambda prompt: json.dumps(
            {
                "summary": "Two checks stopped, so start with the TODO parts of your file.",
                "what_to_check_next": ["Read the TODO comments again."],
                "cited_tests": [],
                "cited_concepts": [],
                "resource_id": None,
                "confidence": "medium",
            }
        )
    )
    _, lines = cycle(conn, gh, "_cyc_a", fake=fake)  # agents_v2 not given
    ((_, payload),) = coach(conn, "_cyc_a")
    assert payload["agent"] == "feedback_agent_v1" and payload["prompt_version"] == "fb1"
    assert "hint_level" not in payload and "agents v2" not in "\n".join(lines)
    assert "STUDENT LINES" not in fake.prompts[0]


@needs_db
def test_reviewed_descriptions_reach_the_prompt_and_drafts_do_not(conn, tmp_path, monkeypatch):
    make_student(conn, "_cyc_a")
    gh = AttemptedGitHub(tmp_path)
    fake = answer_for("    return records")
    # the shipped checks.yaml holds only drafts -> "(none reviewed yet)"
    cycle(conn, gh, "_cyc_a", fake=fake, agents_v2=True)
    assert "(none reviewed yet)" in fake.prompts[0]
    assert "removed by clean_readings" not in fake.prompts[0]


@needs_db
def test_the_recurrence_counts_pushes_up_to_and_including_this_one(conn):
    make_student(conn, "_cyc_a")
    cur = conn.cursor()
    cur.execute("SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a'")
    (attempt_id,) = cur.fetchone()
    names = ["tests/hidden/test_transform.py::test_a", "tests/hidden/test_transform.py::test_b"]
    for i, sha_ in enumerate(("1" * 40, "2" * 40, "3" * 40)):
        cur.execute(
            "INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at,"
            " additions, deletions, files_changed, message) VALUES (%s,'_cyc_a',"
            " 'weather_etl_transform', %s, 1, 0, 1, 'w')",
            (sha_, f"2026-08-2{i + 1} 10:00+00"),
        )
        for name in names:
            fails = name.endswith("test_a") or i == 2  # a fails on all three, b only on 3
            cur.execute(
                "INSERT INTO test_results (attempt_id, test_name, passed, commit_sha)"
                " VALUES (%s,%s,%s,%s)",
                (attempt_id, name, not fails, sha_),
            )
    assert fv2.failure_counts(cur, attempt_id, "3" * 40, names) == {names[0]: 3, names[1]: 1}
    assert fv2.failure_counts(cur, attempt_id, "2" * 40, names) == {names[0]: 2, names[1]: 1}
    assert fv2.failure_counts(cur, attempt_id, "1" * 40, names) == {names[0]: 1, names[1]: 1}
    assert fv2.failure_counts(cur, attempt_id, "3" * 40, []) == {}


@needs_db
def test_a_reviewed_description_is_looked_up_and_a_draft_is_not(conn, tmp_path):
    from config import checks

    make_student(conn, "_cyc_a")
    cur = conn.cursor()
    cur.execute("SELECT attempt_id FROM attempts WHERE student_id = '_cyc_a'")
    (attempt_id,) = cur.fetchone()
    name = "tests/hidden/test_transform.py::test_clean_readings_drops_null_temp"
    cur.execute(
        "INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at, additions,"
        " deletions, files_changed, message) VALUES (%s,'_cyc_a','weather_etl_transform',"
        " now(), 1, 0, 1, 'w')",
        ("9" * 40,),
    )
    cur.execute(
        "INSERT INTO test_results (attempt_id, test_name, gap_id, passed, message,"
        " commit_sha) VALUES (%s,%s,'g_tf_clean',false,'AssertionError: x',%s)",
        (attempt_id, name, "9" * 40),
    )
    p = tmp_path / "checks.yaml"
    p.write_text(
        "version: 1\nassignments:\n  weather_etl_transform:\n"
        f"    - {{test: '{name}', gap: g_tf_clean, description: Reviewed words., "
        "status: reviewed}\n",
        encoding="utf-8",
    )
    checks._load.cache_clear()
    code = tmp_path / "repo"
    (code / "weather_etl").mkdir(parents=True)
    inp = fv2.gather_input_v2(cur, attempt_id, "9" * 40, repo_dir=code, profile={}, checks_path=p)
    assert inp.descriptions == {name: "Reviewed words."} and inp.excerpt is None
    p.write_text(p.read_text(encoding="utf-8").replace("reviewed}", "draft}"), encoding="utf-8")
    checks._load.cache_clear()
    inp = fv2.gather_input_v2(cur, attempt_id, "9" * 40, repo_dir=code, profile={}, checks_path=p)
    assert inp.descriptions == {} and "file" in (inp.excerpt_reason or "").lower()
    checks._load.cache_clear()


# --- the flag ---------------------------------------------------------------------------------


def test_the_flag_is_off_by_default_and_refused_without_with_llm(tmp_path):
    import argparse

    parser = argparse.ArgumentParser()
    rc.add_llm_arguments(parser)
    assert parser.parse_args([]).agents_v2 is False
    assert parser.parse_args(["--agents-v2"]).agents_v2 is True
    lines: list[str] = []
    res = rc.run_cycle({"assignments": []}, agents_v2=True, with_llm=False, out=lines.append)
    assert res.exit_code == rc.EXIT_REFUSED and "--agents-v2 runs only together" in lines[0]
    from scripts import run_hourly as rh

    assert "--agents-v2" in rh._refusal(False, False, {"LLM_PROVIDER": "openai"}, True)
    assert rh._refusal(True, False, {"LLM_PROVIDER": "openai"}, True) is None
    import inspect

    assert inspect.signature(rc.run_cycle).parameters["agents_v2"].default is False
    assert inspect.signature(rh.run).parameters["agents_v2"].default is False


def test_the_scheduled_task_scripts_do_not_mention_the_v2_flag():
    windows = Path(__file__).resolve().parent.parent / "scripts" / "windows"
    for script in windows.glob("*.ps1"):
        assert "agents-v2" not in script.read_text(encoding="utf-8")


def test_the_budget_module_is_the_one_shared_by_both_versions():
    assert budget_mod.WORST_CASE_CALLS_PER_JUDGE == 2
    assert CURRICULUM.exists()
