# INSTALL.md: from a clean machine to a first cycle

For the person who sets the system up. After this, daily running is [OPERATIONS.md](OPERATIONS.md).
What is checked and what is not is said inline: a step marked **not verified** was not run for this
document.

Contents: 1 What you need · 2 Get the code · 3 The database · 4 Secrets and `.env` · 5 The GitHub token ·
6 An LLM key (optional) · 7 The grading container · 8 The roster and the curriculum · 9 Check the machine ·
10 A first cycle · 11 Run it every hour · 12 A first demo

## 1. What you need

| Need | Why | Check |
|---|---|---|
| Python 3.11 or newer (3.13 is what the code was developed and tested on) | the code and the tests | `python --version` |
| Docker (Desktop on Windows) | the database, and the grading container | `docker info` |
| Git | the grader fetches exactly one commit with it | `git --version` |
| A GitHub account that owns the student repositories, and a token (section 5) | collection, publishing, feedback | `python -m scripts.doctor` |
| Optional: one LLM provider key (section 6) | only for the two agents, which are off by default | |

Windows and Linux are both supported by the code. The hourly **task** has a Windows implementation only;
on Linux use cron (section 11). Commands below use `python`; on Linux that may be `python3`.

## 2. Get the code

```bash
git clone <this repository> vdel && cd vdel
python -m venv .venv
# Windows:  .venv\Scripts\activate        Linux/macOS:  source .venv/bin/activate
pip install -r requirements.txt
pip install -e .                  # makes the top-level packages importable from any directory
```

`requirements.txt` is pinned to the versions the suite ran with (Python 3.13.0 on Windows 11).
**Not verified:** that every pin installs on Python 3.11, which is the version CI uses
(`.github/workflows/ci.yml`); if one does not, loosen that line and write it down in
`docs/KNOWN_ISSUES.md`. If you see `RequestsDependencyWarning ... chardet`, run
`pip install "chardet<6"` (the pin is in `requirements.txt`; an older environment may still hold 7.x).
Airflow is deliberately not here; see `requirements-airflow.txt` and `docs/KNOWN_ISSUES.md` (16).

## 3. The database

PostgreSQL 16 with pgvector, from `docker-compose.yml` in this repository:

```bash
docker compose up -d
docker ps --filter "name=vdel-postgres"      # STATUS must say (healthy)
python -m scripts.init_db                    # idempotent: every statement is IF NOT EXISTS
python -m scripts.smoke_test                 # tables present, traces rejects UPDATE and DELETE
```

The container publishes on host port **5433** (not 5432: a native PostgreSQL usually owns 5432 and
shadows the container, which then fails only as "password authentication failed"). The data lives in the
Docker volume `vdel_pgdata`; `docker compose down` keeps it, **never use `down -v`**.

**If you already run PostgreSQL** and do not want the container: create a database and a role, install
the `vector` extension (`CREATE EXTENSION vector` needs the pgvector package on that server), set `PG_DSN`
to it and run `python -m scripts.init_db`. The compose service is only the convenient default; nothing in
the code needs Docker for the database. **Not verified** against a non-Docker server.

Backup before anything destructive: `docs/OPERATIONS.md` section 9.

## 4. Secrets and `.env`

```bash
cp .env.example .env
```

`.env` is gitignored (never commit it); `.env.example` lists the variable **names** with one comment each.
The ones to fill in:

| Name | Value |
|---|---|
| `PG_DSN` | `postgresql://vdel:vdel@localhost:5433/vdel` for the compose database |
| `GITHUB_TOKEN` | the token of section 5 |

The others are optional and commented out in the example on purpose: **a blank value is not an unset
one** (`LLM_PROVIDER=` makes the import fail). Remove the `#` only to give a value.

## 5. The GitHub token

A **classic** personal access token with scopes **`repo`** and **`workflow`**. `workflow` is needed to push
`.github/workflows/ci.yml` into a student repository; without it publishing is refused before it creates
anything. The token is read from `GITHUB_TOKEN`, sent only in an `Authorization` header or through git's
`GIT_CONFIG_*` environment (never on a command line or in a URL), and never printed.

`python -m scripts.doctor` makes exactly one `GET /user` (only when you run it) and prints the scope names
GitHub returns. A fine-grained token sends no scope header, so the doctor says so and you check its
repository permissions by hand. **Not verified:** that a fine-grained token with the right repository
permissions works for every script.

## 6. An LLM key (optional)

Nothing needs a key until you switch the agents on (`--with-llm`, or the task registered with `-WithLlm`).
To use OpenAI:

```bash
# in .env
LLM_PROVIDER=openai
OPENAI_API_KEY=...
```

Keep **one** provider key in `.env`: the gateway falls back to any other provider that has a key, which
would spend somewhere you did not intend (`docs/OPERATIONS.md` section 12). The OpenAI model ids in
`system/llm.py` were supplied by the author and are not verified against OpenAI's public list (D-225).
The first real call is a manual, capped dry run: `docs/OPERATIONS.md` section 12. Every call has a cap per
run and per day; see section 14 there.

