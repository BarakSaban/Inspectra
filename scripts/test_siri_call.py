"""
Run from a machine whose outbound IP matches the whitelisted IP (79.177.157.200).
"""
import sys
from realtime.siri_client import fetch_stop_monitoring_xml, parse_stop_visits

if __name__ == "__main__":
    stop_id = sys.argv[1] if len(sys.argv) > 1 else "32902"
    print(f"Querying stop {stop_id} against test environment...")
    xml = fetch_stop_monitoring_xml(stop_id, use_test_env=True)
    print(xml.decode("utf-8", errors="replace")[:2000])
    print("\n--- Parsed ---")
    for v in parse_stop_visits(stop_id, xml):
        print(v)