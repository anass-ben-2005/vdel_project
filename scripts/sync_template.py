"""scripts/sync_template.py -- re-apply the TEMPLATE files to an already-published student repo.

Why this exists (D-062): D-060 changed the CI workflow every new render ships, but repos that
were published earlier keep the old one -- anas's hand-made repo still ran `ruff check .`
without ever installing ruff, so all of its runs failed before pytest. Every future template
change will have the same problem. This is the one reusable way to fix it, instead of a
one-off script per change.

What it may touch -- a fixed allowlist, `render_student_repo.TEMPLATE_FILES`:
    .github/workflows/ci.yml
    conftest.py
The content comes from the SAME constants the renderer writes (single source of truth, no
copied strings). Any other path is refused, and so is any path with a `hidden` component
(hidden tests must never reach a student repo -- same rule as publish_repo.check_no_hidden).
Student work (src files, tests/visible, ASSIGNMENT.md) is never read or written.

Two modes, and the safe one is the default:

  DRY-RUN (default, and --dry-run)   READ-ONLY. For each allowlisted path: GET the current
      content and blob SHA from the Contents API, print a unified diff against the template,
      say `missing` / `identical` where that is the case, and print the exact --apply command
      with the SHAs just observed. Only GET requests are ever sent.

  --apply --confirm-sha PATH=SHA ...  Writes. Every file that would change must carry the SHA
      you saw in the dry-run (`missing` for a file that does not exist yet). The remote SHAs
      are re-read first; if ANY differs from what was confirmed, or a changing file was not
      confirmed, NOTHING is written. Each file is then written with PUT /contents using that
      SHA, so GitHub itself rejects a write over a changed file (409) as a second guard.

Known limit: PUT /contents makes one commit per file, so two changed files are two commits
with the same message (`ci: sync template (D-060)`), and the first can land while the second
is rejected -- the output then says exactly what was and was not written. A single combined
commit needs the Git Data API; not built, because nothing here needs it yet.

Safety rules besides the above: the repo must be listed in config/roster.yaml (or pass
--allow-unlisted); with --student, the roster row for that repo must belong to that student;
the token is read from the environment the way scripts.collect does (python-dotenv loads
.env, which is gitignored), is only ever sent in the Authorization header, and is replaced
by *** in everything this script prints.

Run (dry-run first, always):
    python -m scripts.sync_template --repo OWNER/NAME [--student X]
    python -m scripts.sync_template --repo OWNER/NAME --apply \\
        --confirm-sha .github/workflows/ci.yml=<sha> --confirm-sha conftest.py=missing
"""

from __future__ import annotations

import argparse
import base64
import difflib
import os
import re
import sys
import time
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

from scripts.publish_repo import GH_API, PublishRefused, check_no_hidden, preflight_scopes
from scripts.render_student_repo import TEMPLATE_FILES
from scripts.seed_data import load_roster

_TIMEOUT_S = 60
DEFAULT_MESSAGE = "ci: sync template (D-060)"
MISSING = "missing"
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_RUN_POLLS = 6          # the run for a push appears a few seconds after the push
_RUN_POLL_WAIT_S = 4


class SyncRefused(PublishRefused):
    """A safety rule stopped the run. Nothing was written."""


# --- output that can never leak the token --------------------------------------------------

class _Out:
    """Every line this script prints goes through here, so the token cannot reach stdout
    even if a server error message happens to echo it."""

    def __init__(self, token: str):
        self._token = token

    def clean(self, text: str) -> str:
        return text.replace(self._token, "***") if self._token else text

    def say(self, text: str = "") -> None:
        print(self.clean(text))


# --- decisions that need no network --------------------------------------------------------

def parse_repo(value: str) -> tuple[str, str]:
    if not _REPO_RE.match(value):
        raise SyncRefused(f"--repo must look like OWNER/NAME, got {value!r}.")
    owner, name = value.split("/")
    return owner, name


