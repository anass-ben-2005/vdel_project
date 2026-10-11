"""scripts/post_feedback.py -- feedback v0 (no LLM) for graded commits. DRY-RUN ONLY in v1.

    python -m scripts.post_feedback --student X [--assignment Y] [--commit SHA] [--dry-run]

For every graded commit it builds a short markdown message from `assessment/diagnose.py` (the
weakest concept, the recurrence flags) and from that commit's own `test_results` rows (which
checks failed, by test name and exception type only; a collection error, a timeout or a
tooling problem explained in plain words). No LLM, no network, no database write.

WHAT IT MUST NEVER SHOW (enforced in code, tested): hidden test CODE, or what a hidden test
EXPECTS. A failing `assert 32.0 == f(0)` states the expected value, so the stored assertion
message is NOT shown by default (D-077): a failing check is reported as its test name plus the
exception type (`AssertionError`, `ConnectionError`, `NotImplementedError`). The message is shown
only for a test the author has explicitly marked safe, by listing its function name in a
module-level `FEEDBACK_SAFE_TESTS = ("test_name", ...)` in the hidden test file (read with `ast`,
the hidden file is never imported). Nothing is marked safe today. Besides that:
  - a message that IS shown is reduced to its first line and capped, so a pytest "where ..."
    expansion or a traceback with source lines never gets through;
  - every line of every hidden test file of the project (>= 12 characters once stripped) is
    redacted from any text before it is used, and
  - the finished message is checked a last time (`assert_no_hidden_source`): if any hidden line
    is still in it, nothing is produced and `HiddenSourceLeak` is raised.

IDEMPOTENCE: a `feedback_posts` row per (attempt, commit, channel) is the "already posted"
marker (sql/07, written but not applied to the real database; a missing table is read as "no
markers yet"). Nothing writes it in v1.

POSTING: only `--dry-run` is implemented. `post_comment` is the real GitHub call and refuses
unless BOTH `enabled=True` is passed AND the environment variable `VDEL_ALLOW_FEEDBACK_POST=1`
is set; the CLI never passes `enabled=True` without `--post`, and no test calls it.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from assessment.diagnose import diagnose
from system import db

CURRICULUM_ROOT = Path(__file__).resolve().parent.parent / "curriculum" / "master"
# MIN_REDACT_LEN and MAX_MESSAGE_CHARS are design choices, not measurements: no source or
# experiment backs the values; change them if a real message shows they are wrong.
MIN_REDACT_LEN = 12          # shorter lines ("return None") are too generic to mean "leaked code"
MAX_MESSAGE_CHARS = 200
POST_ENV_VAR = "VDEL_ALLOW_FEEDBACK_POST"


class HiddenSourceLeak(RuntimeError):
    """A hidden test's source line was about to reach a student. Nothing is produced."""


class FeedbackPostingNotEnabled(RuntimeError):
    """The real GitHub POST was called without the flag AND the environment variable."""


# --- hidden-source guard ----------------------------------------------------------------------

def hidden_source_lines(project_id: str) -> frozenset[str]:
    """Every stripped line (>= MIN_REDACT_LEN) of every hidden test file of the project."""
    folder = CURRICULUM_ROOT / project_id / "tests" / "hidden"
    lines: set[str] = set()
    if folder.is_dir():
        for path in sorted(folder.glob("*.py")):
            for raw in path.read_text(encoding="utf-8").splitlines():
                stripped = raw.strip()
                if len(stripped) >= MIN_REDACT_LEN:
                    lines.add(stripped)
    return frozenset(lines)


def redact(text: str, hidden: frozenset[str]) -> str:
    """Replace any hidden source line found inside `text` (longest first)."""
    for line in sorted(hidden, key=len, reverse=True):
        if line in text:
            text = text.replace(line, "[removed]")
    return text


def assert_no_hidden_source(text: str, hidden: frozenset[str]) -> None:
    for line in hidden:
        if line in text:
            raise HiddenSourceLeak(f"a hidden test line is in the feedback: {line[:60]!r}")


# --- building the text ------------------------------------------------------------------------

_EXC_PREFIX = re.compile(r"^(?:\w+\.)*AssertionError:\s*")


def clean_message(message: str | None, hidden: frozenset[str]) -> str:
    """The assertion message of one failing check, safe to show: first non-empty line,
    redacted, no `AssertionError:` prefix, capped."""
    if not message:
        return ""
    first = next((ln.strip() for ln in message.splitlines() if ln.strip()), "")
    first = _EXC_PREFIX.sub("", redact(first, hidden))
    return first[:MAX_MESSAGE_CHARS] + ("..." if len(first) > MAX_MESSAGE_CHARS else "")


_EXC_TYPE = re.compile(r"^((?:\w+\.)*\w*(?:Error|Exception|Exit|Interrupt))\b")


