-- Reference tables: students and assignments

CREATE TABLE IF NOT EXISTS students (
  student_id       TEXT PRIMARY KEY,
  github_username  TEXT UNIQUE NOT NULL,
  cohort           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assignments (
  assignment_id  TEXT PRIMARY KEY,
  repo_prefix    TEXT NOT NULL,
  released_at    TIMESTAMPTZ NOT NULL,
  due_at         TIMESTAMPTZ,
  concepts       TEXT[] NOT NULL
);