def check_path_allowed(path: str) -> None:
    """The allowlist. `hidden` is checked first so its refusal names the real reason."""
    try:
        check_no_hidden([path])
    except PublishRefused as exc:
        raise SyncRefused(str(exc)) from None
    if path not in TEMPLATE_FILES:
        raise SyncRefused(
            f"{path!r} is not a template file -- this tool manages only "
            f"{sorted(TEMPLATE_FILES)} and refuses everything else."
        )


def check_roster(owner: str, name: str, *, student: str | None, roster: dict,
                 allow_unlisted: bool) -> list[str]:
    """Refuse a repo that is not in the roster. Returns warnings to print."""
    rows = [a for a in roster.get("assignments", [])
            if str(a.get("owner", "")).lower() == owner.lower()
            and str(a.get("repo", "")).lower() == name.lower()]
    if not rows:
        if allow_unlisted:
            return [f"{owner}/{name} is NOT in config/roster.yaml (--allow-unlisted given)."]
        raise SyncRefused(
            f"{owner}/{name} is not in config/roster.yaml. Syncing an unregistered repo is "
            "refused; add it to the roster or pass --allow-unlisted if that is intended."
        )
    if student is not None:
        owners = sorted({str(r.get("student_id")) for r in rows})
        if owners != [student]:
            raise SyncRefused(
                f"roster says {owner}/{name} belongs to {owners}, not {student!r} -- "
                "refusing to sync the wrong student's repo."
            )
    return []


