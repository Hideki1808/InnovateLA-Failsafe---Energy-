"""
simulator.py - makes up a fake home-battery fleet so we have data for the dashboard.

What it creates:
  - A fleet of homes, each with one battery.
  - One day of readings, every 15 minutes, for every battery.
  - Planted problems for the demo:
      1. A battery that goes SILENT  (stops talking, but is still working fine)
      2. A battery that TRIPS        (overheats, shuts itself off, says "tripped")
      3. A battery that BREAKS       (stops talking AND stops helping the home)
      4. A STRESS EVENT in the afternoon that strains the grid: a heat wave in Texas
         (everyone's AC), a cold snap in Germany (everyone's heating). See the config file.

How to tell silent vs broken (this is the trick for the demo):
  Every home also has a utility meter that keeps reporting even when the battery
  doesn't. If the battery is silent but the meter shows grid power DIFFERENT from
  the home's usage, the battery is still working -> it's just not talking.
  If the meter shows the home pulling its FULL usage from the grid -> it's broken.

Country-specific numbers (prices, voltage, map area, zones, buildings...) come from
config/countries.toml. All of them are approximate.

Run it by itself to print a summary for every country and save fleet_data_<country>.csv:
    python simulator.py
Only uses things built into Python, so nothing extra to install.
"""

import csv
import random
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Settings you can tweak
# ---------------------------------------------------------------------------
FLEET_SIZE = 40
STEP_MINUTES = 15
DAY_START = datetime(2026, 10, 17, 0, 0)
SEED = 42  # same seed = same fake data every run (handy for demos)

# ---------------------------------------------------------------------------
# Country settings: everything country-specific lives in config/countries.toml
# ---------------------------------------------------------------------------
# (All values there are approximate.) The dashboard picks a country with
# use_country("us_texas"), which fills in the settings below from that file.
CONFIG_FILE = Path(__file__).parent / "config" / "countries.toml"


def load_countries():
    """Read every country from the config file: {country_id: settings}."""
    with open(CONFIG_FILE, "rb") as f:
        return tomllib.load(f)["countries"]


COUNTRIES = load_countries()
DEFAULT_COUNTRY = next(iter(COUNTRIES))       # the first one in the file

# Household types. This is how the dispatcher knows "whose power can wait".
# The descriptions and priorities are the same everywhere; how common each type is
# comes from the country's household_mix.
HOUSEHOLD_DESCRIPTIONS = {
    "regular":    ("Regular household", "normal"),
    "vulnerable": ("Elderly or heat-vulnerable residents", "critical"),
    "medical":    ("Medical equipment at home (oxygen, dialysis)", "critical"),
}

# Filled in by use_country() below
COUNTRY_ID = COUNTRY = None
ZONES = WATER = HOUSEHOLD_TYPES = CRITICAL_BUILDINGS = None
FLEXIBLE_SHARE = BATTERY_CAPACITY_KWH = BATTERY_MAX_KW = None


def use_country(country_id):
    """
    Switch every country-specific setting to the given country (an id from the
    config file, e.g. "us_texas"). Call this before simulate().

    ZONES: the region is one section of the grid, split into zones (neighborhoods).
    Each zone is a shape on the map (corners as latitude, longitude); together they
    tile the region with no gaps or overlaps, so every battery and building is in
    exactly one. The shapes sit over streets and houses only, so random points inside
    them land on dry land. WATER marks nearby places that are NOT land, as a second
    safety check. Each zone has a capacity; besides our fleet homes it also has other
    customers (homes without batteries, shops). Zone stress = what it draws ÷ capacity.
    """
    global COUNTRY_ID, COUNTRY, ZONES, WATER, HOUSEHOLD_TYPES, CRITICAL_BUILDINGS
    global FLEXIBLE_SHARE, BATTERY_CAPACITY_KWH, BATTERY_MAX_KW
    c = COUNTRIES[country_id]
    COUNTRY_ID, COUNTRY = country_id, c
    ZONES = {z["name"]: {"shape": [tuple(p) for p in z["shape"]],
                         "capacity_kw": z["capacity_kw"],
                         "other_customers_kw": z["other_customers_kw"]}
             for z in c["zones"]}
    WATER = {w["name"]: [tuple(p) for p in w["shape"]] for w in c.get("water", [])}
    HOUSEHOLD_TYPES = {t: (desc, priority, c["household_mix"][t])
                       for t, (desc, priority) in HOUSEHOLD_DESCRIPTIONS.items()}
    FLEXIBLE_SHARE = c["household_mix"]["flexible_share"]
    BATTERY_CAPACITY_KWH = float(c["battery"]["capacity_kwh"])
    BATTERY_MAX_KW = float(c["battery"]["max_kw"])
    # Critical buildings: protected last, never cut off. If the grid is desperate, the
    # ones with their own backup can be asked to run on it for a while.
    CRITICAL_BUILDINGS = [
        {"building_id": b["id"], "name": b["name"], "building_type": b["type"],
         "lat": b["location"][0], "lon": b["location"][1], "load_kw": b["load_kw"],
         "backup": b["backup"], "backup_hours": b["backup_hours"]}
        for b in c["critical_buildings"]
    ]


