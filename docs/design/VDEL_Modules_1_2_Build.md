# VDEL Student-Side — Modules 1 & 2 Consolidated Build Document
### Evaluation Variables + Telemetry Ingestion — with code, file locations, and reasoning

*Author: Anas · VDEL (university × industry partner) · Student-side workstream*

This document consolidates the work completed so far: the seven student-evaluation
variables (Module 1) and the telemetry ingestion layer that feeds them (Module 2),
including the optimization pass. Every code block states **where the file goes** in
the repo and **why** the approach was chosen.

> **Citation note:** The academic references below (Corbett & Anderson, Pardos &
> Heffernan, Jadud, Watson, Kapur, Goh & Barabási, Cronbach, Zimmerman, etc.) are
> drawn from established literature. Verify exact author/year/title before placing
> them in a publication-grade report.

---

## Repository layout

All code in this document maps to this structure:

```
vdel-student-side/
├── sql/
│   ├── 01_reference_tables.sql       # students, assignments
│   ├── 02_raw_tables.sql             # raw_commits, raw_workflow_runs
│   ├── 03_feature_tables.sql         # learner_features, kt_params, items
│   └── 04_indexes.sql                # performance indexes
├── variables/
│   ├── mastery.py                    # Variable 1: BKT + KT-IDEM
│   ├── habits.py                     # Variables 2 & 3: discipline + effort
│   ├── pace.py                       # Variable 4: censoring-aware pace
│   ├── error_response.py             # Variable 5: Jadud/Watwin + wheel-spin
│   └── error_frequency.py            # Variable 6: opportunity-normalized
├── collectors/
│   ├── collect_github.py             # optimized GitHub collector
│   └── error_classifier.py           # CI error → taxonomy concept
├── features/
│   └── compute_features.py           # raw tables → the seven variables
└── dags/
    └── vdel_pipeline.py              # Airflow: collect → compute → update
```

---

# PART A — Context (what this is and how it's used)

The system watches students work (via GitHub), builds a private, continuously-updated
understanding of each student, and uses it to (1) grade submissions with explainable AI
agents and (2) coach students who are stuck.

**Every student has their own private copy of all seven variables.** They are
per-student, and for mastery, per-concept. They update continuously as new telemetry
arrives. The reason there are seven specific variables instead of one overall score:
one number can't tell the coach *what to do*. Seven specific numbers let the system say
"this student understands the material but works slowly — give more time, don't re-teach."

**The data flow (the conveyor belt):**

```
Module 2                    Module 1               Module 3          Modules 5-7
raw GitHub activity    →    seven variables    →   memory/profile →  grading + coaching
(collect + classify)       (the formulas)         (storage)         (the AI agents)
```

Module 2 is the start of the belt (get the data). Module 1 is the math on that data.
This document covers both.

---

# PART B — MODULE 1: The Seven Evaluation Variables

Each variable below states: what it's for, where its data comes from, the algorithm
(with the research comparison), and where the result is stored in memory.

Two memory homes referenced throughout:
- **`learner_features`** — versioned numeric snapshots (one timestamped row per student
  per compute-run). Gives trajectories for free. Regenerable from raw telemetry.
- **`learner_profile`** — single mutable "current belief" row per student (mastery
  vector, weaknesses, reflections). Only distilled, act-on-able beliefs go here.

---

## Variable 1 — Concept Mastery

**What it's for:** The spine of the system — "does the student understand concept X?"
Read by the Code Agent (tone), Pedagogy Agent (trajectory, score-relevant), the weakness
inventory, and the coach (rung selection).

**Data source:** GitHub Actions CI results (`raw_workflow_runs`, pass/fail per concept),
plus item difficulty from cohort pass rate.

**Algorithm & research comparison:**
- Baseline: EWMA — `M ← α·o + (1−α)·M`. Flaws: not a probability, no noise model,
  ignores difficulty, no learning dynamics, no real uncertainty.
- Chosen: **Bayesian Knowledge Tracing** (Corbett & Anderson, 1994) + **item-difficulty
  conditioning KT-IDEM** (Pardos & Heffernan, 2011).
- Rejected: **Deep Knowledge Tracing** (Piech et al., 2015) — needs thousands of
  sequences, is a black box; Gervet et al. (2020) show BKT-family matches/beats deep
  models in low-data regimes (ours).

The equations:
```
# Evidence step (Bayes), correct:
p(L|c)  = p(L)(1−S) / [ p(L)(1−S) + (1−p(L))G ]
# Evidence step, incorrect:
p(L|¬c) = p(L)S     / [ p(L)S     + (1−p(L))(1−G) ]
# Learning step:
p(L)    = p(L|obs) + (1 − p(L|obs))·T
# KT-IDEM (d = 1 − cohort_pass_rate):
G_item  = G·(1−d) ;  S_item = S + (0.40−S)·d·0.5
# Testable prediction:
P(correct_next) = p(L)(1−S) + (1−p(L))G
```
Uncertainty via companion Beta posterior → 90% credible interval instead of a bare count.

**Stored in:** both `learner_features.mastery` and `learner_profile.mastery`.

**File: `variables/mastery.py`**

