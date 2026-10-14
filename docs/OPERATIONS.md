# OPERATIONS.md -- running VDEL on the Windows PC

For the person who runs the system (you). Everything here was written in the overnight batch of
2026-10-12 and **none of the commands was run by the batch**: run them yourself, in order.
Decisions behind it: `docs/DECISIONS.md` D-086 to D-092.

## 1. What runs, and when

One Windows Task Scheduler task, **"VDEL hourly"**, runs `python -m scripts.run_hourly` every hour:

1. `run_cycle` for every student in `config/roster.yaml`: collect from GitHub, grade each new commit
   with the hidden tests, update mastery, features and the profile.
2. Feedback by GitHub issue for the commits graded in the last 48 hours that have no comment yet.
   **This phase writes to GitHub only when the task has `VDEL_ALLOW_GITHUB_WRITE=1`.** Without it the
   log says `WOULD POST` and nothing is sent.

Two Postgres advisory locks stop overlaps: a second `run_hourly` exits with code 3 at once, and a
manual `run_cycle` started while the task runs is refused too.

## 2. Before the first run (once)

```powershell
cd "<repo-folder>"

# 1. Docker Desktop is running, then the database:
docker compose up -d
docker ps --filter "name=vdel-postgres"        # STATUS must say (healthy)

# 2. Take a backup (backups\ is gitignored):
mkdir backups -Force
docker exec vdel-postgres pg_dump -U vdel -d vdel -Fc -f /tmp/vdel_before_v1.dump
docker cp vdel-postgres:/tmp/vdel_before_v1.dump backups\vdel_before_v1.dump

# 3. Apply the additive migrations (idempotent; it re-applies every sql file):
python -m scripts.init_db
#    adds: attempts.lint_violations / lint_changed_loc / lint_tool (D-088),
#          table feedback_issues (D-089), attempts.started_at (D-090)

# 4. Look at what the task would do, without changing anything:
python -m scripts.run_hourly --dry-run
python -m scripts.baseline --full
```

`.env` must hold `GITHUB_TOKEN` (a classic token with `repo` and `workflow` scopes: `workflow` is
needed to publish a repo that contains `.github/workflows/ci.yml`). The project does not read it
for anything else. Never paste it into a log or a message.

## 3. Install the hourly task

```powershell
# Preview (changes nothing):
powershell -ExecutionPolicy Bypass -File scripts\windows\register_task.ps1 -WhatIf

# Observe only: collects, grades, computes, logs what it WOULD post. Nothing goes to GitHub.
powershell -ExecutionPolicy Bypass -File scripts\windows\register_task.ps1

# Later, when you want it to post feedback comments:
powershell -ExecutionPolicy Bypass -File scripts\windows\register_task.ps1 -AllowGitHubWrite -Force
```

The task runs as you, only while you are logged on, never starts a second copy, runs once as soon as
possible if the PC was off at the scheduled time, and is killed after 50 minutes.

## 4. Check it

```powershell
Get-ScheduledTaskInfo -TaskName "VDEL hourly"        # LastRunTime, LastTaskResult (0 = ok)
Get-Content logs\run_hourly-$(Get-Date -Format yyyy-MM-dd).log -Tail 40
```

`LastTaskResult`: 0 ok, 1 a student or a post failed (the log says which) **or the task did not start
at all (see below)**, 2 the database is unreachable, 3 another run holds the lock.

Logs: `logs\run_hourly-YYYY-MM-DD.log`, one file per day, appended, every line timestamped (UTC).
Its first line of every run is `run_hourly START pid=... cwd=... python=...`, written before anything
else. Files older than 14 days are deleted at the start of each run. `logs\` is gitignored.

### LastTaskResult 1 and no new line in `logs\run_hourly-*.log` (D-095)

**Symptom.** The task ran (LastRunTime is right), ended with `LastTaskResult 1`, and nothing was added
to `logs\`. Since the first line of a run is now written before anything else, a missing `START` line
means `run_hourly` never started: the failure happened in the task's own wrapper or in Python's start-up.

**Cause found on 2026-10-12.** The project folder name contained an apostrophe. The first
version of `register_task.ps1` put the folder inside a single-quoted PowerShell string
(`Set-Location -LiteralPath '<folder>'`), so the apostrophe ended the string, the command did not parse
(`TerminatorExpectedAtEndOfString`) and nothing ran. Fixed: the command is now passed encoded, every
path is a literal with `'` doubled to `''`, and the folder is set with `-LiteralPath`
(`scripts\windows\task_command.ps1`, tested with a folder named `o'brien & co [x]`). **A task registered
by the old script keeps the broken command: unregister it and register again with the new script.**