use_country(DEFAULT_COUNTRY)

# Planted problems
SILENT_BATTERY = "BAT-007"
SILENT_AT_HOUR = 13      # stops reporting at 1 pm

TRIPPED_BATTERY = "BAT-023"
TRIP_AT_HOUR = 16        # overheats during the stress event and trips at 4 pm
TRIP_OVERHEAT_C = 72     # how hot its inverter gets in the hour before it trips

BROKEN_BATTERY = "BAT-031"
BROKEN_AT_HOUR = 15      # dies at 3 pm

INVERTER_FLOOR_C = 20    # batteries sit in garages/utility rooms: never colder than this


# ---------------------------------------------------------------------------
# The fleet (who is in it)
# ---------------------------------------------------------------------------
def inside(lat, lon, shape):
    """True if the point is inside the shape. (The classic "ray casting" test: draw a
    line from the point and count how many edges it crosses; odd means inside.)"""
    hits = False
    j = len(shape) - 1
    for i in range(len(shape)):
        (lat_i, lon_i), (lat_j, lon_j) = shape[i], shape[j]
        if (lat_i > lat) != (lat_j > lat) and \
                lon < (lon_j - lon_i) * (lat - lat_i) / (lat_j - lat_i) + lon_i:
            hits = not hits
        j = i
    return hits


def zone_of(lat, lon):
    """Which zone a spot is in (None if it's outside the region)."""
    for name, zone in ZONES.items():
        if inside(lat, lon, zone["shape"]):
            return name
    return None


def on_land(lat, lon):
    """Inside one of our zones, and not in any known water."""
    in_area = zone_of(lat, lon) is not None
    in_water = any(inside(lat, lon, shape) for shape in WATER.values())
    return in_area and not in_water


def random_point(rng, shape):
    """A random spot inside a zone's shape that's on land."""
    lats = [p[0] for p in shape]
    lons = [p[1] for p in shape]
    while True:   # keep trying until a point lands inside (almost always first try)
        lat = rng.uniform(min(lats), max(lats))
        lon = rng.uniform(min(lons), max(lons))
        if inside(lat, lon, shape) and on_land(lat, lon):
            return round(lat, 5), round(lon, 5)


def make_fleet(rng):
    """Create the list of homes. Each home has one battery."""
    # Exact shares (not random picks), so the fleet mix is the same every time:
    # with 40 homes that's about 28 regular, 8 vulnerable, 4 medical (the planted
    # problems below can swap one or two).
    total_weight = sum(weight for _, _, weight in HOUSEHOLD_TYPES.values())
    types = []
    for t, (_, _, weight) in HOUSEHOLD_TYPES.items():
        types += [t] * round(FLEET_SIZE * weight / total_weight)
    types = (types + ["regular"] * FLEET_SIZE)[:FLEET_SIZE]   # top up / trim after rounding
    rng.shuffle(types)
    flexible_left = round(types.count("regular") * FLEXIBLE_SHARE)

    fleet = []
    for i in range(1, FLEET_SIZE + 1):
        household_type = types[i - 1]
        has_flexible_load = household_type == "regular" and flexible_left > 0
        flexible_left -= has_flexible_load
        zone = rng.choice(list(ZONES))
        lat, lon = random_point(rng, ZONES[zone]["shape"])
        home = {
            "battery_id": f"BAT-{i:03d}",
            "home_id": f"HOME-{i:03d}",
            "zone": zone,
            "lat": lat,
            "lon": lon,
            "household_type": household_type,
            "has_flexible_load": has_flexible_load,
            "start_charge_pct": rng.uniform(40, 80),
        }
        _describe(home)
        fleet.append(home)

    # Make sure the planted problems land on homes that make a good story:
    # the tripped battery is at a medical home and the broken one at a vulnerable home,
    # so the dispatcher really cares.
    _set_type(fleet, TRIPPED_BATTERY, "medical")
    _set_type(fleet, SILENT_BATTERY, "regular")
    _set_type(fleet, BROKEN_BATTERY, "vulnerable")
    return fleet


