"""scripts/publish_repo.py -- put a rendered student repo on GitHub and register it.

The gap this closes: render_student_repo.py writes a repo to disk and collect_github.py
reads one from GitHub, but nothing moved a rendered repo to GitHub -- the two real ones were
created by hand. Pipeline order is now: render -> PUBLISH -> (student pushes) -> collect ->
grade_collected.

What one real run does, in this order (the order is the safety design):
  1. Render attempt N with render_student_repo (persists the variant/attempt rows) into a
     temp directory and REFUSE if anything named `hidden` is in the tree (invariant: hidden
     tests never reach a student). Checked on the work tree AND again on `git ls-files`
     after staging, because what git will publish is what matters, not what was on disk.
  2. Preflight GitHub BEFORE creating anything: the token must be able to push
     `.github/workflows/ci.yml`. A classic PAT without the `workflow` scope has that push
     rejected by GitHub -- found on this machine's token (scope `repo` only) -- and failing
     AFTER creating the repo would leave an empty repo behind.
  3. If the repo exists and already has commits: REFUSE. A rendered tree pushed over a
     student's history would destroy their work. Missing -> create (private). Empty -> use.
  4. git init / add / commit / push to main, then confirm the remote head is that commit.
  5. Only after a verified push: add/update the roster entries, so the collector never
     points at a repo that is not there.

`--dry-run` makes NO network call, no git call, writes no roster and, because the render
runs inside a transaction that is rolled back, no database row either; it still renders for
real so the file list and the hidden-test check shown are the real ones. Existence of the
GitHub repo and the authenticated login cannot be known without touching GitHub, and the
output says so.

Naming: `vdel-<project, _ -> ->-gapfill-<student_id>`, derived from the one real repo that
exists (`vdel-weather-etl-gapfill-anas`). That convention covers attempt 1 only; attempt
N>1 needs an explicit --repo-name rather than a convention invented here.

Roster editing is TEXT-level, not load/dump: config/roster.yaml is hand-edited and carries
comments a PyYAML round trip would silently delete. The edited text is re-parsed and
checked before it replaces the file, and the previous file is kept as roster.yaml.bak.

released_at for new roster rows is the publish time -- the real moment the assignment was
handed to that student, not an invented date (config/roster.example.yaml's rule).
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import requests
import yaml

from scripts.grade_collected import _git_env, _remove_tree
from scripts.render_student_repo import render_student_repo
from system import db

ROSTER = Path(__file__).resolve().parent.parent / "config" / "roster.yaml"
GH_API = "https://api.github.com"
_TIMEOUT_S = 60


class PublishRefused(RuntimeError):
    """A safety rule stopped the run. Nothing irreversible had happened yet at the point
    each of these is raised (see the ordering in the module docstring)."""


# --- names and decisions that need no network ----------------------------------------------

def default_repo_name(project_id: str, student_id: str) -> str:
    return f"vdel-{project_id.replace('_', '-')}-gapfill-{student_id}"


def choose_repo_name(project_id: str, student_id: str, attempt_no: int,
                     override: str | None) -> str:
    if override:
        return override
    if attempt_no != 1:
        raise PublishRefused(
            f"attempt {attempt_no}: the naming convention only covers attempt 1 and a new "
            "name is not invented here -- pass --repo-name explicitly."
        )
    return default_repo_name(project_id, student_id)


def check_no_hidden(paths) -> None:
    """Refuse if any path has a component named `hidden`. Deliberately broader than
    `tests/hidden`: a restructured tests/ must still be caught (same reasoning as
    render_student_repo._assert_no_hidden_tests_leaked)."""
    bad = sorted({str(p) for p in paths if "hidden" in Path(p).parts})
    if bad:
        raise PublishRefused(f"tests/hidden would be published ({bad[:5]}) -- refusing.")


def tree_files(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and ".git" not in p.relative_to(root).parts)


# --- roster text editing -------------------------------------------------------------------

_TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*):(.*)$")
_ITEM_START = re.compile(r"^(\s*)-\s")


def _block(lines: list[str], key: str) -> tuple[int, int] | None:
    """(first line after the `key:` line, end) of a top-level block, or None."""
    start = None
    for i, line in enumerate(lines):
        m = _TOP_KEY.match(line)
        if m is None:
            continue
        if start is not None:
            return start, i
        if m.group(1) == key:
            if m.group(2).split("#")[0].strip():
                raise PublishRefused(
                    f"roster.yaml: `{key}:` has an inline value; convert it to a block "
                    "list before publishing (this script edits block-style lists only)."
                )
            start = i + 1
    return (start, len(lines)) if start is not None else None


def _items(lines: list[str], lo: int, hi: int) -> list[tuple[int, int]]:
    """Top-level list items of a block. Only lines at the FIRST item's indentation start an
    item: a deeper `- py.testing` under `concepts:` is a nested entry, not a new item."""
    cands = [(i, _ITEM_START.match(lines[i]).group(1)) for i in range(lo, hi)
             if _ITEM_START.match(lines[i])]
    if not cands:
        return []
    base = cands[0][1]
    starts = [i for i, indent in cands if indent == base]
    return [(s, starts[k + 1] if k + 1 < len(starts) else hi) for k, s in enumerate(starts)]


def _insert_point(lines: list[str], lo: int, hi: int) -> int:
    """After the last real content line of the block (trailing blanks/comments stay put)."""
    last = lo
    for i in range(lo, hi):
        if lines[i].strip() and not lines[i].lstrip().startswith("#"):
            last = i + 1
    return last


def update_roster_text(text: str, *, student: dict, rows: list[dict]) -> tuple[str, list[str]]:
    """Return (new_text, actions). `student`: {student_id, github_username, cohort}.
    `rows`: assignment rows {assignment_id, owner, repo, student_id, released_at, concepts}.
    A row already present for (student_id, assignment_id) has only owner/repo updated --
    its released_at is a real date and is never moved. Idempotent. Comments preserved."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.replace("\r\n", "\n").split("\n")
    actions: list[str] = []

    sblock = _block(lines, "students")
    have_student = False
    if sblock is not None:
        have_student = any(
            (yaml.safe_load("\n".join(lines[a:b])) or [{}])[0].get("student_id")
            == student["student_id"]
            for a, b in _items(lines, *sblock)
        )
    if not have_student:
        new = [f"  - student_id: {student['student_id']}",
               f"    github_username: {student['github_username']}",
               f"    cohort: {student['cohort']}"]
        if sblock is None:
            lines += ["", "students:", *new]
        else:
            at = _insert_point(lines, *sblock)
            lines[at:at] = new
        actions.append(f"add student {student['student_id']}")

    ablock = _block(lines, "assignments")
    existing: dict[tuple, tuple[int, int]] = {}
    if ablock is not None:
        for a, b in _items(lines, *ablock):
            d = (yaml.safe_load("\n".join(lines[a:b])) or [{}])[0]
            existing[(d.get("student_id"), d.get("assignment_id"))] = (a, b)

    to_append: list[str] = []
    for row in rows:
        key = (row["student_id"], row["assignment_id"])
        if key in existing:
            a, b = existing[key]
            changed = False
            for i in range(a, b):
                m = re.match(r"^(\s*(?:-\s+)?)(owner|repo):\s*(\S+)(\s*#.*)?$", lines[i])
                if m and row[m.group(2)] != m.group(3):
                    lines[i] = f"{m.group(1)}{m.group(2)}: {row[m.group(2)]}{m.group(4) or ''}"
                    changed = True
            if changed:
                actions.append(f"update {row['assignment_id']} -> {row['owner']}/{row['repo']}")
            continue
        to_append += [
            f"  - assignment_id: {row['assignment_id']}",
            f"    owner: {row['owner']}",
            f"    repo: {row['repo']}",
            f"    student_id: {row['student_id']}",
            f"    released_at: {row['released_at']}",
            "    due_at: null",
            "    concepts:" if row["concepts"] else "    concepts: []",
            *[f"      - {c}" for c in row["concepts"]],
        ]
        actions.append(f"add {row['assignment_id']} -> {row['owner']}/{row['repo']}")

    if to_append:
        if ablock is None:
            lines += ["", "assignments:", *to_append]
        else:
            at = _insert_point(lines, *_block(lines, "assignments"))
            lines[at:at] = to_append

    new_text = nl.join(lines)
    parsed = yaml.safe_load(new_text) or {}
    got = {(a.get("student_id"), a.get("assignment_id")): (a.get("owner"), a.get("repo"))
           for a in parsed.get("assignments", [])}
    for row in rows:
        if got.get((row["student_id"], row["assignment_id"])) != (row["owner"], row["repo"]):
            raise PublishRefused("roster edit failed its own re-parse check; nothing written.")
    if not any(s.get("student_id") == student["student_id"] for s in parsed.get("students", [])):
        raise PublishRefused("roster edit failed its own re-parse check; nothing written.")
    return new_text, actions


