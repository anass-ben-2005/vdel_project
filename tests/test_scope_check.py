"""assessment/scope_check.py tests. VDEL_REDESIGN.md 8.2, CLAUDE.md invariant 14
(not 13 -- see scope_check.py's own header for the citation correction).
"""

from __future__ import annotations

from assessment.scope_check import ScopeReport, filter_lint_findings, scope_check

# ---------- edit only inside a gap ----------

def test_edit_only_inside_a_gap():
    released = (
        "def run():\n"
        "    total = 0\n"
        "    raise NotImplementedError()\n"   # line 3 -- the gap
        "    return total\n"
    )
    submitted = (
        "def run():\n"
        "    total = 0\n"
        "    total += 1\n"                     # replaced, still 1 line
        "    return total\n"
    )
    report = scope_check(released, submitted, gap_ranges=[(3, 3)])
    assert report == ScopeReport(
        in_gap_lines_changed=1,
        out_of_scope_lines_changed=0,
        out_of_scope_line_numbers=(),
        changed_loc_in_gap=1,
    )


# ---------- edit only outside a gap ----------

def test_edit_only_outside_a_gap():
    released = (
        "def run():\n"
        "    total = 0\n"
        "    raise NotImplementedError()\n"   # line 3 -- the gap, untouched
        "    return total\n"
    )
    submitted = (
        "def run():\n"
        "    total = 999\n"                    # out-of-scope edit, line 2
        "    raise NotImplementedError()\n"
        "    return total\n"
    )
    report = scope_check(released, submitted, gap_ranges=[(3, 3)])
    assert report == ScopeReport(
        in_gap_lines_changed=0,
        out_of_scope_lines_changed=1,
        out_of_scope_line_numbers=(2,),
        changed_loc_in_gap=0,
    )


# ---------- both: in-gap and out-of-scope edits together ----------

def test_edit_both_inside_and_outside_a_gap():
    """The out-of-scope edit sits on the line DIRECTLY ABOVE the gap, with no unchanged
    line between them -- difflib therefore merges both into ONE opcode (verified live
    during review: a single ('replace', 1, 3, 1, 3), not two separate ones). Per
    scope_check's own documented conservative rule, a block that isn't FULLY inside one
    gap is classified entirely out-of-scope -- the in-gap edit does not get credited,
    because this module cannot verify it stayed cleanly inside the gap once merged with
    an adjacent edit it can't separate from. See test_..._with_an_anchor_line below for
    the case where a genuine unchanged line DOES separate them, and precise attribution
    is possible."""
    released = (
        "def run():\n"
        "    total = 0\n"
        "    raise NotImplementedError()\n"   # line 3 -- the gap
        "    return total\n"
    )
    submitted = (
        "def run():\n"
        "    total = 999\n"                    # out-of-scope, line 2
        "    total += 1\n"                      # in-gap, line 3 -- merges with line 2
        "    return total\n"
    )
    report = scope_check(released, submitted, gap_ranges=[(3, 3)])
    assert report.in_gap_lines_changed == 0
    assert report.out_of_scope_lines_changed == 2
    assert report.out_of_scope_line_numbers == (2, 3)
    assert report.changed_loc_in_gap == 0


def test_adjacent_in_gap_and_out_of_scope_edits_with_an_anchor_line_split_precisely():
    """Same edit intent as the test above, but with ONE unchanged line separating the
    out-of-scope edit FROM the gap (not merely before both of them -- the anchor has to
    sit BETWEEN the two edits to break them into separate opcodes) -- difflib now reports
    two separate opcodes, and each is attributed precisely instead of conservatively."""
    released = (
        "def run():\n"                        # line 1
        "    x = 1\n"                          # line 2
        "    total = 0\n"                      # line 3 -- will be edited, out-of-scope
        "    marker = True\n"                  # line 4 -- anchor, BETWEEN the two edits
        "    raise NotImplementedError()\n"    # line 5 -- the gap
        "    return total\n"                   # line 6
    )
    submitted = (
        "def run():\n"
        "    x = 1\n"
        "    total = 999\n"                     # out-of-scope, line 3
        "    marker = True\n"
        "    total += 1\n"                       # in-gap, line 5
        "    return total\n"
    )
    report = scope_check(released, submitted, gap_ranges=[(5, 5)])
    assert report.in_gap_lines_changed == 1
    assert report.out_of_scope_lines_changed == 1
    assert report.out_of_scope_line_numbers == (3,)


