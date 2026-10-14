# INSTALL.md: from a clean machine to a first cycle

For the person who sets the system up. After this, daily running is [OPERATIONS.md](OPERATIONS.md).
What is checked and what is not is said inline: a step marked **not verified** was not run for this
document.

Contents: 1 What you need · 2 Get the code · 3 The database · 4 to 6 Configure secrets (`.env`, the GitHub token,
an LLM key and a spending limit) · 7 The grading container · 8 The roster and the curriculum · 9 Check the machine ·
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

## 4. Configure secrets: where `.env` lives and what goes in it

```bash
cp .env.example .env
```

- **Where.** `.env` sits at the repository root, next to `.env.example`. The code loads it with
  python-dotenv's `load_dotenv()` (`system/db.py:22`, `system/llm.py:139`, `scripts/doctor.py:545`,
  `scripts/sync_template.py:360`), which looks in the calling file's folder and then in each parent folder, so it is
  found whatever directory you run a command from (python-dotenv `find_dotenv`; it falls back to the current
  directory only in a REPL or debugger).
- **Never committed.** `.env` is the first line of `.gitignore` and `git ls-files .env` prints nothing (invariant 11).
  `.env.example` is committed and holds **names only**. The doctor prints names, never values. If a key ever lands in a
  commit, a log or a chat, revoke it at the provider and make a new one; deleting the commit is not enough.
- **Blank is not unset.** A variable that is present but empty can crash the import (`LLM_PROVIDER=` fails at import,
  `system/llm.py:167`; `FEATURE_WINDOW_DAYS=` fails at `features/compute_features.py:37`). That is why the optional
  lines in the example are commented out: remove the `#` only to give a value.

Every variable of `.env.example`:

| Name | Required | What it is for | Read in |
|---|---|---|---|
| `PG_DSN` | yes | the PostgreSQL connection string; the compose database is `postgresql://vdel:vdel@localhost:5433/vdel`. The test suite derives its own `<name>_test` database from it and never touches the real one (D-064) | `system/db.py:25-30` |
| `GITHUB_TOKEN` | yes, for anything that talks to GitHub | the collector, the grader's checkout of a student commit, `publish_repo`, `deliver_next_attempt`, `sync_template`, `post_feedback` (section 5) | `collectors/collect_github.py:46-55`, `scripts/grade_collected.py:170`, `scripts/publish_repo.py:606` |
| `LLM_PROVIDER` | only with `--with-llm` | which provider the gateway uses: `anthropic` (the default when unset), `openai`, `google` or `nvidia`; a typo stops the process at import | `system/llm.py:167` |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `NVIDIA_API_KEY` | only the one of your provider | the key for that provider (section 6) | `system/llm.py`, `scripts/doctor.py:55-60` |
| `FEATURE_WINDOW_DAYS` | no | window in days for the learner features, default `14` | `features/compute_features.py:37` |
| `VDEL_ALLOW_GITHUB_WRITE` | no | `1` lets the hourly task post feedback to GitHub; unset, it only logs that it WOULD post | `scripts/post_feedback.py:334`, `scripts/run_hourly.py` (module docstring) |
| `VDEL_GRADING_SANDBOX` | no | `docker` grades student code in the `vdel-grader` container and never falls back to a subprocess (section 7) | `assessment/test_runner.py:141` |
| `VDEL_GRADING_IMAGE` | no | the grading image when it is not the default `vdel-grader:1` | `assessment/test_runner.py:142-143` |

Two more variables exist but are not for you to set: `VDEL_REQUIRE_DB=1` (you set it when you run the suite, section 9)
and `VDEL_TESTING` (set only by `tests/conftest.py`; it makes the code refuse any database not ending in `_test`,
`system/db.py`).

## 5. Configure secrets: the GitHub token

A **classic** personal access token with scopes **`repo`** and **`workflow`**, created in the GitHub account that will
own the student repositories (the instructor account: `publish_repo` makes the repository owned by the token's user
unless the roster names an owner). `workflow` is needed to push `.github/workflows/ci.yml` into a student repository;
without it publishing is refused before it creates anything (`scripts/publish_repo.py:365`, `preflight_scopes`;
`scripts/doctor.py:49`). The token is read from `GITHUB_TOKEN`, sent only in an `Authorization` header or through git's
`GIT_CONFIG_*` environment (never on a command line or in a URL), and never printed. The exact menu names of GitHub's
token page are not reproduced here (`TODO(verify)`: they change).

`python -m scripts.doctor` makes exactly one `GET /user` (only when you run it) and prints the scope names
GitHub returns. A fine-grained token sends no scope header, so the doctor says so and you check its
repository permissions by hand. **Not verified:** that a fine-grained token with the right repository
permissions works for every script.

## 6. Configure secrets: an LLM key, one provider, and a spending limit

Nothing needs a key until you switch the agents on (`--with-llm`, or the task registered with `-WithLlm`).
To use OpenAI:

```bash
# in .env
LLM_PROVIDER=openai
OPENAI_API_KEY=...
```

- **Keep one provider key in `.env`.** The gateway first tries the other models of your provider, and then **any other
  provider that has a key set**, so a second key means calls can be billed to an account you did not choose
  (`system/llm.py:684`, `_call_with_fallback`; `docs/OPERATIONS.md` section 12). The doctor warns when more than one
  key is present (`scripts/doctor.py:372-384`).
- **Set a spending limit at the provider before the first call.** The project's caps (10 provider calls per run and 20
  per day by default) count calls, not money, a failed fallback attempt is not counted, and no prices are stored in
  the repository (KNOWN_ISSUES item 13). A limit or a prepaid balance in the provider's billing settings is the only
  cap on money. Where that setting is depends on the provider (`TODO(verify)`: the menu names).
- The OpenAI model ids in `system/llm.py` were supplied by the author and are not verified against OpenAI's public list
  (D-225). The first real call is a manual, capped dry run: `docs/OPERATIONS.md` section 12; every call has a cap per
  run and per day (section 14 there).

**Confirm the setup with the doctor** (`python -m scripts.doctor`, section 9). It prints one line per check and never a
value. For a correct setup you should see `github token OK`, `github scopes OK has: ...` listing `repo` and `workflow`
(`scripts/doctor.py:226-278`), `database OK connected ...` (your `PG_DSN`), `llm provider OK LLM_PROVIDER=openai` and
`llm keys OK present: OPENAI_API_KEY` (`scripts/doctor.py:348-388`). `FAIL` means a required name is missing or the
token was rejected (exit code 1); `WARN` means something to read, such as two provider keys or `LLM_PROVIDER` naming a
provider whose key is not set.

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
