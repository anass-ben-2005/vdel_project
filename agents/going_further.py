"""agents/going_further.py -- the "Going further" section for a student whose code passes (D-109).

BUILT, DISABLED, AND POSTED BY NOTHING. This module can turn a stored Code Agent verdict into a
short, optional note for a student ("here is how your working code could be better"). Nothing in
this repository calls it: not the cycle, not the hourly task, not any script; a test pins that. It
exists so that, when the course author decides to switch it on, the part that must be careful is
already written and already tested.

Why it is locked, twice (config/judging.yaml, `post_review`):
  1. `enabled` is false. Turning it on is a decision, not a default.
  2. Even when `enabled` is true it refuses unless a REAL benchmark run on disk
     (`benchmark/results/<run>/summary.json`, written by `benchmark/run_real_benchmark.py`) reached
     `min_benchmark_agreement` exact agreement with the human labels, overall AND on `approach` AND
     on `readability` (the two things the section talks about). The Code Agent is an unmeasured
     judge on `weather_etl`; the one real run so far measured the PySpark files with the benchmark
     prompt, not the production prompt, with labels pre-written by an LLM and reviewed on 10 rows
     (D-102, D-104). The gate cannot repair that, it can only refuse to ignore it.

What the section is allowed to contain: the model's `feedback_for_student` text (at most 120 words
by its prompt), a heading and a line saying the checks, not this note, decide correctness. Never a
score, never the quotes, never the judge's opinion on correctness. It is refused (returns None)
when the verdict was rejected for a fabricated quote, when it holds a line of hidden test source, a
link, a claim that the code is (in)correct or a claim about mastery, or when there is nothing to
improve (approach and readability both 4).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from agents import feedback_agent as fa
from config import judging
from scripts import post_feedback as pf

REPO = Path(__file__).resolve().parent.parent
BENCHMARK_RESULTS = REPO / "benchmark" / "results"

# The criteria the section speaks about; the benchmark must agree with humans on both.
GATED_CRITERIA = ("approach", "readability")
MAX_WORDS = 120


class GoingFurtherRefused(RuntimeError):
    """The section is not allowed or cannot be produced; the message is the plain reason."""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    evidence: str | None = None  # the summary.json that satisfied the gate


def _exact(block: object) -> float | None:
    if isinstance(block, dict) and isinstance(block.get("exact"), (int, float)):
        return float(block["exact"])
    return None


def _agreements(summary: dict) -> dict[str, float | None]:
    agreement = summary.get("agreement") or {}
    out = {"overall": _exact((agreement.get("overall") or {}).get("with_non_applicable"))}
    for criterion in GATED_CRITERIA:
        out[criterion] = _exact(
            ((agreement.get("per_criterion") or {}).get(criterion) or {}).get("with_non_applicable")
        )
    return out


def check_gate(
    *, config: judging.PostReview | None = None, results_root: Path | str = BENCHMARK_RESULTS
) -> Decision:
    """May the section be produced? `Decision.allowed` is True only when `post_review.enabled` is
    true AND a benchmark result file meets the threshold. Reads files; writes nothing."""
    cfg = config if config is not None else judging.post_review()
    if not cfg.enabled:
        return Decision(False, "post_review.enabled is false in config/judging.yaml")
    root = Path(results_root)
    best: tuple[str, dict[str, float | None]] | None = None
    for summary_path in sorted(root.glob("*/summary.json"), reverse=True):
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        meta = summary.get("meta") or {}
        if meta.get("stopped_at_cap") or not meta.get("judge_runs_ok"):
            continue  # a partial or empty run proves nothing
        got = _agreements(summary)
        if all(v is not None and v >= cfg.min_benchmark_agreement for v in got.values()):
            return Decision(
                True, "a benchmark result meets min_benchmark_agreement", str(summary_path)
            )
        if best is None:
            best = (str(summary_path), got)
    if best is None:
        return Decision(
            False,
            f"post_review is enabled but there is no usable benchmark result "
            f"under {root}: it stays refused",
        )
    path, got = best
    shown = ", ".join(f"{k} {'n/a' if v is None else f'{v:.0%}'}" for k, v in got.items())
    return Decision(
        False,
        f"post_review is enabled but no benchmark result meets "
        f"min_benchmark_agreement {cfg.min_benchmark_agreement:.0%}: the newest "
        f"({path}) has {shown}",
    )


def require_allowed(**kw) -> Decision:
    """`check_gate`, raising `GoingFurtherRefused` with the reason when not allowed."""
    decision = check_gate(**kw)
    if not decision.allowed:
        raise GoingFurtherRefused(decision.reason)
    return decision


def _words(text: str) -> int:
    return len(text.split())


def build_section(
    payload: dict,
    *,
    hidden: frozenset[str] = frozenset(),
    decision: Decision | None = None,
    **gate_kw,
) -> str | None:
    """The markdown section for one stored verdict `payload`, or None when there is nothing safe or
    useful to say. Raises `GoingFurtherRefused` when the gate is closed (the default: it is)."""
    if decision is None:
        decision = require_allowed(**gate_kw)
    elif not decision.allowed:
        raise GoingFurtherRefused(decision.reason)
    if payload.get("rejected") or payload.get("flagged"):
        return None  # its quotes did not check out
    scores = payload.get("scores") or {}
    if all((scores.get(k) is None or scores.get(k) >= 4) for k in GATED_CRITERIA):
        return None  # nothing to improve
    text = " ".join(str(payload.get("feedback_for_student") or "").split())
    if not text or _words(text) > MAX_WORDS:
        return None
    if fa._URL.search(text) or fa._MASTERY_WORDS.search(text):
        return None
    if any(p.search(text) for p in fa._CORRECTNESS_PATTERNS):
        return None
    if re.search(r"\b[0-4]\s*(?:/|out of)\s*4\b", text):
        return None  # a score must never reach the student
    section = "\n".join(
        [
            "### Going further (optional, written by an AI assistant)",
            "",
            "Your code passes every check. A thought on how it could be even better:",
            "",
            text,
            "",
            "_This note is not a grade. The checks, not this note, decide whether your code is "
            "correct._",
            "",
        ]
    )
    try:
        pf.assert_no_hidden_source(section, hidden)
    except pf.HiddenSourceLeak:
        return None
    return pf.redact(section, hidden)
