"""Mock weather API. Deterministic: conditions derive from hash(city, seed)."""

import hashlib
from typing import Any

_CONDITIONS = ["clear", "partly cloudy", "overcast", "light rain", "thunderstorms", "snow"]


def run_weather(args: dict[str, Any], seed: int) -> dict[str, Any]:
    city = str(args.get("city", "")).strip()
    if not city:
        raise ValueError("city is required")

    digest = hashlib.sha256(f"{city.lower()}::{seed}".encode()).digest()
    temp_c = round(-5 + (digest[0] / 255) * 40, 1)          # -5..35 °C
    humidity = 30 + digest[1] % 61                           # 30..90 %
    wind_kph = round((digest[2] / 255) * 45, 1)              # 0..45 kph
    condition = _CONDITIONS[digest[3] % len(_CONDITIONS)]

    return {
        "city": city,
        "temperature_c": temp_c,
        "condition": condition,
        "humidity_pct": humidity,
        "wind_kph": wind_kph,
        "source": "mock-weather-api",
    }
