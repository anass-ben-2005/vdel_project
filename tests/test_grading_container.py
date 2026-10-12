"""D-092 -- the grading container (VDEL_GRADING_SANDBOX=docker).

Two groups. The first needs neither docker nor a database: the command line, the mode switch, and
the refusal to fall back. The second runs real containers and SKIPS unless docker is up and the
image exists (`VDEL_GRADING_IMAGE`, default `vdel-grader:1`): it grades
the same student repos in both modes and compares them, then runs the adversarial repos in the
container and checks what the student code could and could not do. The host is never put at risk:
the process-limit probe runs only in the container, and the others touch only files and a loopback
port the test creates.
"""

from __future__ import annotations

import os
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from assessment import test_runner as tr
from system import db
from tests import sandbox_fixtures as fx
from tests.support import ensure_variant

IMAGE = os.environ.get(tr.IMAGE_ENV_VAR, tr.DEFAULT_GRADING_IMAGE)


def docker_image_ready() -> bool:
    try:
        done = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True,
                              timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


needs_container = pytest.mark.skipif(
    not docker_image_ready(), reason=f"docker or the image {IMAGE!r} is not available")


# --- no docker needed ----------------------------------

def argv(**kw):
    base = {"work": Path("/tmp/w"), "results": Path("/tmp/r"), "test_rel_path":
            "tests/hidden/test_x.py", "junit_name": "junit-abc.xml", "ini_name": "pt.ini",
            "image": "img:1", "container": "c1"}
    base.update(kw)
    return tr.docker_run_argv(base.pop("work"), base.pop("results"), base.pop("test_rel_path"),
                              base.pop("junit_name"), base.pop("ini_name"), **base)


def test_the_command_line_has_every_restriction():
    cmd = argv()
    joined = " ".join(cmd)
    for flag in ("--rm", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                 "--network none", "--pull never", f"--pids-limit {tr.DOCKER_PIDS_LIMIT}",
                 f"--memory {tr.DOCKER_MEMORY}", f"--memory-swap {tr.DOCKER_MEMORY}",
                 f"--cpus {tr.DOCKER_CPUS}", "--user 10001:10001", "--name c1"):
        assert flag in joined, flag
    assert "--tmpfs /scratch:rw,noexec,nosuid" in joined
    # the code is read-only and the report goes to a DIFFERENT mount
    mounts = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--mount"]
    assert len(mounts) == 2
    assert mounts[0].endswith("target=/work,readonly") and "readonly" not in mounts[1]
    assert mounts[1].endswith("target=/results")
    assert "--junitxml=/results/junit-abc.xml" in cmd and "/results/pt.ini" in cmd
    assert "--privileged" not in cmd and "--network" in cmd and "host" not in cmd
    assert cmd.index("img:1") < cmd.index("python")                  # the image, then the command


def test_no_host_environment_variable_is_passed_in():
    cmd = argv()
    passed = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-e"]
    assert all("=" in e for e in passed)                 # only explicit NAME=value, never "-e NAME"
    assert not [e for e in passed if e.split("=")[0] in {"GITHUB_TOKEN", "PG_DSN"}]


def test_the_container_pins_the_hash_seed():
    cmd = argv()
    assert "PYTHONHASHSEED=0" in [cmd[i + 1] for i, a in enumerate(cmd) if a == "-e"]


def test_a_path_with_a_comma_is_refused_rather_than_mis_mounted():
    with pytest.raises(tr.TestRunnerError):
        argv(work=Path("/tmp/a,b"))


def test_the_mode_switch(monkeypatch):
    monkeypatch.delenv(tr.SANDBOX_ENV_VAR, raising=False)
    assert tr.sandbox_mode() == "subprocess"
    for value, expected in (("", "subprocess"), ("subprocess", "subprocess"), ("docker", "docker"),
                            (" Docker ", "docker")):
        monkeypatch.setenv(tr.SANDBOX_ENV_VAR, value)
        assert tr.sandbox_mode() == expected
    monkeypatch.setenv(tr.SANDBOX_ENV_VAR, "podman")
    with pytest.raises(tr.TestRunnerError, match="not understood"):
        tr.sandbox_mode()                  # an unknown value must not select the weaker mode


