# Kraków ZTP — GTFS and GTFS-RT profiler

Downloads a schedule and three separate realtime streams from the
[ZTP Kraków server](https://gtfs.ztp.krakow.pl/). Checks identifier consistency,
data freshness, times and delays, cancellations, and the usefulness of vehicle
history for arrival estimation.

| `--network` | Scope | Schedule | Realtime streams |
| --- | --- | --- | --- |
| `T` (default) | Trams | `GTFS_KRK_T.zip` | `VehiclePositions_T.pb`, `TripUpdates_T.pb`, `ServiceAlerts_T.pb` |
| `A` | MPK buses | `GTFS_KRK_A.zip` | Corresponding files ending in `_A` |
| `M` | Mobilis buses | `GTFS_KRK_M.zip` | Corresponding files ending in `_M` |

Each feed is checked against its own ZIP. Identifiers from different feeds must
not be joined without source namespaces.

## Setup and usage

From the repository root, prepare the environment:

```bash
uv sync --locked
```

Mobilis is the project's initial source. Select it explicitly with `--network M`
(the CLI default remains T):

```bash
uv run python tools/feed_profiler/profiler.py collect --network M --hours 4 --interval 30 --report-after
```

Without `--output`, each run creates a new directory at
`tools/feed_profiler/data/krakow-<network>-<UTC timestamp>/`. `--once` fetches one
cycle of VP, TU, and Alerts for the selected network. To investigate A or T,
start a separate run with a different `--network`. The collector runs in the
current terminal; automatic service restart is not configured yet.

Generate a report from saved snapshots and run the tests:

```bash
uv run python tools/feed_profiler/profiler.py report --input tools/feed_profiler/data/krakow-M-20260927
uv run pytest
```

The `report` example refers to the local collection from 27 September. In a fresh
checkout, use the directory created by your own `collect` run; raw data is not
included in Git. Tests use synthetic data and do not require network access.

`--report-after` and `report` write `data-profile.md` inside the collection
directory. Use `report --output <file>` for a different path. The study summary is
in [data-profile.md](data-profile.md), and archived reports are in `reports/`.

Custom sources require both `--gtfs-url` and `--rt-url` (repeated for each stream).
The optional `--label` describes the report. Reusing `--output` appends snapshots
only if the sources match. Use a new directory for a new schedule version.

Raw data in the Git-ignored `data/` directory includes the ZIP, its hash and source
URLs in `sources.json`, separate `samples/0`, `samples/1`, and `samples/2`
directories, and fetch errors in `errors.jsonl`. Stream numbers follow the
`rt_urls` order in the metadata. A failure in one realtime stream does not stop
collection of the others. Collections made before error logging was added require
checking the terminal log.

## Profiler limitations

This is an exploratory tool. PB files are saved only after successful decoding;
invalid responses are not retained as RAW. `errors.jsonl` covers failures in the
realtime loop, but not the initial ZIP download. There is no complete HTTP attempt
registry, automatic retry, or periodic download of new schedule versions.

ZIP matching checks identifiers, not calendar-based service activity. When
`start_date` is absent, history uses the local date to group observations.
Schedule time calculations need further work for daylight saving time transitions;
current results do not validate overnight trips or service date resolution.

Reports count occurrences across snapshots, not unique completed trips. A past
`arrival.time` does not establish a confirmed actual arrival; we also examine
later revisions. Candidate arrival windows come from fresh, ZIP-matched
`IN_TRANSIT_TO/INCOMING_AT → STOPPED_AT` transitions. These still require validation
against GPS and the provider's reporting semantics. A trip missing from the feed
does not establish cancellation. A short sample cannot assess full network coverage
or rare events; validation should cover several hours, then a full day.
