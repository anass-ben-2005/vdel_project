"""D-101 -- scripts/llm_first_call.py: the manual, dry-run, first real call (FAKE LLM only).

No test here can reach a provider (every handler is replaced by one that raises, as in
tests/test_with_llm.py), no key from the real environment is used (the checks take a dict), and the
database is the throwaway test database in one rolled-back transaction. The real database `vdel`
is never connected to (the D-064 counter at the end of a run says so).
"""
from __future__ import annotations

import inspect
import json
import os
import re
from pathlib import Path

import pytest

from agents import fake_llm as fl
from scripts import llm_first_call as fc
from system import db
from system import llm as gateway
from tests.support import ensure_variant
from tests.test_template_commit import ASG as TPL_ASG
from tests.test_template_commit import S as TPL_STUDENT
from tests.test_template_commit import delivered

needs_db = pytest.mark.skipif(not os.environ.get("PG_DSN"), reason="PG_DSN not set")

S, ASG = "_fc_student", "weather_etl_extract"
SHA1, SHA2, SHA3 = "a" * 40, "b" * 40, "c" * 40
T_RETRY = "tests/hidden/test_extract.py::test_fetch_weather_retries_then_succeeds"
T_PARSE = "tests/hidden/test_extract.py::test_parse_response_missing_key_returns_none"
SECRET_A, SECRET_B = "sk-SECRET-AAAA-1111", "sk-SECRET-BBBB-2222"
GOOD_ENV = {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": SECRET_A}
SUMMARY = "The retry check stopped on a ConnectionError, so look at the retry part of your file."


@pytest.fixture(autouse=True)
def no_live_provider(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("LIVE PROVIDER CALL attempted in a test")

    for provider in list(gateway._PROVIDER_HANDLERS):
        monkeypatch.setitem(gateway._PROVIDER_HANDLERS, provider, blocked)


def feedback(**over) -> dict:
    body = {"summary": SUMMARY, "what_to_check_next": ["Re-read the retry instruction."],
            "cited_tests": ["test_fetch_weather_retries_then_succeeds"],
            "cited_concepts": [], "resource_id": None, "confidence": "medium"}
    body.update(over)
    return body


def fake(**over) -> fl.FakeLLM:
    return fl.FakeLLM([fl.valid_json(feedback(**over))])


def go(cur, llm, *, attempt_id, commit=SHA1, student=S, env=None, cap=3):
    lines: list[str] = []
    code = fc.run(student=student, attempt_id=attempt_id, commit_sha=commit, call_cap=cap,
                  env=GOOD_ENV if env is None else env, llm=llm, cur=cur, out=lines.append)
    return code, "\n".join(lines)


@pytest.fixture
def world():
    conn = db._open()
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (S, S))
    variant = ensure_variant(cur, ASG)
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl',%s,1,%s,1) RETURNING attempt_id",
                (S, ASG, variant))
    attempt_id = cur.fetchone()[0]
    for i, sha in enumerate((SHA1, SHA2, SHA3)):
        cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                    " VALUES (%s,%s,%s,%s)", (sha, S, ASG, f"2026-08-25 0{i + 1}:00+00"))

    def result(sha, name, gap, passed, message=None, status="ok"):
        cur.execute("INSERT INTO test_results (attempt_id, commit_sha, test_name, gap_id, passed,"
                    " message, status) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (attempt_id, sha, name, gap, passed, message, status))

    result(SHA1, T_RETRY, "g_ext_retry", False, "AssertionError: x")        # a failing check
    result(SHA1, T_PARSE, "g_ext_parse", True)
    result(SHA2, T_RETRY, "g_ext_retry", False, "collection error: SyntaxError",
           "collection_error")
    result(SHA3, T_RETRY, "g_ext_retry", True)                              # nothing failed
    result(SHA3, T_PARSE, "g_ext_parse", True)
    yield conn, cur, attempt_id
    conn.rollback()
    conn.close()


def counts(cur) -> dict:
    out = {}
    for table in ("traces", "test_results", "learner_profile", "learner_features", "attempts",
                  "feedback_posts", "feedback_issues", "raw_commits", "students"):
        cur.execute(f"SELECT count(*) FROM {table}")
        out[table] = cur.fetchone()[0]
    return out


# --- refusals that need nothing: no database, no call -------------------------------------------

def test_refuses_without_an_explicit_provider(monkeypatch):
    monkeypatch.setattr(db, "_open", lambda: pytest.fail("the database must not be opened"))
    llm = fl.FakeLLM()
    code, text = go(None, llm, attempt_id=1, env={"OPENAI_API_KEY": SECRET_A})
    assert code == fc.EXIT_REFUSED and "LLM_PROVIDER is not set" in text
    assert llm.call_count == 0 and SECRET_A not in text


def test_refuses_with_two_keys_and_never_prints_one(monkeypatch):
    monkeypatch.setattr(db, "_open", lambda: pytest.fail("the database must not be opened"))
    llm = fl.FakeLLM()
    env = {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": SECRET_A, "ANTHROPIC_API_KEY": SECRET_B}
    code, text = go(None, llm, attempt_id=1, env=env)
    assert code == fc.EXIT_REFUSED and llm.call_count == 0
    assert "more than one provider key" in text and "blank" in text.lower()
    assert "ANTHROPIC_API_KEY" in text and "OPENAI_API_KEY" in text      # the NAMES
    assert SECRET_A not in text and SECRET_B not in text                 # never a value


@pytest.mark.parametrize("env, needle", [
    ({"LLM_PROVIDER": "openai"}, "found no key"),
    ({"LLM_PROVIDER": "openai", "GOOGLE_API_KEY": SECRET_B}, "OPENAI_API_KEY must be set"),
    ({"LLM_PROVIDER": "nonsense", "OPENAI_API_KEY": SECRET_A}, "no API key to check"),
    ({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": ""}, "found no key"),     # empty = not set
])
def test_refuses_a_missing_or_mismatched_key(env, needle):
    code, text = go(None, fl.FakeLLM(), attempt_id=1, env=env)
    assert code == fc.EXIT_REFUSED and needle in text
    assert SECRET_A not in text and SECRET_B not in text


@pytest.mark.parametrize("cap", [4, 10, 1, 0, -1])
def test_refuses_a_call_cap_outside_two_or_three(cap):
    llm = fl.FakeLLM()
    code, text = go(None, llm, attempt_id=1, cap=cap)
    assert code == fc.EXIT_REFUSED and llm.call_count == 0
    assert ("hard maximum" in text) if cap > 3 else ("too small" in text)


def test_the_cap_defaults_to_three_and_is_required_to_be_an_integer():
    parser = fc.build_parser()
    args = parser.parse_args(["--student", "s", "--attempt-id", "5", "--commit-sha", "abc"])
    assert args.call_cap == 3 == fc.MAX_CALL_CAP
    for missing in (["--attempt-id", "5", "--commit-sha", "abc"],
                    ["--student", "s", "--commit-sha", "abc"],
                    ["--student", "s", "--attempt-id", "5"]):
        with pytest.raises(SystemExit):
            parser.parse_args(missing)                                    # all three required
    with pytest.raises(SystemExit):
        parser.parse_args(["--student", "s", "--attempt-id", "x", "--commit-sha", "abc"])


def test_the_provider_table_is_the_gateways_own():
    assert set(fc.key_variables().values()) == set(gateway._FALLBACK_KEY_ENV_VARS.values())
    for provider, variable in fc.key_variables().items():
        assert fc.check_environment({"LLM_PROVIDER": provider, variable: "x"}) == provider


# --- the hard ceiling at the provider handler ---------------------------------------------------

def test_hard_cap_refuses_the_call_after_the_cap_and_restores_the_handlers():
    made = []
    original = dict(gateway._PROVIDER_HANDLERS)
    for provider in original:
        gateway._PROVIDER_HANDLERS[provider] = lambda *a, **k: made.append(1) or ("{}", 1, 1)
    before = dict(gateway._PROVIDER_HANDLERS)
    with fc.HardCap(3) as cap:
        handler = next(iter(gateway._PROVIDER_HANDLERS.values()))
        for _ in range(3):
            handler("p", 0.0, "m")
        with pytest.raises(fc.CapReached, match="call cap 3 reached"):
            handler("p", 0.0, "m")
        other = list(gateway._PROVIDER_HANDLERS.values())[-1]            # the counter is shared
        with pytest.raises(fc.CapReached):
            other("p", 0.0, "m")
        assert cap.count == 3 and len(made) == 3                         # the 4th never happened
    assert dict(gateway._PROVIDER_HANDLERS) == before                    # restored


def _failing_judge_calls(cap: int) -> int:
    stub = fl.FakeLLM([fl.provider_error(sticky=True)])
    with stub.installed(), fc.HardCap(cap), pytest.raises(Exception):  # noqa: B017
        gateway.judge("prompt", fl.BaseModel)
    return stub.call_count


def test_hard_cap_holds_through_the_real_gateway_when_a_provider_keeps_failing():
    """On a transient failure the gateway walks to the next model of its chain (two models here,
    no other provider has a key). Uncapped it makes two real calls; with a cap of 1 it must stop
    at one: the budget alone cannot do that, the handler ceiling does."""
    assert _failing_judge_calls(10) == 2
    assert _failing_judge_calls(1) == 1


# --- a real read of stored data, fake LLM, test database ---------------------------------------

@needs_db
def test_a_good_run_prints_everything_asked_and_says_dry_run(world):
    _, cur, aid = world
    llm = fake()
    code, text = go(cur, llm, attempt_id=aid)
    assert code == fc.EXIT_OK and llm.call_count == 1
    assert text.count("DRY RUN, nothing stored, nothing posted") == 2    # at the start AND the end
    lines = text.splitlines()
    assert lines[0].startswith("*** DRY RUN") and lines[-1].startswith("*** DRY RUN")
    assert re.search(r"^provider: anthropic$", text, re.M)               # FakeLLM pins anthropic
    assert re.search(r"^model:\s+\S+", text, re.M)
    assert "provider calls: 1 counted by the budget" in text and "cap 3" in text
    assert re.search(r"^tokens:\s+\d+ in, \d+ out$", text, re.M)
    assert "--- deterministic text" in text and "### VDEL feedback:" in text
    assert "1 of 2" in text                                               # the deterministic counts
    assert "--- LLM paragraph" in text and "**More detail**" in text and SUMMARY in text
    assert text.index("### VDEL feedback:") < text.index("**More detail**")   # base first
    assert "VALIDATOR: ACCEPTED" in text
    assert SECRET_A not in text                                           # never a key value


@needs_db
def test_a_rejected_answer_prints_the_reason_and_no_paragraph(world):
    _, cur, aid = world
    wrong = feedback(summary="Your code is wrong.")
    llm = fl.FakeLLM([fl.valid_json(wrong), fl.valid_json(wrong)])
    code, text = go(cur, llm, attempt_id=aid)
    assert code == fc.EXIT_OK                                             # a rejection is a finding
    assert "VALIDATOR: REJECTED" in text and "correctness_claim" in text
    assert "rejected: correctness_claim" in text and "judge call 1: rule correctness_claim" in text
    paragraph = text.split("--- LLM paragraph")[1].split("VALIDATOR")[0]
    assert "More detail" not in paragraph and "Your code is wrong" not in paragraph
    assert "(none: the comment would be the deterministic text alone)" in paragraph
    assert "### VDEL feedback:" in text                                   # the base is still shown


@needs_db
def test_a_provider_failure_is_reported_not_raised(world):
    _, cur, aid = world
    code, text = go(cur, fl.FakeLLM([fl.provider_error(sticky=True)]), attempt_id=aid)
    assert code == fc.EXIT_OK and "VALIDATOR: REJECTED / NOT USED" in text
    assert "provider_error" in text


@needs_db
def test_it_writes_nothing_anywhere(world, tmp_path, monkeypatch):
    conn, cur, aid = world
    before = counts(cur)
    monkeypatch.chdir(tmp_path)
    go(cur, fake(), attempt_id=aid)
    go(cur, fl.FakeLLM([fl.invalid_json(), fl.invalid_json()]), attempt_id=aid)
    assert counts(cur) == before                                          # every table, same counts
    cur.execute("SELECT count(*) FROM traces WHERE actor = 'coach'")
    assert cur.fetchone()[0] == 0
    assert list(tmp_path.iterdir()) == []                                 # no .vdel ledger, no file
    assert not (Path(__file__).resolve().parent.parent / ".vdel").exists()
    assert conn.get_transaction_status() is not None


def test_the_source_has_no_write_statement_and_no_commit():
    source = Path(fc.__file__).read_text(encoding="utf-8")
    code = re.sub(r'"""(?:.|\n)*?"""', "", source)             # docstrings may name the verbs
    code = "\n".join(line.split("  # ")[0] for line in code.splitlines()
                     if not line.lstrip().startswith("#"))
    for forbidden in (r"\bINSERT\b", r"\bUPDATE\b", r"\bDELETE\b", r"\.commit\(", r"log_trace",
                      r"update_mastery", r"feedback_posts", r"UsageLedger", r"requests\.",
                      r"create_issue"):
        assert not re.search(forbidden, code), forbidden
    assert "readonly=True" in inspect.getsource(fc.open_readonly)


@needs_db
def test_the_default_session_is_read_only_and_on_the_test_database():
    conn = fc.open_readonly()                  # D-064: db._open refuses anything but vdel_test
    try:
        cur = conn.cursor()
        cur.execute("SELECT current_database(), current_setting('transaction_read_only')")
        name, read_only = cur.fetchone()
        assert name.endswith("_test") and name != "vdel" and read_only == "on"
        with pytest.raises(Exception, match="read-only"):
            cur.execute("INSERT INTO students VALUES ('_nope','_nope','x')")
    finally:
        conn.rollback()
        conn.close()


# --- commits it refuses ------------------------------------------------------------------------

@needs_db
@pytest.mark.parametrize("commit, needle", [
    (SHA2, "collection_error"),
    (SHA3, "no check failed"),
    ("d" * 40, "no graded results"),
])
def test_refuses_a_commit_the_agent_would_not_call_the_llm_for(world, commit, needle):
    _, cur, aid = world
    llm = fake()
    code, text = go(cur, llm, attempt_id=aid, commit=commit)
    assert code == fc.EXIT_REFUSED and needle in text and llm.call_count == 0
    assert text.count("DRY RUN, nothing stored, nothing posted") >= 1


@needs_db
@pytest.mark.parametrize("status", ["timeout", "tooling"])
def test_refuses_timeout_and_tooling(world, status):
    _, cur, aid = world
    cur.execute("INSERT INTO test_results (attempt_id, commit_sha, test_name, gap_id, passed,"
                " message, status) VALUES (%s,%s,%s,'g_ext_retry',false,'x',%s)",
                (aid, "e" * 40, T_RETRY, status))
    cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at)"
                " VALUES (%s,%s,%s,'2026-08-25 09:00+00')", ("e" * 40, S, ASG))
    llm = fake()
    code, text = go(cur, llm, attempt_id=aid, commit="e" * 40)
    assert code == fc.EXIT_REFUSED and status in text and llm.call_count == 0


@needs_db
def test_refuses_another_students_attempt_and_an_unknown_attempt(world):
    _, cur, aid = world
    llm = fake()
    code, text = go(cur, llm, attempt_id=aid, student="_someone_else")
    assert code == fc.EXIT_REFUSED and "does not belong" in text
    code, text = go(cur, llm, attempt_id=aid + 10_000)
    assert code == fc.EXIT_REFUSED and "no attempt" in text and llm.call_count == 0


@needs_db
def test_a_unique_prefix_of_the_sha_is_accepted(world):
    _, cur, aid = world
    code, text = go(cur, fake(), attempt_id=aid, commit=SHA1[:10])
    assert code == fc.EXIT_OK and "VALIDATOR: ACCEPTED" in text


@needs_db
def test_refuses_the_template_push_of_a_delivered_repo(world):
    _, cur, _ = world
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (TPL_STUDENT, TPL_STUDENT))
    attempt_id, template, first, _second = delivered(cur)
    llm = fake(cited_tests=[])                 # the contrast commit fails a different check
    code, text = go(cur, llm, attempt_id=attempt_id, commit=template, student=TPL_STUDENT)
    assert code == fc.EXIT_REFUSED and "template push" in text and llm.call_count == 0
    ok, out = go(cur, llm, attempt_id=attempt_id, commit=first, student=TPL_STUDENT)   # contrast
    assert TPL_ASG and ok == fc.EXIT_OK and llm.call_count == 1, out


@needs_db
def test_the_json_in_the_run_is_stable_for_the_same_input(world):
    """Same stored data, same scripted answer: the same text (the output has no clock in it)."""
    _, cur, aid = world
    a = go(cur, fake(), attempt_id=aid)[1]
    b = go(cur, fake(), attempt_id=aid)[1]
    assert a == b and json.dumps(a)