def _describe(home):
    """Fill in the description and priority from the household type."""
    description, priority, _ = HOUSEHOLD_TYPES[home["household_type"]]
    if home["has_flexible_load"]:
        description, priority = f"Regular household with {COUNTRY['flexible_load']['name']}", "flexible"
    home["description"], home["priority"] = description, priority


def _set_type(fleet, battery_id, household_type):
    for home in fleet:
        if home["battery_id"] == battery_id:
            home["household_type"] = household_type
            home["has_flexible_load"] = False
            _describe(home)


def critical_buildings():
    """The critical buildings (hospital, fire station, cold storage) with their locations."""
    buildings = []
    for b in CRITICAL_BUILDINGS:
        assert on_land(b["lat"], b["lon"]), f"{b['name']} is not on land"
        buildings.append({**b, "zone": zone_of(b["lat"], b["lon"])})
    return buildings


def building_load_kw(building, stress_event):
    """A critical building's power use. It goes up during the stress event (cooling in a
    heat wave, heating in a cold snap) by the country's buildings_factor."""
    factor = COUNTRY["stress_event"]["buildings_factor"] if stress_event else 1.0
    return building["load_kw"] * factor


def other_customers_kw(zone, hour):
    """Power used in the zone by customers outside our fleet (homes without
    batteries, shops). Low at night, highest in the evening, more during the stress event."""
    if hour < 6:
        share = 0.45
    elif hour < 17:
        share = 0.7
    elif hour < 22:
        share = 1.0
    else:
        share = 0.6
    if is_stress_event(hour):
        share *= COUNTRY["stress_event"]["other_customers_factor"]   # everyone's AC / heating
    return ZONES[zone]["other_customers_kw"] * share


# ---------------------------------------------------------------------------
# The world around the batteries (prices, grid strain, weather)
# ---------------------------------------------------------------------------
# Set by simulate(): on an ordinary day there's no stress event, and the typical
# weather day for the chosen month (from weather.py)
_ordinary_day = False
_weather_day = None


def is_stress_event(hour):
    """Is the country's stress event (heat wave, cold snap...) happening at this hour?"""
    if _ordinary_day:
        return False
    event = COUNTRY["stress_event"]
    return event["start_hour"] <= hour < event["end_hour"]


def electricity_price(hour):
    """Price per kWh in the country's currency (from the config file).
    Cheap midday (solar), expensive in the evening."""
    p = COUNTRY["prices"]
    event = COUNTRY["stress_event"]
    if is_stress_event(hour) and hour >= event["start_hour"] + 2:
        return event["peak_price"]            # stress event peak: very expensive
    if is_stress_event(hour):
        return event["price"]
    if 10 <= hour < 15:
        return p["cheap_solar"]               # lots of solar, cheap
    if 17 <= hour < 21:
        return p["evening_peak"]              # normal evening peak
    return p["night"]


def grid_stress(hour):
    """The utility's citywide alert level, 0 (relaxed) to 100 (about to shed load).
    Batteries react to this signal on their own. Each zone's actual stress is worked
    out separately from what it's really drawing (see zone_stress in the readings)."""
    if is_stress_event(hour):
        return 85 + (hour - COUNTRY["stress_event"]["start_hour"]) * 2   # climbs 85 -> 95
    if 17 <= hour < 21:
        return 60
    if 7 <= hour < 10:
        return 45
    return 25


