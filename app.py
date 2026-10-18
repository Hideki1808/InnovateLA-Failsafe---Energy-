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
def load_readings(country_id, month):
    simulator.use_country(country_id)
    return simulator.simulate(month=month)


@st.cache_data
def run_rules(country_id, month, at_time):
    simulator.use_country(country_id)
    return pd.DataFrame(rules.triage(load_readings(country_id, month), at_time))


# Page look: the theme is in .streamlit/config.toml; style.py adds the few extras
# (section labels, big key numbers, white panels, no grey-out while Play redraws)
st.html(style.CSS)

@st.cache_data
def get_crisis(country_id, month, mode, kind, severity, seed, full_blackout):
    """The crisis for the Crisis panel's settings and its outages (which zones go dark,
    when). Same settings + same seed = exactly the same crisis, so it can be replayed."""
    simulator.use_country(country_id)
    if mode == "Random":                      # random for the month, by its odds
        c = crisis.pick_random(country_id, month, seed=seed)
    else:
        c = crisis.make_crisis(country_id, month, kind, severity, seed=seed)
    return c, crisis.blackouts(country_id, c, seed=seed, force_full=full_blackout)


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
    st.pydeck_chart(pdk.Deck(layers=below + [pulse] + above, initial_view_state=view,
                             map_style="light_no_labels", tooltip=tooltip),
                    height=520, key="fleet_map")   # same key every time = update the map in place
                    #   (also when switching country: it then moves to the new view, centred)


# --- Country: everything country-specific comes from config/countries.toml ---
st.session_state.setdefault("country", simulator.DEFAULT_COUNTRY)
st.session_state.setdefault("month", simulator.DAY_START.month)   # the demo date's month


def reset_demo():
    """A different country or month starts the demo over: back to noon, nothing approved yet."""
    for key in ("now", "playing", "pause_note", "seen", "approved", "shutoffs", "next_time"):
        st.session_state.pop(key, None)


title_col, country_col = st.columns([2.4, 1.6], vertical_alignment="bottom")
pick_country, pick_month = country_col.columns([1.6, 1])
pick_country.selectbox("Country", list(simulator.COUNTRIES), key="country", on_change=reset_demo,
                       format_func=lambda c: simulator.COUNTRIES[c]["name"], label_visibility="collapsed")
pick_month.selectbox("Month", range(1, 13), key="month", on_change=reset_demo,
                     format_func=lambda m: weather.MONTHS[m - 1], label_visibility="collapsed")
country_id = st.session_state.country
month = st.session_state.month
simulator.use_country(country_id)          # rules.py and simulator.py now use this country
COUNTRY = simulator.COUNTRY
CUR = COUNTRY["currency"]                  # e.g. "$" or "€"
title_col.html(style.label(f"Live grid dispatch · {COUNTRY['region']}")
               + '<p class="brand">Home Battery Fleet</p>')
country_col.caption("Simulated fleet. Country numbers are approximate.")

readings = load_readings(country_id, month)
data = pd.DataFrame(readings)

live_tab, earn_tab = st.tabs(["Live dispatch", "Normal day earnings"])

