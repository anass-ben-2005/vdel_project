"""assessment/gap_generator.py tests. VDEL_REDESIGN.md C2/C3, A4.

Concept ids are real (config/concepts.yaml): py.testing, airflow.idempotency,
py.errors_debugging -- same discipline as tests/test_gap_parser.py.
"""

from __future__ import annotations

import subprocess
import sys

from assessment.gap_generator import _compute_variant_id, compute_seed, select_variant
from assessment.gap_parser import Gap


def gap(gap_id, *concept_ids, line=1):
    """A minimal Gap for selection tests -- body/instruction/difficulty are irrelevant to
    select_variant, which only ever reads gap_id and concept_ids."""
    return Gap(gap_id, tuple(concept_ids), line, line, "instruction", 0.5, "body")


# ---------- compute_seed ----------

def test_seed_is_deterministic_within_a_process():
    a = compute_seed("anas", "a1", 1)
    b = compute_seed("anas", "a1", 1)
    assert a == b


def test_seed_is_an_int():
    assert isinstance(compute_seed("anas", "a1", 1), int)


def test_seed_differs_by_student():
    assert compute_seed("anas", "a1", 1) != compute_seed("mira", "a1", 1)


def test_seed_differs_by_assignment():
    assert compute_seed("anas", "a1", 1) != compute_seed("anas", "a2", 1)


def test_seed_differs_by_attempt_no():
    assert compute_seed("anas", "a1", 1) != compute_seed("anas", "a1", 2)


def test_field_separator_prevents_boundary_collision():
    """Without a separator that can't appear inside a field, ("ab", "c") and ("a", "bc")
    would hash identically -- the \\x1f choice exists specifically to prevent this."""
    assert compute_seed("ab", "c", 1) != compute_seed("a", "bc", 1)


def test_seed_is_deterministic_across_separate_python_processes():
    """The property that actually matters: hashlib survives a fresh interpreter
    (fresh PYTHONHASHSEED); Python's builtin hash() would not have. A permanent,
    automated version of the two `python -c` invocations run by hand during review."""
    script = (
        "from assessment.gap_generator import compute_seed;"
        "print(compute_seed('anas', 'a1', 1))"
    )
    results = {
        subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=True,
        ).stdout.strip()
        for _ in range(2)
    }
    assert len(results) == 1, f"seed differed across processes: {results}"


# ---------- _compute_variant_id ----------

def test_variant_id_matches_c2s_formula_exactly():
    import hashlib
    expected = hashlib.sha1(b"a1|g_a,g_b|deadbeef").hexdigest()
    assert _compute_variant_id("a1", ["g_a", "g_b"], "deadbeef") == expected


def test_variant_id_is_order_independent_in_gap_ids():
    """C2: `sorted(gap_ids)`. The caller's iteration order must not matter."""
    assert (
        _compute_variant_id("a1", ["g_b", "g_a"], "deadbeef")
        == _compute_variant_id("a1", ["g_a", "g_b"], "deadbeef")
    )


def test_variant_id_changes_with_master_version():
    assert (
        _compute_variant_id("a1", ["g_a"], "v1")
        != _compute_variant_id("a1", ["g_a"], "v2")
    )


def test_variant_id_changes_with_assignment_id():
    assert (
        _compute_variant_id("a1", ["g_a"], "v1")
        != _compute_variant_id("a2", ["g_a"], "v1")
    )


# ---------- select_variant: adaptive selection ----------

def test_lowest_mastery_concept_is_selected_when_all_qualify():
    gaps = [gap("g_a", "py.testing", line=1), gap("g_b", "airflow.idempotency", line=2)]
    mastery = {"py.testing": 0.2, "airflow.idempotency": 0.8}
    n_obs = {"py.testing": 5, "airflow.idempotency": 5}

    _, gap_ids = select_variant(
        gaps, assignment_id="a1", master_version="v1", student_id="anas", attempt_no=1,
        mastery_by_concept=mastery, n_obs_by_concept=n_obs,
    )
    assert gap_ids == ("g_a",)   # py.testing has the lower mastery


def test_tied_mastery_breaks_by_concept_id_not_dict_order():
    gaps = [gap("g_a", "py.testing", line=1), gap("g_b", "airflow.idempotency", line=2)]
    mastery = {"py.testing": 0.5, "airflow.idempotency": 0.5}   # exact tie
    n_obs = {"py.testing": 5, "airflow.idempotency": 5}

    _, gap_ids = select_variant(
        gaps, assignment_id="a1", master_version="v1", student_id="anas", attempt_no=1,
        mastery_by_concept=mastery, n_obs_by_concept=n_obs,
    )
    assert gap_ids == ("g_b",)   # "airflow.idempotency" < "py.testing" alphabetically


