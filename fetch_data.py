"""
fetch_data.py - download real data ONCE, before the demo, and save it in data/.

This is the ONLY file in the project that calls the internet. The dashboard only reads
the saved files in data/, so it runs with Wi-Fi off (see CLAUDE.md, "Data and
reliability rules").

For every country in config/countries.toml it saves:
  - Weather (Open-Meteo historical API): hourly temperature, humidity and wind for all
    12 months of last year, at the centre of the country's map region.
    -> data/weather_<country>.json
  - Critical buildings (OpenStreetMap, Overpass API): real hospitals and fire stations
    inside the map region, plus water facilities and cold storage where they're tagged.
    -> data/buildings_<country>.json
  - Earthquake history (USGS): every earthquake of magnitude 4+ within 200 km of the
    region over the last 50 years, and how many there were.
    -> data/earthquakes_<country>.json

All three services are free and need no key.

Safety rules:
  - Every request is tried twice (one retry) before giving up.
  - If a source still fails, it's skipped with a message; the others carry on.
  - A file is never overwritten by an empty result if it already holds good data.
  - Files are written to a temporary file first, then swapped in, so a crash can't
    leave a half-written file behind.

Run it with:
    python fetch_data.py
"""

import json
import os
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
CONFIG_FILE = HERE / "config" / "countries.toml"
DATA_DIR = HERE / "data"

LAST_YEAR = date.today().year - 1                 # "last year" = the full previous calendar year
EARTHQUAKE_RADIUS_KM = 200
EARTHQUAKE_MIN_MAGNITUDE = 4.0
EARTHQUAKE_YEARS = 50

TIMEOUT_S = 90                                    # how long to wait for one answer
RETRY_WAIT_S = 5                                  # pause before the one retry
USER_AGENT = "InnovateLA-Failsafe-Energy hackathon demo (fetch_data.py)"

WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def say(message, indent=1):
    print("  " * indent + message, flush=True)


def get_json(url, params=None, post_data=None):
    """Ask a web API for JSON. Tries twice (one retry). Raises if both tries fail."""
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    body = urllib.parse.urlencode(post_data).encode() if post_data else None
    request = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as error:
            if attempt == 1:
                say(f"! first try failed ({short(error)}), retrying in {RETRY_WAIT_S} s...", 2)
                time.sleep(RETRY_WAIT_S)
            else:
                raise RuntimeError(short(error)) from error


def short(error):
    text = str(getattr(error, "reason", error)) or error.__class__.__name__
    return text[:120]


def save(path, payload, is_empty):
    """
    Save payload as JSON. If the result is empty and the file already holds good data,
    keep the old file. Returns a short note about what happened.
    """
    if is_empty and path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if not old.get("empty", True):
                return f"got nothing new, kept the good data already in {path.name}"
        except (json.JSONDecodeError, OSError):
            pass                                  # old file broken: replace it
    payload["empty"] = is_empty
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)                         # swap in all at once
    size_kb = path.stat().st_size / 1024
    return f"saved {path.name} ({size_kb:,.0f} KB)"


def region_of(country):
    """The map region's bounding box and centre, from the zone shapes."""
    points = [p for zone in country["zones"] for p in zone["shape"]]
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    box = {"south": min(lats), "west": min(lons), "north": max(lats), "east": max(lons)}
    centre = ((box["south"] + box["north"]) / 2, (box["west"] + box["east"]) / 2)
    return box, centre


def stamp(source, extra):
    """Common details saved with every file."""
    return {"source": source,
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            **extra}


# ---------------------------------------------------------------------------
# The three sources
# ---------------------------------------------------------------------------
def fetch_weather(country_id, country, box, centre):
    data = get_json(WEATHER_URL, params={
        "latitude": round(centre[0], 4), "longitude": round(centre[1], 4),
        "start_date": f"{LAST_YEAR}-01-01", "end_date": f"{LAST_YEAR}-12-31",
        "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        "timezone": "auto",
    })
    hourly = data.get("hourly", {})
    hours = len(hourly.get("time", []))
    temps = [t for t in hourly.get("temperature_2m", []) if t is not None]
    payload = stamp("Open-Meteo (archive-api.open-meteo.com), weather reanalysis", {
        "country": country_id, "year": LAST_YEAR,
        "location": {"latitude": data.get("latitude"), "longitude": data.get("longitude"),
                     "timezone": data.get("timezone")},
        "units": data.get("hourly_units", {}),
        "hourly": hourly,
    })
    note = save(DATA_DIR / f"weather_{country_id}.json", payload, is_empty=not temps)
    summary = (f"{hours:,} hours, {min(temps):.1f} to {max(temps):.1f} °C" if temps else "no hours")
    return f"{summary}; {note}"


