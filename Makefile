.PHONY: help setup up migrate collect collect-stop down ps logs postgres check-infra test lint

COMPOSE := docker compose

help:
	@printf '%s\n' 'make setup        Prepare local .env (preserves existing values)' 'make up           Start PostgreSQL, MinIO, initialize the bucket and migrate' 'make migrate      Apply SQL migrations (safe to repeat)' 'make collect      Start the GTFS-RT and schedule collectors (runs make up first)' 'make collect-stop Stop both collectors, keeping other services' 'make down         Stop services, retaining all volumes' 'make ps           Show service status' 'make logs         Follow service logs' 'make postgres     Open a SQL session' 'make check-infra  Check SQL and S3 writes across container recreation' 'make test         Run Python tests' 'make lint         Check Python style'

setup:
	python3 scripts/setup_env.py

up:
	$(COMPOSE) config --quiet
	$(COMPOSE) up -d --build --wait --wait-timeout 120 postgres minio
	$(COMPOSE) run --rm --no-deps minio-init
	$(MAKE) --no-print-directory migrate

migrate:
	bash scripts/migrate.sh

collect: up
	$(COMPOSE) up -d --build --wait collector schedule-collector

collect-stop:
	$(COMPOSE) stop collector schedule-collector

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

test:
	uv run --locked pytest

lint:
	uv run --locked ruff check src/ tools/feed_profiler/ scripts/ tests/
	uv run --locked ruff format --check src/ tools/feed_profiler/ scripts/ tests/