**Where to look.** `logs\task_stderr.log` (UTF-8, appended, never rotated: delete it by hand if it grows):

```powershell
Get-Content logs\task_stderr.log -Tail 40
```

- `--- <time> task start, folder <path>`: the wrapper started and found the folder. One per run.
- Lines below it with no new `START` line in the dated log: Python wrote to stderr or failed to start
  (`No module named ...`, a wrong interpreter, a missing package). The text is Python's own.
- `TASK WRAPPER ERROR: python not found: <path>`: `python.exe` moved or was uninstalled. Register the
  task again (it records the interpreter path found at registration, or pass `-PythonExe`).
- No `task start` line at all: the wrapper could not even reach the folder. Look at
  `%TEMP%\vdel_task_stderr.log` (`PROJECT FOLDER NOT FOUND`): the folder was moved or renamed.
- `logs\task_stderr.log` missing and no dated log either: the task did not launch PowerShell. Check
  `Get-ScheduledTaskInfo` (LastRunTime) and the History tab of the task in Task Scheduler.

## 5. Stop or remove it

```powershell
Disable-ScheduledTask -TaskName "VDEL hourly"        # pause (keeps the definition)
Enable-ScheduledTask  -TaskName "VDEL hourly"        # resume
powershell -ExecutionPolicy Bypass -File scripts\windows\unregister_task.ps1     # delete it
```

Removing the task leaves the logs, the database and every file untouched.

## 6. When Docker (the database) is down

Symptom: the log has `DATABASE UNREACHABLE: ...` and the task result is 2. Nothing is lost and
nothing is half-written: the next hour collects everything that is still on GitHub.

```powershell
# Start Docker Desktop, wait until it says it is running, then:
docker compose up -d
docker ps --filter "name=vdel-postgres"        # wait for (healthy)
python -m scripts.run_hourly --dry-run         # confirm, then let the next hour run, or:
Start-ScheduledTask -TaskName "VDEL hourly"
```

If port 5433 is taken or the container will not start: `docker compose logs postgres`. The data
lives in the Docker volume, not in the container, so `docker compose down` does not delete it
(never use `down -v`).

## 7. The first real feedback post (by hand, one student)

Only for a student whose `students.github_username` is a REAL GitHub login (a placeholder is
refused). Do it for yourself first.

```powershell
# a) read what would happen (contacts nothing):
python -m scripts.post_feedback --student anas --issue

# b) post for ONE assignment (writes to GitHub: one issue, one comment per graded commit):
$env:VDEL_ALLOW_GITHUB_WRITE = "1"
python -m scripts.post_feedback --student anas --assignment weather_etl_extract --issue --apply
Remove-Item Env:VDEL_ALLOW_GITHUB_WRITE

# c) run it again: it must post nothing ("nothing to post").
python -m scripts.post_feedback --student anas --assignment weather_etl_extract --issue --apply
```

Without `--apply` AND the environment variable nothing is sent. The comments show the test name and
the exception type only, never an assertion message or hidden test code.

## 8. Delivering attempt 2 (by hand, one student, one stage)

Needs: the current attempt is frozen (its hidden tests reached 100% on a pushed commit), a real
`github_username`, and the feedback tables from section 2.

```powershell
# a) read the plan (contacts nothing, records nothing):
python -m scripts.deliver_next_attempt --student X --assignment weather_etl_extract

# b) do it (creates a private repo, pushes, invites the student, comments the link):
$env:VDEL_ALLOW_GITHUB_WRITE = "1"
python -m scripts.deliver_next_attempt --student X --assignment weather_etl_extract --apply
Remove-Item Env:VDEL_ALLOW_GITHUB_WRITE

# c) record the new repo in the roster with roster_apply (section 15). Without --yes it only
#    shows the diff; read it, then apply. Never edit config\roster.yaml by hand.
python -m scripts.roster_apply --student X --assignment <assignment_id> --owner <owner> --repo <repo>
python -m scripts.roster_apply --student X --assignment <assignment_id> --owner <owner> --repo <repo> --yes
#    then check the cycle sees the new repo (see also section 20):
python -m scripts.run_cycle --dry-run --student X
```

