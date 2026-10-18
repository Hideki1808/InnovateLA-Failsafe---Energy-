"""
app.py - the dispatcher's dashboard.

Run it with:
    streamlit run app.py
"""

import random
import time

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

import crisis
import rules
import map_gestures
import simulator
import style
import weather

st.set_page_config(page_title="Fleet Dispatcher", layout="wide")
started = time.time()   # used by Play to keep a steady pace

# How each category is written in the table
ICONS = {
    rules.NEEDS_DISPATCHER: "Needs dispatcher",
    rules.WATCH: "Watch",
    rules.CAN_WAIT: "Can wait",
    rules.NORMAL: "Normal",
}
# Most urgent first when sorting the table
SEVERITY = {rules.NEEDS_DISPATCHER: 0, rules.WATCH: 1, rules.CAN_WAIT: 2, rules.NORMAL: 3}


# Make the fake data once per country and remember it (so the page doesn't redo it on
# every click)
@st.cache_data
def load_readings(country_id, month, crisis_settings=None):
    """The simulated day. crisis_settings: the crisis control panel's settings (see
    get_crisis), or None for the normal demo day. From the moment the crisis is started
    it replaces the scripted event; batteries pre-charge during a forecast's warning, and
    dark zones get no grid power (their homes run on their batteries)."""
    simulator.use_country(country_id)
    if crisis_settings is None:
        return simulator.simulate(month=month)
    c, outages = get_crisis(country_id, month, *crisis_settings)
    return simulator.simulate(month=month, crisis=c, outages=outages, crisis_from=c["triggered_at"])


@st.cache_data
def run_rules(country_id, month, crisis_settings, at_time):
    simulator.use_country(country_id)
    return pd.DataFrame(rules.triage(load_readings(country_id, month, crisis_settings), at_time))


# Page look: the theme is in .streamlit/config.toml; style.py adds the few extras
# (section labels, big key numbers, white panels, no grey-out while Play redraws)
st.html(style.CSS)

@st.cache_data
def get_crisis(country_id, month, choice, severity, seed, started, ended, full_on, full_off):
    """
    The crisis and its outages (which zones go dark, when) for the crisis control panel.
      choice: "random" (picked by this month's odds) or a crisis type; severity for a chosen type
      started / ended: hours of the day when "Start crisis" / "End crisis" were pressed
      full_on / full_off: when "Force full blackout" was switched on / off (None = not used)
    Same settings + same seed = exactly the same crisis, so it can be replayed.
    """
    simulator.use_country(country_id)
    if choice == "random":
        c = crisis.pick_random(country_id, month, seed=seed)
    else:
        c = crisis.make_crisis(country_id, month, choice, severity, seed=seed)
    c = crisis.start_at(c, started)
    outages = crisis.blackouts(country_id, c, seed=seed)
    if full_on is not None:
        outages += crisis.full_blackout(country_id, c, full_on, full_off)
    outages = crisis.merge_outages(outages)
    if ended is not None:
        c, outages = crisis.end_at(c, outages, ended)
    return c, outages


def hour_of(t):
    """'2026-10-17 15:45' -> 15.75"""
    return int(t[11:13]) + int(t[14:16]) / 60


def duration(hours):
    """1.25 -> '1 h 15 min', 0.5 -> '30 min'"""
    minutes = int(round(hours * 60))
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if h and m else f"{h} h" if h else f"{m} min"


PULSE_SECONDS = 1.0   # one breath of the ring around "Needs dispatcher" dots


@st.fragment(run_every=PULSE_SECONDS)
def draw_map(below, above, urgent_rows, view, tooltip):
    """
    Draw the map. This little section redraws itself every PULSE_SECONDS (the rest of
    the page doesn't), so the ring around each "Needs dispatcher" dot can grow and fade,
    then shrink back: a gentle pulse that makes urgent homes easy to spot.
    below / above: map layers drawn under / over the pulsing rings.
    """
    beat = st.session_state.get("pulse_beat", 0) + 1
    st.session_state.pulse_beat = beat
    out = beat % 2 == 0                       # every other beat the ring is big and faint
    fade_ms = int(PULSE_SECONDS * 950)
    pulse = pdk.Layer(
        "ScatterplotLayer", urgent_rows, get_position=["lon", "lat"], filled=False, stroked=True,
        get_radius=120 if out else 45, radius_min_pixels=11, radius_max_pixels=34,
        get_line_color=style.rgb(style.CORAL, 30 if out else 230), line_width_min_pixels=3,
        transitions={"getRadius": fade_ms, "getLineColor": fade_ms},
    )
    event = st.pydeck_chart(pdk.Deck(layers=below + [pulse] + above, initial_view_state=view,
                                     map_style="light_no_labels", tooltip=tooltip),
                            # same key every time = update the map in place (also when switching
                            # country: it then moves to the new view, centred). It changes only after
                            # a click, to drop Streamlit's highlight of the clicked shape.
                            height=540, key=f"fleet_map_{st.session_state.get('map_version', 0)}",
                            on_select="rerun", selection_mode="single-object")
    # Clicked a zone, or a home or building in it? Remember the zone and redraw the whole
    # page, so the side panel can list that zone's batteries. The map is then drawn fresh
    # (new key), because Streamlit would otherwise dim everything but the clicked shape.
    picked = [o for objects in event.selection.get("objects", {}).values() for o in objects if o.get("zone")]
    if picked:
        st.session_state.picked_zone = picked[0]["zone"]
        st.session_state.map_version = st.session_state.get("map_version", 0) + 1
        st.rerun()


# --- Country: everything country-specific comes from config/countries.toml ---
st.session_state.setdefault("country", simulator.DEFAULT_COUNTRY)
st.session_state.setdefault("month", simulator.DAY_START.month)   # the demo date's month


def reset_demo():
    """A different country or month starts the demo over: back to noon, nothing approved yet."""
    for key in ("now", "playing", "pause_note", "seen", "approved", "shutoffs", "dark_approved", "next_time", "shown_time",
                "crisis_started", "crisis_ended", "full_on", "full_off", "full_blackout"):
        st.session_state.pop(key, None)


def short_problem(a):
    """A few words on what's wrong with this battery (the full reason shows on hover)."""
    if a["battery_status"] == "tripped":
        return "tripped"
    if pd.notna(a["silent_guess"]):
        return f"silent ({a['silent_guess']})"
    if not a["grid_power"] and a["unserved_kw"] > 0.05:
        return f"no grid · {a['unserved_kw']:.1f} kW unmet"
    if pd.notna(a["inverter_temp_c"]) and a["inverter_temp_c"] >= rules.HOT_C:
        return f"hot · {rules.temp(a['inverter_temp_c'])}"
    low, high = rules.voltage_band()
    if not low <= a["voltage"] <= high:
        return f"{a['voltage']:.0f} V"
    if a["category"] == rules.CAN_WAIT:
        return "can wait · flexible load"
    if pd.notna(a["charge_pct"]) and a["charge_pct"] < rules.LOW_CHARGE_PCT:
        return "low backup"
    return a["reason"].split(".")[0].lower()


CHARGE_COLOR = style.STATE_HEX[rules.CAN_WAIT]   # blue: taking power in
DISCHARGE_COLOR = "#f08a24"                       # orange: giving power out
PRICE_COLOR = style.MUTED                         # neutral gray: the price line
MONEY_COLOR = style.CORAL                         # the accent: the money is the point


@st.cache_data
def load_ordinary_day(country_id, month):
    simulator.use_country(country_id)
    return pd.DataFrame(simulator.simulate(ordinary_day=True, month=month))


@st.cache_data
def demo_day_earnings(country_id, month):
    return sum(r["earnings"] for r in load_readings(country_id, month))


def money(amount, decimals=2):
    """1234.5 -> '$1,234.50' or '€1,234.50', in the country's currency."""
    return f"{CUR}{amount:,.{decimals}f}"


def in_text(s):
    """Streamlit text treats two $ signs as a math formula; escape them so they print."""
    return s.replace("$", "\\$")


