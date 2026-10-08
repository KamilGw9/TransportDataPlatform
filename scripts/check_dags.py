"""Exit with 1 if a DAG is broken; run inside the Airflow image."""

import sys

from airflow.dag_processing.dagbag import DagBag

bag = DagBag()
for path, error in bag.import_errors.items():
    print(f"{path}: {error}", file=sys.stderr)
if bag.import_errors:
    sys.exit(1)
print("DAGs:", ", ".join(sorted(bag.dag_ids)))


def refresh_run_state(failing_load: str | None) -> str:
    dag = bag.get_dag("refresh_models")
    for load in ["load_vehicle_positions", "load_trip_updates"]:
        dag.get_task(load).bash_command = "exit 1" if load == failing_load else "true"
    dag.get_task("dbt_build").bash_command = "true"
    return dag.test().state


# dbt builds even after a failed load, and the run must still show the failure.
for failing_load, expected in [
    ("load_vehicle_positions", "failed"),
    ("load_trip_updates", "failed"),
    (None, "success"),
]:
    state = refresh_run_state(failing_load)
    if state != expected:
        print(
            f"refresh_models with failing load {failing_load} ended as {state}, "
            f"expected {expected}",
            file=sys.stderr,
        )
        sys.exit(1)