def write_roster(path: Path, new_text: str) -> None:
    if path.exists():
        path.with_name(path.name + ".bak").write_bytes(path.read_bytes())
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(new_text.encode("utf-8"))
    os.replace(tmp, path)


# --- GitHub --------------------------------------------------------------------------------

class GitHub:
    """The four calls this script needs. Token is read once, only ever sent in the
    Authorization header, and never printed."""

    def __init__(self, token: str):
        self._h = {"Authorization": f"Bearer {token}",
                   "Accept": "application/vnd.github+json"}

    def _req(self, method: str, path: str, **kw):
        return requests.request(method, f"{GH_API}{path}", headers=self._h,
                                timeout=_TIMEOUT_S, **kw)

    def whoami(self) -> tuple[str, set[str] | None]:
        r = self._req("GET", "/user")
        if r.status_code != 200:
            raise PublishRefused(f"GitHub rejected the token (HTTP {r.status_code}).")
        header = r.headers.get("X-OAuth-Scopes")
        scopes = None if header is None else {s.strip() for s in header.split(",") if s.strip()}
        return r.json()["login"], scopes

    def repo_state(self, owner: str, repo: str) -> str:
        """'missing' | 'empty' | 'has_commits'."""
        if self._req("GET", f"/repos/{owner}/{repo}").status_code == 404:
            return "missing"
        r = self._req("GET", f"/repos/{owner}/{repo}/commits", params={"per_page": 1})
        if r.status_code == 409:                       # "Git Repository is empty."
            return "empty"
        if r.status_code != 200:
            raise PublishRefused(f"cannot inspect {owner}/{repo} (HTTP {r.status_code}).")
        return "has_commits" if r.json() else "empty"

    def create_repo(self, owner: str, repo: str, *, login: str, private: bool,
                    description: str) -> None:
        path = "/user/repos" if owner == login else f"/orgs/{owner}/repos"
        r = self._req("POST", path, json={"name": repo, "private": private,
                                          "description": description, "auto_init": False})
        if r.status_code != 201:
            raise PublishRefused(f"creating {owner}/{repo} failed: HTTP {r.status_code} "
                                 f"{r.json().get('message', '')}")

    def head_sha(self, owner: str, repo: str, branch: str) -> str | None:
        r = self._req("GET", f"/repos/{owner}/{repo}/commits/{branch}")
        return r.json().get("sha") if r.status_code == 200 else None