def normal_day():
    """The Normal day tab: how the fleet earns money on an ordinary day (no stress event)."""
    simulator.use_country(country_id)
    calm = load_ordinary_day(country_id, month)
    prices = COUNTRY["prices"]
    st.markdown("**Buy cheap** at midday (solar), **use it** at the evening peak.")

    # One row per 15 minutes for the whole fleet
    day = calm.groupby("time", as_index=False).agg(
        price=("price_per_kwh", "first"),
        fleet_kw=("battery_kw", "sum"),
        money=("earnings", "sum"),
    )
    day["clock"] = day["time"].str[11:]
    day["running_total"] = day["money"].cumsum()
    day["what"] = day["fleet_kw"].apply(
        lambda kw: "Charging (buying cheap)" if kw < 0 else "Discharging (using at peak)")
    hours = [c for c in day["clock"] if c.endswith(":00")]
    x = alt.X("clock", title=None, axis=alt.Axis(values=hours, labelAngle=-45))

    # --- Headline numbers ---
    batteries = calm["battery_id"].nunique()
    per_day = day["money"].sum()
    shifted_kwh = (calm["battery_kw"].clip(lower=0) * simulator.STEP_MINUTES / 60).sum()
    st.html(style.stats([
        (money(per_day, 0), "fleet per day", True),
        (money(per_day / batteries), "per battery per day", False),
    ]) + style.stats([
        (money(per_day / batteries * 365, 0), "per battery per year", False),
        (f"{shifted_kwh:,.0f} kWh", "moved to the evening", False),
    ]))

    # --- Chart 1: the price of power through the day ---
    st.html(style.label("1 · The price of power changes through the day"))
    price_line = alt.Chart(day).mark_line(interpolate="step-after", strokeWidth=2, color=PRICE_COLOR).encode(
        x=x,
        y=alt.Y("price", title=f"{CUR} per kWh",
                axis=alt.Axis(labelExpr=f"'{CUR}' + format(datum.value, '.2f')")),
        tooltip=[alt.Tooltip("clock", title="Time"),
                 alt.Tooltip("price", title=f"Price ({CUR}/kWh)", format=".2f")],
    )
    labels = pd.DataFrame([
        {"clock": "12:30", "price": prices["cheap_solar"],
         "text": f"Cheap: {money(prices['cheap_solar'])} (solar)"},
        {"clock": "19:00", "price": prices["evening_peak"], "text": f"Peak: {money(prices['evening_peak'])}"},
    ])
    price_labels = alt.Chart(labels).mark_text(dy=-12, fontSize=13, color=PRICE_COLOR).encode(x="clock", y="price", text="text")
    st.altair_chart(theme=None, altair_chart=style.chart_style(price_line + price_labels, 170), width="stretch")

    # --- Chart 2: what the batteries do about it ---
    st.html(style.label("2 · So batteries charge when it's cheap and discharge at the peak"))
    bars = alt.Chart(day[day["fleet_kw"] != 0]).mark_bar(cornerRadius=4).encode(
        x=x,
        y=alt.Y("fleet_kw", title="Whole fleet, kW"),
        color=alt.Color("what", title=None, legend=alt.Legend(orient="top"),
                        scale=alt.Scale(domain=["Charging (buying cheap)", "Discharging (using at peak)"],
                                        range=[CHARGE_COLOR, DISCHARGE_COLOR])),
        tooltip=[alt.Tooltip("clock", title="Time"), alt.Tooltip("what", title="Doing"),
                 alt.Tooltip("fleet_kw", title="Fleet kW", format=".0f")],
    )
    # Keep every hour on the axis, even when the batteries are resting
    axis_keeper = alt.Chart(day).mark_rule(opacity=0).encode(x=x)
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=PRICE_COLOR).encode(y="y")
    st.altair_chart(theme=None, altair_chart=style.chart_style(axis_keeper + bars + zero, 170), width="stretch")
    st.caption("Below the line: batteries buying power. Above: batteries powering their homes "
               "so the homes don't buy at peak prices.")

    # --- Chart 3: the money adding up ---
    st.html(style.label("3 · Small cost at midday, bigger savings in the evening"))
    money_line = alt.Chart(day).mark_line(strokeWidth=2, color=MONEY_COLOR).encode(
        x=x,
        y=alt.Y("running_total", title=f"Fleet total so far ({CUR})",
                axis=alt.Axis(labelExpr=f"'{CUR}' + format(datum.value, ',.0f')")),
        tooltip=[alt.Tooltip("clock", title="Time"),
                 alt.Tooltip("running_total", title=f"Total so far ({CUR})", format=",.2f")],
    )
    st.altair_chart(theme=None, altair_chart=style.chart_style(money_line, 170), width="stretch")

    # --- The simple math ---
    st.html(style.label("The math"))
    hours_per_step = simulator.STEP_MINUTES / 60
    bought = calm[calm["battery_kw"] < 0]
    used = calm[calm["battery_kw"] > 0]
    bought_kwh = (-bought["battery_kw"] * hours_per_step).sum()
    used_kwh = (used["battery_kw"] * hours_per_step).sum()
    math = pd.DataFrame([
        {"When": "10 am – 3 pm", "Batteries": "Charge", "Energy": f"{bought_kwh:,.0f} kWh",
         "Price": f"{money(-bought['earnings'].sum() / bought_kwh)} / kWh",
         "Money": f"−{money(-bought['earnings'].sum())}"},
        {"When": "5 pm – 9 pm", "Batteries": "Discharge", "Energy": f"{used_kwh:,.0f} kWh",
         "Price": f"{money(used['earnings'].sum() / used_kwh)} / kWh",
         "Money": f"+{money(used['earnings'].sum())}"},
        {"When": "Whole day", "Batteries": "", "Energy": "", "Price": "",
         "Money": f"+{money(per_day)}"},
    ])
    st.dataframe(math, hide_index=True, width="stretch")
    st.caption(
        f"Simulated numbers, kept simple: {batteries} batteries of {simulator.BATTERY_CAPACITY_KWH:.0f} kWh, "
        f"no energy lost when charging, and each battery ends the day about where it started. "
        f"For comparison, on the demo day with the {COUNTRY['stress_event']['name'].lower()} "
        f"the same fleet earned "
        + in_text(f"{money(demo_day_earnings(country_id, month), 0)}, because peak prices hit "
                  f"{money(COUNTRY['stress_event']['peak_price'])} / kWh.")
        + " All prices are approximate (see config/countries.toml)."
    )


# ===========================================================================
# The page, top to bottom:
#   top bar (country, month, Play/time, crisis controls) · status bar · 4 key numbers ·
#   big map (left) + tabs Alerts / Relief plan / Outage zone / Normal day (right) ·
#   more details (folded) · footer with data sources and credits
# ===========================================================================
DEMO_START = "2026-10-17 12:00"        # calm before the stress event
SPEEDS = {"Slow": 2.0, "Normal": 1.0, "Fast": 0.4}   # seconds per 15-minute step
SIDE_TABS = ["Alerts", "Relief plan", "Outage zone", "Normal day"]

# --- Remembered between clicks ---
st.session_state.setdefault("crisis_choice", "random")
st.session_state.setdefault("crisis_severity", 4)
st.session_state.setdefault("crisis_seed", 42)
st.session_state.setdefault("crisis_started", None)    # time "Start crisis" was pressed
st.session_state.setdefault("crisis_ended", None)      # time "End crisis" was pressed
st.session_state.setdefault("full_on", None)           # time the full blackout was switched on
st.session_state.setdefault("full_off", None)          # ... and off
st.session_state.setdefault("dark_approved", set())   # approved outage-zone steps: (zone, start, step)
st.session_state.setdefault("approved", set())        # approved relief steps: (time, zone, step)
st.session_state.setdefault("shutoffs", {})           # approved wildfire shutoffs: {zone: (from, until)}
st.session_state.setdefault("now", DEMO_START)
st.session_state.setdefault("playing", False)
st.session_state.setdefault("pause_note", None)
st.session_state.setdefault("seen", set())            # events already announced


# --- Button actions ---
def time_on_screen():
    """The time the dashboard is showing. (While playing, the slider's own value can lag
    behind, so the page remembers what it last drew, or what it's about to draw next.)"""
    return (st.session_state.get("next_time") or st.session_state.get("shown_time")
            or st.session_state.now)


