# VDEL: the student-side AI layer

VDEL is a Virtual Data Engineering Lab (UiTM, with the industry partner AntsBees) that teaches Python,
SQL, PySpark and Airflow. This repository is its **student-side intelligence layer**. It watches what a
student pushes to GitHub, keeps a private, continuously updated model of that student, and uses it to
**grade** the work with executed tests and to **coach** the student with feedback on the failing checks.

> Auditability is a functional requirement. A grade we cannot explain is not a grade we can defend.

That sentence decides the design: correctness comes from hidden tests that really run, never from a
language model; every score an LLM does give carries a verbatim quote from the code, checked by string
match; mastery is an interpretable model (BKT), not a neural one; and the record of what happened is an
append-only log from which every belief can be rebuilt.

## Who it is for

| You are | Start with |
|---|---|
| The **operator** (you run the hourly task for one or a few students) | [docs/INSTALL.md](docs/INSTALL.md), then [docs/OPERATIONS.md](docs/OPERATIONS.md) |
| A **course author** (you write a project the students complete) | [docs/AUTHORING.md](docs/AUTHORING.md) |
| A **developer** (you change the code) | [CONTRIBUTING.md](CONTRIBUTING.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Preparing a **pilot** (3 to 5 students) | [docs/PILOT.md](docs/PILOT.md) |
| A **supervisor or reviewer** (you want to know what is claimed and what is proven) | [docs/DECISIONS.md](docs/DECISIONS.md), [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md), [CHANGELOG.md](CHANGELOG.md) |

## What it does, in one pass

1. A course author writes a **master project** with `# @gap:` markers; each marked block is something a
   student must write. Hidden tests grade it.
2. For each student and attempt the system **renders a repository** with some gaps blanked (which ones is
   chosen deterministically from the student's mastery) and **publishes it** as a private GitHub repo.
3. Every hour a task **collects** the student's commits and CI runs, **grades each new commit** by running
   the hidden tests (in a Docker container if configured), updates the **mastery model** and the seven-plus
   variables, and **comments on a GitHub issue** with what failed and what to check next.
4. Optionally (off by default, capped, never decisive) two LLM agents help: a **Feedback Agent** words the
   diagnosis, a **Code Agent** reads working code and scores approach and readability for the instructor.

## A five-minute tour (nothing here writes anywhere)

```bash
cp .env.example .env                  # fill PG_DSN and GITHUB_TOKEN (names only in the example)
docker compose up -d                  # PostgreSQL 16 + pgvector on host port 5433
pip install -r requirements.txt && pip install -e .
python -m scripts.init_db             # idempotent: creates the schema
python -m scripts.doctor --no-network # OK/WARN/FAIL for the machine; read-only
python -m scripts.baseline --full     # a read-only fingerprint of the database
VDEL_REQUIRE_DB=1 python -m pytest -q # the suite, on its own throwaway database
```

The host port is **5433**, not 5432: a native PostgreSQL commonly owns 5432 and shadows the container,
which then shows up only as "password authentication failed". On a fresh clone `doctor` reports the
missing roster as a failure; that is expected until the next step.

To add a real student, copy `config/roster.example.yaml` to `config/roster.yaml`, fill in real values,
and follow [docs/INSTALL.md](docs/INSTALL.md): seed, collect, then
`python -m scripts.run_cycle --dry-run` (what one cycle would do, touching nothing) and the real cycle.

## Where things are

```
assessment/   gap parser and generator, the hidden-test runner, scope check, diagnosis
agents/       Feedback Agent, Code Agent, validation, prompts, budget, fake LLM for tests
collectors/   GitHub collector and CI error classifier
config/       concepts.yaml (the taxonomy), judging.yaml, resources.csv, roster example
curriculum/   master projects (weather_etl, sales_analyzer) with hidden and visible tests
features/     the variables computed from the raw tables
memory/       the only door to traces and the learner profile
scripts/      every command (run_cycle, run_hourly, doctor, deliver_next_attempt, ...)
sql/          the schema, applied in order by scripts/init_db.py
system/       the database door and the LLM gateway
variables/    the formulas V1 to V6
docs/         operations, decisions, architecture, authoring, known issues, archive/
```

A module-by-module map with a diagram is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); the vocabulary
is in [docs/GLOSSARY.md](docs/GLOSSARY.md).

## Documents

| Document | What it is |
|---|---|
| [docs/INSTALL.md](docs/INSTALL.md) | From a clean machine to a first cycle. |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | The runbook: the hourly task, backups, Docker grading, the first real LLM call, the agents flags, the doctor, looking at the data. |
| [docs/PILOT.md](docs/PILOT.md) | What to do before 3 to 5 students use the system (database role, data notice, opt-out). |
| [docs/AUTHORING.md](docs/AUTHORING.md) | How to write a master project: gap markers, hidden tests, `checks.yaml`, `judging.yaml`, the validator. |
| [VDEL_TEN_PROJECT_CURRICULUM.md](VDEL_TEN_PROJECT_CURRICULUM.md) | The design of the ten projects, mapped to the concept taxonomy. |
| [CONTRIBUTING.md](CONTRIBUTING.md) | The loop for every change, the rules that are easy to break, how to write a decision. |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the system fits together: modules, data model, invariants. |
| [docs/agents.md](docs/agents.md) | The agents: inventory, contracts, the fake LLM, the budget, the pipeline. |
| [docs/explanation.md](docs/explanation.md) | File by file: what the code does and why (written at M0 to M4, extended since; see its banner). |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | The vocabulary. |
| [docs/DECISIONS.md](docs/DECISIONS.md), [docs/DECISIONS_AGENTS.md](docs/DECISIONS_AGENTS.md) | Why: every stable decision with its alternatives (D-numbers; the second file holds D-200 and up). |
| [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) | What is wrong, unproven or missing in v1. |
| [CHANGELOG.md](CHANGELOG.md) | A map into the decisions, by period. |
| [agents/PROMPT_CHANGELOG.md](agents/PROMPT_CHANGELOG.md) | The version history of the judge and feedback prompts. |
| [benchmark/RECOMMENDATION.md](benchmark/RECOMMENDATION.md) | The measured judge-model benchmark (generated by `benchmark/run_real_benchmark.py`). |
| [benchmark/submissions/TASK.md](benchmark/submissions/TASK.md) | The task the five benchmark submissions solve. |
| [docs/resources_review.md](docs/resources_review.md) | How the learning resources in `config/resources.csv` were checked. |
| [tests/fixtures/agents/README.md](tests/fixtures/agents/README.md) | Where every agent test fixture comes from. |
| [docs/archive/](docs/archive/README.md) | Dated analyses kept for their reasoning, not as current references. |

## Status

Built and running for one student (`anas`) and tested end to end: telemetry and features, the
event-sourced memory, hidden-test grading with a Docker sandbox, per-commit feedback by GitHub issue,
delivery of the next attempt, the hourly Windows task, and the two agents behind flags. Not built:
differential testing, the Reviewer and orchestrator, the Coach, the knowledge graph. What is unproven or
wrong is listed in [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md); in particular **the Code Agent is an
unmeasured judge and its verdict is never shown to students**.

Authors: Anass BENBELLA (intern, student side), with a tutor-side collaborator, under the supervisor.

License: not decided yet; see the ownership question in docs/ROADMAP.md.
