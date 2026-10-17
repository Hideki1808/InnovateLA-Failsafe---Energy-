"""
app.py - the dispatcher's dashboard.

Run it with:
    streamlit run app.py
"""

import time

import altair as alt
import pandas as pd
import streamlit as st

import rules
import simulator

st.set_page_config(page_title="Fleet Dispatcher", layout="wide")
started = time.time()   # used by Play to keep a steady pace

# A colored dot for each category, so the table is easy to scan
ICONS = {
    rules.NEEDS_DISPATCHER: "🔴 Needs dispatcher",
    rules.WATCH: "🟠 Watch",
    rules.CAN_WAIT: "🔵 Can wait",
    rules.NORMAL: "🟢 Normal",
}
# Most urgent first when sorting the table
SEVERITY = {rules.NEEDS_DISPATCHER: 0, rules.WATCH: 1, rules.CAN_WAIT: 2, rules.NORMAL: 3}


# Make the fake data once and remember it (so the page doesn't redo it on every click)
@st.cache_data
def load_readings():
    return simulator.simulate()


@st.cache_data
def run_rules(at_time):
    return pd.DataFrame(rules.triage(load_readings(), at_time))


readings = load_readings()
data = pd.DataFrame(readings)

st.title("Home Battery Fleet")

live_tab, earn_tab = st.tabs(["⚡ Live dispatch", "💰 Normal day earnings"])

