"""Create the schema. Idempotent: every statement is IF NOT EXISTS / OR REPLACE.

Run:  python -m scripts.init_db
"""

from __future__ import annotations

import sys
from pathlib import Path

from system import db

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

# 05 before 04 because 04 indexes `traces`, which 05 creates. See the header of
# sql/04_indexes.sql for why the filenames cannot simply be renumbered.
ORDER = [
    "01_reference_tables.sql",
    "02_raw_tables.sql",
    "03_feature_tables.sql",
    "05_memory_tables.sql",
    "04_indexes.sql",
]


def main() -> int:
    with db.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        for name in ORDER:
            cur.execute((SQL_DIR / name).read_text(encoding="utf-8"))
            print(f"  applied {name}")
    print("schema ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
