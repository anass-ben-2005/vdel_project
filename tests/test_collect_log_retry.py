"""D-067 -- the collector downloads a failed run's log only when it needs to.

P5: a failed run that is already classified is never downloaded again (before, every cycle
fetched every failed run's log zip and threw it away). P8: a download that FAILED is stored
as 'empty', counted, retried on later cycles up to MAX_LOG_ATTEMPTS, then left 'empty' with a
reason; and a real classification is never overwritten.

GitHub is faked at `requests.get` so every API call is counted, log downloads included.
collect_repo() commits internally, so each test cleans up with DELETEs (the test database is
throwaway anyway). Skips when no database is reachable.
"""

from __future__ import annotations

import io
import os
import zipfile

import pytest
import requests

import collectors.collect_github as cg
from system import db

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

STUDENT = "_test_logretry"
ASSIGNMENT = "weather_etl_extract"
OWNER, REPO = "test-org", "retry-repo"
BASE = 9_500_000


def log_zip(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("job.txt", text)
    return buf.getvalue()


class Resp:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code, self._body, self.content = status, body, content
        self.headers = {"X-RateLimit-Remaining": "4000"}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            err = requests.HTTPError(f"HTTP {self.status_code}")
            err.response = self
            raise err


class FakeGitHub:
    """`runs`: {run_id: conclusion}. `logs`: {run_id: bytes | int (HTTP error status)}."""

    def __init__(self, runs, logs):
        self.runs, self.logs = runs, logs
        self.requests: list[str] = []

    def log_requests(self):
        return [u for u in self.requests if u.endswith("/logs")]

    def __call__(self, url, headers=None, params=None, timeout=None):
        self.requests.append(url)
        if url.endswith("/commits"):
            return Resp(body=[])
        if url.endswith("/actions/runs"):
            return Resp(body={"workflow_runs": [
                {"id": rid, "status": "completed", "conclusion": conclusion,
                 "run_started_at": "2026-10-01T10:00:00Z", "updated_at": "2026-10-01T10:01:00Z",
                 "head_sha": "f" * 40}
                for rid, conclusion in self.runs.items()]})
        if url.endswith("/logs"):
            run_id = int(url.rsplit("/", 2)[-2])
            answer = self.logs[run_id]
            return Resp(status=answer) if isinstance(answer, int) else Resp(content=answer)
        raise AssertionError(f"unexpected request {url}")


@pytest.fixture
def github(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (STUDENT, STUDENT))
    conn.commit()

    class Session:
        fake: FakeGitHub

        def cycle(self, runs, logs):
            """One collector cycle against a fresh fake; returns (fake, stats)."""
            self.fake = FakeGitHub(runs, logs)
            monkeypatch.setattr(cg.requests, "get", self.fake)
            cg._STATS = cg.Stats()
            cg.collect_repo(conn, OWNER, REPO, STUDENT, [ASSIGNMENT])
            return self.fake, cg._STATS

        def row(self, run_id):
            with conn.cursor() as cur:
                cur.execute("SELECT error_class, concept_id, log_attempts, log_reason"
                            " FROM raw_workflow_runs WHERE run_id = %s", (run_id,))
                return cur.fetchone()

        def insert_stored(self, run_id, error_class, concept_id, attempts=0, reason=None):
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO raw_workflow_runs (run_id, student_id, assignment_id, status,"
                    " conclusion, started_at, completed_at, error_class, concept_id,"
                    " log_attempts, log_reason) VALUES (%s,%s,%s,'completed','failure',"
                    " now(), now(), %s, %s, %s, %s)",
                    (run_id, STUDENT, ASSIGNMENT, error_class, concept_id, attempts, reason))
            conn.commit()

    yield Session()
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM raw_workflow_runs WHERE student_id = %s", (STUDENT,))
        cur.execute("DELETE FROM raw_commits WHERE student_id = %s", (STUDENT,))
        cur.execute("DELETE FROM students WHERE student_id = %s", (STUDENT,))
    conn.commit()
    conn.close()


ASSERTION_LOG = log_zip("E   AssertionError: assert 1 == 2")
UNMATCHED_LOG = log_zip("some output that no rule recognises")


# --- P5: never download a log you already have -------------------------------------------------

def test_a_classified_failed_run_is_never_downloaded_again(github):
    runs = {BASE + 1: "failure", BASE + 2: "failure", BASE + 3: "success"}
    logs = {BASE + 1: ASSERTION_LOG, BASE + 2: UNMATCHED_LOG}

    fake, stats = github.cycle(runs, logs)                       # cycle 1: the real work
    assert len(fake.log_requests()) == 2 and stats.log_downloads == 2
    assert stats.api_calls == 2 + 2                              # commits list + runs list + 2 logs
    assert github.row(BASE + 1)[0] == "AssertionError" and github.row(BASE + 1)[2] == 1
    assert github.row(BASE + 2)[0] == "unmatched"                # a final answer, not retried
    before = [github.row(BASE + i) for i in (1, 2, 3)]

    fake, stats = github.cycle(runs, logs)                       # cycle 2: nothing to learn
    assert fake.log_requests() == [] and stats.log_downloads == 0
    assert stats.log_skipped == 2 and stats.api_calls == 2       # ONLY the two list calls
    assert [github.row(BASE + i) for i in (1, 2, 3)] == before   # nothing changed


def test_calls_per_cycle_no_longer_grow_with_the_number_of_failed_runs(github):
    runs = dict.fromkeys(range(BASE + 10, BASE + 22), "failure")
    logs = dict.fromkeys(runs, ASSERTION_LOG)
    _, first = github.cycle(runs, logs)
    _, second = github.cycle(runs, logs)
    assert first.api_calls == 2 + 12
    assert second.api_calls == 2                                  # was 2 + 12 every cycle


def test_a_successful_run_never_has_its_log_requested(github):
    fake, _ = github.cycle({BASE + 20: "success"}, {})
    assert fake.log_requests() == [] and github.row(BASE + 20) == (None, None, 0, None)


# --- P8: a failed download is retried a bounded number of times -----------------------------------

def test_a_failed_download_is_stored_empty_and_retried_up_to_three_times(github):
    run, runs = BASE + 30, {BASE + 30: "failure"}
    logs = {run: 404}

    github.cycle(runs, logs)                                      # attempt 1
    assert github.row(run) == ("empty", "unclassified", 1, None)
    github.cycle(runs, logs)                                      # attempt 2
    assert github.row(run) == ("empty", "unclassified", 2, None)
    fake, _ = github.cycle(runs, logs)                            # attempt 3 -> final
    assert len(fake.log_requests()) == 1
    error_class, concept, attempts, reason = github.row(run)
    assert (error_class, concept, attempts) == ("empty", "unclassified", 3)
    assert reason == "log unavailable after 3 attempts (HTTP 404)"

    fake, stats = github.cycle(runs, logs)                        # attempt 4 never happens
    assert fake.log_requests() == [] and stats.api_calls == 2
    assert github.row(run) == (error_class, concept, 3, reason)


def test_a_retry_that_succeeds_fills_in_the_classification(github):
    run, runs = BASE + 40, {BASE + 40: "failure"}
    github.cycle(runs, {run: 500})
    assert github.row(run) == ("empty", "unclassified", 1, None)

    github.cycle(runs, {run: ASSERTION_LOG})                      # GitHub recovered
    assert github.row(run) == ("AssertionError", "py.testing", 2, None)

    fake, _ = github.cycle(runs, {run: 500})                      # now final: never downloaded
    assert fake.log_requests() == []
    assert github.row(run)[0] == "AssertionError"


def test_an_existing_empty_row_keeps_its_value_until_a_retry_succeeds(github):
    run = BASE + 50
    github.insert_stored(run, "empty", "unclassified")            # as stored before D-067
    github.cycle({run: "failure"}, {run: 404})
    assert github.row(run) == ("empty", "unclassified", 1, None)  # value unchanged, attempt counted
    github.cycle({run: "failure"}, {run: UNMATCHED_LOG})
    assert github.row(run)[:2] == ("unmatched", "unclassified")


def test_a_log_that_downloads_but_is_empty_is_final(github):
    run = BASE + 60
    github.cycle({run: "failure"}, {run: log_zip("")})
    assert github.row(run) == ("empty", "unclassified", 1, "log downloaded but empty")
    fake, _ = github.cycle({run: "failure"}, {run: log_zip("")})
    assert fake.log_requests() == []


def test_a_real_classification_is_never_overwritten(github):
    run = BASE + 70
    github.insert_stored(run, "KeyError|IndexError", "py.data_structures", attempts=1)
    fake, _ = github.cycle({run: "failure"}, {run: ASSERTION_LOG})
    assert fake.log_requests() == []
    assert github.row(run) == ("KeyError|IndexError", "py.data_structures", 1, None)


def test_the_summary_reports_the_download_counters(github):
    _, stats = github.cycle({BASE + 80: "failure"}, {BASE + 80: ASSERTION_LOG})
    assert "log_downloads=1" in stats.summary() and "log_skipped=0" in stats.summary()
