"""D-065 (grading sandbox) and D-066 (collection errors) -- the grader, tested end to end.

Everything here runs the REAL grader on small throwaway student repos, against the real
`weather_etl` hidden tests (`test_load.py`: two tests, gaps g_ld_insert and g_ld_select).
The database tests use the isolated test database (tests/conftest.py, D-064) and one
transaction that is always rolled back.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import pytest

from assessment import test_runner as tr
from assessment.diagnose import diagnose
from memory.memory import Memory
from system import db
from tests.support import ensure_variant

REPO = Path(__file__).resolve().parent.parent
MASTER_LOAD = REPO / "curriculum" / "master" / "weather_etl" / "weather_etl" / "load.py"
PROJECT, FILE_PATH = "weather_etl", "weather_etl/load.py"
INSERT_TEST = "tests/hidden/test_load.py::test_insert_readings_returns_count"
SELECT_TEST = "tests/hidden/test_load.py::test_readings_since_filters_correctly"

SOLVED_LOAD = MASTER_LOAD.read_text(encoding="utf-8")
STUB_LOAD = (
    "def insert_readings(conn, records):\n    raise NotImplementedError()\n\n\n"
    "def readings_since(conn, since_ts):\n    raise NotImplementedError()\n"
)


def make_repo(root: Path, load_py: str | None = STUB_LOAD, extra: dict | None = None,
              package: bool = True) -> Path:
    """A minimal student repo: the `weather_etl` package and a load.py."""
    if package:
        (root / "weather_etl").mkdir(parents=True)
        (root / "weather_etl" / "__init__.py").write_text("", encoding="utf-8")
        if load_py is not None:
            (root / "weather_etl" / "load.py").write_text(load_py, encoding="utf-8")
    else:
        root.mkdir(parents=True, exist_ok=True)
    for rel, body in (extra or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


def run(repo: Path) -> tr.Evaluation:
    return tr.evaluate(PROJECT, FILE_PATH, repo)


def by_name(evaluation: tr.Evaluation) -> dict[str, bool]:
    return {o.test_name: o.passed for o in evaluation.outcomes}


# --- the environment allowlist (D-065) ---------------------------------------------------------

SECRET_NAMES = ("GITHUB_TOKEN", "PG_DSN", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
                "NVIDIA_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "FEATURE_WINDOW_DAYS",
                "VDEL_SOME_OTHER_DOTENV_KEY")
# Variables that would also STEER pytest if inherited. Kept apart because inheriting them
# breaks pytest's own start-up, which would hide the point of the "has teeth" check.
HOSTILE_NAMES = ("PYTEST_ADDOPTS", "PYTHONSTARTUP")


def test_grading_env_is_built_from_an_allowlist_not_copied(monkeypatch, tmp_path):
    for name in SECRET_NAMES:
        monkeypatch.setenv(name, "SECRET-" + name)
    env = tr.grading_env(tmp_path / "home")
    assert not set(SECRET_NAMES) & {k.upper() for k in env}
    assert env["PYTHONPATH"] == "" and env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert Path(env["HOME"]) == tmp_path / "home" == Path(env["USERPROFILE"])
    assert Path(env["TEMP"]).is_relative_to(tmp_path)          # real home and temp not handed over
    assert {k for k in env if k not in os.environ} <= {
        "HOME", "USERPROFILE", "TEMP", "TMP", "TMPDIR", "PYTHONPATH",
        "PYTHONDONTWRITEBYTECODE", "PYTHONIOENCODING", "PYTEST_DISABLE_PLUGIN_AUTOLOAD"}


def test_no_key_listed_in_env_example_can_ever_be_passed(monkeypatch, tmp_path):
    """`.env.example` is the committed list of every key `.env` holds."""
    keys = [line.split("=", 1)[0].strip() for line in
            (REPO / ".env.example").read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")]
    assert "GITHUB_TOKEN" in keys and "PG_DSN" in keys
    for key in keys:
        monkeypatch.setenv(key, "SECRET")
    env = tr.grading_env(tmp_path / "home")
    assert [k for k in keys if k in env and env[k] == "SECRET"] == []
    assert not set(keys) & set(tr._ENV_PASSTHROUGH)


def _probe(tmp_path: Path, allowed: set[str]) -> Path:
    path = tmp_path / "probe_hidden.py"
    path.write_text(f'''
import os
import pytest

SECRETS = {set(SECRET_NAMES) | set(HOSTILE_NAMES)!r}
ALLOWED = {allowed!r}


@pytest.mark.gap("g_probe_secrets")
def test_no_secret_reaches_the_student_process():
    assert sorted(k for k in os.environ if k.upper() in SECRETS) == []


@pytest.mark.gap("g_probe_names")
def test_only_allowlisted_names_exist():
    assert sorted(k for k in os.environ if k.upper() not in ALLOWED) == []


@pytest.mark.gap("g_probe_pythonpath")
def test_pythonpath_is_ours_and_empty():
    assert os.environ.get("PYTHONPATH") == ""
''', encoding="utf-8")
    return path


def _allowed_names(tmp_path: Path) -> set[str]:
    return ({k.upper() for k in tr.grading_env(tmp_path / "h")}
            | {"PYTEST_CURRENT_TEST", "PYTEST_VERSION"})   # both set by pytest, not by us


def test_secrets_are_absent_inside_the_students_test_process(monkeypatch, tmp_path):
    """The parent holds every secret, a hostile PYTEST_ADDOPTS and a poisoned PYTHONPATH;
    the process that runs the student's tests sees none of them."""
    for name in (*SECRET_NAMES, *HOSTILE_NAMES):
        monkeypatch.setenv(name, "SECRET-" + name)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "evil"))
    probe = _probe(tmp_path, _allowed_names(tmp_path))
    monkeypatch.setattr(tr, "_hidden_test_file", lambda *a: probe)
    result = run(make_repo(tmp_path / "repo"))
    assert result.status == "ok"
    assert {o.gap_id: (o.passed, o.message) for o in result.outcomes} == {
        "g_probe_secrets": (True, None), "g_probe_names": (True, None),
        "g_probe_pythonpath": (True, None)}