def exception_type(message: str | None) -> str | None:
    """The exception class of a stored failure message, or None when it cannot be told.

    pytest's junit `message` is `Type: text` for most exceptions, a bare `Type` when there is no
    text (`NotImplementedError`), a dotted name for a library exception
    (`requests.exceptions.ConnectionError`), and `assert <expr>` for a failed assert (pytest
    drops the `AssertionError: ` prefix). Only the class name is returned, never the text."""
    first = next((ln.strip() for ln in (message or "").splitlines() if ln.strip()), "")
    found = _EXC_TYPE.match(first)
    if found:
        return found.group(1).rsplit(".", 1)[-1]
    if first.startswith("assert"):
        return "AssertionError"
    return None


def feedback_safe_tests(project_id: str) -> frozenset[str]:
    """Function names the author marked safe to show an assertion message for: the strings of a
    module-level `FEEDBACK_SAFE_TESTS = (...)` in any hidden test file of the project. Read with
    `ast.literal_eval` -- the hidden file is parsed, never imported or executed. Anything that
    is not a literal collection of strings marks nothing safe."""
    folder = CURRICULUM_ROOT / project_id / "tests" / "hidden"
    safe: set[str] = set()
    if not folder.is_dir():
        return frozenset()
    for path in sorted(folder.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "FEEDBACK_SAFE_TESTS"):
                try:
                    value = ast.literal_eval(node.value)
                except ValueError:
                    continue
                if isinstance(value, (list, tuple, set, frozenset)):
                    safe.update(v for v in value if isinstance(v, str))
    return frozenset(safe)


def short_test_name(test_name: str) -> str:
    """`tests/hidden/test_extract.py::test_x` -> `test_x (test_extract.py)`: the name only."""
    path, _, name = test_name.rpartition("::")
    return f"{name} ({Path(path).name})" if path else name


@dataclass(frozen=True)
class Feedback:
    attempt_id: int
    commit_sha: str
    markdown: str
    passed: int
    total: int
    status: str            # ok | collection_error | timeout | tooling


def _commit_rows(cur, attempt_id: int, commit_sha: str):
    cur.execute(
        "SELECT test_name, passed, message, gap_id, status FROM test_results"
        " WHERE attempt_id = %s AND commit_sha = %s ORDER BY test_name",
        (attempt_id, commit_sha))
    return cur.fetchall()


