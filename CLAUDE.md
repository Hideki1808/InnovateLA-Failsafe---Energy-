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
A Streamlit dashboard with two tabs:
- **Live dispatch** (the heat-wave demo day):
  - 40 simulated homes in a small part of Wilmington (LA harbor), all on land.
    Household types: regular (some with EV + pool = flexible load), vulnerable
    (elderly / heat-vulnerable), medical. Plus 3 critical buildings: hospital, fire
    station, cold storage (made-up names, real-looking locations).
  - The region is split into **4 zones** (North Wilmington, West Wilmington, Banning
    Park, Avalon) that tile one grid section. Every home and building is in one zone.
    Each zone has a capacity; zone stress = (fleet homes + buildings + other customers)
    ÷ capacity. Strained at 80%+.
  - Rules sort batteries into Needs dispatcher / Watch / Can wait / Normal and guess
    why silent batteries went quiet (broken, tripped, just not talking).
  - **Zone relief ladder**, most strained zone first, gentlest step first: pause
    charging → batteries discharge → flexible homes delay → shed regular homes (EV/pool
    first, then street blocks of other customers) → shed vulnerable homes → critical
    buildings switch to their own backup. Medical homes are never cut. Every step needs
    the dispatcher's Approve click (cutting power needs an extra confirmation).
  - Map (pydeck) under the summary: zones lightly shaded grey / amber / red by stress,
    with names; homes colored by category; critical buildings labelled. Moves with Play.
  - Play button runs the day and pauses on new events. Rules-based summary on top.
- **Normal day earnings**: charge cheap at midday, use at the evening peak (~$128/day
  for the fleet).

Demo story: Banning Park strained from 2 PM (gentle steps are enough at first), West
Wilmington from 5 PM, Avalon from 6:15 PM; North Wilmington stays OK.

## Next

### Country switch, driven by a config file
- A dropdown in the dashboard picks the country; everything country-specific comes from
  **`config/countries.toml`** (read with Python's built-in `tomllib`, no new dependency).
- Each country section sets: name, map centre and zoom, zones (shapes + capacity),
  currency symbol, electricity prices by hour, normal home voltage (e.g. 240 V US
  split-phase vs 230 V Europe), household-type mix, and critical buildings.
- Adding a country = adding a section to the file. No code changes.
- Build order: first move the **current** Wilmington setup into the file (app looks
  the same), then add a second country and the dropdown.

### Open questions
- Which second country (or countries) should the demo show?

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

## Structure
- app.py: the dashboard (tabs: Live dispatch with the map, Normal day earnings)
- simulator.py: generates the fake fleet, zones, critical buildings and planted problems
- rules.py: decides what's normal, what can wait, what needs the dispatcher, the relief
  plan per zone and the summary
- config/countries.toml: (planned) everything country-specific
- requirements.txt: list of Python packages to install

## Conventions
- Keep code readable for a two-person team working fast.
- Small commits with clear messages.
- Ask before adding large dependencies.
- Country-specific numbers live in the config file, not in the code.
