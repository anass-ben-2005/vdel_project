# VALIDATION.md: what has been shown to work, and what has not

Each line says what was shown, with which command, on which date, and where the reasoning is recorded. No run
output is pasted here; rerun the command to see it. Items marked `TODO(verify)` could not be confirmed from the
repository and need the date, the command line or the decision number added by whoever ran them. What is wrong or
unproven is also in [KNOWN_ISSUES.md](KNOWN_ISSUES.md); what comes next is in [ROADMAP.md](ROADMAP.md).

## 1. Shown by hand on 2026-10-13

These were run by the author against real services and are reported here from the author's account; no decision
entry records the run itself yet (`TODO(verify)`: add one, with the exact command lines).

| # | What was shown | Command(s) | Where the design is recorded |
|---|---|---|---|
| 1 | The hourly cycle ran with grading in a Docker container and feedback posted as a GitHub issue comment | `python -m scripts.run_hourly` with `VDEL_GRADING_SANDBOX=docker` and GitHub writes enabled (`docs/OPERATIONS.md` sections 1, 4, 11); `TODO(verify)` exact command line | D-089, D-091, D-092 |
| 2 | The Feedback Agent called a real OpenAI model; a comment with an AI paragraph was posted and the validator accepted the paragraph | `python -m scripts.run_hourly --with-llm` (`docs/OPERATIONS.md` section 14); `TODO(verify)` exact command line | D-099, D-101, D-104 |
| 3 | The Code Agent called a real OpenAI model; its verdict was stored and never posted | `--with-code-agent` on the same command (`docs/OPERATIONS.md` section 14); `python -m scripts.code_agent_report` reads it | D-103, D-104 |
| 4 | A second GitHub account: a private repository owned by the instructor account, a collaborator invitation, collection and grading of that account's commits, the freeze of the attempt, and delivery of the next attempt | `python -m scripts.publish_repo`, `python -m scripts.run_cycle`, `python -m scripts.deliver_next_attempt` (`docs/OPERATIONS.md` sections 7, 8, 15); `TODO(verify)` exact command lines | D-057, D-083, D-090, D-105 |
| 5 | The whole test suite passes | `VDEL_REQUIRE_DB=1 python -m pytest -q` gives 1572 passed, 3 skipped, 1 xfailed (repeated on 2026-10-14) | `CONTRIBUTING.md` (the loop), D-064 |
| 6 | The Code Agent's correctness opinion disagreed with four passing hidden tests out of four, in 3 of 3 observed cases | `python -m scripts.code_agent_report`; `TODO(verify)`: which commits | D-036, D-061 (correctness is decided by executed tests; the model's opinion is never a result) |

Item 6 is the reason the system never lets the model decide correctness.

## 2. Shown earlier

| What was shown | Command | Date | Source |
|---|---|---|---|
| The schema builds from scratch and a second run changes nothing; the `traces` table rejects `UPDATE` and `DELETE` | `python -m scripts.init_db` (twice), `python -m scripts.smoke_test` | 2026-08-11 | M0 of the author's evidence board (not delivered); `TODO(verify)` decision id |
| Computing the features twice leaves `learner_features` unchanged | `python -m features.compute_features` (twice), then `SELECT` on `learner_features` | 2026-08-25 | the author's evidence board (not delivered); `TODO(verify)` decision id |
| The classifier's match rate on real CI failures was recorded: 9 of 21 failures matched a concept (0.429) | `SELECT` over `raw_workflow_runs` where `error_class IS NOT NULL` | 2026-09-02 | the author's evidence board (not delivered); KNOWN_ISSUES item 7, D-096 |
| Wipe `learner_profile`, replay the traces, get an identical profile | `python -m scripts.prove_event_sourcing` | 2026-08-25 and 2026-08-31 | D-034, D-082; `python -m scripts.demo` beat 7 |
| The seven demo beats all pass (format, variants, hidden tests, attribution, mastery, graded verdict with quotes, replay) | `python -m scripts.demo` | 2026-08-31 | the author's evidence board (not delivered); beats 3 and 5 are described in D-076 and D-078 |
| Hidden tests run for real in a separate process; correctness is executed, not asserted | `python -m scripts.grade_collected` (sandboxed) | from 2026-10-07 | D-036, D-046, D-056, D-065 |
| A second student's first live cycle: one commit collected, one graded, mastery updated by one observation | `python -m scripts.run_cycle --student student2` with a scratch roster | 2026-10-11 | D-083 |
| One real benchmark of one provider on five PySpark files: 51 of 60 exact agreement (85%), 60 of 60 within one level; below target on `approach` | `python -m benchmark.run_real_benchmark` | 2026-10-12 | D-102; `benchmark/RECOMMENDATION.md` (read its section 7 first: the labels were pre-written by an LLM and reviewed on 10 rows) |

## 3. Not proven

- **The v2 agents with a real model.** `--agents-v2` has only met the scripted fake provider (KNOWN_ISSUES items 21, 22; D-108, D-109).
- **The Code Agent as a judge.** It is an unmeasured judge: the benchmark labels were pre-written by an LLM, the production prompt
  was never benchmarked, nothing measures it on `weather_etl` (KNOWN_ISSUES items 11, 22).
- **Bulk publishing and delivery** for many students (ROADMAP item 3).
- **A multi-student pilot**, the pilot database role, and consent and retention (KNOWN_ISSUES item 23; `docs/PILOT.md`).
- **A production-mode benchmark** of the prompt actually used with `--agents-v2` (ROADMAP item 2).
- **The Airflow DAG** was never run (KNOWN_ISSUES item 16); its three task bodies were exercised directly.
- **Installing the pinned dependencies on Python 3.11**, the version CI uses (`docs/INSTALL.md`).
- **The container grading image on a clean machine** and the pilot role SQL on a clean PostgreSQL (`docs/OPERATIONS.md` section 11, KNOWN_ISSUES item 23).
