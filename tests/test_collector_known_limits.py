"""D-093 -- a KNOWN LIMIT of the collector, pinned so nobody is surprised by it (not a fix).

`collect_repo` asks GitHub only for commits newer than the largest `committed_at` it has stored for
the student (`?since=`). The date comes from the commit's COMMITTER date, which the student controls
(`git commit --date`, `GIT_COMMITTER_DATE`, a clock that is wrong). One stored commit dated in the
future therefore makes every later honest commit older than `since`, and GitHub never returns them:
they are never collected and never graded. A rebased / force-pushed commit with a committer date
older than the newest stored one is skipped the same way. The fix is in docs/DECISIONS.md D-093
("later"); when it is made, this test is the one to change.
"""

import os

import pytest

import collectors.collect_github as cg
from system import db

STUDENT = "_test_since"
pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)


@pytest.fixture
def stored_future_commit(monkeypatch):
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (STUDENT, STUDENT))
    cur.execute("INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at,"
                " additions, deletions, files_changed, message)"
                " VALUES ('_since_future', %s, 'weather_etl_extract', '2099-01-01 00:00+00',"
                " 1, 0, 1, 'dated in the future')", (STUDENT,))
    conn.commit()
    cg._STATS = cg.Stats()
    seen = {}

    def fake_paged(url, params=None):
        if url.endswith("/commits"):
            seen["params"] = dict(params or {})
        return iter(())

    monkeypatch.setattr(cg, "_paged", fake_paged)
    yield conn, seen
    conn.close()
    with db.cursor() as c:
        c.execute("DELETE FROM raw_commits WHERE student_id = %s", (STUDENT,))
        c.execute("DELETE FROM students WHERE student_id = %s", (STUDENT,))


def test_known_limit_one_future_dated_commit_moves_since_past_every_later_commit(
        stored_future_commit):
    conn, seen = stored_future_commit
    cg.collect_repo(conn, "o", "r", STUDENT, ["weather_etl_extract"])
    assert seen["params"]["since"].startswith("2099-01-01")      # GitHub is asked for 2099 onwards
