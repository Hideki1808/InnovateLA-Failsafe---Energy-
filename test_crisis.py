"""
test_crisis.py - checks crisis mode end to end, and prints a report.

Run it with:
    python test_crisis.py                 normal run, with the saved data in data/
    python test_crisis.py --without-data  hides data/ for a moment (renames it), runs the
                                          same checks plus the dashboard on the fallback
                                          values, then puts data/ back (always, even if a
                                          check fails)

For every country, several months and every crisis type it prints:
    chance      how likely that crisis is in that month (crisis.monthly_chances)
    picked      how often "Random" mode picks it in that month (out of many seeds)
    severity    average severity (1-5) of that crisis in that month
    zones cut   average number of zones that lose grid power
    shortest    the shortest battery runtime (hours) at the moment power goes out,
                over a few simulated days ("-" = no outage in those days)

And it checks (PASS / FAIL):
    - seasons make sense (heat waves in summer, cold snaps in winter, earthquakes all year)
    - severity 4-5 always cuts at least one zone; Full blackout cuts every zone
    - the same seed gives exactly the same crisis, blackouts and simulated day
    - with --without-data: everything runs on fallback values, labelled "simulated"
The exit code is 0 if everything passed, 1 if anything failed.
"""

import os
import subprocess
import sys
from pathlib import Path

import crisis
import rules
import simulator
import weather

MONTHS = [1, 4, 7, 10]            # winter, spring, summer, autumn
PICK_SEEDS = 300                  # random picks per month (for "picked" and severity)
OUTAGE_SEEDS = 40                 # blackout draws per crisis (for "zones cut")
RUNTIME_SEEDS = 4                 # simulated days per crisis (for "shortest")
HERE = Path(__file__).parent
DATA = HERE / "data"
HIDDEN = HERE / "data_hidden_for_test"

failures = []


