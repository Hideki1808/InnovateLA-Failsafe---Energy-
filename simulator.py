"""
simulator.py - makes up a fake home-battery fleet so we have data for the dashboard.

What it creates:
  - A fleet of homes, each with one battery.
  - One day of readings, every 15 minutes, for every battery.
  - Planted problems for the demo:
      1. A battery that goes SILENT  (stops talking, but is still working fine)
      2. A battery that TRIPS        (overheats, shuts itself off, says "tripped")
      3. A battery that BREAKS       (stops talking AND stops helping the home)
      4. A HEAT WAVE in the afternoon (everyone's AC kicks on, the grid strains)

How to tell silent vs broken (this is the trick for the demo):
  Every home also has a utility meter that keeps reporting even when the battery
  doesn't. If the battery is silent but the meter shows grid power DIFFERENT from
  the home's usage, the battery is still working -> it's just not talking.
  If the meter shows the home pulling its FULL usage from the grid -> it's broken.

Run it by itself to print a summary and save fleet_data.csv:
    python simulator.py
Only uses things built into Python, so nothing extra to install.
"""

import csv
import random
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Settings you can tweak
# ---------------------------------------------------------------------------
FLEET_SIZE = 40
STEP_MINUTES = 15
DAY_START = datetime(2026, 10, 17, 0, 0)
SEED = 42  # same seed = same fake data every run (handy for demos)

BATTERY_CAPACITY_KWH = 20.0
BATTERY_MAX_KW = 10.0

# ---------------------------------------------------------------------------
# Where things are: a small residential part of Wilmington, near the LA harbor
# ---------------------------------------------------------------------------
# Each neighborhood is a shape on the map, given by its corners as (latitude, longitude).
# The shapes sit over streets and houses only, so random points inside them land on
# dry land. WATER marks the places nearby that are NOT land, as a second safety check.
NEIGHBORHOODS = {
    "Banning Park":     [(33.7920, -118.2620), (33.7920, -118.2520), (33.7860, -118.2520), (33.7860, -118.2620)],
    "Avalon":           [(33.7860, -118.2670), (33.7860, -118.2570), (33.7805, -118.2570), (33.7805, -118.2670)],
    "West Wilmington":  [(33.7920, -118.2740), (33.7920, -118.2650), (33.7845, -118.2650), (33.7845, -118.2740)],
    "North Wilmington": [(33.7965, -118.2700), (33.7965, -118.2570), (33.7925, -118.2570), (33.7925, -118.2700)],
}
WATER = {
    "Harbor (Slip 5 / East Basin)": [(33.7720, -118.2900), (33.7720, -118.2200), (33.7400, -118.2200), (33.7400, -118.2900)],
    "Machado Lake":                 [(33.7920, -118.2980), (33.7920, -118.2860), (33.7780, -118.2860), (33.7780, -118.2980)],
}

# Household types. This is how the dispatcher knows "whose power can wait".
#   type: (description, priority, how common)
HOUSEHOLD_TYPES = {
    "regular":    ("Regular household", "normal", 7),
    "vulnerable": ("Elderly or heat-vulnerable residents", "critical", 2),
    "medical":    ("Medical equipment at home (oxygen, dialysis)", "critical", 1),
}
# Share of regular homes with an EV charger and pool pump. That load can wait,
# so these homes are first in line when the grid needs relief.
FLEXIBLE_SHARE = 0.4

# Critical buildings: always protected, never shed. Names are made up for the demo.
CRITICAL_BUILDINGS = [
    {"building_id": "HOSP-1", "name": "Harbor Community Hospital", "building_type": "hospital",
     "lat": 33.7890, "lon": -118.2560, "load_kw": 150, "backup": "Diesel generator, 24 hours"},
    {"building_id": "FIRE-1", "name": "Wilmington Fire Station", "building_type": "fire_station",
     "lat": 33.7830, "lon": -118.2625, "load_kw": 15, "backup": "Battery, 8 hours"},
    {"building_id": "COLD-1", "name": "Harbor Cold Storage", "building_type": "cold_storage",
     "lat": 33.7880, "lon": -118.2700, "load_kw": 40, "backup": "None"},
]

# Planted problems
SILENT_BATTERY = "BAT-007"
SILENT_AT_HOUR = 13      # stops reporting at 1 pm

