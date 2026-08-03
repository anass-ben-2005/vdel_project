-- Indexes.
--
-- Ordering note: this file indexes `traces`, which is created in 05_memory_tables.sql.
-- CLAUDE.md section 5 fixes both filenames and BUILD_PLAN 0.3 puts the traces indexes
-- here, so filename order and dependency order genuinely disagree. scripts/init_db.py
-- therefore runs 01, 02, 03, 05, 04 -- stated there explicitly rather than left as a
-- silent reordering someone has to rediscover.

-- Hot path: "what has this student done lately".
CREATE INDEX IF NOT EXISTS idx_traces_student_ts
  ON traces (student_id, ts DESC);

-- Hot path: "which traces touch this concept" -- array containment needs GIN.
CREATE INDEX IF NOT EXISTS idx_traces_concept_ids
  ON traces USING GIN (concept_ids);

-- Raw tables: the collector's incremental `since=` watermark and the feature
-- window both scan (student_id, timestamp).
CREATE INDEX IF NOT EXISTS idx_raw_commits_student_ts
  ON raw_commits (student_id, committed_at DESC);

CREATE INDEX IF NOT EXISTS idx_raw_workflow_runs_student_ts
  ON raw_workflow_runs (student_id, completed_at DESC);

-- Per-assignment rollups (pace, mastery-by-assignment).
CREATE INDEX IF NOT EXISTS idx_raw_commits_assignment
  ON raw_commits (assignment_id, committed_at);

CREATE INDEX IF NOT EXISTS idx_raw_workflow_runs_assignment
  ON raw_workflow_runs (assignment_id, completed_at);

-- "Latest features for this student" -- used by the dirty-student filter.
CREATE INDEX IF NOT EXISTS idx_learner_features_student_ts
  ON learner_features (student_id, computed_at DESC);
