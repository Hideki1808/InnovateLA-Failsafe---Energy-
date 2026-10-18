"""
style.py - the dashboard's look: colors, a little CSS, and small HTML helpers.

The theme itself (background, fonts, rounded corners, status colors) lives in
.streamlit/config.toml. This file only adds what the theme can't do: small uppercase
section labels, big "key number" cards, white rounded panels, and the alert list.

Look: off-white page, white rounded panels, ONE coral-red accent used sparingly
(headings, key numbers, urgent alerts), plenty of space. Built for a projector.
"""

from html import escape

import rules

# ---------------------------------------------------------------------------
# Colors (keep in step with .streamlit/config.toml)
# ---------------------------------------------------------------------------
CORAL = "#e8453c"        # the accent, and "Needs dispatcher"
FONT = "Inter Tight, Helvetica Neue, Arial, sans-serif"   # same as the theme's body font
INK = "#1c1c1e"          # text
MUTED = "#6f6b67"        # captions and labels
PAGE = "#f2f1ef"         # page background
LINE = "#e4e2df"         # hairlines


def rgb(hex_color, alpha=None):
    """'#e8453c' -> [232, 69, 60] (plus alpha if given), for the map."""
    h = hex_color.lstrip("#")
    values = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return values + [alpha] if alpha is not None else values


# Battery state colors: the same on the map, in the alerts and in the legend.
# Red means "Needs dispatcher" and nothing else; the others are far apart in hue.
STATE_HEX = {
    rules.NEEDS_DISPATCHER: CORAL,       # coral red
    rules.WATCH: "#e0a100",              # amber
    rules.CAN_WAIT: "#2f6fdb",           # blue
    rules.NORMAL: "#2e9e5b",             # green
}
# Household rings: kept away from the state colors so they never look like a state
RING_HEX = {"vulnerable": "#1c1c1e", "medical": "#7b4fd6"}   # thin ink ring, thick violet ring
BUILDING_HEX = "#4a4f5a"                                     # dark slate squares
ZONE_HEX = {"OK": "#9aa3ad", "Busy": "#f08a24", "Strained": CORAL}


# ---------------------------------------------------------------------------
# CSS: only what the theme in config.toml can't do
# ---------------------------------------------------------------------------
CSS = f"""
<style>
  /* No grey-out while the page redraws (every step of Play), so nothing flickers */
  [data-stale='true'] {{ opacity: 1 !important; transition: none !important; }}

  /* Small uppercase section labels, like "WHAT'S HAPPENING" */
  .lbl {{ font-size: .78rem; font-weight: 600; letter-spacing: .14em; text-transform: uppercase;
          color: {MUTED}; margin: 0 0 .5rem 0; }}

  /* The big coral title */
  .brand {{ font-family: "Outfit", "Inter Tight", sans-serif; font-size: 2.4rem; font-weight: 700;
            color: {CORAL}; letter-spacing: -.03em;
            line-height: 1.05; margin: 0; }}

  /* Key numbers: very large number, short caption underneath */
  .stats {{ display: grid; grid-template-columns: repeat(var(--n), 1fr); gap: 1.5rem;
            background: #fff; border-radius: 20px; padding: 1.1rem 1.8rem; }}
  .stat .num {{ font-size: 2.8rem; font-weight: 800; color: {CORAL}; line-height: 1;
                letter-spacing: -.04em; white-space: nowrap; }}
  .stat .num.ink {{ color: {INK}; }}
  .stat .cap {{ font-size: 1rem; color: {MUTED}; margin-top: .45rem; line-height: 1.25; }}

  /* White rounded panels (Streamlit containers created with key="panel_...") */
  [class*="st-key-panel_"] {{ background: #fff; border-radius: 20px; padding: 1.3rem 1.5rem; }}

  /* Status pill at the top of the side panel */
  .pill {{ display: inline-block; font-size: .75rem; font-weight: 700; letter-spacing: .12em;
           text-transform: uppercase; padding: .25rem .7rem; border-radius: 999px; }}

  /* Alert list: a colored dot, the battery, then the reason. Hairlines between. */
  .alert {{ display: grid; grid-template-columns: 16px 1fr; gap: .2rem .7rem;
            padding: .75rem 0; border-bottom: 1px solid {LINE}; }}
  .alert .dot {{ width: 12px; height: 12px; border-radius: 50%; margin-top: .45rem; }}
  .alert .who {{ font-weight: 700; }}
  .alert .meta {{ color: {MUTED}; font-weight: 400; }}
  .alert .why {{ grid-column: 2; color: {INK}; font-size: .95rem; line-height: 1.4; }}

  /* Data source tags: "Weather: real (...)" in green, "simulated" in grey, credit after */
  .sources {{ margin: .55rem 0 .1rem .3rem; font-size: .8rem; line-height: 2; }}
  .src {{ display: inline-block; padding: .1rem .65rem; border-radius: 999px; font-weight: 600;
          margin-right: .45rem; }}
  .credit {{ color: {MUTED}; margin-right: 1.3rem; }}

  /* Crisis mode: one line on what's happening, with a coral edge */
  .crisis-line {{ margin: .2rem 0 .5rem; padding: .55rem 1rem; background: #fff; border-radius: 14px;
                  border-left: 5px solid {CORAL}; font-size: .95rem; line-height: 1.6; }}

  /* Legend under the map */
  .legend {{ font-size: .95rem; color: {INK}; line-height: 2.1; }}
  .legend b {{ font-weight: 600; color: {MUTED}; font-size: .78rem; letter-spacing: .12em;
               text-transform: uppercase; margin-right: .4rem; }}
  .sw {{ display: inline-block; width: 13px; height: 13px; vertical-align: -1px;
         margin: 0 .4rem 0 1rem; }}

  /* Tabs: plain, with a coral underline on the selected one */
  [data-baseweb="tab-highlight"] {{ background-color: {CORAL} !important; }}
  [data-baseweb="tab-border"] {{ background-color: {LINE} !important; }}
  button[role="tab"] p {{ font-size: 1rem; font-weight: 600; }}

  /* The map-gesture helper frame (map_gestures.py) does its work invisibly */
  .st-key-gesture_helper {{ display: none !important; }}

  /* Expanders inside panels: no heavy box */
  [data-testid="stExpander"] details {{ border-color: {LINE}; border-radius: 14px; }}
</style>
"""


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
def label(text):
    """A small uppercase section label."""
    return f'<div class="lbl">{escape(text)}</div>'


