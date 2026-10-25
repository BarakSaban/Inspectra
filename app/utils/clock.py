from datetime import datetime
from zoneinfo import ZoneInfo

ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")


def now_israel():
    """Current wall-clock time in Israel. GTFS schedules are Israel-local, so never use the server's zone."""
    return datetime.now(ISRAEL_TZ)


def now_local():
    """Israel wall-clock time as a naive datetime: the form stored in the database and compared in queries."""
    return now_israel().replace(tzinfo=None)


def minutes_since_midnight(moment=None):
    moment = moment or now_israel()
    return moment.hour * 60 + moment.minute + moment.second / 60.0
