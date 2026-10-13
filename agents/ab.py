"""agents/ab.py -- A/B arm assignment for the Feedback Agent, behind `--ab-llm` (D-110).

The question a pilot has to answer before the LLM paragraph is worth its money is simple: do
students who get it pass sooner than students who get the deterministic text alone? This module is
the assignment half of that experiment; `scripts/ab_report.py` is the read-only half.

THE ASSIGNMENT. For every graded commit that has at least one failing check, the arm is a pure
function of the pair (attempt_id, commit_sha): `llm` or `control`. The same pair always gets the
same arm, in any process, on any machine, in any order, so a re-run or a second cycle can never
move a commit from one arm to the other. The function is a hash, not a random draw, so nothing
needs to be remembered to reproduce it; it is also STORED, because a stored assignment is what the
report reads and what survives a change of the rule.

  llm      the Feedback Agent runs exactly as it would without the experiment (v1, or v2 with
           `--agents-v2`), and its paragraph, if it passes validation, is posted under the
           deterministic text
  control  no agent, no provider call: the student gets the deterministic text alone

THE RECORD. One `coach`/`intervention` trace per (attempt, commit), `payload.agent =
"ab_assignment"`, holding the arm, the salt and the rule. `intervention` is a non-mastery kind: it
can never feed BKT, and `memory/memory.py` is unchanged. The record is written whether or not the
agent later produces a paragraph (a rejected or failed answer is still an `llm` commit), which is
what makes the arms comparable.

WHAT THIS CANNOT TELL YOU (also printed by the report): the unit is the COMMIT, so one attempt can
sit in both arms at different pushes and a student sees both kinds of note; the numbers are small;
the outcome (pushes until the attempt freezes) depends on the exercise as much as on the note; and
nothing here is a significance test. It is the descriptive comparison the pilot needs, nothing
more.
"""
from __future__ import annotations

import hashlib

LLM, CONTROL = "llm", "control"
ARMS = (LLM, CONTROL)
AGENT = "ab_assignment"
SALT = "vdel-ab-v1"
RULE = "sha256('<salt>:<attempt_id>:<commit_sha>'), first byte even -> llm, odd -> control"


def arm_for(attempt_id: int, commit_sha: str, salt: str = SALT) -> str:
    """The arm of one (attempt, commit). Pure and stable: see the module docstring."""
    digest = hashlib.sha256(f"{salt}:{int(attempt_id)}:{commit_sha}".encode()).digest()
    return LLM if digest[0] % 2 == 0 else CONTROL


def has_failing_check(cur, attempt_id: int, commit_sha: str) -> bool:
    """True when the commit was graded with status `ok` and at least one check failed."""
    cur.execute("SELECT count(*) FILTER (WHERE NOT passed), count(*) FROM test_results"
                " WHERE attempt_id = %s AND commit_sha = %s AND status = 'ok'",
                (attempt_id, commit_sha))
    failed, total = cur.fetchone()
    return bool(total) and failed > 0


def stored_arm(cur, attempt_id: int, commit_sha: str) -> str | None:
    cur.execute("SELECT payload->>'arm' FROM traces WHERE actor = 'coach' AND kind = 'intervention'"
                " AND payload->>'agent' = %s AND payload->>'commit_sha' = %s"
                " AND (payload->>'attempt_id')::bigint = %s ORDER BY trace_id LIMIT 1",
                (AGENT, commit_sha, attempt_id))
    row = cur.fetchone()
    return row[0] if row else None


def record_arm(mem, cur, student_id: str, assignment_id: str | None, attempt_id: int,
               commit_sha: str) -> str | None:
    """The arm of this commit, stored once; None when the commit has no failing check (it is not
    part of the experiment). A stored assignment wins over the rule, so changing `SALT` later
    cannot move a commit that was already assigned. Writes through `mem.log_trace` on `cur`'s
    connection."""
    if not has_failing_check(cur, attempt_id, commit_sha):
        return None
    existing = stored_arm(cur, attempt_id, commit_sha)
    if existing in ARMS:
        return existing
    arm = arm_for(attempt_id, commit_sha)
    mem.log_trace(student_id, "coach", "intervention",
                  {"agent": AGENT, "attempt_id": attempt_id, "commit_sha": commit_sha, "arm": arm,
                   "salt": SALT, "rule": RULE},
                  assignment_id=assignment_id, conn=cur.connection)
    return arm
