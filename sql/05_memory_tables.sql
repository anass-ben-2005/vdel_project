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
  trace_count INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS learner_profile (
  student_id   TEXT PRIMARY KEY REFERENCES students(student_id),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  mastery      JSONB NOT NULL DEFAULT '{}',
  weaknesses   JSONB NOT NULL DEFAULT '[]',
  reflections  JSONB NOT NULL DEFAULT '[]',
  features_ref TIMESTAMPTZ   -- pointer to the learner_features row it was built from
);
