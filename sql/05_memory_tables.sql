-- Event-sourced memory: append-only traces and mutable profile

CREATE TABLE IF NOT EXISTS traces (
  trace_id        BIGSERIAL PRIMARY KEY,
  parent_trace_id BIGINT,
  session_id      BIGINT,
  student_id      TEXT NOT NULL REFERENCES students(student_id),
  ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
  actor           TEXT NOT NULL,
  kind            TEXT NOT NULL,
  assignment_id   TEXT,
  concept_ids     TEXT[],
  payload         JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  session_id      BIGSERIAL PRIMARY KEY,
  student_id      TEXT NOT NULL REFERENCES students(student_id),
  started_at      TIMESTAMPTZ NOT NULL,
  ended_at        TIMESTAMPTZ,
  inactivity_gap_minutes INT DEFAULT 30,
  trace_count     INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS learner_profile (
  student_id   TEXT PRIMARY KEY REFERENCES students(student_id),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  mastery      JSONB NOT NULL DEFAULT '{}',
  weaknesses   JSONB NOT NULL DEFAULT '[]',
  reflections  JSONB NOT NULL DEFAULT '[]',
  features_ref TIMESTAMPTZ
);
