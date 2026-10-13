"""Shared by config/checks.py and config/judging.py: the two draft-ignoring YAML loaders (D-107).

One home for the two things they agree on, so the rule cannot drift between them:
  - the statuses an entry may carry, and what "reviewed" means -- only a reviewed entry ever
    reaches a prompt or a student; a draft is kept but ignored;
  - reading a versioned file (`version: 1`), failing loudly with the caller's own error type.
"""

from __future__ import annotations

from pathlib import Path

import yaml

STATUSES = ("draft", "reviewed")


def is_reviewed(status: object) -> bool:
    """The draft-ignoring rule: True only for a reviewed entry."""
    return status == "reviewed"


def read_versioned(path: str, label: str, error: type[Exception]) -> dict:
    """The parsed YAML mapping at `path`; raises `error` unless it says `version: 1`."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if data.get("version") != 1:
        raise error(f"{label}: version must be 1")
    return data
