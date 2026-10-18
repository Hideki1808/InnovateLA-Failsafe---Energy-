"""
crisis.py - what can go wrong, how likely it is in a given month, and how bad it gets.

Six crisis types:
    heat_wave, cold_snap, windstorm (downed lines), earthquake, wildfire, conflict (grid attack)

For each type and each country/month it works out:
  - a CHANCE: how likely this kind of crisis is to hit at least once during that month
    (0 = never, 1 = certainly), from the saved real data where we have it;
  - whether it's FORECASTABLE: heat, cold and wind come with a warning period
    ("Forecast: heat wave in 18h"); earthquakes, wildfires and attacks hit with no warning;
  - a SEVERITY from 1 (minor) to 5 (extreme).

Where the numbers come from (it never goes online; see CLAUDE.md data rules):
  - Heat wave, cold snap, windstorm, wildfire: the saved hourly weather,
    data/weather_<country>.json. If it's missing, the approximate monthly values in
    config/countries.toml ([typical_weather]).
  - Earthquake: the saved USGS history, data/earthquakes_<country>.json. If it's missing,
    [crisis] earthquakes_per_year_if_no_data in the config.
  - Conflict: a small fixed chance, [crisis] conflict_chance_per_month in the config.

Use it like this:
    crisis.monthly_chances("us_texas", 8)              -> chance of each type in August
    crisis.pick_random("us_texas", 8, seed=1)          -> a random crisis for August
    crisis.make_crisis("de_munich", 1, "cold_snap", 4) -> a manual pick
    crisis.forecast_label(c, hour=6)                   -> "Forecast: heat wave in 8h"
"""

import json
import math
import random
from functools import lru_cache
from pathlib import Path

import simulator

DATA_DIR = Path(__file__).parent / "data"

# ---------------------------------------------------------------------------
# The crisis types
# ---------------------------------------------------------------------------
# forecastable: does a warning come first?  warning_hours: how long before it hits (range).
# start_hour / hours: when it usually starts on the day and how long it lasts (None = any hour).
TYPES = {
    "heat_wave":  {"name": "Heat wave",  "forecastable": True,  "warning_hours": (18, 48),
                   "start_hour": 14, "hours": 6,
                   "what": "Air conditioning everywhere: demand climbs, lines run hot."},
    "cold_snap":  {"name": "Cold snap",  "forecastable": True,  "warning_hours": (18, 48),
                   "start_hour": 16, "hours": 6,
                   "what": "Heating everywhere: demand climbs, especially in the evening."},
    "windstorm":  {"name": "Windstorm",  "forecastable": True,  "warning_hours": (6, 24),
                   "start_hour": 15, "hours": 4,
                   "what": "Strong gusts bring down trees and power lines; zones can go dark."},
    "earthquake": {"name": "Earthquake", "forecastable": False, "warning_hours": None,
                   "start_hour": None, "hours": 1,
                   "what": "Sudden shaking can trip substations and damage lines."},
    "wildfire":   {"name": "Wildfire",   "forecastable": False, "warning_hours": None,
                   "start_hour": 13, "hours": 8,
                   "what": "Fire near lines; power may be shut off in exposed zones."},
    "conflict":   {"name": "Grid attack", "forecastable": False, "warning_hours": None,
                   "start_hour": None, "hours": 4,
                   "what": "Physical or cyber attack on grid equipment; zones can go dark."},
}

SEVERITY_NAMES = {1: "Minor", 2: "Moderate", 3: "Serious", 4: "Severe", 5: "Extreme"}

MAX_CHANCE = 0.9    # no crisis is ever "certain" in a month


# ---------------------------------------------------------------------------
# Reading the saved data (never crashes: returns None if missing or broken)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=8)
def _weather_hours(path_text):
    """All saved hours as (month, temperature °C, humidity %, wind km/h), or None."""
    try:
        h = json.loads(Path(path_text).read_text(encoding="utf-8"))["hourly"]
        rows = [(int(t[5:7]), temp, hum, wind)
                for t, temp, hum, wind in zip(h["time"], h["temperature_2m"],
                                              h["relative_humidity_2m"], h["wind_speed_10m"])
                if None not in (temp, hum, wind)]
        return rows if len(rows) > 24 * 300 else None      # want most of the year
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None