def test_the_default_is_the_unchanged_subprocess_path(monkeypatch, tmp_path):
    monkeypatch.delenv(tr.SANDBOX_ENV_VAR, raising=False)
    calls = []
    monkeypatch.setattr(tr, "_run_pytest", lambda *a, **k: calls.append("subprocess"))
    monkeypatch.setattr(tr, "_run_pytest_docker", lambda *a, **k: calls.append("docker"))
    tr._run_tests(tmp_path, "tests/hidden/t.py", tmp_path / "j.xml")
    assert calls == ["subprocess"]
    monkeypatch.setenv(tr.SANDBOX_ENV_VAR, "docker")
    tr._run_tests(tmp_path, "tests/hidden/t.py", tmp_path / "j.xml")
    assert calls == ["subprocess", "docker"]


def test_docker_missing_fails_closed_and_never_falls_back(monkeypatch, tmp_path):
    spy = []
    monkeypatch.setattr(tr, "_run_pytest", lambda *a, **k: spy.append("subprocess"))

    def no_docker(*a, **k):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(tr.subprocess, "run", no_docker)
    with pytest.raises(tr.TestRunnerError, match="docker is not installed"):
        tr._run_pytest_docker(tmp_path, "tests/hidden/t.py", tmp_path / "j.xml")
    assert spy == []


def test_a_missing_image_is_an_error_with_the_build_command_not_a_fallback(monkeypatch,
                                                                           tmp_path):
    def fake_run(argv_, **kw):
        if argv_[:2] == ["docker", "run"]:
            return subprocess.CompletedProcess(argv_, 125, "", "Unable to find image 'x' locally")
        return subprocess.CompletedProcess(argv_, 0, "", "")

    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    with pytest.raises(tr.TestRunnerError) as err:
        tr._run_pytest_docker(tmp_path, "tests/hidden/t.py", tmp_path / "j.xml")
    assert "docker build -f docker/grader.Dockerfile" in str(err.value)


def test_an_external_kill_without_a_report_is_a_sandbox_kill(monkeypatch, tmp_path):
    def fake_run(argv_, **kw):
        return subprocess.CompletedProcess(argv_, 137 if argv_[:2] == ["docker", "run"] else 0,
                                           "", "")

    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    with pytest.raises(tr.SandboxKilled):
        tr._run_pytest_docker(tmp_path, "tests/hidden/t.py", tmp_path / "j.xml")


def test_the_wall_clock_limit_kills_the_container(monkeypatch, tmp_path):
    seen = []

    def fake_run(argv_, **kw):
        seen.append(argv_[:2])
        if argv_[:2] == ["docker", "run"]:
            raise subprocess.TimeoutExpired(argv_, 1)
        return subprocess.CompletedProcess(argv_, 0, "", "")

    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    with pytest.raises(subprocess.TimeoutExpired):
        tr._run_pytest_docker(tmp_path, "tests/hidden/t.py", tmp_path / "j.xml")
    assert ["docker", "kill"] in seen and ["docker", "rm"] in seen        # killed AND removed


