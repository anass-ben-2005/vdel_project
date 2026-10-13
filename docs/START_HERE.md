# START HERE — VDEL Project Map

> Read this file first, completely, before opening or reasoning about any other file.
> It exists because an earlier session invented database tables and a data source that
> contradicted the actual module documents. That must not happen again. **When any file
> conflicts with another, the priority order in Part 1 decides who wins — stop and ask
> the person rather than guessing.**

---

## Part 0 — What this project is, in three sentences

VDEL is a Virtual Data Engineering Lab at UiTM. This repo is the **student-side AI
intelligence layer**: it watches students work (via GitHub), maintains an auditable model
of what each student knows, grades their code with an LLM-based agent, and will eventually
coach them when stuck. M0–M4 are built and tested (foundations, telemetry, memory + the
Echo Agent, the LLM gateway, the Code Agent); M5 was dropped (`DECISIONS.md`); M6 and M7
remain designed but not yet built. A supervisor-mandated redesign (`DECISIONS.md` D-035
onward, 2026-08-19) expands the assessment model to completion problems — its schema and
`assessment/` package are documented in `CLAUDE.md` but **not yet implemented in code**:
no `assessment/` directory and none of `projects`/`gaps`/`variants`/`attempts`/`sessions`/
`test_results`/`resources` exist in `sql/` yet.

---

## Part 1 — Authority hierarchy (read this before touching any file)

Files are grouped into four tiers. **Higher tiers win every disagreement.**

```
TIER 0  DECISIONS.md           ← the supersession log. Read FIRST. An ACCEPTED ADR here
           │                      beats every other file, including CLAUDE.md.
TIER 1  CLAUDE.md              ← the condensed, current source of truth. Start here.
           │
TIER 2  The four module docs   ← the original full designs. CLAUDE.md summarizes these;
        (Modules_1_2, Modules_3_9,   if CLAUDE.md is silent on something, these are next.
         Execution_Plan, complete_design)
           │
TIER 3  explanation.md         ← what the CODE actually does today, including bugs found
        + BUILD_PLAN.md            and fixed. Ground truth for "is X actually built."
           │
TIER 4  Everything else        ← historical planning documents. Useful for context on
                                   HOW decisions were reached, but superseded where they
                                   conflict with Tiers 1-3. Listed at the bottom, flagged.
```

**The single most important rule:** if a task seems to require a new table, a new file, or
a new approach that isn't in Tier 0, Tier 1 or Tier 2 — stop and ask. Check `DECISIONS.md`
first: structure that looks forbidden by `CLAUDE.md` may have been explicitly authorised
there (see D-035).

---

## Part 2 — File-by-file map

### Tier 0 — The supersession log (read before anything else)

| File | What it is | Why it exists |
|---|---|---|
| **`DECISIONS.md`** | Append-only architecture decision log. An ACCEPTED entry here supersedes anything in Tiers 1–4 that it names, including `CLAUDE.md`. | Structure that reads as forbidden in a lower tier may have been explicitly authorised here later — check before concluding a task is out of scope. |

### Tier 1 — Read first, always

| File | What it is | Why it exists |
|---|---|---|
| **`CLAUDE.md`** | Condensed project context: scope, architecture, schemas, invariants, domain reference. Auto-loaded by Claude Code every session. | The single fastest path to full context. If you only read one file, read this one. |

### Tier 2 — The original designs (read when CLAUDE.md references them or is silent)

| File | Covers | Read when |
|---|---|---|
| **`VDEL_Modules_1_2_Build.md`** | Module 1 (the seven evaluation variables — full formulas, code) + Module 2 (telemetry ingestion — collector, classifier, schema) | Working on anything in `variables/`, `collectors/`, or the raw/feature tables |
| **`VDEL_Modules_3_9_Build.md`** | Modules 3–9: dynamic memory, LLM selection methodology, the three grading agents, the Reviewer, the system backbone | Working on `memory/`, `agents/`, `system/llm.py`, or anything M2 and later |
| **`VDEL_v1_Execution_Plan.md`** | The milestone plan (M0–M7): what to build in what order, each milestone's Definition of Done | Sequencing work, or checking "is this milestone actually done" |
| **`vdel_complete_design_document.md`** | Full design rationale in five phases + a glossary + a "defend it" compendium of one-line justifications for every major decision | Understanding *why* a decision was made, or preparing to defend a choice to a supervisor |