def outdoor_temp_c(hour):
    """Outdoor temperature: the month's typical day (weather.py), plus the stress event's
    change while it's on (hotter in a heat wave, colder in a cold snap)."""
    import weather
    base = weather.at(_weather_day, hour)["temp_c"]
    if is_stress_event(hour):
        base += COUNTRY["stress_event"]["temperature_change_c"]   # hotter or colder
    return base


# ---------------------------------------------------------------------------
# What each home and battery does
# ---------------------------------------------------------------------------
def home_usage_kw(home, hour, rng):
    """How much power the home is using right now."""
    kw = 0.6                                  # fridge, lights, wifi
    if 6 <= hour < 9 or 17 <= hour < 22:
        kw += 1.5                             # people are home and busy
    if home["household_type"] == "medical":
        kw += 0.8                             # equipment runs all day
    if home["household_type"] == "vulnerable":
        kw += 0.4                             # someone home all day: fans, medicine fridge
    if home["has_flexible_load"]:
        kw += flexible_usage_kw(home, hour, event_part=False)   # EV overnight, daytime load
    if is_stress_event(hour):
        low, high = COUNTRY["stress_event"]["extra_home_load_kw"]
        kw += rng.uniform(low, high)          # air conditioning (heat wave) or heating (cold snap)
    return kw + rng.uniform(-0.2, 0.2)


def flexible_usage_kw(home, hour, event_part=True):
    """The part of a home's usage that could wait an hour or two without hurting anyone.
    Only homes with flexible load have it: EV charging overnight, a daytime load (pool
    pump in Texas, heat-pump water heater in Germany: see the config file), and a smart
    thermostat that can let the house drift a degree during the stress event."""
    if not home["has_flexible_load"]:
        return 0.0
    flex = COUNTRY["flexible_load"]
    kw = 0.0
    if hour >= 22 or hour < 5:
        kw += COUNTRY["home_load_kw"]["ev_charger"]   # EV charging
    if 12 <= hour < 18:
        kw += flex["daytime_kw"]                      # pool pump / water heater
    if event_part and is_stress_event(hour):
        kw += COUNTRY["stress_event"]["thermostat_nudge_kw"]   # thermostat nudge (part of AC/heating)
    return kw


def battery_plan_kw(hour, charge_pct):
    """
    What a healthy battery decides to do.
    Positive = discharging (helping the home / grid). Negative = charging.
    This is the "earn its keep on an ordinary day" part: buy cheap, use when expensive.

    Note: batteries follow their own schedule. They don't know when the grid is in
    trouble, so they keep charging through 3 pm even if the stress event has started.
    Pausing that is one of the dispatcher's relief steps.
    """
    if 10 <= hour < 15:
        return -0.25 * BATTERY_MAX_KW if charge_pct < 95 else 0.0   # cheap solar hours: fill up slowly, then hold
    if grid_stress(hour) >= 80 and charge_pct > 15:
        return 0.5 * BATTERY_MAX_KW           # grid is strained: push hard
    if 17 <= hour < 21 and charge_pct > 20:
        return 0.3 * BATTERY_MAX_KW           # evening peak: use stored power
    return 0.0


# ---------------------------------------------------------------------------
# Run the day
# ---------------------------------------------------------------------------
def simulate(seed=SEED, ordinary_day=False, month=None):
    """Return a list of readings (one dict per battery per 15 minutes).

    ordinary_day=True gives a calm day: no stress event and no planted problems.
    Used by the "Normal day earnings" tab.
    month (1-12): whose typical weather to use (default: the demo date's month).
    The weather comes from weather.py: real saved data if there is some, else the
    approximate monthly values in the config.
    """
    import weather                            # (here, not at the top: weather.py imports this file)
    global _ordinary_day, _weather_day
    _ordinary_day = ordinary_day
    _weather_day = weather.typical_day(COUNTRY_ID, month or DAY_START.month)
    try:
        return _run_day(seed, ordinary_day)
    finally:
        _ordinary_day = False