A delivery that stopped half way is finished with the same command plus `--resume`. `--force` (start
attempt N+1 although attempt N is not frozen) is refused unless you also pass `--i-understand`: the
old attempt stays open, and an open attempt wins over a frozen higher one in the grader (D-072).

## 9. Backups and restore

```powershell
docker exec vdel-postgres pg_dump -U vdel -d vdel -Fc -f /tmp/vdel_backup.dump
docker cp vdel-postgres:/tmp/vdel_backup.dump backups\vdel_backup_$(Get-Date -Format yyyyMMdd).dump

# restore (replaces the data; stop the task first):
docker cp backups\vdel_backup_YYYYMMDD.dump vdel-postgres:/tmp/r.dump
docker exec vdel-postgres pg_restore -U vdel -d vdel --clean --if-exists /tmp/r.dump
```

## 10. Known limits of v1 (written down so they are not surprises)

- The PC must be on, logged in, with Docker running. If it is off, nothing is collected until it is
  back on; nothing is lost.
- The diagnosis in a feedback comment is attempt-wide, so the first comment of an attempt can say
  "Keeps failing across several pushes" (D-074 finding).
- Student code runs in a subprocess on this PC unless the container is switched on (section 11).
- A student can still forge the grade from inside the test process, in either mode (section 11).
- Posting is per commit; there is no edit or deletion of an old comment.
- **A student can hide commits from the collector** by dating one in the future (the collector asks GitHub
  only for commits newer than the newest stored date). If a student says "I pushed but nothing happened",
  look at `SELECT max(committed_at) FROM raw_commits WHERE student_id = 'X'` first (D-093).
- A student who deletes their repository makes `run_cycle` report them FAILED every hour until you fix or
  remove their roster rows; nothing else is affected (D-093).

## 11. Grading in a Docker container (D-092)

By default the hidden tests run in a subprocess on this PC with a stripped environment (D-065). That
is acceptable for ONE trusted student (D-086) and **not** for a pilot of 3 to 5: before that, switch
the container on. The container is the same pytest run with `--network none`, a read-only root file
system plus a small tmpfs scratch, a limit of 128 processes, 512 MB and 1 CPU, no capabilities,
`no-new-privileges`, a non-root user, the student's code mounted read-only and the report written to a
separate mount; it is removed afterwards.

```powershell
cd "<repo-folder>"

# 1. Build the image ONCE (needs network; the build context is docker\ only, so .env and backups\
#    are never sent to Docker). The base image is pinned by digest in docker\grader.Dockerfile.
docker build -f docker/grader.Dockerfile -t vdel-grader:1 docker

# 2. Try it on one commit without recording anything: the demo's Beat 3 grades in a rolled-back
#    transaction, so this changes no data.
$env:VDEL_GRADING_SANDBOX = "docker"
python -m scripts.demo --skip-network --skip-llm        # Beat 3 must still say 4/4 passed
Remove-Item Env:VDEL_GRADING_SANDBOX

# 3. Run the container tests against your image (they skip when the image is missing):
$env:VDEL_REQUIRE_DB = "1"; python -m pytest -q tests/test_grading_container.py

# 4. Turn it on for the hourly task (re-register with the switch), or for one command:
powershell -ExecutionPolicy Bypass -File scripts\windows\register_task.ps1 -UseDockerGrading -Force
$env:VDEL_GRADING_SANDBOX = "docker"; python -m scripts.run_cycle --student X
```

Rules worth knowing:

- `VDEL_GRADING_SANDBOX=docker` **never falls back**: if Docker is down or the image is missing, grading
  raises (the cycle reports that student as failed) instead of quietly running the weaker mode. Any
  other value than `docker` or empty is an error too.
- `VDEL_GRADING_IMAGE` names another image (default `vdel-grader:1`).
- A run killed by the memory limit is recorded like a timeout (status `timeout`: stored once, not
  mastery evidence, no freeze). An infinite loop is cut at 120 seconds and the container is killed.
