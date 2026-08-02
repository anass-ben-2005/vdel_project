#!/usr/bin/env python3
"""Initialize the database schema idempotently."""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    """Connect to PostgreSQL."""
    dsn = os.getenv('PG_DSN')
    if not dsn:
        print("ERROR: PG_DSN not set in .env")
        sys.exit(1)
    return psycopg2.connect(dsn)

def execute_sql_file(conn, filepath):
    """Execute a single SQL file."""
    with open(filepath, 'r') as f:
        sql = f.read()

    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        conn.commit()
        print(f"✓ {filepath}")
    except Exception as e:
        conn.rollback()
        print(f"✗ {filepath}: {e}")
        raise
    finally:
        cursor.close()

def main():
    """Execute all SQL files in order."""
    sql_dir = Path(__file__).parent.parent / 'sql'
    sql_files = [
        '01_reference_tables.sql',
        '02_raw_tables.sql',
        '03_feature_tables.sql',
        '05_memory_tables.sql',
        '04_indexes.sql',
    ]

    conn = get_connection()
    print("Initializing database schema...")

    try:
        # Enable pgvector extension
        cursor = conn.cursor()
        cursor.execute('CREATE EXTENSION IF NOT EXISTS vector;')
        conn.commit()
        cursor.close()
        print("✓ pgvector extension enabled")
    except Exception as e:
        print(f"Warning: could not enable pgvector: {e}")

    for sql_file in sql_files:
        filepath = sql_dir / sql_file
        if filepath.exists():
            execute_sql_file(conn, filepath)
        else:
            print(f"Warning: {filepath} not found")

    conn.close()
    print("\n✅ Database initialized successfully")

if __name__ == '__main__':
    main()