def clear_crisis():
    for key in ("crisis_started", "crisis_ended", "full_on", "full_off"):
        st.session_state[key] = None
    st.session_state.full_blackout = False
    st.session_state.dark_approved = set()


def start_crisis():
    """Start the chosen crisis now (the time on screen). Play keeps going."""
    clear_crisis()
    st.session_state.crisis_started = time_on_screen()
    st.session_state.pause_note = None


def end_crisis():
    """End it now: the crisis stops and power comes back everywhere."""
    st.session_state.crisis_ended = time_on_screen()
    st.session_state.full_blackout = False


def toggle_full_blackout():
    if st.session_state.full_blackout:
        st.session_state.full_on, st.session_state.full_off = hour_of(time_on_screen()), None
    else:
        st.session_state.full_off = hour_of(time_on_screen())


def reroll():
    """A new random seed: a new outcome (a different crisis or different dark zones)."""
    st.session_state.crisis_seed = random.randint(1, 99_999)
    st.session_state.seen = set()
    st.session_state.dark_approved = set()


def toggle_play():
    st.session_state.playing = not st.session_state.playing
    st.session_state.pause_note = None


def jump_to(t):
    st.session_state.playing = False
    st.session_state.pause_note = None
    st.session_state.seen = set()
    st.session_state.now = t
    clear_crisis()                           # back to the normal day


def step_forward():
    i = times.index(st.session_state.now)
    st.session_state.now = times[min(i + 1, len(times) - 1)]


def approve(key):
    st.session_state.approved.add(key)


def approve_dark(key):
    st.session_state.dark_approved.add(key)


def approve_shutoff(zone, start, until):
    st.session_state.shutoffs[zone] = (start, until)


def reset_approvals():
    st.session_state.approved = set()
    st.session_state.shutoffs = {}
    st.session_state.dark_approved = set()


# --- The day: country, crisis and the simulated readings ---
country_id = st.session_state.country
month = st.session_state.month
simulator.use_country(country_id)          # rules.py and simulator.py now use this country
COUNTRY = simulator.COUNTRY
CUR = COUNTRY["currency"]                  # e.g. "$" or "€"
EVENT = COUNTRY["stress_event"]            # the scripted heat wave / cold snap (from the config file)

if st.session_state.crisis_started is not None:
    ended = st.session_state.crisis_ended
    crisis_settings = (st.session_state.crisis_choice, st.session_state.crisis_severity,
                       st.session_state.crisis_seed, hour_of(st.session_state.crisis_started),
                       hour_of(ended) if ended else None,
                       st.session_state.full_on, st.session_state.full_off)
    the_crisis, outages = get_crisis(country_id, month, *crisis_settings)
else:
    crisis_settings, the_crisis, outages = None, None, []
crisis_running = st.session_state.crisis_started is not None and st.session_state.crisis_ended is None

readings = load_readings(country_id, month, crisis_settings)
data = pd.DataFrame(readings)
times = simulator.all_times(readings)

# The Play loop can't move the slider directly after it's drawn, so it leaves the
# next time here and we apply it now, before the slider is drawn.
if "next_time" in st.session_state:
    st.session_state.now = st.session_state.pop("next_time")
now = st.session_state.now
st.session_state.shown_time = now           # what the page is showing (see time_on_screen)
hour_now = hour_of(now)
current = data[data["time"] == now]
results = run_rules(country_id, month, crisis_settings, now)

# --- Zones without grid power now: crisis outages and approved wildfire shutoffs ---
outages_now = [o for o in outages if o["start"] <= hour_now < o["end"]]
fire_plan = rules.shutoff_plan(readings, now)      # None unless a zone's wildfire risk is High+
shut_off_now = {z for z, (start, until) in st.session_state.shutoffs.items()
                if start <= now and (until is None or now < until)}
dark_now = outages_now + [{"zone": z, "start": hour_of(start), "end": hour_of(until) if until else 24.0,
                           "cause": "wildfire shutoff"}
                          for z, (start, until) in st.session_state.shutoffs.items() if z in shut_off_now
                          and z not in {o["zone"] for o in outages_now}]
dark_zones = {o["zone"] for o in dark_now}
blackout = rules.blackout_report(readings, now, dark_now)

# Hours each battery could keep its home going without the grid, from now
# (rules.battery_runtime: stored energy over the home's expected need)
hours_left = {}
for zone, homes in current.groupby("zone"):
    homes = homes.astype(object).where(homes.notna(), None)    # missing values as None, not NaN
    for x in rules.zone_runtimes(readings, now, homes.to_dict("records"), zone)["runtimes"]:
        hours_left[x["battery_id"]] = None if x["tripped"] else x["hours"]

# --- Events to announce once (and pause on, while playing) ---
events = []
for _, r in results.iterrows():
    who = f"Home {int(r['battery_id'][4:])} ({r['household_type']})"
    if r["category"] == rules.NEEDS_DISPATCHER:
        why = (f"silent, probably {r['silent_guess']}" if pd.notna(r["silent_guess"])
               else r["reason"][0].lower() + r["reason"].split(".")[0][1:])   # keep "°F" as is
        events.append((f"{r['battery_id']}:{r['battery_status']}", f"{who} needs the dispatcher: {why}."))
    elif pd.notna(r["silent_guess"]):
        events.append((f"{r['battery_id']}:silent", f"{who} went silent, probably {r['silent_guess']}."))
crisis_line = crisis.forecast_label(the_crisis, hour_now) if the_crisis else None
if the_crisis and the_crisis["triggered_at"] <= hour_now and crisis_line:
    if hour_now < the_crisis["start_hour"]:
        events.append(("crisis:forecast", f"{crisis_line}. Batteries are pre-charging."))
    elif hour_now < the_crisis["end_hour"]:
        events.append(("crisis:start", f"{crisis_line}. {the_crisis['what']}"))
for o in outages_now:
    events.append((f"dark:{o['zone']}", f"{o['zone']} lost grid power ({o['cause']})."))
if fire_plan:
    events.append((f"fire:{fire_plan['zone']}",
                   f"Wildfire risk {fire_plan['level']} in {fire_plan['zone']}: a shutoff plan is in Relief plan."))
for zone, stress in current.groupby("zone")["zone_stress"].first().items():
    if stress >= rules.STRAINED_GRID and zone not in dark_zones:
        events.append((f"strained:{zone}", f"{zone} strained: {stress:.0f}% of capacity."))
new_events = [(k, msg) for k, msg in events if k not in st.session_state.seen]
st.session_state.seen |= {k for k, _ in events}

# ===========================================================================
# Header: name, Play and time, Start/End crisis, and a gear with every other setting
# ===========================================================================
st.session_state.setdefault("speed", "Normal")
st.session_state.setdefault("auto_pause", True)
st.session_state.setdefault("show_legend", True)
st.session_state.setdefault("show_details", False)
st.session_state.setdefault("full_blackout", False)


def bind(name):
    """
    Widgets in the settings gear use their own key ("w_" + name), refreshed from the real
    setting on every run. (A settings widget only appears when the gear is opened; without
    this it would show its default value then, and send that back as if it were a change.)
    """
    st.session_state["w_" + name] = st.session_state[name]
    return "w_" + name


def changed(name, then=None):
    """A settings widget changed: copy its value to the real setting, then react (if needed)."""
    st.session_state[name] = st.session_state["w_" + name]
    if then:
        then()


