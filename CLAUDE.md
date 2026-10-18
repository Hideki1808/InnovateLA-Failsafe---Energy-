# CLAUDE.md

## Project
Hackathon project for the USC Dual-Use InnovateLA Hackathon.
Track 02 — Energy, with Base Power: "On the Grid".

**The user we're building for:** the dispatcher of a home-battery fleet.

**The problem:** Homes full of automated batteries are part of the grid, and critical
services (harbor, phones, cold storage) run on it. When something strains or looks odd,
the blunt move is shedding load. We're building what sits between "normal" and "shed".

**Questions our solution should answer:**
- Whose power can wait, and how would the dispatcher know?
- When a battery goes silent: is it broken, tripped, or just not talking?
- How does the same battery earn its keep on an ordinary day?

## Priorities
- A working demo by judging beats a complete system. Favor simple, visible results.
- Use simulated/mock fleet data unless we get real data from Base Power.
- Keep the dispatcher (a human) in the loop for high-impact decisions.
- Never break the live demo: each new phase must leave the app runnable.

## What's built
A Streamlit dashboard with a **country dropdown** (top right) and two tabs. Everything
country-specific comes from **`config/countries.toml`** (all values approximate):
- **United States · Austin, Texas** (Windsor Park area): $, 240 V ±5%, 20 kWh batteries,
  12-hour clock, strong AC load in a heat wave.
- **Germany · Munich** (Trudering): €, 230 V ±10%, 10 kWh batteries, 24-hour clock,
  little AC, EV wallbox + heat-pump water heater as flexible load.
- Adding a country = copying one `[countries.<id>]` block in the file and changing the
  values. No code changes (tested).

Tabs:
- **Live dispatch** (the heat-wave demo day):
  - 40 simulated homes, all on land, with household types: regular (some with flexible
    load), vulnerable (elderly / heat-vulnerable), medical. Plus 3 critical buildings:
    hospital, fire station, cold storage (made-up names).
  - The region is split into **4 zones** that tile one grid section. Each zone has a
    capacity; zone stress = (fleet homes + buildings + other customers) ÷ capacity.
    Strained at 80%+.
  - Rules sort batteries into Needs dispatcher / Watch / Can wait / Normal and guess
    why silent batteries went quiet (broken, tripped, just not talking).
  - **Zone relief ladder**, most strained zone first, gentlest step first: pause
    charging → batteries discharge → flexible homes delay → shed regular homes (flexible
    ones first, then street blocks of other customers) → shed vulnerable homes →
    critical buildings switch to their own backup. Medical homes are never cut. Every
    step needs the dispatcher's Approve click (cutting power needs an extra confirmation).
  - Look: off-white page, white rounded panels, one coral accent used sparingly
    (title, urgent key numbers, Needs dispatcher), small uppercase labels, big numbers
    with captions. Red on the map means Needs dispatcher only, with a pulsing ring.
    No emojis in the interface text.
  - Layout: key numbers on top, big map (zones shaded by stress, dots by battery state,
    rings by household type), side panel with summary + Alerts / Response ladder tabs.
    Play runs the day and pauses on new events; map updates smoothly.
- **Normal day earnings**: charge cheap at midday, use at the evening peak (Texas ~$96/day,
  Munich ~€56/day for the fleet).

Demo story (same in both countries, zone capacities tuned for it): the hospital's zone is
strained from 2 PM (gentle steps are enough at first), a second zone from 5 PM, a third
from 6:15 PM, the fourth stays OK. Nothing is strained on a normal day.

What stays in code, not config: the demo scenario (which batteries fail, the 2-8 PM heat
wave) and the general shape of a day (cheap solar 10-3, evening peak 5-9).

## Next: Crisis mode (plan)
Checkpoint before starting: commit and tag `before-crisis-mode` (on GitHub).

