# CHANGELOG

Built from [docs/DECISIONS.md](docs/DECISIONS.md), the append-only record of what was decided and why,
which is the authority; this file is a map into it. There are no version tags yet, so entries are grouped
by period and theme, newest first, each with the decision numbers to read. Dates are the `Date:` lines of
the decisions. A decision whose title says OPEN was open when written; read the entry for its current
status. Decisions D-200 and up (the agents branch) are in
[docs/DECISIONS_AGENTS.md](docs/DECISIONS_AGENTS.md) (D-100 explains why).

## Unreleased: the `v1-finalize` branch (2026-10-13)

- **D-105** Stage 1 hygiene: `docs/` tracked; dependencies pinned; `.env.example` names only;
  `scripts/doctor.py` (read-only readiness checks); `scripts/roster_apply.py` (backup, diff, `--yes`);
  the delivery "Next:" hint no longer points at an unsandboxed `grade_collected`; `run_cycle` and
  `run_hourly` warn about an open attempt the roster cannot reach; `docs/KNOWN_ISSUES.md`; three tests
  that failed once a real LLM call had created `.vdel/` now compare state instead of absence.
- **D-106** Stage 2: README rewritten, INSTALL, ARCHITECTURE, AUTHORING, CONTRIBUTING, CHANGELOG, GLOSSARY.
- **D-107** Stage 3: `config/checks.yaml` (a public description per hidden test, all `draft`),
  `config/checks.py` and a `statement` form in `config/judging.yaml` that ignore drafts,
  `scripts/validate_master.py` (markers, ids across the curriculum, test coverage, descriptions, judging,
  resources).
- **D-108** Stage 4: `--agents-v2` and the Feedback Agent v2 (prompt `fb2`): the student's own lines, reviewed
  check descriptions, recurrence, a three-level hint ladder, a stricter validator, no provider call for a stub-only
  commit or when there is nothing to quote.
- **D-109** Stage 5: the Code Agent v2 under `--agents-v2` (once per attempt, on the freezing commit; prompt v4
  with no correctness opinion and no reference; the benchmark keeps both), an instructor section "correct but
  approach <= 2" in `scripts/code_agent_report.py`, and the "Going further" section built, disabled and locked
  behind a benchmark-agreement gate that the one real result does not meet.
- **D-110** Stage 6: a non-owner database role for the hourly task (a proposal, not applied), the student data
  notice in every `ASSIGNMENT.md`, a fail-closed per-student opt-out (`ai_notes` in the roster), and the
  `--ab-llm` experiment with a read-only `scripts/ab_report.py`; `docs/PILOT.md`.
- Later stages of the branch (handoff documentation, authoring scaffolding, agents v2, pilot preparation)
  add their own entries (D-105 onward in [docs/DECISIONS.md](docs/DECISIONS.md)).

## The v1 operating loop (2026-10-07 to 2026-10-12)

**Agents behind flags.** D-099 the Feedback Agent in the hourly loop behind `--with-llm`, with call caps;
D-100 pointer to the agents branch decisions; D-101 a manual, capped first LLM call; D-102 a capped real
benchmark run; D-103 the Code Agent hardened (escaped delimiters, private-copy linters, per-assignment
criteria, gap-line scope, idempotent verdict trace); D-104 the Code Agent wired in behind `--with-code-agent`,
plan mode, an internal report, task switches.

**Delivery, feedback, operation.** D-086 v1 operating decisions; D-089 feedback by GitHub issue; D-090
`deliver_next_attempt` and a new private repo per attempt; D-091 the hourly task and `docs/OPERATIONS.md`;
D-092 grading in a Docker container; D-094 feedback "as of the commit"; D-095 the task survives any path
character (the apostrophe in `stage_a_l'etranger`); D-097 single-assignment repos ship only importable
visible tests (resolves D-096); D-098 the template push is not a student action (formula v8).

**Robustness and honesty.** D-093 hooks never run at checkout, and what a force-push, a future-dated commit
or a deleted repo does today; D-085 `out_of_scope_lines` stays NULL when not measured; D-087 documentation
addenda; D-088 V2 cleanliness measured with gap-scoped lint (formula v7).

