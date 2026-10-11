-- 08_lint_columns.sql -- D-088. ADDITIVE and idempotent (ADD COLUMN IF NOT EXISTS). Written for the
-- overnight batch; the test conftest applies it to vdel_test through init_db like every other
-- file. NOT applied to the real database by the batch: apply by hand with
-- `python -m scripts.init_db` (it re-applies every file; each one is idempotent).
--
-- V2 (engineering discipline, cleanliness) needs the number of lint findings on the lines the
-- student wrote, and the number of lines they wrote. Both are gap-scoped (CLAUDE.md invariant
-- 14, VDEL_REDESIGN.md C4): the master's own code is in every submission and is never
-- attributed to the student.
--
-- One set of values per attempt, same rule as `out_of_scope_lines` (D-073/D-085): the latest
-- graded commit's value until the attempt freezes, the frozen commit's value afterwards.
-- NULL means NOT MEASURED (the file did not load, the linter could not run, no linter covers the
-- file type, or the scope could not be computed) and is never read as 0.
--
--   lint_violations   findings of the default ruff / sqlfluff rule set on in-gap lines
--   lint_changed_loc  lines the student changed inside the gaps (scope_check.changed_loc_in_gap)
--   lint_tool         'ruff' | 'sqlfluff'

ALTER TABLE attempts ADD COLUMN IF NOT EXISTS lint_violations  INT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS lint_changed_loc INT;
ALTER TABLE attempts ADD COLUMN IF NOT EXISTS lint_tool        TEXT;