def test_the_dockerfile_matches_what_the_runner_assumes():
    text = (fx.REPO / "docker" / "grader.Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.11-slim@sha256:" in text                   # pinned by digest
    assert "USER 10001:10001" in text and "WORKDIR /work" in text
    assert "COPY grader-requirements.txt" in text                    # the context is docker/ only
    copies = [ln for ln in text.splitlines() if ln.split(" ")[0] in ("COPY", "ADD")]
    assert copies == ["COPY grader-requirements.txt /tmp/grader-requirements.txt"]   # nothing else
    reqs = (fx.REPO / "docker" / "grader-requirements.txt").read_text(encoding="utf-8")
    pinned = [ln for ln in reqs.splitlines() if ln and not ln.startswith("#")]
    assert pinned and all("==" in ln for ln in pinned)               # every package is pinned
    for forbidden in ("psycopg2", "PyYAML", "anthropic", "openai", "google", "pydantic"):
        assert not any(forbidden.lower() in ln.lower() for ln in pinned)   # no secret holders


# --- real containers ----------------------------------

@pytest.fixture
def docker_mode(monkeypatch):
    monkeypatch.setenv(tr.SANDBOX_ENV_VAR, "docker")
    monkeypatch.setenv(tr.IMAGE_ENV_VAR, IMAGE)


def evaluate(root: Path):
    return tr.evaluate(fx.PROJECT, fx.FILE_PATH, root)


def canon(message):
    """pytest prints the 'Differing items' of a dict comparison in an order that changes with the
    process's hash seed -- two SUBPROCESS runs of the same repo already differ (found while writing
    this test). The first line and the SET of lines are what must agree between the modes."""
    if message is None:
        return None
    first, *rest = message.split("\n")
    return first, tuple(sorted(rest))


def rows(ev):
    return sorted((o.test_name, o.gap_id, o.passed, canon(o.message), o.status)
                  for o in ev.outcomes)


def leftover_containers() -> list[str]:
    out = subprocess.run(["docker", "ps", "-a", "--filter", "name=vdel-grade-", "--format",
                          "{{.Names}}"], capture_output=True, text=True, timeout=30)
    return out.stdout.split()


@needs_container
@pytest.mark.parametrize("name", sorted(fx.ORDINARY))
def test_both_modes_grade_an_ordinary_repo_identically(name, tmp_path, monkeypatch):
    repo = fx.make_repo(tmp_path / "repo", fx.ORDINARY[name])
    monkeypatch.delenv(tr.SANDBOX_ENV_VAR, raising=False)
    host = evaluate(repo)
    monkeypatch.setenv(tr.SANDBOX_ENV_VAR, "docker")
    monkeypatch.setenv(tr.IMAGE_ENV_VAR, IMAGE)
    box = evaluate(repo)
    assert (host.status, host.detail) == (box.status, box.detail)
    assert rows(host) == rows(box)
    assert rows(host)                                       # and something was actually graded


@needs_container
@pytest.mark.parametrize("name", sorted(fx.ORDINARY))
def test_stored_messages_are_identical_across_runs_and_modes(name, tmp_path, monkeypatch):
    """D-094: RAW messages (no canon()): the same repo twice in the container, and once on the
    host, must store the very same text."""
    repo = fx.make_repo(tmp_path / "repo", fx.ORDINARY[name])

    def raw(ev):
        return sorted((o.test_name, o.message) for o in ev.outcomes)
    monkeypatch.delenv(tr.SANDBOX_ENV_VAR, raising=False)
    host = raw(evaluate(repo))
    monkeypatch.setenv(tr.SANDBOX_ENV_VAR, "docker")
    monkeypatch.setenv(tr.IMAGE_ENV_VAR, IMAGE)
    assert raw(evaluate(repo)) == raw(evaluate(repo)) == host != []


@needs_container
def test_the_recorded_test_results_are_identical_row_by_row(tmp_path, monkeypatch):
    """grade_attempt in both modes on the test database: the rows that land in `test_results`."""
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO students VALUES ('_box_student','_box_student','vdel-2026')")
        variant = ensure_variant(cur, "weather_etl_extract")
        ids = {}
        for no in (1, 2):
            cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                        " variant_id, gap_seed) VALUES ('_box_student','weather_etl',"
                        "'weather_etl_extract',%s,%s,1) RETURNING attempt_id", (no, variant))
            ids[no] = cur.fetchone()[0]
        for name in ("solved", "wrong", "broken_syntax", "unsolved"):
            repo = fx.make_repo(tmp_path / name, fx.ORDINARY[name])
            monkeypatch.delenv(tr.SANDBOX_ENV_VAR, raising=False)
            tr.grade_attempt(fx.PROJECT, "weather_etl_extract", repo, ids[1], conn=conn)
            monkeypatch.setenv(tr.SANDBOX_ENV_VAR, "docker")
            monkeypatch.setenv(tr.IMAGE_ENV_VAR, IMAGE)
            tr.grade_attempt(fx.PROJECT, "weather_etl_extract", repo, ids[2], conn=conn)
            per_attempt = []
            for no in (1, 2):
                cur.execute("SELECT test_name, gap_id, passed, message, status FROM test_results"
                            " WHERE attempt_id = %s ORDER BY test_name", (ids[no],))
                per_attempt.append([(n, g, p, canon(m), st) for n, g, p, m, st in cur.fetchall()])
            assert per_attempt[0] == per_attempt[1], name
            assert per_attempt[0]
            cur.execute("DELETE FROM test_results WHERE attempt_id = ANY(%s)",
                        (list(ids.values()),))
    finally:
        conn.rollback()
        conn.close()