def preflight_scopes(tree: list[str], scopes: set[str] | None) -> str | None:
    """A warning string, or None; raises PublishRefused when the push cannot succeed.
    A push touching .github/workflows needs the `workflow` scope."""
    if not any(p.startswith(".github/workflows/") for p in tree):
        return None
    if scopes is None:
        return ("token scopes not reported (fine-grained token?) -- cannot pre-check the "
                "workflow-file permission; the push may still be rejected.")
    if "workflow" not in scopes:
        raise PublishRefused(
            f"the token's scopes are {sorted(scopes)} -- GitHub refuses to let such a token "
            "create or update .github/workflows/ci.yml, and every rendered repo contains one. "
            "Add the `workflow` scope to the token (or use one that has it). Nothing was "
            "created on GitHub."
        )
    return None


# --- git -----------------------------------------------------------------------------------

def _git(cwd: Path, env: dict, *args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                              capture_output=True, text=True, timeout=180)
    except subprocess.CalledProcessError as exc:
        raise PublishRefused(f"git {args[0]} failed: {exc.stderr.strip()}") from None
    return done.stdout.strip()


def git_publish(tree: Path, url: str, message: str, *, branch: str = "main") -> str:
    """init, stage, re-check what git WILL publish, commit, push. Returns the commit sha."""
    env = _git_env(url)
    _git(tree, env, "init", "-q", "-b", branch)
    for key in ("user.name", "user.email"):
        # `git config` exits 1 when the key is unset; that is the answer, not a failure.
        got = subprocess.run(["git", "config", key], cwd=tree, env=env,
                             capture_output=True, text=True)
        if not got.stdout.strip():
            raise PublishRefused(f"git has no {key} configured; cannot commit.")
    _git(tree, env, "add", "-A")
    check_no_hidden(_git(tree, env, "ls-files").splitlines())
    _git(tree, env, "commit", "-q", "-m", message)
    sha = _git(tree, env, "rev-parse", "HEAD")
    _git(tree, env, "push", "-q", url, f"HEAD:refs/heads/{branch}")
    return sha


# --- orchestration -------------------------------------------------------------------------

def _say(n: int, text: str) -> None:
    print(f"[{n}] {text}")


