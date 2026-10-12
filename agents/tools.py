"""agents/tools.py — M4 task 4.2. The deterministic stage, before the LLM sees anything.

Stage 1 of the agent skeleton (`CLAUDE.md` §8): run free, zero-variance checks and hand their
findings to the judge as *verified facts*. The principle is deterministic-first — never pay
an LLM to notice an unused import when ruff notices it perfectly, for nothing, every time.

**This is also a security boundary (invariant 12), and since D-103 it holds by construction, not
by the linters' good manners.** `ruff check` and `sqlfluff lint` are static analysers, but
sqlfluff's jinja templater imports and runs any Python module that a config file's `library_path`
points to (`sqlfluff/core/templaters/jinja.py`, `exec_module`), and both tools read config files
from the directory of the file they check and its parents. The student controls those files. So:

  1. the judged file is vetted (`vet_source`): a symbolic link, a path outside the checkout, a
     missing file, a non-file or a file above `MAX_FILE_BYTES` is REFUSED with a plain reason and
     a `skipped` report, never linted;
  2. ONLY that file is copied, under the fixed name `submission.py` / `submission.sql`, into a
     fresh empty temporary directory, and the tool runs from that directory (`cwd=`). There is no
     sibling file to be discovered as configuration, and no parent directory with project files;
  3. ruff runs with `--isolated` (reads no config file at all, user level included) and an
     EXPLICIT rule set, `--no-cache`;
  4. sqlfluff runs with `--ignore-local-config` and `--config` pointing at OUR config file, kept
     in a second temporary directory: dialect `ansi`, templater `raw` (no jinja, so no macros and
     no `library_path`).

Nothing in this file uses `shell=True`, and every path is its own argv element. A test plants a
`.sqlfluff` with `library_path` (and a `pyproject.toml`), a `ruff.toml` and a `pyproject.toml`
next to the files and requires that a marker file is NOT created and that the findings do not
change (`tests/test_code_agent_hardening.py`), with a positive control that shows the marker IS
created when sqlfluff is run the old way.

Design source: `VDEL_Modules_3_9_Build.md` D.5 (`run_ruff` / `run_sqlfluff`). **Three
deliberate deviations**, all of which follow from actually running the two tools and looking
at what they emit:

1. **`except Exception: return "[]"` is replaced by an explicit status.** D.5 collapses "the
   linter ran and found nothing" and "the linter is not installed" into the same empty
   string. The prompt then presents that silence to the judge as a verified fact — that the
   code is lint-clean — when in truth nothing was ever checked. That is inventing a fact by
   omission, the same class of error as the fabricated `duration_s = run_number * 60` in
   `DEVELOPMENT_MAP.md` §0. A `ToolReport` carries its `status`, and `render_findings` says
   "did not run" out loud when it did not run.

2. **Findings are normalised to five fields, not passed through as raw stdout.** A single
   five-violation sqlfluff run emits several thousand tokens, of which ~90% is `fixes` edit
   spans and per-rule `timings`. `CLAUDE.md` §8 lists linter findings as the element that
   defends against *wasted attention*; pasting the timings block would defeat the element
   with itself, and would be paid for on every graded submission.

3. **Absolute paths are reduced to the file's basename.** Both tools report the full local
   filesystem path. That is noise to the judge, and it puts a developer's directory
   structure into a third-party API call and into `COST_LOG` — gratuitous, and pointed in
   the wrong direction for the PDPA note M3's `RECOMMENDATION.md` has to make about student
   code being personal data. (With the private copy the path is the temporary one anyway.)

Both linters are invoked as `sys.executable -m <tool>` rather than as bare `ruff` /
`sqlfluff`. They are project dependencies (`CLAUDE.md` §9), so binding them to the
interpreter running the agent is what makes the checks reproducible across machines where
the console scripts may not be on `PATH` — which is the case on this one.

What the isolation changes in the numbers: ruff's default rule set is E4, E7, E9, F, and that is
now passed explicitly, so the findings of a file are the defaults', the same for every student and
for every ruff version that keeps those defaults. sqlfluff's rules are its defaults under the `raw`
templater instead of `jinja`: a `.sql` file that used jinja syntax is linted as written, not
rendered.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Statuses a tool run can end in. Only `OK` means the findings list is trustworthy evidence
# of anything; every other value means the absence of findings says nothing about the code.
STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"   # the tool is not installed
STATUS_TIMEOUT = "timeout"
STATUS_ERROR = "error"               # ran, but its output could not be parsed
STATUS_SKIPPED = "skipped"           # refused BEFORE running: link, outside the checkout, too big

# Seconds. D.5's value, carried across unchanged: a linter that has not answered in this long
# on a single student file has hung, and the grading run should not hang with it.
_TIMEOUT_S = 15

# A chosen number, not a measurement (D-103): the largest file the Code Agent will read, lint or
# put in a prompt. Student exercise files are tens of lines; 200 kB is far above any honest one.
MAX_FILE_BYTES = 200_000

# ruff's default rule set (E4, E7, E9, F), written out so the rules do not depend on the version
# or on any config file. `--isolated` ignores every config file, including the user-level one.
RUFF_RULES = ("E4", "E7", "E9", "F")

# sqlfluff requires a dialect and has no default. ANSI is the conservative choice: it is the
# common subset, so a submission written in a richer dialect produces false positives rather
# than a parse failure that would report nothing at all. Named here because it is a real
# limitation to state in the write-up, not a setting to forget — a Spark SQL submission
# linted as ANSI will be judged against slightly the wrong grammar.
DEFAULT_SQL_DIALECT = "ansi"

# Our config for sqlfluff, the only one it reads. `templater = raw`: no jinja, so no macros and no
# `library_path` (the setting that imports Python from the student's tree).
SQLFLUFF_TRUSTED_CONFIG = "[sqlfluff]\ndialect = ansi\ntemplater = raw\n"


class SourceRefused(ValueError):
    """The file must not be read, linted or judged. The message is the plain reason."""


@dataclass
class ToolReport:
    """One tool's result. `findings` is only meaningful when `status == STATUS_OK`."""

    tool: str
    status: str
    findings: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""

    @property
    def ran(self) -> bool:
        return self.status == STATUS_OK

    def to_dict(self) -> dict[str, Any]:
        """The shape stored in the verdict trace, so an auditor can see what the judge saw."""
        return {"tool": self.tool, "status": self.status,
                "findings": self.findings, "detail": self.detail}