### Tier 3 — Ground truth on the actual codebase

| File | What it is | Why it matters |
|---|---|---|
| **`explanation.md`** | A detailed account of what M0+M1 code actually does, file by file, including a documented history of bugs found and fixed during earlier build passes (e.g., a mathematically inert BKT update, a classifier that was defined but never called) | This is the only document that tells you what's **actually true of the running code today**, as opposed to what was designed. Read before touching `variables/`, `collectors/`, or `features/`. |
| **`BUILD_PLAN.md`** | Ordered, executable task list for M0–M4 with a Definition of Done per milestone | The literal task list an agent should follow, in order |

### Tier 4 — Historical / superseded (context only, flagged individually)

| File | Status | Note |
|---|---|---|
| `vdel_implementation_plan.md` | Superseded by `VDEL_v1_Execution_Plan.md` | Earlier-stage planning document; still fine for narrative context on how the project was scoped, but the milestone plan in Tier 2 is authoritative. |
| `vdel_master_build_guide.md` | Superseded by the two Modules_*_Build.md docs | An earlier consolidated draft. The Modules documents are the current, code-bearing version. |
| `VDEL_v01_Plan.md` | **Superseded — do not follow.** | This plan proposed building against a public dataset with `problems`/`attempts` tables. **That approach was abandoned.** The actual data source is the student's own GitHub repositories, per Module 2. Keep this file only as a record of a path not taken. |
| `VDEL_Presentation.html` | Reference / presentation artifact | A supervisor-facing HTML slide deck summarizing the design. Not a spec — useful for tone and framing only. |

---

## Part 3 — The actual code (if included in this project)

If the working codebase is also uploaded, here's the map through it. Everything here is
described in detail in `explanation.md` — read that first, this table is just navigation.

```
sql/
  01_reference_tables.sql      students, assignments
  02_raw_tables.sql            raw_commits, raw_workflow_runs
  03_feature_tables.sql        learner_features, kt_params, items (items now superseded
                                 by variants per D-035 -- not yet dropped in code)
  04_indexes.sql                performance indexes (note: applied after 05, see file header)
  05_memory_tables.sql         traces, sessions, learner_profile -- live: traces and
                                 learner_profile are written by the fast path (M2)

config/
  concepts.yaml                the ~19-of-25 concept taxonomy
  concepts.py                  loader + validator
  roster.example.yaml          template — the REAL roster.yaml maps to real GitHub repos

collectors/
  collect_github.py            pulls commits + CI runs from GitHub, optimized
  error_classifier.py          CI failure text -> concept (never guesses; unmatched -> "unclassified")

variables/                     THE MATH. Pure functions, no I/O, one file per variable.
  mastery.py                   V1 — Bayesian Knowledge Tracing + KT-IDEM
  habits.py                    V2 discipline + V3 effort regulation
  pace.py                      V4 — censoring-aware learning pace
  error_response.py            V5 — wheel-spinning vs productive failure
  error_frequency.py           V6 — opportunity-normalized error rate
  (V8-V11, the redesign's new variables, are documented in CLAUDE.md 8 but not yet coded)

features/
  compute_features.py          wires the raw tables to the variable functions

memory/                        M2: THE ONLY door to memory (traces, learner_profile)
  memory.py                    log_trace, get_profile, update_mastery, rebuild_from_traces

agents/                        M2 + M4: the grading agents
  echo_agent.py                M2 tracer bullet -- rule-based, CI pass/fail only
  code_agent.py                M4 -- the LLM judge, preserves echo_agent's interface
  tools.py                     deterministic ruff/sqlfluff stage (invariant 12: no execution)
  prompts.py, PROMPT_CHANGELOG.md   the versioned judge prompt
  validation.py                invariant 6: fabricated evidence quotes reject the verdict

system/
  db.py                        the ONLY place a database connection is opened
  llm.py                       M3: the LLM gateway -- Anthropic, NVIDIA (D-031), Google
                                 (D-032) live; OpenAI and qwen_local remain stubs

scripts/
  init_db.py, smoke_test.py, seed_data.py, collect.py, prove_event_sourcing.py

tests/
  test_mastery.py, test_variables.py, test_classifier.py, test_concepts.py,
  test_sara.py                 — hand-computed worked example, the strongest test in the repo
  test_pipeline_integration.py — end-to-end, raw tables -> learner_features
  test_memory.py, test_prove_event_sourcing.py, test_echo_agent.py — M2
  test_llm.py — M3        test_code_agent.py, test_tools.py, test_prompts.py, test_validation.py — M4
```