**Feedback and mastery details.** D-074 feedback v0 without an LLM; D-077 test name and exception type, never
the assertion; D-078 `low data` when n < 3; D-079 one mastery observation per (attempt, gap), formula v5;
D-084 an unattempted stub is not a failure, formula v6; D-081 rollout order; D-082 rebuild writes nothing when
nothing changed; D-083 first real `run_cycle`; D-076 the demo grades in a rolled-back transaction.

**Cycle and grading plumbing.** D-056 `grade_collected`; D-057 `publish_repo`; D-062 `sync_template`; D-063
`head_sha` and formula v3; D-064 the suite runs on a throwaway `<db>_test` database; D-065 sandboxed grading
with an explicit environment; D-066 a hidden test that cannot be imported; D-067 the collector skips logs it
has; D-069 formula v4 (initial commit excluded, no grading after the freeze); D-070 one roster loader; D-071
`run_cycle`; D-072 the next-attempt rule; D-073 `scope_check` wired into grading (V9); D-075 addenda; D-080
the Docker sandbox decided (built in D-092).

## The completion-problem redesign and the assessment layer (2026-08-19 to 2026-10-08)

**Redesign.** D-035 attempts, variants, gaps, sessions in scope (supersedes the old prohibition); D-036
correctness is decided by execution, not by an LLM; D-037 notebook interface rejected; D-038 RAG chatbot
dropped for a curated resource table; D-039 internal documents stay ignored; D-040 `sessions` and
`activity_sessions` split; D-041 attempts exist before a commit; D-042 a concept group is hidden whole; D-043
per-file attribution of commits; D-044 `items` superseded by `variants`; D-045 an assignment freezes only at
100% hidden-test pass; D-046 tests are attributed to gaps with `@pytest.mark.gap`; D-047 and D-048 curriculum
concepts protected from the roster, results wired to BKT/V5/V6 through `memory.py` only.

**Curriculum and grading.** D-052 per-project stage lists; D-054 only gaps the attempt hid count as evidence;
D-055 path-independent test names; D-058 `weather_etl` load and quality keep one fixed variant (a known
limit); D-060 the generated CI installs its own tools and lint cannot block pytest; D-061 an agent verdict
never feeds mastery.

**Verification found a bug.** D-034 the first live event-sourcing proof reported DIFFERENT; resolved (a
`features_ref` pointer kept in sync).

## The LLM gateway and the Code Agent (2026-08-12 to 2026-08-31)

D-019 to D-021 M3 scope and two OPEN document disagreements; D-022 schema validation and the corrective retry
live in the gateway; D-023, D-031, D-032 providers (google reinstated, NVIDIA added); D-024 unstamped prices and
model ids; D-025 `temperature=0` only where accepted; D-026 `benchmark/submissions/` excluded from lint by
directory; D-027 no agent ever executes submitted code (invariant 12); D-028 fixtures verified without Spark;
D-029 the ground-truth file shape; D-030 `scripts/collect.py` follows the DAG's pattern; D-033 `validate_evidence` gaps closed; D-049 a two-layer fallback chain;
D-050 the first benchmark runner, and the free tier's daily cap as the blocker; D-051 a 30 s call timeout;
D-053 the demo's primary provider; D-059 the gateway strips one surrounding code fence.

## Memory and the Echo Agent (2026-08-11 to 2026-08-12)

D-007 `update_mastery` drops Beta state, fixed by replay; D-008 `session_digest` transcription gap; D-009 to D-014
the recurrence rule, weakness ids, the rebuild taxonomy, `opened_at` and reflection timestamps from the trace,
the `payload.action` discriminator; D-015 to D-018 the Echo Agent (matches the live memory door, scores only
what CI evidences, is not mastery evidence; D-018 whether invariant 6 binds a deterministic agent was OPEN).

## Foundations (2026-08-10 to 2026-08-11)

D-001 a verification pass before M2; D-002 benchmark authoring pulled forward; D-003 the Sara `spark.joins`
discrepancy stays a strict `xfail`; D-004 V4 and V2's alpha gate are structurally degenerate at a cohort of one;
D-005 the Claude Code setup built around specification verification; D-006 GitHub collection deferred (D-087
adds an addendum).