# --- vetting the judged file ------------------------------------------------------------------

def _is_link(path: Path) -> bool:
    """A symbolic link or, on Windows, a junction."""
    is_junction = getattr(os.path, "isjunction", lambda _p: False)
    return path.is_symlink() or bool(is_junction(path))


def vet_source(path: str | Path, root: str | Path | None = None) -> Path:
    """The real path of a file that is safe to read, or `SourceRefused(reason)`.

    Refused: not found, not a regular file, itself a link, any directory between `root` and the
    file a link, a path outside `root` (when `root`, the checkout, is given), and a file above
    `MAX_FILE_BYTES`. Without `root` the containment check cannot be made; the link and size
    checks still are."""
    candidate = Path(path)
    if not candidate.exists() and not candidate.is_symlink():
        raise SourceRefused("file not found")
    if _is_link(candidate):
        raise SourceRefused("the file is a symbolic link")
    if root is not None:
        base = Path(os.path.abspath(root))
        absolute = Path(os.path.abspath(candidate))
        try:
            relative = absolute.relative_to(base)
        except ValueError:
            raise SourceRefused("the path is outside the checkout") from None
        walk = base
        for part in relative.parts[:-1]:
            walk = walk / part
            if _is_link(walk):
                raise SourceRefused("a directory on the path is a symbolic link")
        if not candidate.resolve().is_relative_to(base.resolve()):
            raise SourceRefused("the path resolves outside the checkout")
    resolved = candidate.resolve()
    if not resolved.is_file():
        raise SourceRefused("not a regular file")
    size = resolved.stat().st_size
    if size > MAX_FILE_BYTES:
        raise SourceRefused(f"the file is {size} bytes, above the limit of {MAX_FILE_BYTES}")
    return resolved


