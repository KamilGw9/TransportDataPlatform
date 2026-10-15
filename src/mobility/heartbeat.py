CHECKS = ("check_freshness", "refresh_models")


def send_heartbeat(client, namespace: str, check: str) -> None:
    # The alarm fires when heartbeats stop arriving rather than on a reported
    # failure, so a host or scheduler that is down raises it too.
    client.put_metric_data(
        Namespace=namespace,
        MetricData=[
            {
                "MetricName": "Heartbeat",
                "Dimensions": [{"Name": "Check", "Value": check}],
                "Value": 1,
            }
        ],
    )
