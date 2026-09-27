import argparse
import io
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from google.transit import gtfs_realtime_pb2 as rt

from profiler import collect, report


def make_schedule():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("agency.txt", "agency_timezone\nUTC\n")
        archive.writestr("routes.txt", "route_id\nr1\n")
        archive.writestr("stops.txt", "stop_id,stop_lat,stop_lon\ns1,50,19\ns2,51,20\n")
        archive.writestr("trips.txt", "trip_id,route_id\nt1,r1\n")
        archive.writestr("stop_times.txt", "trip_id,stop_sequence,stop_id,arrival_time,departure_time\nt1,1,s1,09:00:00,09:00:00\nt1,2,s2,09:01:00,09:01:00\n")
    return buffer.getvalue()


class KrakowTest(unittest.TestCase):
    def test_separate_streams_and_source_change_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            message = rt.FeedMessage()
            message.header.gtfs_realtime_version = "2.0"
            args = argparse.Namespace(output=target, gtfs_url="schedule", rt_url=["vp", "tu", "alerts"],
                                      label="Kraków", refresh_zip=False, once=True, hours=0, interval=30, report_after=False)
            with patch("profiler.fetch", side_effect=[make_schedule()] + [message.SerializeToString()] * 3):
                collect(args)
            self.assertEqual(len(list((target / "samples").rglob("*.pb"))), 3)
            self.assertEqual(json.loads((target / "sources.json").read_text())["rt_urls"], args.rt_url)
            args.refresh_zip = True
            with self.assertRaisesRegex(ValueError, "Cannot replace"):
                collect(args)
            args.refresh_zip = False
            args.rt_url = ["different"]
            with self.assertRaisesRegex(ValueError, "Source URLs changed"):
                collect(args)

    def test_failed_stream_does_not_hide_other_streams(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            message = rt.FeedMessage()
            message.header.gtfs_realtime_version = "2.0"
            args = argparse.Namespace(output=target, gtfs_url="schedule", rt_url=["vp", "tu"],
                                      label="Kraków", refresh_zip=False, once=True, hours=0, interval=30, report_after=False)
            with patch("profiler.fetch", side_effect=[make_schedule(), OSError("unavailable"), message.SerializeToString()]):
                collect(args)
            self.assertEqual(len(list((target / "samples").rglob("*.pb"))), 1)
            self.assertEqual(json.loads((target / "errors.jsonl").read_text())["url"], "vp")

    def test_absolute_time_without_sequence_and_past_revisions(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            stream = target / "samples" / "1"
            stream.mkdir(parents=True)
            (target / "gtfs.zip").write_bytes(make_schedule())
            base = int(datetime(2026, 9, 23, 10, tzinfo=timezone.utc).timestamp())
            for index in range(2):
                message = rt.FeedMessage()
                message.header.gtfs_realtime_version = "2.0"
                entity = message.entity.add(id="tu")
                entity.trip_update.trip.trip_id = "t1"
                stu = entity.trip_update.stop_time_update.add(stop_id="s1")
                stu.arrival.time = base - 60 + index * 10
                # Zero Unix timestamps must not become evidence of past arrivals.
                zero = entity.trip_update.stop_time_update.add(stop_id="s2")
                zero.arrival.time = 0
                name = datetime.fromtimestamp(base + index * 30, timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ.pb")
                (stream / name).write_bytes(message.SerializeToString())
            output = target / "report.md"
            report(argparse.Namespace(input=target, output=output))
            content = output.read_text()
            self.assertIn("STU z czasem zdarzenia w przeszłości (time lub rozkład + delay) | 2/2 (100.0%)", content)
            self.assertIn("już w poprzedniej próbce był przeszły: 1/1 (100.0%)", content)
            self.assertIn("Czasy zdarzeń ≤0 (pomijane w analizie czasów) | 2", content)

    def test_arrival_candidates_require_fresh_matching_vehicle_states(self):
        for stop_id, age, expected in (("s1", 5, 1), ("s2", 5, 0), ("s1", 120, 0)):
            with self.subTest(stop_id=stop_id, age=age), tempfile.TemporaryDirectory() as directory:
                target = Path(directory)
                stream = target / "samples" / "0"
                stream.mkdir(parents=True)
                (target / "gtfs.zip").write_bytes(make_schedule())
                base = int(datetime(2026, 9, 23, 10, tzinfo=timezone.utc).timestamp())
                for index, status in enumerate((rt.VehiclePosition.IN_TRANSIT_TO, rt.VehiclePosition.STOPPED_AT)):
                    message = rt.FeedMessage()
                    message.header.gtfs_realtime_version = "2.0"
                    vp = message.entity.add(id="vp").vehicle
                    vp.trip.trip_id = "t1"
                    vp.vehicle.id = "v1"
                    vp.current_stop_sequence = 1
                    vp.stop_id = stop_id
                    vp.current_status = status
                    vp.position.latitude = 50
                    vp.position.longitude = 19
                    vp.timestamp = base + index * 30 - age
                    name = datetime.fromtimestamp(base + index * 30, timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ.pb")
                    (stream / name).write_bytes(message.SerializeToString())
                output = target / "report.md"
                report(argparse.Namespace(input=target, output=output))
                self.assertIn(f"STOPPED_AT dla tego samego przystanku: {expected}.", output.read_text())
                if expected:
                    self.assertIn("odległość od przystanku ≤50 m: 1/1 (100.0%)", output.read_text())


class ReportTest(unittest.TestCase):
    def test_matches_schedule_and_detects_past_delay_and_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "samples").mkdir()
            with zipfile.ZipFile(source / "gtfs.zip", "w") as archive:
                archive.writestr("agency.txt", "agency_timezone\nUTC\n")
                archive.writestr("routes.txt", "route_id\nr1\n")
                archive.writestr("stops.txt", "stop_id\ns1\n")
                archive.writestr("trips.txt", "trip_id,route_id\nt1,r1\nt2,r1\n")
                archive.writestr("stop_times.txt", "trip_id,stop_sequence,stop_id,arrival_time,departure_time\nt1,1,s1,09:00:00,09:00:00\n")
            message = rt.FeedMessage()
            message.header.gtfs_realtime_version = "2.0"
            update_entity = message.entity.add()
            update_entity.id = "tu1"
            update = update_entity.trip_update
            update.trip.trip_id = "t1"
            update.trip.start_date = "20260923"
            stu = update.stop_time_update.add()
            stu.stop_sequence = 1
            stu.stop_id = "s1"
            stu.arrival.delay = 60
            vehicle_entity = message.entity.add()
            vehicle_entity.id = "vp1"
            vehicle = vehicle_entity.vehicle
            vehicle.trip.trip_id = "t1"
            vehicle.trip.route_id = "wrong-route"
            vehicle.stop_id = "wrong-stop"
            canceled_entity = message.entity.add()
            canceled_entity.id = "tu2"
            canceled = canceled_entity.trip_update
            canceled.trip.trip_id = "t2"
            canceled.trip.schedule_relationship = rt.TripDescriptor.CANCELED
            (source / "samples" / "20260923T100000.000000Z.pb").write_bytes(message.SerializeToString())
            output = source / "report.md"
            report(argparse.Namespace(input=source, output=output))
            content = output.read_text()
            self.assertIn("STU z czasem zdarzenia w przeszłości (time lub rozkład + delay) | 1/1 (100.0%)", content)
            self.assertIn("TripUpdate CANCELED | 1", content)
            self.assertIn("| trip_id | 3/3 (100.0%)", content)
            self.assertIn("| route_id | 0/1 (0.0%)", content)
            self.assertIn("| stop_id | 1/2 (50.0%)", content)
            self.assertIn("stop_sequence` dopasowane", content)


if __name__ == "__main__":
    unittest.main()