@lru_cache(maxsize=8)
def _earthquakes(path_text):
    """The saved earthquake history (count, years covered, magnitudes), or None."""
    try:
        q = json.loads(Path(path_text).read_text(encoding="utf-8"))
        years = int(q["to"][:4]) - int(q["from"][:4])
        mags = [e["magnitude"] for e in q["earthquakes"] if e.get("magnitude")]
        return {"count": int(q["count"]), "years": max(years, 1), "magnitudes": mags}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _percentile(values, p):
    """The value below which p% of the values fall (e.g. p=90 -> the hottest 10% start here)."""
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p / 100))]


def _clamp(x, low=0.0, high=MAX_CHANCE):
    return max(low, min(high, x))


# ---------------------------------------------------------------------------
# Likelihood of each type, for one country and month
# ---------------------------------------------------------------------------
def monthly_chances(country_id, month):
    """
    For each crisis type: {"chance": 0..0.9, "intensity": 0..1, "basis": plain text,
    "source": "real" or "simulated"}. "intensity" says how extreme this month is for that
    type (used to set severity).
    """
    country = simulator.COUNTRIES[country_id]
    hours = _weather_hours(str(DATA_DIR / f"weather_{country_id}.json"))
    out = {}
    if hours:
        out.update(_weather_crises_from_data(hours, month))
    else:
        out.update(_weather_crises_from_config(country, month))
    out["wildfire"] = _wildfire(country_id, month)
    out["earthquake"] = _earthquake(country_id, country)
    chance = float(country.get("crisis", {}).get("conflict_chance_per_month", 0.01))
    # CONFLICT: a small fixed chance from the config, the same in every month and place.
    out["conflict"] = {"chance": chance, "intensity": 0.5, "source": "simulated",
                       "basis": f"fixed {chance:.0%} a month (config)"}
    return out


def _weather_crises_from_data(hours, month):
    """Heat wave, cold snap and windstorm chances from the saved real weather."""
    temps = [r[1] for r in hours]
    winds = [r[3] for r in hours]
    # The year's thresholds: the hottest 10% of hours, the coldest 10%, the windiest 5%.
    # (We compare each month with the YEAR, not with itself: every month has 10% of its
    # own hours above its own 90th percentile, so that would rate every month the same.)
    hot_line = _percentile(temps, 90)
    cold_line = _percentile(temps, 10)
    windy_line = _percentile(winds, 95)
    this_month = [r for r in hours if r[0] == month]
    n = len(this_month) or 1
    hot_share = sum(r[1] >= hot_line for r in this_month) / n      # share of the month's hours that are "hot"
    cold_share = sum(r[1] <= cold_line for r in this_month) / n
    windy_share = sum(r[3] >= windy_line for r in this_month) / n
    # The saved data has average wind, not gusts. Gusts are typically ~1.5x the average.
    peak_gust = 1.5 * max((r[3] for r in this_month), default=0)

    return {
        # HEAT WAVE: chance = 2 x the share of the month's hours in the year's hottest 10%.
        # A month where 40% of hours are "year-hot" (Texas August) -> 0.8, capped at 0.9;
        # a month with none -> 0.
        "heat_wave": {"chance": _clamp(2 * hot_share), "intensity": _clamp(hot_share / 0.5, 0, 1),
                      "source": "real",
                      "basis": f"{hot_share:.0%} of hours above the year's hottest-10% line ({hot_line:.0f} °C)"},
        # COLD SNAP: the same idea with the year's coldest 10% of hours.
        "cold_snap": {"chance": _clamp(2 * cold_share), "intensity": _clamp(cold_share / 0.5, 0, 1),
                      "source": "real",
                      "basis": f"{cold_share:.0%} of hours below the year's coldest-10% line ({cold_line:.0f} °C)"},
        # WINDSTORM: chance = 4 x the share of hours in the year's windiest 5% (rarer, so a
        # bigger multiplier), plus a bump when estimated gusts reach storm level (60+ km/h).
        "windstorm": {"chance": _clamp(4 * windy_share + (0.1 if peak_gust >= 60 else 0), high=0.6),
                      "intensity": _clamp(windy_share / 0.15 + max(0, peak_gust - 40) / 60, 0, 1),
                      "source": "real",
                      "basis": f"{windy_share:.0%} of hours in the year's windiest 5%, "
                               f"gusts up to about {peak_gust:.0f} km/h"},
    }


