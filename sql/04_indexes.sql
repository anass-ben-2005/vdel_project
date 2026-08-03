-- Transcribed from VDEL_Modules_1_2_Build.md Part C (the optimization pass, Flaw 4).

-- Match the access pattern of feature queries: filter by (student, assignment), sort by time
CREATE INDEX IF NOT EXISTS idx_commits_student_assignment
  ON raw_commits (student_id, assignment_id, committed_at);

CREATE INDEX IF NOT EXISTS idx_runs_student_assignment
  ON raw_workflow_runs (student_id, assignment_id, started_at);

-- Partial index: only failed runs carry an error concept -> smaller, faster
CREATE INDEX IF NOT EXISTS idx_runs_concept
  ON raw_workflow_runs (concept_id) WHERE conclusion = 'failure';

-- --------------------------------------------------------------------------------
-- Additive, not from Module 1-2: the module document's sql/ stops at 04 because
-- `traces` belongs to Module 3. BUILD_PLAN 0.3 requires the traces indexes to live in
-- this file, so they are appended here rather than moved into 05. Ordering consequence
-- is handled in scripts/init_db.py, which runs 05 before 04.
CREATE INDEX IF NOT EXISTS idx_traces_student_ts
  ON traces (student_id, ts DESC);

CREATE INDEX IF NOT EXISTS idx_traces_concept_ids
  ON traces USING GIN (concept_ids);