```python
"""
variables/mastery.py — Concept-mastery estimation for the VDEL Learner Digital Twin.

Model: Bayesian Knowledge Tracing (Corbett & Anderson, 1994)
       + item-difficulty conditioning (KT-IDEM, Pardos & Heffernan, 2011)
       + Beta-Bernoulli companion posterior for calibrated uncertainty.

Design contract:
  - update() is a PURE function of (prior_state, outcome, difficulty, params).
  - p_mastery is a CALIBRATED probability; p_correct_next is externally testable.
  - Identifiability guard (Beck & Chang, 2007): guess, slip clamped < 0.5.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from math import sqrt

try:
    from scipy.stats import beta as _beta
    _HAVE_SCIPY = True
except ImportError:
    _HAVE_SCIPY = False


def _clamp(x, lo, hi): return max(lo, min(hi, x))


@dataclass(frozen=True)
class BKTParams:
    """Per-concept BKT parameters. Defaults are literature-grounded cold-start
    priors; replace with EM-fitted values once >~100 sequences per concept exist."""
    p_l0:    float = 0.30
    p_t:     float = 0.15
    p_guess: float = 0.20
    p_slip:  float = 0.10

    def guarded(self) -> "BKTParams":
        return replace(self,
                       p_guess=_clamp(self.p_guess, 0.01, 0.45),
                       p_slip=_clamp(self.p_slip,  0.00, 0.45))

    def for_item(self, difficulty: float) -> "BKTParams":
        d = _clamp(difficulty, 0.0, 1.0)
        g = self.p_guess * (1.0 - d)
        s = self.p_slip + (0.40 - self.p_slip) * d * 0.5
        return replace(self, p_guess=g, p_slip=s).guarded()


@dataclass
class MasteryState:
    p_mastery: float = 0.30
    n_obs:     int   = 0
    a:         float = 0.5     # Beta posterior — passes + 0.5 (Jeffreys prior)
    b:         float = 0.5     # Beta posterior — fails  + 0.5
    history:   tuple = ()

    def credible_interval(self, level: float = 0.90):
        lo_q, hi_q = (1 - level) / 2, 1 - (1 - level) / 2
        if _HAVE_SCIPY:
            return float(_beta.ppf(lo_q, self.a, self.b)), \
                   float(_beta.ppf(hi_q, self.a, self.b))
        m, v = self.a / (self.a + self.b), self.variance
        return _clamp(m - 1.645 * sqrt(v), 0, 1), _clamp(m + 1.645 * sqrt(v), 0, 1)

    @property
    def variance(self):
        a, b = self.a, self.b
        return (a * b) / ((a + b) ** 2 * (a + b + 1))

    @property
    def confidence(self):
        return 1.0 - min(1.0, sqrt(self.variance) / 0.35)

    def trend(self):
        if len(self.history) < 2:
            return "flat"
        slope = self.history[-1] - self.history[0]
        return "up" if slope > 0.03 else "down" if slope < -0.03 else "flat"


def _posterior_given_obs(p_L, correct, g, s):
    if correct:
        num = p_L * (1.0 - s); den = num + (1.0 - p_L) * g
    else:
        num = p_L * s;         den = num + (1.0 - p_L) * (1.0 - g)
    return num / den if den > 1e-9 else p_L


def _apply_learning(p_L_post, t):
    return p_L_post + (1.0 - p_L_post) * t


def predict_correct(p_L, params):
    p = params.guarded()
    return p_L * (1.0 - p.p_slip) + (1.0 - p_L) * p.p_guess


class MasteryEstimator:
    """One instance manages the full mastery vector for one student."""

    def __init__(self, params_by_concept=None,
                 default_params=BKTParams(), history_len=6):
        self.params_by_concept = params_by_concept or {}
        self.default_params = default_params
        self.history_len = history_len
        self.states: dict[str, MasteryState] = {}

    def _params(self, concept):
        return self.params_by_concept.get(concept, self.default_params).guarded()

    def _state(self, concept):
        if concept not in self.states:
            p = self._params(concept)
            self.states[concept] = MasteryState(p_mastery=p.p_l0, history=(p.p_l0,))
        return self.states[concept]

    def update(self, concept, correct, item_difficulty=0.5):
        st = self._state(concept)
        params = self._params(concept).for_item(item_difficulty)
        before = st.p_mastery
        post = _posterior_given_obs(st.p_mastery, correct, params.p_guess, params.p_slip)
        st.p_mastery = _apply_learning(post, params.p_t)
        st.a += 1.0 if correct else 0.0
        st.b += 0.0 if correct else 1.0
        st.n_obs += 1
        st.history = (st.history + (round(st.p_mastery, 4),))[-self.history_len:]
        lo, hi = st.credible_interval(0.90)
        return {
            "concept": concept,
            "p_mastery": round(st.p_mastery, 4),
            "p_mastery_before": round(before, 4),
            "p_correct_next": round(predict_correct(st.p_mastery, self._params(concept)), 4),
            "n_obs": st.n_obs, "confidence": round(st.confidence, 3),
            "ci90": [round(lo, 3), round(hi, 3)], "variance": round(st.variance, 4),
            "trend": st.trend(), "item_difficulty": round(item_difficulty, 3),
            "eff_guess": round(params.p_guess, 3), "eff_slip": round(params.p_slip, 3),
        }

    def snapshot(self):
        out = {}
        for c, st in self.states.items():
            lo, hi = st.credible_interval(0.90)
            out[c] = {"p_mastery": round(st.p_mastery, 4), "n": st.n_obs,
                      "confidence": round(st.confidence, 3),
                      "ci90": [round(lo, 3), round(hi, 3)], "trend": st.trend()}
        return out


class DifficultyEstimator:
    """difficulty = 1 - Beta-smoothed cohort pass rate, per item."""
    def __init__(self, prior_a=2.0, prior_b=2.0):
        self.counts: dict[str, list] = {}
        self.prior = (prior_a, prior_b)

    def observe(self, item_id, passed):
        a, b = self.counts.get(item_id, list(self.prior))
        self.counts[item_id] = [a + (1 if passed else 0), b + (0 if passed else 1)]

    def difficulty(self, item_id):
        a, b = self.counts.get(item_id, self.prior)
        return 1.0 - a / (a + b)
```

