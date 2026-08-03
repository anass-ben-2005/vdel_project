"""
dags/vdel_pipeline.py — daily: collect -> compute_features -> update_profiles.
Runs on VDEL's own Airflow stack (the intelligence layer dogfoods the platform).
Daily batch is sufficient: adaptive tutoring does not need second-by-second freshness.

Transcribed from VDEL_Modules_1_2_Build.md Part C. Two changes, both marked:
  - the repo list is loaded from config/roster.yaml instead of the document's
    `repos=[]` placeholder, so the task actually collects something;
  - start_date is timezone-aware, which Airflow requires.
"""
from datetime import UTC, datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

default_args = {"owner": "anas", "retries": 1, "retry_delay": timedelta(minutes=5)}

with DAG("vdel_pipeline", default_args=default_args,
         schedule="@daily", start_date=datetime(2026, 1, 1, tzinfo=UTC),
         catchup=False,      # backfill would re-collect the same GitHub history
         max_active_runs=1   # concurrent runs would race on the same raw tables
         ) as dag:

    def _collect(**_):
        from collectors.collect_github import collect_all
        from scripts.seed_data import load_roster
        from system import db

        # CHANGED: load the repo list for the active cohort from config/roster.yaml.
        roster = load_roster()
        repos = [{"owner": a["owner"], "repo": a["repo"],
                  "student_id": a["student_id"], "assignment_id": a["assignment_id"]}
                 for a in roster.get("assignments", [])]
        with db.connect() as conn:
            print(collect_all(conn, repos))

    def _compute(**ctx):
        from features.compute_features import run
        last = (ctx["data_interval_start"] - timedelta(days=1)).isoformat()
        run(last)

    def _update_profiles(**_):
        pass   # Module 3: fold new features into learner_profile (fast path)

    t1 = PythonOperator(task_id="collect", python_callable=_collect)
    t2 = PythonOperator(task_id="compute_features", python_callable=_compute)
    t3 = PythonOperator(task_id="update_profiles", python_callable=_update_profiles)
    t1 >> t2 >> t3