def test_the_probe_has_teeth_it_fails_when_the_environment_is_inherited(monkeypatch, tmp_path):
    for name in SECRET_NAMES:
        monkeypatch.setenv(name, "SECRET-" + name)
    probe = _probe(tmp_path, _allowed_names(tmp_path))
    monkeypatch.setattr(tr, "_hidden_test_file", lambda *a: probe)
    monkeypatch.setattr(tr, "grading_env", lambda home: dict(os.environ))   # the OLD behaviour
    outcomes = {o.gap_id: o.passed for o in run(make_repo(tmp_path / "repo")).outcomes}
    assert outcomes["g_probe_secrets"] is False and outcomes["g_probe_names"] is False


# --- the sandbox copy (D-065) ------------------------------------------------------------------

EVIL_CONFTEST = '''
import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    report.outcome = "passed"          # force every test to pass
    report.longrepr = None
'''
EVIL_FILES = {
    "conftest.py": EVIL_CONFTEST,
    "tests/conftest.py": EVIL_CONFTEST,
    "weather_etl/conftest.py": EVIL_CONFTEST,
    "pytest.ini": '[pytest]\naddopts = -k "not insert and not since"\n',
    "tox.ini": '[pytest]\naddopts = -k "not insert and not since"\n',
    "setup.cfg": '[tool:pytest]\naddopts = -k "not insert and not since"\n',
    "pyproject.toml": '[tool.pytest.ini_options]\naddopts = "-k \'not insert and not since\'"\n',
    "sitecustomize.py": "import os\nos._exit(0)\n",
}


def test_a_hostile_repo_cannot_force_a_passing_grade(tmp_path):
    honest = run(make_repo(tmp_path / "honest"))
    hostile = run(make_repo(tmp_path / "hostile", extra=EVIL_FILES))
    assert by_name(honest) == {INSERT_TEST: False, SELECT_TEST: False}      # stubs really fail
    assert by_name(hostile) == by_name(honest)                              # the real grade
    assert hostile.status == honest.status == "ok"


def test_the_attack_is_real_it_forges_a_pass_when_sanitising_is_off(monkeypatch, tmp_path):
    """Mutation check: without prepare_sandbox's cleanup the same repo DOES get 100%."""
    def copy_only(src: Path, dst: Path) -> None:
        shutil.copytree(src, dst, ignore=tr._ignore_for_copy)
        shutil.rmtree(dst / "tests" / "hidden", ignore_errors=True)

    monkeypatch.setattr(tr, "prepare_sandbox", copy_only)
    forged = run(make_repo(tmp_path / "hostile", extra={"conftest.py": EVIL_CONFTEST}))
    assert by_name(forged) == {INSERT_TEST: True, SELECT_TEST: True}