- Rebuild the image when `docker/grader-requirements.txt` changes. Its versions are the ones on this
  PC on 2026-10-11 (TODO(verify): that each installs on Python 3.11; the first build shows it).
- Remove it: `docker rmi vdel-grader:1`. A leftover container would be named `vdel-grade-...`
  (`docker ps -a --filter name=vdel-grade-`); there should never be one.

**What the container still does NOT protect:**

- **Forgery from inside the test process.** The student's module is imported by the hidden test
  inside the container, so it can patch pytest or overwrite the JUnit report it can reach, and report
  `passed`. Isolation cannot fix that; a second signal can (differential execution, D-036, is not built;
  the Code Agent's verdict and `out_of_scope_lines` are partial). Listed as "later".
- **Reading the hidden test.** The hidden test file is in the container with the code it grades.
- **Hash-order noise.** pytest prints dict differences in an order that changes between runs, so the
  stored failure message is not byte-stable (in either mode); only the first line is. Messages are never
  shown to students (D-077).
- **A kernel escape.** The container shares the Docker VM's kernel; this is the usual container
  boundary, not a virtual machine.
- **Disk and CPU time outside the limits.** The scratch is 64 MB; the wall-clock limit is 120 s.

## 12. The first real LLM call (by hand, one commit, a dry run) (D-101)

Before `--with-llm` is ever used, look at ONE real answer. `scripts/llm_first_call.py` reads one
graded commit, runs only the Feedback Agent, and prints the provider, the model, the number of
provider calls, the tokens, the deterministic text, the paragraph that would be added under it and
whether the validator accepted it. It stores nothing and posts nothing: the session is read-only,
there is no trace, no `feedback_posts` row, no GitHub call and no usage-ledger file. It costs at most
3 provider calls (`--call-cap`, 2 or 3; 3 is a hard ceiling at the provider handler, not just a
budget).

Find the three values with a read-only query (an attempt that failed at least one check, and one of
its graded commits):

```powershell
cd "<repo-folder>"
docker exec vdel-postgres psql -U vdel -d vdel -c "SELECT a.student_id, a.attempt_id, t.commit_sha, count(*) FILTER (WHERE NOT t.passed) AS failed FROM test_results t JOIN attempts a USING (attempt_id) WHERE t.status = 'ok' GROUP BY 1,2,3 HAVING count(*) FILTER (WHERE NOT t.passed) > 0 ORDER BY max(t.ran_at) DESC LIMIT 5;"
```

Then, with exactly ONE provider key in the environment:

```powershell
$env:LLM_PROVIDER = "<provider>"      # anthropic | openai | google | nvidia: the provider whose key you keep
python -m scripts.llm_first_call --student <STUDENT_ID> --attempt-id <ATTEMPT_ID> --commit-sha <COMMIT_SHA>
```

It refuses (exit code 2, no call) if `LLM_PROVIDER` is not set, if more than one provider key is set or
the one set is not the key of `LLM_PROVIDER`, if `--call-cap` is not 2 or 3, if the commit is a
collection error / timeout / tooling result, the template push (D-098), or has no failing check. The
gateway falls back to any other provider that has a key, which is why only one may exist. **Keys in
`.env`:** `.env` is loaded by the gateway, and `$env:NAME = ""` in PowerShell deletes the variable, so
`.env` would refill it. To blank the other keys, empty them in `.env` (`NAME=`) or comment them out for
this session, and put them back afterwards. A key is never printed, only its variable name.

Read the output as a reviewer: is the paragraph useful, does it stay inside the facts, does the
validator's verdict match your own? A rejection is a finding, not an error (exit code 0).

## 13. The real benchmark run (by hand, billed, capped) (D-102)

`benchmark/run_real_benchmark.py` grades the 5 PySpark files 3 times each with the Code Agent and
compares every verdict with `benchmark/ground_truth.json`. It writes `benchmark/results/<timestamp>/`
and regenerates `benchmark/RECOMMENDATION.md` from the numbers. It opens no database and writes
nothing to GitHub.

The maximum number of provider calls is computed and printed every time, never guessed: submissions
x runs x 2 attempts (the first call and one corrective retry) x the models of the provider's fallback
chain. With 5 files and 3 runs that is 60 for anthropic, openai and google (30 per model) and 30 for
nvidia; with `--runs 1`, 20 and 10. The usual cost is 15 calls (5 files x 3 runs). The run is refused
if the maximum is above `--max-calls`, and the message says by how much.

The same rules as section 12: exactly one provider key, `LLM_PROVIDER` set, no key printed. See there for
emptying the other keys in `.env`.

```powershell
cd "<repo-folder>"
$env:LLM_PROVIDER = "<provider>"

# 1. Read the plan and the maximum (calls nothing, writes nothing):
python -m benchmark.run_real_benchmark --max-calls <MAX_CALLS>

# 2. The real run (billed). --max-calls must be at least the printed maximum:
python -m benchmark.run_real_benchmark --max-calls <MAX_CALLS> --confirm-billed-run
```

Options: `--runs N` (default 3), `--only clean.py`, `--reference none` (do not give the judge
`clean.py` as the reference solution; by default it does, as `run_benchmark.py` always did, so
`clean.py` is judged with itself), `--allow-partial` (accept a cap below the printed maximum: the run
stops cleanly at the cap, writes what it has and exits with code 3), and
`--price-in-per-mtok` / `--price-out-per-mtok` (USD per million tokens, from the provider's price page;
without them the cost line says "not computed"). Exit codes: 0 done, 2 refused, 3 stopped at the cap.

Read `benchmark/RECOMMENDATION.md` after it, section 7 first: the labels were pre-written by an LLM and
reviewed by a human on 10 rows only, the files' docstrings give away the bug, and the task given to the judge is a
hand-kept paraphrase of `benchmark/submissions/TASK.md`. The previous RECOMMENDATION.md (the skeleton) is in git history.



## 14. The agents in the hourly task: none, Feedback only, or both (D-099, D-104)

The task has three modes. Each is a switch of `register_task.ps1`; none is on by default.

| Mode | Register with | The task runs | Spends |
|---|---|---|---|
| none (the original) | no agent switch | `python -m scripts.run_hourly` | nothing |
| Feedback only | `-WithLlm` | `... run_hourly --with-llm`, with `LLM_PROVIDER=openai` set for the task only | up to the caps (10 calls per run, 20 per day) |
| both agents | `-WithLlm -WithCodeAgent` | `... run_hourly --with-llm --with-code-agent` | the same caps, shared |

`-WithCodeAgent` is refused without `-WithLlm`. `run_hourly --with-llm` refuses to start (exit code 4, one
clear log line, nothing collected or graded that hour) when `LLM_PROVIDER` is not set: the task sets it
itself, so this only bites a hand-made task. The key stays in `.env` (`OPENAI_API_KEY`); if `.env` holds
other provider keys the log warns by name, because the gateway could fall back to them: empty them.

What each agent does, once per newly graded commit: a commit with a FAILING check gets the Feedback Agent
(its paragraph is added under the comment only if the task is allowed to post, `-AllowGitHubWrite`); a
commit whose checks ALL passed gets the Code Agent, if its gap lines can be found and are short enough.
The Code Agent's verdict is stored and **never posted**; read it with `scripts\code_agent_report.py`, which
is labelled "unmeasured judge, internal use only, never shown to students". Commits graded before you
switch are never revisited.

### See what the task runs now

```powershell
cd "<repo-folder>"
$a = (Get-ScheduledTask -TaskName "VDEL hourly").Actions[0].Arguments
[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String(($a -split ' ')[-1]))
```

### Switch (re-registering REPLACES the whole command)

Repeat `-AllowGitHubWrite` and `-UseDockerGrading` if the task has them now, or they are switched off. Read the
preview first: `-WhatIf` registers nothing and prints the exact command.

```powershell
# preview, then do it
.\scripts\windows\register_task.ps1 -Force -WhatIf -WithLlm -WithCodeAgent
.\scripts\windows\register_task.ps1 -Force -WithLlm                       # Feedback only
.\scripts\windows\register_task.ps1 -Force -WithLlm -WithCodeAgent        # both agents

# back to no LLM at all (add -AllowGitHubWrite / -UseDockerGrading if they were on)
.\scripts\windows\register_task.ps1 -Force
```

### Try it by hand before switching the task

```powershell
$env:LLM_PROVIDER = "openai"
Remove-Item Env:VDEL_ALLOW_GITHUB_WRITE -ErrorAction SilentlyContinue   # a cycle never posts anyway
# 1. what would be touched (reads only: no network, no grading, no LLM call, no write)
python -m scripts.run_cycle --student anas --plan --with-llm --with-code-agent
# 2. one real cycle: collects and grades from GitHub (reads), writes the database, makes billed calls
python -m scripts.run_cycle --student anas --with-llm --with-code-agent --llm-run-cap 10 --llm-daily-cap 20
# 3. what the Code Agent said (read-only)
python -m scripts.code_agent_report --student anas
```

The plan lists only commits already collected and not yet graded; a commit still on GitHub is found by the
cycle itself. In the cycle's log look for `llm: ON, run cap ...; Code Agent ON`, then per commit one of
`code_agent stored trace N`, `code_agent already judged this commit`, `code_agent skipped, <reason>`,
`feedback_agent=ok ...`, and at the end `llm: N real provider call(s) this run`. Today's usage is in
`.vdel\llm_usage.json` (counts only). A skipped line is normal: a failing commit, a commit that is the
template push, gap lines not found, judged text above `--code-agent-max-chars` (default 4000), a cap reached.

The report marks a row `tests pass, approach <= 2`: every check passed and the judge scored the approach 2
or lower. Those rows are the ones to read first. The Code Agent has not been measured against labels on
`weather_etl` (there are none); do not act on a score.

## 15. Is the machine ready? The doctor, and recording a delivery in the roster (D-105)

```powershell
# read-only: Python, Docker and the grader image, the database and its migrations, the GitHub token
# (name) and its scopes, the roster, open attempts the roster cannot reach, which LLM keys exist
# (names), the scheduled task and the flags it runs with
python -m scripts.doctor
python -m scripts.doctor --no-network      # skip the single GET /user that reads the token's scopes
```

`FAIL` means something stops the system (exit code 1); `WARN` is something to read. The doctor never
prints a token or a key, only their names and the scope names GitHub returns.

After `deliver_next_attempt --apply` the roster must point at the new repo, or the next cycle never sees
it (the cycle now logs `WARN  open attempt N of A ...` when that happens). The delivery prints the exact
command; run it WITHOUT `--yes` first to see the diff, then with it:

```powershell
python -m scripts.roster_apply --student X --assignment weather_etl_extract --owner OWNER --repo NEW_REPO
python -m scripts.roster_apply --student X --assignment weather_etl_extract --owner OWNER --repo NEW_REPO --yes
```

It keeps `config\roster.yaml.<UTC time>.bak`, changes only that row's `owner` and `repo` (comments,
line endings and `released_at` stay), and refuses an ambiguous target or a credential. A row that does not
exist yet also needs `--released-at <the real date the work began>`.