def test_out_of_scope_edit_before_and_after_the_gap():
    """Praiseworthy-fix / integrity-signal case (VDEL_REDESIGN.md 8.2 point 2): a student
    edits both before and after their gap. Written with NO anchor line separating any of
    the three edits (matching test_adjacent_..._merge above, not its anchored
    counterpart), so all three merge into one conservatively-out-of-scope block -- this
    is the honest behaviour, not the idealised "each counted separately" a first draft
    of this test assumed without checking against the real opcodes."""
    released = (
        "def run():\n"                        # line 1
        "    total = 0\n"                      # line 2
        "    raise NotImplementedError()\n"    # line 3 -- the gap
        "    print(total)\n"                   # line 4
        "    return total\n"                   # line 5
    )
    submitted = (
        "def run():\n"
        "    total = 100\n"                     # out-of-scope, line 2
        "    total += 1\n"                      # in-gap, line 3
        "    print(total * 2)\n"                # out-of-scope, line 4
        "    return total\n"
    )
    report = scope_check(released, submitted, gap_ranges=[(3, 3)])
    assert report.in_gap_lines_changed == 0
    assert report.out_of_scope_lines_changed == 3
    assert report.out_of_scope_line_numbers == (2, 3, 4)


def test_out_of_scope_edits_before_and_after_a_gap_with_anchors_split_precisely():
    """Unlike test_out_of_scope_edit_before_and_after_the_gap above, an anchor line sits
    BETWEEN each edit and the gap on both sides -- so all three edits stay in separate
    opcodes and are each attributed precisely."""
    released = (
        "def run():\n"                        # line 1
        "    x = 1\n"                          # line 2
        "    total = 0\n"                      # line 3 -- out-of-scope
        "    marker1 = True\n"                 # line 4 -- anchor
        "    raise NotImplementedError()\n"    # line 5 -- the gap
        "    marker2 = True\n"                 # line 6 -- anchor
        "    print(total)\n"                   # line 7 -- out-of-scope
        "    return total\n"                   # line 8
    )
    submitted = (
        "def run():\n"
        "    x = 1\n"
        "    total = 100\n"                     # out-of-scope, line 3
        "    marker1 = True\n"
        "    total += 1\n"                       # in-gap, line 5
        "    marker2 = True\n"
        "    print(total * 2)\n"                 # out-of-scope, line 7
        "    return total\n"
    )
    report = scope_check(released, submitted, gap_ranges=[(5, 5)])
    assert report.in_gap_lines_changed == 1
    assert report.out_of_scope_lines_changed == 2
    assert report.out_of_scope_line_numbers == (3, 7)


# ---------- the line-shift case, as a permanent test ----------

def test_line_shift_after_a_gap_that_grows_does_not_misattribute_trailing_lines():
    """The scenario demonstrated live during review: a 1-line gap replaced by a 4-line
    fix. Every line after the gap shifts by +3 in the submission; none of them may be
    reported as out-of-scope just because their line NUMBER changed -- difflib aligns by
    content, so unchanged trailing lines stay classified as unchanged regardless of where
    they now sit."""
    released = (
        "def run():\n"                       # line 1
        "    total = 0\n"                    # line 2
        "    raise NotImplementedError()\n"  # line 3 -- the 1-line gap
        "    print(total)\n"                 # line 4
        "    return total\n"                 # line 5
        "    log('done')\n"                  # line 6
    )
    submitted = (
        "def run():\n"
        "    total = 0\n"
        "    for x in range(3):\n"            # student's 4-line fix, lines 3-6
        "        total += x\n"
        "        total *= 2\n"
        "    total += 1\n"
        "    print(total)\n"                  # unchanged, now line 7 (was released line 4)
        "    return total\n"                  # unchanged, now line 8 (was released line 5)
        "    log('done')\n"                   # unchanged, now line 9 (was released line 6)
    )
    report = scope_check(released, submitted, gap_ranges=[(3, 3)])
    assert report.in_gap_lines_changed == 4
    assert report.out_of_scope_lines_changed == 0
    assert report.out_of_scope_line_numbers == ()
    assert report.changed_loc_in_gap == 4


def test_line_shift_with_a_genuine_out_of_scope_edit_after_a_growing_gap():
    """Same shift as above, but the student ALSO edits a trailing line -- that edit must
    be reported at its true SUBMITTED line number (post-shift), not the released one. An
    unchanged anchor line sits between the gap and the edited line so the two edits stay
    in separate opcodes (see test_edit_both_inside_and_outside_a_gap for what happens
    without one) -- this test is specifically about shift, not about the merge rule."""
    released = (
        "def run():\n"                       # line 1
        "    total = 0\n"                    # line 2
        "    raise NotImplementedError()\n"  # line 3 -- the 1-line gap
        "    marker = True\n"                # line 4 -- anchor, stays unchanged
        "    print(total)\n"                 # line 5 -- will be edited out of scope
        "    return total\n"                 # line 6
    )
    submitted = (
        "def run():\n"
        "    total = 0\n"
        "    for x in range(3):\n"            # in-gap, lines 3-5
        "        total += x\n"
        "        total *= 2\n"
        "    marker = True\n"                 # unchanged anchor, now line 6
        "    print(total * 2)\n"              # out-of-scope, NOW line 7 (was released line 5)
        "    return total\n"                  # unchanged, now line 8
    )
    report = scope_check(released, submitted, gap_ranges=[(3, 3)])
    assert report.in_gap_lines_changed == 3
    assert report.out_of_scope_lines_changed == 1
    assert report.out_of_scope_line_numbers == (7,)   # the SUBMITTED line, not released line 5


