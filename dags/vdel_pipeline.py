"""VDEL telemetry pipeline: collect → compute_features → update_profiles."""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator

default_args = {
    'owner': 'anas',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'vdel_pipeline',
    default_args=default_args,
    description='VDEL telemetry pipeline',
    schedule_interval='0 */6 * * *',  # Every 6 hours
    catchup=False,
)


def collect_github():
    """Collect GitHub commits and workflow runs."""
    import sys
    sys.path.insert(0, '/opt/airflow')
    from collectors.collect_github import GitHubCollector

    collector = GitHubCollector()
    # TODO: Configure with actual repos
    # collector.collect_for_repo('anas', 'kaggle-pipeline-1', 'anas-001', 'project-1')
    print("GitHub collection task (stub)")


def compute_features():
    """Compute the seven variables from raw events."""
    import sys
    sys.path.insert(0, '/opt/airflow')
    from features.compute_features import FeatureComputer

    computer = FeatureComputer()
    computer.run()


def update_profiles():
    """Update learner profiles (stub for M2)."""
    print("Profile update task (stub until M2)")


# Task 1: Collect
collect_task = PythonOperator(
    task_id='collect_github',
    python_callable=collect_github,
    dag=dag,
)

# Task 2: Compute features
compute_task = PythonOperator(
    task_id='compute_features',
    python_callable=compute_features,
    dag=dag,
)

# Task 3: Update profiles (stub)
update_task = PythonOperator(
    task_id='update_profiles',
    python_callable=update_profiles,
    dag=dag,
)

# Dependencies
collect_task >> compute_task >> update_task