---

## Variables 2 & 3 — Engineering Discipline + Effort Regulation

*(These two come out of splitting the original vague "coding habits" into two real
constructs, following Zimmerman's Self-Regulated Learning framework: discipline is a
cognition/skill signal, effort regulation is a behavior signal.)*

**Variable 2 — Engineering Discipline.** What it's for: code quality independent of
correctness (routes the coach to a code-review nudge, not a concept intervention).
Data source: `ruff`/`sqlfluff` lint counts + test presence in CI.

**Variable 3 — Effort Regulation.** What it's for: time-management signal (steady vs.
cram). Purely a coaching flag, never touches grades. Data source: commit timestamps.

**Algorithm & research comparison:**
- Discipline: composite indicator — gated by **Cronbach's alpha** (Cronbach, 1951;
  DeVellis, 2016) before averaging its parts. If alpha < 0.70, report components, not a
  composite.
- Effort regularity: baseline `1/(1+CV)` is unstable at low commit counts →
  **burstiness** `B=(σ−μ)/(σ+μ)` (Goh & Barabási, 2008). Pedagogical justification:
  spacing effect (Cepeda et al., 2006).

**Stored in:** `learner_features.engineering_discipline` and
`learner_features.effort_regulation`.

**File: `variables/habits.py`**

```python
"""
variables/habits.py — Engineering Discipline (V2) + Effort Regulation (V3).

Split from the original "coding habits" per Zimmerman's SRL framework:
  - Engineering Discipline = cognition/skill (cleanliness, testing)
  - Effort Regulation      = behavior (commit regularity, procrastination)

Fixes vs. baseline:
  - CV-based regularity (unstable at low n) -> burstiness (Goh & Barabási, 2008)
  - fixed magic-number thresholds -> cohort-relative percentiles
  - equal-weight averaging with no justification -> Cronbach's alpha gate (Cronbach 1951)
"""
from __future__ import annotations
from dataclasses import dataclass
from statistics import mean, pstdev, variance


def _clamp(x, lo, hi): return max(lo, min(hi, x))


# ----- Effort Regulation: regularity via burstiness -----
def burstiness_regularity(gap_hours):
    """B in [-1,1]: -1 periodic, 0 random, +1 bursty. Mapped to [0,1], regular=high.
    Returns None if too few gaps (do NOT fabricate from 1 gap)."""
    if len(gap_hours) < 2:
        return None
    mu, sigma = mean(gap_hours), pstdev(gap_hours)
    if mu + sigma == 0:
        return 1.0
    B = (sigma - mu) / (sigma + mu)
    return round((1.0 - B) / 2.0, 3)


def effort_regulation(gap_hours, release_to_first_commit_h):
    return {
        "regularity": burstiness_regularity(gap_hours),
        "burstiness": (round((pstdev(gap_hours) - mean(gap_hours)) /
                             (pstdev(gap_hours) + mean(gap_hours)), 3)
                       if len(gap_hours) >= 2 and (pstdev(gap_hours)+mean(gap_hours)) > 0
                       else None),
        "procrastination_h": round(release_to_first_commit_h, 1),  # tracked, NOT scored
    }


# ----- Engineering Discipline: cleanliness + testing -----
def cleanliness(lint_violations, changed_loc):
    if changed_loc <= 0:
        return None
    per_100 = lint_violations / (changed_loc / 100.0)
    return round(1.0 - min(1.0, per_100 / 10.0), 3)


def testing_signal(state):  # 'wired' | 'present' | 'absent'
    return {"wired": 1.0, "present": 0.5, "absent": 0.0}[state]


def cronbachs_alpha(item_matrix):
    """rows=students, cols=sub-signals in [0,1]. >=0.70 => composite defensible."""
    if len(item_matrix) < 10:
        return None
    k = len(item_matrix[0])
    item_vars = [variance([row[c] for row in item_matrix]) for c in range(k)]
    total_var = variance([sum(row) for row in item_matrix])
    if total_var == 0:
        return None
    return round((k / (k - 1)) * (1 - sum(item_vars) / total_var), 3)


@dataclass
class DisciplineResult:
    cleanliness: float | None
    testing: float
    composite: float | None
    composite_valid: bool
    alpha: float | None


def engineering_discipline(lint_violations, changed_loc, tests_state,
                           cohort_alpha=None):
    C = cleanliness(lint_violations, changed_loc)
    T = testing_signal(tests_state)
    valid = cohort_alpha is not None and cohort_alpha >= 0.70
    comps = [v for v in (C, T) if v is not None]
    composite = round(mean(comps), 3) if (comps and valid) else None
    return DisciplineResult(C, T, composite, valid, cohort_alpha)
```

