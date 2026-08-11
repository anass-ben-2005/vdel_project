-- Event-sourced memory. traces is the log; learner_profile is a derived view of it.

CREATE TABLE IF NOT EXISTS traces (
  trace_id        BIGSERIAL PRIMARY KEY,
  parent_trace_id BIGINT REFERENCES traces(trace_id),  -- causal forest
  session_id      BIGINT,
  student_id      TEXT NOT NULL REFERENCES students(student_id),
  ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor           TEXT NOT NULL,   -- code_agent | perf_agent | pedagogy_agent | coach | system
  kind            TEXT NOT NULL,   -- verdict | error_event | intervention | reflection_run
  assignment_id   TEXT REFERENCES assignments(assignment_id),
  concept_ids     TEXT[],          -- denormalised hot query (GIN index in 04)
  payload         JSONB NOT NULL
);

-- Invariant 1 ("traces is append-only") enforced by the database.
-- A comment asks for compliance; a rule makes non-compliance impossible. Auditability
-- is a functional requirement, so the guarantee belongs where it cannot be bypassed --
-- including by a future agent that reaches past memory/memory.py with raw SQL.
CREATE OR REPLACE RULE traces_no_update AS
  ON UPDATE TO traces DO INSTEAD NOTHING;
CREATE OR REPLACE RULE traces_no_delete AS
  ON DELETE TO traces DO INSTEAD NOTHING;

CREATE TABLE IF NOT EXISTS sessions (
  session_id  BIGSERIAL PRIMARY KEY,
  student_id  TEXT NOT NULL REFERENCES students(student_id),
  started_at  TIMESTAMPTZ NOT NULL,
  ended_at    TIMESTAMPTZ,
  trace_count INT NOT NULL DEFAULT 0,
  summary     TEXT          -- NULL until the compression job fills it (M2.3)
);

CREATE TABLE IF NOT EXISTS learner_profile (
  student_id     TEXT PRIMARY KEY REFERENCES students(student_id),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  mastery        JSONB NOT NULL DEFAULT '{}',
  weaknesses     JSONB NOT NULL DEFAULT '[]',
  reflections    JSONB NOT NULL DEFAULT '[]',
  session_digest JSONB NOT NULL DEFAULT '[]',  -- pointers to recent session summaries
  features_ref   TIMESTAMPTZ   -- pointer to the learner_features row it was built from
);

-- The two columns above were missing from this file while Modules_3_9 B.4 declares them,
-- B.5 reads session_digest, B.6 writes sessions.summary, and the complete design document
-- lists both. Three sources against two makes it a transcription gap here rather than a
-- design decision (DECISIONS.md D-008). CREATE TABLE IF NOT EXISTS does nothing to an
-- existing table, so the columns are also added explicitly for databases built before this
-- commit. Both statements are idempotent; running init_db twice changes nothing.
ALTER TABLE sessions        ADD COLUMN IF NOT EXISTS summary        TEXT;
ALTER TABLE learner_profile ADD COLUMN IF NOT EXISTS session_digest JSONB NOT NULL DEFAULT '[]';