def _weather_crises_from_config(country, month):
    """Fallback when the weather file is missing: use the approximate monthly normals."""
    t = country["typical_weather"]
    highs, lows, winds = t["temp_high_c"], t["temp_low_c"], t["wind_kmh"]
    i = month - 1

    def rank(values, value, higher=True):
        """0..1: where this month sits between the year's mildest and most extreme month."""
        lo, hi = min(values), max(values)
        x = (value - lo) / (hi - lo) if hi > lo else 0
        return x if higher else 1 - x

    # Same shape as with real data: only the most extreme months get a real chance
    # (squaring the rank keeps middle months low).
    hot, cold, windy = rank(highs, highs[i]), rank(lows, lows[i], higher=False), rank(winds, winds[i])
    basis = "approximate monthly normals (config), no saved weather"
    return {
        "heat_wave": {"chance": _clamp(0.8 * hot ** 2), "intensity": hot, "source": "simulated", "basis": basis},
        "cold_snap": {"chance": _clamp(0.8 * cold ** 2), "intensity": cold, "source": "simulated", "basis": basis},
        "windstorm": {"chance": _clamp(0.4 * windy ** 2, high=0.6), "intensity": windy,
                      "source": "simulated", "basis": basis},
    }


def wildfire_risk_index(country_id, month):
    """
    A 0-100 wildfire risk index for the month. FIRST VERSION: step 5 replaces this with
    the full wildfire risk index; anything that needs the index should call this function.

    Every hour gets a "fire weather" score = heat x dryness x wind:
        heat    = how far the temperature is from 10 °C toward 40 °C   (0 to 1)
        dryness = 1 - humidity                                        (0 to 1)
        wind    = 0.3 calm ... 1.0 at 40 km/h or more                 (wind spreads fire)
    The index is the average of each day's worst hour, times 100. Hot, dry, windy months
    score high; cold or humid ones near 0.
    """
    def score(temp, humidity, wind):
        heat = _clamp((temp - 10) / 30, 0, 1)
        dryness = 1 - humidity / 100
        windy = 0.3 + 0.7 * _clamp(wind / 40, 0, 1)
        return heat * dryness * windy

    hours = _weather_hours(str(DATA_DIR / f"weather_{country_id}.json"))
    if hours:
        this_month = [score(r[1], r[2], r[3]) for r in hours if r[0] == month]
        days = [max(this_month[d:d + 24]) for d in range(0, len(this_month), 24)]
        return round(100 * sum(days) / len(days)), "real"
    t = simulator.COUNTRIES[country_id]["typical_weather"]
    i = month - 1
    return round(100 * score(t["temp_high_c"][i], t["humidity_pct"][i] - 15, t["wind_kmh"][i])), "simulated"


def _wildfire(country_id, month):
    index, source = wildfire_risk_index(country_id, month)
    # WILDFIRE: chance grows faster than the index (index 50 -> 0.25, index 80 -> 0.64),
    # so only really hot, dry, windy months carry a serious risk.
    return {"chance": _clamp((index / 100) ** 2), "intensity": index / 100, "source": source,
            "basis": f"wildfire risk index {index}/100"}


def _earthquake(country_id, country):
    history = _earthquakes(str(DATA_DIR / f"earthquakes_{country_id}.json"))
    if history:
        per_year, source = history["count"] / history["years"], "real"
        basis = f"{history['count']} quakes M4+ within 200 km in {history['years']} years (USGS)"
    else:
        per_year = float(country.get("crisis", {}).get("earthquakes_per_year_if_no_data", 0.1))
        source, basis = "simulated", f"about {per_year} a year (config, no saved history)"
    # EARTHQUAKE: not seasonal. With quakes happening at random at `per_year` a year, the
    # chance of at least one in a month is 1 - e^(-per_year / 12) (the usual way to turn an
    # average rate into a chance). 7 quakes in 50 years -> about 1% a month.
    return {"chance": _clamp(1 - math.exp(-per_year / 12)), "intensity": 0.3, "source": source,
            "basis": basis}


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------
def _severity(country_id, kind, intensity, rng):
    """
    1 (minor) to 5 (extreme).
    Earthquakes: a real past magnitude from the USGS history, picked at random, mapped
        M4.0-4.4 -> 1, 4.5-4.9 -> 2, 5.0-5.4 -> 3, 5.5-5.9 -> 4, 6.0+ -> 5.
    Everything else: 1 + 4 x the month's intensity, plus some randomness, rounded.
        A mild month mostly gives 1-2, an extreme month mostly 4-5.
    """
    if kind == "earthquake":
        history = _earthquakes(str(DATA_DIR / f"earthquakes_{country_id}.json"))
        mags = history["magnitudes"] if history and history["magnitudes"] else [4.2, 4.4, 4.7]
        magnitude = rng.choice(mags)
        return min(5, max(1, int((magnitude - 4.0) / 0.5) + 1))
    return int(min(5, max(1, round(1 + 4 * intensity + rng.gauss(0, 0.7)))))


