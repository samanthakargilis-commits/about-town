"""The 16-day forecast (Open-Meteo, free, no key) for San Francisco and the
places you'd escape to when it's foggy: Marin, the Peninsula, the East Bay
and Sonoma. One request a day. The app uses it to lift events where the sun
is out on days SF is grey."""
from __future__ import annotations

import json

import requests

URL = "https://api.open-meteo.com/v1/forecast"
PLACES = {               # a town in the middle of each area
    "sf": (37.7599, -122.4600),          # Inner Sunset, where the fog sits
    "marin": (37.9060, -122.5450),       # Mill Valley
    "peninsula": (37.4419, -122.1430),   # Palo Alto
    "eastbay": (37.8044, -122.2712),     # Oakland
    "sonoma": (38.2919, -122.4580),      # Sonoma
}
DAILY = "weather_code,sunshine_duration,daylight_duration,temperature_2m_max,precipitation_probability_max"


def forecast(session=None) -> dict:
    s = session or requests
    names = list(PLACES)
    r = s.get(URL, timeout=30, params={
        "latitude": ",".join(str(PLACES[n][0]) for n in names),
        "longitude": ",".join(str(PLACES[n][1]) for n in names),
        "daily": DAILY, "timezone": "America/Los_Angeles", "forecast_days": 16,
        "temperature_unit": "fahrenheit",
    })
    r.raise_for_status()
    rows = r.json()
    rows = rows if isinstance(rows, list) else [rows]
    days: dict = {}
    for name, row in zip(names, rows):
        d = row["daily"]
        for i, day in enumerate(d["time"]):
            sun, light = d["sunshine_duration"][i], d["daylight_duration"][i]
            if sun is None or not light:
                continue
            days.setdefault(day, {})[name] = {
                "sun": round(sun / light, 2),            # share of daylight with sun
                "hi": round(d["temperature_2m_max"][i]) if d["temperature_2m_max"][i] is not None else None,
                "rain": d["precipitation_probability_max"][i],
                "code": d["weather_code"][i],
            }
    return {"source": "Open-Meteo", "days": days}


def write(path) -> str:
    """Write weather.json; a failed fetch leaves the app without the boost, nothing else."""
    try:
        data = forecast()
    except Exception as exc:
        return f"weather: unavailable ({type(exc).__name__}: {str(exc)[:120]})"
    with open(path, "w") as fh:
        json.dump(data, fh, indent=0)
    first = sorted(data["days"])
    return f"weather: {len(first)} days ({first[0]} to {first[-1]})" if first else "weather: no days"