def test_prepare_sandbox_strips_steering_files_and_installs_the_trusted_conftest(tmp_path):
    from scripts.render_student_repo import TEMPLATE_FILES

    extra = dict(EVIL_FILES)
    extra["tests/visible/test_x.py"] = "def test_x():\n    pass\n"
    extra["pyproject.toml"] = '[project]\nname = "kept"\n'          # no pytest section: stays
    extra["setup.cfg"] = "[metadata]\nname = kept\n"                # no pytest section: stays
    src = make_repo(tmp_path / "src", extra=extra)
    (src / "tests" / "hidden").mkdir(parents=True)
    (src / "tests" / "hidden" / "leftover.py").write_text("x = 1\n", encoding="utf-8")
    dst = tmp_path / "dst"
    tr.prepare_sandbox(src, dst)

    assert (dst / "conftest.py").read_text(encoding="utf-8") == TEMPLATE_FILES["conftest.py"]
    for gone in ("tests/conftest.py", "weather_etl/conftest.py", "pytest.ini", "tox.ini",
                 "sitecustomize.py", "tests/hidden"):
        assert not (dst / gone).exists(), gone
    assert (dst / "pyproject.toml").exists() and (dst / "setup.cfg").exists()
    assert (dst / "tests" / "visible" / "test_x.py").exists()
    assert (dst / "weather_etl" / "load.py").exists()


