"""
rules.py - looks at the fleet at one moment and sorts every battery into:

    Needs dispatcher  - a human should look at this now
    Watch             - something is a bit off; keep an eye on it
    Can wait          - healthy, and this home's power can be put off if the grid needs it
    Normal            - nothing to do

It also answers two questions for the dispatcher:
  - When a battery goes silent: is it broken, tripped, or just not talking? (guess_silent)
  - Whose power can wait, and in what order? (wait_order)

Every rule is plain if/else, so you can read exactly why a battery got its label.

Try it by itself:
    python rules.py
"""

import simulator

NORMAL = "Normal"
WATCH = "Watch"
CAN_WAIT = "Can wait"
NEEDS_DISPATCHER = "Needs dispatcher"

# ---------------------------------------------------------------------------
# Thresholds (tweak these to make the rules stricter or looser)
# ---------------------------------------------------------------------------
HOT_C = 60                 # inverter hotter than this is a warning sign
LOW_CHARGE_PCT = 20        # below this, a critical home's backup is running thin
BUSY_GRID = 70             # zone stress at or above this: flexible homes should wait
STRAINED_GRID = 80         # zone stress at or above this: the zone is close to shedding load
VOLTAGE_LOW, VOLTAGE_HIGH = 225, 255   # normal home voltage is about 240
METER_TOLERANCE_KW = 0.3   # differences smaller than this are just noise
FLEET_ACTIVE_KW = 1.0      # if healthy batteries average more than this, the fleet is "busy"
NEARLY_FULL_PCT = 90       # a battery this full isn't expected to charge
NEARLY_EMPTY_PCT = 25      # a battery this empty isn't expected to discharge
LOOKBACK_STEPS = 8         # how far back to look for warning signs (8 x 15 min = 2 hours)


# ---------------------------------------------------------------------------
# Whose power can wait
# ---------------------------------------------------------------------------
# Lower number = can wait sooner. Medical homes come last of all; critical buildings
# (hospital, fire station, cold storage) aren't homes, but they're protected last too:
# see the relief plan below.
WAIT_LABEL = {
    1: "1 - Can wait first (EV charger, pool pump)",
    2: "2 - Can wait if needed (regular household)",
    3: "3 - Wait late (elderly / heat-vulnerable)",
    4: "4 - Protect last (medical equipment)",
}


def wait_order(row):
    """Return (number, label) for how early this home's power can wait."""
    if row["priority"] == "flexible":
        number = 1
    else:
        number = {"regular": 2, "vulnerable": 3, "medical": 4}[row["household_type"]]
    return number, WAIT_LABEL[number]