def resolve_project(cur, student: str, attempt_no: int, project: str | None) -> str:
    cur.execute("SELECT 1 FROM students WHERE student_id = %s", (student,))
    if cur.fetchone() is None:
        raise PublishRefused(f"unknown student {student!r} (not in the students table).")
    if project:
        cur.execute("SELECT 1 FROM projects WHERE project_id = %s", (project,))
        if cur.fetchone() is None:
            raise PublishRefused(f"unknown project {project!r}.")
        return project
    cur.execute("SELECT DISTINCT project_id FROM attempts"
                " WHERE student_id = %s AND attempt_no = %s", (student, attempt_no))
    found = [r[0] for r in cur.fetchall()]
    if len(found) != 1:
        raise PublishRefused(
            f"cannot infer the project for {student} attempt {attempt_no} "
            f"(candidates: {found or 'none'}) -- pass --project."
        )
    return found[0]


def run(*, student: str, attempt_no: int, project: str | None = None,
        repo_name: str | None = None, owner: str | None = None, private: bool = True,
        dry_run: bool = False, update_roster: bool = True, roster_path: Path = ROSTER,
        assume_yes: bool = False, gh=None, remote_base: str | None = None,
        confirm=input, conn=None) -> dict:
    """`gh`/`remote_base`/`confirm`/`conn` are injectable for tests; production leaves them
    None. `remote_base` replaces https://github.com (tests push to a local bare repo);
    `conn` is a caller-owned transaction used for every DB access and never committed or
    closed here (traces are append-only, so a test must roll back)."""
    out: dict = {"dry_run": dry_run}

    # -- 1. decisions that need only the DB and the roster
    own_conn = conn is None
    if own_conn:
        conn = db._open()
    try:
        with conn.cursor() as cur:
            project_id = resolve_project(cur, student, attempt_no, project)
            cur.execute("SELECT github_username, cohort FROM students WHERE student_id = %s",
                        (student,))
            github_username, cohort = cur.fetchone()
            cur.execute("SELECT assignment_id, concepts FROM assignments"
                        " WHERE project_id = %s ORDER BY seq", (project_id,))
            assignments = cur.fetchall()
        name = choose_repo_name(project_id, student, attempt_no, repo_name)
        roster_text = roster_path.read_text(encoding="utf-8") if roster_path.exists() else ""
        roster = yaml.safe_load(roster_text) or {}
        if owner is None:
            owner = next((a["owner"] for a in roster.get("assignments", [])
                          if a.get("student_id") == student and a.get("owner")), None)
        _say(1, f"student={student} attempt={attempt_no} project={project_id}")
        _say(1, f"repo name  : {name}   ({'--repo-name' if repo_name else 'convention'})")
        _say(1, f"repo owner : {owner or '<the authenticated GitHub user, resolved at run time>'}"
                f"   visibility: {'private' if private else 'PUBLIC'}")

        # -- 2. render into a temp dir (dry-run: inside a transaction that is rolled back)
        tmp = Path(tempfile.mkdtemp(prefix="vdel_publish_"))
        tree = tmp / "repo"
        try:
            if dry_run:
                # a savepoint, not "the connection is ours so it gets rolled back": the
                # caller may own `conn` (tests do), and a dry-run must leave no row behind
                # in either case.
                conn.cursor().execute("SAVEPOINT vdel_publish_dry_run")
            try:
                info = render_student_repo(project_id, student, attempt_no, tree,
                                           conn=conn if (dry_run or not own_conn) else None)
            finally:
                if dry_run:
                    conn.cursor().execute("ROLLBACK TO SAVEPOINT vdel_publish_dry_run")
            files = tree_files(tree)
            check_no_hidden(files)
            _say(2, f"rendered {len(files)} files, {info['hidden_gap_count']} hidden gap(s)"
                    f"{' (rolled back: dry-run)' if dry_run else ''}:")
            for f in files:
                print(f"      {f}")
            _say(2, "hidden-test check: PASS (no path component named 'hidden')")
            out["files"] = files

            rows_owner = owner or "<authenticated-user>"
            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            rows = [{"assignment_id": aid, "owner": rows_owner, "repo": name,
                     "student_id": student, "released_at": now, "concepts": list(concepts or [])}
                    for aid, concepts in assignments]
            new_roster, actions = update_roster_text(
                roster_text, student={"student_id": student,
                                      "github_username": github_username, "cohort": cohort},
                rows=rows)

            url_base = remote_base or "https://github.com"
            if dry_run:
                _say(3, "GitHub: NOT contacted (dry-run). Would: GET /user (login + token "
                        "scopes), refuse if scopes lack `workflow`, GET repo state; refuse if "
                        "it already has commits; POST create if missing.")
                _say(4, f"git: would `init -b main`, `add -A`, re-check `ls-files` for 'hidden', "
                        f"`commit`, `push {url_base}/{rows_owner}/{name}.git HEAD:main`")
                _say(5, "roster: " + ("; ".join(actions) if actions else "no change needed")
                        + ("  [--no-roster: skipped]" if not update_roster else ""))
                for line in added_lines(roster_text, new_roster):
                    print(f"      + {line}")
                print("\nDRY RUN: nothing was created, pushed, written or persisted.")
                out["roster_actions"] = actions
                return out

            # -- 3. GitHub preflight (nothing created yet)
            gh = gh or GitHub(_token())
            login, scopes = gh.whoami()
            owner = owner or login
            warning = preflight_scopes(files, scopes)
            _say(3, f"authenticated as {login}; token scopes: "
                    f"{sorted(scopes) if scopes is not None else 'not reported'}")
            if warning:
                print(f"      WARNING: {warning}")
            state = gh.repo_state(owner, name)
            _say(3, f"{owner}/{name}: {state}")
            if state == "has_commits":
                raise PublishRefused(f"{owner}/{name} already has commits -- refusing to push "
                                     "a fresh render over a student's history.")
            if state == "missing":
                if not assume_yes and confirm(
                    f"Create {'private' if private else 'PUBLIC'} repo {owner}/{name}? [y/N] "
                ).strip().lower() not in {"y", "yes"}:
                    raise PublishRefused("not confirmed; nothing created.")
                gh.create_repo(owner, name, login=login, private=private,
                               description=f"VDEL {project_id} gap-fill, {student} (attempt "
                                           f"{attempt_no}) -- generated by publish_repo.py")
                _say(3, "created")

            # -- 4. commit and push
            sha = git_publish(tree, f"{url_base}/{owner}/{name}.git",
                              f"Initial commit: {project_id} gapfill for {student} "
                              f"(attempt {attempt_no})")
            remote_head = gh.head_sha(owner, name, "main")
            if remote_head != sha:
                raise PublishRefused(f"pushed {sha} but the remote head reads {remote_head}.")
            _say(4, f"pushed {sha[:10]} to {owner}/{name}@main (remote head confirmed)")
            out.update(sha=sha, owner=owner, repo=name)

            # -- 5. roster, only after a verified push
            if update_roster:
                for r in rows:
                    r["owner"] = owner
                final, actions = update_roster_text(
                    roster_text, student={"student_id": student,
                                          "github_username": github_username,
                                          "cohort": cohort}, rows=rows)
                write_roster(roster_path, final)
                _say(5, f"roster {roster_path.name}: " + ("; ".join(actions) or "no change")
                        + "  (previous kept as .bak)")
            else:
                _say(5, "roster: skipped (--no-roster)")
            print(f"\nNext: python -m scripts.seed_data ; python -m scripts.collect ; "
                  f"python -m scripts.grade_collected --student {student}")
            return out
        finally:
            _remove_tree(tmp)
    finally:
        if own_conn:
            conn.rollback()  # dry-run render; a real run already committed via its own txn
            conn.close()