Replace the single scripted stress event with crises that depend on the time of year:
- **Month selector** (done for weather: the outdoor temperature follows the month's
  real typical day). Still to do: load and crisis odds follow the month too.
- (crisis.py now covers seasonal chances, forecastable vs. sudden, severity and a
  first wildfire index; next: show it in the dashboard and make it affect the grid.)
- **Seasonal crisis chances**: each country lists its crises and how likely each is per
  month (e.g. Texas: summer heat waves, winter freezes, hurricanes; Munich: winter cold
  snaps, summer storms). All numbers approximate.
- **Forecastable vs. sudden crises**: forecastable ones (heat wave, cold snap) are
  announced hours ahead so batteries can pre-charge; sudden ones (storm damage,
  earthquake, equipment failure) hit with no warning.
- (Wildfire risk index, reserves and precautionary shutoff: done, see What's built.)
- **Wildfire risk index**: a 0-100 daily score from heat, dryness and wind. High risk can
  trigger preventive power shutoffs in exposed zones.
- **Severity scale**: each crisis gets a level (1 minor to 5 extreme) that sets how hard
  it hits load, prices and outages, shown clearly on screen.
- (Random blackouts, full blackout, seed/Reroll, dark-zone runtimes, the crisis driving
  the power simulation and pre-charging: done, see the Crisis panel notes under Known gaps.)

Triage, the relief ladder and approvals keep working in crisis mode; the dispatcher
still approves every high-impact step.

## Data and reliability rules (follow these in every future change)
- **The app NEVER calls an API while running.** Only `fetch_data.py` calls APIs.
- **All fetched data is saved in `data/` and committed to git.**
- **If any saved file is missing or broken, fall back to simulated values without
  crashing.**
- **The app shows small labels saying whether each data source is real or simulated**,
  plus credits: "Weather: Open-Meteo", "Map data © OpenStreetMap contributors",
  "Earthquakes: USGS".
- **The app must run fully with Wi-Fi off.**

Known gaps today (fix as part of the crisis-mode work):
- The map's street tiles (CARTO, built on OpenStreetMap) load from the internet: with
  Wi-Fi off the map has no streets. Needs saved tiles/shapes in `data/` or a plain
  offline background, plus the "© CARTO" credit while online tiles are used.
- The fonts (Outfit, Inter Tight) load from Google Fonts: save the font files in the
  project and serve them locally (Streamlit static files) so they work offline.
- Weather is real now (weather.py reads data/, falls back to config, shows its label).
- Critical buildings are real now: simulator.py places the saved OpenStreetMap buildings
  at their real locations with real names (power use approximate by type). Made-up ones
  from the config fill in only types with no real match (hospital, cold storage), tagged
  "simulated"; if the file is missing, all made-up. Every zone gets at least 6 homes,
  none within 60 m of a building. Zone capacities retuned for the new loads.
- Wildfire risk index (crisis.py): heat x dryness x wind from the saved weather, 0-100,
  Low / Moderate / High / Extreme; per zone scaled by the config's wildfire_exposure; the
  demo day's risk = worst fire weather in the next 6 h (a heat wave is hotter and drier).
  At High/Extreme a zone's batteries keep an 80% reserve (normally 20%), and the
  dispatcher can approve a precautionary shutoff of the riskiest zone (like California's
  PSPS), with homes affected, battery runtimes and when the risk eases. Approving marks
  the zone shut off on the map; the grid effect of the outage isn't simulated yet.
- Crisis panel (top of Live dispatch): Off / Random (by the month's odds) / Pick (type +
  severity), a visible Seed (same seed = exactly the same crisis and blackouts), Reroll
  (new seed) and Full blackout. Default Off, so the normal demo is unchanged.
  crisis.blackouts(): chance of any outage by severity (1: 5%, 2: 20%, 3: 45%, 4-5:
  always), share of zones dark (about 1/2 at 4, 3/4 at 5), zones drawn weighted by type
  (wildfire: region edges x wildfire_exposure; windstorm: config overhead_lines;
  earthquake: anywhere; heat/cold: least capacity; attack: zones with critical
  buildings), restore time longer at higher severity. Dark zones show black on the map;
  the Response ladder's Blackout card lists homes, runtimes and who runs out before power
  returns (rules.blackout_report); the summary puts the blackout first.
- In crisis mode the crisis drives the simulation (simulator.simulate(crisis=, outages=)):
  the scripted heat wave / cold snap is off; a heat wave or cold snap crisis raises load
  by [crisis_effects] in the config (severity 3 values, scaled by severity / 3); during a
  forecast's warning batteries pre-charge to 95% (fast); while any crisis is on they
  don't discharge below 50% (but don't charge up to it). Dark zones draw nothing from
  the grid: each battery powers its home (up to its max kW, down to empty, can't
  charge); what it can't cover is "unserved_kw"; buildings run on their own backup.
  Crisis mode Off gives exactly the same day as before (checked).