# ---------------------------------------------------------------------------
# Silent batteries: broken, tripped, or just not talking?
# ---------------------------------------------------------------------------
def guess_silent(row, history, fleet_kw_by_time):
    """
    Best guess for a battery that stopped reporting. Returns (guess, reason).

    The trick: the home's utility meter keeps reporting even when the battery doesn't.
        home usage - power from grid = what the battery is doing
    """
    last = None
    for r in reversed(history):
        if r["battery_reporting"]:
            last = r
            break
    since = last["time"][11:] if last else "the start of the day"
    battery_kw = row["home_usage_kw"] - row["from_grid_kw"]

    # Rule S1 - JUST NOT TALKING: the meter shows the battery is still moving power
    # (charging or discharging), so it must be working. Only its messages are lost.
    if abs(battery_kw) > METER_TOLERANCE_KW:
        direction = "giving" if battery_kw > 0 else "taking"
        return "just not talking", (
            f"Silent since {since}, but the meter shows the battery still {direction} "
            f"{abs(battery_kw):.1f} kW. It's working; only its messages are lost."
        )

    # Rule S2 - TRIPPED: the battery isn't doing anything, AND right before it went quiet
    # it was running hot or the meter saw a voltage spike. Those are what trip a battery.
    recent = history[-LOOKBACK_STEPS:]
    was_hot = last is not None and last["battery_status"] in ("warning_hot", "tripped")
    spike = any(r["voltage"] > VOLTAGE_HIGH for r in recent)
    if was_hot or spike:
        sign = "it was running hot" if was_hot else "the meter saw a voltage spike"
        return "tripped", (
            f"Silent since {since} and not helping the home. Just before, {sign}. "
            f"Likely its safety switch tripped; it may need a remote or on-site reset."
        )

    # Rules S3 and S4 look back over the whole time it's been silent. Right now the
    # fleet (or this battery) may just be resting, so "doing nothing" this minute proves little.
    worked = None       # latest moment the meter showed this battery moving power
    busy_idle = None    # latest moment the fleet was busy but this battery did nothing
    # Its last reported charge tells us what it *should* have been able to do:
    # a full battery won't charge and an empty one won't discharge, so neither is suspicious.
    last_charge = last["charge_pct"] if last is not None else 50
    for r in reversed(history):
        if last is not None and r["time"] <= last["time"]:
            break                             # only look at the silent stretch
        kw = r["home_usage_kw"] - r["from_grid_kw"]
        fleet_kw = fleet_kw_by_time[r["time"]]
        should_be_busy = (fleet_kw > FLEET_ACTIVE_KW and last_charge > NEARLY_EMPTY_PCT) or \
                         (fleet_kw < -FLEET_ACTIVE_KW and last_charge < NEARLY_FULL_PCT)
        if abs(kw) > METER_TOLERANCE_KW and worked is None:
            worked = (r, kw)
        elif should_be_busy and busy_idle is None:
            busy_idle = r

    # Rule S3 - JUST NOT TALKING (earlier proof): at some point since it went quiet,
    # the meter showed it working. If it's idle now, it's most likely just empty or resting.
    if worked is not None:
        r, kw = worked
        return "just not talking", (
            f"Silent since {since}. At {r['time'][11:]} the meter showed this battery moving "
            f"{abs(kw):.1f} kW. It's working; only its messages are lost."
        )

    # Rule S4 - BROKEN: the fleet was busy, but this battery never did anything since it
    # went quiet, and there was no warning sign before. Something has failed.
    if busy_idle is not None:
        then = busy_idle["time"][11:]
        return "broken", (
            f"Silent since {since}. At {then}, other batteries averaged "
            f"{fleet_kw_by_time[busy_idle['time']]:.1f} kW, but this home pulled all "
            f"{busy_idle['home_usage_kw']:.1f} kW from the grid. It hasn't done anything since it "
            f"went quiet and gave no warning first, so it has probably failed."
        )

    # Rule S5 - CAN'T TELL YET: the fleet hasn't been busy since it went quiet, so there's
    # been no moment to prove it's working or not. We'll know when batteries are next active.
    return "can't tell yet", (
        f"Silent since {since}. Nothing it was expected to do since then would show "
        f"whether it's working. Check again when batteries are active."
    )