def added_lines(old: str, new: str) -> list[str]:
    """The lines a roster edit would ADD, in order (a real diff, so repeated YAML keys
    such as `repo:` are not hidden by their presence elsewhere in the file)."""
    diff = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
    return [ln[1:] for ln in diff if ln.startswith("+") and not ln.startswith("+++")]


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise PublishRefused("GITHUB_TOKEN is not set. See .env.example.")
    return token


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--student", required=True)
    ap.add_argument("--attempt", type=int, required=True)
    ap.add_argument("--project", help="project_id (inferred from the student's attempt if unique)")
    ap.add_argument("--repo-name", help="override the naming convention (required for attempt > 1)")
    ap.add_argument("--owner",
                    help="GitHub owner (default: from the roster, else the token's user)")
    ap.add_argument("--public", action="store_true", help="create a PUBLIC repo (default: private)")
    ap.add_argument("--dry-run", action="store_true", help="no GitHub, no git, no DB, no roster")
    ap.add_argument("--no-roster", action="store_true", help="do not touch roster.yaml")
    ap.add_argument("--roster-path", type=Path, default=ROSTER)
    ap.add_argument("--yes", action="store_true", help="skip the create-repo confirmation")
    args = ap.parse_args(argv)
    try:
        run(student=args.student, attempt_no=args.attempt, project=args.project,
            repo_name=args.repo_name, owner=args.owner, private=not args.public,
            dry_run=args.dry_run, update_roster=not args.no_roster,
            roster_path=args.roster_path, assume_yes=args.yes)
    except PublishRefused as exc:
        print(f"\nREFUSED: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
