import os
from dotenv import load_dotenv

load_dotenv()

SIRI_BASE_URL = os.environ["SIRI_BASE_URL"]
SIRI_TEST_BASE_URL = os.environ["SIRI_TEST_BASE_URL"]
SIRI_DEV_KEY = os.environ["SIRI_DEV_KEY"]