def parse_confirmations(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        path, sep, sha = item.rpartition("=")
        if not sep or not path or not sha:
            raise SyncRefused(f"--confirm-sha expects PATH=SHA, got {item!r}.")
        check_path_allowed(path)
        if path in out and out[path] != sha:
            raise SyncRefused(f"--confirm-sha given twice for {path} with different SHAs.")
        out[path] = sha
    return out


# --- GitHub (Contents API) -----------------------------------------------------------------

class Contents:
    """The few calls this tool needs. Token only goes in the Authorization header."""

    def __init__(self, token: str):
        self._h = {"Authorization": f"Bearer {token}",
                   "Accept": "application/vnd.github+json"}

    def _req(self, method: str, path: str, **kw):
        return requests.request(method, f"{GH_API}{path}", headers=self._h,
                                timeout=_TIMEOUT_S, **kw)

    def default_branch(self, owner: str, name: str) -> str:
        r = self._req("GET", f"/repos/{owner}/{name}")
        if r.status_code == 404:
            raise SyncRefused(f"{owner}/{name}: HTTP 404 -- no such repo, or the token "
                              "cannot see it.")
        if r.status_code != 200:
            raise SyncRefused(f"{owner}/{name}: cannot read the repo (HTTP {r.status_code}).")
        return r.json()["default_branch"]

    def get_file(self, owner: str, name: str, path: str, ref: str) -> tuple[bytes, str] | None:
        """(content bytes, blob sha), or None when the file does not exist."""
        r = self._req("GET", f"/repos/{owner}/{name}/contents/{path}", params={"ref": ref})
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise SyncRefused(f"GET {path}: HTTP {r.status_code}.")
        body = r.json()
        if not isinstance(body, dict) or body.get("type") != "file" \
                or body.get("encoding") != "base64":
            raise SyncRefused(f"{path} is not a plain file on {ref} (directory, symlink or "
                              "oversized) -- refusing to touch it.")
        return base64.b64decode(body["content"]), body["sha"]

    def scopes(self) -> set[str] | None:
        r = self._req("GET", "/user")
        if r.status_code != 200:
            raise SyncRefused(f"GitHub rejected the token (HTTP {r.status_code}).")
        header = r.headers.get("X-OAuth-Scopes")
        return None if header is None else {s.strip() for s in header.split(",") if s.strip()}

    def put_file(self, owner: str, name: str, path: str, content: bytes, *, message: str,
                 branch: str, sha: str | None) -> str:
        """Create/update one file; return the new commit sha."""
        payload = {"message": message, "branch": branch,
                   "content": base64.b64encode(content).decode("ascii")}
        if sha is not None:
            payload["sha"] = sha
        r = self._req("PUT", f"/repos/{owner}/{name}/contents/{path}", json=payload)
        if r.status_code not in (200, 201):
            try:
                detail = r.json().get("message", "")
            except ValueError:
                detail = ""
            raise SyncRefused(f"PUT {path}: HTTP {r.status_code} {detail}".strip())
        return r.json()["commit"]["sha"]

    def run_url(self, owner: str, name: str, commit_sha: str) -> str | None:
        r = self._req("GET", f"/repos/{owner}/{name}/actions/runs",
                      params={"head_sha": commit_sha, "event": "push", "per_page": 5})
        if r.status_code != 200:
            return None
        runs = r.json().get("workflow_runs", [])
        return runs[0]["html_url"] if runs else None


# --- the plan: what the remote has vs what the template says --------------------------------

@dataclass
class FileState:
    path: str
    template: bytes
    remote: bytes | None
    sha: str | None

    @property
    def status(self) -> str:
        if self.remote is None:
            return MISSING
        return "identical" if self.remote == self.template else "differs"

    @property
    def line_endings_only(self) -> bool:
        return (self.status == "differs"
                and self.remote.replace(b"\r\n", b"\n") == self.template)

    @property
    def confirm_token(self) -> str:
        return self.sha if self.sha is not None else MISSING


def read_state(client: Contents, owner: str, name: str, ref: str) -> list[FileState]:
    states = []
    for path, text in TEMPLATE_FILES.items():
        check_path_allowed(path)
        got = client.get_file(owner, name, path, ref)
        states.append(FileState(path, text.encode("utf-8"),
                                None if got is None else got[0],
                                None if got is None else got[1]))
    return states


def unified_diff(state: FileState) -> str:
    remote = [] if state.remote is None else state.remote.decode("utf-8", "replace").splitlines()
    new = state.template.decode("utf-8").splitlines()
    label = "(missing)" if state.sha is None else f"(remote {state.sha[:7]})"
    return "\n".join(difflib.unified_diff(
        remote, new, fromfile=f"a/{state.path} {label}", tofile=f"b/{state.path} (template)",
        lineterm=""))


# --- the two modes -------------------------------------------------------------------------

def dry_run(client: Contents, owner: str, name: str, ref: str, out: _Out, *,
            student: str | None) -> list[FileState]:
    out.say(f"sync_template DRY-RUN (read-only: GET requests only) -- {owner}/{name} @ {ref}")
    states = read_state(client, owner, name, ref)
    to_change = []
    for s in states:
        out.say()
        if s.status == "identical":
            out.say(f"== {s.path}: identical (sha {s.sha})")
            continue
        if s.status == MISSING:
            out.say(f"== {s.path}: missing -- would be CREATED")
        else:
            note = " (line endings only)" if s.line_endings_only else ""
            out.say(f"== {s.path}: differs{note} (remote sha {s.sha}) -- would be UPDATED")
        out.say(unified_diff(s))
        to_change.append(s)
    out.say()
    if not to_change:
        out.say("Nothing to apply: the template files are already identical.")
        return states
    out.say("No write was made. To apply exactly what is shown above, run:")
    parts = [f"python -m scripts.sync_template --repo {owner}/{name}"]
    if student:
        parts.append(f"--student {student}")
    parts.append("--apply")
    parts += [f"--confirm-sha {s.path}={s.confirm_token}" for s in to_change]
    out.say("  " + " ".join(parts))
    return states


def apply(client: Contents, owner: str, name: str, ref: str, out: _Out, *,
          confirmed: dict[str, str], message: str, sleep=time.sleep) -> list[str]:
    """Validate everything, then write. Returns the commit shas."""
    if not confirmed:
        raise SyncRefused("--apply needs at least one --confirm-sha PATH=SHA, taken from the "
                          "dry-run output. Nothing was written.")
    out.say(f"sync_template APPLY -- {owner}/{name} @ {ref}")
    states = read_state(client, owner, name, ref)     # fresh read: what is there NOW

    for path in confirmed:                            # a confirmation for a path we manage
        check_path_allowed(path)
    for s in states:
        want = confirmed.get(s.path)
        if want is not None and want != s.confirm_token:
            raise SyncRefused(
                f"{s.path}: remote is now {s.confirm_token}, you confirmed {want}. It changed "
                "since the dry-run. Nothing was written -- run the dry-run again."
            )
    to_write = [s for s in states if s.status != "identical"]
    unconfirmed = [s.path for s in to_write if s.path not in confirmed]
    if unconfirmed:
        raise SyncRefused(f"{unconfirmed} would change but were not confirmed with "
                          "--confirm-sha. Nothing was written.")
    if not to_write:
        out.say("Nothing to write: the template files are already identical.")
        return []

    try:
        warning = preflight_scopes([s.path for s in to_write], client.scopes())
    except PublishRefused as exc:
        raise SyncRefused(str(exc)) from None
    if warning:
        out.say(f"warning: {warning}")

    commits: list[str] = []
    for s in to_write:
        try:
            commit = client.put_file(owner, name, s.path, s.template, message=message,
                                     branch=ref, sha=s.sha)
        except SyncRefused as exc:
            done = ", ".join(f"{w.path}@{c[:10]}"
                             for w, c in zip(to_write, commits, strict=False)) or "nothing"
            skipped = [w.path for w in to_write[len(commits):]]
            raise SyncRefused(f"{exc}. WRITTEN so far: {done}. NOT written: {skipped}.") \
                from None
        commits.append(commit)
        out.say(f"  wrote {s.path} -> commit {commit}")

    for commit in commits:
        url = None
        for attempt in range(_RUN_POLLS):
            url = client.run_url(owner, name, commit)
            if url or attempt == _RUN_POLLS - 1:
                break
            sleep(_RUN_POLL_WAIT_S)
        fallback = f"not visible yet -- see https://github.com/{owner}/{name}/actions"
        out.say(f"  run for {commit[:10]}: {url or fallback}")
    return commits


# --- CLI -----------------------------------------------------------------------------------

def _load_token() -> str:
    load_dotenv()    # same mechanism as the rest of the project; .env is gitignored
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SyncRefused("GITHUB_TOKEN is not set. See .env.example.")
    return token


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", required=True, help="OWNER/NAME of the student repo")
    ap.add_argument("--student", help="student_id the roster must list for this repo")
    ap.add_argument("--branch", help="default: the repo's default branch")
    ap.add_argument("--allow-unlisted", action="store_true",
                    help="allow a repo that is not in config/roster.yaml")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="the default; read-only")
    mode.add_argument("--apply", action="store_true", help="write (needs --confirm-sha)")
    ap.add_argument("--confirm-sha", action="append", default=[], metavar="PATH=SHA",
                    help="repeat per changing file; SHA from the dry-run (or `missing`)")
    ap.add_argument("--message", default=DEFAULT_MESSAGE, help="commit message")
    args = ap.parse_args(argv)

    token = ""
    try:
        if args.confirm_sha and not args.apply:
            raise SyncRefused("--confirm-sha only makes sense with --apply.")
        owner, name = parse_repo(args.repo)
        token = _load_token()
        out = _Out(token)
        roster = load_roster()
        for w in check_roster(owner, name, student=args.student, roster=roster,
                              allow_unlisted=args.allow_unlisted):
            out.say(f"warning: {w}")
        confirmed = parse_confirmations(args.confirm_sha)
        client = Contents(token)
        ref = args.branch or client.default_branch(owner, name)
        if args.apply:
            apply(client, owner, name, ref, out, confirmed=confirmed, message=args.message)
        else:
            dry_run(client, owner, name, ref, out, student=args.student)
    except (PublishRefused, requests.RequestException) as exc:
        print(f"REFUSED: {_Out(token).clean(str(exc))}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
