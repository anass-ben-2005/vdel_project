"""scripts/load_resources.py -- load a curated CSV into the `resources` table.

    python -m scripts.load_resources resources.csv                       # dry run (default)
    python -m scripts.load_resources resources.csv --apply --dsn "<dsn>"  # write

The CSV is curated by hand (template: docs/resources_template.csv). Columns:

    resource_id, concept_ids, kind, title, locator, url, level

`concept_ids` holds one or more taxonomy ids separated by `|`. `kind`, `locator`, `url` and
`level` may be left empty (they are nullable in the table); `resource_id`, `concept_ids` and
`title` may not.

VALIDATED before anything is written (all errors are listed, with row numbers; one error and
NOTHING is written):
  - every concept id exists in config/concepts.yaml (the taxonomy; IDs are schema)
  - `kind` is one of agents.resources.KINDS, `level` one of agents.resources.LEVELS
  - `url` is a syntactically valid http(s) URL. Reachability is NOT checked: this script makes no
    network call; the author verifies each link once, by hand (CLAUDE.md schema comment)
  - no duplicate resource_id, and no two rows with the same url
  - rows whose resource_id starts with `EXAMPLE` (the template's fake rows) are refused on --apply

DRY RUN is the default and touches no database at all.

--apply writes ONLY to the database named by --dsn (never from the environment, never a default).
As an extra guard it refuses a database whose name does not end in `_test` unless
--allow-real-db is also given (the author's explicit act, for loading the curated list for real).
One transaction, `INSERT ... ON CONFLICT (resource_id) DO UPDATE`, so re-running is safe
(invariant 9). Nothing is deleted.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
from psycopg2.extensions import parse_dsn

from agents.resources import KINDS, LEVELS
from config import concepts as taxonomy

COLUMNS = ("resource_id", "concept_ids", "kind", "title", "locator", "url", "level")
REQUIRED = ("resource_id", "concept_ids", "title")
EXAMPLE_PREFIX = "EXAMPLE"
TEST_SUFFIX = "_test"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")


@dataclass(frozen=True)
class ResourceRow:
    resource_id: str
    concept_ids: tuple[str, ...]
    kind: str | None
    title: str
    locator: str | None
    url: str | None
    level: str | None

    @property
    def is_example(self) -> bool:
        return self.resource_id.upper().startswith(EXAMPLE_PREFIX)


class CsvError(ValueError):
    """The file itself is unusable (missing columns, unreadable)."""


def read_rows(path: Path) -> list[dict[str, str]]:
    # utf-8-sig: a CSV saved from a spreadsheet often starts with a byte-order mark
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise CsvError(f"missing column(s): {', '.join(missing)}. "
                           f"Expected: {', '.join(COLUMNS)}")
        return [{k: (v or "").strip() for k, v in row.items() if k in COLUMNS}
                for row in reader]


def _valid_url(url: str) -> bool:
    if re.search(r"\s", url):
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc) and "." in parsed.netloc


def validate(raw_rows: list[dict[str, str]], valid_concepts: set[str] | None = None
             ) -> tuple[list[ResourceRow], list[str]]:
    """Returns `(rows, errors)`. Row numbers in messages are CSV line numbers (header = 1)."""
    valid_concepts = taxonomy.ids() if valid_concepts is None else valid_concepts
    rows: list[ResourceRow] = []
    errors: list[str] = []
    seen_ids: dict[str, int] = {}
    seen_urls: dict[str, int] = {}

    for index, raw in enumerate(raw_rows):
        line = index + 2
        problems: list[str] = []
        for column in REQUIRED:
            if not raw.get(column):
                problems.append(f"{column} is empty")

        resource_id = raw.get("resource_id", "")
        if resource_id and not _ID.match(resource_id):
            problems.append(f"resource_id {resource_id!r} must be letters, digits, '_', '.', '-' "
                            "(1-64 chars, starting with a letter or digit)")
        if resource_id:
            if resource_id in seen_ids:
                problems.append(f"duplicate resource_id {resource_id!r} "
                                f"(first on line {seen_ids[resource_id]})")
            else:
                seen_ids[resource_id] = line

        concept_ids = tuple(c.strip() for c in raw.get("concept_ids", "").split("|") if c.strip())
        for concept in concept_ids:
            if concept not in valid_concepts:
                problems.append(f"unknown concept id {concept!r} (not in config/concepts.yaml)")
        if len(set(concept_ids)) != len(concept_ids):
            problems.append("a concept id is listed twice")

        kind = raw.get("kind") or None
        if kind is not None and kind not in KINDS:
            problems.append(f"kind {kind!r} is not one of {list(KINDS)}")
        level = raw.get("level") or None
        if level is not None and level not in LEVELS:
            problems.append(f"level {level!r} is not one of {list(LEVELS)}")

        url = raw.get("url") or None
        if url is not None:
            if not _valid_url(url):
                problems.append(f"url {url!r} is not a valid http(s) URL")
            elif url in seen_urls:
                problems.append(f"duplicate url (first on line {seen_urls[url]})")
            else:
                seen_urls[url] = line

        if problems:
            errors.extend(f"line {line}: {p}" for p in problems)
            continue
        rows.append(ResourceRow(resource_id, concept_ids, kind, raw["title"],
                                raw.get("locator") or None, url, level))
    return rows, errors


def check_target(dsn: str, *, allow_real_db: bool) -> str:
    """The database name in `dsn`; raises unless it is a `*_test` database (or the author passed
    --allow-real-db)."""
    name = parse_dsn(dsn).get("dbname", "")
    if not name:
        raise SystemExit("refusing: the DSN names no database")
    if not name.endswith(TEST_SUFFIX) and not allow_real_db:
        raise SystemExit(
            f"refusing to write to database {name!r}: it does not end in {TEST_SUFFIX!r}. "
            "Use a test database, or pass --allow-real-db if you really mean it.")
    return name


UPSERT = (
    "INSERT INTO resources (resource_id, concept_ids, kind, title, locator, url, level)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s)"
    " ON CONFLICT (resource_id) DO UPDATE SET concept_ids = EXCLUDED.concept_ids,"
    " kind = EXCLUDED.kind, title = EXCLUDED.title, locator = EXCLUDED.locator,"
    " url = EXCLUDED.url, level = EXCLUDED.level"
)


def apply_rows(cur, rows: list[ResourceRow]) -> tuple[int, int]:
    """Upsert `rows` through `cur` (the caller owns the transaction). Returns (inserted,
    updated)."""
    inserted = updated = 0
    for row in rows:
        cur.execute("SELECT 1 FROM resources WHERE resource_id = %s", (row.resource_id,))
        exists = cur.fetchone() is not None
        cur.execute(UPSERT, (row.resource_id, list(row.concept_ids), row.kind, row.title,
                             row.locator, row.url, row.level))
        updated += exists
        inserted += not exists
    return inserted, updated


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("csv", type=Path)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="validate only (the default)")
    mode.add_argument("--apply", action="store_true", help="write; requires --dsn")
    ap.add_argument("--dsn", help="database to write to (only with --apply)")
    ap.add_argument("--allow-real-db", action="store_true",
                    help="allow a database whose name does not end in _test")
    args = ap.parse_args(argv)

    try:
        rows, errors = validate(read_rows(args.csv))
    except (CsvError, OSError) as exc:
        print(f"cannot read {args.csv}: {exc}")
        return 2
    for message in errors:
        print(f"ERROR {message}")
    if errors:
        print(f"{len(errors)} error(s); nothing was written.")
        return 1
    print(f"{len(rows)} valid row(s).")

    if not args.apply:
        print("dry run: no database was touched. Add --apply --dsn <dsn> to write.")
        return 0

    if not args.dsn:
        print("--apply needs --dsn: the target database is never taken from the environment.")
        return 2
    examples = [r.resource_id for r in rows if r.is_example]
    if examples:
        print(f"refusing to apply template rows: {', '.join(examples)}")
        return 1
    name = check_target(args.dsn, allow_real_db=args.allow_real_db)

    conn = psycopg2.connect(args.dsn)
    try:
        with conn.cursor() as cur:
            inserted, updated = apply_rows(cur, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"applied to {name!r}: {inserted} inserted, {updated} updated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
