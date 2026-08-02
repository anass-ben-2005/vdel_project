"""Engineering discipline (V2) and effort regulation (V3)."""

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime
import statistics


@dataclass
class DisciplineState:
    """Engineering discipline: code quality per LOC."""
    ruff_issues_per_100_loc: float = 0.0  # Lower = better
    tests_present: bool = False
    tests_passing: bool = False
    n: int = 0


@dataclass
class EffortState:
    """Effort regulation: burstiness and gap patterns."""
    mean_gap_hours: float = 0.0     # Average time between commits
    gap_stddev_hours: float = 0.0   # Variance (burstiness)
    max_gap_hours: float = 0.0      # Longest single gap
    burstiness_ratio: float = 0.0   # stddev / mean (higher = more bursty)
    n: int = 0


def compute_discipline(
    commit_messages: List[str],
    files_modified: int,
    code_lines: int,
    linter_violations: int,
    tests_exist: bool,
    tests_passing: bool,
) -> DisciplineState:
    """
    Compute engineering discipline (V2).

    Based on: ruff/sqlfluff violations per 100 LOC, test presence.

    Args:
        commit_messages: List of commit messages (for coherence check)
        files_modified: Number of files changed
        code_lines: Total lines of code
        linter_violations: Number of ruff/sqlfluff issues
        tests_exist: Whether tests exist
        tests_passing: Whether tests pass

    Returns:
        DisciplineState
    """
    # Normalize: violations per 100 LOC
    if code_lines > 0:
        violations_per_100 = (linter_violations / code_lines) * 100
    else:
        violations_per_100 = 0

    return DisciplineState(
        ruff_issues_per_100_loc=violations_per_100,
        tests_present=tests_exist,
        tests_passing=tests_passing,
        n=len(commit_messages),
    )


def compute_effort(commit_timestamps: List[datetime]) -> EffortState:
    """
    Compute effort regulation (V3).

    Based on: inter-commit gap variance (burstiness indicator).
    High variance = bursty work (procrastination + cramming).
    Low variance = steady pace.

    Args:
        commit_timestamps: Sorted list of commit timestamps

    Returns:
        EffortState
    """
    if len(commit_timestamps) < 2:
        return EffortState(n=len(commit_timestamps))

    # Compute inter-commit gaps in hours
    gaps = []
    for i in range(1, len(commit_timestamps)):
        delta = (commit_timestamps[i] - commit_timestamps[i-1]).total_seconds() / 3600
        gaps.append(delta)

    if not gaps:
        return EffortState(n=len(commit_timestamps))

    mean_gap = statistics.mean(gaps)
    stddev_gap = statistics.stdev(gaps) if len(gaps) > 1 else 0
    max_gap = max(gaps)

    # Burstiness ratio: stddev / mean (normalized)
    burstiness = stddev_gap / (mean_gap + 1e-6)  # +epsilon to avoid division by zero

    return EffortState(
        mean_gap_hours=mean_gap,
        gap_stddev_hours=stddev_gap,
        max_gap_hours=max_gap,
        burstiness_ratio=burstiness,
        n=len(commit_timestamps),
    )


def discipline_score(state: DisciplineState) -> float:
    """
    Aggregate discipline into [0, 1] score (higher = better).

    Rules:
    - Low linter violations: ~40% weight
    - Tests present: ~30% weight
    - Tests passing: ~30% weight
    """
    # Linter component: penalize violations
    linter_score = max(0, 1 - state.ruff_issues_per_100_loc / 20)

    # Test presence: binary
    test_present_score = 1.0 if state.tests_present else 0.0

    # Test passing: binary, only counts if tests exist
    test_pass_score = 1.0 if (state.tests_present and state.tests_passing) else 0.0

    # Weighted aggregate
    return 0.4 * linter_score + 0.3 * test_present_score + 0.3 * test_pass_score


def effort_score(state: EffortState) -> float:
    """
    Aggregate effort regulation into [0, 1] score (higher = better).

    Rules:
    - Low burstiness: steady work = better
    - No extreme gaps: avoid cramming patterns
    """
    if state.n < 2:
        return 0.5  # Neutral if insufficient data

    # Penalize high burstiness (cramming indicator)
    burstiness_score = max(0, 1 - state.burstiness_ratio / 3)

    # Penalize extreme gaps (weeks of silence)
    gap_score = max(0, 1 - state.max_gap_hours / (7 * 24))  # 7 days = threshold

    return 0.6 * burstiness_score + 0.4 * gap_score
