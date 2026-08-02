#!/usr/bin/env python3
"""Seed initial students and assignments."""

import os
import sys
from datetime import datetime, timedelta
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    """Connect to PostgreSQL."""
    dsn = os.getenv('PG_DSN')
    if not dsn:
        print("ERROR: PG_DSN not set")
        sys.exit(1)
    return psycopg2.connect(dsn)

def seed_students():
    """Insert the first student (Anas)."""
    conn = get_connection()
    cursor = conn.cursor()

    # Insert Anas as the first student
    try:
        cursor.execute("""
            INSERT INTO students (student_id, github_username, cohort)
            VALUES (%s, %s, %s)
            ON CONFLICT (student_id) DO NOTHING
        """, ('anas-001', 'anas', 'cohort-2024'))
        conn.commit()
        print("✓ Student Anas inserted")
    except Exception as e:
        print(f"✗ Error inserting student: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def seed_assignments():
    """Insert sample assignments."""
    conn = get_connection()
    cursor = conn.cursor()

    assignments = [
        {
            'assignment_id': 'project-1',
            'repo_prefix': 'kaggle-pipeline-1',
            'released_at': datetime.utcnow() - timedelta(days=30),
            'due_at': datetime.utcnow() - timedelta(days=10),
            'concepts': ['python.basics', 'python.control_flow', 'git', 'testing']
        },
        {
            'assignment_id': 'project-2',
            'repo_prefix': 'kaggle-pipeline-2',
            'released_at': datetime.utcnow() - timedelta(days=15),
            'due_at': datetime.utcnow() + timedelta(days=5),
            'concepts': ['sql.select', 'sql.joins', 'python.functions', 'testing']
        },
        {
            'assignment_id': 'project-3',
            'repo_prefix': 'kaggle-pipeline-3',
            'released_at': datetime.utcnow() - timedelta(days=5),
            'due_at': datetime.utcnow() + timedelta(days=20),
            'concepts': ['spark.dataframe', 'spark.aggregation', 'ci_cd', 'documentation']
        }
    ]

    for a in assignments:
        try:
            cursor.execute("""
                INSERT INTO assignments
                (assignment_id, repo_prefix, released_at, due_at, concepts)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (assignment_id) DO NOTHING
            """, (
                a['assignment_id'],
                a['repo_prefix'],
                a['released_at'],
                a['due_at'],
                a['concepts']
            ))
            print(f"✓ Assignment {a['assignment_id']} inserted")
        except Exception as e:
            print(f"✗ Error inserting assignment {a['assignment_id']}: {e}")
            conn.rollback()
            continue

    conn.commit()
    cursor.close()
    conn.close()

def main():
    """Seed the database."""
    print("Seeding reference data...\n")
    seed_students()
    seed_assignments()
    print("\n✅ Seeding complete")

if __name__ == '__main__':
    main()
