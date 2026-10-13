"""scripts/roster_apply.py -- record a delivered repo in the roster, safely (D-105).

    python -m scripts.roster_apply --student X --assignment A --owner O --repo R
                                   [--github-username U --cohort C --released-at ISO]
                                   [--roster PATH] [--yes]

`scripts.deliver_next_attempt` never edits `config/roster.yaml` (D-090): a roster that still
points at the old repo means the next cycle does not see the new one, and that last step is a
person's. It prints the exact command for this script, which is the person's tool for that step:

  1. it computes the new roster text with the same editor `publish_repo` uses
     (`update_roster_text`: comments kept, line endings kept, idempotent, an existing row only has
     its `owner` and `repo` changed and its `released_at` never moved);
  2. it prints a unified diff;
  3. without `--yes` it stops there and exits 2 ("refused"): nothing is written;
  4. with `--yes` it first copies the roster to a timestamped backup next to it
     (`roster.yaml.<UTC time>.bak`, never overwritten), then replaces the file atomically.

It REFUSES (exit 2, nothing written) when the target is ambiguous, because a guess in a file that
decides what is collected and graded is worse than no edit: more than one row for the same
(student, assignment); the row's `owner:` or `repo:` line is missing or appears more than once; the
student appears twice; the file is not a block-style YAML list; a new row is needed but
`--released-at` (the real date the work began, it starts the Pace clock) was not given.

IT NEVER WRITES A TOKEN. It does not read `GITHUB_TOKEN` or `.env`, it makes no network call, and it
refuses any argument or resulting line that has the shape of a credential (`ghp_...`, `gho_...`,
`github_pat_...`, `sk-...`, `AIza...`, or a `token:` / `password:` key), so pasting one by mistake
cannot put it into the roster. It cannot recognise a secret with no known shape.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from scripts.publish_repo import ROSTER, PublishRefused, update_roster_text

EXIT_OK, EXIT_REFUSED = 0, 2

# Token SHAPES, with a minimum length: a bare "sk-" would match any repo called "...task-...".
_SECRET = re.compile(
    r"(?<![A-Za-z0-9])(gh[pousr]_[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}"
    r"|sk-[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{16,})"
    r"|^\s*(token|password|secret|api[_-]?key)\s*:",
    re.I | re.M,
)
_KEY_LINE = {
    "owner": re.compile(r"^\s*(?:-\s+)?owner\s*:"),
    "repo": re.compile(r"^\s*(?:-\s+)?repo\s*:"),
}


class Ambiguous(PublishRefused):
    """The edit cannot be made without guessing which line is meant."""


def _items_of(text: str, key: str) -> list[list[str]]:
    """The raw lines of each top-level list item under `key:`, in file order."""
    lines = text.replace("\r\n", "\n").split("\n")
    items: list[list[str]] = []
    inside, base = False, None
    for line in lines:
        if re.match(r"^[A-Za-z_][\w-]*:", line):
            inside = line.startswith(f"{key}:")
            base = None
            continue
        if not inside:
            continue
        m = re.match(r"^(\s*)-\s", line)
        if m and (base is None or m.group(1) == base):
            base = m.group(1)
            items.append([line])
        elif items:
            items[-1].append(line)
    return items


def check_unambiguous(text: str, student: str, assignment: str) -> None:
    """Refuse when more than one line could be the target. Raises `Ambiguous`."""
    try:
        parsed = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise Ambiguous(f"the roster does not parse as YAML: {str(exc).splitlines()[0]}") from None
    for section in ("students", "assignments"):
        if section in parsed and not isinstance(parsed[section], list):
            raise Ambiguous(f"`{section}:` is not a block list; this tool edits block lists only")
    students = [s for s in parsed.get("students") or [] if s.get("student_id") == student]
    if len(students) > 1:
        raise Ambiguous(f"student {student!r} appears {len(students)} times in `students:`")
    rows = [
        a
        for a in parsed.get("assignments") or []
        if a.get("student_id") == student and a.get("assignment_id") == assignment
    ]
    if len(rows) > 1:
        raise Ambiguous(f"{len(rows)} rows for ({student}, {assignment}): which one is meant?")
    if rows:
        for item in _items_of(text, "assignments"):
            body = "\n".join(item)
            d = (yaml.safe_load(body) or [{}])[0]
            if d.get("student_id") != student or d.get("assignment_id") != assignment:
                continue
            for key, pattern in _KEY_LINE.items():
                n = sum(1 for ln in item if pattern.match(ln))
                if n != 1:
                    raise Ambiguous(
                        f"the row for ({student}, {assignment}) has {n} `{key}:` "
                        "line(s); exactly one is needed to edit it"
                    )


def refuse_credentials(*values: str) -> None:
    for v in values:
        if v and _SECRET.search(v):
            raise Ambiguous(
                "an argument or a resulting line looks like a credential; the roster "
                "never holds one, so nothing was written"
            )


def plan_edit(
    text: str,
    *,
    student: str,
    assignment: str,
    owner: str,
    repo: str,
    github_username: str | None,
    cohort: str,
    released_at: str | None,
) -> tuple[str, list[str]]:
    """(new text, actions), or `Ambiguous` / `PublishRefused`. Pure: touches no file."""
    refuse_credentials(
        student, assignment, owner, repo, github_username or "", cohort, released_at or ""
    )
    check_unambiguous(text, student, assignment)
    parsed = yaml.safe_load(text) or {}
    have_row = any(
        a.get("student_id") == student and a.get("assignment_id") == assignment
        for a in parsed.get("assignments") or []
    )
    have_student = any(s.get("student_id") == student for s in parsed.get("students") or [])
    if not have_row and not released_at:
        raise Ambiguous(
            f"there is no row for ({student}, {assignment}) yet and --released-at (the "
            "real date the work began; it starts the Pace clock) was not given"
        )
    if not have_student and not github_username:
        raise Ambiguous(
            f"student {student!r} is not in the roster and --github-username was not given"
        )
    concepts: list[str] = []
    new_text, actions = update_roster_text(
        text,
        student={"student_id": student, "github_username": github_username or "", "cohort": cohort},
        rows=[
            {
                "assignment_id": assignment,
                "owner": owner,
                "repo": repo,
                "student_id": student,
                "released_at": released_at or "",
                "concepts": concepts,
            }
        ],
    )
    added = [
        ln
        for ln in difflib.unified_diff(text.splitlines(), new_text.splitlines(), lineterm="", n=0)
        if ln.startswith("+")
    ]
    refuse_credentials("\n".join(added))
    return new_text, actions


def unified_diff(old: str, new: str, name: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), f"{name} (before)", f"{name} (after)", lineterm=""
        )
    )


def backup_path(path: Path, now: datetime) -> Path:
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    candidate = path.with_name(f"{path.name}.{stamp}.bak")
    n = 1
    while candidate.exists():  # never overwrite an earlier backup
        n += 1
        candidate = path.with_name(f"{path.name}.{stamp}-{n}.bak")
    return candidate


def apply(path: Path, new_text: str, now: datetime) -> Path:
    """Back the roster up, then replace it atomically. Returns the backup path."""
    backup = backup_path(path, now)
    backup.write_bytes(path.read_bytes())
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(new_text.encode("utf-8"))
    os.replace(tmp, path)
    return backup


def run(
    *,
    student: str,
    assignment: str,
    owner: str,
    repo: str,
    roster_path: Path = ROSTER,
    github_username: str | None = None,
    cohort: str = "vdel-2026",
    released_at: str | None = None,
    yes: bool = False,
    now: datetime | None = None,
    out=print,
) -> int:
    path = Path(roster_path)
    if not path.exists():
        out(f"REFUSED: {path} not found")
        return EXIT_REFUSED
    text = path.read_bytes().decode("utf-8")
    try:
        new_text, actions = plan_edit(
            text,
            student=student,
            assignment=assignment,
            owner=owner,
            repo=repo,
            github_username=github_username,
            cohort=cohort,
            released_at=released_at,
        )
    except PublishRefused as exc:
        out(f"REFUSED: {exc}")
        return EXIT_REFUSED
    if new_text == text:
        out(f"{path.name}: already up to date, nothing to change")
        return EXIT_OK
    out("; ".join(actions) or "edit")
    out(unified_diff(text, new_text, path.name))
    if not yes:
        out(
            f"\nREFUSED: --yes was not given, so nothing was written. Add --yes to apply the diff "
            f"above to {path.name}."
        )
        return EXIT_REFUSED
    backup = apply(path, new_text, now or datetime.now(UTC))
    out(f"\nwrote {path.name}; the previous version is {backup.name}")
    return EXIT_OK


def main(argv: list[str] | None = None, out=print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--student", required=True)
    ap.add_argument("--assignment", required=True)
    ap.add_argument("--owner", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument(
        "--roster", type=Path, default=ROSTER, help="roster file (default config/roster.yaml)"
    )
    ap.add_argument(
        "--github-username", default=None, help="only for a student not yet in the roster"
    )
    ap.add_argument("--cohort", default="vdel-2026")
    ap.add_argument(
        "--released-at",
        default=None,
        help="only for a NEW row: the real date the work began (ISO 8601)",
    )
    ap.add_argument("--yes", action="store_true", help="really write (a backup is made first)")
    args = ap.parse_args(argv)
    return run(
        student=args.student,
        assignment=args.assignment,
        owner=args.owner,
        repo=args.repo,
        roster_path=args.roster,
        github_username=args.github_username,
        cohort=args.cohort,
        released_at=args.released_at,
        yes=args.yes,
        out=out,
    )


if __name__ == "__main__":
    sys.exit(main())