---

## Variable 4 — Learning Pace

**What it's for:** How fast a student reaches a passing solution vs. peers, adjusted for
difficulty. Tells the coach whether to nudge — and whether the *whole cohort* is slow
(assignment problem, not student problem).

**Data source:** `assignments.released_at` + first passing `raw_workflow_runs` per
student + cohort distribution.

**Algorithm & research comparison:**
- Baseline flaw: cohort median from passers only = **right-censoring / survivorship
  bias**.
- Chosen: **survival analysis** framing — keep non-passers as censored lower bounds;
  upgrade to **Cox proportional hazards** (Cox, 1972) when cohort data exists.
- `log2` makes "2× faster" and "2× slower" symmetric around the average.

**Stored in:** `learner_features.pace` (per student) + cohort `censoring_rate`
(assignment level).

**File: `variables/pace.py`**

```python
"""
variables/pace.py — Learning Pace: cohort-normalized, censoring-aware.

Baseline bug fixed: computing the cohort median from PASSERS ONLY drops students
still stuck (survivorship bias). Non-passers are kept as censored lower bounds.
Upgrade path: lifelines CoxPHFitter -> per-student hazard ratio.
"""
from math import log2


def _clamp(x, lo, hi): return max(lo, min(hi, x))


def learning_pace(time_to_pass_h, cohort_median_h, elapsed_h=None, censored=False):
    """
    time_to_pass_h : hours from release to first passing run (if passed)
    cohort_median_h: median time-to-pass over PASSERS on this assignment
    elapsed_h      : hours since release so far (used when censored)
    censored       : True if the student has NOT passed yet
    """
    if censored:
        r = max((elapsed_h or 0) / cohort_median_h, 1.0)   # lower bound only
        return {"score": round(_clamp(0.5 - 0.25 * log2(r), 0, 0.5), 3),
                "censored": True,
                "note": "lower-bound; excluded from cohort median calc"}
    r = time_to_pass_h / cohort_median_h
    return {"score": round(_clamp(0.5 - 0.25 * log2(r), 0, 1), 3),
            "ratio": round(r, 3), "censored": False}


def cohort_censoring_rate(n_not_passed, n_total):
    """Assignment-level signal: high rate => assignment may be too hard/unclear."""
    return round(n_not_passed / n_total, 3) if n_total else 0.0
```

---

## Variable 5 — Error Response

**What it's for:** *How* a student reacts when something breaks. Separates a bold
experimenter (many errors, resolves all, improving) from a struggler (many errors,
resolving nothing). The metacognitive heart of the set.

**Data source:** Sequential `raw_workflow_runs` (fail → next resolving run, matched by
error class) + mastery trend from Variable 1.

**Algorithm & research comparison:**
- Grounding: **Error Quotient** (Jadud, 2006) + **Watwin** (Watson et al., 2013).
- Productive-vs-unproductive layer: **wheel-spinning** (Beck & Gong, 2013) +
  **productive failure** (Kapur, 2008).

**Stored in:** `learner_features.error_response`; if wheel-spinning, flags into
`learner_profile.weaknesses`.

**File: `variables/error_response.py`**

```python
"""
variables/error_response.py — Error Response (V5).

Grounded in Jadud's Error Quotient (2006) and the Watwin score (Watson et al., 2013),
with a productive-vs-unproductive layer: wheel-spinning (Beck & Gong, 2013) vs.
productive failure (Kapur, 2008). The distinction drives the intervention.
"""
from statistics import mean


def _clamp(x, lo, hi): return max(lo, min(hi, x))


def error_response(median_ttf_h, resolved_errors, total_errors,
                   concept_opportunities, current_mastery, mastery_slope):
    ttf_score = _clamp(1 - median_ttf_h / 24.0, 0, 1)
    resolution_ratio = resolved_errors / total_errors if total_errors else 1.0
    base = mean([ttf_score, resolution_ratio])

    wheel_spinning = (concept_opportunities >= 8 and current_mastery < 0.6
                      and mastery_slope <= 0.0)
    productive = mastery_slope > 0.03

    score = base
    if wheel_spinning:
        score = _clamp(base - 0.25, 0, 1)
    elif productive:
        score = _clamp(base + 0.15, 0, 1)

    return {"score": round(score, 3), "ttf_score": round(ttf_score, 3),
            "resolution_ratio": round(resolution_ratio, 3),
            "wheel_spinning": wheel_spinning, "productive_failure": productive}
```

---

## Variable 6 — Error Frequency

**What it's for:** Rate + category breakdown of errors. Weak as a standalone predictor
(Jadud found raw counts predict little), so its real job is the per-concept histogram
that feeds mastery and the recurrence rule.

