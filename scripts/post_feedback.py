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
marker (sql/07, applied to the real database; a missing table is read as "no markers yet").

ISSUE MODE (D-089, `--issue`): the v1 channel. One GitHub issue per (student, attempt), titled
"VDEL feedback - <assignment> - attempt <n>", ONE COMMENT per graded commit with the deterministic
text and an @mention of the student's github_username. Dry-run by default: it prints the exact API
calls and the text and contacts nothing. The real write needs `--apply` AND the environment
variable `VDEL_ALLOW_GITHUB_WRITE=1`, refuses a placeholder github_username, and records the issue
(`feedback_issues`, sql/09) and each comment (`feedback_posts`, channel `github_issue_comment`) so a
second run posts nothing. Every comment carries a hidden marker so a comment that reached GitHub
but not the database (a crash between the two) is recognised instead of posted twice.

OLD COMMIT-COMMENT PATH: `post_comment` is the original real GitHub call (a commit comment); it
refuses unless BOTH `enabled=True` AND `VDEL_ALLOW_FEEDBACK_POST=1`; the CLI never reaches it
(`--post` only checks the gate and says it is not wired), and no test calls it.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from assessment.diagnose import diagnose
from scripts.publish_repo import GitHub, GitHubHTTPError, PublishRefused
from scripts.publish_repo import _token as github_token
from scripts.seed_data import load_roster, roster_repo_for
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


# --- issue mode (D-089) -----------------------------------------------------------------------

GITHUB_WRITE_ENV_VAR = "VDEL_ALLOW_GITHUB_WRITE"
ISSUE_CHANNEL = "github_issue_comment"
# A github_username that was never a real login. The check is on the text, not on a GitHub
# lookup (no network): "student2-placeholder-local-render-only" is what the local render wrote.
_PLACEHOLDER_MARKERS = ("placeholder", "change_me", "changeme", "render-only", "example")
_GITHUB_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


class GitHubWriteNotEnabled(RuntimeError):
    """A GitHub write was requested without `--apply` AND VDEL_ALLOW_GITHUB_WRITE=1."""


def require_github_write(apply: bool) -> None:
    """The gate for EVERY GitHub write of the v1 loop: both the explicit flag and the
    environment variable, or it raises. Nothing is contacted before this passes."""
    if not (apply and os.environ.get(GITHUB_WRITE_ENV_VAR) == "1"):
        raise GitHubWriteNotEnabled(
            f"a GitHub write needs --apply AND {GITHUB_WRITE_ENV_VAR}=1 in the environment; "
            "this is the dry-run.")


def is_placeholder_username(username: str | None) -> bool:
    """True for an empty / fixture / placeholder github_username, or one GitHub cannot issue."""
    if not username or username.startswith("_"):
        return True
    lowered = username.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return True
    return _GITHUB_LOGIN.match(username) is None


def issue_title(assignment_id: str, attempt_no: int) -> str:
    return f"VDEL feedback - {assignment_id} - attempt {attempt_no}"


def comment_marker(attempt_id: int, commit_sha: str) -> str:
    """Invisible in the rendered comment; lets a re-run recognise a comment GitHub already has."""
    return f"<!-- vdel:feedback attempt={attempt_id} commit={commit_sha} -->"


def issue_intro(username: str, assignment_id: str, attempt_no: int) -> str:
    return (f"@{username} automated feedback for `{assignment_id}`, attempt {attempt_no}. "
            "Each push that is checked gets one comment here. The checks run on tests you "
            "cannot see, and these messages never show them.")


def issue_comment_body(username: str, markdown: str, attempt_id: int, commit_sha: str) -> str:
    return f"@{username}\n\n{markdown}\n{comment_marker(attempt_id, commit_sha)}\n"


@dataclass(frozen=True)
class IssuePlan:
    """Everything an issue post needs, built from reads only."""
    attempt_id: int
    commit_sha: str
    student_id: str
    github_username: str | None
    assignment_id: str
    attempt_no: int
    owner: str | None
    repo: str | None
    title: str
    intro: str
    comment_body: str
    issue_number: int | None        # known from feedback_issues
    already_posted: bool
    problems: tuple[str, ...]       # reasons a real post would be refused

    @property
    def refused(self) -> bool:
        return bool(self.problems)