def _run_day(seed, ordinary_day):
    rng = random.Random(seed)
    buildings = critical_buildings()
    # Which batteries get planted problems today (none on an ordinary day)
    silent_id = None if ordinary_day else SILENT_BATTERY
    tripped_id = None if ordinary_day else TRIPPED_BATTERY
    broken_id = None if ordinary_day else BROKEN_BATTERY
    fleet = make_fleet(rng)
    readings = []

    charge = {h["battery_id"]: h["start_charge_pct"] for h in fleet}
    if ordinary_day:
        # A normal day repeats: batteries start where last evening left them (~20%),
        # so the day's earnings come from buying cheap and using it later, not from
        # energy that was already stored.
        charge = {bid: 20.0 for bid in charge}
    temp = {h["battery_id"]: 30.0 for h in fleet}
    tripped = set()

    steps = 24 * 60 // STEP_MINUTES
    step_hours = STEP_MINUTES / 60

    for step in range(steps):
        now = DAY_START + timedelta(minutes=step * STEP_MINUTES)
        hour = now.hour + now.minute / 60
        price = electricity_price(hour)
        stress = grid_stress(hour)

        for home in fleet:
            bid = home["battery_id"]
            usage = home_usage_kw(home, hour, rng)

            # --- what the battery actually does (the truth) ---
            battery_kw = battery_plan_kw(hour, charge[bid])

            if bid == broken_id and hour >= BROKEN_AT_HOUR:
                battery_kw = 0.0              # dead: not helping at all

            if bid == tripped_id:
                if hour >= TRIP_AT_HOUR:
                    tripped.add(bid)
                if bid in tripped:
                    battery_kw = 0.0          # safety switch is off

            # Batteries can't go below empty or above full
            battery_kw = max(-BATTERY_MAX_KW, min(BATTERY_MAX_KW, battery_kw))
            kwh = battery_kw * step_hours
            new_charge = charge[bid] - kwh / BATTERY_CAPACITY_KWH * 100
            if new_charge < 5 or new_charge > 100:
                battery_kw, kwh = 0.0, 0.0
            else:
                charge[bid] = new_charge

            # Inverter temperature: warms with heavy use and hot weather (indoors, so
            # never colder than INVERTER_FLOOR_C even in a cold snap)
            surroundings = max(outdoor_temp_c(hour), INVERTER_FLOOR_C)
            target_temp = surroundings + abs(battery_kw) * 2.0
            if bid == tripped_id and hour >= TRIP_AT_HOUR - 1 and bid not in tripped:
                target_temp = TRIP_OVERHEAT_C    # the hour before tripping, it runs hot
            if bid in tripped:
                target_temp = surroundings
            temp[bid] += (target_temp - temp[bid]) * 0.5

            # --- what the utility meter sees (always reports) ---
            from_grid_kw = usage - battery_kw   # negative = sending power back to grid
            nominal = COUNTRY["nominal_voltage"]
            voltage = nominal * (1 + rng.uniform(-0.008, 0.008) - (0.04 if stress >= 80 else 0))
            if bid == tripped_id and abs(hour - TRIP_AT_HOUR) < 0.01:
                voltage = nominal * 1.12      # the spike that tripped it

            # --- what the battery reports (may be missing) ---
            silent = (bid == silent_id and hour >= SILENT_AT_HOUR) or \
                     (bid == broken_id and hour >= BROKEN_AT_HOUR)
            if bid in tripped:
                status = "tripped"
            elif silent:
                status = None
            elif temp[bid] > 60:
                status = "warning_hot"
            else:
                status = "ok"

            readings.append({
                "time": now.strftime("%Y-%m-%d %H:%M"),
                "battery_id": bid,
                "home_id": home["home_id"],
                "zone": home["zone"],
                "lat": home["lat"],
                "lon": home["lon"],
                "household_type": home["household_type"],
                "description": home["description"],
                "priority": home["priority"],
                # From the battery (blank if it's silent)
                "battery_reporting": not silent,
                "battery_status": status,
                "charge_pct": None if silent else round(charge[bid], 1),
                "battery_kw": None if silent else round(battery_kw, 2),
                "inverter_temp_c": None if silent else round(temp[bid], 1),
                # From the utility meter (always there)
                "home_usage_kw": round(usage, 2),
                "flexible_kw": flexible_usage_kw(home, hour),   # part of usage that can wait
                "from_grid_kw": round(from_grid_kw, 2),
                "voltage": round(voltage, 1),
                # The world
                "price_per_kwh": price,
                "outdoor_temp_c": round(outdoor_temp_c(hour), 1),
                "grid_stress": stress,
                "stress_event": is_stress_event(hour),
                # Money: discharging when it's pricey saves/earns; charging costs
                "earnings": round(kwh * price, 3),     # in the country's currency
            })

        # --- Each zone's load and stress at this moment ---
        # Load = what our fleet homes pull from the grid (batteries reduce this)
        #      + the critical buildings + the zone's other customers.
        step_rows = readings[-len(fleet):]
        for zone, info in ZONES.items():
            fleet_kw = sum(r["from_grid_kw"] for r in step_rows if r["zone"] == zone)
            buildings_kw = sum(building_load_kw(b, is_stress_event(hour)) for b in buildings if b["zone"] == zone)
            load = fleet_kw + buildings_kw + other_customers_kw(zone, hour)
            for r in step_rows:
                if r["zone"] == zone:
                    r["zone_load_kw"] = round(load, 1)
                    r["zone_capacity_kw"] = info["capacity_kw"]
                    r["zone_stress"] = round(100 * load / info["capacity_kw"], 1)

    return readings