with st.container(key="panel_top"):
    h_brand, h_play, h_time, h_menu, h_crisis, h_gear = st.columns([2.3, 0.75, 3.3, 1.05, 1.15, 0.42],
                                                                    vertical_alignment="center")
    h_brand.html(style.brand("Home Battery Fleet", COUNTRY["region"].split(", ")[-1]))   # e.g. "Austin"
    h_play.button("Pause" if st.session_state.playing else "Play", on_click=toggle_play,
                  type="primary", width="stretch", icon=":material/pause:" if st.session_state.playing
                  else ":material/play_arrow:")
    h_time.select_slider("Time of day", options=times, key="now", label_visibility="collapsed",
                         format_func=lambda t: t[11:])   # show just "16:30"

    # --- Crisis menu: which crisis, how bad, the seed, and the full blackout switch ---
    choice_name = ("Random" if st.session_state.crisis_choice == "random"
                   else crisis.TYPES[st.session_state.crisis_choice]["name"])
    with h_menu.popover(choice_name, icon=":material/bolt:", help="Configure the crisis", width="stretch"):
        st.html(style.label("Crisis"))
        st.selectbox("Type", ["random"] + list(crisis.TYPES), key=bind("crisis_choice"), disabled=crisis_running,
                     on_change=changed, args=("crisis_choice",),
                     format_func=lambda k: "Random (this month's odds)" if k == "random" else crisis.TYPES[k]["name"],
                     help="Random: picked by this month's odds (it picks the severity too)")
        st.selectbox("Severity", range(1, 6), key=bind("crisis_severity"),
                     on_change=changed, args=("crisis_severity",),
                     disabled=crisis_running or st.session_state.crisis_choice == "random",
                     format_func=lambda s: f"{s} · {crisis.SEVERITY_NAMES[s]}")
        s1, s2 = st.columns(2, vertical_alignment="bottom")
        s1.number_input("Seed", min_value=0, max_value=999_999, step=1, key=bind("crisis_seed"),
                        on_change=changed, args=("crisis_seed",),
                        help="The same seed replays exactly the same crisis")
        s2.button("Reroll", on_click=reroll, width="stretch", icon=":material/casino:",
                  help="A new random seed: a new outcome")
        st.toggle("Force full blackout", key=bind("full_blackout"), on_change=changed,
                  args=("full_blackout", toggle_full_blackout),
                  disabled=not crisis_running, help="Cut grid power to every zone (start a crisis first)")
    if crisis_running:
        h_crisis.button("End crisis", on_click=end_crisis, width="stretch", icon=":material/stop_circle:",
                        help="The crisis stops now and power comes back everywhere")
    else:
        h_crisis.button("Start crisis", on_click=start_crisis, width="stretch", icon=":material/warning:",
                        help="Starts now, also while playing. Configure it in the menu on the left.")

    # --- Settings: scenario, playback and display ---
    with h_gear.popover("", icon=":material/settings:", help="Settings", width="stretch"):
        st.html(style.label("Scenario"))
        s1, s2 = st.columns(2)
        s1.selectbox("Country", list(simulator.COUNTRIES), key=bind("country"),
                     on_change=changed, args=("country", reset_demo),
                     format_func=lambda c: simulator.COUNTRIES[c]["name"].split(" · ")[-1],
                     help="Country numbers are approximate (config file)")
        s2.selectbox("Month", range(1, 13), key=bind("month"), on_change=changed, args=("month", reset_demo),
                     format_func=lambda m: weather.MONTHS[m - 1],
                     help="Weather, crisis odds and the fleet follow the month")
        st.html(style.label("Playback"))
        s1, s2 = st.columns(2)
        s1.button("Step 15 min", on_click=step_forward, width="stretch", icon=":material/skip_next:")
        s2.button("Reset day", on_click=jump_to, args=(DEMO_START,), width="stretch", icon=":material/replay:",
                  help="Back to noon, normal day, no crisis")
        s1, s2 = st.columns(2, vertical_alignment="bottom")
        s1.selectbox("Speed", list(SPEEDS), key=bind("speed"), on_change=changed, args=("speed",))
        s2.toggle("Auto-pause", key=bind("auto_pause"), on_change=changed, args=("auto_pause",),
                  help="Stop playing on each new event")
        st.html(style.label("Display"))
        st.toggle("Map legend", key=bind("show_legend"), on_change=changed, args=("show_legend",))
        st.toggle("Data tables (every battery, whose power can wait)", key=bind("show_details"),
                  on_change=changed, args=("show_details",))
    speed = st.session_state.speed
    pause_on_events = st.session_state.auto_pause

# While playing, pop up each new event and (optionally) pause so the presenter can talk
if st.session_state.playing and new_events:
    for _, msg in new_events:
        st.toast(msg)
    if pause_on_events:
        st.session_state.playing = False
        st.session_state.pause_note = " ".join(msg for _, msg in new_events)
        st.rerun()                           # redraw so the button says Play again

# --- Status line: time, weather and event; the crisis (if any); wildfire risk (always) ---
row0 = current.iloc[0]
left_parts = [f'<span class="time">{rules.clock(now)}</span>',
              f'<span class="muted">{rules.temp(row0["outdoor_temp_c"])}</span>']
if row0["stress_event"] and not (the_crisis and hour_now >= the_crisis["triggered_at"]):
    left_parts.append(style.tag(row0["event_name"], "warn"))
if the_crisis and hour_now >= the_crisis["triggered_at"]:
    c = the_crisis
    if hour_now >= c.get("ended_at", 99) or hour_now >= c["end_hour"]:
        when = f'over since {rules._hour_clock(min(c.get("ended_at", 99), c["end_hour"]))}'
    elif hour_now < c["start_hour"]:
        when = f'hits in {rules.hrs(c["start_hour"] - hour_now)} · pre-charging'
    else:
        when = f'{rules.hrs(hour_now - c["start_hour"])} since start'
    left_parts.append(style.tag(c["name"], "crit") + " " + style.severity_dots(c["severity"]))
    left_parts.append(f'<span>{"Forecast" if c["forecastable"] else "No warning"} · {when}</span>')
    if any("full blackout" in o["cause"] for o in outages_now):
        left_parts.append(style.tag("Full blackout", "solid"))
    left_parts.append(f'<span class="muted">seed {st.session_state.crisis_seed}</span>')
fire_zones = current.groupby("zone")["zone_fire_index"].first()
fire_index = int(fire_zones.max())
right_parts = [style.fire_pill(crisis.risk_level(fire_index)),
               f'<span class="muted">{fire_index}/100 · {rules.zone_short(fire_zones.idxmax())}</span>']
crisis_live = bool(the_crisis and the_crisis["start_hour"] <= hour_now < the_crisis["end_hour"]
                   and hour_now < the_crisis.get("ended_at", 99))
st.html(style.status_line(left_parts, right_parts) + (style.MAP_PULSE_CSS if crisis_live else ""))

# The pause message gets a slot that's always on the page (empty when not paused), so
# the map below never shifts position. A shift would make Streamlit rebuild the map.
pause_slot = st.empty()
if st.session_state.pause_note:
    pause_slot.info(f"**Paused at {rules.clock(now)}.** {st.session_state.pause_note}", icon=":material/pause_circle:")

# --- Four query-value tiles (drawn beside the map) ---
on_battery = int(current["zone"].isin(dark_zones).sum())
medical_risk = {x["battery_id"] for z in blackout for x in z["runtimes"] if x["household_type"] == "medical"
                and (x["runs_out"] or x["hours"] is None or x["hours"] <= 0.01 or x["short_kw"] > 0.05)}
medical_risk |= set(results[(results["household_type"] == "medical")
                            & (results["category"] == rules.NEEDS_DISPATCHER)]["battery_id"])
if blackout:                                 # shortest time left among homes without grid power
    running = [x for z in blackout for x in z["runtimes"] if x["hours"] and x["hours"] > 0.01]
    shortest = min(running, key=lambda x: x["hours"]) if running else None
    shortest_label = "Shortest time left"
else:                                        # no outage: shortest backup if the grid failed now
    running = [{"home_id": "HOME-" + b[4:], "hours": h} for b, h in hours_left.items() if h and h > 0.01]
    shortest = min(running, key=lambda x: x["hours"]) if running else None
    shortest_label = "Shortest backup"
dark_names = ", ".join(sorted(rules.zone_short(z) for z in dark_zones))
medical_names = ", ".join(f"Home {int(b[4:])}" for b in sorted(medical_risk))
tile_items = [
    ("Homes on battery", on_battery, "no grid power" if on_battery else "all on the grid",
     "crit" if on_battery else "ok"),
    ("Zones dark", f"{len(dark_zones)}/{len(simulator.ZONES)}", dark_names or "none",
     "crit" if dark_zones else "ok"),
    ("Medical at risk", len(medical_risk), medical_names or "none", "crit" if medical_risk else "ok"),
    (shortest_label, rules.hrs(shortest["hours"]) if shortest else "-",
     f"Home {int(shortest['home_id'][5:])}" if shortest else "",
     "crit" if shortest and shortest["hours"] < 2 else "warn" if shortest and shortest["hours"] < 4 else "ok"),
]
# ===========================================================================
# Big map on the left; tiles and next steps on the right
# ===========================================================================
left, right = st.columns([2.45, 1], gap="small")

