"""The event-sourcing proof (BUILD_PLAN 2.6).

Snapshot every learner_profile -> TRUNCATE the table -> rebuild each profile from `traces`
alone -> deep-diff -> print `IDENTICAL` or exactly which fields differ.

**What this proves and why it is the project's central claim.** `traces` is the ledger and
`learner_profile` is the balance. If deleting the balance and re-adding the ledger returns
the same numbers, the profile was never holding private information: every belief in it is a
consequence of a recorded event. That is what makes a grade built on this profile defensible
all the way down -- and it is a demonstration, not an assertion.

Run:  python -m scripts.prove_event_sourcing
      python -m scripts.prove_event_sourcing --commit    # persist the rebuild

Six decisions, each load-bearing:

1. **Stored state is compared to stored state.** The snapshot is read back out of the
   table, and so is the rebuilt profile -- not compared against `rebuild_from_traces`'s
   in-memory return value. Both sides therefore travel the identical JSONB -> Python path,
   so a difference can only mean the values really differ, never that one side took a
   different route. It is also the more faithful reading of "wipe the table and get the same
   table back".

2. **It rolls back by default.** The comparison happens inside the transaction, so the proof
   is complete either way; rolling back means this is safe to run against real data and safe
   to rehearse repeatedly, which BUILD_PLAN explicitly asks for ("rehearse it"). `TRUNCATE`
   is transactional in PostgreSQL, so the wipe is genuine and genuinely undone. `--commit`
   exists for the one case where persisting is the point: repairing a profile that has
   drifted from its log.

3. **A vacuous pass is a failure.** With no profiles to compare, "IDENTICAL" would be
   literally true and completely worthless. Zero comparable profiles exits non-zero with
   NOTHING TO PROVE, so neither CI nor a DoD write-up can mistake an empty database for a
   passing proof. (The database is empty today -- DECISIONS.md D-006.)

4. **`updated_at` is excluded.** It is a freshness stamp, not derived belief: a rebuild
   legitimately touches it. Every other column is compared.

5. **`traces` is counted before and after.** A proof that quietly modified the log it
   replays would prove nothing, so the count is printed as part of the output.

6. **Students who had no profile are reported, not failed.** A student with traces but no
   profile row means the fast path has not run for them yet. The rebuild creating one is
   correct, not a mismatch, so it is listed separately and kept out of the verdict.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

from memory.memory import Memory
from system import db

# Compared column-for-column against sql/05_memory_tables.sql, minus `updated_at`
# (decision 4). `student_id` is the key, not a compared field.
PROFILE_COLUMNS = ("mastery", "weaknesses", "reflections", "session_digest", "features_ref")

_ABSENT = object()          # distinguishes "key missing" from "key present and None"


@dataclass(frozen=True)
class Difference:
    student_id: str
    path: str
    snapshot: Any
    rebuilt: Any

    def render(self) -> str:
        def show(value):
            return "<absent>" if value is _ABSENT else repr(value)
        return (f"    {self.student_id}  {self.path}\n"
                f"        snapshot : {show(self.snapshot)}\n"
                f"        rebuilt  : {show(self.rebuilt)}")


def diff_values(before: Any, after: Any, path: str = ""):
    """Yield `(path, before, after)` for every leaf that differs.

    Hand-written rather than pulled from a dependency: this comparison IS the proof, so it
    should be something that can be read and explained in a viva, and the repo's dependency
    list stays as CLAUDE.md 9 fixes it.
    """
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            here = f"{path}.{key}" if path else str(key)
            yield from diff_values(before.get(key, _ABSENT), after.get(key, _ABSENT), here)
        return

    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            yield (f"{path}[length]", len(before), len(after))
        for index in range(min(len(before), len(after))):
            yield from diff_values(before[index], after[index], f"{path}[{index}]")
        return

    # A dict/list on one side and a scalar on the other lands here and differs, as it should.
    if before is _ABSENT or after is _ABSENT or before != after:
        yield (path, before, after)


def read_profiles(conn) -> dict[str, dict[str, Any]]:
    """Every learner_profile row, keyed by student, as stored."""
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT student_id, {', '.join(PROFILE_COLUMNS)} FROM learner_profile"
        )
        return {row[0]: dict(zip(PROFILE_COLUMNS, row[1:], strict=True))
                for row in cur.fetchall()}


def _all_student_ids(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT student_id FROM students ORDER BY student_id")
        return [row[0] for row in cur.fetchall()]


def _count_traces(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM traces")
        return cur.fetchone()[0]


@dataclass
class ProofResult:
    compared: list[str]               # students whose profile existed before and after
    created: list[str]                # had no profile; the rebuild made one (decision 6)
    # Had a profile the rebuild could not justify at all. **Currently unreachable, kept
    # deliberately**: `rebuild_from_traces` writes a row for every student in `students`
    # even when the log justifies nothing, and learner_profile.student_id is a FK into
    # `students` -- so snapshot is always a subset of rebuilt. It stops being unreachable
    # the moment the rebuild is optimised to skip writing all-empty rows, which is a
    # plausible future change, and at that point a profile the log cannot justify must
    # fail the proof rather than vanish quietly. Not covered by a test, because it cannot
    # currently be provoked.
    vanished: list[str]
    differences: list[Difference]
    traces_before: int
    traces_after: int
    rows_after_wipe: int              # must be 0 -- see `prove`

    @property
    def identical(self) -> bool:
        return not self.differences and not self.vanished

    @property
    def vacuous(self) -> bool:
        """No profile existed to be reproduced, so there was nothing to prove."""
        return not self.compared and not self.vanished


def prove(conn) -> ProofResult:
    """Snapshot, wipe, rebuild, diff. Neither commits nor rolls back -- the caller decides,
    which is also what makes this callable from a test that rolls back.

    **Why the TRUNCATE is a real step, honestly stated.** Mutation testing showed the
    comparison still detects tampering with the wipe removed, because
    `rebuild_from_traces` REPLACES every column rather than merging into it -- so the
    rebuild overwrites the profile either way. The wipe earns its place for three other
    reasons: BUILD_PLAN 2.6 specifies it; it is the demo's whole rhetorical core ("I delete
    the entire profile, then replay the log"); and it is what would catch a future rebuild
    that started merging instead of replacing, which would otherwise pass by reading the
    state it was supposed to be deriving. `rows_after_wipe` is recorded so the wipe is
    *observed* rather than merely performed -- a step nothing checks is a step that can
    silently stop happening.
    """
    memory = Memory()

    traces_before = _count_traces(conn)
    snapshot = read_profiles(conn)

    with conn.cursor() as cur:
        cur.execute("TRUNCATE learner_profile")
        cur.execute("SELECT count(*) FROM learner_profile")
        rows_after_wipe = cur.fetchone()[0]

    for student_id in _all_student_ids(conn):
        memory.rebuild_from_traces(student_id, conn=conn)

    rebuilt = read_profiles(conn)

    compared = sorted(set(snapshot) & set(rebuilt))
    differences = [
        Difference(student_id, path, before, after)
        for student_id in compared
        for path, before, after in diff_values(snapshot[student_id], rebuilt[student_id])
    ]

    return ProofResult(
        compared=compared,
        created=sorted(set(rebuilt) - set(snapshot)),
        vanished=sorted(set(snapshot) - set(rebuilt)),
        differences=differences,
        traces_before=traces_before,
        traces_after=_count_traces(conn),
        rows_after_wipe=rows_after_wipe,
    )


def _summarise(value: Any) -> str:
    if isinstance(value, dict):
        return f"{len(value)} concept(s)"
    if isinstance(value, list):
        return f"{len(value)} entry(ies)"
    return "set" if value is not None else "unset"


def report(result: ProofResult, profiles: dict[str, dict[str, Any]], out=print) -> None:
    out("")
    out("VDEL - event-sourcing proof   (BUILD_PLAN 2.6)")
    out("traces are truth; learner_profile is derived belief")
    out("")
    out(f"  traces in the log            : {result.traces_before}")
    out(f"  profiles snapshotted         : {len(result.compared) + len(result.vanished)}")
    out("")
    out("  1. SNAPSHOT   read learner_profile as stored")
    out(f"  2. WIPE       TRUNCATE learner_profile -> {result.rows_after_wipe} rows remain")
    out("  3. REPLAY     rebuild_from_traces() for every student")
    out("  4. COMPARE    deep-diff, field by field")
    out("")

    if result.vacuous:
        out("NOTHING TO PROVE")
        out("")
        out("  No learner_profile row existed, so there was no belief to reproduce.")
        out("  'IDENTICAL' here would be true and worthless -- see decision 3 in this")
        out("  file's docstring. The database has no telemetry yet (DECISIONS.md D-006).")
        out("")
        return

    by_student = {d.student_id for d in result.differences}
    for student_id in result.compared:
        mark = "DIFFERS" if student_id in by_student else "identical"
        out(f"  {student_id}")
        for column in PROFILE_COLUMNS:
            column_differs = any(d.student_id == student_id
                                 and (d.path == column or d.path.startswith(f"{column}.")
                                      or d.path.startswith(f"{column}["))
                                 for d in result.differences)
            state = "DIFFERS" if column_differs else "identical"
            detail = _summarise(profiles.get(student_id, {}).get(column))
            out(f"      {column:<15} {state:<10} ({detail})")
        out(f"      -> {mark}")
        out("")

    for student_id in result.created:
        out(f"  {student_id}: no prior profile; the rebuild created one.")
        out("      Not a mismatch -- the fast path has not run for this student yet.")
    for student_id in result.vanished:
        out(f"  {student_id}: had a profile the log does not justify AT ALL.")
    if result.created or result.vanished:
        out("")

    if result.identical:
        out("IDENTICAL")
        out("")
        out("  Every number above was deleted and recomputed from traces alone.")
        out("  The profile is a faithful projection of the log, not a blob to trust.")
    else:
        out(f"DIFFERENT - {len(result.differences)} field(s) differ")
        out("")
        for difference in result.differences:
            out(difference.render())
        if result.vanished:
            out("")
            out(f"  plus {len(result.vanished)} profile(s) the log cannot justify at all.")

    out("")
    out(f"  traces after                 : {result.traces_after}"
        f"{'  (unchanged)' if result.traces_after == result.traces_before else '  CHANGED!'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--commit", action="store_true",
        help="persist the rebuilt profiles. Default is to roll back, so the proof leaves "
             "the database exactly as it was (decision 2).",
    )
    args = parser.parse_args(argv)

    conn = db._open()
    try:
        result = prove(conn)
        report(result, read_profiles(conn))

        if args.commit:
            conn.commit()
            print("  committed - the rebuilt profiles are now the stored profiles")
        else:
            conn.rollback()
            print("  rolled back - the database is exactly as it was "
                  "(pass --commit to persist)")
        print("")
    finally:
        conn.close()

    if result.vacuous:
        return 2
    return 0 if result.identical else 1


if __name__ == "__main__":
    sys.exit(main())