# ---------------------------------------------------------------------------
# Helpers the dashboard can use
# ---------------------------------------------------------------------------
def all_times(readings):
    """Every timestamp in the data, in order."""
    return sorted({r["time"] for r in readings})


def snapshot(readings, at_time):
    """One row per battery at a given time, e.g. '2026-10-17 16:30'."""
    return [r for r in readings if r["time"] == at_time]


def earnings_by_battery(readings, up_to_time=None):
    """Total each battery has earned so far today (in the country's currency)."""
    totals = {}
    for r in readings:
        if up_to_time and r["time"] > up_to_time:
            continue
        totals[r["battery_id"]] = totals.get(r["battery_id"], 0) + r["earnings"]
    return {k: round(v, 2) for k, v in totals.items()}


def save_csv(readings, path="fleet_data.csv"):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=readings[0].keys())
        writer.writeheader()
        writer.writerows(readings)


# ---------------------------------------------------------------------------
# Run directly: print a quick summary so we can see it works
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Run every country in the config file, one after the other
    for country_id in COUNTRIES:
        use_country(country_id)
        cur = COUNTRY["currency"]
        print(f"===== {COUNTRY['name']} (all numbers approximate) =====")
        data = simulate()
        save_csv(data, f"fleet_data_{country_id}.csv")
        print(f"Made {len(data)} readings for {FLEET_SIZE} batteries -> fleet_data_{country_id}.csv\n")

        for t in ["2026-10-17 12:00", "2026-10-17 16:30"]:
            print(f"--- Snapshot at {t} ---")
            for r in snapshot(data, t):
                if r["battery_id"] in (SILENT_BATTERY, TRIPPED_BATTERY, BROKEN_BATTERY):
                    print(f"  {r['battery_id']} ({r['household_type']}): status={r['battery_status']}, "
                          f"charge={r['charge_pct']}, temp={r['inverter_temp_c']}, "
                          f"usage={r['home_usage_kw']} kW, from grid={r['from_grid_kw']} kW")
            row = snapshot(data, t)[0]
            print(f"  grid stress={row['grid_stress']}, price={cur}{row['price_per_kwh']}/kWh, "
                  f"{COUNTRY['stress_event']['name'].lower()}={row['stress_event']}\n")

        totals = earnings_by_battery(data)
        print(f"Whole fleet earned {cur}{sum(totals.values()):.2f} today "
              f"(avg {cur}{sum(totals.values()) / len(totals):.2f} per battery)\n")

        homes = snapshot(data, "2026-10-17 00:00")
        print("Household types:", {t: sum(h["household_type"] == t for h in homes) for t in HOUSEHOLD_TYPES},
              "| with flexible load:", sum(h["priority"] == "flexible" for h in homes))
        print("Homes per zone:", {z: sum(h["zone"] == z for h in homes) for z in ZONES})
        print("All homes on land:", all(on_land(h["lat"], h["lon"]) for h in homes))
        print("\nCritical buildings:")
        for b in critical_buildings():
            print(f"  {b['name']} ({b['building_type']}) at {b['lat']}, {b['lon']}, {b['load_kw']} kW")
        print()
