# ADR 001: Start with Kraków Mobilis

Status: accepted

Date: 2026-09-27

## Context

Rzeszów was investigated first. In the sampled realtime feed, `arrival.time` and
explicit `current_status` were absent, while `arrival.delay` and `departure.delay`
had identical values. This limited our ability to distinguish arrivals from
departures and estimate arrival times. Detected events were not confirmed arrivals.

We then profiled the Kraków feeds: A (MPK buses), M (Mobilis), and T (trams).
In the roughly ten-minute sample, M had timestamps on all TripUpdates and
consistent stop identifiers and sequences in VehiclePositions. We found 158
candidate transitions to `STOPPED_AT`, all with GPS positions within 50 m of the
stop. This supports further investigation of arrival windows; the method's
accuracy remains unvalidated.

Comparison: [A/M/T profiling findings](../../tools/feed_profiler/data-profile.md).

## Decision

Build the first data pipeline for Kraków, starting with `krakow_ztp_m`.
The alternatives considered were Rzeszów and the Kraków A/M/T feeds. We choose
M because of its field consistency in the sample. Add A and T in a later extension.

## Consequences

- Include `source_id` in identifier namespaces from the start.
- Validate the choice of M through longer observation, including overnight trips.
- Retain `arrival.time` as the provider-reported time; the field's presence alone
  does not establish whether it is a prediction or a measurement.
- Vehicle state transitions can yield candidate arrival windows. Timestamps,
  GPS positions, and the provider's state reporting require separate validation.
