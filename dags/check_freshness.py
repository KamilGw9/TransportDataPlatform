from datetime import UTC, datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

# A stale feed fails the run, which is how it shows up in the Airflow UI.
# Retrying would only hide the failure for a few minutes.
with DAG(
    dag_id="check_freshness",
    schedule=timedelta(minutes=5),
    start_date=datetime(2026, 10, 7, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
    # A hung check would block the next ones without failing.
    default_args={"execution_timeout": timedelta(minutes=2)},
):
    BashOperator(
        task_id="check_freshness",
        bash_command="/opt/mobility/.venv/bin/mobility check-freshness",
    )