# ---------------------------------------------------------------------------
# The main sorting rules (checked in order; the first one that matches wins)
# ---------------------------------------------------------------------------
def classify(row, history, fleet_kw_by_time):
    """Return (category, reason, silent_guess) for one battery at one moment."""
    stress = row["zone_stress"]                         # how strained this home's zone is
    critical = row["priority"] == "critical"
    home = row["description"].split(" (")[0].lower()   # "medical equipment at home"

    # Rule 1 - The battery says it TRIPPED. It's off and the home is back on the grid.
    # Someone has to decide whether it's safe to reset it.
    if row["battery_status"] == "tripped":
        reason = (f"Battery reports it tripped (safety switch off). "
                  f"Home now pulls {row['from_grid_kw']:.1f} kW from the grid.")
        if critical:
            reason += f" Critical home ({home}): check this first."
        return NEEDS_DISPATCHER, reason, None

    # Rule 2 - The battery is SILENT. Use the meter to guess why (see guess_silent).
    # Broken or tripped means it isn't helping, so a person needs to act.
    # "Just not talking" or "can't tell yet" only needs watching.
    if not row["battery_reporting"]:
        guess, reason = guess_silent(row, history, fleet_kw_by_time)
        if guess in ("broken", "tripped"):
            if critical:
                reason += f" Critical home ({home})."
            return NEEDS_DISPATCHER, reason, guess
        return WATCH, reason, guess

    # Rule 3 - Running HOT. Hot batteries can trip. At a critical home that would cut
    # backup power where it matters most, so a person should step in before it happens.
    if row["inverter_temp_c"] >= HOT_C:
        reason = f"Inverter is {row['inverter_temp_c']:.0f}°C (limit {HOT_C}°C) and may trip soon."
        if critical:
            return NEEDS_DISPATCHER, reason + f" Critical home ({home}): consider easing its load.", None
        return WATCH, reason, None

    # Rule 4 - A CRITICAL home's battery is getting LOW. If its zone is also strained,
    # this home could lose its backup right when it's needed, so ask a person.
    if critical and row["charge_pct"] < LOW_CHARGE_PCT:
        reason = f"Backup down to {row['charge_pct']:.0f}% at a critical home ({home})."
        if stress >= STRAINED_GRID:
            return NEEDS_DISPATCHER, reason + f" {row['zone']} is strained ({stress:.0f}% of capacity).", None
        return WATCH, reason, None

    # Rule 5 - Odd VOLTAGE at the home. Not an emergency, but often comes before trouble.
    if not VOLTAGE_LOW <= row["voltage"] <= VOLTAGE_HIGH:
        return WATCH, f"Home voltage is {row['voltage']:.0f} V (normal is about 240 V).", None

    # Rule 6 - CAN WAIT: healthy battery, flexible home, busy zone. This home's extra
    # load (EV charging, pool pump) can be paused before anyone talks about shedding.
    if row["priority"] == "flexible" and stress >= BUSY_GRID:
        return CAN_WAIT, (
            f"{row['zone']} is busy ({stress:.0f}% of capacity). This home's EV charger and "
            f"pool pump can be paused. First in line to wait."
        ), None

    # Rule 7 - Nothing above matched: all good.
    return NORMAL, "Reporting normally.", None


# ---------------------------------------------------------------------------
# Run the rules on the whole fleet
# ---------------------------------------------------------------------------
def triage(readings, at_time):
    """
    Sort every battery at the given time (e.g. "2026-10-17 16:30").
    Returns one dict per battery with its category, reason and wait order.
    """
    # Each battery's readings from the start of the day up to now
    history = {}
    for r in readings:
        if r["time"] <= at_time:
            history.setdefault(r["battery_id"], []).append(r)

    now_rows = [h[-1] for h in history.values()]

    # What healthy batteries were doing on average at each moment (used to judge silent ones)
    kw_at = {}
    for r in readings:
        if r["time"] <= at_time and r["battery_reporting"]:
            kw_at.setdefault(r["time"], []).append(r["battery_kw"])
    fleet_kw_by_time = {t: sum(kws) / len(kws) for t, kws in kw_at.items()}

    results = []
    for row in now_rows:
        category, reason, guess = classify(row, history[row["battery_id"]], fleet_kw_by_time)
        order, order_label = wait_order(row)
        results.append({
            "battery_id": row["battery_id"],
            "household_type": row["household_type"],
            "priority": row["priority"],
            "category": category,
            "reason": reason,
            "silent_guess": guess,
            "battery_status": row["battery_status"],
            "zone": row["zone"],
            "wait_order": order,
            "wait_label": order_label,
        })
    return results


def waiting_list(results):
    """Homes in the order their power can wait: flexible first, critical last.
    Batteries already needing the dispatcher are left out (they're being handled)."""
    ok = [r for r in results if r["category"] != NEEDS_DISPATCHER]
    return sorted(ok, key=lambda r: (r["wait_order"], r["battery_id"]))


# ---------------------------------------------------------------------------
# Relief plan: gentler steps to try BEFORE shedding load, one zone at a time
# ---------------------------------------------------------------------------
# When a zone is strained, the plan suggests these steps for that zone only,
# gentlest first:
#   1. Pause battery charging            (nobody notices)
#   2. Batteries discharge to help       (nobody notices; batteries keep a reserve)
#   3. Flexible homes delay usage        (EV and pool wait a bit)
#   4. Shed regular homes                (EV/pool homes first, then street blocks of the
#                                         zone's other customers: homes without our batteries)
#   5. Shed vulnerable homes             (elderly / heat-vulnerable; very late)
#   6. Critical buildings run on backup  (hospital, fire station; protected last)
# Medical homes are never on any list. The most strained zone is handled first.
# Each step says how many kW it frees, and the plan only goes as far as it has to.
# Nothing happens until the dispatcher approves it in the dashboard.

