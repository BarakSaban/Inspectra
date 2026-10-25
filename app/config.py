"""Single source of configuration: loads `.env` and exposes every environment-driven setting.

Settings are read once at import. Code that needs a setting reads it from this module at call time
(`config.SIRI_TIMEOUT_SECONDS`), which keeps it overridable in tests. See `.env.example` for the full list.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
GTFS_DIR = DATA_DIR / "gtfs"
FARE_EVASION_CSV = DATA_DIR / "routes_with_avgs.csv"
OSM_CACHE_DIR = ROOT / "cache"


def _load_env_file(path):
    """Populate os.environ from a KEY=VALUE file without overriding variables that are already set."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))


_load_env_file(ROOT / ".env")


def _env(name, default=None, legacy=None):
    """Read an environment variable, optionally falling back to a legacy name."""
    value = os.environ.get(name)
    if not value and legacy:
        value = os.environ.get(legacy)
    return value if value else default


def _env_flag(name, default):
    return os.environ.get(name, "1" if default else "0").strip().lower() in {"1", "true", "yes", "on"}


# ---------------- Web application ----------------
DEFAULT_SECRET = "inspectra_dev_secret_please_change"
DEFAULT_ADMIN_PASSWORD = "admin"

SECRET_KEY = _env("INSPECTRA_SECRET", DEFAULT_SECRET)
ADMIN_PASSWORD = _env("INSPECTRA_ADMIN_PW", DEFAULT_ADMIN_PASSWORD)
DB_PATH = Path(_env("INSPECTRA_DB_PATH", str(ROOT / "inspectra.db")))
# The UI is served by this app (same origin), so CORS is off unless origins are listed explicitly.
CORS_ORIGINS = [o.strip() for o in (_env("INSPECTRA_CORS_ORIGINS", "") or "").split(",") if o.strip()]
SEED_DEMO_DATA = _env_flag("INSPECTRA_SEED_DEMO", True)
# Browsers drop Secure cookies on plain-http hosts other than localhost; set to 0 for LAN http.
COOKIE_SECURE = _env_flag("INSPECTRA_COOKIE_SECURE", True)
# The Werkzeug debugger allows remote code execution, so debug mode is strictly opt-in.
DEBUG = _env_flag("INSPECTRA_DEBUG", False)
HOST = _env("INSPECTRA_HOST", "0.0.0.0")
PORT = int(_env("PORT", "5000"))
LOG_LEVEL = _env("INSPECTRA_LOG_LEVEL", "INFO").upper()
# After this many failed logins for one address + username, further attempts are refused for the lockout period.
LOGIN_MAX_FAILURES = int(_env("INSPECTRA_LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCKOUT_SECONDS = int(_env("INSPECTRA_LOGIN_LOCKOUT_SECONDS", "300"))
# Load GTFS and the routing engine in the background at startup so the first request is not slow.
WARM_UP = _env_flag("INSPECTRA_WARM_UP", True)


class Config:
    """Flask configuration (loaded with `app.config.from_object`)."""
    SECRET_KEY = SECRET_KEY
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH.as_posix()}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = COOKIE_SECURE
    # Application settings
    CORS_ORIGINS = CORS_ORIGINS
    BOOTSTRAP_DB = True  # create tables and the default admin on startup
    SEED_DEMO_DATA = SEED_DEMO_DATA
    ADMIN_PASSWORD = ADMIN_PASSWORD
    WARM_UP = WARM_UP


# ---------------- Live data (SIRI stop-monitoring proxy) ----------------
SIRI_BASE_URL = _env(
    "INSPECTRA_SIRI_BASE_URL", "https://raspberry-phy.taila18e05.ts.net", legacy="SIRI_BASE_URL"
).rstrip("/")
# Requests run inside a web request, so a dead proxy must fail fast.
SIRI_TIMEOUT_SECONDS = float(_env("INSPECTRA_SIRI_TIMEOUT_SECONDS", "8", legacy="SIRI_TIMEOUT_SECONDS"))
SIRI_RETRY_DELAY_SECONDS = float(_env("INSPECTRA_SIRI_RETRY_DELAY_SECONDS", "0.5", legacy="SIRI_RETRY_DELAY_SECONDS"))
SIRI_CACHE_TTL_SECONDS = int(_env("INSPECTRA_SIRI_CACHE_TTL_SECONDS", "60"))
# After a failed fetch a stop is not retried for this long, so a down proxy can't stall every request.
SIRI_FAILURE_BACKOFF_SECONDS = int(_env("INSPECTRA_SIRI_FAILURE_BACKOFF_SECONDS", "15"))
SIRI_MAX_PARALLEL_FETCHES = int(_env("INSPECTRA_SIRI_MAX_PARALLEL_FETCHES", "8"))
# Total time one recommendation waits for SIRI; slower stops finish in the background and warm the cache.
SIRI_REQUEST_BUDGET_SECONDS = float(_env("INSPECTRA_SIRI_REQUEST_BUDGET_SECONDS", "5"))
