"""Synthetic student file (fixture): a single attempt, no retry, brittle parsing."""
import requests


def fetch_weather(city):
    reply = requests.get(f"https://example.invalid/weather?q={city}", timeout=5)
    return reply.json()


def parse_response(payload):
    return {"temperature": payload["current"]["temp_c"], "humidity": payload["current"]["humidity"]}