Before a new or changed master project is issued to anyone, run the read-only validator (D-107):

```powershell
python -m scripts.validate_master weather_etl            # markers, ids, tests, public descriptions, judging, resources
python -m scripts.validate_master --require-reviewed     # drafts count as errors: the check before a pilot
```

## 16. The v2 agents: `--agents-v2` (D-108)

Off by default, refused without `--with-llm`, and **not** a switch of `register_task.ps1`: use it by hand
first. It changes the Feedback Agent only (stage 5 adds the Code Agent). Without the flag nothing changes,
byte for byte.

What a failing commit gets with it:

- the student's own gap lines (plus three lines of context) go to the model, with the reviewed public
  description of each failing check (`config/checks.yaml`, drafts never), how many pushes each check has
  failed on, and a hint level chosen by code: 1 push -> the expected behaviour in words, 2 -> one quoted line of
  their code, 3 or more -> a strategy in words. Never code.
- a commit whose only failures are `NotImplementedError` stubs gets one fixed sentence ("Where to start") and
  **no provider call**; so does a commit from which no lines of the student's can be cut out.
- a reply is rejected (then one corrective call, then the deterministic text alone) unless it quotes the
  student's code verbatim, writes no code, does not copy the reference solution and does not repeat the counts
  or test names.

```powershell
$env:LLM_PROVIDER = "openai"
python -m scripts.run_cycle --student anas --plan --with-llm --agents-v2        # reads only
python -m scripts.run_cycle --student anas --with-llm --agents-v2 --llm-run-cap 10 --llm-daily-cap 20
```

