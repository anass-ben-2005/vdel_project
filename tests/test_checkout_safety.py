"""D-093 -- fetching and checking out a student's repo never runs anything the repo ships.

A hostile student repo could try three routes at checkout time: a git hook, a `.gitattributes`
filter/smudge command, and a submodule. `checkout_commit` is `git init` + `git fetch --depth 1 <url>
<sha>` + `git checkout --detach FETCH_HEAD` into an empty directory. Hooks live in `.git/hooks` and
`core.hooksPath` lives in `.git/config`: neither is part of what a fetch transfers, so a freshly
initialised directory has none of them. This test builds the hostile repository for real and proves
the canary file those routes would write is never created. It uses a local repository as the
remote (no network) and skips when git is not available."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from scripts import grade_collected as gc


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def hostile_remote(tmp_path):
    try:
        git(tmp_path, "--version")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git not available")
    canary = tmp_path / "CANARY-hook-ran.txt"
    remote = tmp_path / "remote"
    remote.mkdir()
    git(remote, "init", "-q")
    git(remote, "config", "user.email", "t@example.com")
    git(remote, "config", "user.name", "t")
    git(remote, "config", "uploadpack.allowAnySHA1InWant", "true")

    script = f'#!/bin/sh\necho ran > "{canary.as_posix()}"\n'
    # route 1: real hooks in the SOURCE repository's .git/hooks, and a hooksPath in its config
    for name in ("post-checkout", "post-merge", "post-commit", "pre-commit"):
        hook = remote / ".git" / "hooks" / name
        hook.write_text(script, encoding="utf-8")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    git(remote, "config", "core.hooksPath", ".githooks")
    # the same hook as a COMMITTED file, where a hooksPath of ".githooks" would find it
    (remote / ".githooks").mkdir()
    committed = remote / ".githooks" / "post-checkout"
    committed.write_text(script, encoding="utf-8")
    committed.chmod(committed.stat().st_mode | stat.S_IXUSR)
    # route 2: an attributes filter whose command would write the canary (needs config to arm)
    (remote / ".gitattributes").write_text("* filter=evil\n", encoding="utf-8")
    git(remote, "config", "filter.evil.smudge", f'sh -c "echo smudge > {canary.as_posix()}"')
    git(remote, "config", "filter.evil.clean", "cat")
    # route 3: a submodule
    (remote / ".gitmodules").write_text(
        '[submodule "x"]\n\tpath = x\n\turl = file:///nonexistent/submodule\n', encoding="utf-8")
    (remote / "weather_etl").mkdir()
    (remote / "weather_etl" / "__init__.py").write_text("", encoding="utf-8")
    git(remote, "add", "--all")
    # make sure the committed files are tracked even though the filter exists in THIS repo only
    git(remote, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "hostile")
    sha = git(remote, "rev-parse", "HEAD")
    canary.unlink(missing_ok=True)       # committing in the source may have armed it; start clean
    return remote, sha, canary


def test_a_checkout_never_runs_a_hook_a_filter_or_a_submodule(hostile_remote, tmp_path):
    remote, sha, canary = hostile_remote
    dest = tmp_path / "work" / "repo"
    dest.parent.mkdir()
    gc.checkout_commit(None, None, sha, dest, remote_url=remote.as_uri())

    assert not canary.exists(), "something the repository shipped ran during checkout"
    # the files ARE there (they are just data) ...
    assert (dest / ".githooks" / "post-checkout").is_file()
    assert (dest / "weather_etl" / "__init__.py").is_file()
    # ... but the clone has no hooks, no hooksPath and no filter configured
    hooks = sorted(p.name for p in (dest / ".git" / "hooks").iterdir())
    assert all(name.endswith(".sample") for name in hooks), hooks
    config = git(dest, "config", "--local", "--list")
    assert "hookspath" not in config.lower() and "filter." not in config.lower()
    # a submodule is not initialised by a plain checkout
    assert not (dest / "x").exists() or not any((dest / "x").iterdir())
    gc._remove_tree(dest.parent)


def test_the_source_repo_really_carries_the_traps(hostile_remote):
    """Guards the test above against passing for the wrong reason: if the hostile repository did
    not contain what it claims, "nothing ran" would prove nothing."""
    remote, _sha, _canary = hostile_remote
    hooks = {p.name for p in (remote / ".git" / "hooks").iterdir()}
    assert {"post-checkout", "post-merge", "pre-commit"} <= hooks
    assert git(remote, "config", "--local", "core.hooksPath") == ".githooks"
    assert "filter.evil.smudge" in git(remote, "config", "--local", "--list")
    assert "filter=evil" in git(remote, "show", "HEAD:.gitattributes")
    assert git(remote, "show", "HEAD:.githooks/post-checkout").startswith("#!/bin/sh")


def test_the_trap_is_armed_a_checkout_inside_the_source_repo_does_run_the_hook(hostile_remote):
    """Sensitivity: in the SOURCE repo (hooksPath = .githooks) the same hook DOES fire on a
    checkout. So "the canary is absent after `checkout_commit`" means the mechanism that would have
    fired it was not there, not that the trap was a dud on this machine."""
    remote, _sha, canary = hostile_remote
    assert not canary.exists()
    git(remote, "checkout", "-q", "-b", "armed-probe")
    assert canary.exists(), "the hook did not fire in the source repo (no sh?)"
