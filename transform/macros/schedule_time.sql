{#
    Mobilis and its buses keep GTFS times to the clock of the service date, not
    to noon minus 12 hours as GTFS defines them: when the clocks went back on
    2026-10-25, a stop at 27:30 was served at 03:30 local time. PostgreSQL takes
    a local time that occurs twice as the later one, as Mobilis did, and moves
    one that does not exist an hour forward. Europe/Warsaw is the
    agency_timezone of Mobilis.
#}
{% macro scheduled_time(service_date, seconds) %}
    (({{ service_date }} + {{ seconds }} * interval '1 second') AT TIME ZONE 'Europe/Warsaw')
{%- endmacro %}

{% macro service_hour(service_date, time) %}
    floor(extract(epoch FROM ({{ time }} AT TIME ZONE 'Europe/Warsaw') - {{ service_date }}) / 3600)::smallint
{%- endmacro %}