def test_qualifying_threshold_is_inclusive_at_three():
    """VDEL_REDESIGN.md C3: 'n_obs < 3' is the fallback condition, so n_obs == 3 must
    already qualify for adaptive selection, not still be treated as insufficient."""
    gaps = [gap("g_a", "py.testing", line=1), gap("g_b", "airflow.idempotency", line=2)]
    mastery = {"py.testing": 0.2, "airflow.idempotency": 0.8}
    n_obs = {"py.testing": 3, "airflow.idempotency": 3}   # exactly at the boundary

    _, gap_ids = select_variant(
        gaps, assignment_id="a1", master_version="v1", student_id="anas", attempt_no=1,
        mastery_by_concept=mastery, n_obs_by_concept=n_obs,
    )
    assert gap_ids == ("g_a",)   # adaptive fired; lowest mastery won


# ---------- select_variant: uniform fallback, proven not just asserted ----------

def test_uniform_fallback_can_pick_the_higher_mastery_concept():
    """If this only ever picked the lowest-mastery concept, it would still be silently
    adaptive under a different name. attempt_no=4 (found by scanning attempt_no 0..19,
    see review) picks airflow.idempotency here even though it has the HIGHER mastery --
    real evidence the fallback path is not adaptive selection in disguise."""
    gaps = [gap("g_a", "py.testing", line=1), gap("g_b", "airflow.idempotency", line=2)]
    mastery = {"py.testing": 0.2, "airflow.idempotency": 0.9}   # py.testing still "better" pick
    n_obs = {"py.testing": 0, "airflow.idempotency": 0}          # both below threshold -> fallback

    _, gap_ids = select_variant(
        gaps, assignment_id="a1", master_version="v1", student_id="anas", attempt_no=4,
        mastery_by_concept=mastery, n_obs_by_concept=n_obs,
    )
    assert gap_ids == ("g_b",)


def test_uniform_fallback_visits_more_than_one_concept_across_attempts():
    gaps = [gap("g_a", "py.testing", line=1), gap("g_b", "airflow.idempotency", line=2)]
    mastery = {"py.testing": 0.2, "airflow.idempotency": 0.9}
    n_obs = {"py.testing": 0, "airflow.idempotency": 0}

    seen = {
        select_variant(
            gaps, assignment_id="a1", master_version="v1", student_id="anas",
            attempt_no=n, mastery_by_concept=mastery, n_obs_by_concept=n_obs,
        )[1]
        for n in range(20)
    }
    assert seen == {("g_a",), ("g_b",)}


# ---------- select_variant: gaps are bundled by concept, not picked one at a time ----------

def test_every_gap_tagged_with_the_chosen_concept_is_bundled():
    gaps = [
        gap("g_a", "py.testing", line=1),
        gap("g_b", "py.testing", line=2),
        gap("g_c", "py.testing", line=3),
        gap("g_d", "airflow.idempotency", line=4),
    ]
    mastery = {"py.testing": 0.1, "airflow.idempotency": 0.9}
    n_obs = {"py.testing": 5, "airflow.idempotency": 5}

    _, gap_ids = select_variant(
        gaps, assignment_id="a1", master_version="v1", student_id="anas", attempt_no=1,
        mastery_by_concept=mastery, n_obs_by_concept=n_obs,
    )
    assert gap_ids == ("g_a", "g_b", "g_c")   # all three, sorted -- none of g_d


def test_single_gap_variant_falls_out_naturally():
    """A concept tagged on exactly one gap produces a one-element variant without any
    special-casing -- this is the scope-correction's own claim, checked directly."""
    gaps = [gap("g_a", "py.testing", line=1), gap("g_b", "airflow.idempotency", line=2)]
    mastery = {"py.testing": 0.9, "airflow.idempotency": 0.1}
    n_obs = {"py.testing": 5, "airflow.idempotency": 5}

    _, gap_ids = select_variant(
        gaps, assignment_id="a1", master_version="v1", student_id="anas", attempt_no=1,
        mastery_by_concept=mastery, n_obs_by_concept=n_obs,
    )
    assert gap_ids == ("g_b",)


def test_a_gap_tagged_with_two_concepts_can_be_pulled_in_by_either():
    gaps = [
        gap("g_shared", "py.testing", "airflow.idempotency", line=1),
        gap("g_other", "py.testing", line=2),
    ]
    mastery = {"py.testing": 0.9, "airflow.idempotency": 0.1}   # airflow wins
    n_obs = {"py.testing": 5, "airflow.idempotency": 5}

    _, gap_ids = select_variant(
        gaps, assignment_id="a1", master_version="v1", student_id="anas", attempt_no=1,
        mastery_by_concept=mastery, n_obs_by_concept=n_obs,
    )
    assert gap_ids == ("g_shared",)   # only the gap tagged with the chosen concept


# ---------- determinism and order-independence, end to end ----------

def test_select_variant_is_deterministic_within_a_process():
    gaps = [gap("g_a", "py.testing", line=1), gap("g_b", "airflow.idempotency", line=2)]
    mastery = {"py.testing": 0.2, "airflow.idempotency": 0.8}
    n_obs = {"py.testing": 5, "airflow.idempotency": 5}
    kwargs = {
        "assignment_id": "a1", "master_version": "v1", "student_id": "anas", "attempt_no": 1,
        "mastery_by_concept": mastery, "n_obs_by_concept": n_obs,
    }
    assert select_variant(gaps, **kwargs) == select_variant(gaps, **kwargs)