def fetch_buildings(country_id, country, box, centre):
    b = f'{box["south"]},{box["west"]},{box["north"]},{box["east"]}'
    # Things worth protecting: hospitals, fire stations, water facilities, cold storage
    query = f"""
    [out:json][timeout:60];
    (
      nwr["amenity"="hospital"]({b});
      nwr["amenity"="fire_station"]({b});
      nwr["man_made"~"^(water_works|water_tower|wastewater_plant|pumping_station)$"]({b});
      nwr["building"="cold_storage"]({b});
      nwr["industrial"="cold_storage"]({b});
    );
    out center tags;
    """
    data = get_json(OVERPASS_URL, post_data={"data": query})
    buildings = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        if lat is None or lon is None:
            continue
        if tags.get("amenity") == "hospital":
            kind = "hospital"
        elif tags.get("amenity") == "fire_station":
            kind = "fire_station"
        elif "cold_storage" in (tags.get("building"), tags.get("industrial")):
            kind = "cold_storage"
        else:
            kind = "water"
        buildings.append({"type": kind, "name": tags.get("name", f"Unnamed {kind.replace('_', ' ')}"),
                          "lat": round(lat, 6), "lon": round(lon, 6),
                          "osm_id": f'{el.get("type")}/{el.get("id")}'})
    payload = stamp("OpenStreetMap via Overpass API (© OpenStreetMap contributors, ODbL)", {
        "country": country_id, "region_box": box, "buildings": buildings,
    })
    note = save(DATA_DIR / f"buildings_{country_id}.json", payload, is_empty=not buildings)
    counts = {}
    for item in buildings:
        counts[item["type"]] = counts.get(item["type"], 0) + 1
    listing = ", ".join(f"{n} {kind.replace('_', ' ')}" for kind, n in sorted(counts.items())) or "none found"
    return f"{listing}; {note}"


def fetch_earthquakes(country_id, country, box, centre):
    today = date.today()
    start = today.replace(year=today.year - EARTHQUAKE_YEARS)
    data = get_json(USGS_URL, params={
        "format": "geojson", "starttime": start.isoformat(), "endtime": today.isoformat(),
        "latitude": round(centre[0], 4), "longitude": round(centre[1], 4),
        "maxradiuskm": EARTHQUAKE_RADIUS_KM, "minmagnitude": EARTHQUAKE_MIN_MAGNITUDE,
        "orderby": "time",
    })
    if "features" not in data:
        raise RuntimeError("unexpected answer from USGS")
    quakes = []
    for f in data["features"]:
        p, g = f.get("properties", {}), f.get("geometry", {}).get("coordinates", [None, None, None])
        quakes.append({"magnitude": p.get("mag"), "place": p.get("place"),
                       "time": datetime.fromtimestamp(p["time"] / 1000, timezone.utc).strftime("%Y-%m-%d")
                       if p.get("time") else None,
                       "lon": g[0], "lat": g[1], "depth_km": g[2]})
    payload = stamp("USGS Earthquake Hazards Program (earthquake.usgs.gov)", {
        "country": country_id, "centre": {"latitude": centre[0], "longitude": centre[1]},
        "radius_km": EARTHQUAKE_RADIUS_KM, "min_magnitude": EARTHQUAKE_MIN_MAGNITUDE,
        "from": start.isoformat(), "to": today.isoformat(),
        "count": len(quakes), "earthquakes": quakes,
    })
    # Zero earthquakes can be a real answer (a quiet area). save() still writes it the
    # first time, but never lets it replace an older file that did list earthquakes.
    note = save(DATA_DIR / f"earthquakes_{country_id}.json", payload, is_empty=not quakes)
    strongest = max((q["magnitude"] for q in quakes if q["magnitude"]), default=None)
    detail = f", strongest M{strongest:.1f}" if strongest else ""
    return f"{len(quakes)} earthquakes M{EARTHQUAKE_MIN_MAGNITUDE:g}+ in {EARTHQUAKE_YEARS} years{detail}; {note}"


SOURCES = [
    ("Weather (Open-Meteo)", fetch_weather),
    ("Critical buildings (OpenStreetMap)", fetch_buildings),
    ("Earthquakes (USGS)", fetch_earthquakes),
]


# ---------------------------------------------------------------------------
# Run it
# ---------------------------------------------------------------------------
def main():
    DATA_DIR.mkdir(exist_ok=True)
    with open(CONFIG_FILE, "rb") as f:
        countries = tomllib.load(f)["countries"]

    print(f"Fetching real data for {len(countries)} countries into {DATA_DIR.name}/ "
          f"(weather for {LAST_YEAR})\n", flush=True)
    results = []
    for country_id, country in countries.items():
        box, centre = region_of(country)
        print(f"== {country['name']}  (region centre {centre[0]:.4f}, {centre[1]:.4f})", flush=True)
        for label, fetch in SOURCES:
            say(f"{label}: downloading...")
            try:
                outcome = fetch(country_id, country, box, centre)
                say(f"OK  {outcome}", 2)
                results.append((country["name"], label, "OK", outcome))
            except Exception as error:   # skip this source, carry on with the rest
                say(f"SKIPPED: {short(error)}. Any data saved earlier is kept.", 2)
                results.append((country["name"], label, "SKIPPED", short(error)))
            time.sleep(1)                # be polite to the free services
        print(flush=True)

    print("Summary", flush=True)
    for name, label, status, detail in results:
        print(f"  [{status:7s}] {name} - {label}", flush=True)
    skipped = sum(r[2] == "SKIPPED" for r in results)
    print(f"\nDone: {len(results) - skipped} saved, {skipped} skipped.", flush=True)


if __name__ == "__main__":
    main()
