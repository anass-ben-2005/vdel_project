"""Live D-043 demonstration: per-file commit attribution against the real weather_etl
curriculum data already in the dev DB (4 real assignments, 4 real variants, seeded by
earlier sessions), plus a synthetic student and a hand-built `attempts` state designed
to trigger every branch collect_github.py's per-file attribution added:

  - a commit touching TWO real assignment files (extract.py + load.py) -> raw_commits
    lands with assignment_id NULL (D-043: no single owner), and `attempts` gets updated
    for BOTH matched assignments independently (extract has an open attempt; load's
    only attempt is already submitted).
  - a commit touching ONE assignment file (quality.py) whose assignment has NO
    `attempts` row at all yet (nothing rendered) -> matched, but nothing to attach to.
  - a commit touching NO assignment file (README.md) -> lands in raw_commits, correctly
    untouched by `attempts`, no counter increments (Q2's case, distinct from Q4's).

GitHub's HTTP layer is monkeypatched (`_paged`/`_get`) -- this is a schema/attribution
test, not a live-network test; `collectors/collect_github.py` has no other seam for
substituting commit data. Skips when no database is reachable, matching
`tests/test_pipeline_integration.py`'s own convention exactly.
"""
import os

import pytest

import collectors.collect_github as cg
from system import db

STUDENT = "_test_attr"
OWNER, REPO = "test-org", "weather_etl_repo"

FAKE_COMMITS = [
    {
        "sha": "_test_sha_multi",
        "url": "fake://_test_sha_multi",
        "commit": {"committer": {"date": "2026-08-24T10:00:00Z"},
                    "message": "wire extract output into load"},
    },
    {
        "sha": "_test_sha_quality",
        "url": "fake://_test_sha_quality",
        "commit": {"committer": {"date": "2026-08-24T11:00:00Z"},
                    "message": "add null check"},
    },
    {
        "sha": "_test_sha_readme",
        "url": "fake://_test_sha_readme",
        "commit": {"committer": {"date": "2026-08-24T12:00:00Z"},
                    "message": "typo in README"},
    },
]

# Filenames are PACKAGE-QUALIFIED ('weather_etl/extract.py', not 'extract.py') because
# that is the literal string GitHub puts in a commit's files[].filename for a repo whose
# sources live in a package directory -- and therefore the literal string
# assignments.file_path must equal for _match_assignments to match it. Using bare
# basenames here passed for exactly as long as the master tree was flat, and broke the
# moment it became a real package; that is the shape of bug this test exists to catch.
FAKE_DETAILS = {
    "fake://_test_sha_multi": {
        "stats": {"additions": 12, "deletions": 3},
        "files": [{"filename": "weather_etl/extract.py"},
                  {"filename": "weather_etl/load.py"}],
    },
    "fake://_test_sha_quality": {
        "stats": {"additions": 4, "deletions": 0},
        "files": [{"filename": "weather_etl/quality.py"}],
    },
    "fake://_test_sha_readme": {
        "stats": {"additions": 1, "deletions": 1},
        "files": [{"filename": "README.md"}],
    },
}


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _fake_paged(url, params=None):
    if url.endswith("/commits"):
        yield from FAKE_COMMITS
    # /actions/runs deliberately yields nothing -- this test is about commit
    # attribution, not workflow-run attribution.


def _fake_get(url, params=None):
    return _FakeResp(FAKE_DETAILS[url])


