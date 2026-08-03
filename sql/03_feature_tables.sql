-- Module 1 outputs: the seven variables, plus the knowledge-tracing parameters.

CREATE TABLE IF NOT EXISTS learner_features (
  student_id             TEXT NOT NULL REFERENCES students(student_id),
  computed_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  window_days            INT NOT NULL DEFAULT 14,
  mastery                JSONB NOT NULL,   -- V1
  engineering_discipline JSONB NOT NULL,   -- V2
  effort_regulation      JSONB NOT NULL,   -- V3
  pace                   JSONB NOT NULL,   -- V4
  error_response         JSONB NOT NULL,   -- V5
  error_frequency        JSONB NOT NULL,   -- V6
  help_seeking           JSONB,            -- V7 (v2 seam, nullable)
  mastery_model          TEXT NOT NULL DEFAULT 'bkt_v1',
  formula_ver            TEXT NOT NULL DEFAULT 'v2',
  PRIMARY KEY (student_id, computed_at)
);

-- BKT parameters, per concept, per versioned parameter set.
-- p_guess/p_slip are nullable: CLAUDE.md names the columns but does not give values,
-- so the defaults live in exactly one place (variables/mastery.py DEFAULT_PARAMS)
-- rather than being invented twice. EM-fitted values land here at bkt_v2.
CREATE TABLE IF NOT EXISTS kt_params (
  param_set   TEXT NOT NULL DEFAULT 'bkt_v1',
  concept_id  TEXT NOT NULL,
  p_l0        REAL NOT NULL DEFAULT 0.30,
  p_t         REAL NOT NULL DEFAULT 0.15,
  p_guess     REAL,
  p_slip      REAL,
  PRIMARY KEY (param_set, concept_id),
  -- Identifiability guard (Beck & Chang 2007) enforced by the database, not by hope.
  CONSTRAINT kt_params_guess_identifiable CHECK (p_guess IS NULL OR p_guess < 0.5),
  CONSTRAINT kt_params_slip_identifiable  CHECK (p_slip  IS NULL OR p_slip  < 0.5)
);

-- Item difficulty for KT-IDEM (Pardos & Heffernan 2011).
-- TODO(verify): CLAUDE.md section 5 names this table but gives no DDL. This is the
-- minimum KT-IDEM needs. Reconcile against VDEL_Modules_1_2_Build.md before relying on it.
CREATE TABLE IF NOT EXISTS items (
  concept_id  TEXT PRIMARY KEY,
  difficulty  REAL NOT NULL CHECK (difficulty >= 0 AND difficulty <= 1)
);
