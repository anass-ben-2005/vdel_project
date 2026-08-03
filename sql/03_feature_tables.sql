-- Transcribed from VDEL_Modules_1_2_Build.md Part C.
-- IF NOT EXISTS added per BUILD_PLAN 0.3 (idempotent re-runs); everything else is the
-- document's, including the kt_params defaults and the items table's item-level shape.

CREATE TABLE IF NOT EXISTS learner_features (
  student_id            TEXT NOT NULL REFERENCES students(student_id),
  computed_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  window_days           INT NOT NULL DEFAULT 14,
  mastery               JSONB NOT NULL,   -- V1
  engineering_discipline JSONB NOT NULL,  -- V2
  effort_regulation     JSONB NOT NULL,   -- V3
  pace                  JSONB NOT NULL,   -- V4
  error_response        JSONB NOT NULL,   -- V5
  error_frequency       JSONB NOT NULL,   -- V6
  help_seeking          JSONB,            -- V7 (v2 seam, nullable)
  mastery_model         TEXT NOT NULL DEFAULT 'bkt_v1',
  formula_ver           TEXT NOT NULL DEFAULT 'v2',
  PRIMARY KEY (student_id, computed_at)
);

-- BKT / KT-IDEM parameters (versioned; EM-fitted values land here later)
CREATE TABLE IF NOT EXISTS kt_params (
  param_set   TEXT NOT NULL DEFAULT 'bkt_v1',
  concept_id  TEXT NOT NULL,
  p_l0 REAL NOT NULL DEFAULT 0.30, p_t REAL NOT NULL DEFAULT 0.15,
  p_guess REAL NOT NULL DEFAULT 0.20, p_slip REAL NOT NULL DEFAULT 0.10,
  fitted BOOLEAN NOT NULL DEFAULT FALSE,   -- FALSE => cold-start prior
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (param_set, concept_id)
);

-- Item bank for KT-IDEM difficulty (IRT-lite now, 2PL later)
CREATE TABLE IF NOT EXISTS items (
  item_id      TEXT PRIMARY KEY,
  concept_ids  TEXT[] NOT NULL,
  difficulty   REAL NOT NULL DEFAULT 0.5,     -- 1 - cohort pass rate, Beta-smoothed
  n_cohort_obs INT  NOT NULL DEFAULT 0
);