TRIPPED_BATTERY = "BAT-023"
TRIP_AT_HOUR = 16        # overheats during the heat wave and trips at 4 pm

BROKEN_BATTERY = "BAT-031"
BROKEN_AT_HOUR = 15      # dies at 3 pm

HEAT_WAVE_START_HOUR = 14  # 2 pm
HEAT_WAVE_END_HOUR = 20    # 8 pm


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


def on_land(lat, lon):
    """Inside one of our neighborhoods, and not in any known water."""
    in_area = any(inside(lat, lon, shape) for shape in NEIGHBORHOODS.values())
    in_water = any(inside(lat, lon, shape) for shape in WATER.values())
    return in_area and not in_water


def random_point(rng, shape):
    """A random spot inside a neighborhood shape that's on land."""
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
        neighborhood = rng.choice(list(NEIGHBORHOODS))
        lat, lon = random_point(rng, NEIGHBORHOODS[neighborhood])
        home = {
            "battery_id": f"BAT-{i:03d}",
            "home_id": f"HOME-{i:03d}",
            "neighborhood": neighborhood,
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
        description, priority = "Regular household with EV charger and pool pump", "flexible"
    home["description"], home["priority"] = description, priority


def _set_type(fleet, battery_id, household_type):
    for home in fleet:
        if home["battery_id"] == battery_id:
            home["household_type"] = household_type
            home["has_flexible_load"] = False
            _describe(home)


def critical_buildings():
    """The critical buildings (hospital, fire station, cold storage) with their locations."""
    for b in CRITICAL_BUILDINGS:
        assert on_land(b["lat"], b["lon"]), f"{b['name']} is not on land"
    return [dict(b) for b in CRITICAL_BUILDINGS]


# ---------------------------------------------------------------------------
# The world around the batteries (prices, grid strain, weather)
# ---------------------------------------------------------------------------
# Set by simulate(): on an ordinary day there's no heat wave
_ordinary_day = False


def is_heat_wave(hour):
    if _ordinary_day:
        return False
    return HEAT_WAVE_START_HOUR <= hour < HEAT_WAVE_END_HOUR


def electricity_price(hour):
    """Price in $ per kWh. Cheap midday (solar), expensive in the evening."""
    if is_heat_wave(hour) and hour >= 16:
        return 0.90   # heat wave peak: very expensive
    if is_heat_wave(hour):
        return 0.45
    if 10 <= hour < 15:
        return 0.08   # lots of solar, cheap
    if 17 <= hour < 21:
        return 0.35   # normal evening peak
    return 0.15


def grid_stress(hour):
    """How strained the grid is, 0 (relaxed) to 100 (about to shed load)."""
    if is_heat_wave(hour):
        return 85 + (hour - HEAT_WAVE_START_HOUR) * 2   # climbs 85 -> 95
    if 17 <= hour < 21:
        return 60
    if 7 <= hour < 10:
        return 45
    return 25


def outdoor_temp_c(hour):
    base = 22 + 8 * max(0, 1 - abs(hour - 15) / 9)   # warmest around 3 pm
    if is_heat_wave(hour):
        base += 10
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
    if home["has_flexible_load"] and (hour >= 22 or hour < 5):
        kw += 7.0                             # EV charging overnight
    if home["has_flexible_load"] and 12 <= hour < 18:
        kw += 1.5                             # pool pump
    if is_heat_wave(hour):
        kw += rng.uniform(3.0, 5.0)           # air conditioning
    return kw + rng.uniform(-0.2, 0.2)


def flexible_usage_kw(home, hour):
    """The part of a home's usage that could wait an hour or two without hurting anyone.
    Only homes with flexible load have it: EV charging, pool pump, and a smart thermostat
    that can let the house warm up a degree or two during a heat wave."""
    if not home["has_flexible_load"]:
        return 0.0
    kw = 0.0
    if hour >= 22 or hour < 5:
        kw += 7.0                             # EV charging
    if 12 <= hour < 18:
        kw += 1.5                             # pool pump
    if is_heat_wave(hour):
        kw += 1.0                             # thermostat nudge on the AC
    return kw


def battery_plan_kw(hour, charge_pct):
    """
    What a healthy battery decides to do.
    Positive = discharging (helping the home / grid). Negative = charging.
    This is the "earn its keep on an ordinary day" part: buy cheap, use when expensive.

    Note: batteries follow their own schedule. They don't know when the grid is in
    trouble, so they keep charging through 3 pm even if a heat wave has started.
    Pausing that is one of the dispatcher's relief steps.
    """
    if 10 <= hour < 15:
        return -2.5 if charge_pct < 95 else 0.0   # cheap solar hours: fill up slowly, then hold
    if grid_stress(hour) >= 80 and charge_pct > 15:
        return 5.0                            # grid is strained: push hard
    if 17 <= hour < 21 and charge_pct > 20:
        return 3.0                            # evening peak: use stored power
    return 0.0


# ---------------------------------------------------------------------------
# Run the day
# ---------------------------------------------------------------------------
def simulate(seed=SEED, ordinary_day=False):
    """Return a list of readings (one dict per battery per 15 minutes).

    ordinary_day=True gives a calm day: no heat wave and no planted problems.
    Used by the "Normal day earnings" tab.
    """
    global _ordinary_day
    _ordinary_day = ordinary_day
    try:
        return _run_day(seed, ordinary_day)
    finally:
        _ordinary_day = False


def _run_day(seed, ordinary_day):
    rng = random.Random(seed)
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

            # Inverter temperature: warms with heavy use and hot weather
            target_temp = outdoor_temp_c(hour) + abs(battery_kw) * 2.0
            if bid == tripped_id and hour >= TRIP_AT_HOUR - 1 and bid not in tripped:
                target_temp += 25             # the hour before tripping, it runs hot
            if bid in tripped:
                target_temp = outdoor_temp_c(hour)
            temp[bid] += (target_temp - temp[bid]) * 0.5

            # --- what the utility meter sees (always reports) ---
            from_grid_kw = usage - battery_kw   # negative = sending power back to grid
            voltage = 240 + rng.uniform(-2, 2) - (10 if stress >= 80 else 0)
            if bid == tripped_id and abs(hour - TRIP_AT_HOUR) < 0.01:
                voltage = 262.0               # the spike that tripped it

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
                "neighborhood": home["neighborhood"],
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
                "grid_stress": stress,
                "heat_wave": is_heat_wave(hour),
                # Money: discharging when it's pricey saves/earns; charging costs
                "earnings_usd": round(kwh * price, 3),
            })

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
    """Total $ each battery has earned so far today."""
    totals = {}
    for r in readings:
        if up_to_time and r["time"] > up_to_time:
            continue
        totals[r["battery_id"]] = totals.get(r["battery_id"], 0) + r["earnings_usd"]
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
    data = simulate()
    save_csv(data)
    print(f"Made {len(data)} readings for {FLEET_SIZE} batteries -> fleet_data.csv\n")

    for t in ["2026-10-17 12:00", "2026-10-17 16:30"]:
        print(f"--- Snapshot at {t} ---")
        for r in snapshot(data, t):
            if r["battery_id"] in (SILENT_BATTERY, TRIPPED_BATTERY, BROKEN_BATTERY):
                print(f"  {r['battery_id']} ({r['household_type']}): status={r['battery_status']}, "
                      f"charge={r['charge_pct']}, temp={r['inverter_temp_c']}, "
                      f"usage={r['home_usage_kw']} kW, from grid={r['from_grid_kw']} kW")
        row = snapshot(data, t)[0]
        print(f"  grid stress={row['grid_stress']}, price=${row['price_per_kwh']}/kWh, "
              f"heat wave={row['heat_wave']}\n")

    totals = earnings_by_battery(data)
    print(f"Whole fleet earned ${sum(totals.values()):.2f} today "
          f"(avg ${sum(totals.values()) / len(totals):.2f} per battery)\n")

    homes = snapshot(data, "2026-10-17 00:00")
    print("Household types:", {t: sum(h["household_type"] == t for h in homes) for t in HOUSEHOLD_TYPES},
          "| with EV + pool:", sum(h["priority"] == "flexible" for h in homes))
    print("Neighborhoods:", {n: sum(h["neighborhood"] == n for h in homes) for n in NEIGHBORHOODS})
    print("All homes on land:", all(on_land(h["lat"], h["lon"]) for h in homes))
    print("\nCritical buildings:")
    for b in critical_buildings():
        print(f"  {b['name']} ({b['building_type']}) at {b['lat']}, {b['lon']}, {b['load_kw']} kW")