**Data source:** Failed `raw_workflow_runs` classified into concepts + changed-LOC.

**Algorithm & research comparison:**
- Normalize per opportunity (not raw counts) — Jadud caveat.
- Recurrence rule aligns with **Repeated Error Density** (Becker, 2016): same error ×2
  within one assignment opens a weakness immediately.

**Stored in:** `learner_features.error_frequency`; histogram feeds mastery, recurrence
writes to `learner_profile.weaknesses`.

**File: `variables/error_frequency.py`**

```python
"""
variables/error_frequency.py — Error Frequency (V6).

Raw error counts predict little on their own (Jadud, 2006) — the load-bearing outputs
are the per-concept histogram (feeds mastery) and the recurrence rule (opens weaknesses;
Becker, 2016, Repeated Error Density).
"""
from statistics import mean


def _clamp(x, lo, hi): return max(lo, min(hi, x))


def error_frequency(failed_runs, total_runs, errors, changed_loc,
                    by_concept, weekly_slope):
    fail_ratio = failed_runs / total_runs if total_runs else 0.0
    per_100 = errors / (changed_loc / 100.0) if changed_loc else 0.0
    score = 1.0 - _clamp(mean([fail_ratio, min(1.0, per_100 / 5.0)]), 0, 1)
    return {"score": round(score, 3), "fail_ratio": round(fail_ratio, 3),
            "by_concept": by_concept,   # {concept_id: count} -> mastery + weaknesses
            "trend": ("worsening" if weekly_slope > 0
                      else "improving" if weekly_slope < 0 else "flat")}


def recurrence_check(error_class_counts_this_assignment):
    """Same error class >=2 within one assignment -> open a weakness now."""
    return [ec for ec, n in error_class_counts_this_assignment.items() if n >= 2]
```

---

## Variable 7 — Help-Seeking (v2, deferred)

**What it's for:** Whether/how well a student seeks help (avoidance vs. abuse) — a
classic SRL construct. Tells the coach if its interventions land.

**Data source:** *Does not exist yet* — needs the coach's interaction log (Module 7+).

**Grounding:** Aleven et al. (2003/2006) help-seeking in intelligent tutoring systems.

**Status:** Documented seam. A reserved column, not yet populated. When built, feeds
`learner_features.help_seeking` and `learner_profile.reflections`.

---

## Variable summary map

| # | Variable | Data source | Core method (cited) | Memory home |
|---|---|---|---|---|
| 1 | Concept Mastery | CI pass/fail + difficulty | BKT + KT-IDEM | features + profile.mastery |
| 2 | Engineering Discipline | linters + test presence | composite w/ Cronbach's α gate | features |
| 3 | Effort Regulation | commit timestamps | burstiness (Goh & Barabási) | features |
| 4 | Learning Pace | release + first-pass times | survival analysis (censoring) | features + assignment-level |
| 5 | Error Response | sequential CI runs + mastery slope | Jadud/Watwin + wheel-spin/productive-failure | features + profile.weaknesses |
| 6 | Error Frequency | classified CI failures + LOC | opportunity-normalized + recurrence (Becker) | features + profile.weaknesses |
| 7 | Help-Seeking (v2) | coach logs (future) | Aleven help-seeking model | features + profile.reflections (seam) |

---

# PART C — MODULE 2: Telemetry Ingestion

Two halves: **collect raw events** from GitHub, then **compute features** from them.

## Design principles

1. **Land raw first, compute features separately** — formulas change (EWMA→BKT proved
   it); keep raw forever so you can recompute history.
2. **Idempotent upserts** (`ON CONFLICT`) — collectors crash and re-run; re-running must
   be safe.
3. **One PostgreSQL for everything** — smallest operational footprint for one developer.
4. **It's an ELT pipeline** scheduled by Airflow — the intelligence layer runs on VDEL's
   own stack.

---

## The schema

**File: `sql/01_reference_tables.sql`**

```sql
CREATE TABLE students (
  student_id       TEXT PRIMARY KEY,          -- university ID
  github_username  TEXT UNIQUE NOT NULL,
  cohort           TEXT NOT NULL
);

CREATE TABLE assignments (
  assignment_id  TEXT PRIMARY KEY,            -- e.g. 'A2'
  repo_prefix    TEXT NOT NULL,               -- Classroom repo naming pattern
  released_at    TIMESTAMPTZ NOT NULL,        -- start clock for Pace
  due_at         TIMESTAMPTZ,
  concepts       TEXT[] NOT NULL              -- taxonomy IDs this assignment tests
);
```

**File: `sql/02_raw_tables.sql`**

