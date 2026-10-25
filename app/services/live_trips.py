"""Turns live SIRI visits near a location into options the routing engine can score.

A visit is matched to the static feed through the route it serves: SIRI's `line_ref` is the GTFS `route_id`
(with the public bus number as a fallback for ids that drifted between feed releases), narrowed by direction.
Fare-evasion data and ride-time estimates are per route, so no live trip_id is needed.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone

from app import config
from app.services.siri import (
    DESTINATION_UNKNOWN,
    fetch_live_stop_visits,
    parse_iso_datetime,
)
from app.utils.geo import haversine_meters
from app.utils.ids import normalize_id, normalize_line_ref, normalize_route_name

logger = logging.getLogger(__name__)


def _wanted_direction(direction_ref):
    """SIRI DirectionRef is 1/2; GTFS direction_id is 0/1."""
    ref = normalize_id(direction_ref)
    return str(int(ref) - 1) if ref in {"1", "2"} else None


def match_route_entry(stop_routes, stop_id, line_ref, line_name=None, direction_ref=None):
    """
    The `GtfsData.stop_routes` entry (a representative trip/shape of a route) a live visit refers to, or None.

    `line_ref` is matched against route_id first; the public bus number is only a fallback. A route_id hit whose
    bus number contradicts `line_name` is treated as a stale id. Anything still ambiguous (the same bus number on
    several routes with no direction to tell them apart) is rejected rather than guessed.
    """
    candidates = stop_routes.get(normalize_id(stop_id), [])
    line_ref = normalize_line_ref(line_ref)
    line_name = normalize_route_name(line_name)

    matches = []
    if line_ref is not None:
        matches = [
            e for e in candidates
            if e["route_id"] == line_ref and (line_name is None or normalize_route_name(e["route_short_name"]) in (None, line_name))
        ]
    if not matches and line_name is not None:
        matches = [e for e in candidates if normalize_route_name(e["route_short_name"]) == line_name]

    wanted = _wanted_direction(direction_ref)
    if wanted is not None:
        matches = [e for e in matches if e["direction_id"] in (None, wanted)]

    if len({(e["route_id"], e["shape_id"]) for e in matches}) != 1:
        if matches:
            logger.debug("Live visit at stop %s (line %s/%s) is ambiguous", stop_id, line_ref, line_name)
        return None
    return min(matches, key=lambda e: str(e["trip_id"]))


def _resolve_destination(visit, stop_names_by_code):
    """SIRI often sends only destination_ref (a stop_code); fall back to that stop's name, else None."""
    name = visit.get("destination_name")
    if name and name != DESTINATION_UNKNOWN:
        return name
    return stop_names_by_code.get(normalize_id(visit.get("destination_ref")))


def build_live_trip_option(visit, stop_id, gtfs):
    """A live option for one visit at a stop, or None if the visit can't be matched to the feed or has no ETA."""
    stop_id = normalize_id(stop_id)
    if not isinstance(visit, dict) or not stop_id:
        return None

    entry = match_route_entry(
        gtfs.stop_routes, stop_id, visit.get("line_ref"), visit.get("line_name"), visit.get("direction_ref")
    )
    if entry is None:
        return None

    arrival_dt = visit.get("arrival_dt") or parse_iso_datetime(visit.get("expected_arrival_time"))
    if arrival_dt is None:
        return None
    minutes_until_arrival = round((arrival_dt - datetime.now(timezone.utc)).total_seconds() / 60.0, 1)

    latitude, longitude = visit.get("latitude"), visit.get("longitude")
    return {
        "trip_id": entry["trip_id"],
        "route_id": entry["route_id"],
        "stop_id": stop_id,
        "arrival_time": visit.get("expected_arrival_time"),
        "minutes_until_arrival": minutes_until_arrival,
        "route_num": normalize_route_name(entry["route_short_name"]) or entry["route_id"],
        "destination": _resolve_destination(visit, gtfs.stop_names_by_code),
        "vehicle_ref": visit.get("vehicle_ref"),
        "vehicle_location": {"lat": float(latitude), "lon": float(longitude)} if latitude is not None and longitude is not None else None,
        "latitude": latitude,
        "longitude": longitude,
        "line_ref": normalize_line_ref(visit.get("line_ref")),
        "line_name": normalize_route_name(visit.get("line_name")),
        "direction_ref": visit.get("direction_ref"),
        "shape_feature": gtfs.shape_lookup.get(entry["shape_id"]),
        "stop_feature": gtfs.stop_lookup.get(stop_id),
        "shape_id": entry["shape_id"],
        "data_source": "live",
        "source_label": "Live SIRI data",
        "is_live": True,
        "live_status": "live",
    }


def stops_within_radius(lat, lon, stop_lookup, radius_m):
    """(stop_id, stop_code, distance_m) for stops inside the radius, nearest first. SIRI is queried by stop_code."""
    nearby = []
    for stop_id, feature in stop_lookup.items():
        props = feature.get("properties") or {}
        distance = haversine_meters(float(lat), float(lon), float(props["stop_lat"]), float(props["stop_lon"]))
        if distance > float(radius_m):
            continue
        stop_code = normalize_id(props.get("stop_code"))
        if stop_code is None:
            logger.warning("GTFS stop %s has no stop_code; cannot query SIRI for it", stop_id)
            continue
        nearby.append((str(stop_id), stop_code, distance))
    return sorted(nearby, key=lambda item: item[2])


def get_live_trip_options(lat, lon, gtfs, radius_m=666):
    """All valid upcoming live options near (lat, lon), soonest first. Stops are queried in parallel."""
    stops = stops_within_radius(lat, lon, gtfs.stop_lookup, radius_m)
    if not stops:
        logger.info("No GTFS stops within SIRI search radius %.1fm", float(radius_m))
        return []

    pool = ThreadPoolExecutor(max_workers=max(1, min(config.SIRI_MAX_PARALLEL_FETCHES, len(stops))))
    futures = [pool.submit(fetch_live_stop_visits, stop_code) for _stop_id, stop_code, _distance in stops]
    done, pending = wait(futures, timeout=config.SIRI_REQUEST_BUDGET_SECONDS)
    pool.shutdown(wait=False, cancel_futures=True)  # stragglers finish on their own and fill the cache
    if pending:
        logger.warning("SIRI: %s of %s stops did not answer within %.1fs; continuing without them",
                       len(pending), len(futures), config.SIRI_REQUEST_BUDGET_SECONDS)

    options, visits_received = [], 0
    for (stop_id, _stop_code, _distance), future in zip(stops, futures):
        visits = future.result() if future in done and future.exception() is None else []
        visits_received += len(visits)
        for visit in visits:
            option = build_live_trip_option(visit, stop_id, gtfs)
            if option is not None and option["minutes_until_arrival"] > 0:
                options.append(option)

    options.sort(key=lambda option: option["minutes_until_arrival"])
    logger.info("SIRI: %s nearby stops, %s visits, %s matched to GTFS and upcoming", len(stops), visits_received, len(options))
    return options