TARGET_STRESS = 78         # aim to bring a strained zone back just under the strained line (80%)
BLOCK_KW = 25              # cutting one street block of other customers frees about this much
HOMES_PER_BLOCK = 10       # ...and turns off about this many homes
RESERVE_PCT = 20           # every battery keeps at least this much for its own home
SUPPORT_HOURS = 1          # extra discharge has to be something the battery can keep up this long


def stress_after(load_kw, capacity_kw, kw_freed):
    """Zone stress (% of capacity) after freeing this many kW."""
    return max(0.0, 100 * (load_kw - kw_freed) / capacity_kw)


def shed_list(rows, gap, extra, household_type):
    """Pick homes of one household type to cut, lowest priority first, until `gap` kW is covered."""
    order = sorted([r for r in rows if r["household_type"] == household_type],
                   key=lambda r: (wait_order(r)[0], r["battery_id"]))
    picked, kw = [], 0.0
    for r in order:
        if kw >= gap:
            break
        # What cutting this home saves, after the earlier steps already helped
        saves = r["from_grid_kw"] - r["flexible_kw"] - extra.get(r["battery_id"], 0)
        if saves > 0.1:
            picked.append(r)
            kw += saves
    return picked, kw


def relief_plan(readings, at_time, zone):
    """
    The relief plan for one zone. Returns None if the zone isn't strained, otherwise:
        zone, stress, load_kw, capacity_kw, needed_kw, steps (gentlest first), shortfall_kw
    """
    rows = [r for r in readings if r["time"] == at_time and r["zone"] == zone]
    stress, load, capacity = rows[0]["zone_stress"], rows[0]["zone_load_kw"], rows[0]["zone_capacity_kw"]
    if stress < STRAINED_GRID:
        return None

    needed = load - capacity * TARGET_STRESS / 100     # kW to free to get back to the target

    # Only batteries that are talking and healthy get commands.
    # (Silent, tripped or hot batteries are already on the alerts list.)
    healthy = [r for r in rows if r["battery_reporting"] and r["battery_status"] == "ok"]

    # Step 1 - PAUSE CHARGING: any battery in the zone pulling power to charge stops.
    charging = [r for r in healthy if r["battery_kw"] < 0]
    step1_kw = sum(-r["battery_kw"] for r in charging)

    # Step 2 - DISCHARGE TO SUPPORT THE ZONE: healthy batteries push out more power.
    # Medical and vulnerable homes are left alone (their charge is their backup), every
    # battery keeps RESERVE_PCT, and the extra must last SUPPORT_HOURS.
    extra = {}
    for r in healthy:
        if r["priority"] == "critical":
            continue
        spare_kwh = (r["charge_pct"] - RESERVE_PCT) / 100 * simulator.BATTERY_CAPACITY_KWH
        can_keep_up_kw = min(simulator.BATTERY_MAX_KW, spare_kwh / SUPPORT_HOURS)
        more = can_keep_up_kw - max(r["battery_kw"], 0)
        if more > 0.1:
            extra[r["battery_id"]] = more
    step2_kw = sum(extra.values())

    # Step 3 - FLEXIBLE HOMES DELAY USAGE: pause EV charging and pool pumps, nudge
    # smart thermostats. Inconvenient but harmless; they catch up later.
    flexible = [r for r in rows if r["flexible_kw"] > 0]
    step3_kw = sum(r["flexible_kw"] for r in flexible)

    # Steps 4 and 5 - SHED HOMES: only whatever gap is left. Regular homes first
    # (EV/pool homes before the rest), vulnerable homes only if that isn't enough.
    gap = needed - step1_kw - step2_kw - step3_kw
    shed4, step4_kw = shed_list(rows, gap, extra, "regular")
    # ...then whole street blocks of the zone's other customers (homes without our
    # batteries), about BLOCK_KW each, until the gap is covered.
    heat = rows[0]["heat_wave"]
    buildings_kw = sum(simulator.building_load_kw(b, heat) for b in simulator.critical_buildings()
                       if b["zone"] == zone)
    other_kw = load - sum(r["from_grid_kw"] for r in rows) - buildings_kw
    blocks = 0
    while step4_kw < gap and (blocks + 1) * BLOCK_KW <= other_kw:
        blocks += 1
        step4_kw += BLOCK_KW
    shed5, step5_kw = shed_list(rows, gap - step4_kw, extra, "vulnerable")

    # Step 6 - CRITICAL BUILDINGS RUN ON BACKUP: protected last. Buildings with their own
    # backup (diesel, battery) switch to it for a while; nobody loses power. Most backup first.
    gap6 = gap - step4_kw - step5_kw
    on_backup, step6_kw = [], 0.0
    buildings = sorted((b for b in simulator.critical_buildings() if b["zone"] == zone and b["backup_hours"] > 0),
                       key=lambda b: -b["backup_hours"])
    for b in buildings:
        if step6_kw >= gap6:
            break
        on_backup.append(b)
        step6_kw += simulator.building_load_kw(b, heat)

    steps = [
        {"number": 1, "title": "Pause battery charging",
         "action": f"Tell {len(charging)} charging batteries to stop pulling power from the grid.",
         "impact": "Nobody notices. Batteries just fill up a little later.",
         "kw": step1_kw, "targets": [r["battery_id"] for r in charging],
         "nothing_to_do": "no batteries are charging."},
        {"number": 2, "title": "Batteries discharge to support the zone",
         "action": f"Ask {len(extra)} batteries to push out more power for the next {SUPPORT_HOURS} hour.",
         "impact": f"Nobody notices. Medical and vulnerable homes keep their batteries, and every "
                   f"battery keeps at least {RESERVE_PCT}% for its own home.",
         "kw": step2_kw, "targets": sorted(extra),
         "nothing_to_do": "batteries are already giving all they can spare."},
        {"number": 3, "title": "Ask flexible homes to delay usage",
         "action": f"Ask {len(flexible)} flexible homes to pause EV charging and pool pumps "
                   f"and nudge their thermostat.",
         "impact": "Small inconvenience. They catch up later in the evening.",
         "kw": step3_kw, "targets": [r["battery_id"] for r in flexible],
         "nothing_to_do": "no flexible load is running."},
        {"number": 4, "title": "Shed regular homes",
         "action": (f"Cut power to {len(shed4)} regular fleet homes (EV/pool first)"
                    + (f" and {blocks} street block{'s' if blocks != 1 else ''} of other homes "
                       f"(about {blocks * HOMES_PER_BLOCK} homes)" if blocks else "") + "."),
         "impact": "These homes lose power for a while. Vulnerable and medical homes are not on this list.",
         "kw": step4_kw,
         "targets": [r["battery_id"] for r in shed4]
                    + [f"Street block {n} (other customers)" for n in range(1, blocks + 1)],
         "nothing_to_do": "the steps above are enough, or cutting homes wouldn't help."},
        {"number": 5, "title": "Shed vulnerable homes",
         "action": f"Cut power to {len(shed5)} elderly / heat-vulnerable homes.",
         "impact": "Serious: call these residents first. Medical homes are never on this list.",
         "kw": step5_kw, "targets": [r["battery_id"] for r in shed5],
         "nothing_to_do": "not needed, or it wouldn't help."},
        {"number": 6, "title": "Critical buildings switch to backup power",
         "action": f"Ask {len(on_backup)} critical buildings to run on their own backup for a while.",
         "impact": "Nobody loses power, but it uses up their emergency backup. Protected last.",
         "kw": step6_kw,
         "targets": [f"{b['name']} ({b['backup'].lower()}, {b['backup_hours']} h)" for b in on_backup],
         "nothing_to_do": "not needed, or no building here has its own backup."},
    ]

    # For each step: is it still needed after the steps before it?
    freed = 0.0
    for s in steps:
        s["needed"] = freed < needed and s["kw"] > 0
        freed += s["kw"]
        s["stress_after"] = stress_after(load, capacity, freed)

    # If all the steps together still fall short, say so honestly
    return {"zone": zone, "stress": stress, "load_kw": load, "capacity_kw": capacity,
            "needed_kw": needed, "steps": steps, "shortfall_kw": max(0.0, needed - freed)}