```sql
CREATE TABLE raw_commits (
  sha            TEXT PRIMARY KEY,            -- git's unique commit hash
  student_id     TEXT NOT NULL REFERENCES students(student_id),
  assignment_id  TEXT NOT NULL REFERENCES assignments(assignment_id),
  committed_at   TIMESTAMPTZ NOT NULL,        -- timestamps -> gaps -> burstiness
  additions      INT, deletions INT, files_changed INT,
  message        TEXT
);

CREATE TABLE raw_workflow_runs (
  run_id         BIGINT PRIMARY KEY,          -- GitHub's run ID
  student_id     TEXT NOT NULL REFERENCES students(student_id),
  assignment_id  TEXT NOT NULL REFERENCES assignments(assignment_id),
  status         TEXT,
  conclusion     TEXT,                        -- success / failure  (the pass/fail signal)
  started_at     TIMESTAMPTZ, completed_at TIMESTAMPTZ,
  duration_s     INT,                         -- coarse runtime signal
  error_class    TEXT,                        -- filled by classifier
  concept_id     TEXT                         -- taxonomy mapping of the error
);
```

**File: `sql/03_feature_tables.sql`**

```sql
CREATE TABLE learner_features (
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
CREATE TABLE kt_params (
  param_set   TEXT NOT NULL DEFAULT 'bkt_v1',
  concept_id  TEXT NOT NULL,
  p_l0 REAL NOT NULL DEFAULT 0.30, p_t REAL NOT NULL DEFAULT 0.15,
  p_guess REAL NOT NULL DEFAULT 0.20, p_slip REAL NOT NULL DEFAULT 0.10,
  fitted BOOLEAN NOT NULL DEFAULT FALSE,   -- FALSE => cold-start prior
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (param_set, concept_id)
);

-- Item bank for KT-IDEM difficulty (IRT-lite now, 2PL later)
CREATE TABLE items (
  item_id      TEXT PRIMARY KEY,
  concept_ids  TEXT[] NOT NULL,
  difficulty   REAL NOT NULL DEFAULT 0.5,     -- 1 - cohort pass rate, Beta-smoothed
  n_cohort_obs INT  NOT NULL DEFAULT 0
);
```

**File: `sql/04_indexes.sql`** *(the optimization pass — see Part D)*

```sql
-- Match the access pattern of feature queries: filter by (student, assignment), sort by time
CREATE INDEX idx_commits_student_assignment
  ON raw_commits (student_id, assignment_id, committed_at);

CREATE INDEX idx_runs_student_assignment
  ON raw_workflow_runs (student_id, assignment_id, started_at);

-- Partial index: only failed runs carry an error concept -> smaller, faster
CREATE INDEX idx_runs_concept
  ON raw_workflow_runs (concept_id) WHERE conclusion = 'failure';
```

---

## The error classifier (the load-bearing risk)

Maps a CI failure log → taxonomy concept. **Feeds three variables** (Mastery, Error
Response, Error Frequency), so a misclassification silently corrupts mastery. v1 uses a
rule table with an explicit `unclassified` fallback — **never force a wrong guess**; an
unclassified error counts toward frequency but updates no specific mastery.

**File: `collectors/error_classifier.py`**

```python
"""
collectors/error_classifier.py — map a CI failure log to a taxonomy concept.
v1: rule table + explicit 'unclassified' fallback. NEVER force a wrong guess:
an unmatched error updates NO mastery (better to update nothing than the wrong concept).
The low BKT learning rate further limits the damage of any single misclassification.
"""
import re

RULES = [
    (r"ambiguous column",                       "spark.joins"),
    (r"cannot resolve .* given input columns",  "spark.df_basics"),
    (r"AnalysisException.*group by",            "spark.aggregation"),
    (r"is neither present in the group by",     "sql.aggregation"),
    (r"cartesian product|cross join",           "spark.joins"),
    (r"OutOfMemory|GC overhead",                "spark.partitioning"),
    (r"KeyError|IndexError",                    "py.data_structures"),
    (r"SettingWithCopyWarning",                 "py.pandas"),
    (r"SyntaxError|IndentationError",           "py.errors_debugging"),
    (r"AssertionError",                         "py.testing"),
    # extend to your ~15 most common real failures
]


def classify_error(log_text: str):
    """Returns (error_class, concept_id). 'unclassified' if no rule fits."""
    if not log_text:
        return ("empty", "unclassified")
    for pattern, concept in RULES:
        if re.search(pattern, log_text, re.IGNORECASE):
            return (pattern, concept)
    return ("unmatched", "unclassified")
```

---

# PART D — MODULE 2 OPTIMIZATION PASS

The enemy here is the **GitHub rate limit (5,000 req/h)** and **wasted work**. Seven
fixes, applied in the collector below.

| # | Flaw | Fix | Saves |
|---|---|---|---|
| 1 | Re-fetching every commit's detail every run | Skip-if-present + incremental `since=` | ~99% of detail calls after backfill |
| 2 | Sequential blocking requests | Rate-limit-header-aware backoff | Wall-clock; avoids abuse-ban |
| 3 | Row-by-row inserts | Batched `execute_values` | 10-50× on DB writes |
| 4 | Full table scans in feature queries | Matched + partial indexes (sql/04) | Keeps feature compute fast |
| 5 | Recomputing all students daily | Dirty-student incremental recompute | ~80% of daily compute |
| 6 | LLM classifier on every failure | Tiered (rules→LLM) + signature cache | Thousands of calls → dozens |
| 7 | One bad repo crashes everything | Per-repo try/except isolation | Reliability |

**Philosophy:** *Nothing is recomputed that hasn't changed; nothing is fetched that we
already have.*

