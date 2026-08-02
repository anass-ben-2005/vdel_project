-- Raw telemetry tables from GitHub

CREATE TABLE IF NOT EXISTS raw_commits (
  sha            TEXT PRIMARY KEY,
  student_id     TEXT NOT NULL REFERENCES students(student_id),
  assignment_id  TEXT NOT NULL REFERENCES assignments(assignment_id),
  committed_at   TIMESTAMPTZ NOT NULL,
  additions      INT,
  deletions      INT,
  files_changed  INT,
  message        TEXT
);

CREATE TABLE IF NOT EXISTS raw_workflow_runs (
  run_id         BIGINT PRIMARY KEY,
  student_id     TEXT NOT NULL REFERENCES students(student_id),
  assignment_id  TEXT NOT NULL REFERENCES assignments(assignment_id),
  status         TEXT,
  conclusion     TEXT,
  started_at     TIMESTAMPTZ,
  completed_at   TIMESTAMPTZ,
  duration_s     INT,
  error_class    TEXT,
  concept_id     TEXT
);
