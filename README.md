# Transport data platform

An urban transport data platform for Kraków: GTFS and GTFS-Realtime history,
predicted delay analysis, and data quality monitoring.

The repository currently contains a Python application scaffold, a feed collection
and profiling tool, results from a short study of the A/M/T feeds, and RAW archiving
of the Mobilis (`krakow_ztp_m`) schedule ZIP in local S3 storage. Estimating arrival
windows from vehicle states still requires validation.

- [Profiler setup and usage](tools/feed_profiler/README.md)
- [Profiling findings](tools/feed_profiler/data-profile.md)
- [Project plan](docs/project-plan.md)
- [Current status](docs/project-status.md)
- [Why Kraków and Mobilis](docs/adr/001-krakow-m-first.md)
- [Local PostgreSQL and S3 storage](docs/local-development.md)

## Local infrastructure

```bash
make setup
make up
make check-infra
```

PostgreSQL is available at `127.0.0.1:5432`; the S3 endpoint is
`http://127.0.0.1:9000`, with a console at `http://127.0.0.1:9001`.
Credentials are in the ignored `.env`. `make down` retains database and object
volumes. The first MinIO source build takes several minutes; see the
[local setup and lifecycle notes](docs/local-development.md).

## Development environment

Required tool: uv. The project uses Python 3.12.

```bash
uv sync --locked
uv run mobility --help
uv run mobility --version
uv run pytest
uv run ruff check src/ tools/feed_profiler/
uv run ruff format --check src/ tools/feed_profiler/
```

Archive the current Mobilis schedule (requires running services, see
[local setup](docs/local-development.md#archive-the-gtfs-schedule)):

```bash
set -a; source .env; set +a
uv run python -m mobility.ingestion.gtfs
```

Project documentation, code identifiers, and commit messages are written in English.
