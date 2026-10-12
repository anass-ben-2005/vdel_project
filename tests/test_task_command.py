"""D-095 -- the command the hourly Windows task runs, tested by RUNNING what register_task builds.

The bug: the project folder sat inside a single-quoted PowerShell literal, and a folder name with
an apostrophe (stage_a_l'etranger) ended the string early -> the command did not parse ->
LastTaskResult 1 and an empty log. These tests build the command with the real generator
(scripts/windows/task_command.ps1, dot-sourced), put every awkward character in the folder AND in
the python path (apostrophe, spaces, ampersand, brackets), and run the generated argument string
with powershell.exe exactly as Task Scheduler does, with the folder as the working directory
("Start in"). The "python" is a .cmd stub, so nothing real is touched: no database, no network,
no GitHub.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="powershell.exe is not available")

TASK_COMMAND = Path(__file__).resolve().parent.parent / "scripts" / "windows" / "task_command.ps1"
AWKWARD = "o'brien & co [x]"            # apostrophe, spaces, ampersand, brackets
STUB = (
    "@echo off\r\n"
    'echo FAKE-PYTHON-RAN cwd="%CD%" args=%*\r\n'
    "echo write-flag=%VDEL_ALLOW_GITHUB_WRITE% sandbox=%VDEL_GRADING_SANDBOX%\r\n"
    "echo boom-on-stderr 1>&2\r\n"
    "exit /b %FAKE_EXIT%\r\n"
)


def powershell(*args: str, cwd: Path | None = None, env: dict | None = None):
    return subprocess.run([POWERSHELL, "-NoProfile", *args], capture_output=True, text=True,
                          cwd=cwd, env={**os.environ, **(env or {})}, timeout=120)


def generate(folder: Path, python_exe: Path, tmp_path: Path, *switches: str) -> str:
    """The argument string for powershell.exe, from the real generator."""
    driver = tmp_path / "driver.ps1"
    driver.write_text(
        "param([string]$Folder, [string]$PythonExe, [string]$Lib)\n"
        ". $Lib\n"
        "$s = New-HourlyTaskScript -ProjectFolder $Folder -PythonExe $PythonExe "
        f"{' '.join(switches)}\n"
        "Write-Output (New-HourlyTaskArguments -Script $s)\n", encoding="utf-8")
    done = powershell("-ExecutionPolicy", "Bypass", "-File", str(driver), "-Folder", str(folder),
                      "-PythonExe", str(python_exe), "-Lib", str(TASK_COMMAND))
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def decode(arguments: str) -> str:
    return base64.b64decode(arguments.rsplit(" ", 1)[1]).decode("utf-16-le")


def run_task(arguments: str, folder: Path, exit_code: int = 0):
    return powershell(*arguments.split(" "), cwd=folder, env={"FAKE_EXIT": str(exit_code)})


@pytest.fixture
def awkward(tmp_path):
    """A 'project folder' and a 'python' whose paths both hold an apostrophe, spaces and '&'."""
    folder = tmp_path / AWKWARD
    folder.mkdir()
    py_dir = tmp_path / "py'thon & more"
    py_dir.mkdir()
    stub = py_dir / "python.cmd"
    stub.write_text(STUB, encoding="utf-8", newline="")
    return folder, stub


def test_the_command_line_holds_nothing_a_parser_could_trip_on(awkward, tmp_path):
    folder, stub = awkward
    arguments = generate(folder, stub, tmp_path)
    assert arguments.startswith("-NoProfile -ExecutionPolicy Bypass -EncodedCommand ")
    assert re.fullmatch(r"[A-Za-z0-9+/=]+", arguments.rsplit(" ", 1)[1]), "only base64 may be there"
    script = decode(arguments)
    assert "py''thon & more" in script and "o''brien & co [x]" in script   # ' doubled in both
    assert "Set-Location -LiteralPath 'C:" in script or "Set-Location -LiteralPath '" in script


def test_a_folder_and_python_with_apostrophe_space_ampersand_and_brackets_run(awkward, tmp_path):
    folder, stub = awkward
    done = run_task(generate(folder, stub, tmp_path), folder)
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert "FAKE-PYTHON-RAN" in done.stdout and "-m scripts.run_hourly" in done.stdout
    assert f'cwd="{folder}"' in done.stdout              # python really starts in the folder
    log = (folder / "logs" / "task_stderr.log").read_text(encoding="utf-8", errors="replace")
    assert "task start, folder" in log and AWKWARD in log
    assert "boom-on-stderr" in log                         # python's stderr is kept, not lost
    assert "\x00" not in log                               # one encoding (UTF-8) in the whole file


def test_the_folder_is_set_by_the_script_not_trusted_to_start_in(awkward, tmp_path):
    """Found while writing this: PowerShell 5.1 started in a folder with [x] in its name falls
    back to its own install folder, so 'Start in' alone is not enough. Started from a different
    directory altogether, the task still ends up in the project folder."""
    folder, stub = awkward
    done = run_task(generate(folder, stub, tmp_path), tmp_path)        # wrong Start in on purpose
    assert done.returncode == 0, (done.stdout, done.stderr)
    assert f'cwd="{folder}"' in done.stdout
    assert (folder / "logs" / "task_stderr.log").is_file()


def test_the_exit_code_of_python_is_the_exit_code_of_the_task(awkward, tmp_path):
    folder, stub = awkward
    assert run_task(generate(folder, stub, tmp_path), folder, exit_code=7).returncode == 7


def test_a_startup_failure_is_written_to_the_stderr_log_never_silent(tmp_path):
    folder = tmp_path / AWKWARD
    folder.mkdir()
    missing = tmp_path / "no'such & python" / "python.exe"
    done = run_task(generate(folder, missing, tmp_path), folder)
    assert done.returncode != 0
    log = (folder / "logs" / "task_stderr.log").read_text(encoding="utf-8", errors="replace")
    assert "task start" in log and "TASK WRAPPER ERROR" in log, (log, done.stdout, done.stderr)


def test_writes_to_github_and_docker_grading_are_set_only_when_asked(awkward, tmp_path):
    folder, stub = awkward
    plain = generate(folder, stub, tmp_path)
    assert "VDEL_ALLOW_GITHUB_WRITE" not in decode(plain)
    assert "VDEL_GRADING_SANDBOX" not in decode(plain)
    assert "write-flag= sandbox=" in run_task(plain, folder).stdout
    both = generate(folder, stub, tmp_path, "-AllowGitHubWrite", "-UseDockerGrading")
    assert "write-flag=1 sandbox=docker" in run_task(both, folder).stdout


def test_the_old_quoting_really_did_break_on_an_apostrophe(awkward):
    """The regression this file exists for, kept as a fact: the previous form does not parse."""
    folder, _ = awkward
    done = powershell("-Command", f"Set-Location -LiteralPath '{folder}'; Write-Output ok")
    assert done.returncode != 0 and "ok" not in done.stdout
