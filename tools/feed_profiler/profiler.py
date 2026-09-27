#!/usr/bin/env python3
"""Collect and profile a matching GTFS Schedule / GTFS Realtime pair."""

import argparse
import csv
import hashlib
import io
import json
import math
import time
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2 as rt

BASE_URL = "https://gtfs.ztp.krakow.pl"
NETWORKS = {"T": "trams", "A": "MPK buses", "M": "Mobilis"}


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def fetch(url):
    request = urllib.request.Request(
        url, headers={"User-Agent": "transport-feed-profiler/2.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def collect(args):
    target = args.output
    samples = target / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    zip_path = target / "gtfs.zip"
    metadata = target / "sources.json"
    if not metadata.exists() and (zip_path.exists() or any(samples.rglob("*.pb"))):
        raise ValueError(
            "Existing data lacks source metadata; use a new --output directory"
        )
    if args.refresh_zip and any(samples.rglob("*.pb")):
        raise ValueError(
            "Cannot replace GTFS ZIP with existing samples; use a new --output directory"
        )
    if metadata.exists() and not args.refresh_zip:
        old = json.loads(metadata.read_text())
        if (
            old.get("gtfs_url") != args.gtfs_url
            or old.get("rt_urls", [old.get("rt_url")]) != args.rt_url
        ):
            raise ValueError(
                "Source URLs changed; use a new --output directory for a new feed pair"
            )
    if not zip_path.exists() or args.refresh_zip:
        payload = fetch(args.gtfs_url)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if archive.testzip() is not None:
                raise ValueError("GTFS ZIP failed CRC check")
        zip_path.write_bytes(payload)
    metadata.write_text(
        json.dumps(
            {
                "label": args.label,
                "gtfs_url": args.gtfs_url,
                "rt_urls": args.rt_url,
                "zip_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    (target / "errors.jsonl").touch(exist_ok=True)
    deadline = time.monotonic() + args.hours * 3600
    next_fetch = time.monotonic()
    ok = errors = 0
    while True:
        for index, url in enumerate(args.rt_url):
            try:
                payload = fetch(url)
                message = rt.FeedMessage()
                message.ParseFromString(payload)
                if not message.IsInitialized():
                    raise ValueError("GTFS-RT message lacks required fields")
                fetched_at = time.time()
                name = datetime.fromtimestamp(fetched_at, timezone.utc).strftime(
                    "%Y%m%dT%H%M%S.%fZ"
                )
                stream = samples / str(index)
                stream.mkdir(exist_ok=True)
                (stream / f"{name}.pb").write_bytes(payload)
                ok += 1
                print(
                    f"{iso(fetched_at)}: {url}: {len(message.entity)} entities",
                    flush=True,
                )
            except (OSError, ValueError, DecodeError) as exc:
                errors += 1
                with (target / "errors.jsonl").open("a", encoding="utf-8") as log:
                    log.write(
                        json.dumps(
                            {
                                "fetched_at": iso(time.time()),
                                "url": url,
                                "error": str(exc),
                            }
                        )
                        + "\n"
                    )
                print(f"fetch error: {url}: {exc}", flush=True)
        if args.once or time.monotonic() >= deadline:
            break
        next_fetch = max(next_fetch + args.interval, time.monotonic())
        time.sleep(max(0, min(next_fetch, deadline) - time.monotonic()))
    print(f"Saved {ok} snapshots; {errors} errors")
    if not ok:
        raise SystemExit(1)
    if args.report_after:
        report(argparse.Namespace(input=target, output=target / "data-profile.md"))


def rows(archive, filename):
    paths = [name for name in archive.namelist() if name.split("/")[-1] == filename]
    if len(paths) != 1:
        raise ValueError(
            f"Expected exactly one {filename} in GTFS ZIP, found {len(paths)}"
        )
    with (
        archive.open(paths[0]) as raw,
        io.TextIOWrapper(raw, encoding="utf-8-sig", newline="") as stream,
    ):
        yield from csv.DictReader(stream)


def schedule(path):
    with zipfile.ZipFile(path) as archive:
        timezones = {row["agency_timezone"] for row in rows(archive, "agency.txt")}
        if len(timezones) != 1:
            raise ValueError(f"Expected one agency timezone, got {timezones}")
        routes = {row["route_id"] for row in rows(archive, "routes.txt")}
        stops = {row["stop_id"] for row in rows(archive, "stops.txt")}
        trip_routes = {
            row["trip_id"]: row["route_id"] for row in rows(archive, "trips.txt")
        }
        stop_times = 0
        trip_stops = set()
        trip_sequences = {}
        for row in rows(archive, "stop_times.txt"):
            stop_times += 1
            trip_stops.add((row["trip_id"], row["stop_id"]))
            trip_sequences[(row["trip_id"], int(row["stop_sequence"]))] = (
                row["stop_id"],
                row["arrival_time"],
                row["departure_time"],
            )
    return (
        routes,
        stops,
        trip_routes,
        stop_times,
        trip_stops,
        trip_sequences,
        ZoneInfo(next(iter(timezones))),
    )


def scheduled_timestamp(service_date, clock, tz):
    if not service_date or not clock:
        return None
    try:
        base = datetime.strptime(service_date, "%Y%m%d").replace(tzinfo=tz)
        hours, minutes, seconds = (int(part) for part in clock.split(":"))
        return (
            base + timedelta(hours=hours, minutes=minutes, seconds=seconds)
        ).timestamp()
    except (ValueError, OverflowError):
        return None


def rate(hit, total):
    return (
        f"{hit}/{total} ({100 * hit / total:.1f}%)" if total else "n/a (0 observations)"
    )


def distance_m(lat, lon, other_lat, other_lon):
    if not (
        -90 <= lat <= 90
        and -90 <= other_lat <= 90
        and -180 <= lon <= 180
        and -180 <= other_lon <= 180
    ):
        return None
    phi, other_phi = math.radians(lat), math.radians(other_lat)
    a = (
        math.sin((other_phi - phi) / 2) ** 2
        + math.cos(phi)
        * math.cos(other_phi)
        * math.sin(math.radians(other_lon - lon) / 2) ** 2
    )
    return 6371000 * 2 * math.asin(math.sqrt(min(1, max(0, a))))


def report(args):
    source = args.input
    zip_path = source / "gtfs.zip"
    paths = sorted((source / "samples").rglob("*.pb"), key=lambda path: path.name)
    if not paths:
        raise ValueError("No .pb snapshots in samples directory")
    routes, stops, trip_routes, stop_times, trip_stops, trip_sequences, tz = schedule(
        zip_path
    )
    stop_coordinates = {}
    with zipfile.ZipFile(zip_path) as archive:
        for row in rows(archive, "stops.txt"):
            try:
                stop_coordinates[row["stop_id"]] = (
                    float(row["stop_lat"]),
                    float(row["stop_lon"]),
                )
            except (KeyError, ValueError):
                pass
    c = Counter()
    examples = {
        key: set() for key in ("trip", "route", "stop", "trip_stop", "sequence")
    }
    unique = {key: set() for key in ("trip", "route", "stop")}
    trip_max_sequence = {}
    stop_lookup = {}
    for trip_id, sequence in trip_sequences:
        trip_max_sequence[trip_id] = max(sequence, trip_max_sequence.get(trip_id, 0))
        stop_lookup.setdefault(
            (trip_id, trip_sequences[(trip_id, sequence)][0]), []
        ).append(sequence)
    vp_ages, tu_ages = [], []
    stream_counts, stream_empty = Counter(), Counter()
    stream_ages = {}
    previous_vp, arrival_history = {}, {}
    arrival_intervals, arrival_distances, delays = [], [], []
    first, last = None, None
    hashes = set()
    for path in paths:
        fetched = (
            datetime.strptime(path.stem, "%Y%m%dT%H%M%S.%fZ")
            .replace(tzinfo=timezone.utc)
            .timestamp()
        )
        first = fetched if first is None else min(first, fetched)
        last = fetched if last is None else max(last, fetched)
        payload = path.read_bytes()
        hashes.add(hashlib.sha256(payload).digest())
        message = rt.FeedMessage()
        try:
            message.ParseFromString(payload)
        except DecodeError:
            c["invalid"] += 1
            continue
        if not message.IsInitialized():
            c["invalid"] += 1
            continue
        c["snapshots"] += 1
        stream_name = (
            path.parent.name if path.parent != source / "samples" else "legacy"
        )
        stream_counts[stream_name] += 1
        stream_empty[stream_name] += not message.entity
        c["differential"] += message.header.incrementality == rt.FeedHeader.DIFFERENTIAL
        if message.header.HasField("timestamp"):
            stream_ages.setdefault(stream_name, []).append(
                fetched - message.header.timestamp
            )
        for entity in message.entity:
            if entity.HasField("vehicle"):
                vp = entity.vehicle
                c["vp"] += 1
                c["vp_vehicle_id"] += bool(vp.HasField("vehicle") and vp.vehicle.id)
                c["vp_trip_id"] += bool(vp.HasField("trip") and vp.trip.trip_id)
                c["vp_timestamp"] += vp.HasField("timestamp")
                c["vp_position"] += (
                    vp.HasField("position")
                    and vp.position.HasField("latitude")
                    and vp.position.HasField("longitude")
                )
                c["vp_status"] += vp.HasField("current_status")
                c["vp_stopped"] += (
                    vp.HasField("current_status")
                    and vp.current_status == rt.VehiclePosition.STOPPED_AT
                )
                if vp.HasField("current_stop_sequence"):
                    c["vp_sequence_checked"] += 1
                    planned = trip_sequences.get(
                        (vp.trip.trip_id, vp.current_stop_sequence)
                    )
                    matched = planned is not None and (
                        not vp.stop_id or planned[0] == vp.stop_id
                    )
                    c["vp_sequence_match"] += matched
                    next_stop = trip_sequences.get(
                        (vp.trip.trip_id, vp.current_stop_sequence + 1)
                    )
                    c["vp_stop_next"] += (
                        not matched
                        and bool(vp.stop_id)
                        and next_stop is not None
                        and next_stop[0] == vp.stop_id
                    )
                    # Only fresh, explicitly reported, schedule-matched states are candidates.
                    if (
                        matched
                        and vp.vehicle.id
                        and vp.HasField("timestamp")
                        and vp.HasField("current_status")
                        and 0 <= fetched - vp.timestamp <= 90
                    ):
                        day = vp.trip.start_date or datetime.fromtimestamp(
                            vp.timestamp, tz
                        ).strftime("%Y%m%d")
                        key = (
                            stream_name,
                            day,
                            vp.vehicle.id,
                            vp.trip.trip_id,
                            vp.trip.start_time,
                        )
                        old = previous_vp.get(key)
                        current = (
                            vp.timestamp,
                            vp.current_stop_sequence,
                            vp.current_status,
                        )
                        if old and 0 < current[0] - old[0] <= 90:
                            c["vp_sequence_advance"] += current[1] > old[1]
                            if (
                                current[1] == old[1]
                                and old[2]
                                in (
                                    rt.VehiclePosition.IN_TRANSIT_TO,
                                    rt.VehiclePosition.INCOMING_AT,
                                )
                                and current[2] == rt.VehiclePosition.STOPPED_AT
                            ):
                                arrival_intervals.append(current[0] - old[0])
                                coordinates = stop_coordinates.get(planned[0])
                                if (
                                    coordinates
                                    and vp.HasField("position")
                                    and vp.position.HasField("latitude")
                                    and vp.position.HasField("longitude")
                                ):
                                    distance = distance_m(
                                        vp.position.latitude,
                                        vp.position.longitude,
                                        *coordinates,
                                    )
                                    if distance is not None:
                                        arrival_distances.append(distance)
                        if old is None or current[0] > old[0]:
                            previous_vp[key] = current
                if vp.HasField("timestamp"):
                    vp_ages.append(fetched - vp.timestamp)
                if vp.HasField("trip"):
                    check_descriptor(vp.trip, trip_routes, routes, c, examples, unique)
                if vp.stop_id:
                    check_stop(vp.stop_id, stops, c, examples, unique)
            if entity.HasField("trip_update"):
                tu = entity.trip_update
                c["tu"] += 1
                c["tu_trip_id"] += bool(tu.trip.trip_id)
                c["tu_start_date"] += bool(tu.trip.start_date)
                c["tu_timestamp"] += tu.HasField("timestamp")
                check_descriptor(tu.trip, trip_routes, routes, c, examples, unique)
                if tu.trip.schedule_relationship == rt.TripDescriptor.CANCELED:
                    c["canceled"] += 1
                if tu.HasField("timestamp"):
                    tu_ages.append(fetched - tu.timestamp)
                for stu in tu.stop_time_update:
                    c["stu"] += 1
                    c["arrival_time"] += stu.HasField(
                        "arrival"
                    ) and stu.arrival.HasField("time")
                    c["arrival_delay"] += stu.HasField(
                        "arrival"
                    ) and stu.arrival.HasField("delay")
                    c["arrival_uncertainty"] += stu.HasField(
                        "arrival"
                    ) and stu.arrival.HasField("uncertainty")
                    c["arrival_uncertainty_zero"] += (
                        stu.HasField("arrival")
                        and stu.arrival.HasField("uncertainty")
                        and stu.arrival.uncertainty == 0
                    )
                    c["departure_time"] += stu.HasField(
                        "departure"
                    ) and stu.departure.HasField("time")
                    c["departure_delay"] += stu.HasField(
                        "departure"
                    ) and stu.departure.HasField("delay")
                    c["nonpositive_event_time"] += sum(
                        stu.HasField(field)
                        and getattr(stu, field).HasField("time")
                        and getattr(stu, field).time <= 0
                        for field in ("arrival", "departure")
                    )
                    c["skipped"] += (
                        stu.schedule_relationship
                        == rt.TripUpdate.StopTimeUpdate.SKIPPED
                    )
                    c["no_data"] += (
                        stu.schedule_relationship
                        == rt.TripUpdate.StopTimeUpdate.NO_DATA
                    )
                    if stu.HasField("arrival") and stu.arrival.HasField("delay"):
                        delays.append(stu.arrival.delay)
                    if stu.HasField("arrival") and stu.arrival.HasField("time"):
                        c["past_arrival_time"] += 0 < stu.arrival.time < fetched
                    schedule_stop = None
                    if stu.HasField("stop_sequence"):
                        c["sequence_checked"] += 1
                        key = (tu.trip.trip_id, stu.stop_sequence)
                        schedule_stop = trip_sequences.get(key)
                        if schedule_stop:
                            c["sequence_match"] += 1
                            if stu.stop_id:
                                c["sequence_stop_checked"] += 1
                                c["sequence_stop_match"] += (
                                    schedule_stop[0] == stu.stop_id
                                )
                        else:
                            c["sequence_beyond_end"] += (
                                stu.stop_sequence
                                > trip_max_sequence.get(tu.trip.trip_id, float("inf"))
                            )
                            if len(examples["sequence"]) < 5:
                                examples["sequence"].add(
                                    f"{tu.trip.trip_id}/{stu.stop_sequence}"
                                )
                    elif stu.stop_id:
                        sequences = stop_lookup.get((tu.trip.trip_id, stu.stop_id), [])
                        if len(sequences) == 1:
                            schedule_stop = trip_sequences[
                                (tu.trip.trip_id, sequences[0])
                            ]
                    # Absolute timestamps do not require stop_sequence or a static join.
                    event_time = None
                    for field, clock_index in (("arrival", 1), ("departure", 2)):
                        if not stu.HasField(field):
                            continue
                        event = getattr(stu, field)
                        if event.HasField("time"):
                            if event.time <= 0:
                                continue
                            event_time = event.time
                            break
                        if event.HasField("delay") and schedule_stop:
                            planned_time = scheduled_timestamp(
                                tu.trip.start_date, schedule_stop[clock_index], tz
                            )
                            if planned_time is not None:
                                event_time = planned_time + event.delay
                                break
                    if event_time is not None:
                        c["past_stu_evaluable"] += 1
                        c["past_stu"] += event_time < fetched
                    if (
                        stu.HasField("arrival")
                        and stu.arrival.HasField("time")
                        and stu.arrival.time > 0
                    ):
                        day = tu.trip.start_date or datetime.fromtimestamp(
                            fetched, tz
                        ).strftime("%Y%m%d")
                        stop_key = (
                            ("sequence", stu.stop_sequence)
                            if stu.HasField("stop_sequence")
                            else ("stop", stu.stop_id)
                        )
                        key = (
                            stream_name,
                            day,
                            tu.trip.trip_id,
                            tu.trip.start_time,
                            stop_key,
                        )
                        old = arrival_history.get(key)
                        if old and old[0] < fetched:
                            c["arrival_repeated"] += 1
                            c["arrival_revised"] += old[1] != stu.arrival.time
                            if old[1] < old[0]:
                                c["arrival_past_repeated"] += 1
                                c["arrival_past_revised"] += old[1] != stu.arrival.time
                        arrival_history[key] = (fetched, stu.arrival.time)
                    if stu.stop_id:
                        check_stop(stu.stop_id, stops, c, examples, unique)
                        if tu.trip.trip_id in trip_routes:
                            c["trip_stop_checked"] += 1
                            if (tu.trip.trip_id, stu.stop_id) in trip_stops:
                                c["trip_stop_match"] += 1
                            elif len(examples["trip_stop"]) < 5:
                                examples["trip_stop"].add(
                                    f"{tu.trip.trip_id}/{stu.stop_id}"
                                )
            if entity.HasField("alert"):
                c["alerts"] += 1
                if entity.alert.effect == rt.Alert.NO_SERVICE:
                    c["no_service_alerts"] += 1
                for selector in entity.alert.informed_entity:
                    if selector.HasField("trip"):
                        check_descriptor(
                            selector.trip, trip_routes, routes, c, examples, unique
                        )
                    if selector.route_id:
                        c["route_checked"] += 1
                        unique["route"].add(selector.route_id)
                        if selector.route_id in routes:
                            c["route_match"] += 1
                        elif len(examples["route"]) < 5:
                            examples["route"].add(selector.route_id)
                    if selector.stop_id:
                        check_stop(selector.stop_id, stops, c, examples, unique)
    meta_path = source / "sources.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    zip_hash = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if meta.get("zip_sha256") and meta["zip_sha256"] != zip_hash:
        raise ValueError("GTFS ZIP hash differs from sources.json")
    duration = (last - first) / 3600

    def age_stats(values):
        if not values:
            return "n/a (missing timestamp)"
        ordered = sorted(values)
        return f"median {ordered[len(ordered) // 2]:.0f} s; >90 s: {rate(sum(x > 90 for x in values), len(values))}; maximum {max(values):.0f} s"

    def examples_line(key):
        return ", ".join(sorted(examples[key])) or "none"

    lines = [
        f"# {meta.get('label', 'GTFS')} — GTFS data profile",
        "",
        f"Generated: {iso(time.time())}. Data: {iso(first)} – {iso(last)} ({duration:.2f} h); {c['snapshots']} valid snapshots from {len(paths)} files, {len(hashes)} distinct payloads.",
        "",
        f"GTFS Schedule: {meta.get('gtfs_url', str(zip_path))}  ",
        f"GTFS-RT: {', '.join(meta.get('rt_urls', [meta.get('rt_url', str(source / 'samples'))]))}  ",
        f"SHA-256 ZIP: `{zip_hash}`",
        "",
        "Identifier matching applies only to the supplied ZIP and realtime streams. Separate realtime sources are saved as separate files; the file count is not the number of fetch cycles.",
        "",
        "## GTFS Schedule",
        "",
        "| Metric | Count |",
        "| --- | ---: |",
        f"| routes | {len(routes)} |",
        f"| stops | {len(stops)} |",
        f"| trips | {len(trip_routes)} |",
        f"| stop_times | {stop_times} |",
        "",
        "## GTFS-RT — field presence",
        "",
        "The denominator counts occurrences across snapshots, not unique vehicles or trips. Empty identifiers count as missing.",
        "",
        "| Field | Observations |",
        "| --- | ---: |",
        f"| VehiclePosition | {c['vp']} |",
        f"| VP vehicle.id | {rate(c['vp_vehicle_id'], c['vp'])} |",
        f"| VP trip.trip_id | {rate(c['vp_trip_id'], c['vp'])} |",
        f"| VP timestamp | {rate(c['vp_timestamp'], c['vp'])} |",
        f"| VP coordinates | {rate(c['vp_position'], c['vp'])} |",
        f"| VP explicit current_status | {rate(c['vp_status'], c['vp'])} |",
        f"| VP STOPPED_AT | {rate(c['vp_stopped'], c['vp'])} |",
        f"| VP sequence and optional stop_id consistent with the trip | {rate(c['vp_sequence_match'], c['vp_sequence_checked'])} |",
        f"| VP mismatch: stop_id points to sequence +1 | {c['vp_stop_next']} |",
        f"| TripUpdate | {c['tu']} |",
        f"| TU trip.trip_id | {rate(c['tu_trip_id'], c['tu'])} |",
        f"| TU trip.start_date | {rate(c['tu_start_date'], c['tu'])} |",
        f"| TU timestamp | {rate(c['tu_timestamp'], c['tu'])} |",
        f"| StopTimeUpdate | {c['stu']} |",
        f"| STU arrival.time | {rate(c['arrival_time'], c['stu'])} |",
        f"| STU arrival.delay | {rate(c['arrival_delay'], c['stu'])} |",
        f"| STU arrival.uncertainty | {rate(c['arrival_uncertainty'], c['stu'])} |",
        f"| STU arrival.uncertainty = 0 (explicit) | {rate(c['arrival_uncertainty_zero'], c['stu'])} |",
        f"| STU departure.time | {rate(c['departure_time'], c['stu'])} |",
        f"| STU departure.delay | {rate(c['departure_delay'], c['stu'])} |",
        f"| STU arrival.time earlier than fetch time | {rate(c['past_arrival_time'], c['arrival_time'])} |",
        f"| STU with a past event time (time or schedule + delay) | {rate(c['past_stu'], c['past_stu_evaluable'])} |",
        f"| TripUpdate CANCELED | {c['canceled']} |",
        f"| STU SKIPPED | {c['skipped']} |",
        f"| STU NO_DATA | {c['no_data']} |",
        f"| Event times ≤0 (excluded from time analysis) | {c['nonpositive_event_time']} |",
        f"| ServiceAlert | {c['alerts']} |",
        "",
        f"Alert effect=NO_SERVICE: {c['no_service_alerts']} occurrences.",
        "",
        "## Identifier matching against the ZIP",
        "",
        "Nonempty identifiers in VP, TU, STU, and Alert.informed_entity are checked. Repeated occurrences across snapshots remain in the denominator. An explicit route_id in a trip descriptor must also match the route assigned to that trip_id in the ZIP.",
        "",
        "| Identifier | Matching occurrences | Unique values | Mismatch examples |",
        "| --- | ---: | ---: | --- |",
        f"| trip_id | {rate(c['trip_match'], c['trip_checked'])} | {len(unique['trip'])} | {examples_line('trip')} |",
        f"| route_id | {rate(c['route_match'], c['route_checked'])} | {len(unique['route'])} | {examples_line('route')} |",
        f"| stop_id | {rate(c['stop_match'], c['stop_checked'])} | {len(unique['stop'])} | {examples_line('stop')} |",
        f"| trip_id/stop_id pair in stop_times | {rate(c['trip_stop_match'], c['trip_stop_checked'])} | — | {examples_line('trip_stop')} |",
        "",
        f"Explicit `stop_sequence` matched to `(trip_id, stop_sequence)` in GTFS: {rate(c['sequence_match'], c['sequence_checked'])}. Mismatches: {examples_line('sequence')}; {c['sequence_beyond_end']} occurrences have a sequence beyond the final stop in GTFS. Explicit `stop_id` consistent with the stop resolved through `stop_sequence`: {rate(c['sequence_stop_match'], c['sequence_stop_checked'])}.",
        "",
        "Note: `route_id` and `stop_id` are checked only when explicitly present in GTFS-RT. `stop_sequence` is not `stop_id`; sequence matching identifies a stop indirectly but does not validate the supplied `stop_id`.",
        "",
        "## Freshness",
        "",
        "| Timestamp | Result |",
        "| --- | --- |",
        f"| VehiclePosition.timestamp | {age_stats(vp_ages)} |",
        f"| TripUpdate.timestamp | {age_stats(tu_ages)} |",
        "",
        "90 s threshold: [GTFS Realtime Best Practices](https://gtfs.org/documentation/realtime/realtime-best-practices/). Age is measured at fetch time; negative values indicate clock differences.",
        "",
    ]
    lines += [
        "## Streams and sample completeness",
        "",
        "| Realtime source | Valid files | Empty | Header age |",
        "| --- | ---: | ---: | --- |",
    ]
    rt_urls = meta.get("rt_urls", [meta.get("rt_url", "legacy")])
    for stream, count in sorted(stream_counts.items()):
        label = (
            rt_urls[int(stream)]
            if stream.isdigit() and int(stream) < len(rt_urls)
            else stream
        )
        lines.append(
            f"| {label} | {count} | {stream_empty[stream]} | {age_stats(stream_ages.get(stream, []))} |"
        )
    if "rt_urls" in meta:
        for index, url in enumerate(rt_urls):
            if str(index) not in stream_counts:
                lines.append(f"| {url} | 0 | — | no valid snapshots |")
    error_path = source / "errors.jsonl"
    error_count = (
        len(error_path.read_text().splitlines()) if error_path.exists() else None
    )
    lines += [
        "",
        f"Fetch errors recorded in errors.jsonl: {error_count if error_count is not None else 'no error journal; check the collector log'}. Failed fetches are excluded from field presence denominators.",
    ]
    lines += [
        "",
        "The 90 s threshold applies to VP/TU; the GTFS recommendation for alerts is 10 minutes. Missing source files indicate missing data, not an empty feed.",
        f"Invalid protobuf: {c['invalid']}; DIFFERENTIAL snapshots: {c['differential']} (the report counts supplied records without reconstructing differential state).",
        "",
        "## History and suitability for the project",
        "",
        f"Changes in arrival.time between consecutive observations of the same trip/stop: {rate(c['arrival_revised'], c['arrival_repeated'])}. Revisions of a time that was already in the past in the previous snapshot: {rate(c['arrival_past_revised'], c['arrival_past_repeated'])}.",
        "",
        f"Fresh VP observations with advancing stop_sequence: {c['vp_sequence_advance']}; IN_TRANSIT_TO/INCOMING_AT → STOPPED_AT transitions for the same stop: {len(arrival_intervals)}.",
    ]
    if arrival_intervals:
        lines.append(
            f"Timestamp gap at these transitions: median {sorted(arrival_intervals)[len(arrival_intervals) // 2]} s; maximum {max(arrival_intervals)} s. These are candidate arrival windows based on vehicle states; GPS and provider semantics require validation."
        )
        lines.append(
            f"GPS at transition to STOPPED_AT available for {len(arrival_distances)}/{len(arrival_intervals)} candidates; distance from stop ≤50 m: {rate(sum(d <= 50 for d in arrival_distances), len(arrival_distances))}. The 50 m threshold is a provisional location consistency check, not confirmation of an exact arrival time."
        )
        if arrival_distances:
            lines.append(
                f"GPS distance from stop: median {sorted(arrival_distances)[len(arrival_distances) // 2]:.0f} m; maximum {max(arrival_distances):.0f} m."
            )
    if delays:
        lines += [
            "",
            f"Explicit arrival.delay: minimum {min(delays)} s, median {sorted(delays)[len(delays) // 2]} s, maximum {max(delays)} s. These are feed updates (including predictions), not a distribution of actual trip delays.",
        ]
    lines += [
        "",
        "VP transitions require ZIP-matched sequences and stop_id, explicit status and timestamp, age 0–90 s, and gap 0–90 s. History is separated by source, trip, vehicle (VP), and date; when start_date is absent, the local observation date is used only for grouping, not for computing scheduled times. Trips crossing midnight require separate validation.",
        "",
        "## Can actual arrivals be determined?",
        "",
    ]
    if c["arrival_time"] == 0:
        lines.append(
            "This GTFS-RT sample does not provide `arrival.time`. If `arrival.delay` is available, a time can be derived by matching the schedule and service date; this does not distinguish a prediction from a measurement. Actual arrivals may be estimated from vehicle position and state history, with uncertainty that requires validation."
        )
    else:
        lines.append(
            "`arrival.time` is present in the snapshots, but GTFS-RT may provide predictions even for past stops. The presence of the field and a past timestamp do not establish a confirmed actual arrival. This interpretation requires examining changes across snapshots and validating against observed trips."
        )
    lines += [
        "",
        "Missing `uncertainty` means unknown uncertainty under the [GTFS-RT specification](https://gtfs.org/documentation/realtime/reference/). Explicit CANCELED reports a cancellation; a trip disappearing from the feed does not establish cancellation. SKIPPED applies to a stop, and NO_SERVICE must be interpreted within the alert selector scope.",
    ]
    if duration < 2:
        lines += [
            "",
            f"**Sample limitation:** the window of {duration:.2f} h is shorter than the intended several hours / full day. Findings about rare events (cancellations, past updates) are preliminary; run the collector again with `--hours 4` or longer and regenerate the report.",
        ]
    if c["sequence_beyond_end"]:
        lines += [
            "",
            "The snapshots contain `stop_sequence` values beyond the final stop of the trip in the ZIP. Filter sequence changes against `stop_times.txt` before using them for arrival estimation.",
        ]
    lines += [
        "",
        "## Method",
        "",
        "Each `.pb` file is a separate snapshot downloaded from the full feed. Percentages describe observations, so the same vehicle may be counted repeatedly. A past update has `arrival.time` or `departure.time`, or a local `stop_times.txt` time for `start_date` plus the corresponding `delay`, earlier than the fetch time. When both events are available, arrival is analyzed. This classification does not confirm an actual arrival. No CANCELED updates in the sample does not prove that the feed never publishes cancellations.",
        "",
    ]
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.output}")


def check_descriptor(desc, trip_routes, routes, c, examples, unique):
    if desc.trip_id:
        c["trip_checked"] += 1
        unique["trip"].add(desc.trip_id)
        if desc.trip_id in trip_routes:
            c["trip_match"] += 1
        elif len(examples["trip"]) < 5:
            examples["trip"].add(desc.trip_id)
    if desc.route_id:
        c["route_checked"] += 1
        unique["route"].add(desc.route_id)
        if desc.route_id in routes and (
            not desc.trip_id
            or desc.trip_id not in trip_routes
            or trip_routes[desc.trip_id] == desc.route_id
        ):
            c["route_match"] += 1
        elif len(examples["route"]) < 5:
            examples["route"].add(desc.route_id)


def check_stop(stop_id, stops, c, examples, unique):
    c["stop_checked"] += 1
    unique["stop"].add(stop_id)
    if stop_id in stops:
        c["stop_match"] += 1
    elif len(examples["stop"]) < 5:
        examples["stop"].add(stop_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    collect_parser = sub.add_parser(
        "collect", help="Download GTFS ZIP and sample the realtime feed"
    )
    collect_parser.add_argument(
        "--network",
        choices=NETWORKS,
        default="T",
        help="Kraków: T trams, A MPK buses, M Mobilis",
    )
    collect_parser.add_argument("--gtfs-url")
    collect_parser.add_argument(
        "--rt-url",
        action="append",
        help="Repeat for each RT stream; custom ZIP requires custom RT URLs",
    )
    collect_parser.add_argument("--label")
    collect_parser.add_argument("--output", type=Path)
    collect_parser.add_argument(
        "--interval", type=float, default=30, help="Seconds between fetch starts"
    )
    collect_parser.add_argument(
        "--hours", type=float, default=4, help="Sampling duration"
    )
    collect_parser.add_argument("--once", action="store_true")
    collect_parser.add_argument("--refresh-zip", action="store_true")
    collect_parser.add_argument(
        "--report-after",
        action="store_true",
        help="Write data-profile.md inside the collection directory",
    )
    report_parser = sub.add_parser("report", help="Profile saved snapshots")
    report_parser.add_argument("--input", type=Path, required=True)
    report_parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "collect":
        if args.interval <= 0 or args.hours < 0:
            parser.error("--interval must be positive and --hours nonnegative")
        if bool(args.gtfs_url) != bool(args.rt_url):
            parser.error("Custom sources require both --gtfs-url and --rt-url")
        custom = bool(args.gtfs_url)
        args.gtfs_url = args.gtfs_url or f"{BASE_URL}/GTFS_KRK_{args.network}.zip"
        args.rt_url = args.rt_url or [
            f"{BASE_URL}/{kind}_{args.network}.pb"
            for kind in ("VehiclePositions", "TripUpdates", "ServiceAlerts")
        ]
        args.label = args.label or (
            "GTFS" if custom else f"Kraków ZTP — {NETWORKS[args.network]}"
        )
        args.output = (
            args.output
            or Path(__file__).parent
            / "data"
            / f"{'custom' if custom else 'krakow-' + args.network}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S.%fZ}"
        )
        collect(args)
    else:
        args.output = args.output or args.input / "data-profile.md"
        report(args)


if __name__ == "__main__":
    main()