def plan_issue_post(cur, attempt_id: int, commit_sha: str, repo_for: dict) -> IssuePlan:
    """Read-only. `repo_for` maps (student_id, assignment_id) -> (owner, repo) (the roster)."""
    cur.execute("SELECT a.student_id, a.assignment_id, a.attempt_no, s.github_username"
                " FROM attempts a JOIN students s USING (student_id) WHERE a.attempt_id = %s",
                (attempt_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"no attempt {attempt_id}")
    student_id, assignment_id, attempt_no, username = row
    feedback = build_feedback(cur, attempt_id, commit_sha)
    problems = []
    if is_placeholder_username(username):
        problems.append(f"placeholder github_username {username!r}: nobody to mention or invite")
    owner, repo = repo_for.get((student_id, assignment_id), (None, None))
    if owner is None:
        problems.append(f"no roster entry for {student_id}/{assignment_id}: the repo is unknown")
    cur.execute("SELECT to_regclass('public.feedback_issues') IS NOT NULL,"
                " to_regclass('public.feedback_posts') IS NOT NULL")
    has_issues, has_posts = cur.fetchone()
    if not (has_issues and has_posts):
        # fail closed: an issue created on GitHub that the database cannot record is a duplicate
        # waiting to happen. The migration is `python -m scripts.init_db` (sql/07 and sql/09).
        problems.append("the tables feedback_issues / feedback_posts are missing: run "
                        "`python -m scripts.init_db` first")
    number = None
    if has_issues:
        cur.execute("SELECT issue_number FROM feedback_issues WHERE attempt_id = %s",
                    (attempt_id,))
        found = cur.fetchone()
        number = found[0] if found else None
    body = issue_comment_body(username or "?", feedback.markdown, attempt_id, commit_sha)
    hidden = hidden_source_lines(_project_of(cur, attempt_id))
    assert_no_hidden_source(body, hidden)                   # last guard, on the exact text sent
    return IssuePlan(
        attempt_id, commit_sha, student_id, username, assignment_id, attempt_no, owner, repo,
        issue_title(assignment_id, attempt_no), issue_intro(username or "?", assignment_id,
                                                           attempt_no),
        body, number, already_posted(cur, attempt_id, commit_sha, ISSUE_CHANNEL),
        tuple(problems))


def _project_of(cur, attempt_id: int) -> str:
    cur.execute("SELECT project_id FROM attempts WHERE attempt_id = %s", (attempt_id,))
    return cur.fetchone()[0]


def describe_calls(plan: IssuePlan) -> list[str]:
    """The exact API calls a real post would make, for the dry-run."""
    base = f"/repos/{plan.owner or '<owner>'}/{plan.repo or '<repo>'}"
    calls = []
    if plan.issue_number is None:
        calls += [f"GET  {base}/issues?state=all&per_page=100   (find an issue titled "
                  f"{plan.title!r}; skipped if the database already knows it)",
                  f"POST {base}/issues   title={plan.title!r}   (only if none was found)"]
        number = "<n>"
    else:
        number = str(plan.issue_number)
    calls += [f"GET  {base}/issues/{number}/comments   (look for the marker "
              f"{comment_marker(plan.attempt_id, plan.commit_sha)})",
              f"POST {base}/issues/{number}/comments   (the text below)"]
    return calls


@dataclass(frozen=True)
class PostOutcome:
    status: str           # posted | recovered | skipped | dry_run | refused | failed
    detail: str = ""
    issue_number: int | None = None
    comment_url: str | None = None


def _record_issue(cur, attempt_id: int, owner: str, repo: str, number: int,
                  url: str | None) -> None:
    cur.execute(
        "INSERT INTO feedback_issues (attempt_id, owner, repo, issue_number, issue_url)"
        " VALUES (%s,%s,%s,%s,%s) ON CONFLICT (attempt_id) DO NOTHING",
        (attempt_id, owner, repo, number, url))


def ensure_issue(cur, gh, attempt_id: int, owner: str, repo: str, title: str,
                 intro: str) -> int:
    """The number of the feedback issue of an attempt, creating it only if no issue with the exact
    title exists. The database row comes first; then GitHub is searched; then it is created.
    The result is recorded (`ON CONFLICT DO NOTHING`). Raises GitHubHTTPError on a GitHub error."""
    cur.execute("SELECT issue_number FROM feedback_issues WHERE attempt_id = %s", (attempt_id,))
    known = cur.fetchone()
    if known:
        return known[0]
    issue = gh.find_issue(owner, repo, title)
    if issue is None:
        issue = gh.create_issue(owner, repo, title, intro)
    _record_issue(cur, attempt_id, owner, repo, issue["number"], issue.get("html_url"))
    return issue["number"]


def _record_post(cur, plan: IssuePlan, external_ref: str | None) -> None:
    digest = hashlib.sha256(plan.comment_body.encode("utf-8")).hexdigest()
    cur.execute(
        "INSERT INTO feedback_posts (attempt_id, commit_sha, channel, body_sha256, external_ref)"
        " VALUES (%s,%s,%s,%s,%s) ON CONFLICT (attempt_id, commit_sha, channel) DO NOTHING",
        (plan.attempt_id, plan.commit_sha, ISSUE_CHANNEL, digest, external_ref))


def post_issue_feedback(cur, plan: IssuePlan, *, apply: bool = False, gh=None) -> PostOutcome:
    """Post one comment (creating the issue first if needed), or say what would happen.

    Order of the safety checks: already posted -> dry-run -> the write gate (raises) -> refusals
    (placeholder, no roster entry) -> GitHub. A GitHub error (403 / 404 / 410 / 422 ...) is
    returned as a `failed` outcome, never raised, and writes no database row; the next run
    retries. The caller commits after each outcome."""
    if plan.already_posted:
        return PostOutcome("skipped", "already posted")
    if not apply:
        return PostOutcome("dry_run")
    require_github_write(apply)
    if plan.refused:
        return PostOutcome("refused", "; ".join(plan.problems))
    try:
        gh = gh or GitHub(github_token())
        number = plan.issue_number
        if number is None:
            number = ensure_issue(cur, gh, plan.attempt_id, plan.owner, plan.repo, plan.title,
                                  plan.intro)
        marker = comment_marker(plan.attempt_id, plan.commit_sha)
        for existing in gh.issue_comments(plan.owner, plan.repo, number):
            if marker in (existing.get("body") or ""):
                _record_post(cur, plan, existing.get("html_url"))
                return PostOutcome("recovered", "the comment was already on GitHub", number,
                                   existing.get("html_url"))
        comment = gh.create_issue_comment(plan.owner, plan.repo, number, plan.comment_body)
        _record_post(cur, plan, comment.get("html_url"))
        return PostOutcome("posted", "", number, comment.get("html_url"))
    except (GitHubHTTPError, PublishRefused) as exc:
        return PostOutcome("failed", str(exc))


def unposted_commits(cur, student_id: str, assignment_id: str | None = None,
                     commit: str | None = None) -> list[tuple[int, str]]:
    """Graded commits with no issue comment yet, oldest first."""
    return [(a, s) for a, s in graded_commits(cur, student_id, assignment_id, commit)
            if not already_posted(cur, a, s, ISSUE_CHANNEL)]


def recent_unposted(cur, student_id: str, hours: int) -> list[tuple[int, str]]:
    """Graded commits (pushed, with a commit_sha) whose results were written in the last `hours`
    hours and that have no issue comment yet, oldest first. This is what the hourly task posts:
    the lookback keeps the historical backlog quiet and retries a failed post for a while."""
    cur.execute(
        "SELECT t.attempt_id, t.commit_sha FROM test_results t"
        " JOIN attempts a USING (attempt_id) JOIN raw_commits c ON c.sha = t.commit_sha"
        " WHERE a.student_id = %s AND t.commit_sha IS NOT NULL"
        " GROUP BY t.attempt_id, t.commit_sha, c.committed_at"
        " HAVING max(t.ran_at) >= now() - make_interval(hours => %s)"
        " ORDER BY c.committed_at, t.commit_sha", (student_id, hours))
    return [(a, s) for a, s in cur.fetchall() if not already_posted(cur, a, s, ISSUE_CHANNEL)]


def _issue_main(args) -> int:
    if args.apply:
        try:
            require_github_write(True)
        except GitHubWriteNotEnabled as exc:
            print(f"REFUSED: {exc}")
            return 2
    repo_for = roster_repo_for(load_roster(args.roster))
    conn = db._open()
    failures = 0
    try:
        cur = conn.cursor()
        todo = unposted_commits(cur, args.student, args.assignment, args.commit)
        if not todo:
            print(f"nothing to post for {args.student} (no graded commit without a comment)")
            return 0
        for attempt_id, sha in todo:
            print("=" * 78)
            plan = plan_issue_post(cur, attempt_id, sha, repo_for)
            mode = "APPLY" if args.apply else "DRY-RUN"
            print(f"[{mode}] attempt {attempt_id}  commit {sha[:10]}  -> "
                  f"{plan.owner}/{plan.repo} issue {plan.title!r}")
            for problem in plan.problems:
                print(f"  WOULD REFUSE: {problem}")
            if not args.apply:
                for call in describe_calls(plan):
                    print(f"  {call}")
                print("\n" + plan.comment_body)
                continue
            outcome = post_issue_feedback(cur, plan, apply=True)
            print(f"  -> {outcome.status}: {outcome.detail} {outcome.comment_url or ''}")
            if outcome.status in ("posted", "recovered"):
                conn.commit()
            elif outcome.status in ("failed", "refused"):
                failures += 1
                conn.rollback()
    finally:
        conn.rollback()
        conn.close()
    return 1 if failures else 0


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
    parser.add_argument("--issue", action="store_true",
                        help="issue mode (D-089): one issue per attempt, one comment per commit; "
                             "dry-run unless --apply")
    parser.add_argument("--apply", action="store_true",
                        help="with --issue: really write to GitHub (also needs "
                             f"{GITHUB_WRITE_ENV_VAR}=1 in the environment)")
    parser.add_argument("--roster", default=None,
                        help="roster file (default config/roster.yaml); issue mode only")
    args = parser.parse_args(argv)
    if args.issue:
        return _issue_main(args)
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
