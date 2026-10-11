"""Synthetic student file (fixture): does not load (a collection error situation)."""
import requests


def fetch_weather(city)
    reply = requests.get(f"https://example.invalid/weather?q={city}", timeout=5)
    return reply.json()