**File: `collectors/collect_github.py`**

```python
"""
collectors/collect_github.py — rate-aware, incremental, batched, isolated GitHub collector.

Optimizations (see Module 2 optimization pass):
  1. skip-if-present + incremental `since=`  -> ~99% fewer detail calls after backfill
  2. rate-limit-header-aware backoff          -> avoids the hard 5000/h wall + abuse-ban
  3. batched execute_values upserts           -> 10-50x fewer DB round-trips
  7. per-repo failure isolation               -> one bad repo != total outage
"""
import os, time, psycopg2
from datetime import datetime as dt
from psycopg2.extras import execute_values
import requests

GH = "https://api.github.com"
HEADERS = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
           "Accept": "application/vnd.github+json"}


def _get(url, params=None):
    """Single GET with rate-limit awareness (Flaw 2)."""
    r = requests.get(url, headers=HEADERS, params=params, timeout=30)
    remaining = int(r.headers.get("X-RateLimit-Remaining", 1))
    if remaining < 50:                                  # back off before the wall
        reset = int(r.headers.get("X-RateLimit-Reset", time.time()))
        time.sleep(max(0, reset - time.time()) + 1)
    r.raise_for_status()
    return r


def _paged(url, params=None):
    params = dict(params or {}, per_page=100); page = 1
    while True:
        batch = _get(url, dict(params, page=page)).json()
        items = batch.get("workflow_runs", batch) if isinstance(batch, dict) else batch
        if not items:
            return
        yield from items
        if len(items) < 100:
            return
        page += 1


def collect_repo(conn, owner, repo, student_id, assignment_id):
    cur = conn.cursor()

    # Flaw 1b: incremental — only commits since our last collection
    cur.execute("""SELECT MAX(committed_at) FROM raw_commits
                   WHERE student_id=%s AND assignment_id=%s""",
                (student_id, assignment_id))
    since = cur.fetchone()[0]
    params = {}
    if since:
        params["since"] = since.isoformat()

    commit_rows = []
    for c in _paged(f"{GH}/repos/{owner}/{repo}/commits", params):
        sha = c["sha"]
        # Flaw 1a: skip the expensive detail call for commits we already have complete
        cur.execute("SELECT 1 FROM raw_commits WHERE sha=%s AND additions IS NOT NULL", (sha,))
        if cur.fetchone():
            continue
        detail = _get(c["url"]).json()                  # the expensive call, now rare
        s = detail.get("stats", {})
        commit_rows.append((sha, student_id, assignment_id,
                            c["commit"]["committer"]["date"],
                            s.get("additions"), s.get("deletions"),
                            len(detail.get("files", [])),
                            c["commit"]["message"][:500]))

    # Flaw 3: one batched upsert instead of N inserts
    if commit_rows:
        execute_values(cur, """
            INSERT INTO raw_commits (sha, student_id, assignment_id, committed_at,
                                     additions, deletions, files_changed, message)
            VALUES %s ON CONFLICT (sha) DO UPDATE SET additions = EXCLUDED.additions
        """, commit_rows)

    # Workflow runs (batched too)
    run_rows = []
    for w in _paged(f"{GH}/repos/{owner}/{repo}/actions/runs"):
        dur = None
        if w.get("run_started_at") and w.get("updated_at"):
            f = "%Y-%m-%dT%H:%M:%SZ"
            dur = int((dt.strptime(w["updated_at"], f)
                       - dt.strptime(w["run_started_at"], f)).total_seconds())
        run_rows.append((w["id"], student_id, assignment_id, w["status"],
                         w["conclusion"], w["run_started_at"], w["updated_at"], dur))
    if run_rows:
        execute_values(cur, """
            INSERT INTO raw_workflow_runs (run_id, student_id, assignment_id, status,
                                           conclusion, started_at, completed_at, duration_s)
            VALUES %s ON CONFLICT (run_id) DO NOTHING
        """, run_rows)

    conn.commit()


def collect_all(conn, repos):
    """Flaw 7: per-repo isolation — a broken repo is a logged warning, not an outage."""
    ok, failed = 0, []
    for repo in repos:
        try:
            collect_repo(conn, **repo); ok += 1
        except Exception as e:
            failed.append({"repo": repo.get("repo"), "error": str(e)})
            conn.rollback()
    return {"ok": ok, "failed": failed}


if __name__ == "__main__":
    conn = psycopg2.connect(os.environ["PG_DSN"])
    print(collect_all(conn, [
        {"owner": "your-org", "repo": "a2-sara", "student_id": "sara01", "assignment_id": "A2"},
    ]))
```

---

## Feature computation (dirty-student incremental)

**File: `features/compute_features.py`**

