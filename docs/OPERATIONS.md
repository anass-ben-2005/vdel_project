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
cd "C:\Users\ASUS\Desktop\EMINES\internship\stage_a_l'etranger\projet\vdel"

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

**Cause found on 2026-10-12.** The project folder `stage_a_l'etranger` contains an apostrophe. The first
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

# c) the command PRINTS the roster rows; edit config\roster.yaml by hand (it never does),
#    then check the cycle sees the new repo:
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
cd "C:\Users\ASUS\Desktop\EMINES\internship\stage_a_l'etranger\projet\vdel"

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

