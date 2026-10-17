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

## Structure
- app.py: the dashboard (tabs: Live dispatch with the map, Normal day earnings)
- simulator.py: generates the fake fleet, zones, critical buildings and planted problems
- rules.py: decides what's normal, what can wait, what needs the dispatcher, the relief
  plan per zone and the summary
- config/countries.toml: everything country-specific (all values approximate)
- style.py: the look (colors, a little CSS, stat cards, labels, alert list, legend)
- map_gestures.py: trackpad gestures on the map (two-finger slide moves it, pinch zooms)
- .streamlit/config.toml: the theme (off-white page, white rounded panels, coral accent;
  fonts: Outfit for the title, Inter Tight for everything else)
- requirements.txt: list of Python packages to install

## Conventions
- Keep code readable for a two-person team working fast.
- Small commits with clear messages.
- Ask before adding large dependencies.
- Country-specific numbers live in the config file, not in the code.
