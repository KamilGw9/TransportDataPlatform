"""Exit with 1 if a DAG is broken; run inside the Airflow image."""

import sys

from airflow.dag_processing.dagbag import DagBag

bag = DagBag()
for path, error in bag.import_errors.items():
    print(f"{path}: {error}", file=sys.stderr)
if bag.import_errors:
    sys.exit(1)
print("DAGs:", ", ".join(sorted(bag.dag_ids)))


def refresh_run_state(load_command: str) -> str:
    dag = bag.get_dag("refresh_models")
    dag.get_task("load_vehicle_positions").bash_command = load_command
    dag.get_task("dbt_build").bash_command = "true"
    return dag.test().state


# dbt builds even after a failed load, and the run must still show the failure.
for load_command, expected in [("exit 1", "failed"), ("true", "success")]:
    state = refresh_run_state(load_command)
    if state != expected:
        print(
            f"refresh_models with load '{load_command}' ended as {state}, "
            f"expected {expected}",
            file=sys.stderr,
        )
        sys.exit(1)