@pytest.fixture
def attribution_scenario(monkeypatch):
    """A synthetic student against the REAL weather_etl assignments/variants, with
    `attempts` deliberately in three different states -- open, already-submitted,
    and absent -- so one collect_all() run exercises all of D-043's branches at once.
    Explicit DELETE teardown, not a rollback: collect_repo() commits internally per
    repo (D-043's own regrouping still calls conn.commit() once per group), so an
    outer transaction has nothing left to roll back by the time the test asserts.
    """
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")

    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (STUDENT, STUDENT))
    cur.execute(
        "SELECT variant_id FROM variants WHERE assignment_id=%s", ("weather_etl_extract",)
    )
    extract_variant = cur.fetchone()[0]
    cur.execute(
        "SELECT variant_id FROM variants WHERE assignment_id=%s", ("weather_etl_load",)
    )
    load_variant = cur.fetchone()[0]

    # weather_etl_extract: attempt_no=1, OPEN (submitted_at NULL) -- the multi-file
    # commit should attach here successfully.
    cur.execute(
        "INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
        "  variant_id, gap_seed) VALUES (%s,'weather_etl','weather_etl_extract',1,%s,1)",
        (STUDENT, extract_variant),
    )
    # weather_etl_load: attempt_no=1, ALREADY SUBMITTED -- the multi-file commit
    # matches this assignment by file, but has nothing open to attach to.
    cur.execute(
        "INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
        "  variant_id, gap_seed, submitted_at) VALUES"
        " (%s,'weather_etl','weather_etl_load',1,%s,2,now())",
        (STUDENT, load_variant),
    )
    # weather_etl_quality: NO attempts row at all -- nothing rendered yet.
    conn.commit()
    cur.close()
    conn.close()

    cg._STATS = cg.Stats()   # clean counters for this run, not whatever earlier tests left
    monkeypatch.setattr(cg, "_paged", _fake_paged)
    monkeypatch.setattr(cg, "_get", _fake_get)

    yield

    with db.cursor() as c:
        # attempts.commit_sha references raw_commits(sha) -- must clear the referencing
        # row before the referenced one, or the FK rejects the delete.
        c.execute("DELETE FROM attempts WHERE student_id=%s", (STUDENT,))
        c.execute("DELETE FROM raw_commits WHERE student_id=%s", (STUDENT,))
        c.execute("DELETE FROM students WHERE student_id=%s", (STUDENT,))


pytestmark = pytest.mark.skipif(
    not os.environ.get("PG_DSN"), reason="PG_DSN not set; integration test needs a database"
)


def test_multi_assignment_commit_and_unattached_counter(attribution_scenario, capsys):
    repos = [
        {"owner": OWNER, "repo": REPO, "student_id": STUDENT, "assignment_id": aid}
        for aid in ("weather_etl_extract", "weather_etl_transform",
                    "weather_etl_load", "weather_etl_quality")
    ]

    with db.connect() as conn:
        result = cg.collect_all(conn, repos)

    print(f"\nD-043 live run: {result['stats']}")

    with db.cursor() as cur:
        cur.execute(
            "SELECT sha, assignment_id FROM raw_commits WHERE student_id=%s ORDER BY sha",
            (STUDENT,),
        )
        landed = dict(cur.fetchall())
        cur.execute(
            "SELECT assignment_id, commit_sha FROM attempts"
            " WHERE student_id=%s ORDER BY assignment_id",
            (STUDENT,),
        )
        attempts_state = dict(cur.fetchall())

    print(f"D-043 live run: raw_commits landed = {landed}")
    print(f"D-043 live run: attempts.commit_sha by assignment = {attempts_state}")

    # raw_commits: every commit lands, regardless of attribution outcome (Q2).
    assert landed == {
        "_test_sha_multi": None,        # two matches -> honest NULL, not a guess
        "_test_sha_quality": "weather_etl_quality",   # one match -> real attribution
        "_test_sha_readme": None,       # zero matches -> honest NULL
    }

    # D-045a: the collector writes NOTHING to attempts. An assignment freezes only when
    # its hidden tests reach 100% pass, and the collector sees pushes, not test outcomes --
    # so commit_sha stays NULL even for the assignment that DOES have an open attempt and
    # DID receive a matching commit. This assertion previously read
    # `== "_test_sha_multi"`, encoding the pre-D-045 behaviour where the first push froze
    # the attempt and the `WHERE submitted_at IS NULL` guard then silently ignored every
    # later commit. It is inverted here on purpose: it is now the regression guard against
    # freeze-on-push coming back.
    assert attempts_state["weather_etl_extract"] is None
    assert attempts_state["weather_etl_load"] is None

    # the actual thing this test exists to prove: not a silent 0-row UPDATE.
    #   1x weather_etl_load  (matched, but already submitted)
    # + 1x weather_etl_quality (matched, but nothing rendered yet)
    assert cg._STATS.commits_without_open_attempt == 2
