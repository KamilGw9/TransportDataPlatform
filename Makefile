.PHONY: help setup up migrate collect collect-stop airflow dashboard down ps logs postgres check-infra check-dags dbt-build test lint

COMPOSE := docker compose

# The AWS host adds compose.aws.yaml through COMPOSE_FILE in .env and keeps RAW
# in S3, so MinIO is not started there.
ifeq ($(findstring compose.aws.yaml,$(shell grep -s '^COMPOSE_FILE=' .env)),)
MINIO := minio
endif

help:
	@printf '%s\n' 'make setup        Prepare local .env (preserves existing values)' 'make up           Start PostgreSQL, MinIO, initialize the bucket and migrate' 'make migrate      Apply SQL migrations (safe to repeat)' 'make collect      Start the GTFS-RT and schedule collectors (runs make up first)' 'make collect-stop Stop both collectors, keeping other services' 'make airflow      Start Airflow (runs make up first)' 'make dashboard    Start Grafana (runs make up first)' 'make down         Stop services, retaining all volumes' 'make ps           Show service status' 'make logs         Follow service logs' 'make postgres     Open a SQL session' 'make check-infra  Check SQL and S3 writes across container recreation' 'make check-dags   Check that the Airflow DAGs import' 'make dbt-build    Build and test the dbt models in core' 'make test         Run Python tests' 'make lint         Check Python style'

setup:
	python3 scripts/setup_env.py

up:
	$(COMPOSE) config --quiet
	$(COMPOSE) up -d --build --wait --wait-timeout 120 postgres $(MINIO)
ifdef MINIO
	$(COMPOSE) run --rm --no-deps minio-init
endif
	$(MAKE) --no-print-directory migrate

migrate:
	bash scripts/migrate.sh

collect: up
	$(COMPOSE) up -d --build --wait collector schedule-collector

collect-stop:
	$(COMPOSE) stop collector schedule-collector

airflow: up
	$(COMPOSE) up -d --build --wait airflow-api-server airflow-scheduler airflow-dag-processor

dashboard: up
	$(COMPOSE) up -d --wait grafana

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps --all

logs:
	$(COMPOSE) logs --follow --tail=100

postgres:
	$(COMPOSE) exec postgres sh -c 'exec psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

check-infra:
	bash scripts/check_infrastructure.sh

# Test runs of a DAG need a metadata database; this one is SQLite inside the
# throwaway container, not the airflow database in PostgreSQL.
check-dags:
	$(COMPOSE) build airflow-scheduler
	docker run --rm -v "$(CURDIR)/scripts/check_dags.py:/tmp/check_dags.py:ro" mobility-airflow \
		bash -c "airflow db migrate > /dev/null && python /tmp/check_dags.py"

# dbt reads the database password from the environment, unlike Compose, which
# loads .env by itself.
dbt-build:
	set -a; . ./.env; set +a; cd transform && uv run --locked dbt build

test:
	uv run --locked pytest

lint:
	uv run --locked ruff check src/ tools/feed_profiler/ scripts/ tests/ dags/
	uv run --locked ruff format --check src/ tools/feed_profiler/ scripts/ tests/ dags/
