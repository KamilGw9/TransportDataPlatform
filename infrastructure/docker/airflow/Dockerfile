FROM apache/airflow:slim-3.3.2-python3.12@sha256:a54e7bd6c4d7a17e55cd14b0ead257877b8f8111680d2692cbdba2ff32bd3ff3

# The slim image has no PostgreSQL driver for Airflow's own metadata database.
# The constraints file keeps the extra at the versions released with Airflow.
RUN pip install --no-cache-dir "apache-airflow[postgres]==3.3.2" \
    --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.3.2/constraints-3.12.txt

# mobility and dbt get their own environment, so their dependencies do not
# have to agree with Airflow's. Tasks call its executables by full path.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/python/bin/python3.12 \
    UV_PROJECT_ENVIRONMENT=/opt/mobility/.venv

USER root
WORKDIR /opt/mobility

COPY pyproject.toml uv.lock ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.7@sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --group transform --no-install-project

COPY src ./src
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.7@sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --group transform

COPY transform ./transform
# The project belongs to root, so dbt writes its artifacts under /tmp.
ENV DBT_PROJECT_DIR=/opt/mobility/transform \
    DBT_PROFILES_DIR=/opt/mobility/transform \
    DBT_TARGET_PATH=/tmp/dbt/target \
    DBT_LOG_PATH=/tmp/dbt/logs

USER airflow
WORKDIR /opt/airflow
