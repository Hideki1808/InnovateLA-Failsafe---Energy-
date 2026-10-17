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
BUSY_GRID = 60             # grid stress at or above this: flexible homes should wait
STRAINED_GRID = 80         # grid stress at or above this: the grid is close to shedding load
VOLTAGE_LOW, VOLTAGE_HIGH = 225, 255   # normal home voltage is about 240
METER_TOLERANCE_KW = 0.3   # differences smaller than this are just noise
FLEET_ACTIVE_KW = 1.0      # if healthy batteries average more than this, the fleet is "busy"
LOOKBACK_STEPS = 8         # how far back to look for warning signs (8 x 15 min = 2 hours)


# ---------------------------------------------------------------------------
# Whose power can wait
# ---------------------------------------------------------------------------
# Lower number = can wait sooner. Homes with medical equipment, cold storage or a
# cell-phone relay are "critical" and come last.
WAIT_ORDER = {"flexible": 1, "normal": 2, "critical": 3}
WAIT_LABEL = {
    1: "1 - Can wait first (EV charger, pool pump)",
    2: "2 - Can wait if needed (regular household)",
    3: "3 - Protect, wait last (medical, cold storage, phones)",
}


def wait_order(row):
    """Return (number, label) for how early this home's power can wait."""
    number = WAIT_ORDER[row["priority"]]
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
    for r in reversed(history):
        if last is not None and r["time"] <= last["time"]:
            break                             # only look at the silent stretch
        kw = r["home_usage_kw"] - r["from_grid_kw"]
        if abs(kw) > METER_TOLERANCE_KW and worked is None:
            worked = (r, kw)
        elif abs(fleet_kw_by_time[r["time"]]) > FLEET_ACTIVE_KW and busy_idle is None:
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
        f"Silent since {since}. The fleet is resting right now, so we can't tell "
        f"if it's working. Check again when batteries are active."
    )


