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

## What's built (checkpoint: "working version before map", on `main`)
A Streamlit dashboard with two tabs:
- **Live dispatch**: 40 simulated homes in the LA harbor area over one day with a
  heat wave. Rules sort batteries into Needs dispatcher / Watch / Can wait / Normal,
  guess why silent batteries went quiet (broken, tripped, just not talking), and
  propose a grid relief plan (pause charging → discharge → flexible homes wait → shed
  lowest priority). Each step needs the dispatcher's Approve click. Play button runs
  the day and pauses on new events. A rules-based summary sits at the top.
- **Normal day earnings**: charge cheap at midday, use at the evening peak (~$128/day
  for the fleet).

## Next: the map version (plan)

### 1. Interactive map
- New first tab, **Map**, showing every home, generator and critical building.
- Use **pydeck** (already installed with Streamlit, no new dependency).
- Dots colored by rules category (Needs dispatcher / Watch / Can wait / Normal);
  icons or shapes for generators and critical buildings so color is never the only cue.
- Hover a dot: home type, battery status and the rules' reason.
- Moves with the existing time slider and Play button.
- Lines from each generator to the homes it serves.

### 2. Generators serving groups of homes
- The grid is split into **generators** (think: a local substation or feeder), each
  serving a group of homes and critical buildings, with its own capacity in kW.
- Grid stress is worked out **per generator** (load ÷ capacity), not one number for
  the whole city. The heat wave hits some generators harder than others.
- The relief plan runs per generator: only the homes on a strained generator are asked
  to help or wait. The summary names the strained generator(s).
- Demo story: one generator goes over capacity while its neighbour is fine.

### 3. Household types
Replace today's five types with a fuller set, each with its own usage pattern, how much
load can wait, and its place in the wait order:
- Medical equipment at home (critical, waits last)
- Elderly / heat-vulnerable (critical during heat waves)
- Family household (normal)
- Work-from-home (normal, busy daytime)
- EV + pool (flexible, waits first)
- Small home business (normal)
Exact list and numbers come from the config file (see 5).

### 4. Critical buildings
Non-household sites on the map, always protected (never shed, served first):
- Hospital / clinic
- Harbor / port operations
- Cell-phone tower
- Cold storage / pharmacy
- Water pumping station
- Fire / police station
Each has its own load and may have its own backup battery. They show in alerts and the
summary when the generator feeding them is strained.

### 5. Country switch, driven by a config file
- A dropdown in the dashboard picks the country; everything country-specific comes from
  **`config/countries.toml`** (read with Python's built-in `tomllib`, no new dependency).
- Each country section sets: name, map centre and zoom, neighbourhood names, currency
  symbol, electricity prices by hour, normal home voltage (e.g. 240 V US split-phase vs
  230 V Europe), household-type mix, critical buildings, and generators.
- Adding a country = adding a section to the file. No code changes.
- Sketch of the format:
  ```toml
  [usa]
  name = "United States (Los Angeles harbor)"
  map_center = [33.74, -118.27]
  currency = "$"
  voltage = 240
  prices = { cheap = 0.08, normal = 0.15, peak = 0.35, heat_wave_peak = 0.90 }

  [[usa.generators]]
  name = "San Pedro substation"
  location = [33.74, -118.29]
  capacity_kw = 250

  [usa.household_mix]
  medical = 1
  family = 6
  flexible = 3
  ```

### Build order (keep the app runnable after each step)
1. Config file + loader, with the **current** LA setup moved into it. App looks the same.
2. Generators and per-generator stress in `simulator.py` and `rules.py`.
3. Household types and critical buildings.
4. Map tab.
5. Second country in the config + the country dropdown.

### Open questions
- Which second country (or countries) should the demo show?
- Real-looking coordinates for the LA harbor sites, or a stylised made-up town?

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
- app.py: the dashboard (tabs: Live dispatch, Normal day earnings; Map coming)
- simulator.py: generates the fake fleet and planted problems
- rules.py: decides what's normal, what can wait, what needs the dispatcher, the relief
  plan and the summary
- config/countries.toml: (planned) everything country-specific
- requirements.txt: list of Python packages to install

## Conventions
- Keep code readable for a two-person team working fast.
- Small commits with clear messages.
- Ask before adding large dependencies.
- Country-specific numbers live in the config file, not in the code.
