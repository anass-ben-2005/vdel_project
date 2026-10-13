# CURRENT_DEMO.md — M1 pipeline demo: GitHub → raw tables → the seven variables

> A runnable command sequence, not a status record (that's `STATUS.md`) and not a session
> handoff (that's `HANDOFF.md`). Use this to demo or re-demo the M1 telemetry pipeline —
> collector through feature computation — from a clean slate.

Prerequisites (one-time, skip if already done): Postgres running (`docker compose up -d`),
`config/roster.yaml` filled in (copy from `config/roster.example.yaml`), `.env` has `PG_DSN`
and a real `GITHUB_TOKEN`.

---

## 1. Clean the collector's tables

Wipes `raw_commits` and `raw_workflow_runs` only. This resets the collector's incremental
cursor (`MAX(committed_at)` in `raw_commits`) so the next run does a full backfill instead of
an incremental no-op — needed to demo collection from scratch.

```powershell
docker exec -it vdel-postgres psql -U vdel -d vdel -c "TRUNCATE raw_commits, raw_workflow_runs;"
```

**Does not touch** `learner_features`, `traces`, or `learner_profile`. Those are downstream
of the raw tables (features/compute_features.py) or append-only by invariant (`traces`) —
cleaning them is a different, more sensitive operation and out of scope here.

## 2. Collect from GitHub

```powershell
python -m scripts.collect
```

Prints `collecting N repo(s)` then a `Stats.summary()` line: `api_calls=… detail_calls=…
commits=… runs=… classified=… match_rate=…`. This is the real collector
(`collectors/collect_github.py`) hitting the real repos in `config/roster.yaml`.

Run it a **second time** to demonstrate the idempotent/incremental behaviour (invariant 9,
BUILD_PLAN 1.4): `detail_calls` should drop to `0` and `commits`/most of `runs` to `0`, since
everything is already present.

```powershell
python -m scripts.collect
```

## 3. Compute the seven variables

```powershell
python -m features.compute_features
```

Prints `N student(s) with activity since …`, then per student how many concepts landed in
`mastery`. Reads only the raw tables just populated; writes one new row per dirty student
into `learner_features`.

## 4. Inspect the raw tables

```powershell
docker exec -it vdel-postgres psql -U vdel -d vdel -c "SELECT student_id, assignment_id, committed_at, additions, deletions, files_changed FROM raw_commits ORDER BY committed_at DESC LIMIT 20;"

docker exec -it vdel-postgres psql -U vdel -d vdel -c "SELECT student_id, assignment_id, conclusion, error_class, concept_id, started_at FROM raw_workflow_runs ORDER BY started_at DESC LIMIT 20;"
```

## 5. Inspect the computed variables (`learner_features`)

Expanded display (`\x`) because the seven variables are JSONB columns:

```powershell
docker exec -it vdel-postgres psql -U vdel -d vdel -c "\x" -c "SELECT student_id, computed_at, window_days, mastery, engineering_discipline, effort_regulation, pace, error_response, error_frequency FROM learner_features ORDER BY computed_at DESC LIMIT 1;"
```

Or pretty-printed JSON from Python:

```powershell
python -c "import json; from system import db; cur = db.connect().cursor(); cur.execute('SELECT student_id, mastery FROM learner_features ORDER BY computed_at DESC LIMIT 1'); r = cur.fetchone(); print(r[0]); print(json.dumps(r[1], indent=2))"
```

---

## Not covered here

Feeding these events through the Echo agent (`agents/echo_agent.py`) into `traces` and
`learner_profile` is a separate step — BUILD_PLAN task 2.2 ("wire the fast path to collector
events") isn't built yet, so there is no standing command for it. See `HANDOFF.md` / the
session log for the one-off demo used to exercise that loop manually.
