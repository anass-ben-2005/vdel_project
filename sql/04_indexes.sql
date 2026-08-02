-- Indexes for performance-critical queries

CREATE INDEX IF NOT EXISTS idx_raw_commits_student_ts
  ON raw_commits(student_id, committed_at DESC);

CREATE INDEX IF NOT EXISTS idx_raw_workflow_runs_student_ts
  ON raw_workflow_runs(student_id, completed_at DESC);

CREATE INDEX IF NOT EXISTS idx_traces_student_ts
  ON traces(student_id, ts DESC);

CREATE INDEX IF NOT EXISTS idx_traces_concept_ids
  ON traces USING GIN(concept_ids);

CREATE INDEX IF NOT EXISTS idx_learner_features_student
  ON learner_features(student_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_raw_commits_assignment
  ON raw_commits(assignment_id);

CREATE INDEX IF NOT EXISTS idx_raw_workflow_runs_assignment
  ON raw_workflow_runs(assignment_id);
