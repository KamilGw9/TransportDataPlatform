"""Exit with 1 if a DAG is broken; run inside the Airflow image."""

import sys

from airflow.dag_processing.dagbag import DagBag

bag = DagBag()
for path, error in bag.import_errors.items():
    print(f"{path}: {error}", file=sys.stderr)
if bag.import_errors:
    sys.exit(1)
print("DAGs:", ", ".join(sorted(bag.dag_ids)))


def refresh_run_states(failing_load: str | None) -> tuple[str, str]:
    dag = bag.get_dag("refresh_models")
    for load in ["load_vehicle_positions", "load_trip_updates"]:
        dag.get_task(load).bash_command = "exit 1" if load == failing_load else "true"
    for task in ["dbt_build", "prune_trip_updates"]:
        dag.get_task(task).bash_command = "true"
    run = dag.test()
    return run.state, run.get_task_instance("send_heartbeat").state


# dbt builds even after a failed load, and the run must still show the failure
# and send no heartbeat. Without HEARTBEAT_NAMESPACE, as here, a successful
# run skips the heartbeat.
for failing_load, expected in [
    ("load_vehicle_positions", ("failed", "upstream_failed")),
    ("load_trip_updates", ("failed", "upstream_failed")),
    (None, ("success", "skipped")),
]:
    states = refresh_run_states(failing_load)
    if states != expected:
        print(
            f"refresh_models with failing load {failing_load} ended as {states} "
            f"(run, heartbeat), expected {expected}",
            file=sys.stderr,
        )
        sys.exit(1)