with left, st.container(key="panel_map"):
    st.html(style.title("Fleet map", f"{len(current)} homes · {len(simulator.ZONES)} zones · click a dark zone for details"))
    # --- Map: zones lightly shaded by how strained they are, homes colored by category ---
    ink = style.rgb(style.INK)                 # label color on the light map

    zone_now = current.groupby("zone")[["zone_stress", "zone_fire_index", "zone_fire_level"]].first()
    # Forecast to be hit: a forecast crisis has been announced and this zone's outage is
    # still ahead. (Sudden crises give no warning, so nothing is forecast for them.)
    forecast_out = {}
    if the_crisis and the_crisis["forecastable"] and the_crisis["triggered_at"] <= hour_now:
        for o in outages:
            if hour_now < o["start"] and o["zone"] not in dark_zones:
                forecast_out[o["zone"]] = min(o["start"], forecast_out.get(o["zone"], 99))
    zone_rows, forecast_paths = [], []
    for name, z in simulator.ZONES.items():
        stress = zone_now.loc[name, "zone_stress"]
        fire_index, fire_level = zone_now.loc[name, "zone_fire_index"], zone_now.loc[name, "zone_fire_level"]
        state = ("Strained" if stress >= rules.STRAINED_GRID
                 else "Busy" if stress >= rules.BUSY_GRID else "OK")
        fill = style.rgb(style.ZONE_HEX[state], {"Strained": 32, "Busy": 38, "OK": 26}[state])
        label = f"{rules.zone_short(name)}: {stress:.0f}%"
        title = f"{name} · {stress:.0f}% of capacity"
        line1 = f"{state} · wildfire risk {fire_level.lower()}"
        if fire_level in ("High", "Extreme"):
            label += f" · fire {fire_level.lower()}"
        dark = next((o for o in outages_now if o["zone"] == name), None)
        if dark:                                # crisis blackout: no grid power here
            fill, label = style.rgb(style.DARK_ZONE_HEX, 120), f"{rules.zone_short(name)}: no power"
            title = f"{name} · no grid power"
            line1 = "Power back " + (f"~{rules._hour_clock(dark['end'])}" if dark["end"] < 24 else "after midnight")
        elif name in shut_off_now:                # precautionary shutoff approved: zone is dark
            fill, label = style.rgb(style.DARK_ZONE_HEX, 120), f"{rules.zone_short(name)}: shut off"
            title, line1 = f"{name} · shut off", "Precautionary shutoff (wildfire)"
        elif name in forecast_out:
            label += f"\nOutage ~{rules._hour_clock(forecast_out[name])}"   # second line
            line1 = f"Outage forecast ~{rules._hour_clock(forecast_out[name])}"
            forecast_paths += style.dashed_outline(z["shape"])
        corners = [[lon, lat] for lat, lon in z["shape"]]
        zone_rows.append({
            "zone": name, "polygon": corners, "fill": fill, "label": label,
            # Label in the zone's top-left corner, out of the way of the dots
            "lat": max(p[1] for p in corners), "lon": min(p[0] for p in corners),
            "title": title, "line1": line1,
        })

    FADE_MS = 600   # how long a dot or zone takes to fade to its new color

    # Dot fill = battery state. Ring = household type (none for regular homes).
    # Colors come from style.py so the map, alerts and legend always match.
    STATE_COLORS = {state: style.rgb(color) for state, color in style.STATE_HEX.items()}
    RING_COLORS = {kind: style.rgb(color) for kind, color in style.RING_HEX.items()}
    BUILDING_COLOR = style.rgb(style.BUILDING_HEX)
    def level_color(r):
        """In a dark zone the dot shows the battery level instead of its state."""
        if r["battery_status"] == "tripped" or pd.isna(r["charge_pct"]):
            return style.rgb(style.MUTED) if pd.isna(r["charge_pct"]) else STATE_COLORS[rules.NEEDS_DISPATCHER]
        if r["charge_pct"] > 50:
            return STATE_COLORS[rules.NORMAL]
        return STATE_COLORS[rules.WATCH] if r["charge_pct"] >= 20 else STATE_COLORS[rules.NEEDS_DISPATCHER]

    home_rows = []
    for _, r in current.merge(results[["battery_id", "category", "reason"]], on="battery_id").iterrows():
        # Short hover: "Home 112 · Medical · 64% · ~7h left"
        hours = hours_left.get(r["battery_id"])
        if r["battery_status"] == "tripped":
            left_text = "battery off"
        elif hours is None:
            left_text = "battery silent"
        else:
            left_text = f"{rules.hrs(hours)} left"
        title = " · ".join([f"Home {int(r['home_id'][5:])}", r["household_type"].capitalize()]
                           + ([f"{r['charge_pct']:.0f}%"] if pd.notna(r["charge_pct"]) else []) + [left_text])
        in_dark = r["zone"] in dark_zones
        home_rows.append({
            "zone": r["zone"], "lat": r["lat"], "lon": r["lon"],
            "color": level_color(r) if in_dark else STATE_COLORS[r["category"]],
            "household_type": r["household_type"], "category": r["category"],
            "ring": RING_COLORS.get(r["household_type"], [0, 0, 0, 0]),
            "title": title,
            "line1": r["category"] + (" · no grid power" if in_dark else ""),
        })
    vulnerable_rows = [h for h in home_rows if h["household_type"] == "vulnerable"]
    medical_rows = [h for h in home_rows if h["household_type"] == "medical"]
    urgent_rows = [h for h in home_rows if h["category"] == rules.NEEDS_DISPATCHER]

    # Critical buildings are squares about 70 m across (corners worked out in degrees)
    half_lat, half_lon = 35 / 111_320, 35 / 92_530
    building_rows = [{
        "zone": b["zone"], "lat": b["lat"], "lon": b["lon"], "label": b["name"],
        "square": [[b["lon"] - half_lon, b["lat"] - half_lat], [b["lon"] + half_lon, b["lat"] - half_lat],
                   [b["lon"] + half_lon, b["lat"] + half_lat], [b["lon"] - half_lon, b["lat"] + half_lat]],
        "title": b["name"],                     # the real OpenStreetMap name, if real
        "line1": " · ".join([b["building_type"].replace("_", " ").capitalize(),
                             f"backup {b['backup_hours']} h" if b["backup_hours"] else "no backup"]
                            + ([] if b.get("real") else ["simulated"])),
    } for b in simulator.critical_buildings()]
    # Buildings close together (like a fire station next to a water facility) would
    # print their names on top of each other: push each later one's name down a line.
    for i, row in enumerate(building_rows):
        near = sum(simulator.meters_between(row["lat"], row["lon"], other["lat"], other["lon"]) < 250
                   for other in building_rows[:i])
        row["offset"] = [14, 18 * near]

    def dots(data, radius_m, min_px, max_px, color, pickable=False, layer_id=None):
        """A layer of round dots. Rings are drawn as a slightly bigger dot underneath.
        When a dot changes color it fades over FADE_MS instead of jumping."""
        return pdk.Layer("ScatterplotLayer", data, get_position=["lon", "lat"], get_fill_color=color,
                         get_radius=radius_m, radius_min_pixels=min_px, radius_max_pixels=max_px,
                         stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=1.5,
                         pickable=pickable, transitions={"getFillColor": FADE_MS}, id=layer_id)

    below = [
        # Zones: lightly shaded, with their name and stress in the corner
        pdk.Layer("PolygonLayer", zone_rows, id="zones", get_polygon="polygon", get_fill_color="fill",
                  get_line_color=ink + [90], line_width_min_pixels=1, pickable=True,
                  transitions={"getFillColor": FADE_MS}),
            # Zones forecast to lose power: a dashed coral outline
        pdk.Layer("PathLayer", forecast_paths, get_path="path", get_color=style.rgb(style.CORAL, 230),
                  get_width=3, width_units="'pixels'", cap_rounded=True),
        # Critical buildings: larger squares with their name beside them
        pdk.Layer("PolygonLayer", building_rows, id="buildings", get_polygon="square",
                  get_fill_color=BUILDING_COLOR,
                  get_line_color=[255, 255, 255], line_width_min_pixels=2, pickable=True),
        pdk.Layer("TextLayer", character_set="'auto'", font_family=f"'{style.FONT}'", data=building_rows, get_position=["lon", "lat"], get_text="label", get_color=ink,
                  get_size=14, font_weight=600, get_text_anchor="'start'", get_pixel_offset="offset"),
    ]
    # (the pulsing rings around "Needs dispatcher" homes are drawn here, by draw_map)
    above = [
        # Homes: rings first (thick violet for medical, thin ink for vulnerable), then the dot
        dots(medical_rows, 62, 12, 16, "ring"),
        dots(vulnerable_rows, 46, 9, 12, "ring"),
        dots(home_rows, 32, 7, 10, "color", pickable=True, layer_id="homes"),
        # Zone names last, on a white tag, so no dot ever covers them
        pdk.Layer("TextLayer", character_set="'auto'", font_family=f"'{style.FONT}'", data=zone_rows, get_position=["lon", "lat"], get_text="label",
                  get_color=ink, get_size=16, font_weight=700, get_text_anchor="'start'",
                  get_alignment_baseline="'top'", get_pixel_offset=[6, 6],
                  background=True, get_background_color=[255, 255, 255, 220], background_padding=[4, 2]),
    ]
    view = pdk.ViewState(latitude=COUNTRY["map"]["center"][0], longitude=COUNTRY["map"]["center"][1],
                         zoom=COUNTRY["map"]["zoom"])
    # Hover box: the formatting lives here; each row just supplies plain title/line1
    tooltip = {"html": "<b>{title}</b><br/>{line1}",
               "style": {"maxWidth": "340px", "fontSize": "15px", "fontFamily": style.FONT, "backgroundColor": "#ffffff",
                         "color": style.INK, "borderRadius": "12px", "padding": "10px 12px",
                         "boxShadow": "0 4px 18px rgba(0,0,0,.12)"}}
    draw_map(below, above, urgent_rows, view, tooltip)
    # (the map shows its own credit in the corner: © CARTO, © OpenStreetMap contributors)

    # Legend: what every color and shape means
    if st.session_state.show_legend:
        st.html(style.legend(dark=bool(dark_zones), forecast=bool(forecast_out)))
    map_gestures.install()   # mouse wheel zooms; trackpad: two-finger slide moves, pinch zooms

