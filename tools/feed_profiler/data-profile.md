# Kraków — decision after GTFS-RT profiling

Study: 27 September 2026, 15:41–15:51 Europe/Warsaw time, roughly 10 minutes,
with fetches every 30 seconds. Sources: [ZTP Kraków](https://gtfs.ztp.krakow.pl/),
with A, T, and M collected separately.

**The pilot can proceed. Mobilis (M) is the strongest starting point in this
sample.** The sample confirms data availability and the ability to identify
arrival candidates. It does not yet establish actual arrival time accuracy or
full network coverage.

| Sample result | Trams (T) | MPK buses (A) | Mobilis (M) |
| --- | ---: | ---: | ---: |
| Valid realtime files | 66 | 55 | 66 |
| Fetch errors reported in the collector's final message | 0 | 11 | 0 |
| trip_id occurrences matching the corresponding ZIP | 99.7% | 100% | 100% |
| VP sequence and supplied stop_id consistent with the trip | 29.3% | 53.0% | 100% |
| Arrival candidates from transitions to STOPPED_AT | 0 | 38 | 158 |
| Candidates with GPS within 50 m of the stop | — | 37/38 | 158/158 |
| Explicit CANCELED updates | 0 | 0 | 0 |

Fetch error counts come from the recorded terminal summary. The archived reports
state that this collection has no `errors.jsonl`, so the ZIP/PB files alone cannot
independently confirm the number or causes of failures.

A candidate is an IN_TRANSIT_TO/INCOMING_AT → STOPPED_AT transition for the same
stop sequence, with fresh timestamps and a match to the schedule ZIP. Zero tram
candidates reflects the method's limitations with inconsistent sequences; it does
not imply that no trams arrived. Percentages describe occurrences across snapshots,
not unique completed trips.

## Pilot decisions

- **Source:** Kraków, initially Mobilis. The collector also supports A and T, but
  they require additional data quality handling.
- **Arrivals:** estimate from vehicle position and state history, retaining the
  time window and estimation quality. For the 158 Mobilis candidates, the median
  timestamp gap was 28 s and the maximum was 38 s. Median GPS distance from the
  stop was 10 m and the maximum was 40 m. This is a consistency check, not a
  measured estimator error.
- **Delays:** distinguish TripUpdates predictions from delays derived from
  estimated arrivals. The latter require correct service date resolution and
  matching to the schedule first.
- **TripUpdates times:** do not automatically store arrival.time as a confirmed
  arrival. In Mobilis, 104/105 repeated observations of a previously past time
  contained a revision.
- **Cancellations:** handle explicit CANCELED updates, while treating detection
  effectiveness as unvalidated. Absence from the feed does not imply cancellation.
  No CANCELED updates were observed in this sample.

The next validation should cover several hours, then a full day including a service
date transition. Only then can trip coverage, estimation stability, and rare events
be assessed beyond this short sample.

## Source material

- [Mobilis report](reports/krakow-M-20260927.md)
- [MPK bus report](reports/krakow-A-20260927.md)
- [Tram report](reports/krakow-T-20260927.md)

Raw ZIP files, source metadata, and snapshots are stored locally in the Git-ignored
`data/krakow-{A,M,T}-20260927/` directories and retained for reproducibility. Errors
from the first collection were reported in the terminal; the current collector
also writes `errors.jsonl`.
