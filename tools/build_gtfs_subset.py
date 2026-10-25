"""Filter the national Israeli GTFS feed down to Inspectra's tracked bus routes (output: data/gtfs/).

Usage:  python tools/build_gtfs_subset.py path/to/israel-public-transportation.zip

Download the feed from https://www.gov.il/he/pages/gtfs (keep it out of git: `data/raw/` is ignored).
Map GeoJSON and the stop->route index are derived from these tables at runtime, so nothing else needs generating.
When the feed has a calendar.txt it is kept, and the app then only offers scheduled trips that run today.
"""
import argparse
import zipfile
from pathlib import Path

import pandas as pd

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "gtfs"

# Tracked route_ids (see routes.txt). Routes come in pairs: one id per direction.
TRACKED_ROUTE_IDS = [
    "39165", "39166", "27901", "27902", "27081", "27082", "27083", "27084", "34619", "34620",
    "36503", "36504", "25957", "25958", "25955", "25956", "24281", "24282", "23917", "23918",
    "22051", "22052", "21999", "22000", "21997", "21988", "21993", "21994", "21189", "21190",
    "21187", "21188", "13429", "13430", "11537", "11538", "10933", "10934", "10275", "10276",
]


def build(zip_path, output_dir=OUTPUT_DIR, route_ids=TRACKED_ROUTE_IDS):
    output_dir.mkdir(parents=True, exist_ok=True)

    def read(archive, name, **kwargs):
        with archive.open(name) as handle:
            return pd.read_csv(handle, **kwargs)

    with zipfile.ZipFile(zip_path) as archive:
        routes = read(archive, "routes.txt", dtype={"route_id": str})
        trips = read(archive, "trips.txt", dtype={"route_id": str})
        stop_times = read(archive, "stop_times.txt")
        stops = read(archive, "stops.txt")
        names = archive.namelist()
        shapes = read(archive, "shapes.txt") if "shapes.txt" in names else pd.DataFrame()
        calendar = read(archive, "calendar.txt") if "calendar.txt" in names else pd.DataFrame()

    routes["route_id"] = routes["route_id"].str.strip()
    trips["route_id"] = trips["route_id"].str.strip()

    routes = routes[routes["route_id"].isin(route_ids)]
    trips = trips[trips["route_id"].isin(routes["route_id"])]
    stop_times = stop_times[stop_times["trip_id"].isin(trips["trip_id"])]
    stops = stops[stops["stop_id"].isin(stop_times["stop_id"].unique())]
    if not shapes.empty:
        shapes = shapes[shapes["shape_id"].isin(trips["shape_id"].dropna().unique())]
    if not calendar.empty:
        calendar = calendar[calendar["service_id"].isin(trips["service_id"].unique())]

    tables = (("routes", routes), ("trips", trips), ("stop_times", stop_times), ("stops", stops),
              ("shapes", shapes), ("calendar", calendar))
    for name, table in tables:
        if table.empty and name in ("shapes", "calendar"):
            print(f"{name}.txt missing in the feed; skipped (shapes: no map lines, calendar: trips assumed to run every day)")
            continue
        table.to_csv(output_dir / f"{name}.txt", index=False)
        print(f"{name}.txt: {len(table)} rows")
    print(f"Filtered GTFS written to {output_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("gtfs_zip", type=Path, help="national GTFS zip (israel-public-transportation.zip)")
    build(parser.parse_args().gtfs_zip)
