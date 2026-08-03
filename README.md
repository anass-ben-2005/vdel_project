# VDEL — Student-Side AI Intelligence Layer

Watches students work via GitHub, maintains an event-sourced model of each student, and
uses it to grade submissions with explainable agents and coach students who are stuck.

> Auditability is a functional requirement. A grade we cannot explain is not a grade we
> can defend.

## Quick start

```bash
cp .env.example .env                # PG_DSN is pre-filled; add GITHUB_TOKEN
docker compose up -d                # PostgreSQL 16 + pgvector, on host port 5433
pip install -r requirements.txt && pip install -e .
python -m scripts.init_db           # idempotent; re-running is a no-op
python -m scripts.smoke_test        # tables present + traces is append-only
pytest -q
```

Host port is **5433**, not 5432 — a native PostgreSQL service commonly owns 5432 and
shadows the container silently, surfacing only as "password authentication failed".

## Collecting real telemetry

```bash
cp config/roster.example.yaml config/roster.yaml   # your real repos and start dates
python -m scripts.seed_data
python -m scripts.collect                          # backfill
python -m scripts.collect                          # re-run: almost no API calls
python -m features.compute_features
```

Nothing is seeded by default. `released_at` starts the Learning Pace clock, so a
made-up date makes V4 meaningless.

## Where the code comes from

The formulas are **transcribed**, not designed. `variables/*.py`,
`collectors/*.py` and the schema come from `VDEL_Modules_1_2_Build.md`; each file names
its source in the module docstring and marks any addition inline. Files held
character-for-character against the document are exempted from cosmetic lint rules in
`pyproject.toml` so a diff against the source stays empty.

| Module | Variable | Method |
|---|---|---|
| `variables/mastery.py` | V1 Concept Mastery | BKT + KT-IDEM + Beta posterior |
| `variables/habits.py` | V2 Discipline · V3 Effort | Cronbach α gate · burstiness |
| `variables/pace.py` | V4 Learning Pace | survival analysis, censoring-aware |
| `variables/error_response.py` | V5 Error Response | Jadud/Watwin + wheel-spinning |
| `variables/error_frequency.py` | V6 Error Frequency | opportunity-normalised |
| — | V7 Help-Seeking | seam only; needs the coach (M7) |

## Architecture

- **Land raw first.** Formulas change and carry a `formula_ver`; history is only
  recomputable if the raw events were kept.
- **Event sourcing.** `traces` is append-only — enforced by a database rule, not by
  convention. `learner_profile` is derived and can be rebuilt from it.
- **Fast path / slow path.** Deterministic per-event updates; one weekly LLM reflection.

## Status

M0 (foundations) and M1 (telemetry + features) are built. M2 memory, M3 LLM gateway and
M4 Code Agent are next; see `BUILD_PLAN.md`.

Known open questions are marked `TODO(verify)` in the code, and one worked-example
discrepancy is recorded as a strict `xfail` in `tests/test_sara.py`.
