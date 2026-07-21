"""
Client for Israel MOT's SIRI-SM (Stop Monitoring) real-time data service.
ICD: https://www.gov.il/he/departments/general/real_time_information_siri
"""
import time
import requests
from lxml import etree
from config import SIRI_BASE_URL, SIRI_TEST_BASE_URL, SIRI_DEV_KEY
from realtime.models import StopVisit


class SiriClientError(Exception):
    pass


def fetch_stop_monitoring_xml(
    monitoring_ref: str,
    use_test_env: bool = False,
    timeout: int = 10,
    max_retries: int = 3,
    backoff_seconds: float = 1.0,
) -> bytes:
    """
    Calls SIRI-SM for a given stop (MonitoringRef), returns raw XML bytes.
    Retries transient failures (timeouts, connection errors, 5xx) with
    exponential backoff. Does not retry 4xx errors — those indicate a bad
    request (wrong key, bad stop ref) that won't fix itself.
    """
    base_url = SIRI_TEST_BASE_URL if use_test_env else SIRI_BASE_URL
    url = f"{base_url}/xml"
    params = {"Key": SIRI_DEV_KEY, "MonitoringRef": monitoring_ref}

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)

            if 400 <= resp.status_code < 500:
                raise SiriClientError(
                    f"SIRI request rejected for stop {monitoring_ref}: "
                    f"{resp.status_code} {resp.text[:200]}"
                )

            resp.raise_for_status()
            return resp.content

        except SiriClientError:
            raise  # don't retry client errors

        except requests.RequestException as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(backoff_seconds * (2 ** (attempt - 1)))
                continue

    raise SiriClientError(
        f"SIRI request failed for stop {monitoring_ref} after {max_retries} attempts: {last_error}"
    )


def parse_stop_visits(monitoring_ref: str, xml_bytes: bytes) -> list[StopVisit]:
    """
    Parses SIRI-SM XML into StopVisit records.
    NOTE: tag names follow the standard SIRI-SM schema
    (MonitoredStopVisit / MonitoredVehicleJourney / MonitoredCall) but are
    unconfirmed against a real response — verify once we see live output.
    """
    root = etree.fromstring(xml_bytes)
    ns_uri = root.nsmap.get(None, "http://www.siri.org.uk/siri")
    ns = {"siri": ns_uri}

    visits = []
    for visit in root.iter(f"{{{ns_uri}}}MonitoredStopVisit"):
        journey = visit.find(".//siri:MonitoredVehicleJourney", namespaces=ns)
        if journey is None:
            continue

        def text(tag):
            el = journey.find(f"siri:{tag}", namespaces=ns)
            return el.text if el is not None else None

        call = journey.find("siri:MonitoredCall", namespaces=ns)
        expected = call.find("siri:ExpectedArrivalTime", namespaces=ns) if call is not None else None
        aimed = call.find("siri:AimedArrivalTime", namespaces=ns) if call is not None else None

        visits.append(StopVisit(
            monitoring_ref=monitoring_ref,
            line_ref=text("LineRef"),
            direction_ref=text("DirectionRef"),
            vehicle_ref=text("VehicleRef"),
            aimed_arrival=aimed.text if aimed is not None else None,
            expected_arrival=expected.text if expected is not None else None,
        ))

    return visits


def get_upcoming_vehicles(monitoring_ref: str, use_test_env: bool = False) -> list[StopVisit]:
    xml_bytes = fetch_stop_monitoring_xml(monitoring_ref, use_test_env=use_test_env)
    return parse_stop_visits(monitoring_ref, xml_bytes)