**Not yet built:** `system/orchestrator.py`, `system/observability.py` (M6, needs ≥2 agents
to aggregate), a Coach (M7). Also not yet built, though documented in `CLAUDE.md` as
in-scope per the redesign (D-035): the `assessment/` package (`gap_parser.py`,
`gap_generator.py`, `scope_check.py`, `diff_runner.py`) and its seven new tables
(`projects`/`gaps`/`variants`/`attempts`/`sessions`/`test_results`/`resources`) — none of
this exists in `sql/` yet, confirmed by checking the repo directly, not assumed from
`CLAUDE.md`'s plan.

---

## Part 4 — What to actually upload to a new Claude project

**Minimum (always include):**
1. `DECISIONS.md` — Tier 0. Read before `CLAUDE.md`, not after.
2. `CLAUDE.md`
3. `VDEL_Modules_1_2_Build.md`
4. `VDEL_Modules_3_9_Build.md`
5. `VDEL_v1_Execution_Plan.md`
6. `explanation.md`
7. `BUILD_PLAN.md`

**Add if continuing active development on the codebase:**
8. All files under `sql/`, `config/`, `collectors/`, `variables/`, `features/`, `memory/`,
   `agents/`, `system/`, `scripts/`, `tests/` — i.e., the actual repo

**Add only if useful for narrative/defense context, not required for building:**
9. `vdel_complete_design_document.md` (glossary + "defend it" answers — genuinely useful
   before a supervisor meeting)
10. `docs/design/VDEL_REDESIGN.md` (the 2026-08-19 redesign critique — background for why
    D-035 onward exist)
11. `VDEL_Presentation.html` (tone/framing reference)

**Do not upload unless specifically asked about project history:**
- `vdel_implementation_plan.md`, `vdel_master_build_guide.md`, `VDEL_v01_Plan.md` — these
  are superseded and risk confusing a fresh Claude into treating an abandoned plan as current.

---

## Part 5 — First message to send the new Claude

Copy this as your opening message in the new project:

> "This is the VDEL student-side AI intelligence layer. Read START_HERE.md first — it
> explains which documents are authoritative and which are historical. Then read
> CLAUDE.md fully. The four module documents and explanation.md are ground truth for
> design and for what the code actually does. Do not invent database tables, files, or
> approaches that aren't in those documents — if something seems missing or ambiguous,
> stop and ask me rather than guessing. Once you've read everything, summarize back to me
> in your own words: (1) what M0 and M1 actually do today, (2) what the seven evaluation
> variables are and which ones currently produce real signal vs. structurally degenerate
> output, and (3) what M2 is and why the Echo Agent exists. I'll correct anything you get
> wrong before we start work."

That last instruction matters — **make it explain the project back to you** before doing
any work. That's how you catch a wrong mental model in one message instead of after a
day of building on a bad assumption.
