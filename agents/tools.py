"""agents/tools.py — M4 task 4.2. The deterministic stage, before the LLM sees anything.

Stage 1 of the agent skeleton (`CLAUDE.md` §8): run free, zero-variance checks and hand their
findings to the judge as *verified facts*. The principle is deterministic-first — never pay
an LLM to notice an unused import when ruff notices it perfectly, for nothing, every time.

**This is also a security boundary, and it is worth being explicit about why it holds.**
Invariant 12: no agent ever executes submitted code. `ruff check` and `sqlfluff lint` are
static analysers — they tokenise and parse, they do not import, evaluate or run. Nothing in
this file uses `shell=True`, and every path is passed as its own argv element, so a
submission cannot escape through its own filename. There is no untrusted-execution path
here, which is why correctness is judged by reading the code and never by running it.

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
   code being personal data.

Both linters are invoked as `sys.executable -m <tool>` rather than as bare `ruff` /
`sqlfluff`. They are project dependencies (`CLAUDE.md` §9), so binding them to the
interpreter running the agent is what makes the checks reproducible across machines where
the console scripts may not be on `PATH` — which is the case on this one.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Statuses a tool run can end in. Only `OK` means the findings list is trustworthy evidence
# of anything; every other value means the absence of findings says nothing about the code.
STATUS_OK = "ok"
STATUS_UNAVAILABLE = "unavailable"   # the tool is not installed
STATUS_TIMEOUT = "timeout"
STATUS_ERROR = "error"               # ran, but its output could not be parsed

# Seconds. D.5's value, carried across unchanged: a linter that has not answered in this long
# on a single student file has hung, and the grading run should not hang with it.
_TIMEOUT_S = 15

# sqlfluff requires a dialect and has no default. ANSI is the conservative choice: it is the
# common subset, so a submission written in a richer dialect produces false positives rather
# than a parse failure that would report nothing at all. Named here because it is a real
# limitation to state in the write-up, not a setting to forget — a Spark SQL submission
# linted as ANSI will be judged against slightly the wrong grammar.
DEFAULT_SQL_DIALECT = "ansi"


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


def _run(argv: list[str], tool: str) -> tuple[str, ToolReport | None]:
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


def run_ruff(path: str | Path) -> ToolReport:
    """`ruff check --output-format json` over one Python file. Static; never imports it."""
    argv = [sys.executable, "-m", "ruff", "check", str(path), "--output-format", "json"]
    stdout, failure = _run(argv, "ruff")
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


def run_sqlfluff(path: str | Path, dialect: str = DEFAULT_SQL_DIALECT) -> ToolReport:
    """`sqlfluff lint --format json` over one SQL file. Static; never connects to a database."""
    argv = [sys.executable, "-m", "sqlfluff", "lint", str(path),
            "--format", "json", "--dialect", dialect]
    stdout, failure = _run(argv, "sqlfluff")
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


def lint_submission(path: str | Path,
                    dialect: str = DEFAULT_SQL_DIALECT) -> list[ToolReport]:
    """Every applicable linter for this file, chosen by extension.

    Returns an empty list for a file type neither tool understands, which is honest: it means
    no deterministic facts are available, and `render_findings` says so rather than implying
    a clean bill of health.
    """
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return [run_ruff(path)]
    if suffix == ".sql":
        return [run_sqlfluff(path, dialect)]
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
            blocks.append(f"{report.tool}: ran, 0 findings.")
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
