# Transport data platform

An urban transport data platform for Kraków: GTFS and GTFS-Realtime history,
predicted delay analysis, and data quality monitoring.

The repository currently contains a Python application scaffold, a feed collection
and profiling tool, and results from a short study of the A/M/T feeds. The first
platform pipeline will use Mobilis buses. Estimating arrival windows from vehicle
states still requires validation.

- [Profiler setup and usage](tools/feed_profiler/README.md)
- [Profiling findings](tools/feed_profiler/data-profile.md)
- [Project plan](docs/project-plan.md)
- [Current status](docs/project-status.md)
- [Why Kraków and Mobilis](docs/adr/001-krakow-m-first.md)

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

Project documentation, code identifiers, and commit messages are written in English.