def stats(items):
    """
    A row of key numbers. items = [(number, caption, accent), ...]
    accent=True draws the number in coral, False in ink.
    """
    cells = "".join(
        f'<div class="stat"><div class="num{"" if accent else " ink"}">{escape(str(number))}</div>'
        f'<div class="cap">{escape(caption)}</div></div>'
        for number, caption, accent in items
    )
    return f'<div class="stats" style="--n:{len(items)}">{cells}</div>'


PILL = {  # summary level -> (text, background, text color)
    "error": ("Action needed", "#fdecea", CORAL),
    "warning": ("Heads up", "#fdf5df", "#9a6b00"),
    "ok": ("All clear", "#e8f5ee", "#1f7a45"),
}


def pill(level):
    text, bg, fg = PILL[level]
    return f'<span class="pill" style="background:{bg};color:{fg}">{text}</span>'


FIRE_PILL = {  # wildfire risk level -> (background, text color)
    "Extreme": (CORAL, "#ffffff"),
    "High": ("#fdecea", CORAL),
    "Moderate": ("#fdf5df", "#9a6b00"),
    "Low": ("#e8f5ee", "#1f7a45"),
}


def fire_pill(level):
    """A small pill like "WILDFIRE RISK HIGH", colored by level."""
    bg, fg = FIRE_PILL[level]
    return f'<span class="pill" style="background:{bg};color:{fg}">Wildfire risk {escape(level)}</span>'


def alert_list(rows):
    """rows: dicts with battery_id, household_type, zone, category, reason, silent_guess."""
    out = []
    for a in rows:
        guess = f" · silent: {a['silent_guess']}" if a.get("silent_guess") else ""
        out.append(
            f'<div class="alert"><span class="dot" style="background:{STATE_HEX[a["category"]]}"></span>'
            f'<div class="who">{escape(a["battery_id"])} '
            f'<span class="meta">· {escape(a["household_type"])} home · {escape(a["zone"])}{escape(guess)}</span></div>'
            f'<div class="why">{escape(a["reason"])}</div></div>'
        )
    return "".join(out)


def sources(items):
    """
    A small line of data-source tags. items = [(label, is_real, credit), ...], e.g.
    ("Weather: real (typical October day, 2025 data)", True, "Weather: Open-Meteo").
    Real data gets a green tag, simulated a grey one; the credit follows in plain text.
    """
    out = []
    for text, real, credit in items:
        bg, fg = ("#e8f5ee", "#1f7a45") if real else ("#ecebe8", MUTED)
        out.append(f'<span class="src" style="background:{bg};color:{fg}">{escape(text)}</span>')
        if credit:
            out.append(f'<span class="credit">{escape(credit)}</span>')
    return '<div class="sources">' + "".join(out) + "</div>"


def swatch(color, ring=None, ring_px=0, square=False):
    border = f"{ring_px}px solid {ring}" if ring else "none"
    radius = "3px" if square else "50%"
    return f'<span class="sw" style="background:{color};border:{border};border-radius:{radius}"></span>'


def legend():
    grey = "#c9c6c2"
    return (
        '<div class="legend">'
        "<b>Battery</b>"
        f"{swatch(STATE_HEX[rules.NORMAL])}Normal"
        f"{swatch(STATE_HEX[rules.WATCH])}Watch"
        f"{swatch(STATE_HEX[rules.CAN_WAIT])}Can wait"
        f"{swatch(STATE_HEX[rules.NEEDS_DISPATCHER], CORAL + '55', 3)}Needs dispatcher (pulsing)<br/>"
        "<b>Household</b>"
        f"{swatch(grey)}Regular"
        f"{swatch(grey, RING_HEX['vulnerable'], 2)}Vulnerable"
        f"{swatch(grey, RING_HEX['medical'], 4)}Medical"
        f"{swatch(BUILDING_HEX, square=True)}Critical building<br/>"
        "<b>Zone</b>"
        f"{swatch(ZONE_HEX['OK'] + '55', square=True)}OK"
        f"{swatch(ZONE_HEX['Busy'] + '66', square=True)}Busy (70%+)"
        f"{swatch(ZONE_HEX['Strained'] + '66', square=True)}Strained (80%+)"
        f"{swatch('#1c1c1e99', square=True)}No grid power"
        "</div>"
    )
