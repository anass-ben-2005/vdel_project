"""Synthetic student file (fixture): a retry loop with no exit (a timeout situation).

Agents never execute this file (invariant 12); it is only ever read as text.
"""
import requests


def fetch_weather(city):
    while True:
        try:
            reply = requests.get(f"https://example.invalid/weather?q={city}", timeout=5)
            return reply.json()
        except requests.exceptions.ConnectionError:
            continue
