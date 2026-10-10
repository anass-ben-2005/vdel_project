"""D-063 -- the collector stores the Actions API's `head_sha` on raw_workflow_runs.

GitHub's HTTP layer is monkeypatched (`_paged`), like tests/test_collect_attribution.py.
collect_repo() commits internally, so this test cleans up with explicit DELETEs rather than a
rollback. Skips when no database is reachable.
"""

import os

import pytest

import collectors.collect_github as cg
from system import db

pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)

STUDENT = "_test_hs"
SHA_WITH = "c" * 40
RUN_WITH, RUN_WITHOUT = 9_600_001, 9_600_002

FAKE_RUNS = [
    {"id": RUN_WITH, "status": "completed", "conclusion": "success", "head_sha": SHA_WITH,
     "run_started_at": "2026-10-10T03:20:24Z", "updated_at": "2026-10-10T03:20:40Z"},
    # a payload without head_sha must store NULL, not crash the collection
    {"id": RUN_WITHOUT, "status": "completed", "conclusion": "success",
     "run_started_at": "2026-10-10T04:00:00Z", "updated_at": "2026-10-10T04:00:10Z"},
]


def _fake_paged(url, params=None):
    if url.endswith("/actions/runs"):
        yield from FAKE_RUNS


@pytest.fixture
def scenario(monkeypatch):
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (STUDENT, STUDENT))
    conn.commit()
    cur.close()
    conn.close()
    cg._STATS = cg.Stats()
    monkeypatch.setattr(cg, "_paged", _fake_paged)
    yield
    with db.cursor() as c:
        c.execute("DELETE FROM raw_workflow_runs WHERE student_id=%s", (STUDENT,))
        c.execute("DELETE FROM raw_commits WHERE student_id=%s", (STUDENT,))
        c.execute("DELETE FROM students WHERE student_id=%s", (STUDENT,))


def test_collector_stores_head_sha_and_tolerates_its_absence(scenario):
    repos = [{"owner": "test-org", "repo": "hs-repo", "student_id": STUDENT,
              "assignment_id": "weather_etl_extract"}]
    with db.connect() as conn:
        cg.collect_all(conn, repos)
    with db.cursor() as cur:
        cur.execute("SELECT run_id, head_sha FROM raw_workflow_runs WHERE student_id=%s",
                    (STUDENT,))
        stored = dict(cur.fetchall())
    assert stored == {RUN_WITH: SHA_WITH, RUN_WITHOUT: None}
