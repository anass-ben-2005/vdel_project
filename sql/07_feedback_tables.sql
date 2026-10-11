-- 07_feedback_tables.sql -- D-074. ADDITIVE and idempotent. Written, NOT applied to the real
-- database by the overnight batch (apply by hand: `python -m scripts.init_db`, which now lists
-- this file). The test conftest applies it to vdel_test through init_db like every other file.
--
-- One row per feedback comment actually POSTED for a graded commit. It is the idempotency
-- marker for scripts/post_feedback.py: a (attempt, commit, channel) already present is never
-- posted twice. Nothing writes to it in v1 (only --dry-run is implemented); the table exists
-- so the posting step, when it is enabled, has somewhere to record that it happened.
--
-- When the posting loop is written, its INSERT must be `ON CONFLICT DO NOTHING` (invariant 9):
-- posting twice must be a no-op.
--
-- It is not a source of truth for grades: it records that a message was sent, not what the
-- student's work was. body_sha256 lets an audit confirm which text went out without storing
-- a second copy of it.
CREATE TABLE IF NOT EXISTS feedback_posts (
  attempt_id   BIGINT      NOT NULL REFERENCES attempts(attempt_id),
  commit_sha   TEXT        NOT NULL REFERENCES raw_commits(sha),
  channel      TEXT        NOT NULL DEFAULT 'github_commit_comment',
  body_sha256  TEXT        NOT NULL,
  external_ref TEXT,                          -- e.g. the GitHub comment id
  posted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (attempt_id, commit_sha, channel)
);