# ---------------------------------------------------------------------------
# The main sorting rules (checked in order; the first one that matches wins)
# ---------------------------------------------------------------------------
def classify(row, history, fleet_kw_by_time):
    """Return (category, reason, silent_guess) for one battery at one moment."""
    stress = row["grid_stress"]
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

    # Rule 4 - A CRITICAL home's battery is getting LOW. If the grid is also strained,
    # this home could lose its backup right when it's needed, so ask a person.
    if critical and row["charge_pct"] < LOW_CHARGE_PCT:
        reason = f"Backup down to {row['charge_pct']:.0f}% at a critical home ({home})."
        if stress >= STRAINED_GRID:
            return NEEDS_DISPATCHER, reason + f" Grid is strained ({stress:.0f}/100).", None
        return WATCH, reason, None

    # Rule 5 - Odd VOLTAGE at the home. Not an emergency, but often comes before trouble.
    if not VOLTAGE_LOW <= row["voltage"] <= VOLTAGE_HIGH:
        return WATCH, f"Home voltage is {row['voltage']:.0f} V (normal is about 240 V).", None

    # Rule 6 - CAN WAIT: healthy battery, flexible home, busy grid. This home's extra
    # load (EV charging, pool pump) can be paused before anyone talks about shedding.
    if row["priority"] == "flexible" and stress >= BUSY_GRID:
        return CAN_WAIT, (
            f"Grid is busy ({stress:.0f}/100). This home's EV charger and pool pump "
            f"can be paused. First in line to wait."
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
            "home_type": row["home_type"],
            "priority": row["priority"],
            "category": category,
            "reason": reason,
            "silent_guess": guess,
            "battery_status": row["battery_status"],
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
# Relief plan: gentler steps to try BEFORE shedding load
# ---------------------------------------------------------------------------
# When the grid is strained, the plan suggests four steps, gentlest first:
#   1. Pause battery charging         (nobody notices)
#   2. Batteries discharge to help    (nobody notices; batteries keep a reserve)
#   3. Flexible homes delay usage     (EV and pool wait a bit)
#   4. Shed lowest-priority homes     (people lose power; last resort)
# Each step says how many kW it frees. The plan only goes as far as it has to.
# Nothing happens until the dispatcher approves it in the dashboard.

TARGET_STRESS = 75         # aim to bring grid stress back down to this
KW_PER_STRESS_POINT = 4    # simple model: every 4 kW the fleet frees lowers grid stress by 1 point
RESERVE_PCT = 20           # every battery keeps at least this much for its own home
SUPPORT_HOURS = 1          # extra discharge has to be something the battery can keep up this long


def stress_after(stress, kw_freed):
    """Estimated grid stress after freeing this many kW."""
    return max(0, stress - kw_freed / KW_PER_STRESS_POINT)


def relief_plan(readings, at_time):
    """
    Returns None if the grid is fine. Otherwise returns a dict:
        stress, needed_kw, steps (list of 4 dicts, gentlest first)
    """
    now_rows = [r for r in readings if r["time"] == at_time]
    stress = now_rows[0]["grid_stress"]

    # The plan only appears when the grid is strained (same line as Rule 4 uses)
    if stress < STRAINED_GRID:
        return None

    needed = (stress - TARGET_STRESS) * KW_PER_STRESS_POINT

    # Only batteries that are talking and healthy get commands.
    # (Silent, tripped or hot batteries are already on the alerts list.)
    healthy = [r for r in now_rows if r["battery_reporting"] and r["battery_status"] == "ok"]

    # Step 1 - PAUSE CHARGING: any battery pulling power from the grid to charge stops.
    # Gentlest step: the batteries just fill up a little later.
    charging = [r for r in healthy if r["battery_kw"] < 0]
    step1_kw = sum(-r["battery_kw"] for r in charging)

    # Step 2 - DISCHARGE TO SUPPORT THE GRID: healthy batteries push out more power.
    # Rules: critical homes are left alone (their charge is their backup), every battery
    # keeps RESERVE_PCT, and the extra must last SUPPORT_HOURS so we don't run them dry.
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
    flexible = [r for r in now_rows if r["flexible_kw"] > 0]
    step3_kw = sum(r["flexible_kw"] for r in flexible)

    # Step 4 - SHED LOWEST-PRIORITY HOMES: only whatever gap is left after steps 1-3.
    # Order: flexible homes first, then regular households. Critical homes are NEVER shed.
    gap = needed - step1_kw - step2_kw - step3_kw
    order = sorted(
        [r for r in now_rows if r["priority"] != "critical"],
        key=lambda r: (WAIT_ORDER[r["priority"]], r["battery_id"]),
    )
    shed, step4_kw = [], 0.0
    for r in order:
        if step4_kw >= gap:
            break
        # What cutting this home saves, after the earlier steps already helped
        saves = r["from_grid_kw"] - r["flexible_kw"] - extra.get(r["battery_id"], 0)
        if saves > 0.1:
            shed.append(r)
            step4_kw += saves

    steps = [
        {
            "number": 1,
            "title": "Pause battery charging",
            "action": f"Tell {len(charging)} charging batteries to stop pulling power from the grid.",
            "impact": "Nobody notices. Batteries just fill up a little later.",
            "kw": step1_kw,
            "targets": [r["battery_id"] for r in charging],
            "nothing_to_do": "no batteries are charging.",
        },
        {
            "number": 2,
            "title": "Batteries discharge to support the grid",
            "action": f"Ask {len(extra)} batteries to push out more power for the next {SUPPORT_HOURS} hour.",
            "impact": f"Nobody notices. Critical homes are left alone, and every battery keeps "
                      f"at least {RESERVE_PCT}% for its own home.",
            "kw": step2_kw,
            "targets": sorted(extra),
            "nothing_to_do": "batteries are already giving all they can spare.",
        },
        {
            "number": 3,
            "title": "Ask flexible homes to delay usage",
            "action": f"Ask {len(flexible)} flexible homes to pause EV charging and pool pumps "
                      f"and nudge their thermostat.",
            "impact": "Small inconvenience. They catch up later in the evening.",
            "kw": step3_kw,
            "targets": [r["battery_id"] for r in flexible],
            "nothing_to_do": "no flexible load is running.",
        },
        {
            "number": 4,
            "title": "Shed lowest-priority homes",
            "action": f"Cut power to {len(shed)} homes, lowest priority first." if shed
                      else "Cut power to the lowest-priority homes.",
            "impact": "These homes lose power. Critical homes (medical, cold storage, phones) "
                      "are never on this list.",
            "kw": step4_kw,
            "targets": [r["battery_id"] for r in shed],
            "nothing_to_do": "the steps above are enough, or shedding wouldn't help.",
        },
    ]

    # For each step: is it still needed after the steps before it?
    freed = 0.0
    for s in steps:
        s["needed"] = freed < needed and s["kw"] > 0
        freed += s["kw"]
        s["kw_so_far"] = freed
        s["stress_after"] = stress_after(stress, freed)

    # If all four steps together still fall short, say so honestly
    shortfall = max(0.0, needed - freed)
    return {"stress": stress, "needed_kw": needed, "steps": steps, "shortfall_kw": shortfall}


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
    who = f"{r['battery_id']} ({r['home_type'].replace('_', ' ')} home)"
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
    approved_steps: relief plan step numbers already approved at this time.
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
    stress_at = {}
    for r in readings:
        stress_at.setdefault(r["time"], r["grid_stress"])
    times = sorted(stress_at)
    i = times.index(at_time)
    ahead = times[i + 1: i + 1 + LOOKAHEAD_HOURS * 60 // simulator.STEP_MINUTES]
    now_stress = stress_at[at_time]
    strained_now = now_stress >= STRAINED_GRID
    coming = next((t for t in ahead if stress_at[t] >= STRAINED_GRID), None)

    if strained_now:
        eases = next((t for t in times[i + 1:] if stress_at[t] < STRAINED_GRID), None)
        outlook = f"Grid is **strained now** ({now_stress:.0f}/100)"
        outlook += (f", expected to ease around {clock(eases)}." if eases
                    else " for the rest of the day.")
    elif coming:
        peak = max(stress_at[t] for t in ahead)
        outlook = (f"**Heat wave expected at {clock(coming)}.** Grid stress will climb to "
                   f"about {peak:.0f}/100.")
    else:
        outlook = f"Grid looks calm for the next {LOOKAHEAD_HOURS} hours."

    # --- Action: grid first (it affects everyone), then the urgent batteries ---
    actions = []
    if strained_now:
        plan = relief_plan(readings, at_time)
        todo = [s for s in plan["steps"] if s["needed"] and s["number"] not in approved_steps]
        if todo:
            s = todo[0]
            text = f"approve relief step {s['number']}, {s['title'].lower()} (frees about {s['kw']:.0f} kW)"
            shed_needed = plan["steps"][3]["needed"]
            if s["number"] < 4:
                text += "; shedding may still be needed after that" if shed_needed else "; nobody needs to lose power"
            actions.append(text)
        elif plan["shortfall_kw"] > 0:
            actions.append(f"relief steps approved but still {plan['shortfall_kw']:.0f} kW short; escalate to the utility")
        else:
            actions.append("relief steps approved; keep an eye on grid stress")
    elif coming:
        actions.append(f"let batteries finish charging before {clock(coming)} so they're full when the heat hits")

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

    level = "error" if needs or strained_now else "warning" if watch or coming else "ok"
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
                print(f"  {r['category']:<17} {r['battery_id']} ({r['home_type']}){guess}: {r['reason']}")
        print()