# --- running a linter ------------------------------------------------------------------------

def _run(argv: list[str], tool: str, cwd: Path | None = None) -> tuple[str, ToolReport | None]:
    """Run one linter. Returns `(stdout, None)` on success or `("", failure_report)`.

    Both linters exit non-zero when they find violations, so the return code says nothing
    about whether the run succeeded — only whether stdout parses does. That is why this
    returns stdout for the caller to parse rather than branching on `returncode`.
    """
    try:
        # Fixed argv, `shell=False`, every path its own element: a submission cannot reach
        # a shell through its filename. See this module's docstring on invariant 12.
        completed = subprocess.run(
            argv, capture_output=True, text=True, timeout=_TIMEOUT_S, shell=False,
            cwd=str(cwd) if cwd is not None else None,
        )
    except FileNotFoundError:
        return "", ToolReport(tool, STATUS_UNAVAILABLE,
                              detail=f"{tool} is not installed for {sys.executable}")
    except subprocess.TimeoutExpired:
        return "", ToolReport(tool, STATUS_TIMEOUT,
                              detail=f"{tool} exceeded {_TIMEOUT_S}s")
    except OSError as exc:  # a path the OS refuses outright
        return "", ToolReport(tool, STATUS_ERROR, detail=f"{type(exc).__name__}: {exc}")

    if not completed.stdout.strip():
        # No stdout at all. Clean runs still print `[]`, so this means the tool failed to
        # start properly -- stderr is the diagnosis and belongs in the report, not swallowed.
        stderr = completed.stderr.strip()
        if stderr:
            return "", ToolReport(tool, STATUS_ERROR, detail=stderr[:500])
    return completed.stdout, None


def _in_private_copy(tool: str, source: str | Path, root: str | Path | None,
                     suffix: str, run: Callable[[Path, Path, Path], ToolReport]) -> ToolReport:
    """Vet `source`, copy ONLY it into a fresh empty directory and call `run(copy, work, trusted)`.

    `work` holds the copy and nothing else (the process runs from it); `trusted` is a second empty
    directory where a tool's config of OUR making may be written. Both are removed afterwards."""
    try:
        resolved = vet_source(source, root)
    except SourceRefused as exc:
        return ToolReport(tool, STATUS_SKIPPED, detail=str(exc))
    with tempfile.TemporaryDirectory(prefix="vdel_tools_") as tmp:
        work, trusted = Path(tmp) / "work", Path(tmp) / "trusted"
        work.mkdir()
        trusted.mkdir()
        copy = work / f"submission{suffix}"
        shutil.copyfile(resolved, copy)
        return run(copy, work, trusted)


def run_ruff(path: str | Path, root: str | Path | None = None) -> ToolReport:
    """`ruff check --isolated` over a private copy of one Python file. Static; never imports it."""
    def run(copy: Path, work: Path, trusted: Path) -> ToolReport:
        argv = [sys.executable, "-m", "ruff", "check", str(copy), "--isolated", "--no-cache",
                "--select", ",".join(RUFF_RULES), "--output-format", "json"]
        stdout, failure = _run(argv, "ruff", cwd=work)
        if failure is not None:
            return failure
        try:
            raw = json.loads(stdout or "[]")
        except json.JSONDecodeError as exc:
            return ToolReport("ruff", STATUS_ERROR, detail=f"unparseable JSON: {exc}")
        findings = [
            {
                "code": item.get("code"),
                "message": item.get("message"),
                "line": (item.get("location") or {}).get("row"),
                "column": (item.get("location") or {}).get("column"),
                "severity": item.get("severity"),
            }
            for item in raw
            if isinstance(item, dict)
        ]
        return ToolReport("ruff", STATUS_OK, findings=findings)

    return _in_private_copy("ruff", path, root, ".py", run)


