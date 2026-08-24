from datetime import datetime, timezone


def clean_readings(records: list[dict]) -> list[dict]:
    """Drop readings missing a critical field (temp)."""
    # @gap:id=g_tf_clean concepts=[py.data_structures] difficulty=0.3
    # @instruct: Return only records where record.get("temp") is not None.
    return [r for r in records if r.get("temp") is not None]
    # @endgap


def to_fahrenheit(celsius: float) -> float:
    """Convert Celsius to Fahrenheit."""
    # @gap:id=g_tf_convert concepts=[py.data_structures] difficulty=0.2
    # @instruct: Apply the standard C-to-F formula.
    return celsius * 9 / 5 + 32
    # @endgap


def enrich_with_timestamp(record: dict, raw_ts: str | None) -> dict:
    """Attach an ISO timestamp; fall back to now() if raw_ts is missing or malformed."""
    # @gap:id=g_tf_timestamp concepts=[py.errors_debugging] difficulty=0.3
    # @instruct: Try to parse raw_ts as ISO format. If it is None or unparsable,
    #            use the current UTC time instead. Never let this raise.
    try:
        ts = datetime.fromisoformat(raw_ts) if raw_ts else datetime.now(timezone.utc)
    except ValueError:
        ts = datetime.now(timezone.utc)
    record["timestamp"] = ts.isoformat()
    return record
    # @endgap