from dataclasses import dataclass
from typing import Optional


@dataclass
class StopVisit:
    monitoring_ref: str        # the stop this visit was fetched for
    line_ref: Optional[str]
    direction_ref: Optional[str]
    vehicle_ref: Optional[str]
    aimed_arrival: Optional[str]
    expected_arrival: Optional[str]