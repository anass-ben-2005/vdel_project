import time
import requests

MAX_ATTEMPTS = 3


def fetch_weather(url: str, params: dict) -> dict:
    """Fetch current weather, retrying on transient failure."""
    # @gap:id=g_ext_retry concepts=[py.errors_debugging,py.data_structures] difficulty=0.35
    # @instruct: Loop over attempt numbers from 1 to MAX_ATTEMPTS inclusive. Each
    #            attempt: issue a GET request with params and a 10-second timeout,
    #            raise on a bad HTTP status, and return the JSON body on success.
    #            On the final attempt, let the exception propagate instead of retrying.
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            if attempt == MAX_ATTEMPTS:
                raise
            time.sleep(2 ** attempt)
    # @endgap


def parse_response(raw: dict) -> dict:
    """Extract the fields the pipeline actually needs, defensively."""
    # @gap:id=g_ext_parse concepts=[py.data_structures] difficulty=0.35
    # @instruct: Safely extract 'temp', 'humidity', 'wind_speed' from raw['current'].
    #            Missing keys must produce None, not a KeyError.
    current = raw.get("current", {})
    return {
        "temp": current.get("temp"),
        "humidity": current.get("humidity"),
        "wind_speed": current.get("wind_speed"),
    }
    # @endgap