# ---------------------------------------------------------------------------
# Making a crisis: at random for the month, or picked by hand
# ---------------------------------------------------------------------------
def pick_random(country_id, month, seed=None):
    """
    A random crisis for this country and month. Each type's chance of being picked is
    proportional to its monthly chance: in a Texas August a heat wave is far more likely
    than a cold snap. Same seed = same pick (handy for repeatable demos).
    """
    rng = random.Random(seed)
    chances = monthly_chances(country_id, month)
    kinds = list(chances)
    kind = rng.choices(kinds, weights=[max(chances[k]["chance"], 1e-6) for k in kinds])[0]
    severity = _severity(country_id, kind, chances[kind]["intensity"], rng)
    return make_crisis(country_id, month, kind, severity, rng=rng, chances=chances)


def make_crisis(country_id, month, kind, severity, rng=None, chances=None):
    """A crisis of a chosen type and severity (1-5), e.g. for the dispatcher's manual pick."""
    if kind not in TYPES:
        raise ValueError(f"unknown crisis type {kind!r}; choose from {', '.join(TYPES)}")
    rng = rng or random.Random()
    severity = int(min(5, max(1, severity)))
    t = TYPES[kind]
    start = t["start_hour"] if t["start_hour"] is not None else rng.randint(9, 18)  # sudden: any daytime hour
    warning = rng.randint(*t["warning_hours"]) if t["forecastable"] else 0
    chance = (chances or monthly_chances(country_id, month))[kind]
    return {
        "type": kind,
        "name": t["name"],
        "severity": severity,
        "severity_name": SEVERITY_NAMES[severity],
        "forecastable": t["forecastable"],
        "warning_hours": warning,          # announced this many hours before it starts
        "start_hour": start,               # hour of the demo day it begins (0-23)
        "end_hour": min(24, start + t["hours"]),
        "what": t["what"],
        "month": month,
        "chance_this_month": chance["chance"],
        "basis": chance["basis"],
        "source": chance["source"],
    }


def forecast_label(c, hour):
    """
    What the dispatcher sees about crisis c at this hour of the demo day (0-24, can be 14.25):
      before, forecastable, inside the warning period: "Forecast: heat wave in 18h"
      before, not forecastable (or warning not out yet): None (nobody knows yet)
      during: "Heat wave now: severity 3 (serious)"
      after:  "Heat wave over"
    The demo day starts at midnight, so a warning longer than the start hour was already
    out when the day began.
    """
    if hour < c["start_hour"]:
        hours_left = math.ceil(c["start_hour"] - hour)
        if c["forecastable"] and hours_left <= c["warning_hours"]:
            return f"Forecast: {c['name'].lower()} in {hours_left}h"
        return None
    if hour < c["end_hour"]:
        return f"{c['name']} now: severity {c['severity']} ({c['severity_name'].lower()})"
    return f"{c['name']} over"


# ---------------------------------------------------------------------------
# Run directly: chances by month for every country, and a few random picks
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    short = {"heat_wave": "heat", "cold_snap": "cold", "windstorm": "wind",
             "earthquake": "quake", "wildfire": "fire", "conflict": "attack"}
    for country_id in simulator.COUNTRIES:
        simulator.use_country(country_id)
        print(f"===== {simulator.COUNTRY['name']} - chance per month (approximate)")
        print("month  " + "".join(f"{s:>8}" for s in short.values()) + "   fire index")
        for month in range(1, 13):
            ch = monthly_chances(country_id, month)
            index, _ = wildfire_risk_index(country_id, month)
            print(f"{month:5d}  " + "".join(f"{ch[k]['chance']:8.0%}" for k in short) + f"   {index:5d}")
        for month in (1, 8):
            c = pick_random(country_id, month, seed=7)
            print(f"  random pick for month {month}: {c['name']}, severity {c['severity']} "
                  f"({c['severity_name']}), starts {c['start_hour']}:00, "
                  f"{'warning ' + str(c['warning_hours']) + 'h' if c['forecastable'] else 'no warning'}"
                  f" | {forecast_label(c, 6)} | {c['basis']}")
        print()
