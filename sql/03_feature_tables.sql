-- Computed feature tables (the seven variables + params)

CREATE TABLE IF NOT EXISTS learner_features (
  student_id             TEXT NOT NULL REFERENCES students(student_id),
  computed_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  window_days            INT NOT NULL DEFAULT 14,
  mastery                JSONB NOT NULL,
  engineering_discipline JSONB NOT NULL,
  effort_regulation      JSONB NOT NULL,
  pace                   JSONB NOT NULL,
  error_response         JSONB NOT NULL,
  error_frequency        JSONB NOT NULL,
  help_seeking           JSONB,
  mastery_model          TEXT NOT NULL DEFAULT 'bkt_v1',
  formula_ver            TEXT NOT NULL DEFAULT 'v2',
  PRIMARY KEY (student_id, computed_at)
);

CREATE TABLE IF NOT EXISTS kt_params (
  param_set   TEXT NOT NULL DEFAULT 'bkt_v1',
  concept_id  TEXT NOT NULL,
  p_l0        REAL NOT NULL DEFAULT 0.30,
  p_t         REAL NOT NULL DEFAULT 0.15,
  p_guess     REAL,
  p_slip      REAL,
  PRIMARY KEY (param_set, concept_id)
);

CREATE TABLE IF NOT EXISTS items (
  concept_id  TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  difficulty  REAL
);