with right:
    # --- Four query-value tiles, colored by threshold ---
    st.html(style.tiles(tile_items))

    # --- Next steps: the dispatcher's to-do list, a few short lines, most urgent first ---
    with st.container(key="panel_steps"):
        approved_now = {(zone, n) for t, zone, n in st.session_state.approved if t == now}
        dark_approved_now = {(zone, n) for zone, start, n in st.session_state.dark_approved
                             if any(o["zone"] == zone and o["start"] == start for o in dark_now)}
        todo, more = rules.next_steps(readings, now, results.to_dict("records"), approved_now,
                                      blackout=blackout, dark_approved=dark_approved_now,
                                      shutoff_approved=bool(fire_plan and fire_plan["zone"] in shut_off_now))
        st.html(style.title("Next steps", "most urgent first") + style.status_list(todo, more))

# A click on a dark zone on the map opens the Outage zone tab on that zone
if blackout:
    names = [z["zone"] for z in blackout]
    click = st.session_state.get("map_version", 0)
    if click != st.session_state.get("click_applied"):        # a new click on the map
        st.session_state.click_applied = click
        if st.session_state.get("picked_zone") in names:
            st.session_state.dark_zone_pick = st.session_state.picked_zone
            st.session_state.side_tab = "Outage zone"
    if st.session_state.get("dark_zone_pick") not in names:
        st.session_state.dark_zone_pick = names[0]

# ===========================================================================
# Timeseries: how the day is going so far (lines grow as Play runs)
# ===========================================================================
so_far = data[data["time"] <= now].copy()
so_far["hour"] = so_far["time"].map(hour_of)
hour_axis = alt.X("hour:Q", title=None, scale=alt.Scale(domain=[0, 24], nice=False),
                  axis=alt.Axis(values=list(range(0, 25, 3)), labelExpr="datum.value + ':00'"))
now_rule = alt.Chart(pd.DataFrame({"hour": [hour_now]})).mark_rule(color=style.MUTED, strokeDash=[2, 2]).encode(x="hour:Q")

chart_left, chart_right = st.columns(2, gap="small")
with chart_left, st.container(key="panel_chart_load"):
    st.html(style.title("Zone load", "% of capacity · strained at 80%"))
    load = so_far.groupby(["hour", "zone"], as_index=False)["zone_stress"].first()
    load["zone"] = load["zone"].map(rules.zone_short)
    zones = [rules.zone_short(z) for z in simulator.ZONES]
    lines = alt.Chart(load).mark_line(strokeWidth=1.8, interpolate="monotone").encode(
        x=hour_axis,
        y=alt.Y("zone_stress:Q", title=None, scale=alt.Scale(domain=[0, max(120, float(load["zone_stress"].max()) + 5)]),
                axis=alt.Axis(labelExpr="datum.value + '%'", tickCount=4)),
        color=alt.Color("zone:N", scale=alt.Scale(domain=zones, range=style.ZONE_LINE_HEX)),
        tooltip=[alt.Tooltip("zone:N", title="Zone"), alt.Tooltip("zone_stress:Q", title="Load %", format=".0f")])
    limit = alt.Chart(pd.DataFrame({"y": [rules.STRAINED_GRID]})).mark_rule(
        color=style.CORAL, strokeDash=[4, 3], strokeWidth=1.2).encode(y="y:Q")
    st.altair_chart(theme=None, altair_chart=style.chart_style(lines + limit + now_rule, 165), width="stretch")

with chart_right, st.container(key="panel_chart_charge"):
    st.html(style.title("Battery charge", "average by home type"))
    charge = so_far.dropna(subset=["charge_pct"]).groupby(["hour", "household_type"], as_index=False)["charge_pct"].mean()
    charge["household_type"] = charge["household_type"].str.capitalize()
    types = ["Regular", "Vulnerable", "Medical"]
    lines = alt.Chart(charge).mark_line(strokeWidth=1.8, interpolate="monotone").encode(
        x=hour_axis,
        y=alt.Y("charge_pct:Q", title=None, scale=alt.Scale(domain=[0, 100]),
                axis=alt.Axis(labelExpr="datum.value + '%'", tickCount=4)),
        color=alt.Color("household_type:N", scale=alt.Scale(domain=types, range=["#64748b", "#0ea5e9", style.RING_HEX["medical"]])),
        tooltip=[alt.Tooltip("household_type:N", title="Homes"), alt.Tooltip("charge_pct:Q", title="Charge %", format=".0f")])
    st.altair_chart(theme=None, altair_chart=style.chart_style(lines + now_rule, 165), width="stretch")

