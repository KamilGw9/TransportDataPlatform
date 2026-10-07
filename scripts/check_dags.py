"""Exit with 1 if a DAG file cannot be imported; run inside the Airflow image."""

import sys

from airflow.dag_processing.dagbag import DagBag

bag = DagBag()
for path, error in bag.import_errors.items():
    print(f"{path}: {error}", file=sys.stderr)
if bag.import_errors:
    sys.exit(1)
print("DAGs:", ", ".join(sorted(bag.dag_ids)))