def relief_plans(readings, at_time):
    """Relief plans for every strained zone, most strained first (handle that one first)."""
    plans = [relief_plan(readings, at_time, zone) for zone in simulator.ZONES]
    return sorted([p for p in plans if p], key=lambda p: -p["stress"])


# ---------------------------------------------------------------------------
# Dispatcher summary: three plain-English lines for the top of the dashboard
# ---------------------------------------------------------------------------
LOOKAHEAD_HOURS = 4   # how far ahead the grid forecast looks


def clock(t):
    """'2026-10-17 16:30' -> '4:30 PM'"""
    h, m = int(t[11:13]), t[14:16]
    return f"{h % 12 or 12}{'' if m == '00' else ':' + m} {'AM' if h < 12 else 'PM'}"


def plural(n, word):
    """plural(1, 'battery') -> '1 battery', plural(3, 'battery') -> '3 batteries'"""
    if n == 1:
        return f"1 {word}"
    return f"{n} {word[:-1] + 'ies' if word.endswith('y') else word + 's'}"


def problem_and_action(r):
    """For a battery that needs the dispatcher: (kind, short problem, what to do about it).
    kind is a number used to put the worst problems first: 0 tripped, 1 broken, 2 hot, 3 low backup."""
    who = f"{r['battery_id']} ({r['household_type'].replace('_', ' ')} home)"
    # Tripped: the safety switch is off; check why before switching it back on
    if r["battery_status"] == "tripped" or r["silent_guess"] == "tripped":
        return 0, f"{r['battery_id']} tripped", f"check {who} is safe, then reset it remotely"
    # Broken: nothing can be done remotely, someone has to go there
    if r["silent_guess"] == "broken":
        return 1, f"{r['battery_id']} probably broken", f"send a technician to {who}"
    # Hot: take load off it before it trips
    if r["battery_status"] == "warning_hot":
        return 2, f"{r['battery_id']} running hot", f"ease the load on {who} before it trips"
    # Otherwise it's a critical home with low backup
    return 3, f"{r['battery_id']} low backup", f"check on {who}: its backup is running low"


