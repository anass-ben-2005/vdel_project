"""Load config/checks.yaml: the public description of each hidden test (D-107).

THE RULE THIS FILE EXISTS FOR: a `draft` entry reaches nothing. `description_for` and `entries`
return only entries whose status is `reviewed`; a draft is invisible to every caller that does not
ask for it by name (`entries(..., include_drafts=True)`, which only the validator and the tests
use). The drafts in the shipped file were written by an assistant from the hidden tests and have not
been read by the course author, so they must not be put in a prompt or shown to a student until a
person changes the status. Same rule for the task `statement` in config/judging.yaml.

Fails loudly on a malformed file, like config/concepts.py and config/judging.py: a description that
was silently dropped would mean feedback that quietly says less than the author wrote.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

CHECKS_PATH = Path(__file__).resolve().parent / "checks.yaml"
STATUSES = ("draft", "reviewed")
MAX_DESCRIPTION_CHARS = 400

# The stored form of a hidden test's name (assessment/test_runner.py::_normalise_test_name).
_TEST_NAME = re.compile(r"^tests/hidden/[A-Za-z0-9_]+\.py::[A-Za-z0-9_:]+$")
# A description is prose about behaviour. These shapes mean test code or a code block leaked in.
_CODE_SHAPES = (
    (re.compile(r"```"), "a code fence"),
    (re.compile(r"(^|\s)assert\s"), "an `assert` statement"),
    (re.compile(r"==|!=|\bdef\s|\blambda\b|\bpytest\."), "test code"),
)


class ChecksError(ValueError):
    """config/checks.yaml is malformed. Never recoverable at runtime -- fix the YAML."""


@dataclass(frozen=True)
class Check:
    assignment_id: str
    test: str  # tests/hidden/<file>.py::<test>
    gap: str
    description: str
    status: str  # "draft" | "reviewed"

    @property
    def reviewed(self) -> bool:
        return self.status == "reviewed"


def description_problems(text: object) -> list[str]:
    """Why a description is not acceptable prose, or []. Shared with the validator."""
    if not isinstance(text, str) or not text.strip():
        return ["description must be a non-empty string"]
    problems = []
    if len(text.strip()) > MAX_DESCRIPTION_CHARS:
        problems.append(f"description is longer than {MAX_DESCRIPTION_CHARS} characters")
    for pattern, what in _CODE_SHAPES:
        if pattern.search(text):
            problems.append(f"description contains {what}; describe the behaviour in words")
    return problems


def _entry(assignment_id: str, raw: object) -> Check:
    where = f"assignment {assignment_id!r}"
    if not isinstance(raw, dict):
        raise ChecksError(f"{where}: each check must be a mapping")
    unknown = set(raw) - {"test", "gap", "description", "status"}
    if unknown:
        raise ChecksError(f"{where}: unknown key(s) {sorted(unknown)}")
    test, gap, status = raw.get("test"), raw.get("gap"), raw.get("status")
    if not isinstance(test, str) or not _TEST_NAME.match(test):
        raise ChecksError(f"{where}: test {test!r} must look like tests/hidden/<file>.py::<test>")
    where = f"{where}, {test}"
    if not isinstance(gap, str) or not gap.strip():
        raise ChecksError(f"{where}: gap is required")
    if status not in STATUSES:
        raise ChecksError(f"{where}: status must be one of {list(STATUSES)}, got {status!r}")
    problems = description_problems(raw.get("description"))
    if problems:
        raise ChecksError(f"{where}: {problems[0]}")
    return Check(assignment_id, test, gap.strip(), " ".join(raw["description"].split()), status)


@lru_cache(maxsize=1)
def _load(path: str) -> dict[str, tuple[Check, ...]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if data.get("version") != 1:
        raise ChecksError("checks.yaml: version must be 1")
    out: dict[str, tuple[Check, ...]] = {}
    for assignment_id, rows in (data.get("assignments") or {}).items():
        if not isinstance(rows, list):
            raise ChecksError(f"assignment {assignment_id!r}: expected a list of checks")
        checks = tuple(_entry(assignment_id, raw) for raw in rows)
        names = [c.test for c in checks]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            raise ChecksError(f"assignment {assignment_id!r}: test listed twice: {dup[0]}")
        out[assignment_id] = checks
    return out


def entries(
    assignment_id: str | None = None,
    *,
    include_drafts: bool = False,
    path: Path | str = CHECKS_PATH,
) -> list[Check]:
    """The checks of one assignment (or of all), reviewed ones only unless `include_drafts`.

    Asking for drafts is for the validator and tests. Nothing that builds a prompt or a
    student-facing text may pass `include_drafts=True`."""
    loaded = _load(str(path))
    pool = (
        loaded.get(assignment_id, ())
        if assignment_id is not None
        else [c for rows in loaded.values() for c in rows]
    )
    return [c for c in pool if include_drafts or c.reviewed]


def description_for(assignment_id: str, test: str, path: Path | str = CHECKS_PATH) -> str | None:
    """The reviewed public description of one test, or None -- also None for a draft."""
    for check in entries(assignment_id, path=path):
        if check.test == test:
            return check.description
    return None
