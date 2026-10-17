# Home Battery Fleet: dispatcher dashboard

Hackathon project for the **USC Dual-Use InnovateLA Hackathon**, Track 02 (Energy, with
Base Power): *"On the Grid"*.

A dashboard for the dispatcher of a fleet of home batteries. It shows the fleet on a map,
flags batteries that look odd, and suggests gentle steps (pause charging, batteries help
the grid, flexible homes wait) **before** anyone reaches for load shedding. Every step
needs the dispatcher's approval, and medical homes and critical buildings are protected
last.

All data is **simulated**. Country numbers (prices, voltages, loads) are approximate and
live in `config/countries.toml`.

## What it answers

- **Whose power can wait, and how would the dispatcher know?** Homes are sorted by
  household type (flexible load first, medical last), and each grid zone gets its own
  step-by-step relief plan.
- **When a battery goes silent: is it broken, tripped, or just not talking?** The rules
  compare the battery with the home's utility meter, which keeps reporting.
- **How does the same battery earn its keep on an ordinary day?** The "Normal day
  earnings" tab: charge when power is cheap, use it at the evening peak.

## Run it

You need Python 3.11 or newer.

```
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501. Pick a country at the top right (Austin, Texas or
Munich, Germany) and press **Play** to run the demo day.

## Files

| File | What it does |
|---|---|
| `app.py` | The dashboard |
| `simulator.py` | Makes up the fleet, zones, critical buildings, and the planted problems |
| `rules.py` | Decides what's normal, what can wait, what needs the dispatcher, the relief plan and the summary |
| `style.py` | Colors, a little CSS, and small display helpers |
| `map_gestures.py` | Trackpad gestures on the map (two-finger slide moves it, pinch zooms) |
| `config/countries.toml` | Everything country-specific. Add a country by copying one block |
| `.streamlit/config.toml` | The theme (colors, fonts, rounded corners) |
| `CLAUDE.md` | Project notes and plan |
