# PILOT.md: before 3 to 5 students use the system

What is prepared for a pilot, what is **not applied**, and the order to do things in. None of it is on by
default. Decisions behind it: D-110. What is still wrong is in [KNOWN_ISSUES.md](KNOWN_ISSUES.md).

Contents: 1 Checklist · 2 A database role that is not the owner · 3 What students are told, and opting out ·
4 The A/B experiment · 5 What this does not settle

## 1. Checklist

Do these in order; each line says where.

1. **Container grading is mandatory** for a pilot (D-086): build the image and register the task with
   `-UseDockerGrading` (`docs/OPERATIONS.md` section 11). `python -m scripts.doctor` shows both.
2. **Roster**: one student block per student with a real GitHub login; add `ai_notes: false` for anyone who
   opts out (section 3). `python -m scripts.roster_apply` records each delivered repo.
3. **Review the drafts** the pilot would otherwise ignore: the fifteen check descriptions in
   `config/checks.yaml` and the four statements in `config/judging.yaml`. `python -m scripts.validate_master
   --require-reviewed weather_etl` must report no error.
4. **Read the student notice** (section 3) and confirm its wording with the course author and whoever is
   responsible for data protection. It is written to match what the prompts carry; a test checks the facts.
5. **Create the database role** (section 2) and point the task at it.
6. **Decide on the agents**: all of them are off by default. If you switch the Feedback Agent on, read
   `docs/OPERATIONS.md` sections 12, 14 and 16 first, and consider the A/B experiment (section 4).
7. Back up (`docs/OPERATIONS.md` section 9) and run `python -m scripts.baseline --full` before the first
   student is delivered.

## 2. A database role that is not the owner

`sql/pilot/vdel_cycle_role.sql` creates `vdel_cycle`: not a superuser, no right to create or alter anything,
**no DELETE or TRUNCATE anywhere**, `INSERT` only on `traces`, and `INSERT`/`UPDATE` only on the handful of
tables the cycle writes. A test re-derives that list from the code on every run and fails if the file and the
code drift apart, so the role cannot silently lose a permission the cycle needs or keep one it does not.

**The file is not applied.** Nothing in this repository runs it: it lives outside the files `init_db` applies,
and a test only reads it (a role belongs to the whole Postgres server, so applying it from a test would change
the real one). You run it, as the database owner, connected to the target database:

```powershell
# 1. a long random password, kept out of this repository and out of your shell history
$pw = [Convert]::ToBase64String((1..24 | ForEach-Object { Get-Random -Maximum 256 }))
# 2. apply it as the owner (read the file first: Get-Content sql\pilot\vdel_cycle_role.sql)
docker cp sql\pilot\vdel_cycle_role.sql vdel-postgres:/tmp/vdel_cycle_role.sql
docker exec vdel-postgres psql -U vdel -d vdel -v dbname=vdel -v "pw='$pw'" -f /tmp/vdel_cycle_role.sql
docker exec vdel-postgres rm /tmp/vdel_cycle_role.sql
# 3. in .env, point the TASK at the new role (a separate .env or the task's own environment):
#    PG_DSN=postgresql://vdel_cycle:<the password>@localhost:5433/vdel
```

Quoting a value that contains single quotes through PowerShell to a native program is fiddly (not verified);
if step 2 complains about the password, open a shell in the container (`docker exec -it vdel-postgres bash`)
and run the same `psql` command there, with the password in single quotes inside double quotes.

Keep the owner's `PG_DSN` for the commands the role cannot run: `init_db`, `seed_data`, `publish_repo`,
`deliver_next_attempt`, `load_resources`, `prove_event_sourcing` and the test suite. To undo it:
`REASSIGN OWNED BY vdel_cycle TO vdel; DROP OWNED BY vdel_cycle; DROP ROLE vdel_cycle;`.

**Not verified:** the SQL has never been executed (no change to the real server was allowed while it was
written). Run it once on a copy of the database first, and run `python -m scripts.doctor` and
`python -m scripts.run_cycle --dry-run` with the new `PG_DSN`. If a statement fails with "permission denied",
the message names the table: that is a drift to fix in the file and in its test, not to bypass.

## 3. What students are told, and opting out

Every `ASSIGNMENT.md` rendered from now on ends with a section, "About the automatic feedback and the AI
notes" (`DATA_NOTICE` in `scripts/render_student_repo.py`). In short: the checks are not AI; if the instructor
switches AI notes on, **text is sent to an external AI provider**, and it lists exactly what: for a failing
commit the exercise and attempt, the names and error types of the failing checks, a short description of what
each expects, how many pushes each has failed on, a number per related topic, and the lines the student wrote
inside the marked gaps with three lines of context; once, for a passing attempt, the same lines for a review
only the instructor reads. It says what is **not** sent (name, e-mail, GitHub login, the hidden tests' code,
anything outside the gaps and their context) and how to opt out. Repositories already delivered keep their
old `ASSIGNMENT.md`: re-sending the notice to them is a manual step (`scripts/sync_template.py` re-applies
template files; `ASSIGNMENT.md` is not one of them, so tell those students by hand).

**Opt-out** is one line in the roster, under the student:

```yaml
students:
  - student_id: sara
    github_username: sara-gh
    cohort: vdel-2026
    ai_notes: false        # no AI note, no provider call, for this student
```

`ai_notes: false` stops both agents for that student (the cycle logs `student opted out of AI notes, no
agent`) and stops the hourly task from posting any paragraph already stored for them. The switch **fails
closed**: any value other than `true` (`false`, `no`, `off`, `0`, an empty value) is an opt-out; only a missing
key or `true` leaves the instructor's settings in force. Their hidden checks, grading and the deterministic
note listing the failed checks are unchanged.

## 4. The A/B experiment

To find out whether the AI paragraph helps before paying for it everywhere:

```powershell
python -m scripts.run_hourly --with-llm --ab-llm            # or run_cycle; refused without --with-llm
python -m scripts.ab_report                                 # read-only: commits-to-pass per arm
```

For each failing commit a fixed hash of (attempt, commit) picks `llm` (the Feedback Agent runs as usual) or
`control` (the deterministic text alone, no provider call). The arm is stored as a `coach`/`intervention`
trace (`ab_assignment`) before anything else happens, so a re-run never moves a commit, and a commit whose AI
answer was rejected still counts as `llm`. The report gives, per arm, how many commits, how many of their
attempts have since passed, how many have not (censored), and the mean and median number of further pushes
needed. It is **descriptive**: one attempt can sit in both arms, the exercise matters as much as the note, and
with a handful of students every difference is noise. Do not decide on it; use it to see whether anything
could be there.

## 5. What this does not settle

The Code Agent and the v2 Feedback Agent have never run against a real model on `weather_etl`; the notice
describes what the code sends, not what the provider does with it (their terms apply); the role has not been
executed; and consent, retention and deletion are not written down anywhere in this repository. None of that
is a reason not to pilot with one trusted student, and all of it is a reason to go slowly with five.
