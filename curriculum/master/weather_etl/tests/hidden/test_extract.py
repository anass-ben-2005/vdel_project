import pytest
import requests
from weather_etl.extract import fetch_weather, parse_response


def test_fetch_weather_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return {"current": {"temp": 20}}

    def fake_get(*a, **kw):
        calls["n"] += 1
        if calls["n"] < 2:
            raise requests.ConnectionError()
        return FakeResp()

    monkeypatch.setattr(requests, "get", fake_get)
    result = fetch_weather("http://x", {})
    assert result == {"current": {"temp": 20}}
    assert calls["n"] == 2


def test_fetch_weather_raises_after_max_attempts(monkeypatch):
    def always_fail(*a, **kw):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "get", always_fail)
    with pytest.raises(requests.ConnectionError):
        fetch_weather("http://x", {})


def test_parse_response_missing_key_returns_none():
    result = parse_response({"current": {"temp": 20}})
    assert result["temp"] == 20
    assert result["humidity"] is None
    assert result["wind_speed"] is None


def test_parse_response_missing_current_key_entirely():
    result = parse_response({})
    assert result == {"temp": None, "humidity": None, "wind_speed": None}