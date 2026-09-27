# Project status

Last updated: 2026-09-27.

- Current stage: 1 — Python scaffold and quality tooling; in progress.
- Implemented: the `mobility` package, CLI, uv configuration, lockfile, Ruff,
  pytest, and the GTFS/GTFS-RT profiler with [A/M/T reports](../tools/feed_profiler/data-profile.md).
- Verification: CLI help and version work; Ruff lint and formatting checks pass;
  `uv run pytest` passes all 5 tests without fetching live data.
- Local data: ZIP and PB files in `tools/feed_profiler/data/` (excluded from Git).
- Data verification: ZIP hashes match `sources.json` and the archived reports;
  PB counts: A=55, M=66, T=66.
- Report reproducibility: English A/M/T reports reproduced from local ZIP/PB files
  match the archived reports after normalizing generation timestamps and historical
  source labels. Translation preserved every reported number and source URL.
- Initial source: `krakow_ztp_m` — Mobilis buses;
  see the [city and feed selection decision](adr/001-krakow-m-first.md).
- Still missing: CI and repository configuration for PostgreSQL and MinIO.
- Limitations: the profiler is an exploratory tool. It does not yet provide full
  RAW archiving or a registry of every HTTP attempt. The short sample does not
  validate overnight service or daylight saving time transitions.
- Open questions: longer observation of M, time/delay consistency, service date
  resolution, vehicle state interpretation, and arrival estimation accuracy.
- Next task: CI running quality checks and tests.
