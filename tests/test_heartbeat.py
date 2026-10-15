import pytest

from mobility.cli import main
from mobility.heartbeat import send_heartbeat


class FakeCloudWatch:
    def __init__(self) -> None:
        self.metric_data: list[dict] = []

    def put_metric_data(self, **kwargs) -> None:
        self.metric_data.append(kwargs)


def test_send_heartbeat_reports_the_check_as_a_dimension() -> None:
    cloudwatch = FakeCloudWatch()

    send_heartbeat(cloudwatch, "UrbanMobility", "check_freshness")

    assert cloudwatch.metric_data == [
        {
            "Namespace": "UrbanMobility",
            "MetricData": [
                {
                    "MetricName": "Heartbeat",
                    "Dimensions": [{"Name": "Check", "Value": "check_freshness"}],
                    "Value": 1,
                }
            ],
        }
    ]


def test_send_heartbeat_is_skipped_without_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HEARTBEAT_NAMESPACE", raising=False)

    assert main(["send-heartbeat", "refresh_models"]) == 99


def test_send_heartbeat_rejects_unknown_check() -> None:
    with pytest.raises(SystemExit):
        main(["send-heartbeat", "check_fresness"])