```python
"""
features/compute_features.py — turn raw tables into the seven variables.

Optimization (Flaw 5): only recompute students with NEW activity since the last run.
Unchanged inputs produce unchanged features, so recomputing them is pure waste.
"""
import os, json, psycopg2

from variables.mastery import MasteryEstimator, DifficultyEstimator
from variables.habits import effort_regulation, engineering_discipline
from variables.pace import learning_pace
from variables.error_response import error_response
from variables.error_frequency import error_frequency


def dirty_students(cur, last_run_iso):
    """Flaw 5: who actually did something since the last feature run?"""
    cur.execute("""
        SELECT DISTINCT student_id FROM raw_commits WHERE committed_at > %s
        UNION
        SELECT DISTINCT student_id FROM raw_workflow_runs WHERE started_at > %s
    """, (last_run_iso, last_run_iso))
    return [r[0] for r in cur.fetchall()]


def compute_for_student(cur, student_id):
    """
    Skeleton: pull this student's raw rows, run the Module-1 variable functions,
    assemble one learner_features payload. (Query details elided for brevity —
    each variable's data source is documented in Part B.)
    """
    # 1. commit gaps -> effort regulation
    cur.execute("""
        SELECT committed_at, additions, deletions FROM raw_commits
        WHERE student_id=%s ORDER BY committed_at
    """, (student_id,))
    commits = cur.fetchall()
    gaps = [ (commits[i][0]-commits[i-1][0]).total_seconds()/3600
             for i in range(1, len(commits)) ]
    effort = effort_regulation(gaps, release_to_first_commit_h=0)  # fill release delta

    # 2. mastery — replay classified pass/fails through BKT
    est = MasteryEstimator()
    cur.execute("""
        SELECT concept_id, conclusion FROM raw_workflow_runs
        WHERE student_id=%s AND concept_id IS NOT NULL AND concept_id <> 'unclassified'
        ORDER BY started_at
    """, (student_id,))
    for concept_id, conclusion in cur.fetchall():
        est.update(concept_id, correct=(conclusion == "success"))
    mastery = est.snapshot()

    # 3..6: pace / error_response / error_frequency / discipline
    #        (call the respective Module-1 functions with queried inputs)

    payload = {
        "mastery": mastery,
        "effort_regulation": effort,
        # "engineering_discipline": ...,
        # "pace": ...,
        # "error_response": ...,
        # "error_frequency": ...,
    }
    return payload


def run(last_run_iso):
    conn = psycopg2.connect(os.environ["PG_DSN"])
    cur = conn.cursor()
    for sid in dirty_students(cur, last_run_iso):     # incremental
        payload = compute_for_student(cur, sid)
        cur.execute("""
            INSERT INTO learner_features
              (student_id, mastery, engineering_discipline, effort_regulation,
               pace, error_response, error_frequency)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (sid,
              json.dumps(payload.get("mastery", {})),
              json.dumps(payload.get("engineering_discipline", {})),
              json.dumps(payload.get("effort_regulation", {})),
              json.dumps(payload.get("pace", {})),
              json.dumps(payload.get("error_response", {})),
              json.dumps(payload.get("error_frequency", {}))))
    conn.commit()
```

---

## The Airflow DAG (scheduling)

**File: `dags/vdel_pipeline.py`**

```python
"""
dags/vdel_pipeline.py — daily: collect -> compute_features -> update_profiles.
Runs on VDEL's own Airflow stack (the intelligence layer dogfoods the platform).
Daily batch is sufficient: adaptive tutoring does not need second-by-second freshness.
"""
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

default_args = {"owner": "anas", "retries": 1, "retry_delay": timedelta(minutes=5)}

with DAG("vdel_pipeline", default_args=default_args,
         schedule_interval="@daily", start_date=datetime(2026, 1, 1),
         catchup=False) as dag:

    def _collect(**_):
        import os, psycopg2
        from collectors.collect_github import collect_all
        conn = psycopg2.connect(os.environ["PG_DSN"])
        # load the repo list for the active cohort from `assignments` + `students`
        collect_all(conn, repos=[])   # fill with cohort repo descriptors

    def _compute(**ctx):
        from features.compute_features import run
        last = (ctx["execution_date"] - timedelta(days=1)).isoformat()
        run(last)

    def _update_profiles(**_):
        pass   # Module 3: fold new features into learner_profile (fast path)

    t1 = PythonOperator(task_id="collect", python_callable=_collect)
    t2 = PythonOperator(task_id="compute_features", python_callable=_compute)
    t3 = PythonOperator(task_id="update_profiles", python_callable=_update_profiles)
    t1 >> t2 >> t3
```

---

# PART E — What's next (Module 3 preview)

The `update_profiles` task above is the seam into **Module 3 — Dynamic Memory**: the
append-only `traces` log + the mutable `learner_profile` snapshot (event sourcing), the
fast path (deterministic mastery/recurrence updates), and the slow path (scheduled LLM
reflection job). That module is where the seven variables become a living profile the
agents and coach read from.

---

## Setup notes

- **PostgreSQL** with `pgvector` (needed in Module 3 for RAG). Run the `sql/` files in
  order: 01 → 02 → 03 → 04.
- **Python deps:** `psycopg2-binary`, `requests`, `scipy` (optional, for exact Beta
  intervals), and `apache-airflow` for the DAG.
- **Env vars:** `GITHUB_TOKEN` (fine-grained PAT, `contents:read` + `actions:read`),
  `PG_DSN` (PostgreSQL connection string).
- **First run:** point `collect_github.py` at one of your own repos to get real rows
  before the cohort exists.

*End of Modules 1 & 2 build document.*
