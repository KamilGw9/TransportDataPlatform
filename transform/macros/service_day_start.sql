{#
    GTFS times count from noon minus 12 hours of the service date in the agency
    time zone, which differs from midnight on the days the clocks change.
    Europe/Warsaw is the agency_timezone of Mobilis.
#}
{% macro service_day_start(service_date) %}
    (({{ service_date }} + time '12:00') AT TIME ZONE 'Europe/Warsaw' - interval '12 hours')
{%- endmacro %}