def summary(readings, at_time, results, approved_steps=()):
    """
    Three short lines for the dispatcher:
        status  - how many batteries need attention, and why
        outlook - what the grid is doing now and over the next few hours
        action  - what to do first
    approved_steps: (zone, step number) pairs already approved at this time.
    """
    # --- Status: count and name the urgent batteries ---
    needs = sorted([r for r in results if r["category"] == NEEDS_DISPATCHER],
                   key=lambda r: (problem_and_action(r)[0], -r["wait_order"], r["battery_id"]))  # worst first
    watch = [r for r in results if r["category"] == WATCH]
    # Several critical homes low on backup get grouped into one item, to keep it short
    low = [r for r in needs if problem_and_action(r)[0] == 3]
    single = [r for r in needs if problem_and_action(r)[0] < 3 or len(low) < 3]
    if needs:
        items = [problem_and_action(r)[1] for r in single]
        if len(low) >= 3:
            items.append(f"{len(low)} critical homes low on backup")
        what = ", ".join(items)
        status = (f"**{plural(len(needs), 'battery')} need{'s' if len(needs) == 1 else ''} "
                  f"attention** ({what})")
        status += f", plus {len(watch)} to watch." if watch else "."
    elif watch:
        status = f"Nothing urgent. {plural(len(watch), 'battery')} to watch."
    else:
        status = f"All {len(results)} batteries are working normally."

    # --- Outlook: use the grid forecast for the next few hours ---
    # (In the simulator we know the rest of the day; a real dispatcher gets this from
    # the utility's load forecast.)
    # Each zone's stress over the day: {zone: {time: stress}}
    stress_at = {}
    for r in readings:
        stress_at.setdefault(r["zone"], {})[r["time"]] = r["zone_stress"]
    times = sorted(next(iter(stress_at.values())))
    i = times.index(at_time)
    ahead = times[i + 1: i + 1 + LOOKAHEAD_HOURS * 60 // simulator.STEP_MINUTES]

    strained = sorted([z for z in stress_at if stress_at[z][at_time] >= STRAINED_GRID],
                      key=lambda z: -stress_at[z][at_time])         # most strained first
    # Zones that aren't strained yet but will be soon: {zone: first strained time}
    coming = {}
    for z in stress_at:
        if z not in strained:
            t = next((t for t in ahead if stress_at[z][t] >= STRAINED_GRID), None)
            if t:
                coming[z] = t

    if strained:
        listed = ", ".join(f"{z} ({stress_at[z][at_time]:.0f}% of capacity)" for z in strained)
        outlook = f"**{plural(len(strained), 'zone')} strained now:** {listed}."
        eases = next((t for t in times[i + 1:]
                      if all(stress_at[z][t] < STRAINED_GRID for z in stress_at)), None)
        if coming:
            z, t = min(coming.items(), key=lambda kv: kv[1])
            outlook += f" {z} expected to join at {clock(t)}."
        outlook += f" Expected to ease around {clock(eases)}." if eases else " Strain lasts the rest of the day."
    elif coming:
        z, t = min(coming.items(), key=lambda kv: kv[1])
        peak = max(stress_at[z][t2] for t2 in ahead)
        outlook = f"**{z} expected to be strained at {clock(t)}** (up to {peak:.0f}% of capacity)."
        if len(coming) > 1:
            outlook += f" {len(coming) - 1} more zone{'s' if len(coming) > 2 else ''} later."
    else:
        outlook = f"All zones look calm for the next {LOOKAHEAD_HOURS} hours."

    # --- Action: strained zones first (most strained first), then the urgent batteries ---
    actions = []
    for plan in relief_plans(readings, at_time)[:2]:
        z = plan["zone"]
        todo = [s for s in plan["steps"] if s["needed"] and (z, s["number"]) not in approved_steps]
        if todo:
            s = todo[0]
            text = f"in {z}, approve step {s['number']}: {s['title'].lower()} (frees about {s['kw']:.0f} kW)"
            cuts_needed = any(st["needed"] for st in plan["steps"][3:5])
            if s["number"] < 4:
                text += "; homes may still need cutting after that" if cuts_needed else "; nobody needs to lose power"
            actions.append(text)
        elif plan["shortfall_kw"] > 0:
            actions.append(f"in {z}, all steps approved but still {plan['shortfall_kw']:.0f} kW short; escalate to the utility")
        else:
            actions.append(f"in {z}, relief steps approved; keep an eye on it")
    if not strained and coming:
        z, t = min(coming.items(), key=lambda kv: kv[1])
        actions.append(f"let batteries in {z} finish charging before {clock(t)} so they're full when the strain hits")

    singles = [r for r in single if r not in low or len(low) < 3]
    actions += [problem_and_action(r)[2] for r in singles[:2]]
    if len(low) >= 3:
        actions.append(f"check on the {len(low)} critical homes low on backup "
                       f"({', '.join(r['battery_id'] for r in low)})")
    if len(singles) > 2:
        actions.append(f"then the other {len(singles) - 2} on the alerts list")

    if actions:
        action = "**Recommended:** " + " ".join(f"{n}) {a[0].upper() + a[1:]}." for n, a in enumerate(actions, 1))
    else:
        action = "**Recommended:** nothing right now. Batteries are earning on their normal schedule."

    level = "error" if needs or strained else "warning" if watch or coming else "ok"
    return {"status": status, "outlook": outlook, "action": action, "level": level}


# ---------------------------------------------------------------------------
# Run directly: show what the rules say at a few moments in the day
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    data = simulator.simulate()

    for t in ["2026-10-17 12:00", "2026-10-17 13:30", "2026-10-17 15:30",
              "2026-10-17 16:30", "2026-10-17 21:00"]:
        results = triage(data, t)
        counts = {c: 0 for c in (NEEDS_DISPATCHER, WATCH, CAN_WAIT, NORMAL)}
        for r in results:
            counts[r["category"]] += 1
        print(f"=== {t[11:]} === " + ", ".join(f"{k}: {v}" for k, v in counts.items()))
        for r in results:
            if r["category"] in (NEEDS_DISPATCHER, WATCH):
                guess = f" [{r['silent_guess']}]" if r["silent_guess"] else ""
                print(f"  {r['category']:<17} {r['battery_id']} ({r['household_type']}){guess}: {r['reason']}")
        print()