def listener():
    """A loopback server on the HOST. A student reaching it would prove a network path."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    received = []

    def serve():
        server.settimeout(0.5)
        for _ in range(40):
            try:
                conn, _ = server.accept()
            except (TimeoutError, OSError):
                continue
            received.append(conn.recv(64))
            conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return server, received, thread


@needs_container
def test_student_code_in_the_container_cannot_reach_the_host(tmp_path, docker_mode, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_should-never-be-seen")
    canary = tmp_path / "canary.txt"
    canary.write_text("CANARY-9f3a1c", encoding="utf-8")
    outside = tmp_path / "outside" / "pwned.txt"
    outside.parent.mkdir()
    server, received, thread = listener()
    try:
        port = server.getsockname()[1]
        repo = fx.make_repo(tmp_path / "repo", fx.probe_source(canary, outside, port))
        ev = evaluate(repo)
    finally:
        thread.join(timeout=25)
        server.close()
    obs = fx.parse_obs(ev.detail)
    assert ev.status == "collection_error" and obs, ev.detail
    assert obs["uid"] == "10001"                                  # not root
    assert obs["token"] == "absent"                               # no host environment variable
    assert obs["canary"] == "FileNotFoundError"                   # the host's files are not there
    assert "CANARY" not in (ev.detail or "")
    assert received == [] and obs["connect"] != "connected"       # no path to the host's loopback
    assert obs["write_outside"] in ("FileNotFoundError", "OSError") and not outside.exists()
    assert obs["write_work"] == "OSError"                         # the checkout is read-only
    assert obs["write_etc"] == "OSError"                          # so is the rest of the filesystem
    assert obs["write_scratch"] == "wrote"                        # only the scratch is writable
    assert leftover_containers() == []                            # the container was removed


@needs_container
def test_a_process_bomb_is_stopped_by_the_pids_limit(tmp_path, docker_mode):
    ev = evaluate(fx.make_repo(tmp_path / "repo", fx.FORK_PROBE))
    obs = fx.parse_obs(ev.detail)
    assert ev.status == "collection_error", ev.detail
    spawned = int(obs["spawned"])
    assert 1 <= spawned < 300 and spawned <= int(tr.DOCKER_PIDS_LIMIT)
    assert obs["stopped_by"] != "none"
    assert leftover_containers() == []


@needs_container
def test_an_infinite_loop_times_out_and_the_container_is_killed(tmp_path, docker_mode,
                                                                monkeypatch):
    monkeypatch.setattr(tr, "_TIMEOUT_S", 8)
    ev = evaluate(fx.make_repo(tmp_path / "repo", fx.INFINITE_LOOP))
    assert ev.status == "timeout" and ev.outcomes
    assert all(o.status == "timeout" for o in ev.outcomes)
    assert leftover_containers() == []


@needs_container
def test_the_container_has_no_network_at_all(tmp_path, docker_mode):
    """No interface but loopback: even a connection to an address that would route out fails."""
    code = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('192.0.2.1', 9), timeout=2)\n"
        "    r = 'connected'\n"
        "except OSError as e:\n"
        "    r = type(e).__name__\n"
        "raise RuntimeError('OBS net=' + r)\n"
    )
    ev = evaluate(fx.make_repo(tmp_path / "repo", code))
    assert fx.parse_obs(ev.detail)["net"] in ("OSError", "ConnectionRefusedError",
                                              "TimeoutError", "gaierror")
    assert fx.parse_obs(ev.detail)["net"] != "connected"
