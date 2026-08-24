"""Create the schema. Idempotent: every statement is IF NOT EXISTS / OR REPLACE.

Run:  python -m scripts.init_db
"""

from __future__ import annotations

import sys
from pathlib import Path

from system import db

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"

# 05 before 04 because 04 indexes `traces`, which 05 creates. See the header of
# sql/04_indexes.sql for why the filenames cannot simply be renumbered. 06 (the assessment
# redesign) ALTERs `assignments` (01) and `raw_commits`/`raw_workflow_runs` (02), and
# references `raw_commits` (02) and `traces` (05) by foreign key, so it must run after all
# three; placed after 05 and before 04 since nothing in 04 depends on 06 and nothing in 06
# depends on 04. It does NOT touch `sessions` -- D-040 kept that table untouched and gave
# the git-derived activity concept its own new `activity_sessions` table instead.
ORDER = [
    "01_reference_tables.sql",
    "02_raw_tables.sql",
    "03_feature_tables.sql",
    "05_memory_tables.sql",
    "06_assessment_tables.sql",
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
