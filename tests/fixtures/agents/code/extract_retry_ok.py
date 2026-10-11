"""Synthetic student file (fixture): fetch with a bounded retry loop."""
import time

import requests

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 0.5


def fetch_weather(city):
    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            reply = requests.get(f"https://example.invalid/weather?q={city}", timeout=5)
            reply.raise_for_status()
            return reply.json()
        except requests.exceptions.ConnectionError as error:
            last_error = error
            time.sleep(BACKOFF_SECONDS * (attempt + 1))
    raise last_error


def parse_response(payload):
    current = payload.get("current")
    if current is None:
        return None
    return {"temperature": current.get("temp_c"), "humidity": current.get("humidity")}