# ===========================================================================
# Tab 1: live dispatch (the demo day with the heat wave)
# ===========================================================================
with live_tab:
    # --- Playback: run the day forward for the live demo ---
    times = simulator.all_times(readings)
    DEMO_START = "2026-10-17 12:00"        # calm before the heat wave
    SPEEDS = {"Slow": 2.0, "Normal": 1.0, "Fast": 0.4}   # seconds per 15-minute step

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
    results = run_rules(now)

    # Spot new events: a battery that needs the dispatcher (or changes why), a battery
    # going silent, or the grid becoming strained. Announce each once.
    events = []
    for _, r in results.iterrows():
        who = f"{r['battery_id']} ({r['home_type'].replace('_', ' ')} home)"
        if r["category"] == rules.NEEDS_DISPATCHER:
            why = (f"silent, probably {r['silent_guess']}" if pd.notna(r["silent_guess"])
                   else r["reason"].split(".")[0].lower())
            events.append((f"{r['battery_id']}:{r['battery_status']}", f"🔴 {who} needs the dispatcher: {why}."))
        elif pd.notna(r["silent_guess"]):
            events.append((f"{r['battery_id']}:silent", f"📵 {who} went silent. Best guess: {r['silent_guess']}."))
    if current.iloc[0]["grid_stress"] >= rules.STRAINED_GRID:
        events.append(("strained", f"🌡️ Heat wave: grid stress {current.iloc[0]['grid_stress']:.0f}/100. "
                                   f"Relief plan is ready below."))
    new_events = [(k, msg) for k, msg in events if k not in st.session_state.seen]
    st.session_state.seen |= {k for k, _ in events}

    c1, c2, c3, c4, c5 = st.columns([1.3, 1.1, 1.1, 2, 2.5], vertical_alignment="center")
    c1.button("⏸ Pause" if st.session_state.playing else "▶ Play", on_click=toggle_play,
              type="primary", width="stretch")
    c2.button("⏭ Step", on_click=step_forward, width="stretch", help="Move forward 15 minutes")
    c3.button("⏮ Reset", on_click=jump_to, args=(DEMO_START,), width="stretch",
              help="Back to 12:00, before the heat wave")
    speed = c4.radio("Speed", list(SPEEDS), index=1, horizontal=True, label_visibility="collapsed")
    pause_on_events = c5.checkbox("Pause on new events", value=True,
                                  help="Stop playing when a battery goes silent, needs the dispatcher, or the grid gets strained")

    st.select_slider("Time of day", options=times, key="now",
                     format_func=lambda t: t[11:])   # show just "16:30"

    # While playing, pop up each new event and (optionally) pause so the presenter can talk
    if st.session_state.playing and new_events:
        for _, msg in new_events:
            st.toast(msg)
        if pause_on_events:
            st.session_state.playing = False
            st.session_state.pause_note = " ".join(msg for _, msg in new_events)
            st.rerun()                           # redraw so the button says Play again

    if st.session_state.pause_note:
        st.info(f"⏸ **Paused at {now[11:]}.** {st.session_state.pause_note} Press Play to continue.")

    # --- Dispatcher summary: three plain-English lines, written by the rules ---
    st.session_state.setdefault("approved", set())
    approved_now = {n for t, n in st.session_state.approved if t == now}
    brief = rules.summary(readings, now, results.to_dict("records"), approved_now)
    box = {"ok": st.success, "warning": st.warning, "error": st.error}[brief["level"]]
    box(f"**📋 At {rules.clock(now)}:** {brief['status']}  \n"
        f"{brief['outlook']}  \n"
        f"{brief['action']}")

    # --- Top numbers: what the rules say ---
    counts = results["category"].value_counts()
    cols = st.columns(4)
    for col, category in zip(cols, ICONS):
        col.metric(ICONS[category], int(counts.get(category, 0)))

    # --- Fleet numbers ---
    row = current.iloc[0]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total homes", current["home_id"].nunique())
    col2.metric("Average charge", f"{current['charge_pct'].mean():.0f}%")
    col3.metric("Batteries not reporting", int((~current["battery_reporting"]).sum()))
    col4.metric("Grid stress", f"{row['grid_stress']:.0f} / 100", "Heat wave" if row["heat_wave"] else None,
                delta_color="inverse")
    # (Average charge only counts batteries that are reporting.)

    # --- Alerts: everything that isn't Normal, most urgent first ---
    st.subheader("Alerts")
    alerts = results[results["category"] != rules.NORMAL].merge(
        current[["battery_id", "neighborhood"]], on="battery_id")
    alerts["severity"] = alerts["category"].map(SEVERITY)
    # Most urgent category first; inside a category, critical homes first
    alerts = alerts.sort_values(["severity", "wait_order", "battery_id"], ascending=[True, False, True])

    if alerts.empty:
        st.success("All clear: every battery is normal right now.")
    else:
        # Scrollable box so a long list doesn't push the rest of the page down
        with st.container(height=380):
            for _, a in alerts.iterrows():
                guess = f" · silent: **{a['silent_guess']}**" if pd.notna(a["silent_guess"]) else ""
                text = (f"**{a['battery_id']}** · {a['home_type']} · {a['neighborhood']}{guess}  \n"
                        f"{a['reason']}")
                if a["category"] == rules.NEEDS_DISPATCHER:
                    st.error(text, icon="🔴")
                elif a["category"] == rules.WATCH:
                    st.warning(text, icon="🟠")
                else:
                    st.info(text, icon="🔵")

    # --- Grid relief plan: gentle steps before shedding, each needs the dispatcher's OK ---
    st.subheader("Grid relief plan")

    # Remember which steps the dispatcher approved (survives clicks, resets on page reload)
    if "approved" not in st.session_state:
        st.session_state.approved = set()


    def approve(key):
        st.session_state.approved.add(key)


    def reset_approvals():
        st.session_state.approved = set()


    plan = rules.relief_plan(readings, now)

    if plan is None:
        st.success(f"Grid is OK (stress {row['grid_stress']:.0f}/100). No relief steps needed.")
    else:
        st.warning(
            f"**Grid is strained: stress {plan['stress']:.0f}/100.** About **{plan['needed_kw']:.0f} kW** "
            f"of relief would bring it down to {rules.TARGET_STRESS}. Try the gentle steps first, in order. "
            f"**Nothing happens until you click Approve.**"
        )

        approved_kw = sum(s["kw"] for s in plan["steps"] if (now, s["number"]) in st.session_state.approved)
        c1, c2 = st.columns(2)
        c1.metric("Relief approved", f"{approved_kw:.0f} of {plan['needed_kw']:.0f} kW")
        c2.metric("Grid stress after approved steps", f"{rules.stress_after(plan['stress'], approved_kw):.0f} / 100")

        # A step can only be approved once every earlier step that's needed has been approved.
        # That's what stops anyone jumping straight to shedding.
        earlier_done = True
        for s in plan["steps"]:
            key = (now, s["number"])
            done = key in st.session_state.approved

            with st.container(border=True):
                left, right = st.columns([3, 1])
                left.markdown(f"**Step {s['number']}: {s['title']}**")
                if s["kw"] <= 0:
                    left.caption("Nothing to do right now: " + s["nothing_to_do"])
                    continue                      # skipped steps don't block later ones
                left.write(s["action"])
                left.caption(s["impact"])
                with left.expander(f"Which {len(s['targets'])} batteries / homes"):
                    st.write(", ".join(s["targets"]))
                right.metric("Would free", f"{s['kw']:.0f} kW")
                right.caption(f"Grid stress after steps 1–{s['number']}: ≈{s['stress_after']:.0f}")

                if done:
                    st.success(f"Approved. Command sent to {len(s['targets'])} batteries / homes (simulated).", icon="✅")
                elif not s["needed"]:
                    st.caption("Not needed: the steps above already free enough.")
                elif not earlier_done:
                    st.button("Approve", key=f"approve_{now}_{s['number']}", disabled=True,
                              help="Approve the earlier steps first.")
                else:
                    confirmed = True
                    if s["number"] == 4:
                        # Shedding cuts people's power, so ask for an extra confirmation
                        confirmed = st.checkbox(f"I understand {len(s['targets'])} homes will lose power.",
                                                key=f"confirm_{now}")
                    st.button("Approve", key=f"approve_{now}_{s['number']}", type="primary",
                              on_click=approve, args=(key,), disabled=not confirmed)

            if s["needed"] and not done:
                earlier_done = False

        if plan["shortfall_kw"] > 0:
            st.error(f"Even with all four steps, about {plan['shortfall_kw']:.0f} kW is still missing. "
                     f"Escalate to the utility.")
        st.button("Reset approvals", on_click=reset_approvals)

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
    st.caption("Batteries fill up on cheap midday solar, then drain during the 2–8 pm heat wave.")

    # --- Table: every battery right now, most urgent first ---
    st.subheader(f"All batteries at {now[11:]}")
    table = current.merge(results[["battery_id", "category", "reason", "silent_guess", "wait_order"]], on="battery_id")
    table["severity"] = table["category"].map(SEVERITY)
    table = table.sort_values(["severity", "battery_id"])
    table["category"] = table["category"].map(ICONS)
    table["battery_status"] = table["battery_status"].fillna("no signal")
    table["silent_guess"] = table["silent_guess"].fillna("")
    table = table[[
        "category", "battery_id", "reason", "silent_guess", "home_type", "priority", "neighborhood",
        "battery_status", "charge_pct", "battery_kw", "inverter_temp_c", "home_usage_kw", "from_grid_kw",
    ]].rename(columns={
        "category": "Category",
        "battery_id": "Battery",
        "reason": "Why",
        "silent_guess": "Silent: best guess",
        "home_type": "Home type",
        "priority": "Priority",
        "neighborhood": "Neighborhood",
        "battery_status": "Status",
        "charge_pct": "Charge %",
        "battery_kw": "Battery kW",
        "inverter_temp_c": "Temp °C",
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
    waiting = waiting.merge(current[["battery_id", "home_usage_kw", "neighborhood"]], on="battery_id")

    # How much power each group could free up
    SHORT_LABEL = {1: "1 · Waits first", 2: "2 · Waits if needed", 3: "3 · Protect, waits last"}
    groups = waiting.groupby("wait_order", as_index=False).agg(
        homes=("battery_id", "count"), total_kw=("home_usage_kw", "sum"))
    cols = st.columns(len(groups))
    for col, (_, g) in zip(cols, groups.iterrows()):
        col.metric(f"{SHORT_LABEL[g['wait_order']]} ({int(g['homes'])} homes)", f"{g['total_kw']:.0f} kW")

    waiting["category"] = waiting["category"].map(ICONS)
    st.dataframe(
        waiting[["wait_label", "battery_id", "home_type", "neighborhood", "home_usage_kw", "category"]].rename(columns={
            "wait_label": "Wait order",
            "battery_id": "Battery",
            "home_type": "Home type",
            "neighborhood": "Neighborhood",
            "home_usage_kw": "Home uses kW",
            "category": "Category",
        }),
        hide_index=True, width="stretch", height=400,
    )

# ===========================================================================
# Tab 2: how the fleet earns money on a normal day (no heat wave, no problems)
# ===========================================================================
CHARGE_COLOR = "#3987e5"      # blue: taking power in
DISCHARGE_COLOR = "#eb6834"   # orange: giving power out
PRICE_COLOR = "#9a9893"       # neutral gray: the price line
MONEY_COLOR = "#7c6ee0"       # violet: the running total


@st.cache_data
def load_ordinary_day():
    return pd.DataFrame(simulator.simulate(ordinary_day=True))


@st.cache_data
def demo_day_earnings():
    return sum(r["earnings_usd"] for r in load_readings())


with earn_tab:
    calm = load_ordinary_day()
    st.markdown(
        "On a normal day there's no emergency. Each battery earns its keep the simple way: "
        "**buy power when it's cheap** (midday, when solar floods the grid) and "
        "**use it when it's expensive** (the evening peak), so the home doesn't have to buy it then."
    )

    # One row per 15 minutes for the whole fleet
    day = calm.groupby("time", as_index=False).agg(
        price=("price_per_kwh", "first"),
        fleet_kw=("battery_kw", "sum"),
        money=("earnings_usd", "sum"),
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
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fleet earns per day", f"${per_day:,.0f}")
    c2.metric("Per battery per day", f"${per_day / batteries:.2f}")
    c3.metric("Per battery per year", f"${per_day / batteries * 365:,.0f}",
              help="Just the daily number × 365. Real years have cloudy days and holidays.")
    c4.metric("Energy moved to the evening", f"{shifted_kwh:,.0f} kWh")

    # --- Chart 1: the price of power through the day ---
    st.subheader("1. The price of power changes through the day")
    price_line = alt.Chart(day).mark_line(interpolate="step-after", strokeWidth=2, color=PRICE_COLOR).encode(
        x=x,
        y=alt.Y("price", title="$ per kWh", axis=alt.Axis(format="$.2f")),
        tooltip=[alt.Tooltip("clock", title="Time"), alt.Tooltip("price", title="Price", format="$.2f")],
    )
    labels = pd.DataFrame([
        {"clock": "12:30", "price": 0.08, "text": "Cheap: $0.08 (solar)"},
        {"clock": "19:00", "price": 0.35, "text": "Peak: $0.35"},
    ])
    price_labels = alt.Chart(labels).mark_text(dy=-12, fontSize=13, color=PRICE_COLOR).encode(x="clock", y="price", text="text")
    st.altair_chart((price_line + price_labels).properties(height=200), width="stretch")

    # --- Chart 2: what the batteries do about it ---
    st.subheader("2. So the batteries charge when it's cheap and discharge at the peak")
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
    st.subheader("3. Small cost at midday, bigger savings in the evening")
    money_line = alt.Chart(day).mark_line(strokeWidth=2, color=MONEY_COLOR).encode(
        x=x,
        y=alt.Y("running_total", title="Fleet total so far", axis=alt.Axis(format="$,.0f")),
        tooltip=[alt.Tooltip("clock", title="Time"),
                 alt.Tooltip("running_total", title="Total so far", format="$,.2f")],
    )
    st.altair_chart(money_line.properties(height=200), width="stretch")

    # --- The simple math ---
    st.subheader("The math")
    hours_per_step = simulator.STEP_MINUTES / 60
    bought = calm[calm["battery_kw"] < 0]
    used = calm[calm["battery_kw"] > 0]
    bought_kwh = (-bought["battery_kw"] * hours_per_step).sum()
    used_kwh = (used["battery_kw"] * hours_per_step).sum()
    math = pd.DataFrame([
        {"When": "10 am – 3 pm", "Batteries": "Charge", "Energy": f"{bought_kwh:,.0f} kWh",
         "Price": f"${-bought['earnings_usd'].sum() / bought_kwh:.2f} / kWh",
         "Money": f"−${-bought['earnings_usd'].sum():,.2f}"},
        {"When": "5 pm – 9 pm", "Batteries": "Discharge", "Energy": f"{used_kwh:,.0f} kWh",
         "Price": f"${used['earnings_usd'].sum() / used_kwh:.2f} / kWh",
         "Money": f"+${used['earnings_usd'].sum():,.2f}"},
        {"When": "Whole day", "Batteries": "", "Energy": "", "Price": "",
         "Money": f"+${per_day:,.2f}"},
    ])
    st.dataframe(math, hide_index=True, width="stretch")
    st.caption(
        f"Simulated numbers, kept simple: {batteries} batteries of {simulator.BATTERY_CAPACITY_KWH:.0f} kWh, "
        f"no energy lost when charging, and each battery ends the day about where it started. "
        f"For comparison, on the heat-wave demo day the same fleet earned "
        f"\\${demo_day_earnings():,.0f}, because peak prices hit \\$0.90 / kWh."   # \$ = a plain dollar sign
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
