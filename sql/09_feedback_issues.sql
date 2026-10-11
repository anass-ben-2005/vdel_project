-- 09_feedback_issues.sql -- D-089. ADDITIVE and idempotent. The test conftest applies it to
-- vdel_test through init_db like every other file. NOT applied to the real database by the
-- batch: apply by hand with `python -m scripts.init_db`.
--
-- One row per (attempt): the GitHub issue that holds the feedback comments of that attempt
-- ("VDEL feedback - <assignment> - attempt <n>"). Together with `feedback_posts` (one row per
-- comment, channel 'github_issue_comment') it makes the issue mode idempotent: the issue is
-- created once, and each graded commit is commented once. Not a source of truth for grades.
CREATE TABLE IF NOT EXISTS feedback_issues (
  attempt_id   BIGINT      PRIMARY KEY REFERENCES attempts(attempt_id),
  owner        TEXT        NOT NULL,
  repo         TEXT        NOT NULL,
  issue_number INT         NOT NULL,
  issue_url    TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
