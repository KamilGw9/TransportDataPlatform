from datetime import UTC, datetime, timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, TriggerRule

MOBILITY_BIN = "/opt/mobility/.venv/bin"

# Each run loads every snapshot not loaded yet, so missed intervals need no
# catching up, and two runs at once would rebuild the same tables.
with DAG(
    dag_id="refresh_models",
    schedule=timedelta(minutes=30),
    start_date=datetime(2026, 10, 7, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=2)},
):
    load_vehicle_positions = BashOperator(
        task_id="load_vehicle_positions",
        bash_command=f"{MOBILITY_BIN}/mobility load-vehicle-positions",
    )
    # The loader fails the task if any snapshot fails, but the others are
    # committed; one broken snapshot must not stop the models from updating.
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"{MOBILITY_BIN}/dbt build",
        trigger_rule=TriggerRule.ALL_DONE,
    )

    load_vehicle_positions >> dbt_build
