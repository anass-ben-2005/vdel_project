#!/usr/bin/env python3
"""Smoke test: verify DB connectivity and schema."""

import os
import sys
from dotenv import load_dotenv
import psycopg2

load_dotenv()

def test_db_connection():
    """Test that we can connect to PostgreSQL."""
    dsn = os.getenv('PG_DSN')
    if not dsn:
        print("✗ PG_DSN not set")
        return False

    try:
        conn = psycopg2.connect(dsn)
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        cursor.close()
        conn.close()
        print("✓ Database connection successful")
        return True
    except Exception as e:
        print(f"✗ Database connection failed: {e}")
        return False

def test_tables_exist():
    """Verify all required tables exist."""
    dsn = os.getenv('PG_DSN')
    conn = psycopg2.connect(dsn)
    cursor = conn.cursor()

    required_tables = [
        'students',
        'assignments',
        'raw_commits',
        'raw_workflow_runs',
        'learner_features',
        'kt_params',
        'items',
        'traces',
        'sessions',
        'learner_profile',
    ]

    missing = []
    for table in required_tables:
        cursor.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = %s",
            (table,)
        )
        if cursor.fetchone() is None:
            missing.append(table)

    cursor.close()
    conn.close()

    if missing:
        print(f"✗ Missing tables: {', '.join(missing)}")
        return False
    else:
        print(f"✓ All {len(required_tables)} required tables exist")
        return True

def main():
    """Run smoke tests."""
    print("Running smoke tests...\n")

    tests = [
        ("DB Connection", test_db_connection),
        ("Schema Tables", test_tables_exist),
    ]

    results = []
    for name, test_func in tests:
        print(f"Testing {name}...")
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"✗ {name} failed with exception: {e}")
            results.append(False)
        print()

    if all(results):
        print("✅ All smoke tests passed!")
        return 0
    else:
        print(f"❌ {sum(1 for r in results if not r)} test(s) failed")
        return 1

if __name__ == '__main__':
    sys.exit(main())