## 7. The grading container (do this before a second student)

```bash
docker build -f docker/grader.Dockerfile -t vdel-grader:1 docker
```

Then set `VDEL_GRADING_SANDBOX=docker` (in the environment of whatever runs the cycle; the Windows task has
a `-UseDockerGrading` switch). Without it the hidden tests run in a subprocess on your machine, which is
acceptable for one trusted student and **not** for a pilot of 3 to 5 (D-086). With it set, a missing Docker or
image makes grading **fail**; it never falls back. The base image is pinned by digest and the package
versions in `docker/grader-requirements.txt` are those installed on 2026-10-11; **not verified** that each
installs on the image's Python 3.11, the first build shows it.

## 8. The roster and the curriculum

```bash
cp config/roster.example.yaml config/roster.yaml     # real GitHub login, real repos, real dates
python -m scripts.seed_data                           # projects, assignments, gaps, students
```

`config/roster.yaml` is gitignored (it holds real logins). `released_at` starts the Learning Pace clock, so
it must be the real date the work began; the example file says the same and the code refuses a note in that
field. `seed_data` also reads `curriculum/master/*` and seeds the gaps from the `# @gap:` markers; that
step does not need the roster ([AUTHORING.md](AUTHORING.md)).

To hand a student their first repository: render and publish it (`python -m scripts.publish_repo --student X
--attempt 1 --dry-run` first; the module docstring explains each step and its safety order), then collect.
Later attempts are delivered with `scripts/deliver_next_attempt` and recorded with `scripts/roster_apply`
(`docs/OPERATIONS.md` sections 8 and 15). **Not verified:** the whole onboarding of a brand-new student on a
brand-new database was not re-run for this document; the pieces each have tests, and the live student was
onboarded with them.

## 9. Check the machine

```bash
python -m scripts.doctor --no-network      # skip the one GET /user, or drop the flag to check the scopes
python -m scripts.baseline --full          # a read-only fingerprint of the database; keep the output
VDEL_REQUIRE_DB=1 python -m pytest -q      # the suite (about eight minutes); needs the database
ruff check .
```

`doctor` prints `OK`, `WARN` or `FAIL` per line and exits 1 only on a `FAIL`. The tests run on their own
throwaway database named `<yours>_test` and never connect to the real one (D-064); `VDEL_REQUIRE_DB=1` turns
"the test database could not be built" from a silent skip into an error.

## 10. A first cycle

```bash
python -m scripts.run_cycle --dry-run      # reads only: what a cycle would do today
python -m scripts.run_cycle                # collect, grade, features, profile (writes the database)
python -m scripts.post_feedback --student X --issue     # read what feedback WOULD be posted
```

A cycle never posts to GitHub; posting is a separate step that needs both `--apply` and
`VDEL_ALLOW_GITHUB_WRITE=1` (`docs/OPERATIONS.md` sections 1 and 7). The cycle logs a `WARN` for any open
attempt the roster cannot reach.

## 11. Run it every hour

**Windows** (Task Scheduler), from `docs/OPERATIONS.md` section 3:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\register_task.ps1 -WhatIf   # preview
powershell -ExecutionPolicy Bypass -File scripts\windows\register_task.ps1           # observe only
```

The task writes `logs\run_hourly-YYYY-MM-DD.log`. Flags that change what it does (`-AllowGitHubWrite`,
`-UseDockerGrading`, `-WithLlm`, `-WithCodeAgent`) are described in `docs/OPERATIONS.md` sections 3, 11 and
14. **Re-registering replaces the whole command**, so repeat the switches you want to keep.

**Linux/macOS** (no script is provided; **not verified**): run the same command from cron, with the
environment the task would set.

```cron
0 * * * *  cd /path/to/vdel && . .venv/bin/activate && VDEL_GRADING_SANDBOX=docker python -m scripts.run_hourly >> logs/cron.log 2>&1
```

`run_hourly` takes a Postgres advisory lock, so two overlapping runs cannot both proceed (the second exits
with code 3); it writes its own dated log under `logs/`. Add `VDEL_ALLOW_GITHUB_WRITE=1` only when you want
it to post.

## 12. A first demo

`python -m scripts.demo --skip-network --skip-llm` runs the seven demo beats offline and ends with the
event-sourcing proof (wipe the profile, replay the traces, get the identical profile back). It is **fixed to
the author's data**: student `anas`, project `weather_etl`, and a rendered repo at `renders/anas_attempt1`
(`scripts/demo.py`, constants `STUDENT`, `PROJECT`, `REPO_DIR`). On a new machine it fails on the first beat
that needs that student. What works anywhere: the doctor, the baseline, the suite, and
`python -m scripts.prove_event_sourcing` once there is at least one trace and profile (it exits 2,
"nothing to prove", on an empty database, on purpose).
