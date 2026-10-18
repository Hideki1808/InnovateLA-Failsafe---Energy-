"""
weather.py - the outdoor weather for the selected country and month.

It builds a TYPICAL DAY for that month: for each hour of the day (0-23), the average
temperature, humidity and wind across all the days of that month.

Where the numbers come from (it never goes online):
  1. Real: the saved Open-Meteo file, data/weather_<country>.json (made by fetch_data.py).
  2. Simulated: if that file is missing, broken or has no data for the month, the
     approximate monthly values in config/countries.toml ([countries.<id>.typical_weather]).
Either way the app keeps running.

    day = weather.typical_day("us_texas", 8)
    day["temp_c"][15]   -> average temperature at 3 pm in August
    day["source"]       -> "real" or "simulated"
"""

import json
import math
from pathlib import Path

import simulator

DATA_DIR = Path(__file__).parent / "data"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def typical_day(country_id, month):
    """A typical day for this country and month (1-12). Real data if saved, else simulated."""
    return _from_saved_file(country_id, month) or _from_config(country_id, month)


def _from_saved_file(country_id, month):
    """Average each hour of the day over the month, from the saved Open-Meteo file.
    Returns None (so we fall back) if the file is missing, broken or incomplete."""
    path = DATA_DIR / f"weather_{country_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        hourly = data["hourly"]
        rows = zip(hourly["time"], hourly["temperature_2m"],
                   hourly["relative_humidity_2m"], hourly["wind_speed_10m"])
        buckets = [[] for _ in range(24)]               # one list per hour of the day
        for time, temp, humidity, wind in rows:          # time looks like "2025-08-01T15:00"
            if int(time[5:7]) == month and None not in (temp, humidity, wind):
                buckets[int(time[11:13])].append((temp, humidity, wind))
        if any(not hour for hour in buckets):            # an hour with no data: don't trust it
            return None
        year = data.get("year", "")
        return {
            "temp_c": [sum(r[0] for r in hour) / len(hour) for hour in buckets],
            "humidity_pct": [sum(r[1] for r in hour) / len(hour) for hour in buckets],
            "wind_kmh": [sum(r[2] for r in hour) / len(hour) for hour in buckets],
            "source": "real",
            "label": f"Weather: real (typical {MONTHS[month - 1]} day, {year} data)",
            "credit": "Weather: Open-Meteo",
        }
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None                                      # missing or broken: fall back


def _from_config(country_id, month):
    """A smooth typical day from the approximate monthly values in the config:
    coolest around 3 am, warmest around 3 pm."""
    i = month - 1
    try:
        typical = simulator.COUNTRIES[country_id]["typical_weather"]
        low, high = typical["temp_low_c"][i], typical["temp_high_c"][i]
        humidity, wind = typical["humidity_pct"][i], typical["wind_kmh"][i]
    except (KeyError, IndexError, TypeError):
        low, high, humidity, wind = 15, 25, 60, 12        # last resort, so nothing ever crashes
    warmth = [(1 + math.cos(2 * math.pi * (h - 15) / 24)) / 2 for h in range(24)]  # 0 at 3 am, 1 at 3 pm
    return {
        "temp_c": [low + (high - low) * w for w in warmth],
        "humidity_pct": [humidity + 8 * (0.5 - w) for w in warmth],   # a bit drier when warm
        "wind_kmh": [wind] * 24,
        "source": "simulated",
        "label": f"Weather: simulated (approximate typical {MONTHS[month - 1]} values)",
        "credit": None,
    }


def at(day, hour):
    """A value for any time of day, e.g. hour=14.25 for 2:15 pm, blending neighbouring hours."""
    h0 = int(hour) % 24
    h1 = (h0 + 1) % 24
    share = hour - int(hour)
    return {key: day[key][h0] * (1 - share) + day[key][h1] * share
            for key in ("temp_c", "humidity_pct", "wind_kmh")}
