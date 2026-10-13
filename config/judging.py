"""Load and validate config/judging.yaml: which criteria apply to which assignment (D-103).

Fails loudly on a malformed file, like `config/concepts.py`: an unknown criterion name would
otherwise mean a criterion silently never asked.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

JUDGING_PATH = Path(__file__).resolve().parent / "judging.yaml"

# The rubric's four criteria, in order. Duplicated from agents/prompts.py on purpose (config/ does
# not import agents/); a test asserts the two lists are equal.
ALL_CRITERIA = ("correctness", "approach", "readability", "idiomatic")


class JudgingError(ValueError):
    """config/judging.yaml is malformed. Never recoverable at runtime -- fix the YAML."""


@dataclass(frozen=True)
class Judging:
    assignment_id: str | None       # None for the default
    criteria: tuple[str, ...]
    note: str
    statement: str | None           # a REVIEWED assignment-level description, or None
    # D-107. A statement written as {text, status: draft} is kept here and nowhere else: `statement`
    # stays None, so `compose_task` and every prompt behave as if it did not exist.
    statement_status: str | None = None          # "draft" | "reviewed" | None
    draft_statement: str | None = None


def _criteria(raw: object, where: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw:
        raise JudgingError(f"{where}: criteria must be a non-empty list")
    unknown = [c for c in raw if c not in ALL_CRITERIA]
    if unknown:
        raise JudgingError(f"{where}: unknown criterion {unknown}; allowed: {list(ALL_CRITERIA)}")
    if len(set(raw)) != len(raw):
        raise JudgingError(f"{where}: a criterion is listed twice")
    return tuple(c for c in ALL_CRITERIA if c in raw)         # canonical order


STATEMENT_STATUSES = ("draft", "reviewed")


def _statement(raw: object, where: str) -> tuple[str | None, str | None, str | None]:
    """(reviewed text, status, draft text). `null` -> nothing; a plain string -> reviewed (the form
    that existed before D-107); `{text, status}` -> reviewed text only when status is `reviewed`."""
    if raw is None:
        return None, None, None
    if isinstance(raw, str):
        if not raw.strip():
            raise JudgingError(f"{where}: statement must be null or a non-empty string")
        return raw.strip(), "reviewed", None
    if not isinstance(raw, dict) or set(raw) != {"text", "status"}:
        raise JudgingError(f"{where}: statement must be null, a string or {{text, status}}")
    text, status = raw["text"], raw["status"]
    if not (isinstance(text, str) and text.strip()):
        raise JudgingError(f"{where}: statement text must be a non-empty string")
    if status not in STATEMENT_STATUSES:
        raise JudgingError(f"{where}: statement status must be one of {list(STATEMENT_STATUSES)}")
    return (text.strip(), status, None) if status == "reviewed" else (None, status, text.strip())


def _entry(raw: object, assignment_id: str | None, fallback: Judging | None) -> Judging:
    where = f"assignment {assignment_id!r}" if assignment_id else "default"
    if not isinstance(raw, dict):
        raise JudgingError(f"{where}: expected a mapping")
    criteria = (_criteria(raw["criteria"], where) if "criteria" in raw
                else (fallback.criteria if fallback else ALL_CRITERIA))
    statement, status, draft = _statement(raw.get("statement"), where)
    note = str(raw.get("note") or "").strip()
    return Judging(assignment_id, criteria, note, statement, status, draft)


@lru_cache(maxsize=1)
def _load(path: str) -> tuple[Judging, dict[str, Judging]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if data.get("version") != 1:
        raise JudgingError("judging.yaml: version must be 1")
    default = _entry(data.get("default") or {}, None, None)
    assignments = {aid: _entry(raw, aid, default)
                   for aid, raw in (data.get("assignments") or {}).items()}
    return default, assignments


def load(path: Path | str = JUDGING_PATH) -> tuple[Judging, dict[str, Judging]]:
    """`(default, {assignment_id: Judging})`, parsed, validated and cached."""
    return _load(str(path))


def for_assignment(assignment_id: str, path: Path | str = JUDGING_PATH) -> Judging:
    """The judging config of one assignment, or the default when it has none."""
    default, assignments = load(path)
    return assignments.get(assignment_id, default)


def compose_task(statement: str | None, instructions: list[str]) -> str:
    """The task text: the assignment's statement (if any), then the gap instructions, which the
    caller passes already in file order."""
    body = " ".join(instructions)
    return f"{statement}\n\n{body}".strip() if statement else body