In the cycle's log look for `agents v2 ON` and, per commit, `feedback_agent_v2=<source>, hint level N, K
provider call(s)` with `<source>` one of `llm`, `deterministic_stub`, `deterministic_no_excerpt`,
`deterministic_v0_fallback` (the model was tried and rejected; the reasons follow). The hourly task passes the
flag too when run by hand (`python -m scripts.run_hourly --with-llm --agents-v2`) and then posts the v2
paragraph under the deterministic text, or the v1 paragraph for a commit graded before the switch. Until the
author marks the check descriptions `reviewed`, level 1 has no "Expected behaviour" sentence.

### The Code Agent with `--agents-v2` (D-109)

With the flag, the Code Agent changes in three ways: it judges **once per attempt**, on the commit that
freezes it (all hidden checks passed), and never again for that attempt; its prompt (v4) asks **no correctness
opinion** and carries **no reference solution** (the benchmark keeps both); and the stored verdict says
`code_agent_v4` / `production`. Read it with the report, which now ends with an instructor section:

```powershell
python -m scripts.code_agent_report --student anas      # table, then "CORRECT BUT APPROACH <= 2"
```

The "Going further" note for students exists in `agents/going_further.py` but is **off and posted by
nothing**. `config/judging.yaml` has `post_review: {enabled: false, min_benchmark_agreement: 0.80}`; even if you
set `enabled: true` it refuses until a real benchmark result (section 13) reaches 80% exact agreement overall
and on approach and readability. The result recorded on 2026-10-12 has 60% on approach, so it stays refused.
Turning it on needs a person to write the posting step too: nothing calls the module today.

## 17. Pilot preparation (D-110)

`docs/PILOT.md` has the checklist, the database role (not applied), the student notice and opting a student out
(`ai_notes: false` in the roster), and the A/B experiment:

```powershell
python -m scripts.run_hourly --with-llm --ab-llm     # half of the failing commits get the deterministic text alone
python -m scripts.ab_report                          # read-only: commits-to-pass per arm, descriptive only
```

## 18. Looking at the data (read-only)

Three `SELECT`s that show what the collector and the feature computation stored. They change nothing; run them
whenever you want to see a student's raw activity or the computed variables.

```powershell
# the newest commits the collector has seen
docker exec -it vdel-postgres psql -U vdel -d vdel -c "SELECT student_id, assignment_id, committed_at, additions, deletions, files_changed FROM raw_commits ORDER BY committed_at DESC LIMIT 20;"