def test_select_variant_is_deterministic_across_separate_python_processes():
    script = (
        "from assessment.gap_parser import Gap;"
        "from assessment.gap_generator import select_variant;"
        "gaps = [Gap('g_a', ('py.testing',), 1, 1, 'i', 0.5, 'b'),"
        " Gap('g_b', ('airflow.idempotency',), 2, 2, 'i', 0.5, 'b')];"
        "print(select_variant(gaps, assignment_id='a1', master_version='v1',"
        " student_id='anas', attempt_no=1,"
        " mastery_by_concept={'py.testing': 0.2, 'airflow.idempotency': 0.8},"
        " n_obs_by_concept={'py.testing': 5, 'airflow.idempotency': 5}))"
    )
    results = {
        subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, check=True,
        ).stdout.strip()
        for _ in range(2)
    }
    assert len(results) == 1, f"selection differed across processes: {results}"


def test_result_does_not_depend_on_the_order_gaps_are_supplied_in():
    forward = [
        gap("g_a", "py.testing", line=1),
        gap("g_b", "py.testing", line=2),
        gap("g_c", "airflow.idempotency", line=3),
    ]
    reversed_ = list(reversed(forward))
    mastery = {"py.testing": 0.2, "airflow.idempotency": 0.8}
    n_obs = {"py.testing": 5, "airflow.idempotency": 5}
    kwargs = {
        "assignment_id": "a1", "master_version": "v1", "student_id": "anas", "attempt_no": 1,
        "mastery_by_concept": mastery, "n_obs_by_concept": n_obs,
    }
    assert select_variant(forward, **kwargs) == select_variant(reversed_, **kwargs)


def test_result_does_not_depend_on_a_generator_vs_a_list():
    """gaps: Iterable[Gap] -- must work identically whether the caller passes a list or
    a one-shot generator, since a generator has no inherent 'order' guarantee to lean on
    beyond what it yields, and this function must not assume list-like re-iterability
    without converting first (it does: `gaps = list(gaps)`)."""
    def gen():
        yield gap("g_a", "py.testing", line=1)
        yield gap("g_b", "airflow.idempotency", line=2)

    mastery = {"py.testing": 0.2, "airflow.idempotency": 0.8}
    n_obs = {"py.testing": 5, "airflow.idempotency": 5}
    kwargs = {
        "assignment_id": "a1", "master_version": "v1", "student_id": "anas", "attempt_no": 1,
        "mastery_by_concept": mastery, "n_obs_by_concept": n_obs,
    }
    from_list = select_variant([gap("g_a", "py.testing", line=1),
                                 gap("g_b", "airflow.idempotency", line=2)], **kwargs)
    from_gen = select_variant(gen(), **kwargs)
    assert from_list == from_gen


# ---------- edge cases ----------

def test_no_gaps_with_any_concept_raises():
    gaps = [gap("g_a", line=1)]   # no concept_ids at all
    try:
        select_variant(
            gaps, assignment_id="a1", master_version="v1", student_id="anas",
            attempt_no=1, mastery_by_concept={}, n_obs_by_concept={},
        )
    except ValueError as exc:
        assert "concept" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_unseen_concept_defaults_to_zero_obs_and_zero_mastery():
    """A concept with no entry in n_obs_by_concept/mastery_by_concept is exactly the
    cold-start case (no observations yet) -- must fall back to uniform, not raise
    a KeyError."""
    gaps = [gap("g_a", "py.testing", line=1)]
    _, gap_ids = select_variant(
        gaps, assignment_id="a1", master_version="v1", student_id="anas", attempt_no=1,
        mastery_by_concept={}, n_obs_by_concept={},
    )
    assert gap_ids == ("g_a",)


# ---------- real curriculum content: Project 2 (sales_analyzer) ----------
# VDEL_TEN_PROJECT_CURRICULUM.md §3. Reuses this file's existing harness (real Gap
# objects, select_variant called the same way as every synthetic test above) against
# gaps parsed from the real master file, via parse_master -- not a hand-built parallel
# fixture that could silently drift from what parse_master actually produces.

def test_select_variant_on_sales_analyzer_clean_py_is_deterministic_and_reproducible():
    from pathlib import Path

    from assessment.gap_parser import parse_master

    path = (
        Path(__file__).resolve().parent.parent
        / "curriculum" / "master" / "sales_analyzer" / "sales_analyzer" / "clean.py"
    )
    gaps = parse_master(path)   # g_cl_dedupe, g_cl_fillna -- both py.pandas

    kwargs = {
        "assignment_id": "sales_analyzer_clean", "master_version": "test_mv",
        "student_id": "anas", "attempt_no": 1,
        "mastery_by_concept": {}, "n_obs_by_concept": {},
    }
    first = select_variant(gaps, **kwargs)
    second = select_variant(gaps, **kwargs)
    assert first == second   # same inputs -> same variant, every time

    variant_id, hidden_gap_ids = first
    assert set(hidden_gap_ids) <= {"g_cl_dedupe", "g_cl_fillna"}
    assert hidden_gap_ids   # at least one gap chosen -- never an empty variant
    assert isinstance(variant_id, str) and variant_id
