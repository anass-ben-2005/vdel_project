# VDEL Student-Side AI Intelligence Layer

This is the student-side intelligence layer for the Virtual Data Engineering Lab at UiTM. It watches student work (via GitHub), maintains an event-sourced profile of each student's mastery, and powers grading and coaching agents.

## Quick Start

```bash
# 1. Set up environment
cp .env.example .env
# Edit .env with your GitHub token and LLM credentials

# 2. Start PostgreSQL with pgvector
docker compose up -d

# 3. Initialize database
python scripts/init_db.py

# 4. Run smoke test
python scripts/smoke_test.py
```

## Architecture

- **Event sourcing:** `traces` table is append-only; `learner_profile` is rebuilt from traces
- **Blackboard:** Agents read shared state from PostgreSQL, write structured verdicts back
- **Seven variables:** Mastery (BKT), discipline, effort, pace, error response, error frequency, help-seeking
- **Agents:** Echo Agent (M2 tracer bullet), Code Agent (M4 research heart)

## Milestones

- **M0:** Foundations (repo, DB, smoke test)
- **M1:** Telemetry + Features (GitHub collector, 7 variables)
- **M2:** Memory + Echo Agent (event sourcing, walking skeleton)
- **M3:** LLM Gateway + Benchmark (model selection)
- **M4:** Code Agent (the research heart)

## Data Source

Anas's own GitHub repos (real commits, real GitHub Actions runs). No synthetic data, no CodeNet.

See `CLAUDE.md` for full architectural details.