# ===========================================================================
# Details: alerts, relief plan, outage zone, normal day
# ===========================================================================
with st.container(key="panel_tabs"):
    alerts_tab, relief_tab, outage_tab, normal_tab = st.tabs(SIDE_TABS, key="side_tab")

    with alerts_tab:
        # --- Alerts: one line per battery that isn't Normal, most urgent first ---
        alerts = results[results["category"] != rules.NORMAL].merge(
            current[["battery_id", "home_id", "charge_pct", "inverter_temp_c", "voltage", "unserved_kw", "grid_power"]],
            on="battery_id")
        alerts["severity"] = alerts["category"].map(SEVERITY)
        alerts = alerts.sort_values(["severity", "wait_order", "battery_id"], ascending=[True, False, True])
        if alerts.empty:
            st.html(f'<p style="color:{style.MUTED}">All clear: every battery is normal.</p>')
        else:
            rows = []
            for _, a in alerts.iterrows():
                rows.append({"category": a["category"], "name": f"Home {int(a['home_id'][5:])}",
                             "type": a["household_type"].capitalize(),
                             "pct": None if pd.isna(a["charge_pct"]) else a["charge_pct"],
                             "hours": hours_left.get(a["battery_id"]), "problem": short_problem(a),
                             "reason": a["reason"]})
            with st.container(height=420, border=False):
                st.html(style.alert_lines(rows))

    with relief_tab:
        with st.container(height=420, border=False):
            # --- Wildfire precaution: a planned shutoff of the riskiest zone ---
            if fire_plan or shut_off_now:
                with st.container(border=True):
                    if fire_plan:
                        st.html(style.label("Wildfire precaution") + style.fire_pill(fire_plan["level"]))
                    else:
                        st.html(style.label("Wildfire precaution"))
                    for zone in sorted(shut_off_now):
                        until = st.session_state.shutoffs[zone][1]
                        st.success(f"**Shut off:** {zone} until "
                                   + (rules.clock(until) if until else "end of day") + " (see Outage zone)")
                    if fire_plan and fire_plan["zone"] not in shut_off_now:
                        p = fire_plan
                        buildings = [b["name"] + (" (no backup)" if not b["backup_hours"] else
                                                  f" ({b['backup_hours']} h backup)")
                                     for b in p["buildings"]]
                        until = rules.clock(p["until"]) if p["until"] else "the end of the day"
                        st.markdown(f"**{p['index']}/100** · {p['zone']} · batteries hold 80% · "
                                    f"shutoff until ~{until}")
                        st.markdown(f"**{p['homes']} homes** ({p['medical']} medical, {p['vulnerable']} vulnerable)"
                                    + (f" · shortest **{rules.hrs(p['shortest']['hours'])}**" if p["shortest"] else "")
                                    + (f" · {', '.join(buildings)}" if buildings else ""))
                        what = f"{p['homes']} homes" + (" and " + ", ".join(b["name"] for b in p["buildings"])
                                                        if p["buildings"] else "")
                        confirmed = st.checkbox(f"I understand {what} will lose grid power.",
                                                key=f"psps_confirm_{now}_{p['zone']}")
                        st.button("Approve shutoff", type="primary", disabled=not confirmed,
                                  key=f"psps_{now}_{p['zone']}", on_click=approve_shutoff,
                                  args=(p["zone"], now, p["until"]))


            # Every zone at a glance: a colored square, the name and how full it is
            ZONE_DOT = style.ZONE_HEX
            zone_now = current.groupby("zone", sort=False)[["zone_stress", "zone_load_kw", "zone_capacity_kw"]].first()
            lines = []
            for zone, z in zone_now.sort_values("zone_stress", ascending=False).iterrows():
                state = ("Strained" if z["zone_stress"] >= rules.STRAINED_GRID
                         else "Busy" if z["zone_stress"] >= rules.BUSY_GRID else "OK")
                square = ('<span style="display:inline-block;width:12px;height:12px;border-radius:2px;'
                          'margin-right:8px;background:{}"></span>')
                if zone in dark_zones:      # no grid power: nothing flows (see Outage zone)
                    lines.append(f'<div>{square.format(style.DARK_ZONE_HEX)}<b>no grid</b> · {rules.zone_short(zone)}</div>')
                    continue
                lines.append(f'<div>{square.format(ZONE_DOT[state])}<b>{z["zone_stress"]:.0f}%</b> · {rules.zone_short(zone)} '
                             f'<span style="opacity:.65">· {z["zone_load_kw"]:.0f}/{z["zone_capacity_kw"]:.0f} kW</span></div>')
            st.html('<div style="font-size:15px;line-height:1.9;margin-bottom:6px">' + "".join(lines) + "</div>")

            # (zones in a blackout have no grid to relieve: they're in the Blackout card)
            plans = [p for p in rules.relief_plans(readings, now) if p["zone"] not in dark_zones]

            if not plans:
                st.success("No zone is strained.")
            else:
                st.warning(f"**{rules.plural(len(plans), 'zone')} strained.** Gentlest step first, medical "
                           f"homes and critical buildings last. Nothing happens until you approve.")

            for i, plan in enumerate(plans):
                zone = plan["zone"]
                approved_kw = sum(s["kw"] for s in plan["steps"] if (now, zone, s["number"]) in st.session_state.approved)
                label = f"{plan['stress']:.0f}% · {rules.zone_short(zone)} · needs {plan['needed_kw']:.0f} kW"
                with st.expander(label, expanded=(i == 0)):
                    st.markdown(f"**{approved_kw:.0f} of {plan['needed_kw']:.0f} kW** approved → "
                                f"**{rules.stress_after(plan['load_kw'], plan['capacity_kw'], approved_kw):.0f}%**")

                    # A step can only be approved once every earlier step that's needed has been approved.
                    # That's what stops anyone jumping straight to cutting power.
                    earlier_done = True
                    for s in plan["steps"]:
                        key = (now, zone, s["number"])
                        done = key in st.session_state.approved

                        if s["kw"] <= 0:
                            # Nothing to do: one small grey line, no card
                            st.caption(f"{s['number']}. {s['title']}: nothing to do "
                                       f"({s['nothing_to_do'].rstrip('.')})")
                            continue                          # skipped steps don't block later ones
                        with st.container(border=True):
                            st.markdown(f"**{s['number']}. {s['title']}** · {s['kw']:.0f} kW → "
                                        f"{s['stress_after']:.0f}%")
                            with st.expander(f"Details · {len(s['targets'])} affected"):
                                st.write(f"{s['action']} {s['impact']}")
                                st.write(", ".join(s["targets"]))

                            if done:
                                st.success("Approved. Command sent (simulated).")
                            elif not s["needed"]:
                                st.caption("Not needed: the steps above already free enough.")
                            elif not earlier_done:
                                st.button("Approve", key=f"approve_{now}_{zone}_{s['number']}", disabled=True,
                                          help="Approve the earlier steps first.")
                            else:
                                confirmed = True
                                if s["number"] >= 4:
                                    # Cutting power or using emergency backup: ask for an extra confirmation
                                    what = ("these homes will lose power" if s["number"] < 6
                                            else "these buildings will use up their emergency backup")
                                    confirmed = st.checkbox(f"I understand {what}.", key=f"confirm_{now}_{zone}_{s['number']}")
                                st.button("Approve", key=f"approve_{now}_{zone}_{s['number']}", type="primary",
                                          on_click=approve, args=(key,), disabled=not confirmed)

                        if s["needed"] and not done:
                            earlier_done = False

                    if plan["shortfall_kw"] > 0:
                        st.error(f"Even with every step, {zone} is still about {plan['shortfall_kw']:.0f} kW short. "
                                 f"Medical homes are never cut: escalate to the utility.")

            if plans or shut_off_now or st.session_state.dark_approved or st.session_state.approved:
                st.button("Reset approvals", on_click=reset_approvals)

    with outage_tab:
        # --- Outage zone: its batteries, shortest runtime first (click a dark zone on the
        # map, or pick it here). Medical homes and critical buildings are pinned on top. ---
        if not blackout:
            st.html(f'<p style="color:{style.MUTED}">No zone is dark. Start a crisis (top bar) to see '
                    f'outage zones here.</p>')
        else:
            st.selectbox("Outage zone", names, key="dark_zone_pick", label_visibility="collapsed",
                         format_func=rules.zone_short,
                         help="Or click a dark zone on the map")
            z = next(z for z in blackout if z["zone"] == st.session_state.dark_zone_pick)
            rows = []
            for x in z["runtimes"]:
                rows.append({"name": f"Home {int(x['home_id'][5:])}", "type": x["household_type"].capitalize(),
                             "pct": x["charge_pct"], "hours": x["hours"],
                             "pinned": x["household_type"] == "medical", "kind": x["household_type"],
                             "off": x["tripped"]})
            for b in z["buildings"]:                 # critical buildings run on their own backup
                rows.append({"name": b["name"], "type": b["building_type"].replace("_", " ").capitalize(),
                             "pct": 100 * b["backup_left_h"] / b["backup_hours"] if b["backup_hours"] else 0,
                             "hours": b["backup_left_h"] if b["backup_hours"] else 0,
                             "no_backup": not b["backup_hours"], "pinned": True, "kind": "building"})
            # Pinned first (medical homes, critical buildings), then shortest runtime first
            rows.sort(key=lambda x: (not x["pinned"], x["hours"] is None, x["hours"] or 0))
            known = [x for x in z["runtimes"] if x["charge_pct"] is not None]
            running = [x for x in z["runtimes"] if x["hours"] and x["hours"] > 0.01]
            out = len([x for x in z["runtimes"] if x["hours"] is not None and x["hours"] <= 0.01
                       and not x["tripped"]])
            off = len([x for x in z["runtimes"] if x["tripped"]])
            first = min(running, key=lambda x: x["hours"]) if running else None
            back = f"~{rules._hour_clock(z['end'])}" if z["end"] < 24 else "after midnight"
            facts = [style.tag(f"{z['homes']} homes", "grey"),
                     style.tag(f"{sum(x['charge_pct'] for x in known) / len(known):.0f}% avg", "grey") if known else "",
                     style.tag(f"first empty {rules.hrs(first['hours'])} · Home {int(first['home_id'][5:])}",
                               "crit" if first["hours"] < 2 else "warn") if first else "",
                     style.tag(f"{out} empty", "crit") if out else "",
                     style.tag(f"{off} off", "crit") if off else "",
                     style.tag(f"power back {back}", "ok")]
            st.html(style.zone_battery_list("".join(f for f in facts if f), rows))
            # Recommended steps: nothing happens until the dispatcher approves
            st.html(style.label("Steps"))
            for s in z["steps"]:
                key = (z["zone"], z["start"], s["number"])
                text_col, button_col = st.columns([4, 1.3], vertical_alignment="center")
                text_col.markdown(f"**{s['number']}. {s['title']}** · {s['short']}")
                if key in st.session_state.dark_approved:
                    button_col.markdown(":green[Approved]")
                elif s["needed"]:
                    button_col.button("Approve", key=f"dark_{z['zone']}_{z['start']}_{s['number']}",
                                      type="primary" if s["number"] == 1 else "secondary",
                                      on_click=approve_dark, args=(key,), width="stretch")
                else:
                    button_col.caption("Not needed")
            st.caption("Approvals are recorded; the effect shown is an estimate (simulated).")

    with normal_tab:
        normal_day()