- Dark-zone runtimes (rules.battery_runtime): stored kWh walked forward 15 min at a time
  through the home's expected need (usage + unserved), capped at the battery's max kW.
  rules.dark_zone_plan gives 4 approvable steps per dark zone: save power (30%), check on
  medical/vulnerable homes, portable backup for medical homes running out, ask the
  utility to restore the zone first. The summary recommends the most urgent first
  (medical, critical buildings, checks, saving). Triage: a home in a dark zone whose
  battery can't cover it is Watch (Needs dispatcher if critical). Approvals are recorded
  but don't change the simulation (like the relief ladder).
- The saved earthquakes are used for crisis chances, not shown on screen yet.

## Tech stack
- Python + Streamlit (web dashboard), Altair for charts, pydeck for the map
- Simulated battery fleet data (no real API), with planted problems for the demo:
  a battery that goes silent, one that trips, one that breaks, and a heat wave
- Rules-based triage and summary; AI summaries for the dispatcher only if time allows
- I'm a beginner: explain what you're doing in plain language, keep the code simple,
  and tell me exactly what to type when I need to run something

## Commands
- Install: pip install -r requirements.txt
- Run: streamlit run app.py
- Check the rules on their own: python rules.py
- Simulate every country and print a summary: python simulator.py
- Download real data into data/ (needs internet, run before the demo): python fetch_data.py

## Structure
- app.py: the dashboard (tabs: Live dispatch with the map, Normal day earnings)
- simulator.py: generates the fake fleet, zones, critical buildings and planted problems
- rules.py: decides what's normal, what can wait, what needs the dispatcher, the relief
  plan per zone and the summary
- config/countries.toml: everything country-specific (all values approximate)
- style.py: the look (colors, a little CSS, stat cards, labels, alert list, legend)
- map_gestures.py: trackpad gestures on the map (two-finger slide moves it, pinch zooms)
- fetch_data.py: the ONLY file that calls APIs. Run once before the demo:
  python fetch_data.py (weather, OSM critical buildings, USGS earthquakes per country)
- data/: the fetched data (weather_*, buildings_*, earthquakes_* per country), committed to git
- crisis.py: the six crisis types (heat wave, cold snap, windstorm, earthquake, wildfire,
  grid attack): chance per country/month from the saved data (config fallback),
  forecastable or not, severity 1-5, random pick and manual pick, wildfire index, and
  seeded random blackouts by zone (shown in the app's Crisis panel).
- weather.py: typical day of weather for the chosen country and month: real from data/,
  or approximate monthly values from config/countries.toml if the file is missing or broken
- .streamlit/config.toml: the theme (off-white page, white rounded panels, coral accent;
  fonts: Outfit for the title, Inter Tight for everything else)
- requirements.txt: list of Python packages to install

## Conventions
- Keep code readable for a two-person team working fast.
- Small commits with clear messages.
- Ask before adding large dependencies.
- Country-specific numbers live in the config file, not in the code.
