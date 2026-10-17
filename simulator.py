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

NEIGHBORHOODS = ["San Pedro", "Wilmington", "Harbor City", "Long Beach West"]

# What each home has on the line. This is how the dispatcher knows "whose power can wait".
#   (type, description, priority, how common)
HOME_TYPES = [
    ("medical", "Medical equipment at home (oxygen, dialysis)", "critical", 1),
    ("cold_storage", "Small cold storage / pharmacy fridge", "critical", 1),
    ("telecom", "Hosts a cell-phone relay", "critical", 1),
    ("family", "Regular household", "normal", 6),
    ("flexible", "Has EV charger and pool pump (can wait)", "flexible", 3),
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
def make_fleet(rng):
    """Create the list of homes. Each home has one battery."""
    types = [t for t in HOME_TYPES for _ in range(t[3])]
    fleet = []
    for i in range(1, FLEET_SIZE + 1):
        home_type, description, priority, _ = rng.choice(types)
        fleet.append({
            "battery_id": f"BAT-{i:03d}",
            "home_id": f"HOME-{i:03d}",
            "neighborhood": rng.choice(NEIGHBORHOODS),
            "home_type": home_type,
            "description": description,
            "priority": priority,
            "start_charge_pct": rng.uniform(40, 80),
        })

    # Make sure the planted problems land on homes that make a good story:
    # the tripped battery is at a critical home, so the dispatcher really cares.
    _set_type(fleet, TRIPPED_BATTERY, "medical")
    _set_type(fleet, SILENT_BATTERY, "family")
    _set_type(fleet, BROKEN_BATTERY, "cold_storage")
    return fleet


def _set_type(fleet, battery_id, home_type):
    for home in fleet:
        if home["battery_id"] == battery_id:
            for t in HOME_TYPES:
                if t[0] == home_type:
                    home["home_type"], home["description"], home["priority"] = t[0], t[1], t[2]


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
    if home["home_type"] == "medical":
        kw += 0.8                             # equipment runs all day
    if home["home_type"] == "cold_storage":
        kw += 1.5
    if home["home_type"] == "telecom":
        kw += 1.0
    if home["home_type"] == "flexible" and (hour >= 22 or hour < 5):
        kw += 7.0                             # EV charging overnight
    if home["home_type"] == "flexible" and 12 <= hour < 18:
        kw += 1.5                             # pool pump
    if is_heat_wave(hour):
        kw += rng.uniform(3.0, 5.0)           # air conditioning
    return kw + rng.uniform(-0.2, 0.2)


def flexible_usage_kw(home, hour):
    """The part of a home's usage that could wait an hour or two without hurting anyone.
    Only "flexible" homes have it: EV charging, pool pump, and a smart thermostat
    that can let the house warm up a degree or two during a heat wave."""
    if home["home_type"] != "flexible":
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
                "home_type": home["home_type"],
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
                print(f"  {r['battery_id']} ({r['home_type']}): status={r['battery_status']}, "
                      f"charge={r['charge_pct']}, temp={r['inverter_temp_c']}, "
                      f"usage={r['home_usage_kw']} kW, from grid={r['from_grid_kw']} kW")
        row = snapshot(data, t)[0]
        print(f"  grid stress={row['grid_stress']}, price=${row['price_per_kwh']}/kWh, "
              f"heat wave={row['heat_wave']}\n")

    totals = earnings_by_battery(data)
    print(f"Whole fleet earned ${sum(totals.values()):.2f} today "
          f"(avg ${sum(totals.values()) / len(totals):.2f} per battery)")
