"""Compare (and optionally refresh) the passenger averages in data/routes_with_avgs.csv with data.gov.il.

Usage:  python tools/refresh_fare_evasion.py            # dry run: report differences, change nothing
        python tools/refresh_fare_evasion.py --write    # overwrite the API-backed slots in the CSV

Note: the committed table was not produced by this exact query (the API returns one record per direction and
quarter and this tool takes the first), so expect differences and review them before using --write.

`WorkDay - <slot>` is the average boardings per trip; `DontPay - <slot>` is the share assumed to be fare evaders
(20%, rounded). The open-data API only publishes the three slots in REFRESHED_SLOTS with the same time ranges the
app uses; the remaining slots of the table are maintained by hand and are left untouched by this tool, as is any
route the API has no data for. Rows are keyed by `NesoaRouteID` (the number before the first dash of route_desc).
"""
import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ROUTES_TXT = ROOT / "data" / "gtfs" / "routes.txt"
OUTPUT_CSV = ROOT / "data" / "routes_with_avgs.csv"

API_URL = "https://data.gov.il/api/3/action/datastore_search"
RESOURCE_ID = "e6cfac2f-979a-44fd-b439-ecb116ec0b16"
REFRESHED_SLOTS = ("06:00-08:59", "09:00-11:59", "12:00-14:59")
DONT_PAY_SHARE = 0.2


def fetch_workday_averages(nesoa_id):
    """{slot: average} from the first API record of a route, or None when the API has nothing for it."""
    query = urllib.parse.urlencode({"resource_id": RESOURCE_ID, "filters": json.dumps({"RouteID": nesoa_id})})
    with urllib.request.urlopen(f"{API_URL}?{query}", timeout=30) as response:
        records = json.load(response).get("result", {}).get("records", [])
    if not records:
        return None
    return {slot: records[0].get(f"WorkDay - {slot}") or 0 for slot in REFRESHED_SLOTS}


def refresh(routes, existing=None):
    """
    `routes` plus NesoaRouteID and WorkDay/DontPay columns. Slot columns already present in `existing` are carried
    over (matched on route_id) and only the REFRESHED_SLOTS values the API returns are overwritten.
    """
    table = routes.copy()
    table["NesoaRouteID"] = table["route_desc"].astype(str).str.split("-").str[0].str.strip()
    if existing is not None:
        slot_columns = [c for c in existing.columns if c.startswith(("WorkDay - ", "DontPay - "))]
        table = table.merge(existing[["route_id", *slot_columns]], on="route_id", how="left")

    for index, nesoa_id in table["NesoaRouteID"].items():
        try:
            averages = fetch_workday_averages(nesoa_id)
        except Exception as exc:
            print(f"route {nesoa_id}: API error ({exc}); keeping existing values")
            continue
        if averages is None:
            print(f"route {nesoa_id}: no API data; keeping existing values")
            continue
        for slot, value in averages.items():
            table.loc[index, f"WorkDay - {slot}"] = value
            table.loc[index, f"DontPay - {slot}"] = round(value * DONT_PAY_SHARE)
    return table


def _differences(before, after):
    """Count of changed cells per column between two tables with identical columns."""
    changed = {}
    for column in before.columns:
        old, new = before[column].reset_index(drop=True).astype(str), after[column].reset_index(drop=True).astype(str)
        if (old != new).any():
            changed[column] = int((old != new).sum())
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="save the refreshed table (default: dry run)")
    args = parser.parse_args()

    existing_table = pd.read_csv(OUTPUT_CSV) if OUTPUT_CSV.exists() else None
    result = refresh(pd.read_csv(ROUTES_TXT), existing_table)
    if existing_table is not None and list(result.columns) == list(existing_table.columns):
        print("Cells that differ from the current CSV, per column:", _differences(existing_table, result) or "none")
    if args.write:
        result.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        print(f"Saved {len(result)} routes to {OUTPUT_CSV}")
    else:
        print("Dry run: nothing written (use --write to save).")