def test_line_shift_when_the_gap_shrinks():
    """The inverse shift: a multi-line gap collapsed to fewer lines. Trailing content
    moves EARLIER, and must still not be misattributed."""
    released = (
        "def run():\n"                        # line 1
        "    # step 1\n"                       # line 2 -- gap start
        "    a = 1\n"                          # line 3
        "    b = 2\n"                          # line 4
        "    c = 3\n"                          # line 5 -- gap end
        "    return a + b + c\n"               # line 6
    )
    submitted = (
        "def run():\n"
        "    total = 6\n"                       # in-gap, replaces lines 2-5 with 1 line
        "    return a + b + c\n"                # unchanged, now line 3 (was released line 6)
    )
    report = scope_check(released, submitted, gap_ranges=[(2, 5)])
    assert report.in_gap_lines_changed == 1
    assert report.out_of_scope_lines_changed == 0
    assert report.out_of_scope_line_numbers == ()


# ---------- no edits at all ----------

def test_no_edits_at_all():
    released = (
        "def run():\n"
        "    total = 0\n"
        "    raise NotImplementedError()\n"
        "    return total\n"
    )
    report = scope_check(released, released, gap_ranges=[(3, 3)])
    assert report == ScopeReport(
        in_gap_lines_changed=0,
        out_of_scope_lines_changed=0,
        out_of_scope_line_numbers=(),
        changed_loc_in_gap=0,
    )


# ---------- pure deletion, in and out of scope ----------

def test_pure_deletion_inside_a_gap_is_counted():
    released = (
        "def run():\n"
        "    a = 1\n"     # line 2 -- gap
        "    b = 2\n"     # line 3 -- gap
        "    return a + b\n"
    )
    submitted = (
        "def run():\n"
        "    a = 1\n"      # line 2 kept, line 3 deleted
        "    return a + b\n"
    )
    report = scope_check(released, submitted, gap_ranges=[(2, 3)])
    assert report.in_gap_lines_changed == 1
    assert report.out_of_scope_lines_changed == 0


def test_pure_deletion_outside_a_gap_counts_but_has_no_submitted_line_number():
    """A deleted out-of-scope line has nothing left in the submission to point at --
    it must still count toward out_of_scope_lines_changed, honestly, without inventing
    a submitted line number that doesn't exist. Separated from the gap by an anchor line
    so this registers as a genuine difflib 'delete' opcode (i1:i2 non-empty, j1==j2) --
    directly adjacent to the gap it would merge into a 'replace' instead (same rule as
    test_edit_both_inside_and_outside_a_gap), which is a different case already covered."""
    released = (
        "def run():\n"
        "    debug_print()\n"                  # line 2 -- deleted, out of scope
        "    marker = True\n"                  # line 3 -- anchor, stays unchanged
        "    raise NotImplementedError()\n"     # line 4 -- gap
        "    return 1\n"
    )
    submitted = (
        "def run():\n"
        "    marker = True\n"
        "    x = 1\n"                            # in-gap replacement
        "    return 1\n"
    )
    report = scope_check(released, submitted, gap_ranges=[(4, 4)])
    assert report.out_of_scope_lines_changed == 1
    assert report.out_of_scope_line_numbers == ()   # nothing to point at in the submission
    assert report.in_gap_lines_changed == 1


# ---------- filter_lint_findings ----------

def test_filter_lint_findings_keeps_only_in_gap_findings():
    findings = [
        {"code": "F401", "message": "unused import", "line": 1,
         "column": 1, "severity": "error"},
        {"code": "E501", "message": "line too long", "line": 3,
         "column": 80, "severity": "warning"},
        {"code": "B006", "message": "mutable default", "line": 7,
         "column": 5, "severity": "error"},
    ]
    kept = filter_lint_findings(findings, gap_ranges=[(3, 3), (6, 8)])
    assert kept == [findings[1], findings[2]]


def test_filter_lint_findings_excludes_a_finding_with_no_line_number():
    findings = [
        {"code": "PLR", "message": "file-level issue", "line": None,
         "column": None, "severity": "error"},
    ]
    assert filter_lint_findings(findings, gap_ranges=[(1, 100)]) == []


def test_filter_lint_findings_with_no_gaps_keeps_nothing():
    findings = [{"code": "F401", "message": "x", "line": 5, "column": 1, "severity": "error"}]
    assert filter_lint_findings(findings, gap_ranges=[]) == []
