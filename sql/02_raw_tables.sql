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

-- D-063. The commit a run ran against (the Actions API's `head_sha`). CLAUDE.md section 6
-- does not list this column: an ADDITIVE, NULLABLE exception, no existing row changed.
-- It is what lets features/compute_features.py recognise a run that was triggered by a
-- template-sync commit (a re-evaluation of already-pushed code, not a student action) by
-- joining to raw_commits.message. NULL = not known yet (rows collected before D-063 until
-- scripts/backfill_head_sha.py fills them); a NULL run is treated as a student run.
ALTER TABLE raw_workflow_runs ADD COLUMN IF NOT EXISTS head_sha TEXT;
