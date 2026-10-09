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
    # A run that hangs on a lock would otherwise block every later run.
    default_args={"execution_timeout": timedelta(minutes=10)},
):
    # No retries: the next run loads the failed snapshots again anyway.
    load_vehicle_positions = BashOperator(
        task_id="load_vehicle_positions",
        bash_command=f"{MOBILITY_BIN}/mobility load-vehicle-positions",
    )
    load_trip_updates = BashOperator(
        task_id="load_trip_updates",
        bash_command=f"{MOBILITY_BIN}/mobility load-trip-updates",
    )
    # A loader fails its task if any snapshot fails, but the others are
    # committed; one broken snapshot must not stop the models from updating.
    dbt_build = BashOperator(
        task_id="dbt_build",
        bash_command=f"{MOBILITY_BIN}/dbt build",
        trigger_rule=TriggerRule.ALL_DONE,
        retries=1,
        retry_delay=timedelta(minutes=2),
    )
    # Only after a successful build: the prediction periods must be built from
    # snapshots before they leave staging (ADR 006).
    prune_trip_updates = BashOperator(
        task_id="prune_trip_updates",
        bash_command=f"{MOBILITY_BIN}/mobility prune-trip-updates",
    )
    # Airflow judges a run by its last tasks only, so without this a failed
    # load would leave the run green once dbt_build succeeds.
    fail_run_on_load_failure = BashOperator(
        task_id="fail_run_on_load_failure",
        bash_command="exit 1",
        trigger_rule=TriggerRule.ONE_FAILED,
    )

    load_vehicle_positions >> [dbt_build, fail_run_on_load_failure]
    load_trip_updates >> [dbt_build, fail_run_on_load_failure]
    dbt_build >> prune_trip_updates
