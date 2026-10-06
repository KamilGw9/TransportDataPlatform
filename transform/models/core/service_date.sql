-- Dates on which each service of a schedule version runs, by the GTFS rule:
-- a weekday within the calendar range, unless calendar_dates removes it, plus
-- every date that calendar_dates adds. Mobilis sets all weekdays to false and
-- lists each date in calendar_dates.
WITH calendar_day AS (
    SELECT calendar.schedule_sha256, calendar.service_id, day::date AS service_date
    FROM {{ source('staging', 'schedule_calendar') }} AS calendar
    CROSS JOIN LATERAL
        generate_series(calendar.start_date, calendar.end_date, interval '1 day') AS day
    WHERE (ARRAY[
        calendar.monday, calendar.tuesday, calendar.wednesday, calendar.thursday,
        calendar.friday, calendar.saturday, calendar.sunday
    ])[extract(isodow FROM day)]
)
SELECT schedule_sha256, service_id, service_date
FROM calendar_day
WHERE NOT EXISTS (
    SELECT
    FROM {{ source('staging', 'schedule_calendar_date') }} AS removed
    WHERE removed.schedule_sha256 = calendar_day.schedule_sha256
        AND removed.service_id = calendar_day.service_id
        AND removed.service_date = calendar_day.service_date
        AND removed.exception_type = 2
)
UNION
SELECT schedule_sha256, service_id, service_date
FROM {{ source('staging', 'schedule_calendar_date') }}
WHERE exception_type = 1
