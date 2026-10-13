"""scripts/doctor.py -- is this machine ready to run VDEL? (D-105)

    python -m scripts.doctor [--roster PATH] [--no-network] [--task-name NAME]

One line per check: `OK`, `WARN` or `FAIL`. The exit code is 1 only when something FAILED (a WARN
is something to read, not something that stops the system). Read-only by construction:

  * the database session is opened `readonly=True` and rolled back;
  * Docker is asked two questions (`docker info`, `docker image inspect`); nothing is started or
    built;
  * the scheduled task is READ with `Get-ScheduledTask`; nothing is registered, enabled or disabled;
  * no secret is ever printed: the GitHub token and the provider keys are reported by NAME only, and
    the only text taken from the token's check is the list of scope names GitHub sends back.

THE ONE NETWORK CALL. With a `GITHUB_TOKEN` present, the doctor makes exactly one `GET /user` to
read the `X-OAuth-Scopes` response header (a classic token lists its scopes there; a fine-grained
token sends no such header, which is reported, not guessed). It is the only call the doctor can
make, it happens only when a person runs the command, and `--no-network` skips it. The tests never
reach it: every function takes its probes as parameters and the test module forbids `requests`.

"Migrations current" means: every table a `sql/*.sql` file creates (`CREATE TABLE`) and every
column it adds (`ALTER TABLE ... ADD COLUMN`) exists in the database. That is what `scripts.init_db`
applies, found by reading the SQL text with two regular expressions; a statement shape those do not
match (an index, a rule, a column renamed or dropped) is not checked, and the line says so. It does
not compare data.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import os
import platform
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
SQL_DIR = REPO / "sql"
DEFAULT_ROSTER = REPO / "config" / "roster.yaml"
TASK_NAME = "VDEL hourly"
MIN_PYTHON = (3, 11)  # pyproject.toml: requires-python = ">=3.11"
GITHUB_SCOPES_NEEDED = ("repo", "workflow")  # docs/OPERATIONS.md section 2
GITHUB_USER_URL = "https://api.github.com/user"

# Mirrors system.llm._FALLBACK_KEY_ENV_VARS; tests/test_doctor.py pins the two together. Not
# imported from there: system.llm validates LLM_PROVIDER at import time and raises on a typo, and
# a doctor that crashes on a typo cannot report it.
PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
}
KNOWN_PROVIDERS = (*PROVIDER_KEYS, "qwen_local")

OK, WARN, FAIL = "OK", "WARN", "FAIL"


@dataclass(frozen=True)
class Check:
    level: str
    name: str
    detail: str

    def line(self) -> str:
        return f"{self.level:<5} {self.name:<18} {self.detail}"


# --- python ---------------------------------------------------------------------------------------


def check_python(version=None) -> Check:
    v = tuple(version if version is not None else sys.version_info[:3])
    text = ".".join(str(n) for n in v[:3])
    if v[:2] < MIN_PYTHON:
        return Check(
            FAIL, "python", f"{text}; the project needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer"
        )
    return Check(OK, "python", text)


# --- docker ---------------------------------------------------------------------------------------


def _run(argv: list[str], run=subprocess.run, timeout: int = 20):
    return run(argv, capture_output=True, text=True, timeout=timeout, shell=False)


def check_docker(run=subprocess.run, image: str | None = None) -> list[Check]:
    if image is None:
        from assessment.test_runner import DEFAULT_GRADING_IMAGE, IMAGE_ENV_VAR

        image = os.environ.get(IMAGE_ENV_VAR, DEFAULT_GRADING_IMAGE)
    try:
        info = _run(["docker", "info", "--format", "{{.ServerVersion}}"], run)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [
            Check(FAIL, "docker", f"cannot ask Docker ({type(exc).__name__}); start Docker Desktop")
        ]
    if info.returncode != 0:
        return [Check(FAIL, "docker", "the Docker daemon is not running; start Docker Desktop")]
    checks = [
        Check(OK, "docker", f"daemon running, server {info.stdout.strip() or 'version unknown'}")
    ]
    try:
        found = _run(["docker", "image", "inspect", image, "--format", "{{.Id}}"], run)
    except (OSError, subprocess.TimeoutExpired) as exc:
        checks.append(
            Check(WARN, "grader image", f"could not look for {image} ({type(exc).__name__})")
        )
        return checks
    if found.returncode == 0:
        checks.append(Check(OK, "grader image", f"{image} present"))
    else:
        checks.append(
            Check(
                WARN,
                "grader image",
                f"{image} not built: grading would run student code in a subprocess on this PC "
                "(D-086: acceptable for one trusted student only). "
                "Build: docker build -f docker/grader.Dockerfile -t vdel-grader:1 docker",
            )
        )
    return checks


# --- database and migrations ----------------------------------------------------------------------

_CREATE_TABLE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)", re.I)
_ALTER_TABLE = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?([a-z_][a-z0-9_]*)(.*?);", re.I | re.S
)
_ADD_COLUMN = re.compile(r"ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)", re.I)


def expected_schema(sql_dir: Path = SQL_DIR) -> dict[str, dict[str, set[str]]]:
    """{file name: {"tables": {...}, "columns": {"table.column", ...}}} read from the SQL text."""
    out: dict[str, dict[str, set[str]]] = {}
    for path in sorted(sql_dir.glob("*.sql")):
        text = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
        columns = {
            f"{m.group(1).lower()}.{c.lower()}"
            for m in _ALTER_TABLE.finditer(text)
            for c in _ADD_COLUMN.findall(m.group(2))
        }
        out[path.name] = {
            "tables": {t.lower() for t in _CREATE_TABLE.findall(text)},
            "columns": columns,
        }
    return out


def check_migrations(cur, sql_dir: Path = SQL_DIR) -> Check:
    cur.execute(
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_schema = current_schema()"
    )
    have_columns = {f"{t}.{c}" for t, c in cur.fetchall()}
    have_tables = {col.split(".")[0] for col in have_columns}
    missing = []
    expected = expected_schema(sql_dir)
    for name, wants in expected.items():
        missing += [f"{name}: table {t}" for t in sorted(wants["tables"] - have_tables)]
        missing += [f"{name}: column {c}" for c in sorted(wants["columns"] - have_columns)]
    n_tables = sum(len(w["tables"]) for w in expected.values())
    n_columns = sum(len(w["columns"]) for w in expected.values())
    if missing:
        return Check(
            FAIL,
            "migrations",
            f"{len(missing)} missing, first: {missing[0]}. Run: python -m scripts.init_db",
        )
    return Check(
        OK,
        "migrations",
        f"{n_tables} table(s) and {n_columns} added column(s) from "
        f"{len(expected)} sql file(s) all present (CREATE TABLE / ADD COLUMN "
        "only; indexes and rules are not checked)",
    )


def check_database(opener: Callable | None = None, sql_dir: Path = SQL_DIR):
    """(checks, conn-or-None). The connection is read-only; the caller rolls back and closes it."""
    if opener is None:
        from system import db

        opener = db._open
    try:
        conn = opener()
    except Exception as exc:  # noqa: BLE001 -- the doctor reports, it never crashes
        reason = str(exc).strip().splitlines()[0][:160] if str(exc).strip() else type(exc).__name__
        return [Check(FAIL, "database", f"not reachable: {reason}. docker compose up -d")], None
    with contextlib.suppress(Exception):         # a fake connection in tests has no set_session
        conn.set_session(readonly=True)
    try:
        cur = conn.cursor()
        cur.execute("SELECT current_database()")
        name = cur.fetchone()[0]
        checks = [
            Check(OK, "database", f"connected to {name!r}, read-only session"),
            check_migrations(cur, sql_dir),
        ]
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        return [Check(FAIL, "database", f"connected but a read failed: {type(exc).__name__}")], conn
    return checks, conn


# --- GitHub token ---------------------------------------------------------------------------------


def _default_http_get(url: str, headers: dict):
    import requests

    r = requests.get(url, headers=headers, timeout=20)
    return r.status_code, dict(r.headers)


def check_github_token(env, http_get: Callable | None = None) -> list[Check]:
    """`http_get(url, headers) -> (status, headers)`; None = do not touch the network."""
    token = (env.get("GITHUB_TOKEN") or "").strip()
    if not token:
        return [
            Check(FAIL, "github token", "GITHUB_TOKEN is not set (name only; see .env.example)")
        ]
    checks = [Check(OK, "github token", "GITHUB_TOKEN is set")]
    if http_get is None:
        checks.append(Check(WARN, "github scopes", "not checked (--no-network)"))
        return checks
    try:
        status, headers = http_get(
            GITHUB_USER_URL,
            {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(Check(WARN, "github scopes", f"GET /user failed ({type(exc).__name__})"))
        return checks
    if status == 401:
        checks.append(
            Check(FAIL, "github scopes", "GitHub rejected the token (401): expired or revoked")
        )
        return checks
    if status != 200:
        checks.append(Check(WARN, "github scopes", f"GET /user answered HTTP {status}"))
        return checks
    raw = {k.lower(): v for k, v in headers.items()}.get("x-oauth-scopes")
    if raw is None:
        checks.append(
            Check(
                WARN,
                "github scopes",
                "no X-OAuth-Scopes header: a fine-grained token "
                "does not list scopes; check its repository "
                "permissions by hand",
            )
        )
        return checks
    scopes = [s.strip() for s in raw.split(",") if s.strip()]
    missing = [s for s in GITHUB_SCOPES_NEEDED if s not in scopes]
    shown = ", ".join(scopes) or "(none)"
    if missing:
        checks.append(
            Check(
                WARN,
                "github scopes",
                f"has: {shown}; missing: {', '.join(missing)} "
                "(workflow is needed to publish .github/workflows)",
            )
        )
    else:
        checks.append(Check(OK, "github scopes", f"has: {shown}"))
    return checks


# --- roster and open attempts ---------------------------------------------------------------------

_ROW_KEYS = ("assignment_id", "owner", "repo", "student_id")


def load_roster_rows(path: Path) -> tuple[dict | None, Check]:
    if not path.exists():
        return None, Check(
            FAIL, "roster", f"{path.name} not found; copy config/roster.example.yaml"
        )
    try:
        roster = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return None, Check(
            FAIL, "roster", f"{path.name} does not parse: {str(exc).splitlines()[0][:120]}"
        )
    rows = roster.get("assignments") or []
    bad = [
        i + 1
        for i, r in enumerate(rows)
        if not isinstance(r, dict) or any(not r.get(k) for k in _ROW_KEYS)
    ]
    if bad:
        return roster, Check(
            FAIL, "roster", f"assignment row(s) {bad} lack one of {', '.join(_ROW_KEYS)}"
        )
    placeholders = [
        r["assignment_id"]
        for r in rows
        if any(str(r.get(k)).startswith("CHANGE_ME") for k in _ROW_KEYS)
    ]
    if placeholders:
        return roster, Check(
            WARN, "roster", f"placeholder values (CHANGE_ME) in {placeholders[:3]}"
        )
    students = {r["student_id"] for r in rows}
    return roster, Check(
        OK,
        "roster",
        f"{path.name} parses: {len(rows)} assignment row(s), {len(students)} student(s)",
    )


def check_open_attempts(cur, roster: dict) -> list[Check]:
    """Every OPEN attempt must be reachable through the roster (the same rule run_cycle logs)."""
    from scripts.run_cycle import roster_warnings
    from scripts.seed_data import roster_repo_for

    repo_for = roster_repo_for(roster)
    cur.execute("SELECT DISTINCT student_id FROM attempts WHERE submitted_at IS NULL ORDER BY 1")
    students = [r[0] for r in cur.fetchall()]
    lines = [f"{sid}: {line}" for sid in students for line in roster_warnings(cur, sid, repo_for)]
    if lines:
        return [Check(WARN, "open attempts", line) for line in lines]
    return [
        Check(
            OK,
            "open attempts",
            f"{len(students)} student(s) with an open attempt, each reachable through the roster",
        )
    ]


# --- LLM provider keys ----------------------------------------------------------------------------


def check_llm_keys(env) -> list[Check]:
    present = [name for name in PROVIDER_KEYS.values() if (env.get(name) or "").strip()]
    provider = (env.get("LLM_PROVIDER") or "").strip()
    checks = []
    if provider and provider not in KNOWN_PROVIDERS:
        checks.append(
            Check(
                FAIL,
                "llm provider",
                f"LLM_PROVIDER={provider!r} is not one of {', '.join(KNOWN_PROVIDERS)}",
            )
        )
    else:
        checks.append(Check(OK, "llm provider", f"LLM_PROVIDER={provider or '(unset: anthropic)'}"))
    if not present:
        checks.append(
            Check(
                OK,
                "llm keys",
                "no provider key set: the agents (--with-llm) cannot run; "
                "everything deterministic still does",
            )
        )
        return checks
    checks.append(Check(OK, "llm keys", "present: " + ", ".join(present)))
    if len(present) > 1:
        checks.append(
            Check(
                WARN,
                "llm keys",
                "more than one provider key is present: the gateway may "
                "fall back to another provider than LLM_PROVIDER "
                "(docs/OPERATIONS.md section 12)",
            )
        )
    wanted = PROVIDER_KEYS.get(provider or "anthropic")
    if wanted and wanted not in present:
        checks.append(Check(WARN, "llm keys", f"LLM_PROVIDER needs {wanted}, which is not set"))
    return checks


# --- the scheduled task (Windows only, read only) -------------------------------------------------

_PS_READ_TASK = (
    "$t = Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue; "
    "if ($t) {{ 'STATE=' + $t.State; 'ARGS=' + $t.Actions[0].Arguments }}"
)


def decode_task_command(arguments: str) -> str | None:
    """The text a task registered with `-EncodedCommand <base64 UTF-16LE>` runs, or None."""
    tokens = arguments.split()
    for i, tok in enumerate(tokens[:-1]):
        if tok.lower() in ("-encodedcommand", "-e", "-ec"):
            try:
                return base64.b64decode(tokens[i + 1]).decode("utf-16-le")
            except Exception:  # noqa: BLE001
                return None
    if tokens:
        try:  # the registration passes it as the last token
            return base64.b64decode(tokens[-1], validate=True).decode("utf-16-le")
        except Exception:  # noqa: BLE001
            return None
    return None


def task_flags(command: str) -> dict[str, bool | str]:
    """What the decoded task command switches on. Substring tests on the generated text."""
    provider = re.search(r"LLM_PROVIDER\s*=\s*'([^']*)'", command)
    return {
        "github_write": "VDEL_ALLOW_GITHUB_WRITE" in command,
        "docker_grading": re.search(r"VDEL_GRADING_SANDBOX\s*=\s*'docker'", command) is not None,
        "with_llm": "--with-llm" in command,
        "with_code_agent": "--with-code-agent" in command,
        "llm_provider": provider.group(1) if provider else "",
    }


def check_scheduled_task(
    system: str | None = None, run=subprocess.run, task_name: str = TASK_NAME
) -> list[Check]:
    system = system or platform.system()
    if system != "Windows":
        return [
            Check(OK, "scheduled task", f"not applicable on {system}; use cron or systemd instead")
        ]
    try:
        res = _run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _PS_READ_TASK.format(name=task_name.replace("'", "''")),
            ],
            run,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [Check(WARN, "scheduled task", f"could not read it ({type(exc).__name__})")]
    state = next(
        (ln[6:].strip() for ln in res.stdout.splitlines() if ln.startswith("STATE=")), None
    )
    arguments = next(
        (ln[5:].strip() for ln in res.stdout.splitlines() if ln.startswith("ARGS=")), ""
    )
    if state is None:
        return [
            Check(
                WARN,
                "scheduled task",
                f"{task_name!r} is not registered: nothing runs by itself "
                "(scripts\\windows\\register_task.ps1)",
            )
        ]
    command = decode_task_command(arguments)
    if command is None:
        return [
            Check(
                WARN,
                "scheduled task",
                f"{task_name!r} is {state}; its command could not be decoded",
            )
        ]
    f = task_flags(command)
    on = lambda b: "on" if b else "off"  # noqa: E731
    checks = [
        Check(
            OK if state in ("Ready", "Running") else WARN,
            "scheduled task",
            f"{task_name!r} is {state}; github write {on(f['github_write'])}, docker grading "
            f"{on(f['docker_grading'])}, --with-llm {on(f['with_llm'])}"
            f"{' (' + f['llm_provider'] + ')' if f['llm_provider'] else ''}, "
            f"--with-code-agent {on(f['with_code_agent'])}",
        )
    ]
    if not f["docker_grading"]:
        checks.append(
            Check(
                WARN,
                "scheduled task",
                "grading runs student code on this PC (no "
                "VDEL_GRADING_SANDBOX=docker); mandatory before "
                "3-5 students (D-086)",
            )
        )
    return checks


# --- the whole run --------------------------------------------------------------------------------


def run_checks(
    *,
    roster_path: Path = DEFAULT_ROSTER,
    env=None,
    network: bool = True,
    task_name: str = TASK_NAME,
    run=subprocess.run,
    opener: Callable | None = None,
    http_get: Callable | None = None,
    system: str | None = None,
    version=None,
    sql_dir: Path = SQL_DIR,
) -> list[Check]:
    env = os.environ if env is None else env
    checks = [check_python(version)]
    checks += check_docker(run)
    db_checks, conn = check_database(opener, sql_dir)
    checks += db_checks
    checks += check_github_token(env, (http_get or _default_http_get) if network else None)
    roster, roster_check = load_roster_rows(Path(roster_path))
    checks.append(roster_check)
    if roster is not None and conn is not None and roster_check.level != FAIL:
        try:
            checks += check_open_attempts(conn.cursor(), roster)
        except Exception as exc:  # noqa: BLE001
            checks.append(Check(WARN, "open attempts", f"could not check ({type(exc).__name__})"))
    if conn is not None:
        conn.rollback()
        conn.close()
    checks += check_llm_keys(env)
    checks += check_scheduled_task(system, run, task_name)
    return checks


def main(argv: list[str] | None = None, out=print) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--roster", type=Path, default=DEFAULT_ROSTER)
    ap.add_argument(
        "--no-network",
        action="store_true",
        help="skip the single GET /user that reads the token's scopes",
    )
    ap.add_argument("--task-name", default=TASK_NAME)
    args = ap.parse_args(argv)
    from dotenv import load_dotenv

    load_dotenv()
    checks = run_checks(
        roster_path=args.roster, network=not args.no_network, task_name=args.task_name
    )
    for c in checks:
        out(c.line())
    n = {lvl: sum(1 for c in checks if c.level == lvl) for lvl in (OK, WARN, FAIL)}
    out(f"\n{n[OK]} ok, {n[WARN]} warning(s), {n[FAIL]} failure(s)")
    return 1 if n[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
