"""Student repos for the grading-container tests (D-092): ordinary ones, to compare the two modes
row by row, and adversarial ones, to see what each mode lets student code do.

Adversarial code reports what it saw by RAISING at import time: the grader turns an exception raised
inside the student's module into a `collection_error` whose detail carries the message
(`RuntimeError at weather_etl/extract.py:N: OBS ...`). That is the observation channel, and it needs
no change to the grader. Nothing here is dangerous on the host: the probes touch only files and a
loopback port the test itself created, and the process-limit probe is BOUNDED (at most 300 tiny
children, killed at once) and is run only against the container.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from assessment.gap_parser import render_student_file

REPO = Path(__file__).resolve().parent.parent
PKG = REPO / "curriculum" / "master" / "weather_etl" / "weather_etl"
EXTRACT_MASTER = (PKG / "extract.py").read_text(encoding="utf-8")
EXTRACT_GAPS = ["g_ext_parse", "g_ext_retry"]
PROJECT, FILE_PATH = "weather_etl", "weather_etl/extract.py"


def make_repo(root: Path, extract_py: str) -> Path:
    """A student repo with the real package scaffolding and the given extract.py."""
    (root / "weather_etl").mkdir(parents=True)
    shutil.copyfile(PKG / "__init__.py", root / "weather_etl" / "__init__.py")
    (root / "weather_etl" / "extract.py").write_text(extract_py, encoding="utf-8")
    return root


# --- ordinary fixtures: the two modes must grade them identically ---------------------

SOLVED = EXTRACT_MASTER
UNSOLVED = render_student_file(EXTRACT_MASTER, hide_gap_ids=EXTRACT_GAPS)  # NotImplementedError
BROKEN_SYNTAX = "def fetch_weather(:\n"  # collection_error
# attempted but wrong: fetch_weather never retries, parse_response ignores its argument
WRONG = (
    "import requests\n\n"
    "def fetch_weather(url, max_attempts=3, backoff=0.0):\n"
    "    return requests.get(url, timeout=5).json()\n\n"
    "def parse_response(data):\n"
    "    return {'temp': 0, 'humidity': 0, 'wind_speed': 0}\n"
)
ORDINARY = {"solved": SOLVED, "unsolved": UNSOLVED, "wrong": WRONG, "broken_syntax": BROKEN_SYNTAX}


# --- adversarial fixtures ----------------------------------

INFINITE_LOOP = "while True:\n    pass\n"

# At most 300 tiny children (`sleep`), then report how many could be started and kill them.
FORK_PROBE = """\
import subprocess

started = []
try:
    for _ in range(300):
        started.append(subprocess.Popen(["sleep", "5"]))
except OSError as exc:
    failure = type(exc).__name__
else:
    failure = "none"
for child in started:
    child.kill()
raise RuntimeError(f"OBS spawned={len(started)} stopped_by={failure}")
"""


def probe_source(canary: Path, outside: Path, port: int) -> str:
    """One module that tries everything a hostile student might, and reports it as `OBS k=v ...`."""
    return f"""\
import os
import socket


def attempt(label, fn):
    try:
        return f"{{label}}=" + str(fn())
    except BaseException as exc:  # the point is to observe, whatever happens
        return f"{{label}}=" + type(exc).__name__


def read_canary():
    with open({str(canary)!r}, encoding="utf-8") as fh:
        return "READ:" + fh.read().strip()


def connect_loopback():
    with socket.create_connection(("127.0.0.1", {port}), timeout=3) as s:
        s.sendall(b"hello-from-student")
    return "connected"


def write_to(path):
    def run():
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("pwned")
        return "wrote"
    return run


uid = os.getuid() if hasattr(os, "getuid") else "n/a"
parts = [
    f"uid={{uid}}",
    "token=" + ("present" if os.environ.get("GITHUB_TOKEN") else "absent"),
    attempt("canary", read_canary),
    attempt("connect", connect_loopback),
    attempt("write_outside", write_to({str(outside)!r})),
    attempt("write_work", write_to("/work/pwned.txt")),
    attempt("write_etc", write_to("/etc/pwned")),
    attempt("write_scratch", write_to("/scratch/ok.txt")),
]
raise RuntimeError("OBS " + " ".join(parts))
"""


def parse_obs(detail: str | None) -> dict[str, str]:
    """`... OBS a=1 b=2 ...` -> {'a': '1', 'b': '2'}."""
    match = re.search(r"OBS (.*)$", detail or "")
    if not match:
        return {}
    return dict(token.split("=", 1) for token in match.group(1).split() if "=" in token)
