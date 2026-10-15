locals {
  # Must match HEARTBEAT_NAMESPACE in compose.aws.yaml.
  heartbeat_namespace = "UrbanMobility"

  # Each check runs as a DAG that sends a heartbeat after a successful run.
  # An alarm fires after the given number of periods without one, which
  # covers failed runs as well as a stopped host or scheduler.
  heartbeat_checks = {
    check_freshness = {
      period             = 300
      evaluation_periods = 3
      description        = "No successful check_freshness run for 15 minutes: a GTFS-RT feed is stale, or Airflow or the host is down. The task log in Airflow names the stale feed."
    }
    refresh_models = {
      period             = 1800
      evaluation_periods = 2
      description        = "No successful refresh_models run for an hour: a load, dbt build or prune failed, or Airflow or the host is down. The task logs in Airflow show which."
    }
  }
}

resource "aws_sns_topic" "alerts" {
  name = "urban-mobility-alerts"
}

# The address has to confirm the subscription from the email that AWS sends
# after the first apply; until then nothing is delivered.
resource "aws_sns_topic_subscription" "alert_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "heartbeat" {
  for_each = local.heartbeat_checks

  alarm_name        = "urban-mobility-${each.key}"
  alarm_description = each.value.description
  namespace         = local.heartbeat_namespace
  metric_name       = "Heartbeat"
  dimensions = {
    Check = each.key
  }
  statistic           = "SampleCount"
  period              = each.value.period
  evaluation_periods  = each.value.evaluation_periods
  comparison_operator = "LessThanThreshold"
  threshold           = 1
  # No data is what a stopped host looks like.
  treat_missing_data = "breaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}
