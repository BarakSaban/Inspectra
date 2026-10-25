"""Diagnostic: call the SIRI proxy for the stops nearest a point and print the raw first visit of each.

Usage:  python tools/probe_siri.py [lat lon]       (default: Tel Aviv, 32.0880 34.7898)

Uses the proxy URL from the app configuration (INSPECTRA_SIRI_BASE_URL / .env) and never prints secrets.
Run from the repository root so `app` is importable.
"""
import json
import os
import sys
from pathlib import Path
from urllib import error, request

import pandas as pd

from app import config

ROOT = Path(__file__).resolve().parents[1]


def _redact(text):
    key = os.environ.get("SIRI_DEV_KEY")
    return text.replace(key, "***REDACTED***") if key else text


def _nearest_stop_codes(lat, lon, count=3):
    stops = pd.read_csv(ROOT / "data" / "gtfs" / "stops.txt")
    distance = ((stops["stop_lat"] - lat) ** 2 + ((stops["stop_lon"] - lon) * 0.85) ** 2) ** 0.5
    nearest = stops.loc[distance.nsmallest(count).index]
    return list(zip(nearest["stop_id"], nearest["stop_code"]))


def main():
    base_url = config.SIRI_BASE_URL
    lat, lon = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) >= 3 else (32.0880, 34.7898)

    for stop_id, stop_code in _nearest_stop_codes(lat, lon):
        url = f"{base_url.rstrip('/')}/stops/{stop_code}"
        print(f"--- stop_id={stop_id} stop_code={stop_code}")
        try:
            with request.urlopen(url, timeout=15) as response:
                status = response.status
                payload = json.loads(response.read().decode("utf-8") or "{}")
        except error.HTTPError as exc:
            print(f"status={exc.code}")
            continue
        except Exception as exc:
            print(_redact(f"unreachable: {exc!r}"))
            continue
        visits = payload.get("visits") or []
        print(f"status={status} visits={len(visits)}")
        if visits:
            print(_redact(json.dumps(visits[0], ensure_ascii=False, indent=2)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