def check(ok, what):
    """Print PASS or FAIL for one check, and remember failures."""
    print(f"  {'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        failures.append(what)


def hour_to_time(hour):
    """15.25 -> '2026-10-17 15:15' (a time in the simulated day)."""
    hour = min(hour, 23.75)
    return f"2026-10-17 {int(hour):02d}:{int(round(hour % 1 * 60)):02d}"


def shortest_runtime(country_id, month, c, seed):
    """Simulate the day with this crisis; at the moment the first zone goes dark, return
    the shortest battery runtime (hours) among the homes without grid power, or None."""
    outages = crisis.blackouts(country_id, c, seed=seed)
    if not outages:
        return None
    readings = simulator.simulate(month=month, crisis=c, outages=outages)
    first = min(o["start"] for o in outages)
    dark_now = [o for o in outages if o["start"] <= first < o["end"]]
    report = rules.blackout_report(readings, hour_to_time(first), dark_now)
    # Leave out batteries already out of action (the planted tripped one): that's not a runtime
    tripped = {r["battery_id"] for r in readings
               if r["time"] == hour_to_time(first) and r["battery_status"] == "tripped"}
    hours = [x["hours"] for z in report for x in z["runtimes"]
             if x["hours"] is not None and x["battery_id"] not in tripped]
    return min(hours) if hours else None


# ---------------------------------------------------------------------------
# 1. The report: every crisis type, several months, both countries
# ---------------------------------------------------------------------------
def report(country_id):
    simulator.use_country(country_id)
    print(f"\n=== {simulator.COUNTRY['name']} ===")
    print(f"{'month':5s} {'crisis':11s} {'chance':>7s} {'picked':>7s} {'severity':>8s} "
          f"{'zones cut':>9s} {'shortest':>9s}  source")
    table = {}
    for month in MONTHS:
        chances = crisis.monthly_chances(country_id, month)
        picks = [crisis.pick_random(country_id, month, seed=s) for s in range(PICK_SEEDS)]
        for kind in crisis.TYPES:
            mine = [p for p in picks if p["type"] == kind]
            # Severity: from the random picks of this type if there are enough, else from
            # crises of this type made the same way Random mode makes them
            if len(mine) >= 10:
                severities = [p["severity"] for p in mine]
            else:
                import random
                severities = [crisis._severity(country_id, kind, chances[kind]["intensity"],
                                               random.Random(s)) for s in range(PICK_SEEDS)]
            avg_sev = sum(severities) / len(severities)
            # Zones cut: blackouts for crises of this type at this month's typical severities
            cut = []
            for s in range(OUTAGE_SEEDS):
                c = crisis.make_crisis(country_id, month, kind, severities[s % len(severities)], seed=s)
                cut.append(len(crisis.blackouts(country_id, c, seed=s)))
            # Shortest runtime: a few simulated days with a strong (severity 4) crisis, so
            # there is always an outage to measure
            runtimes = []
            for s in range(RUNTIME_SEEDS):
                c = crisis.make_crisis(country_id, month, kind, 4, seed=s)
                r = shortest_runtime(country_id, month, c, s)
                if r is not None:
                    runtimes.append(r)
            row = {"chance": chances[kind]["chance"], "picked": len(mine) / PICK_SEEDS,
                   "severity": avg_sev, "cut": sum(cut) / len(cut),
                   "shortest": min(runtimes) if runtimes else None,
                   "source": chances[kind]["source"]}
            table[(month, kind)] = row
            print(f"{weather.MONTHS[month - 1][:3]:5s} {crisis.TYPES[kind]['name']:11s} "
                  f"{row['chance']:7.1%} {row['picked']:7.1%} {avg_sev:8.1f} {row['cut']:9.1f} "
                  f"{'-' if row['shortest'] is None else f'{row['shortest']:.1f} h':>9s}  {row['source']}")
    print("  (shortest = at the moment power goes out, severity-4 crisis)")
    return table


# ---------------------------------------------------------------------------
# 2. Do the seasons make sense?
# ---------------------------------------------------------------------------
def check_seasons(country_id, table):
    name = simulator.COUNTRIES[country_id]["name"]
    print(f"\nSeasons, {name}:")
    jan, jul = 1, 7
    c = lambda m, k: table[(m, k)]["chance"]
    check(c(jul, "heat_wave") > c(jan, "heat_wave"),
          f"heat waves likelier in July ({c(jul, 'heat_wave'):.0%}) than January ({c(jan, 'heat_wave'):.0%})")
    check(c(jan, "cold_snap") > c(jul, "cold_snap"),
          f"cold snaps likelier in January ({c(jan, 'cold_snap'):.0%}) than July ({c(jul, 'cold_snap'):.0%})")
    check(c(jul, "wildfire") >= c(jan, "wildfire"),
          f"wildfires at least as likely in July ({c(jul, 'wildfire'):.0%}) as January ({c(jan, 'wildfire'):.0%})")
    quakes = {round(c(m, "earthquake"), 6) for m in MONTHS}
    check(len(quakes) == 1, f"earthquake chance the same every month ({c(jan, 'earthquake'):.1%})")
    conflict = simulator.COUNTRIES[country_id]["crisis"]["conflict_chance_per_month"]
    check(all(abs(c(m, "conflict") - conflict) < 1e-9 for m in MONTHS),
          f"grid attack chance fixed at the config's {conflict:.0%}")
    check(all(0 <= c(m, k) <= crisis.MAX_CHANCE for m in MONTHS for k in crisis.TYPES),
          f"every chance between 0 and {crisis.MAX_CHANCE:.0%}")


# ---------------------------------------------------------------------------
# 3. Severity 4-5 always cuts a zone; Full blackout cuts every zone
# ---------------------------------------------------------------------------
def check_blackouts(country_id):
    simulator.use_country(country_id)
    zones = len(simulator.ZONES)
    print(f"\nBlackouts, {simulator.COUNTRY['name']}:")
    missed = [(kind, sev, s) for kind in crisis.TYPES for sev in (4, 5) for m in MONTHS for s in range(50)
              if not crisis.blackouts(country_id, crisis.make_crisis(country_id, m, kind, sev, seed=s), seed=s)]
    check(not missed, f"severity 4-5 cut at least one zone in all {len(crisis.TYPES) * 2 * len(MONTHS) * 50} "
                      f"crises" + (f" (missed: {missed[:3]})" if missed else ""))
    full = [len(crisis.blackouts(country_id, crisis.make_crisis(country_id, 7, kind, sev, seed=s),
                                 seed=s, force_full=True))
            for kind in crisis.TYPES for sev in range(1, 6) for s in range(10)]
    check(all(n == zones for n in full), f"Full blackout cuts all {zones} zones, at every severity")
    # Severity 1 should rarely cut anything
    low = sum(bool(crisis.blackouts(country_id, crisis.make_crisis(country_id, 7, "earthquake", 1, seed=s), seed=s))
              for s in range(400)) / 400
    check(low < 0.15, f"severity 1 rarely cuts power ({low:.0%} of crises)")


# ---------------------------------------------------------------------------
# 4. Same seed, same result
# ---------------------------------------------------------------------------
def check_replay(country_id):
    simulator.use_country(country_id)
    print(f"\nReplay, {simulator.COUNTRY['name']}:")
    same = all(crisis.pick_random(country_id, m, seed=s) == crisis.pick_random(country_id, m, seed=s)
               for m in MONTHS for s in range(20))
    check(same, "same seed -> same random crisis")
    same = all(crisis.blackouts(country_id, crisis.make_crisis(country_id, 7, k, 3, seed=s), seed=s)
               == crisis.blackouts(country_id, crisis.make_crisis(country_id, 7, k, 3, seed=s), seed=s)
               for k in crisis.TYPES for s in range(20))
    check(same, "same seed -> same blackouts")
    c = crisis.make_crisis(country_id, 1, "windstorm", 4, seed=7)
    out = crisis.blackouts(country_id, c, seed=7)
    day1 = simulator.simulate(month=1, crisis=c, outages=out)
    day2 = simulator.simulate(month=1, crisis=c, outages=out)
    check(day1 == day2, "same seed -> exactly the same simulated day (every reading)")
    different = len({str(crisis.blackouts(country_id, crisis.make_crisis(country_id, 7, "windstorm", 3, seed=s),
                                          seed=s)) for s in range(20)})
    check(different > 3, f"different seeds give different outcomes ({different} different out of 20): Reroll works")


# ---------------------------------------------------------------------------
# 5. Fallbacks (only when data/ is hidden): everything says "simulated"
# ---------------------------------------------------------------------------
def check_fallback_labels(country_id):
    simulator.use_country(country_id)
    print(f"\nFallbacks, {simulator.COUNTRY['name']}:")
    day = weather.typical_day(country_id, 7)
    check(day["source"] == "simulated", f"weather falls back to the config ({day['label']})")
    check(not any(b.get("real") for b in simulator.critical_buildings()),
          "buildings fall back to the made-up ones from the config")
    sources = {v["source"] for v in crisis.monthly_chances(country_id, 7).values()}
    check(sources == {"simulated"}, f"crisis chances all from the config ({sources})")
    index, source = crisis.wildfire_risk_index(country_id, 7)
    check(source == "simulated", f"wildfire risk index from the config ({index}/100)")


def check_dashboard():
    """Run the dashboard (no browser) in a few modes: no errors, and the data labels say
    'simulated' when data/ is hidden."""
    from streamlit.testing.v1 import AppTest
    print("\nDashboard on fallback values:")
    for country in simulator.COUNTRIES:
        for choice, full in [(None, False), ("random", False), ("windstorm", False), ("cold_snap", True)]:
            at = AppTest.from_file(str(HERE / "app.py"), default_timeout=180)
            at.session_state.country = country
            at.session_state.now = "2026-10-17 16:00"
            at.run()
            if choice:                                   # start a crisis at 16:00, 2 hours on
                at.session_state.crisis_choice = choice
                at.session_state.crisis_severity = 4
                next(b for b in at.button if b.label == "Start crisis").click().run()
                if full:
                    at.toggle(key="full_blackout").set_value(True).run()
                for _ in range(8):
                    next(b for b in at.button if b.label == "Step").click().run()
            html = " ".join(getattr(h, "body", "") or "" for h in at.get("html"))
            labels_ok = "Weather: simulated" in html and "Buildings: simulated" in html
            check(not at.exception and labels_ok,
                  f"{country} {choice or 'no crisis'}{' + full blackout' if full else ''}: runs"
                  + ("" if labels_ok else " (but the 'simulated' labels are missing)")
                  + (f" ERROR {at.exception}" if at.exception else ""))


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def run_all():
    fallback = os.environ.get("EXPECT_FALLBACK") == "1"
    print("Crisis mode test" + (" (data/ hidden: fallback values)" if fallback else " (saved data in data/)"))
    for country_id in simulator.COUNTRIES:
        table = report(country_id)
        check_seasons(country_id, table)
        check_blackouts(country_id)
        check_replay(country_id)
        if fallback:
            check_fallback_labels(country_id)
    if fallback:
        check_dashboard()
    print(f"\n{'ALL PASSED' if not failures else f'{len(failures)} FAILED:'}")
    for f in failures:
        print("  -", f)
    return 0 if not failures else 1


def run_without_data():
    """Rename data/ out of the way, run everything on fallbacks, always rename it back."""
    if HIDDEN.exists():
        sys.exit(f"{HIDDEN.name} already exists: put it back as data/ first.")
    if not DATA.exists():
        sys.exit("data/ is missing: nothing to hide.")
    DATA.rename(HIDDEN)
    print(f"data/ renamed to {HIDDEN.name}/ for the test")
    try:
        env = dict(os.environ, EXPECT_FALLBACK="1", PYTHONIOENCODING="utf-8")
        # A fresh Python, so nothing saved in memory from the data files is reused
        code = subprocess.run([sys.executable, str(Path(__file__).resolve())], env=env, cwd=HERE).returncode
    finally:
        HIDDEN.rename(DATA)
        print(f"\n{HIDDEN.name}/ renamed back to data/ "
              f"({len(list(DATA.iterdir()))} files there)")
    return code


if __name__ == "__main__":
    if "--without-data" in sys.argv:
        sys.exit(run_without_data())
    sys.exit(run_all())
