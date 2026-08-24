"""assessment/gap_generator.py -- seeded, adaptive-then-random variant selection.

VDEL_REDESIGN.md C3: "Select the *concept* by lowest BKT mastery among the assignment's
tagged concepts; select the *variant* uniformly among templates tagged with that
concept. Fall back to uniform when n_obs < 3 everywhere." (Verified verbatim against
VDEL_REDESIGN.md C3.) A4 names this "seeded, adaptive-then-random, persisted." Note the
phase this module is being built at: 14 Phase 1 step 6 says "seeded, uniform for now
(adaptive in Phase 4)" -- this file implements the adaptive selection now, not the phase-1
stub, per direct instruction.

It also deliberately diverges from C3's SECOND clause: C3 picks one template from among
those tagged with the chosen concept; this module hides ALL of them together as one group.
That is D-042 -- `select_variant`'s own docstring records both the decision and the fact
that the justifications offered for it could not be verified against any document here.

Section 14's own DoD line for this module: "two students, same assignment, demonstrably
different variants, both reconstructible from (seed, master_version)." Two separate
concerns, kept separate here: `master_version` selects WHICH pool of gaps exists to
choose from (sql/06: every gap/variant row pins one); the seed is what deterministically
picks among that pool for one student's one attempt.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterable, Mapping

from assessment.gap_parser import Gap

# VDEL_REDESIGN.md C3: "Fall back to uniform when n_obs < 3 everywhere."
_MIN_OBS_FOR_ADAPTIVE = 3

# ASCII unit separator (0x1F), not "|" or ",": student_id is a GitHub username and
# assignment_id is free text elsewhere in the schema (sql/01), neither is constrained
# against containing a literal "|". A field separator that can appear IN a field turns
# ("ab", "c") and ("a", "bc") into the same key -- a real collision, not a theoretical one.
# \x1f cannot appear in either field in practice and is the character POSIX itself
# reserves for exactly this job.
_FIELD_SEP = "\x1f"


def compute_seed(student_id: str, assignment_id: str, attempt_no: int) -> int:
    """The exact, sole seed construction for gap/variant selection -- every caller in
    this module must go through this function; there must be only one formula, not one
    per call site that could quietly drift apart (the same argument DECISIONS.md D-007
    makes for mastery, applied here to a third piece of state: seed, features_ref via
    memory.Memory.sync_features_ref, and now this).

    hashlib.sha256, NOT Python's builtin hash(): since Python 3.3 (PEP 456 / the
    hash-flooding CVEs it followed), str/bytes hash() is salted per-process from
    PYTHONHASHSEED, which is randomised at interpreter startup unless explicitly pinned.
    Two separate `python -c` invocations of the identical script would get two DIFFERENT
    seeds from hash() for the identical input -- silently. That failure would not show up
    in a single test run (one process, one hash seed for the whole run) and would only
    surface as "why did this student get a different variant when we regenerated their
    repo" days later. hashlib has no such salt; sha256(key) is bit-identical for the same
    key on any machine, any process, any Python version that implements SHA-256
    correctly, which is the actual property "reconstructible from (seed, master_version)"
    requires.

    Order-independence: every input is already scalar (a string, a string, an int) --
    there is no dict or set anywhere in this function for iteration order to affect. The
    functions later in this module that DO iterate a collection (candidate concepts,
    candidate gaps) must sort it before using this seed to choose from it; sorting is
    enforced there, not here, because this function has nothing to sort.
    """
    key = f"{student_id}{_FIELD_SEP}{assignment_id}{_FIELD_SEP}{attempt_no}".encode()
    digest = hashlib.sha256(key).digest()
    # First 8 bytes -> a signed 64-bit int. Big-endian is arbitrary but fixed: any
    # deterministic byte order works, and "arbitrary but fixed and documented" is the
    # actual requirement, not a specific endianness. SIGNED, not unsigned (found
    # necessary persisting this into sql/06's `attempts.gap_seed BIGINT` -- Postgres
    # BIGINT is signed 64-bit, and an unsigned 8-byte int overflows it roughly half the
    # time with `NumericValueOutOfRange`). random.Random(seed) treats a negative int
    # exactly as validly as a positive one, so this changes nothing about selection --
    # it only makes the same one seed value directly storable where it's used.
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _compute_variant_id(assignment_id: str, gap_ids: Iterable[str], master_version: str) -> str:
    """VDEL_REDESIGN.md C2, transcribed exactly: `variant_id = sha1(assignment_id ||
    sorted(gap_ids) || master_version)`. sha1, not sha256 -- C2 specifies sha1 by name for
    this one value; `compute_seed` above uses sha256 for a different value (the RNG seed)
    that C2/C3 do not name a hash for, so that choice is this module's own, not C2's.

    `sorted(gap_ids)` is C2's own words, not an addition -- two gaps chosen in a different
    ORDER must still hash to the same variant_id, because "order chosen" isn't part of
    what a variant IS. Sorting here, not trusting the caller to have already sorted, is
    what makes that guarantee hold regardless of what iterable the caller passes.
    """
    key = f"{assignment_id}|{','.join(sorted(gap_ids))}|{master_version}".encode()
    return hashlib.sha1(key).hexdigest()


def select_variant(
    gaps: Iterable[Gap],
    *,
    assignment_id: str,
    master_version: str,
    student_id: str,
    attempt_no: int,
    mastery_by_concept: Mapping[str, float],
    n_obs_by_concept: Mapping[str, int],
) -> tuple[str, tuple[str, ...]]:
    """C3's adaptive-then-random selection. Returns `(variant_id, chosen_gap_ids)`.

    REVISED scope (D-042): a variant is the CONCEPT's whole group, not one gap picked from
    it -- when a concept is selected, EVERY gap in this assignment tagged with that concept
    is hidden together. This DIVERGES from C3 as quoted in this module's header, which says
    "select the *variant* uniformly among templates tagged with that concept" -- i.e. one
    template picked from among several. The reversal was made on Anas's direct authority.

    The justifications offered for it at the time -- that the 19 Aug supervisor meeting
    judged a single hidden region "too easy," and that VDEL_REDESIGN.md itself calls a
    variant "a coherent, concept-tagged region" -- COULD NOT BE VERIFIED: neither phrase
    appears anywhere in VDEL_REDESIGN.md (grepped directly, twice, most recently at the
    commit that landed this file), and the meeting-notes files cited as the source do not
    exist in this repo. D-042 records this as unverifiable rather than confirmed, and so
    does this docstring: the technical reasoning stands on its own and the person asking
    has the authority, but neither of those quoted phrases should be repeated as though a
    document in this repository says it.

    A single-gap variant still falls out naturally whenever a concept happens to tag only
    one gap in the assignment -- this is a scope correction, not a bigger mechanism.

    Determinism, mechanically:
      1. `compute_seed(...)` -- hashlib, not hash(). One `random.Random` instance seeded
         from it, used for every random choice below, so the WHOLE selection is
         reproducible from the three-tuple, not just pieces of it.
      2. Concept candidates are `sorted({c for gap in gaps for c in gap.concept_ids})` --
         a set comprehension (unordered by construction) immediately sorted before any
         further use. Never iterated, indexed, or compared in its unsorted form.
      3. Adaptive pick: among concepts with `n_obs_by_concept.get(c, 0) >= 3`, the one
         with lowest mastery; ties broken by sorted concept_id (deterministic, consumes
         no RNG state) rather than by whichever the set/dict order happened to produce.
      4. Uniform fallback (no concept has n_obs >= 3): `rng.choice` over the SORTED
         concept list -- the only place this function still consumes RNG state, now that
         gap-picking-among-templates no longer exists as a separate random step.
      5. Gap group: EVERY gap tagged with the chosen concept, in this assignment, SORTED
         by gap_id -- no further selection, no RNG. "Templates tagged with that concept"
         (C3's words) is now read as the group itself, not a menu to pick one from.
    """
    rng = random.Random(compute_seed(student_id, assignment_id, attempt_no))

    gaps = list(gaps)
    all_concepts = sorted({concept for gap in gaps for concept in gap.concept_ids})
    if not all_concepts:
        raise ValueError("no gaps with any concept_ids were supplied")

    qualifying = sorted(
        (c for c in all_concepts if n_obs_by_concept.get(c, 0) >= _MIN_OBS_FOR_ADAPTIVE),
    )
    if qualifying:
        chosen_concept = min(qualifying, key=lambda c: (mastery_by_concept.get(c, 0.0), c))
    else:
        chosen_concept = rng.choice(all_concepts)

    chosen_gap_ids = tuple(sorted(
        gap.gap_id for gap in gaps if chosen_concept in gap.concept_ids
    ))

    variant_id = _compute_variant_id(assignment_id, chosen_gap_ids, master_version)
    return variant_id, chosen_gap_ids