# ===========================================================================
# Tab 1: live dispatch (the demo day with the country's stress event)
# ===========================================================================
with live_tab:
    # --- Playback: run the day forward for the live demo ---
    times = simulator.all_times(readings)
    DEMO_START = "2026-10-17 12:00"        # calm before the stress event
    EVENT = COUNTRY["stress_event"]          # heat wave, cold snap... (from the config file)
    SPEEDS = {"Slow": 2.0, "Normal": 1.0, "Fast": 0.4}   # seconds per 15-minute step

    # --- Crisis mode: a random or hand-picked crisis, with a seed so it can be replayed ---
    CRISIS_MODES = ["Off", "Random", "Pick"]
    st.session_state.setdefault("crisis_mode", "Off")
    st.session_state.setdefault("crisis_type", "windstorm")
    st.session_state.setdefault("crisis_severity", 4)
    st.session_state.setdefault("crisis_seed", 42)
    st.session_state.setdefault("full_blackout", False)


    def reroll():
        """A new random seed: a new outcome (a different crisis or different dark zones)."""
        st.session_state.crisis_seed = random.randint(1, 99_999)
        st.session_state.seen = set()


    with st.container(key="panel_crisis"):
        k1, k2, k3, k4, k5, k6 = st.columns([2.2, 1.8, 1.6, 1.3, 1.0, 1.9], vertical_alignment="bottom")
        k1.segmented_control("Crisis mode", CRISIS_MODES, key="crisis_mode", required=True,
                             help="Random: a crisis picked by this month's odds. Pick: choose the type and severity.")
        picking = st.session_state.crisis_mode == "Pick"
        crisis_on = st.session_state.crisis_mode != "Off"
        k2.selectbox("Type", list(crisis.TYPES), key="crisis_type", disabled=not picking,
                     format_func=lambda k: crisis.TYPES[k]["name"])
        k3.selectbox("Severity", range(1, 6), key="crisis_severity", disabled=not picking,
                     format_func=lambda s: f"{s} {crisis.SEVERITY_NAMES[s].lower()}")
        k4.number_input("Seed", min_value=0, max_value=999_999, step=1, key="crisis_seed",
                        disabled=not crisis_on, help="The same seed replays exactly the same crisis")
        k5.button("Reroll", on_click=reroll, disabled=not crisis_on, width="stretch",
                  help="Pick a new random seed for a new outcome")
        k6.checkbox("Full blackout", key="full_blackout", disabled=not crisis_on,
                    help="Force a full blackout: cut grid power to every zone")

    if crisis_on:
        the_crisis, outages = get_crisis(country_id, month, st.session_state.crisis_mode,
                                         st.session_state.crisis_type, st.session_state.crisis_severity,
                                         st.session_state.crisis_seed, crisis_on and st.session_state.full_blackout)
    else:
        the_crisis, outages = None, []

    st.session_state.setdefault("now", DEMO_START)
    st.session_state.setdefault("playing", False)
    st.session_state.setdefault("pause_note", None)
    st.session_state.setdefault("seen", set())      # events already announced

    # The Play loop can't move the slider directly after it's drawn, so it leaves the
    # next time here and we apply it now, before the slider is drawn.
    if "next_time" in st.session_state:
        st.session_state.now = st.session_state.pop("next_time")


    def toggle_play():
        st.session_state.playing = not st.session_state.playing
        st.session_state.pause_note = None


    def jump_to(t):
        st.session_state.playing = False
        st.session_state.pause_note = None
        st.session_state.seen = set()
        st.session_state.now = t


    def step_forward():
        i = times.index(st.session_state.now)
        st.session_state.now = times[min(i + 1, len(times) - 1)]


    now = st.session_state.now
    current = data[data["time"] == now]
    results = run_rules(country_id, month, now)

    # Spot new events: a battery that needs the dispatcher (or changes why), a battery
    # going silent, or the grid becoming strained. Announce each once.
    events = []
    for _, r in results.iterrows():
        who = f"{r['battery_id']} ({r['household_type'].replace('_', ' ')} home)"
        if r["category"] == rules.NEEDS_DISPATCHER:
            why = (f"silent, probably {r['silent_guess']}" if pd.notna(r["silent_guess"])
                   else r["reason"].split(".")[0].lower())
            events.append((f"{r['battery_id']}:{r['battery_status']}", f"{who} needs the dispatcher: {why}."))
        elif pd.notna(r["silent_guess"]):
            events.append((f"{r['battery_id']}:silent", f"{who} went silent. Best guess: {r['silent_guess']}."))
    # Crisis mode: the crisis starting, and each zone losing or getting back grid power
    hour_now = int(now[11:13]) + int(now[14:16]) / 60
    outages_now = [o for o in outages if o["start"] <= hour_now < o["end"]]
    crisis_line = crisis.forecast_label(the_crisis, hour_now) if the_crisis else None
    if the_crisis and the_crisis["start_hour"] <= hour_now < the_crisis["end_hour"]:
        events.append(("crisis:start", f"{crisis_line}. {the_crisis['what']}"))
    for o in outages_now:
        events.append((f"dark:{o['zone']}", f"{o['zone']} lost grid power ({o['cause']}). "
                                            f"Its homes run on their batteries. See the Response ladder tab."))
    # Wildfire: the riskiest zone's precautionary-shutoff plan (None unless High/Extreme),
    # and which shutoffs the dispatcher has approved: {zone: (from, until)}
    fire_plan = rules.shutoff_plan(readings, now)
    st.session_state.setdefault("shutoffs", {})
    shut_off_now = {z for z, (start, until) in st.session_state.shutoffs.items()
                    if start <= now and (until is None or now < until)}
    if fire_plan:
        events.append((f"fire:{fire_plan['zone']}",
                       f"Wildfire risk {fire_plan['level']} in {fire_plan['zone']}: batteries there hold "
                       f"an 80% reserve. A precautionary shutoff is ready in the Response ladder tab."))
    for zone, stress in current.groupby("zone")["zone_stress"].first().items():
        if stress >= rules.STRAINED_GRID:
            events.append((f"strained:{zone}", f"{EVENT['name']}: {zone} is strained ({stress:.0f}% of capacity). "
                                               f"See its plan in the Response ladder tab."))
    new_events = [(k, msg) for k, msg in events if k not in st.session_state.seen]
    st.session_state.seen |= {k for k, _ in events}

    # One row: Play / Step / Reset, the time slider, speed, and auto-pause
    c1, c2, c3, c_slider, c4, c5 = st.columns([1.1, 1, 1.1, 3.4, 2.6, 1.8], vertical_alignment="center")
    c1.button("Pause" if st.session_state.playing else "Play", on_click=toggle_play,
              type="primary", width="stretch")
    c2.button("Step", on_click=step_forward, width="stretch", help="Move forward 15 minutes")
    c3.button("Reset", on_click=jump_to, args=(DEMO_START,), width="stretch",
              help=f"Back to the start, before the {EVENT['name'].lower()}")
    speed = c4.segmented_control("Speed", list(SPEEDS), default="Normal", required=True,
                                 label_visibility="collapsed")
    pause_on_events = c5.checkbox("Auto-pause", value=True,
                                  help="Stop playing when a battery goes silent, needs the dispatcher, or a zone gets strained")

    c_slider.select_slider("Time of day", options=times, key="now", label_visibility="collapsed",
                           format_func=lambda t: t[11:])   # show just "16:30"

    # While playing, pop up each new event and (optionally) pause so the presenter can talk
    if st.session_state.playing and new_events:
        for _, msg in new_events:
            st.toast(msg)
        if pause_on_events:
            st.session_state.playing = False
            st.session_state.pause_note = " ".join(msg for _, msg in new_events)
            st.rerun()                           # redraw so the button says Play again

    # The pause message gets a slot that's always on the page (empty when not paused), so
    # the map below never shifts position. A shift would make Streamlit rebuild the map.
    pause_slot = st.empty()
    if st.session_state.pause_note:
        pause_slot.info(f"**Paused at {rules.clock(now)}.** {st.session_state.pause_note} Press Play to continue.")

    # --- Key numbers across the top: very large number, short caption underneath ---
    # Coral only when the number is a warning sign; everything else stays ink-black.
    counts = results["category"].value_counts()
    zone_stress_now = current.groupby("zone")["zone_stress"].first()
    strained_zones = int((zone_stress_now >= rules.STRAINED_GRID).sum())
    worst_zone = zone_stress_now.idxmax()
    worst = zone_stress_now[worst_zone]
    needs = int(counts.get(rules.NEEDS_DISPATCHER, 0))
    event_on = bool(current.iloc[0]["stress_event"])      # is the heat wave / cold snap on?
    st.html(style.stats([
        (rules.clock(now), f"{rules.temp(current.iloc[0]['outdoor_temp_c'])} outside"
                           + (f" · {rules.event_label()}" if event_on else ""), False),
        (needs, "need the dispatcher", needs > 0),
        (int(counts.get(rules.WATCH, 0)), "to watch", False),
        (int(counts.get(rules.CAN_WAIT, 0)), "can wait", False),
        (f"{strained_zones} of {len(zone_stress_now)}", "zones strained", strained_zones > 0),
        (f"{worst:.0f}%", f"busiest: {worst_zone}", worst >= rules.STRAINED_GRID),
    ]))
    # Where each kind of data comes from: real (saved by fetch_data.py) or simulated
    weather_day = weather.typical_day(country_id, month)
    buildings_now = simulator.critical_buildings()
    real_buildings = [b for b in buildings_now if b.get("real")]
    made_up = [b["building_type"].replace("_", " ") for b in buildings_now if not b.get("real")]
    if real_buildings:
        buildings_label = (f"Buildings: real ({len(real_buildings)} from OpenStreetMap"
                           + (f"; simulated {' and '.join(made_up)}" if made_up else "") + ")")
    else:
        buildings_label = "Buildings: simulated (no saved OpenStreetMap data)"
    st.html(style.sources([
        (weather_day["label"], weather_day["source"] == "real", weather_day["credit"]),
        (buildings_label, bool(real_buildings),
         "Map data © OpenStreetMap contributors" if real_buildings else None),
    ]))

    if the_crisis:
        c = the_crisis
        when = (f"starts {rules._hour_clock(c['start_hour'])}"
                + (f", forecast {c['warning_hours']}h ahead" if c["forecastable"] else ", no warning"))
        dark_text = ("; ".join(f"{o['zone']} {rules._hour_clock(o['start'])} to "
                               + (rules._hour_clock(o["end"]) if o["end"] < 24 else "midnight")
                               for o in outages) or "no outages this time")
        headline = crisis_line or f'{c["name"]} coming (no warning yet)'
        if "severity" not in headline:
            headline += f', severity {c["severity"]} ({c["severity_name"].lower()})'
        st.html(f'<div class="crisis-line"><b>{headline}</b> · {when}'
                f' · chance this month {c["chance_this_month"]:.0%}'
                f' · Seed {st.session_state.crisis_seed}'
                f'<br/>Blackouts: {dark_text}</div>')

    # --- Main area: big map on the left, side panel with what to do on the right ---
    left, right = st.columns([1.9, 1.1], gap="medium")

    with left, st.container(key="panel_map"):
        st.html(style.label("Fleet map"))
        # --- Map: zones lightly shaded by how strained they are, homes colored by category ---
        ink = style.rgb(style.INK)                 # label color on the light map

        zone_now = current.groupby("zone")[["zone_stress", "zone_fire_index", "zone_fire_level"]].first()
        zone_rows = []
        for name, z in simulator.ZONES.items():
            stress = zone_now.loc[name, "zone_stress"]
            fire_index, fire_level = zone_now.loc[name, "zone_fire_index"], zone_now.loc[name, "zone_fire_level"]
            state = ("Strained" if stress >= rules.STRAINED_GRID
                     else "Busy" if stress >= rules.BUSY_GRID else "OK")
            fill = style.rgb(style.ZONE_HEX[state], {"Strained": 32, "Busy": 38, "OK": 26}[state])
            label = f"{name}: {stress:.0f}%"
            line2 = f"Wildfire risk {fire_level.lower()} ({fire_index}/100)"
            if fire_level in ("High", "Extreme"):
                label += f" · fire {fire_level.lower()}"
                line2 += ": batteries hold an 80% reserve"
            dark = next((o for o in outages_now if o["zone"] == name), None)
            if dark:                                # crisis blackout: no grid power here
                fill, label = style.rgb("#1c1c1e", 150), f"{name}: no power"
                line2 = (f"Blackout ({dark['cause']}) since {rules._hour_clock(dark['start'])}; homes run on "
                         f"their batteries. Power back "
                         + (f"about {rules._hour_clock(dark['end'])}" if dark["end"] < 24 else "after midnight"))
            elif name in shut_off_now:                # precautionary shutoff approved: zone is dark
                fill, label = style.rgb("#3a3a3c", 120), f"{name}: shut off"
                line2 = "Precautionary shutoff (wildfire): homes run on their batteries"
            corners = [[lon, lat] for lat, lon in z["shape"]]
            zone_rows.append({
                "polygon": corners, "fill": fill, "label": label,
                # Label in the zone's top-left corner, out of the way of the dots
                "lat": max(p[1] for p in corners), "lon": min(p[0] for p in corners),
                "title": name, "line1": f"Zone {state.lower()}: using {stress:.0f}% of its capacity",
                "line2": line2,
            })

        FADE_MS = 600   # how long a dot or zone takes to fade to its new color

        # Dot fill = battery state. Ring = household type (none for regular homes).
        # Colors come from style.py so the map, alerts and legend always match.
        STATE_COLORS = {state: style.rgb(color) for state, color in style.STATE_HEX.items()}
        RING_COLORS = {kind: style.rgb(color) for kind, color in style.RING_HEX.items()}
        BUILDING_COLOR = style.rgb(style.BUILDING_HEX)
        home_rows = []
        for _, r in current.merge(results[["battery_id", "category", "reason"]], on="battery_id").iterrows():
            home_rows.append({
                "lat": r["lat"], "lon": r["lon"], "color": STATE_COLORS[r["category"]],
                "household_type": r["household_type"], "category": r["category"],
                "ring": RING_COLORS.get(r["household_type"], [0, 0, 0, 0]),
                "title": f"{r['battery_id']} · {r['household_type']} home · {r['zone']}",
                "line1": f"Battery: {r['category']}"
                         + (f", {r['charge_pct']:.0f}% charged" if pd.notna(r["charge_pct"]) else ", not reporting"),
                "line2": r["reason"],
            })
        vulnerable_rows = [h for h in home_rows if h["household_type"] == "vulnerable"]
        medical_rows = [h for h in home_rows if h["household_type"] == "medical"]
        urgent_rows = [h for h in home_rows if h["category"] == rules.NEEDS_DISPATCHER]

        # Critical buildings are squares about 70 m across (corners worked out in degrees)
        half_lat, half_lon = 35 / 111_320, 35 / 92_530
        building_rows = [{
            "lat": b["lat"], "lon": b["lon"], "label": b["name"],
            "square": [[b["lon"] - half_lon, b["lat"] - half_lat], [b["lon"] + half_lon, b["lat"] - half_lat],
                       [b["lon"] + half_lon, b["lat"] + half_lat], [b["lon"] - half_lon, b["lat"] + half_lat]],
            "title": f"{b['name']} · critical building · {b['zone']}",
            "line1": f"Uses about {b['load_kw']} kW. Backup: {b['backup'].lower()}"
                     + (f", {b['backup_hours']} h" if b["backup_hours"] else ""),
            "line2": ("Real building (OpenStreetMap); power use approximate."
                  if b.get("real") else "Simulated building (no real one found here).")
                 + " Protected last: never cut off.",
        } for b in simulator.critical_buildings()]
        # Buildings close together (like a fire station next to a water facility) would
        # print their names on top of each other: push each later one's name down a line.
        for i, row in enumerate(building_rows):
            near = sum(simulator.meters_between(row["lat"], row["lon"], other["lat"], other["lon"]) < 250
                       for other in building_rows[:i])
            row["offset"] = [14, 18 * near]

        def dots(data, radius_m, min_px, max_px, color, pickable=False):
            """A layer of round dots. Rings are drawn as a slightly bigger dot underneath.
            When a dot changes color it fades over FADE_MS instead of jumping."""
            return pdk.Layer("ScatterplotLayer", data, get_position=["lon", "lat"], get_fill_color=color,
                             get_radius=radius_m, radius_min_pixels=min_px, radius_max_pixels=max_px,
                             stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=1.5,
                             pickable=pickable, transitions={"getFillColor": FADE_MS})

        below = [
            # Zones: lightly shaded, with their name and stress in the corner
            pdk.Layer("PolygonLayer", zone_rows, get_polygon="polygon", get_fill_color="fill",
                      get_line_color=ink + [90], line_width_min_pixels=1, pickable=True,
                      transitions={"getFillColor": FADE_MS}),
                # Critical buildings: larger squares with their name beside them
            pdk.Layer("PolygonLayer", building_rows, get_polygon="square", get_fill_color=BUILDING_COLOR,
                      get_line_color=[255, 255, 255], line_width_min_pixels=2, pickable=True),
            pdk.Layer("TextLayer", character_set="'auto'", font_family=f"'{style.FONT}'", data=building_rows, get_position=["lon", "lat"], get_text="label", get_color=ink,
                      get_size=14, font_weight=600, get_text_anchor="'start'", get_pixel_offset="offset"),
        ]
        # (the pulsing rings around "Needs dispatcher" homes are drawn here, by draw_map)
        above = [
            # Homes: rings first (thick violet for medical, thin ink for vulnerable), then the dot
            dots(medical_rows, 62, 12, 16, "ring"),
            dots(vulnerable_rows, 46, 9, 12, "ring"),
            dots(home_rows, 32, 7, 10, "color", pickable=True),
            # Zone names last, on a white tag, so no dot ever covers them
            pdk.Layer("TextLayer", character_set="'auto'", font_family=f"'{style.FONT}'", data=zone_rows, get_position=["lon", "lat"], get_text="label",
                      get_color=ink, get_size=16, font_weight=700, get_text_anchor="'start'",
                      get_alignment_baseline="'top'", get_pixel_offset=[6, 6],
                      background=True, get_background_color=[255, 255, 255, 220], background_padding=[4, 2]),
        ]
        view = pdk.ViewState(latitude=COUNTRY["map"]["center"][0], longitude=COUNTRY["map"]["center"][1],
                             zoom=COUNTRY["map"]["zoom"])
        # Hover box: the formatting lives here; each row just supplies plain title/line1/line2
        tooltip = {"html": "<b>{title}</b><br/>{line1}<br/>{line2}",
                   "style": {"maxWidth": "340px", "fontSize": "15px", "fontFamily": style.FONT, "backgroundColor": "#ffffff",
                             "color": style.INK, "borderRadius": "12px", "padding": "10px 12px",
                             "boxShadow": "0 4px 18px rgba(0,0,0,.12)"}}
        draw_map(below, above, urgent_rows, view, tooltip)

        # Legend: what every color and shape means
        st.html(style.legend())
        map_gestures.install()   # two-finger slide moves the map, pinch zooms

    with right, st.container(key="panel_side"):
        # --- Dispatcher summary: three plain-English lines, written by the rules ---
        st.session_state.setdefault("approved", set())
        approved_now = {(zone, n) for t, zone, n in st.session_state.approved if t == now}
        blackout = rules.blackout_report(readings, now, outages_now)
        brief = rules.summary(readings, now, results.to_dict("records"), approved_now,
                              shutoff_approved=bool(fire_plan and fire_plan["zone"] in shut_off_now),
                              blackout=blackout)
        st.html(style.label("What's happening") + style.pill(brief["level"]))
        st.markdown(f"{brief['status']}  \n{brief['outlook']}  \n{brief['action']}")

        alerts_tab, ladder_tab = st.tabs(["Alerts", "Response ladder"])
        with alerts_tab:
            # --- Alerts: everything that isn't Normal, most urgent first ---
            alerts = results[results["category"] != rules.NORMAL].copy()   # (the rules already give each zone)
            alerts["severity"] = alerts["category"].map(SEVERITY)
            # Most urgent category first; inside a category, critical homes first
            alerts = alerts.sort_values(["severity", "wait_order", "battery_id"], ascending=[True, False, True])

            if alerts.empty:
                st.html(f'<p style="color:{style.MUTED}">All clear: every battery is normal right now.</p>')
            else:
                # Scrollable list so a long one doesn't push the rest of the page down
                rows = alerts.assign(silent_guess=alerts["silent_guess"].where(alerts["silent_guess"].notna(), None))
                with st.container(height=520, border=False):
                    st.html(style.alert_list(rows.to_dict("records")))

        with ladder_tab:
            with st.container(height=560, border=False):
                # --- Zone relief plans: gentle steps before shedding, one zone at a time ---

                # Remember which steps the dispatcher approved, as (time, zone, step) — survives
                # clicks, resets on page reload
                if "approved" not in st.session_state:
                    st.session_state.approved = set()


                def approve(key):
                    st.session_state.approved.add(key)


                def reset_approvals():
                    st.session_state.approved = set()
                    st.session_state.shutoffs = {}


                def approve_shutoff(zone, start, until):
                    st.session_state.shutoffs[zone] = (start, until)


                # --- Blackout (crisis mode): zones without grid power and their battery runtimes ---
                if blackout:
                    with st.container(border=True):
                        st.html(style.label("Blackout") + style.pill("error"))
                        for z in blackout:
                            back = (f"about {rules._hour_clock(z['end'])}" if z["end"] < 24
                                    else "not before midnight")
                            st.markdown(f"**{z['zone']}**: no grid power since {rules._hour_clock(z['start'])} "
                                        f"({z['cause']}); expected back {back}, in {z['hours_left']:.1f} h. "
                                        f"{z['homes']} homes on their batteries ({z['medical']} medical, "
                                        f"{z['vulnerable']} vulnerable).")
                            if z["shortest"]:
                                note = (f"Shortest runtime {z['shortest']['hours']:.1f} h ({z['shortest']['battery_id']}), "
                                        f"typical {z['median_hours']:.1f} h. ")
                                note += (f"{rules.plural(len(z['run_out']), 'home')} will run out before power returns: "
                                         + ", ".join(f"{x['battery_id']} ({x['household_type']})" for x in z["run_out"])
                                         + "." if z["run_out"] else "Every battery should last until power returns.")
                                st.caption(note)
                            if z["buildings"]:
                                st.caption("Critical buildings on their own backup: " + ", ".join(
                                    b["name"] + (f" ({b['backup'].lower()}, {b['backup_hours']} h)"
                                                 if b["backup_hours"] else " (no backup)") for b in z["buildings"]))
                            with st.expander(f"Homes and battery runtimes ({z['homes']})"):
                                st.write(", ".join(
                                    f"{x['battery_id']} ({x['household_type']}): "
                                    + (f"{x['hours']:.1f} h" if x["hours"] is not None else "unknown (silent)")
                                    for x in z["runtimes"]))

                # --- Wildfire precaution: a planned shutoff of the riskiest zone ---
                if fire_plan or shut_off_now:
                    with st.container(border=True):
                        if fire_plan:
                            st.html(style.label("Wildfire precaution") + style.fire_pill(fire_plan["level"]))
                        else:
                            st.html(style.label("Wildfire precaution"))
                        for zone in sorted(shut_off_now):
                            until = st.session_state.shutoffs[zone][1]
                            st.success(f"**Shutoff approved: {zone} is off the grid**"
                                       + (f" until {rules.clock(until)}" if until else " for the rest of the day")
                                       + ". Homes run on their batteries (simulated).")
                        if fire_plan and fire_plan["zone"] not in shut_off_now:
                            p = fire_plan
                            buildings = [b["name"] + (" (no backup)" if not b["backup_hours"] else
                                                      f" ({b['backup'].lower()}, {b['backup_hours']} h)")
                                         for b in p["buildings"]]
                            until = rules.clock(p["until"]) if p["until"] else "the end of the day"
                            st.markdown(
                                f"**{p['zone']}**: wildfire risk **{p['level'].lower()}** ({p['index']}/100). "
                                f"Its batteries already hold an 80% reserve. A planned shutoff would cut grid "
                                f"power to **{p['homes']} homes**"
                                + (f" and **{', '.join(buildings)}**" if buildings else "")
                                + f" until about **{until}**, so power lines can't spark a fire.")
                            if p["shortest"]:
                                st.caption(f"Battery runtime if shut off now: shortest {p['shortest']['hours']:.1f} h "
                                           f"({p['shortest']['battery_id']}), typical {p['median_hours']:.1f} h. "
                                           f"{p['medical']} medical and {p['vulnerable']} vulnerable homes.")
                            with st.expander(f"Homes and battery runtimes ({p['homes']})"):
                                st.write(", ".join(
                                    f"{x['battery_id']} ({x['household_type']}): "
                                    + (f"{x['hours']:.1f} h" if x["hours"] is not None else "unknown (silent)")
                                    for x in p["runtimes"]))
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
                    lines.append(f'<div><span style="display:inline-block;width:12px;height:12px;border-radius:2px;'
                                 f'background:{ZONE_DOT[state]};margin-right:8px"></span><b>{zone}</b>: '
                                 f'{z["zone_stress"]:.0f}% <span style="opacity:.65">({state.lower()}, '
                                 f'{z["zone_load_kw"]:.0f} of {z["zone_capacity_kw"]:.0f} kW)</span></div>')
                st.html('<div style="font-size:15px;line-height:1.9;margin-bottom:6px">' + "".join(lines) + "</div>")

                # (zones in a blackout have no grid to relieve: they're in the Blackout card)
                plans = [p for p in rules.relief_plans(readings, now)
                         if p["zone"] not in {o["zone"] for o in outages_now}]

                if not plans:
                    st.success("No zone is strained. No relief steps needed.")
                else:
                    st.warning(
                        f"**{rules.plural(len(plans), 'zone')} strained.** Gentlest step first; medical homes "
                        f"and critical buildings are protected last. **Nothing happens until you click Approve.**"
                    )

                for i, plan in enumerate(plans):
                    zone = plan["zone"]
                    approved_kw = sum(s["kw"] for s in plan["steps"] if (now, zone, s["number"]) in st.session_state.approved)
                    label = f"{zone}: {plan['stress']:.0f}%, needs {plan['needed_kw']:.0f} kW"
                    with st.expander(label, expanded=(i == 0)):
                        st.markdown(f"Approved so far: **{approved_kw:.0f} of {plan['needed_kw']:.0f} kW** → zone "
                                    f"≈**{rules.stress_after(plan['load_kw'], plan['capacity_kw'], approved_kw):.0f}%**")

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
                                st.markdown(f"**{s['number']}. {s['title']}** · frees **{s['kw']:.0f} kW** "
                                            f"→ zone ≈{s['stress_after']:.0f}%")
                                st.caption(f"{s['action']} {s['impact']}")
                                with st.expander(f"Which {len(s['targets'])}"):
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

                if plans or shut_off_now:
                    st.button("Reset approvals", on_click=reset_approvals)


    # --- Everything else, folded away so the main view stays clean ---
    with st.expander("More details: charge over the day, every battery, whose power can wait"):
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
        marker = alt.Chart(over_time[over_time["time"] == now]).mark_point(size=120, filled=True, color="red").encode(
            x="clock", y="charge_pct",
        )
        st.altair_chart(chart + marker, width="stretch")
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


# ===========================================================================
# Tab 2: how the fleet earns money on a normal day (no stress event, no problems)
# ===========================================================================
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


with earn_tab, st.container(key="panel_earnings"):
    simulator.use_country(country_id)
    calm = load_ordinary_day(country_id, month)
    prices = COUNTRY["prices"]
    st.html(style.label("How the fleet earns its keep on a normal day"))
    st.markdown(
        "On a normal day there's no emergency. Each battery earns its keep the simple way: "
        "**buy power when it's cheap** (midday, when solar floods the grid) and "
        "**use it when it's expensive** (the evening peak), so the home doesn't have to buy it then."
    )

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
        (money(per_day, 0), "fleet earns per day", True),
        (money(per_day / batteries), "per battery per day", False),
        (money(per_day / batteries * 365, 0), "per battery per year (daily × 365)", False),
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
    st.altair_chart((price_line + price_labels).properties(height=200), width="stretch")

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
    st.altair_chart((axis_keeper + bars + zero).properties(height=220), width="stretch")
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
    st.altair_chart(money_line.properties(height=200), width="stretch")

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
