"""Run with: python -m unittest discover -s tests -t ."""
import logging

# Expected warnings (offline fallbacks, simulated outages) would otherwise flood the test output.
logging.getLogger("app").setLevel(logging.CRITICAL)