def run_sqlfluff(path: str | Path, dialect: str = DEFAULT_SQL_DIALECT,
                 root: str | Path | None = None) -> ToolReport:
    """`sqlfluff lint` over a private copy of one SQL file, with OUR config only. Static: the
    `raw` templater runs no jinja, so no student code is imported (see the module docstring)."""
    def run(copy: Path, work: Path, trusted: Path) -> ToolReport:
        config = trusted / "sqlfluff.cfg"
        config.write_text(SQLFLUFF_TRUSTED_CONFIG, encoding="utf-8")
        argv = [sys.executable, "-m", "sqlfluff", "lint", str(copy), "--format", "json",
                "--dialect", dialect, "--ignore-local-config", "--config", str(config)]
        stdout, failure = _run(argv, "sqlfluff", cwd=work)
        if failure is not None:
            return failure
        try:
            raw = json.loads(stdout or "[]")
        except json.JSONDecodeError as exc:
            return ToolReport("sqlfluff", STATUS_ERROR, detail=f"unparseable JSON: {exc}")

        findings: list[dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            for violation in entry.get("violations") or []:
                findings.append({
                    "code": violation.get("code"),
                    "message": violation.get("description"),
                    "line": violation.get("start_line_no"),
                    "column": violation.get("start_line_pos"),
                    # sqlfluff reports `warning: bool` where ruff reports a severity string.
                    # Normalised to ruff's vocabulary so the prompt has one column, not two.
                    "severity": "warning" if violation.get("warning") else "error",
                })
        return ToolReport("sqlfluff", STATUS_OK, findings=findings)

    return _in_private_copy("sqlfluff", path, root, ".sql", run)


def lint_submission(path: str | Path, dialect: str = DEFAULT_SQL_DIALECT,
                    root: str | Path | None = None) -> list[ToolReport]:
    """Every applicable linter for this file, chosen by extension.

    Returns an empty list for a file type neither tool understands, which is honest: it means
    no deterministic facts are available, and `render_findings` says so rather than implying
    a clean bill of health. `root` is the checkout the file must stay inside (see `vet_source`).
    """
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return [run_ruff(path, root)]
    if suffix == ".sql":
        return [run_sqlfluff(path, dialect, root)]
    return []


def render_findings(reports: list[ToolReport], filename: str = "") -> str:
    """The block that goes into the prompt. Facts when there are facts, silence never implied.

    The distinction this function exists to preserve: "ruff ran and found no issues" and
    "ruff did not run" are different statements, and only the first one is evidence. A judge
    told the second will weigh it correctly; a judge shown an empty list will read it as the
    first and score readability higher for it.

    Line numbers are kept because they let the judge tie a finding to the code it is about,
    and dropped file paths are not missed — the submission is the only file in the prompt.
    """
    if not reports:
        return ("No deterministic linter covers this file type, so no verified facts are "
                "available. Judge from the submission alone.")

    blocks: list[str] = []
    for report in reports:
        if not report.ran:
            blocks.append(
                f"{report.tool}: DID NOT RUN ({report.status}"
                f"{' — ' + report.detail if report.detail else ''}). "
                f"No {report.tool} facts are available for this submission; the absence of "
                f"findings below is not evidence that there are none."
            )
            continue

        if not report.findings:
            blocks.append(f"{report.tool}: ran, 0 findings"
                          f"{' (' + report.detail + ')' if report.detail else ''}.")
            continue

        where = f" in {Path(filename).name}" if filename else ""
        lines = [f"{report.tool}: ran, {len(report.findings)} finding(s){where}."]
        for finding in report.findings:
            location = f"line {finding['line']}" if finding.get("line") else "unknown line"
            lines.append(
                f"  - [{finding.get('code')}] {location}: {finding.get('message')}"
            )
        blocks.append("\n".join(lines))

    return "\n".join(blocks)