def test_prepare_sandbox_never_follows_a_symlink(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("do not copy", encoding="utf-8")
    src = make_repo(tmp_path / "src")
    try:
        os.symlink(secret, src / "link.txt")
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    dst = tmp_path / "dst"
    tr.prepare_sandbox(src, dst)
    assert not (dst / "link.txt").exists()


def test_the_original_repo_is_never_modified(tmp_path):
    repo = make_repo(tmp_path / "student", extra=EVIL_FILES)
    before = {p.relative_to(repo).as_posix(): p.read_bytes()
              for p in repo.rglob("*") if p.is_file()}
    run(repo)
    after = {p.relative_to(repo).as_posix(): p.read_bytes()
             for p in repo.rglob("*") if p.is_file()}
    assert after == before                  # their conftest is still there, no hidden dir added
    assert not (repo / "tests" / "hidden").exists()


def test_the_junit_report_is_outside_the_students_directory_under_a_random_name(
        monkeypatch, tmp_path):
    seen = []
    real = tr._run_pytest

    def spy(repo_dir, test_rel, junit_path, ini_path=None):
        seen.append((Path(repo_dir), Path(junit_path)))
        return real(repo_dir, test_rel, junit_path, ini_path)

    monkeypatch.setattr(tr, "_run_pytest", spy)
    repo = make_repo(tmp_path / "student")
    run(repo)
    run(repo)
    (_, junit1), (_, junit2) = seen
    for work, junit in seen:
        assert work not in junit.parents and junit.parent.name == "results"
        assert re.fullmatch(r"junit-[0-9a-f]{32}\.xml", junit.name)
    assert junit1.name != junit2.name


def test_pytest_runs_with_our_flags(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"], captured["kwargs"] = cmd, kwargs

    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    work, results = tmp_path / "w", tmp_path / "r"
    work.mkdir()
    results.mkdir()
    tr._run_pytest(work, "tests/hidden/test_load.py", results / "j.xml")
    cmd = captured["cmd"]
    assert cmd[:4] == [sys.executable, "-P", "-m", "pytest"]
    assert "-c" in cmd and "--rootdir" in cmd and "no:cacheprovider" in cmd
    assert captured["kwargs"]["env"]["PYTHONPATH"] == ""
    assert captured["kwargs"]["cwd"] == work


# --- collection errors (D-066) -----------------------------------------------------------------

@pytest.mark.parametrize("label, repo_kwargs, expect_in_detail", [
    ("SyntaxError in the student's file",
     {"load_py": "def insert_readings(conn, records):\n    hellot workd\n"},
     "SyntaxError at weather_etl/load.py"),
    ("the student removed a function the task needs",
     {"load_py": "x = 1\n"}, "cannot import name 'insert_readings'"),
    ("the student's module raises at import",
     {"load_py": "raise RuntimeError('boom at import')\n"},
     "RuntimeError at weather_etl/load.py"),
    ("the student deleted the whole package",
     {"load_py": None, "package": False}, "weather_etl"),
])
def test_a_student_caused_collection_error_is_a_real_failure(
        tmp_path, label, repo_kwargs, expect_in_detail):
    result = run(make_repo(tmp_path / "r", **repo_kwargs))
    assert result.status == "collection_error", label
    assert expect_in_detail in result.detail
    assert by_name(result) == {INSERT_TEST: False, SELECT_TEST: False}      # EVERY gap test
    assert {o.gap_id for o in result.outcomes} == {"g_ld_insert", "g_ld_select"}
    assert all(o.status == "collection_error" and not o.passed and expect_in_detail
               in o.message for o in result.outcomes)


def test_a_broken_hidden_test_file_is_tooling_not_a_failure(monkeypatch, tmp_path):
    broken = tmp_path / "broken_hidden.py"
    broken.write_text("def test(:\n", encoding="utf-8")                     # OUR file, bad syntax
    monkeypatch.setattr(tr, "_hidden_test_file", lambda *a: broken)
    result = run(make_repo(tmp_path / "r", load_py=SOLVED_LOAD))
    assert result.status == "tooling" and result.outcomes == ()
    assert "tests/hidden/broken_hidden.py" in result.detail


def test_a_missing_third_party_library_in_the_hidden_file_is_tooling(monkeypatch, tmp_path):
    needs_lib = tmp_path / "needs_lib_hidden.py"
    needs_lib.write_text("import not_a_real_library_xyz\n", encoding="utf-8")
    monkeypatch.setattr(tr, "_hidden_test_file", lambda *a: needs_lib)
    result = run(make_repo(tmp_path / "r", load_py=SOLVED_LOAD))
    assert result.status == "tooling" and "not_a_real_library_xyz" in result.detail


def test_a_solved_repo_still_grades_normally(tmp_path):
    result = run(make_repo(tmp_path / "r", load_py=SOLVED_LOAD))
    assert result.status == "ok" and by_name(result) == {INSERT_TEST: True, SELECT_TEST: True}


def test_classify_collection_error_defaults_to_tooling_when_it_cannot_tell(tmp_path):
    assert tr.classify_collection_error("collection failure\n", tmp_path)[0] == "tooling"
    assert tr.classify_collection_error("E   KeyError: 'x'", tmp_path)[0] == "tooling"


# --- recorded in the database (D-066) ----------------------------------------------------------

STUDENT = "_sandbox_student"


@pytest.fixture
def world():
    """One transaction, always rolled back: a student with an attempt that hides both
    weather_etl_load gaps, so both tests are genuine mastery evidence."""
    try:
        conn = db._open()
    except Exception as exc:  # noqa: BLE001 -- any connection failure means "skip"
        pytest.skip(f"database unreachable: {type(exc).__name__}")
    cur = conn.cursor()
    cur.execute("INSERT INTO students VALUES (%s,%s,'vdel-2026')", (STUDENT, STUDENT))
    variant_id = ensure_variant(cur, "weather_etl_load")
    cur.execute("INSERT INTO attempts (student_id, project_id, assignment_id, attempt_no,"
                " variant_id, gap_seed) VALUES (%s,'weather_etl','weather_etl_load',1,%s,1)"
                " RETURNING attempt_id", (STUDENT, variant_id))
    attempt_id = cur.fetchone()[0]
    yield conn, cur, attempt_id
    conn.rollback()
    conn.close()


def grade(conn, attempt_id, repo, sha="_sb_sha_1"):
    return tr.grade_attempt(PROJECT, "weather_etl_load", repo, attempt_id,
                            commit_sha=sha, conn=conn)


def rows(cur, attempt_id):
    cur.execute("SELECT test_name, gap_id, passed, status FROM test_results"
                " WHERE attempt_id=%s ORDER BY test_name", (attempt_id,))
    return cur.fetchall()


def test_a_collection_error_is_recorded_as_failed_tests_and_is_mastery_evidence(
        world, tmp_path):
    conn, cur, attempt_id = world
    repo = make_repo(tmp_path / "r", load_py="def insert_readings(c, r):\n    hellot workd\n")
    result = grade(conn, attempt_id, repo)

    assert (result.status, result.tests_passed, result.tests_total, result.frozen) == (
        "collection_error", 0, 2, False)
    assert sorted(rows(cur, attempt_id)) == sorted([
        (INSERT_TEST, "g_ld_insert", False, "collection_error"),
        (SELECT_TEST, "g_ld_select", False, "collection_error")])
    history = Memory().test_result_history(STUDENT, conn=conn)
    assert [h["passed"] for h in history] == [False, False]
    mastery = Memory().get_profile(STUDENT, conn=conn)["mastery"]
    assert mastery["sql.select_filter"]["n"] == 2

    grade(conn, attempt_id, repo)                          # the same commit again
    assert len(Memory().test_result_history(STUDENT, conn=conn)) == 2   # no double counting


def test_a_tooling_error_is_a_marker_not_a_failure_and_is_not_retried(
        world, monkeypatch, tmp_path):
    conn, cur, attempt_id = world
    broken = tmp_path / "broken_hidden.py"
    broken.write_text("def test(:\n", encoding="utf-8")
    monkeypatch.setattr(tr, "_hidden_test_file", lambda *a: broken)
    result = grade(conn, attempt_id, make_repo(tmp_path / "r", load_py=SOLVED_LOAD))

    assert (result.status, result.tests_total, result.frozen) == ("tooling", 0, False)
    assert rows(cur, attempt_id) == [
        ("tests/hidden/test_load.py::<collection>", None, False, "tooling")]
    assert Memory().test_result_history(STUDENT, conn=conn) == []        # no evidence
    assert "sql.select_filter" not in Memory().get_profile(STUDENT, conn=conn)["mastery"]
    cur.execute("SELECT submitted_at FROM attempts WHERE attempt_id=%s", (attempt_id,))
    assert cur.fetchone()[0] is None                                      # nothing froze
    cur.execute("SELECT NOT EXISTS (SELECT 1 FROM test_results WHERE attempt_id=%s"
                " AND commit_sha=%s)", (attempt_id, "_sb_sha_1"))
    assert cur.fetchone()[0] is False                # grade_collected will not pick it up again


def test_diagnose_does_not_show_a_tooling_marker_as_a_failing_test(world, monkeypatch, tmp_path):
    conn, cur, attempt_id = world
    broken = tmp_path / "broken_hidden.py"
    broken.write_text("def test(:\n", encoding="utf-8")
    monkeypatch.setattr(tr, "_hidden_test_file", lambda *a: broken)
    grade(conn, attempt_id, make_repo(tmp_path / "r", load_py=SOLVED_LOAD))
    result = diagnose(cur, attempt_id)
    assert result.failing_tests == () and result.weakest_concept is None


# --- pinned against REAL captured pytest 9.1 output (D-066) ------------------------------------
# Captured from a real run (paths shortened); if a pytest upgrade changes the format, these
# fail loudly instead of the classifier silently drifting to "tooling".

CAPTURED_IMPORT_ERROR = """collection failure
ImportError while importing test module '{root}/tests/hidden/test_load.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
../Lib/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/hidden/test_load.py:3: in <module>
    from weather_etl.load import insert_readings
E   ImportError: cannot import name 'insert_readings' from 'weather_etl.load'
"""
CAPTURED_STUDENT_RAISES = """collection failure
tests/hidden/test_load.py:3: in <module>
    from weather_etl.load import insert_readings
weather_etl/load.py:1: in <module>
    raise RuntimeError('boom at import')
E   RuntimeError: boom at import
"""
CAPTURED_OUR_FILE_BROKEN = """collection failure
ImportError while importing test module '{root}/tests/hidden/test_load.py'.
Traceback:
tests/hidden/test_load.py:1: in <module>
    import not_a_real_lib_xyz
E   ModuleNotFoundError: No module named 'not_a_real_lib_xyz'
"""


@pytest.mark.parametrize("text, expected", [
    (CAPTURED_IMPORT_ERROR, "collection_error"),
    (CAPTURED_STUDENT_RAISES, "collection_error"),
    (CAPTURED_OUR_FILE_BROKEN, "tooling"),
])
def test_classifier_on_captured_pytest_output(tmp_path, text, expected):
    make_repo(tmp_path / "r")
    root = (tmp_path / "r").as_posix()
    status, _ = tr.classify_collection_error(
        text.format(root=root), tmp_path / "r", ("weather_etl",))
    assert status == expected