def build_feedback(cur, attempt_id: int, commit_sha: str) -> Feedback:
    """The message for ONE graded commit. Deterministic; reads only."""
    cur.execute("SELECT student_id, assignment_id, project_id, attempt_no FROM attempts"
                " WHERE attempt_id = %s", (attempt_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no attempt {attempt_id}")
    _student_id, assignment_id, project_id, attempt_no = row
    rows = _commit_rows(cur, attempt_id, commit_sha)
    if not rows:
        raise ValueError(f"commit {commit_sha[:10]} has no graded results for attempt "
                         f"{attempt_id}")
    hidden = hidden_source_lines(project_id)
    safe = feedback_safe_tests(project_id)
    diagnosis = diagnose(cur, attempt_id)

    statuses = {r[4] for r in rows}
    status = ("tooling" if statuses == {"tooling"}
              else "collection_error" if "collection_error" in statuses
              else "timeout" if "timeout" in statuses else "ok")
    checks = [r for r in rows if r[4] != "tooling"]
    passed = sum(1 for r in checks if r[1])
    total = len(checks)

    out = [f"### VDEL feedback: `{assignment_id}`, attempt {attempt_no}, commit "
           f"`{commit_sha[:7]}`", ""]
    if status == "tooling":
        out.append("The checks for this commit could not run because of a problem on our side. "
                   "It does **not** count against you; nothing has changed in your results.")
    else:
        out.append(f"**{passed} of {total}** checks passed"
                   + (" - all done for this file." if total and passed == total else "."))
    if status == "collection_error":
        detail = next((clean_message(r[2], hidden) for r in checks if r[2]), "")
        detail = detail.removeprefix("collection error: ")
        out += ["", "**Your file could not be loaded**, so none of its checks could run"
                + (f" ({detail})." if detail else ".")
                + " Fix that first; it is not counted as a wrong answer to the exercise."]
    elif status == "timeout":
        out += ["", "**The checks did not finish in time.** A loop that never ends, or a call "
                    "that waits forever, is the usual cause. Nothing was scored for this push."]

    failing = [r for r in checks if not r[1]]
    if failing and status == "ok":
        out += ["", "Checks that failed on this commit:"]
        for test_name, _, message, _, _ in failing:
            kind = exception_type(message) or "check failed"
            line = f"- `{short_test_name(test_name)}`: {kind}"
            if test_name.rpartition("::")[2] in safe:       # explicitly marked safe, else never
                note = clean_message(message, hidden)
                if note and note != kind:
                    line += f" ({note})"
            out.append(line)

    # History (recurrence, weakest concept) only when THIS commit has real failing checks: a
    # passing commit gets no "keeps failing", and a load error / timeout is not a wrong answer,
    # so it is not added to the student's pattern of mistakes (found on the first dry-run).
    if failing and status == "ok":
        recurring = sorted(g for g, flag in diagnosis.recurrence_flags.items() if flag)
        if recurring:
            out += ["", "Keeps failing across several pushes: "
                    + ", ".join(f"`{g}`" for g in recurring) + "."]
        if diagnosis.weakest_concept:
            out += ["", f"Concept to practise next: `{diagnosis.weakest_concept}`."]

    markdown = "\n".join(out) + "\n"
    markdown = redact(markdown, hidden)
    assert_no_hidden_source(markdown, hidden)
    return Feedback(attempt_id, commit_sha, markdown, passed, total, status)


# --- idempotency marker + (disabled) posting --------------------------------------------------

def already_posted(cur, attempt_id: int, commit_sha: str,
                   channel: str = "github_commit_comment") -> bool:
    cur.execute("SELECT to_regclass('public.feedback_posts') IS NOT NULL")
    if not cur.fetchone()[0]:
        return False                      # the migration is not applied: no marker can exist
    cur.execute("SELECT 1 FROM feedback_posts WHERE attempt_id=%s AND commit_sha=%s"
                " AND channel=%s", (attempt_id, commit_sha, channel))
    return cur.fetchone() is not None


def require_enabled(enabled: bool) -> None:
    """The gate: BOTH the explicit flag and the environment variable, or it raises."""
    if not (enabled and os.environ.get(POST_ENV_VAR) == "1"):
        raise FeedbackPostingNotEnabled(
            f"posting feedback is not enabled: pass enabled=True (CLI: --post) AND set "
            f"{POST_ENV_VAR}=1. v1 implements --dry-run only.")


def post_comment(owner: str, repo: str, commit_sha: str, body: str, *,
                 enabled: bool = False) -> str:
    """The REAL GitHub write (a commit comment). Refuses unless `enabled=True` AND the
    environment variable VDEL_ALLOW_FEEDBACK_POST=1 are both present. Not called by any test
    and not by the dry-run path. Returns the comment's URL."""
    require_enabled(enabled)
    import requests  # local: the dry-run path needs no HTTP

    token = os.environ["GITHUB_TOKEN"]
    response = requests.post(
        f"https://api.github.com/repos/{owner}/{repo}/commits/{commit_sha}/comments",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"body": body}, timeout=30)
    response.raise_for_status()
    return response.json().get("html_url", "")


# --- the command ------------------------------------------------------------------------------

def graded_commits(cur, student_id: str, assignment_id: str | None = None,
                   commit: str | None = None) -> list[tuple[int, str]]:
    """(attempt_id, commit_sha) for every graded commit, oldest first."""
    query = ("SELECT DISTINCT t.attempt_id, t.commit_sha, c.committed_at FROM test_results t"
             " JOIN attempts a USING (attempt_id) JOIN raw_commits c ON c.sha = t.commit_sha"
             " WHERE a.student_id = %s AND t.commit_sha IS NOT NULL")
    args: list = [student_id]
    if assignment_id:
        query += " AND a.assignment_id = %s"
        args.append(assignment_id)
    if commit:
        query += " AND t.commit_sha LIKE %s"
        args.append(commit + "%")
    cur.execute(query + " ORDER BY c.committed_at, t.commit_sha", args)
    return [(a, s) for a, s, _ in cur.fetchall()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--student", required=True)
    parser.add_argument("--assignment")
    parser.add_argument("--commit", help="a commit sha or prefix")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the feedback; send nothing (the default and the only "
                             "implemented mode)")
    parser.add_argument("--post", action="store_true",
                        help="really post (refuses unless VDEL_ALLOW_FEEDBACK_POST=1; v1: no)")
    args = parser.parse_args(argv)
    if args.post:
        require_enabled(True)          # raises FeedbackPostingNotEnabled unless the env var is set
        print("--post: the posting loop is not wired into the CLI in v1; use --dry-run")
        return 2

    conn = db._open()
    try:
        cur = conn.cursor()
        todo = graded_commits(cur, args.student, args.assignment, args.commit)
        if not todo:
            print(f"no graded commits for {args.student}")
            return 0
        for attempt_id, sha in todo:
            print("=" * 78)
            if already_posted(cur, attempt_id, sha):
                print(f"attempt {attempt_id} commit {sha[:10]}: ALREADY POSTED, skipped")
                continue
            print(f"[DRY-RUN] would post to commit {sha[:10]} (attempt {attempt_id}):\n")
            print(build_feedback(cur, attempt_id, sha).markdown)
    finally:
        conn.rollback()
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
