"""collect -> compute_features -> update_profiles.

The tasks shell out to this repo's module entrypoints rather than importing them.
Airflow requires Python <3.12 and pins its own pydantic/psycopg2, so it lives in a
separate environment (requirements-airflow.txt); crossing that boundary by import would
force the two environments to be one. The previous version did
`sys.path.insert(0, '/opt/airflow')` inside each task -- a hardcoded container path that
cannot work when the repo is checked out anywhere else.

Set VDEL_HOME (Airflow Variable or environment variable) to the repo root.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.empty import EmptyOperator

VDEL_HOME = os.environ.get("VDEL_HOME", "/opt/vdel")
PYTHON = os.environ.get("VDEL_PYTHON", "python")

default_args = {
    "owner": "anas",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="vdel_pipeline",
    default_args=default_args,
    description="GitHub telemetry -> the seven variables -> learner profiles",
    start_date=datetime(2026, 1, 1, tzinfo=UTC),  # Airflow requires tz-aware
    schedule="0 */6 * * *",
    catchup=False,   # backfilling this pipeline would re-collect the same GitHub history
    max_active_runs=1,  # two concurrent runs would race on the same raw tables
    tags=["vdel", "m1"],
) as dag:

    collect = BashOperator(
        task_id="collect",
        bash_command=f"cd {VDEL_HOME} && {PYTHON} -m scripts.collect",
    )

    compute_features = BashOperator(
        task_id="compute_features",
        bash_command=f"cd {VDEL_HOME} && {PYTHON} -m features.compute_features",
    )

    # Stub until M2 builds memory/memory.py. Present so the shape of the pipeline is
    # visible now and the milestone only has to swap the operator.
    update_profiles = EmptyOperator(task_id="update_profiles")

    collect >> compute_features >> update_profiles
