# DATA_PROTECTION.md: what student data the system holds, and what is not yet decided

A factual outline, drawn from the code and the decisions, for whoever owns data protection for a cohort. It is
not legal advice and it settles nothing: the open points are listed in section 5. Where a fact could not be
confirmed from the repository it says `TODO(verify)`.

## 1. What is stored, and where

- **In PostgreSQL** (the `vdel` database; the container publishes host port 5433, `README.md`): students (an id, a
  GitHub login, a cohort), raw commits (hash, time, line counts, message), CI runs, the derived attempts, gaps,
  variants, test results, the feature rows, the append-only `traces` log and the `learner_profile`
  (`CLAUDE.md` section 6; `sql/`). Hidden-test results are keyed to the student's attempt.
- **Backups** are `pg_dump` files in `backups/` (git-ignored). They hold the same student data, including code
  excerpts (`docs/OPERATIONS.md` section 9; the comment in `.gitignore`).
- **Logs** in `logs/` (git-ignored): one file per day, 14 days kept (`scripts/run_hourly.py`, D-091).
- **The LLM call ledger** `.vdel/llm_usage.json` holds call counts only, no content (`agents/budget.py`).
- **In git:** nothing about a real student is tracked. `config/roster.yaml` (logins, repositories) and `.env`
  are git-ignored; `config/roster.example.yaml` is the template.

## 2. What leaves the machine

- **GitHub:** the student's own repository is created and read through the GitHub API; feedback is posted as an
  issue comment under the instructor's account (`docs/OPERATIONS.md` sections 7, 8; D-089, D-090).
- **An AI provider, only when the agents are switched on** (`--with-llm`, `--with-code-agent`, `--agents-v2`; all
  off by default, D-099, D-104, D-108): the Feedback Agent sends the failing check names and an excerpt of the
  student's own code lines (at most 4000 characters in v2) and the Code Agent sends the submission
  (D-103 for what is cut before sending; D-108 for the excerpt). The student notice states that the checks
  themselves are not AI, that the provider does not receive the student's name, and what is sent
  (`scripts/render_student_repo.py` `DATA_NOTICE`, checked by `tests/test_pilot.py`).
- **Posted comments** are checked so that the source of a hidden test never appears in them
  (`scripts/post_feedback.py`, `assert_no_hidden_source`).

## 3. Opt-out

`ai_notes: false` on a student's roster entry opts that student out of every AI note; the check fails closed (anything
that is not `true` is treated as opted out) (`config/roster.example.yaml`, `docs/PILOT.md` section 3, D-110 item 3).
Students delivered before the notice existed were not shown it (KNOWN_ISSUES item 23).

## 4. Controls that exist

- The test suite never connects to the real database (`CONTRIBUTING.md`, D-064).
- Hidden-test grading runs in a sandboxed copy with an explicit environment, and in a Docker container when configured
  (`VDEL_GRADING_SANDBOX=docker`, D-065, D-092): no token, no connection string reaches a student's code.
- A database role that cannot update or delete traces and does not own the schema is prepared in
  `sql/pilot/vdel_cycle_role.sql` and is **not applied** (D-110, `docs/PILOT.md` section 2).
- `traces` is append-only by a database rule (`CLAUDE.md` section 7, invariant 1).

## 5. Not decided, not written down

1. **Consent.** The notice informs; it does not obtain consent (KNOWN_ISSUES item 23). The route has to be confirmed
   by the course author and whoever owns data protection before a pilot of 3 to 5 students.
2. **Retention.** How long raw commits, traces and backups are kept is not written down. `TODO(verify)`: a policy.
3. **Deletion.** `traces` cannot be deleted by design (the rule makes `DELETE` a no-op), so removing one student
   needs a decision that does not exist yet (KNOWN_ISSUES item 17 describes the consequence for test data).
   `TODO(verify)`: how deletion would be done and what it would do to the replay guarantee.
4. **The legal basis.** The module document notes that student code is personal data and cites the Malaysian
   Personal Data Protection Act as amended in 2024 (`docs/design/VDEL_Modules_3_9_Build.md`, the PDPA notes).
   `TODO(verify)`: confirm which law applies to the deployment.
5. **The pilot database role** was never executed on a PostgreSQL (KNOWN_ISSUES item 23): apply it to a copy first.