# --- Everything else, folded away so the main view stays clean ---
if st.session_state.show_details:
    with st.expander("Data tables: charge over the day, every battery, whose power can wait", expanded=True):
        # --- Chart: fleet charge over the day ---
        st.subheader("Average fleet charge over the day")
        over_time = data.groupby("time", as_index=False)["charge_pct"].mean()
        over_time["clock"] = over_time["time"].str[11:]   # "16:30" instead of the full date
        chart = alt.Chart(over_time).mark_line().encode(
            x=alt.X("clock", title="Time", axis=alt.Axis(values=[t for t in over_time["clock"] if t.endswith(":00")])),
            y=alt.Y("charge_pct", title="Average charge (%)", scale=alt.Scale(domain=[0, 100])),
            tooltip=["clock", alt.Tooltip("charge_pct", format=".0f", title="Charge %")],
        )
        # A dot showing the time picked on the slider
        marker = alt.Chart(over_time[over_time["time"] == now]).mark_point(size=80, filled=True, color=style.ACCENT).encode(
            x="clock", y="charge_pct",
        )
        st.altair_chart(theme=None, altair_chart=style.chart_style(chart + marker, 220), width="stretch")
        st.caption(f"Batteries fill up on cheap midday solar, then drain during the "
                   f"{EVENT['name'].lower()} ({rules.clock(f'2026-10-17 {EVENT['start_hour']:02d}:00')}–"
                   f"{rules.clock(f'2026-10-17 {EVENT['end_hour']:02d}:00')}).")

        # --- Table: every battery right now, most urgent first ---
        st.subheader(f"All batteries at {now[11:]}")
        table = current.merge(results[["battery_id", "category", "reason", "silent_guess", "wait_order"]], on="battery_id")
        table["severity"] = table["category"].map(SEVERITY)
        table = table.sort_values(["severity", "battery_id"])
        table["category"] = table["category"].map(ICONS)
        table["battery_status"] = table["battery_status"].fillna("no signal")
        table["silent_guess"] = table["silent_guess"].fillna("")
        if COUNTRY["temperature_unit"] == "F":     # show temperatures the way this country does
            table["inverter_temp_c"] = (table["inverter_temp_c"] * 9 / 5 + 32).round(1)
        table = table[[
            "category", "battery_id", "reason", "silent_guess", "household_type", "priority", "zone",
            "battery_status", "charge_pct", "battery_kw", "inverter_temp_c", "home_usage_kw", "from_grid_kw",
        ]].rename(columns={
            "category": "Category",
            "battery_id": "Battery",
            "reason": "Why",
            "silent_guess": "Silent: best guess",
            "household_type": "Household",
            "priority": "Priority",
            "zone": "Zone",
            "battery_status": "Status",
            "charge_pct": "Charge %",
            "battery_kw": "Battery kW",
            "inverter_temp_c": f"Temp °{COUNTRY['temperature_unit']}",
            "home_usage_kw": "Home uses kW",
            "from_grid_kw": "From grid kW",
        })
        st.dataframe(
            table, hide_index=True, width="stretch", height=600,
            column_config={"Why": st.column_config.TextColumn(width="large")},
        )

        # --- Waiting list: whose power can wait, in order ---
        st.subheader("Whose power can wait")
        st.caption("If the grid needs relief, ask homes to wait in this order: flexible loads first, "
                   "critical homes last. Batteries that need the dispatcher are left out.")
        waiting = pd.DataFrame(rules.waiting_list(results.to_dict("records")))
        waiting = waiting.merge(current[["battery_id", "home_usage_kw"]], on="battery_id")

        # How much power each group could free up
        SHORT_LABEL = {1: "1 · Waits first", 2: "2 · Waits if needed", 3: "3 · Waits late", 4: "4 · Protect last"}
        groups = waiting.groupby("wait_order", as_index=False).agg(
            homes=("battery_id", "count"), total_kw=("home_usage_kw", "sum"))
        cols = st.columns(len(groups))
        for col, (_, g) in zip(cols, groups.iterrows()):
            col.metric(f"{SHORT_LABEL[g['wait_order']]} ({int(g['homes'])} homes)", f"{g['total_kw']:.0f} kW")

        waiting["category"] = waiting["category"].map(ICONS)
        st.dataframe(
            waiting[["wait_label", "battery_id", "household_type", "zone", "home_usage_kw", "category"]].rename(columns={
                "wait_label": "Wait order",
                "battery_id": "Battery",
                "household_type": "Household",
                "zone": "Zone",
                "home_usage_kw": "Home uses kW",
                "category": "Category",
            }),
            hide_index=True, width="stretch", height=400,
        )

# --- Footer: where each kind of data comes from (real or simulated), and the credits ---
weather_day = weather.typical_day(country_id, month)
buildings_now = simulator.critical_buildings()
real_buildings = [b for b in buildings_now if b.get("real")]
quakes = crisis._earthquakes(str(crisis.DATA_DIR / f"earthquakes_{country_id}.json"))
st.html(style.sources([
    (weather_day["label"], weather_day["source"] == "real", weather_day["credit"]),
    (f"Buildings: real ({len(real_buildings)} from OpenStreetMap)" if real_buildings
     else "Buildings: simulated", bool(real_buildings), None),
    ("Earthquakes: real (50 years)" if quakes else "Earthquakes: simulated", bool(quakes),
     "Earthquakes: USGS" if quakes else None),
    ("Fleet: simulated · country numbers approximate", False, None),
]), )


# --- Playback loop: wait, then move to the next 15 minutes and redraw ---
# (This sits at the very end so the whole page is drawn before we wait.)
if st.session_state.playing:
    i = times.index(now)
    if i + 1 < len(times):
        # Wait out the rest of the step (drawing the page already took some of it)
        time.sleep(max(0, SPEEDS[speed] - (time.time() - started)))
        st.session_state.next_time = times[i + 1]
    else:
        st.session_state.playing = False     # end of the day
    st.rerun()
