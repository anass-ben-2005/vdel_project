-- sql/pilot/vdel_cycle_role.sql -- a NON-SUPERUSER role for the hourly task (D-110). NOT APPLIED.
--
-- Nothing in this repository applies this file: `scripts/init_db.py` lists its files by name and this
-- one is in a subdirectory on purpose, `tests/` never loads it (a role is a property of the whole
-- Postgres server, not of one database, so applying it from a test would change the real server), and
-- the `doctor` reads only `sql/*.sql`. It is applied by a person, as the database owner, by hand:
-- see docs/PILOT.md for the commands, the password step and how to point `PG_DSN` at the new role.
--
-- WHY. Today the task connects as `vdel`, the role that OWNS the database: it could drop a table, rewrite
-- a rule or read every row of every student. For one trusted student on one's own PC that is a choice;
-- for a pilot of 3 to 5 it should not be. The role below can do exactly what the cycle, the hourly feedback
-- phase, `post_feedback`, `code_agent_report`, `baseline` and `doctor` do, and nothing else.
--
-- WHAT IT CAN DO (derived from the INSERT / UPDATE statements of the modules those commands run;
-- tests/test_pilot_role.py re-derives the list and fails if the code and this file drift apart):
--   read     every table
--   traces              INSERT only (UPDATE and DELETE are rejected by the database's own rules anyway)
--   raw_commits         INSERT, UPDATE              the collector (INSERT ... ON CONFLICT DO UPDATE)
--   raw_workflow_runs   INSERT, UPDATE              the collector and the error classifier
--   test_results        INSERT, UPDATE              the grader (upserts the local-run rows)
--   attempts            UPDATE                      the freeze and the lint columns
--   learner_features    INSERT, UPDATE              compute_features (upserts at its watermark)
--   learner_profile     INSERT, UPDATE              the memory door
--   feedback_issues, feedback_posts   INSERT        the feedback poster (ON CONFLICT DO NOTHING)
-- An `INSERT ... ON CONFLICT DO UPDATE` needs the UPDATE privilege too, which is why raw_commits and
-- learner_features carry it; leaving it out would stop the first cycle with "permission denied".
-- WHAT IT CANNOT DO: DELETE or TRUNCATE anything, create or alter any object, create a role or a database,
-- read another database, bypass row security, or run `init_db`, `seed_data`, `render`/`publish_repo`,
-- `deliver_next_attempt`, `load_resources` or `prove_event_sourcing` (those write other tables or truncate
-- `learner_profile`: run them as the owner, as today).
--
-- RUN AS THE DATABASE OWNER, connected to the target database, with the database name and a password
-- supplied on the command line so that neither is written in this file:
--     psql -U vdel -d vdel -v dbname=vdel -v pw="'<a long random password>'" -f sql/pilot/vdel_cycle_role.sql
-- Re-running is safe (the role is created once; the grants are repeated).

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vdel_cycle') THEN
    CREATE ROLE vdel_cycle LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
      CONNECTION LIMIT 5;
  END IF;
END
$$;

-- The password comes from the psql variable `pw` (already quoted by the caller), never from this file.
ALTER ROLE vdel_cycle PASSWORD :pw;

GRANT CONNECT ON DATABASE :"dbname" TO vdel_cycle;
GRANT USAGE ON SCHEMA public TO vdel_cycle;
REVOKE CREATE ON SCHEMA public FROM vdel_cycle;

-- Read everything.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO vdel_cycle;

-- The log: append only.
GRANT INSERT ON traces TO vdel_cycle;
GRANT USAGE, SELECT ON SEQUENCE traces_trace_id_seq TO vdel_cycle;

-- The raw and graded tables.
GRANT INSERT, UPDATE ON raw_commits TO vdel_cycle;
GRANT INSERT, UPDATE ON raw_workflow_runs TO vdel_cycle;
GRANT INSERT, UPDATE ON test_results TO vdel_cycle;
GRANT UPDATE ON attempts TO vdel_cycle;

-- The derived tables.
GRANT INSERT, UPDATE ON learner_features TO vdel_cycle;
GRANT INSERT, UPDATE ON learner_profile TO vdel_cycle;

-- Feedback bookkeeping.
GRANT INSERT ON feedback_issues, feedback_posts TO vdel_cycle;

-- To undo it all (as the owner), run:
--   REASSIGN OWNED BY vdel_cycle TO vdel; DROP OWNED BY vdel_cycle; DROP ROLE vdel_cycle;
