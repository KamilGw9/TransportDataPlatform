# ADR 008: Scheduled times on the local clock

Status: accepted

Date: 2026-10-26

## Context

GTFS stop times are durations, such as `27:30:00`, that the models turn into
timestamps on a service date. The GTFS reference measures them from noon minus
12 hours of the service date, which is midnight except on the days the clocks
change, and the models did so.

On 2026-10-25 the clocks in Kraków went back from 03:00 to 02:00. The night
trips of the 2026-10-24 service after 02:00 ran an hour after the times the
rule gives: their 14 trusted arrivals were all about 3,600 s late, none of
their positions between 01:00 and 03:00 UTC fell within the scheduled time of
its trip, and in TripUpdates the predicted time minus the delay was exactly
3,600 s after the scheduled time from the rule. The night trips before 02:00,
and those of the previous Saturday, were on time. Mobilis keeps stop times to
the clock of the service date: `27:30:00` on 2026-10-24 is 03:30 local time on
2026-10-25. A stop at `26:30:00` was served at the second 02:30 of that night.

Two options were considered: keep the GTFS rule and list the night as a
limitation, or follow the clock as Mobilis does.

## Decision

- A stop time is the local time in Europe/Warsaw that many seconds after
  midnight of the service date on the clock, computed by the
  `scheduled_time` macro as `(service_date + seconds) AT TIME ZONE
  'Europe/Warsaw'`.
- A local time that occurs twice is taken as the later one, as PostgreSQL
  does and as the stop at `26:30:00` showed. A local time that does not exist
  moves an hour forward.
- Service hours in the marts are whole hours on the clock from midnight of the
  service date, computed by the `service_hour` macro, so the trips after
  02:00 on 2026-10-25 keep hours 26 and 27.

## Consequences

Arrival delays, the matching of positions to trip times and of predictions to
arrivals follow what the buses and the feed did on the night the clocks go
back. The models no longer follow the GTFS reference on the two nights a year
the clocks change, and another agency would have to be checked the same way
before reusing them. When the clocks go forward, on 2027-03-28, a stop time
between 02:00 and 03:00 does not exist on the clock; whether Mobilis moves it
forward is not known until that night has been collected. Rows built before
the change keep the old times until they are rebuilt.
