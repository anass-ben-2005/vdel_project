-- Assessment redesign: completion-problem tracking (the 2026-08-19 supervisor-mandated
-- redesign). Transcribed from VDEL_REDESIGN.md §11. Every statement is
-- CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS -- idempotent per CLAUDE.md
-- invariant 9, safe to re-run.
--
-- CITATION CORRECTION: the item-supersession comment below is sometimes cited as "D-032"
-- (e.g. in earlier drafts of this task). The REAL docs/DECISIONS.md D-032 is a different,
-- unrelated decision ("google reinstated as a live provider") -- a numbering collision from
-- earlier this session, already fixed everywhere else in CLAUDE.md/DECISIONS.md. The correct
-- citation is D-035 ("Attempts, variants, gaps, sessions in scope; supersedes CLAUDE.md §2's
-- prohibition"). Used correctly below.
--
-- Every change here is additive or nullable (VDEL_REDESIGN.md §11.1's own "migration is
-- safe" property): new tables can have NOT NULL columns freely (nothing writes to them yet),
-- and the one ALTER TABLE on an EXISTING table (assignments) only adds nullable columns, so
-- no existing row can be broken.
--
-- REVISED: an earlier version of this file also ALTERed the existing `sessions` table
-- (sql/05_memory_tables.sql) to add duration/pace columns, weakening two of them to
-- nullable to avoid breaking existing rows. That was wrong, not just imperfect: `sessions`
-- and VDEL_REDESIGN.md §11's `sessions` are two DIFFERENT CONCEPTS that happen to share a
-- name -- a memory/trace-grouping session (feeds learner_profile.session_digest) versus a
-- git-derived activity session (for duration/pace, V4/V11) -- and forcing them onto one row
-- produced constraint compromises with no upside, the same class of overloading this
-- project already got burned by once (assignment-level concept tags being too coarse once
-- gaps existed). Fixed: `sessions` is untouched below; the activity-session concept gets
-- its own new table, `activity_sessions`, with the full NOT NULL constraints §11 specifies
-- -- a brand-new table has zero existing rows, so there is no retrofit problem at all.

-- ═══ ASSIGNMENT STRUCTURE ═══════════════════════════════════════════

CREATE TABLE IF NOT EXISTS projects (
  project_id     TEXT PRIMARY KEY,
  repo_prefix    TEXT NOT NULL,
  title          TEXT NOT NULL,
  released_at    TIMESTAMPTZ NOT NULL,
  master_version TEXT NOT NULL           -- git sha of the master repo state
);

-- Nullable throughout: old `assignments` rows survive untouched.
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS project_id TEXT REFERENCES projects(project_id);
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS file_path  TEXT;      -- 'src/extract.py'
ALTER TABLE assignments ADD COLUMN IF NOT EXISTS seq        INT;       -- stage order in project
-- assignments.concepts[] is now conceptually DERIVED from gaps (kept for query convenience;
-- a future seed job rebuilds it). Not enforced by this schema -- no trigger, no check.

CREATE TABLE IF NOT EXISTS gaps (
  gap_id         TEXT PRIMARY KEY,        -- 'g_retry_loop'
  assignment_id  TEXT NOT NULL REFERENCES assignments(assignment_id),
  concept_ids    TEXT[] NOT NULL,         -- tags live HERE, not on the assignment
  line_start     INT NOT NULL,
  line_end       INT NOT NULL,
  instruction    TEXT NOT NULL,           -- becomes the student's TODO comment
  difficulty     REAL NOT NULL DEFAULT 0.5,   -- cold-start seed
  master_version TEXT NOT NULL            -- line numbers are only valid for one master
);

CREATE TABLE IF NOT EXISTS variants (
  variant_id     TEXT PRIMARY KEY,        -- sha1(assignment || sorted(gap_ids) || master_version)
  assignment_id  TEXT NOT NULL REFERENCES assignments(assignment_id),
  gap_ids        TEXT[] NOT NULL,
  master_version TEXT NOT NULL,
  difficulty     REAL,                    -- THE KT-IDEM ITEM. Replaces `items`.
  n_cohort_obs   INT NOT NULL DEFAULT 0
);
-- `items` (sql/03_feature_tables.sql) is superseded by `variants` -- D-035, NOT D-032, see
-- this file's header. NOT dropped here (D-044): both CLAUDE.md §6 and VDEL_REDESIGN.md §11
-- literally say `DROP TABLE IF EXISTS items;`, and this file deliberately omits it until
-- the migration is verified -- i.e. until `variants` is populated for a real project AND
-- something has read `variants.difficulty` on the live path. Keeping a superseded empty
-- table is free and reversible; dropping one something still reads is not. The drop is a
-- scheduled task, not a forgotten one.

-- ═══ ACTIVITY & TIMING ══════════════════════════════════════════════
--
-- `sessions` (sql/05_memory_tables.sql) is UNTOUCHED by this file: session_id, student_id,
-- started_at, ended_at, trace_count, summary -- a memory/trace-grouping session, feeding
-- learner_profile.session_digest via traces of kind='session_summary'. Confirmed by grep
-- (this session, before this edit) that nothing in the codebase reads duration/pace/
-- assignment_id/attempt_no from `sessions` -- the only consumers are scripts/smoke_test.py
-- and tests/test_schema.py, and both only check that `summary` exists, not any data in it.
-- So there is nothing to migrate and no call site to update.
--
-- `activity_sessions` is the git-derived concept VDEL_REDESIGN.md §11 calls `sessions`:
-- reconstructed from raw_commits, for duration/pace tracking (V4/V11). A brand-new table,
-- zero existing rows, so every NOT NULL constraint §11 specifies is kept exactly as written
-- -- no retrofit problem, no compromise.
CREATE TABLE IF NOT EXISTS activity_sessions (   -- DERIVED from raw_commits; rebuildable
  session_id     BIGSERIAL PRIMARY KEY,
  student_id     TEXT NOT NULL REFERENCES students(student_id),
  assignment_id  TEXT REFERENCES assignments(assignment_id),
  attempt_no     INT,
  started_at     TIMESTAMPTZ NOT NULL,   -- first event in the session
  ended_at       TIMESTAMPTZ NOT NULL,   -- last event
  duration_min   REAL NOT NULL,
  n_events       INT NOT NULL,
  threshold_min  INT NOT NULL DEFAULT 30,   -- METHOD IS DATA (§7.2)
  method_ver     TEXT NOT NULL DEFAULT 'git_session_v1',
  abandoned      BOOLEAN NOT NULL DEFAULT FALSE
);

-- ═══ ATTEMPTS (DERIVED — NOT a source of truth) ═════════════════════

CREATE TABLE IF NOT EXISTS attempts (
  attempt_id         BIGSERIAL PRIMARY KEY,
  student_id         TEXT NOT NULL REFERENCES students(student_id),
  project_id         TEXT NOT NULL REFERENCES projects(project_id),
  assignment_id      TEXT NOT NULL REFERENCES assignments(assignment_id),
  attempt_no         INT  NOT NULL,
  variant_id         TEXT NOT NULL REFERENCES variants(variant_id),
  gap_seed           BIGINT NOT NULL,     -- regeneration determinism
  commit_sha         TEXT REFERENCES raw_commits(sha),
  submitted_at       TIMESTAMPTZ,
  duration_min       REAL,                -- sum of sessions (§7.5)
  n_sessions         INT,                 -- -> V11
  tests_passed       INT,
  tests_total        INT,                 -- -> V8, ground truth
  diff_agreement     REAL,                -- differential-execution agreement rate
  equivalence        TEXT,                -- Equivalent|Mostly|Not|CannotDetermine
  out_of_scope_lines INT,                 -- -> V9
  verdict_trace      BIGINT REFERENCES traces(trace_id),
  UNIQUE (student_id, assignment_id, attempt_no)
);
-- REVISED: `commit_sha`/`submitted_at` are nullable here, NOT NULL in VDEL_REDESIGN.md
-- 11's original spec. An attempt now exists the moment a variant is assigned to a
-- student (scripts/render_student_repo.py), which is BEFORE anything has been pushed to
-- GitHub -- there is no real commit_sha or submitted_at yet, and this project's own
-- rule (config/roster.example.yaml's "there is no default... a made-up date makes V4
-- meaningless") forbids inventing placeholder values for either just to satisfy NOT
-- NULL. Both get filled in for real once raw_commits has a matching row (collect_github,
-- a later step). ALTER, not just a different CREATE TABLE column, because `attempts`
-- already exists in any database that ran this file before this change -- CREATE TABLE
-- IF NOT EXISTS does nothing to an existing table's constraints, matching 05's own
-- ALTER-after-CREATE precedent for the same reason (D-008).
ALTER TABLE attempts ALTER COLUMN commit_sha DROP NOT NULL;
ALTER TABLE attempts ALTER COLUMN submitted_at DROP NOT NULL;

-- D-041's invariant, on the schema object itself -- visible via \d+ attempts, not only
-- readable by someone who already knows to go look in DECISIONS.md. COMMENT ON always
-- overwrites the existing comment for that object; re-running this file is therefore
-- idempotent by construction, the same property CREATE TABLE IF NOT EXISTS gives the
-- tables themselves.
COMMENT ON TABLE attempts IS
  'One row per (student, assignment, attempt_no) combination, created at RENDER time '
  '(see D-041). submitted_at IS NULL means the variant was assigned but not yet '
  'submitted. A naive COUNT(*) overcounts real attempts -- filter '
  'WHERE submitted_at IS NOT NULL for anything counting actual submissions.';

COMMENT ON COLUMN attempts.submitted_at IS
  'NULL until collect_github fills it in from a real commit (D-041). Treat NULL as '
  '"assigned, not yet worked" -- not as missing data.';

COMMENT ON COLUMN attempts.commit_sha IS
  'NULL until collect_github matches a real push (D-041). Same nullability reasoning '
  'as submitted_at.';

CREATE TABLE IF NOT EXISTS test_results (   -- the evidence behind tests_passed
  attempt_id  BIGINT NOT NULL REFERENCES attempts(attempt_id),
  test_name   TEXT NOT NULL,
  gap_id      TEXT REFERENCES gaps(gap_id),   -- localises failure to a concept
  passed      BOOLEAN NOT NULL,
  message     TEXT,
  PRIMARY KEY (attempt_id, test_name)
);

-- ═══ RESOURCES (replaces RAG) ════════════════════════════════════════

CREATE TABLE IF NOT EXISTS resources (
  resource_id TEXT PRIMARY KEY,
  concept_ids TEXT[] NOT NULL,
  kind        TEXT,                       -- book_section | doc_page | kaggle | video
  title       TEXT NOT NULL,
  locator     TEXT,                       -- 'Ch. 4, §4.2'
  url         TEXT,                       -- verified once, at authoring time
  level       TEXT
);
-- Named (§11's own "CREATE INDEX ON resources ..." is anonymous) so IF NOT EXISTS has
-- something to check against on a re-run -- Postgres requires a name for that form.
CREATE INDEX IF NOT EXISTS idx_resources_concept_ids ON resources USING GIN (concept_ids);

-- ═══ PER-FILE COMMIT ATTRIBUTION (D-043) ═══════════════════════════════
--
-- `raw_commits`/`raw_workflow_runs`.assignment_id were NOT NULL under the one-repo-
-- one-assignment model (sql/02_raw_tables.sql). Under this file's curriculum model, one
-- repo now covers FOUR assignment_ids (one per `assignments.file_path`), so a single
-- commit's real assignment attribution can be one match, zero (a README/CI-config-only
-- commit), or more than one (a commit touching both extract.py and load.py). A scalar
-- NOT NULL column cannot honestly hold "zero" or "more than one" -- same shape as D-041's
-- `attempts.commit_sha`/`submitted_at`, and the same fix: relax the constraint rather
-- than invent a value. `raw_commits` itself is unchanged otherwise -- VDEL_REDESIGN.md
-- §10.4 pins it "Keep, correctly designed", and this ALTER only touches one column's
-- nullability, not its grain (still one row per sha) or its PK.
--
-- The real, non-ambiguous multi-assignment attribution lives in `attempts` instead --
-- `attempts.commit_sha` already carries no uniqueness constraint (D-041), so two
-- `attempts` rows (one per touched assignment) can already point at the same
-- `raw_commits.sha` with zero further schema change. `collectors/collect_github.py`
-- writes both sides: one `raw_commits` row per commit (assignment_id = the single match,
-- or NULL if zero/multiple), and one `attempts` UPDATE per matched assignment.
--
-- `raw_workflow_runs.assignment_id` relaxes for the same reason but a coarser one: a CI
-- run tests the whole repo, not one file, so it cannot be file-matched at all under this
-- model. NULL there means "ambiguous across >1 assignment in this repo", same convention
-- as `raw_commits`. Per-run test-level attribution is `attempts.test_results.gap_id`'s
-- job already (sql/06 above), not this column's -- VDEL_REDESIGN.md §10.4 already flags
-- `raw_workflow_runs` "⚠️ Extend" for unrelated reasons; not resolving that note here.
ALTER TABLE raw_commits ALTER COLUMN assignment_id DROP NOT NULL;
ALTER TABLE raw_workflow_runs ALTER COLUMN assignment_id DROP NOT NULL;

COMMENT ON COLUMN raw_commits.assignment_id IS
  'NULL means this commit matched zero or more than one assignment file_path in its '
  'repo (D-043). The real per-assignment attribution for a multi-match commit is on '
  'attempts, not here -- see collectors/collect_github.py.';

COMMENT ON COLUMN raw_workflow_runs.assignment_id IS
  'NULL means this run''s repo covers more than one assignment_id, so a single-column '
  'attribution would be a guess (D-043). Per-assignment/per-concept detail belongs on '
  'test_results.gap_id, not here.';