# the newest CI runs and how each failure was classified
docker exec -it vdel-postgres psql -U vdel -d vdel -c "SELECT student_id, assignment_id, conclusion, error_class, concept_id, started_at FROM raw_workflow_runs ORDER BY started_at DESC LIMIT 20;"

# the latest computed variables (expanded display, because they are JSONB columns)
docker exec -it vdel-postgres psql -U vdel -d vdel -c "\x" -c "SELECT student_id, computed_at, window_days, mastery, engineering_discipline, effort_regulation, pace, error_response, error_frequency FROM learner_features ORDER BY computed_at DESC LIMIT 1;"
```

To rebuild the features from the raw tables run `python -m features.compute_features` (idempotent; it writes one new
row only for a student with new activity). Never empty `raw_commits` or `raw_workflow_runs` to "start again" on a
database that holds real students: the collector's cursor and the attempt history depend on them.

## 19. Start from an empty database

For a new installation or a clean practice database. Do it against a database you can lose; on one that holds real
students take a backup first (section 9). `docs/INSTALL.md` has the machine side (the token, the key, the container).

1. **The database.** `docker compose up -d`, wait for `(healthy)`, and put its connection string in `.env` as `PG_DSN`
   (`docs/INSTALL.md` sections 3 and 4).
2. **The schema.** `python -m scripts.init_db` applies `sql/01` to `sql/10` in order and is idempotent; then
   `python -m scripts.smoke_test` checks that the tables exist and that `traces` rejects `UPDATE` and `DELETE`.
3. **The roster.** `cp config/roster.example.yaml config/roster.yaml` and edit it (the file is git-ignored):
   - in `students:` one block per student: `student_id`, a **real** `github_username`, `cohort`; an `ai_notes: false`
     line opts a student out of AI notes (`docs/PILOT.md`);
   - replace the example `assignments:` rows by `assignments: []`. A fresh installation has none: `publish_repo` writes the
     rows after it has pushed a repository (step 5 below). Keep the key, because `seed_data` reads it when it prints its summary
     (`scripts/seed_data.py:405-407`); any row left as `CHANGE_ME` is refused, and so is a note in `released_at`
     (`scripts/seed_data.py:222-253, 273-293`).
4. **Seed.** `python -m scripts.seed_data`. It prints one `seeded curriculum: ...` line per project (`weather_etl` and
   `sales_analyzer`, `scripts/seed_data.py:304-323`) and then `seeded N student(s), 0 assignment(s), ...`. It writes the
   curriculum first, in its own transaction, so a roster error stops it after the curriculum is already in place.
5. **Check.** `python -m scripts.doctor` (a missing roster is a `FAIL`),
   then `python -m scripts.baseline --full > baseline_empty.txt` as the reference for later changes.
6. **Add a student later.** Add a block under `students:` and run `python -m scripts.seed_data` again (it upserts), or use
   `python -m scripts.roster_apply --student X --assignment A --owner O --repo R --github-username LOGIN --cohort C`
   for a student not yet in the roster (`--yes` to write; a timestamped backup is made first). Then give the student
   a repository (next section).

## 20. Deliver and change what a student works on

**The first attempt: `publish_repo`.** It renders the project for one student and puts it on GitHub, for all the stages
of the project at once:

```powershell
python -m scripts.publish_repo --student X --attempt 1 --project weather_etl --dry-run   # renders, contacts nothing
python -m scripts.publish_repo --student X --attempt 1 --project weather_etl             # asks for confirmation
```

The real run needs a token with the `workflow` scope (`docs/INSTALL.md` section 5). It creates a private repository
owned by the roster's owner or, failing that, the token's account, pushes it, and only then writes the roster rows. It
**invites nobody** (`scripts/publish_repo.py` has no invitation step; only `deliver_next_attempt` invites,
`scripts/deliver_next_attempt.py:314`): add the student as a collaborator with write access in the repository's settings and
have them accept the invitation.

**Another attempt at a stage: `deliver_next_attempt`.** Which stage gets another attempt is your decision; the command does
not choose, it takes `--assignment`. The current attempt must be frozen (its hidden tests reached 100 % on a pushed
commit); `--force` with `--i-understand` overrides that and leaves the old attempt open, which is why you should not use it
(D-072).

```powershell
python -m scripts.deliver_next_attempt --student X --assignment weather_etl_extract            # the plan; contacts nothing
$env:VDEL_ALLOW_GITHUB_WRITE = "1"
python -m scripts.deliver_next_attempt --student X --assignment weather_etl_extract --apply    # creates, pushes, invites
Remove-Item Env:VDEL_ALLOW_GITHUB_WRITE
```

It creates a new private repository for that one stage, invites the student, comments the link on the old repository, and
prints the roster rows to record. A delivery that stopped half way is finished with the same command plus `--resume`.

**Record it in the roster: `roster_apply`.** `deliver_next_attempt` does not edit `config/roster.yaml`. Run the command
that `deliver_next_attempt` printed, first without `--yes` (it shows the diff and writes nothing), then with it:

```powershell
python -m scripts.roster_apply --student X --assignment weather_etl_extract --owner O --repo R
python -m scripts.roster_apply --student X --assignment weather_etl_extract --owner O --repo R --yes
python -m scripts.run_cycle --dry-run --student X      # the cycle must now see the new repository
```

Until the roster has the row, the cycle logs `open attempt ... has no roster repo` and collects nothing for it.

**Changing what a student works on.** Moving a student on means choosing the next attempt or stage and delivering it as
above. Changing the exercise itself (a stage file, a hidden test, a check description) is a different operation with
consequences for students already working on it: `docs/AUTHORING.md` section 10.
