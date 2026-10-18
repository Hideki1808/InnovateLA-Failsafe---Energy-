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
DARK_ZONE_HEX = "#6f6b67"   # a zone without grid power: shaded gray


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

  /* Status bar under the crisis controls: crisis banner (left), wildfire risk (right) */
  .status-bar {{ display: flex; justify-content: space-between; align-items: center; gap: 1rem;
                 flex-wrap: wrap; margin: .1rem 0 .5rem; padding: .5rem 1rem; background: #fff;
                 border-radius: 14px; font-size: .95rem; line-height: 1.6; }}
  .status-bar.crisis {{ border-left: 5px solid {CORAL}; }}
  .status-bar .muted {{ color: {MUTED}; margin-left: .45rem; }}
  .sev {{ color: {CORAL}; letter-spacing: .08em; }}

  /* Map credits, pulled up into the map's bottom-left corner */
  .map-credit {{ position: relative; top: -58px; z-index: 5; display: block; width: fit-content;
                 margin: 0 0 -30px .6rem;
                 padding: .1rem .55rem; border-radius: 8px; background: rgba(255,255,255,.85);
                 color: {MUTED}; font-size: .72rem; pointer-events: none; }}

  /* Dark zone battery list: one line per battery, with a small charge bar */
  .zl-facts {{ font-size: .95rem; margin: .1rem 0 .5rem; }}
  .zl {{ max-height: 330px; overflow-y: auto; }}
  .zl-row {{ display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr) 2.5em 3.4em 30px;
             gap: .3rem; align-items: center; padding: .25rem .3rem; font-size: .8rem;
             border-bottom: 1px solid {LINE}; border-left: 3px solid transparent; }}
  .zl-row.medical {{ border-left-color: {RING_HEX["medical"]}; }}
  .zl-row.building {{ border-left-color: {BUILDING_HEX}; }}
  .zl-row span {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .zl-row .t {{ color: {MUTED}; }}
  .zl-row .n {{ font-weight: 600; }}
  .zl-bar {{ height: 7px; background: #ece9e5; border-radius: 4px; overflow: hidden; }}
  .zl-bar span {{ display: block; height: 100%; border-radius: 4px; }}

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


# While a crisis is on, the map's border pulses red: slow (2 s) and faint
MAP_PULSE_CSS = f"""<style>
  @keyframes crisis-pulse {{
    0%, 100% {{ box-shadow: 0 0 0 2px {CORAL}1a; }}
    50%      {{ box-shadow: 0 0 0 7px {CORAL}55; }}
  }}
  .st-key-panel_map [data-testid="stDeckGlJsonChart"] {{
    border-radius: 14px; animation: crisis-pulse 2s ease-in-out infinite;
  }}
</style>"""


def dashed_outline(shape, dash_m=55, gap_m=35):
    """A zone's outline as short dashes, for the map's PathLayer. shape: [(lat, lon), ...].
    Returns [{"path": [[lon, lat], [lon, lat]]}, ...], one entry per dash."""
    import math
    lat0 = sum(p[0] for p in shape) / len(shape)
    m_per_lat, m_per_lon = 111_320, 111_320 * math.cos(math.radians(lat0))
    dashes = []
    for (lat1, lon1), (lat2, lon2) in zip(shape, shape[1:] + shape[:1]):
        length = math.hypot((lat2 - lat1) * m_per_lat, (lon2 - lon1) * m_per_lon)
        pos = 0.0
        while pos < length:
            a, b = pos / length, min(pos + dash_m, length) / length
            dashes.append({"path": [[lon1 + (lon2 - lon1) * a, lat1 + (lat2 - lat1) * a],
                                    [lon1 + (lon2 - lon1) * b, lat1 + (lat2 - lat1) * b]]})
            pos += dash_m + gap_m
    return dashes


def zone_battery_list(facts_html, rows):
    """The dark-zone list: a line of key facts, then one line per battery or building:
    name, type, charge %, hours left, and a small bar (colored like the map's dark-zone dots).
    rows: dicts with name, type, pct (None = unknown), hours (None = unknown), kind, pinned."""
    def hours_text(x):
        if x.get("no_backup"):
            return "no backup"
        if x.get("off"):
            return "off"                     # tripped: switched off, whatever its charge
        if x["hours"] is None:
            return "silent"
        if x["hours"] <= 0.01:
            return "out"
        return f"{x['hours'] * 60:.0f} min" if x["hours"] < 59.5 / 60 else f"{x['hours']:.1f} h"

    lines = []
    for x in rows:
        pct = x["pct"]
        color = (MUTED if pct is None else STATE_HEX[rules.NORMAL] if pct > 50
                 else STATE_HEX[rules.WATCH] if pct >= 20 else STATE_HEX[rules.NEEDS_DISPATCHER])
        pinned = x["kind"] if x["kind"] in ("medical", "building") else ""
        lines.append(
            f'<div class="zl-row {pinned}"><span class="n" title="{escape(x["name"])}">{escape(x["name"])}</span>'
            f'<span class="t" title="{escape(x["type"])}">{escape(x["type"])}</span>'
            f'<span>{"-" if pct is None else f"{pct:.0f}%"}</span><span>{hours_text(x)}</span>'
            f'<span class="zl-bar"><span style="width:{0 if pct is None else max(pct, 2):.0f}%;'
            f'background:{color}"></span></span></div>')
    return f'<div class="zl-facts">{facts_html}</div><div class="zl">{"".join(lines)}</div>'


def severity_dots(severity):
    """3 -> '●●●○○' in coral (filled dots = severity out of 5)."""
    return f'<span class="sev">{"●" * severity}{"○" * (5 - severity)}</span>'


def status_bar(crisis_html, fire_html):
    """The bar under the crisis controls: the crisis banner on the left (empty when there's
    no crisis) and the wildfire risk on the right (always)."""
    left = crisis_html or f'<span class="muted" style="margin:0">No crisis. Start one above.</span>'
    return (f'<div class="status-bar{" crisis" if crisis_html else ""}"><div>{left}</div>'
            f'<div>{fire_html}</div></div>')


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


def legend(dark=False, forecast=False):
    """What every color and shape on the map means. dark / forecast: also explain the
    dark-zone dots / the dashed outline (only while there are some)."""
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
        f"{swatch(DARK_ZONE_HEX + '99', square=True)}No grid power"
        + (f'<span class="sw" style="border:2px dashed {CORAL};background:none"></span>Outage forecast'
           if forecast else "")
        + ("<br/><b>In dark zones</b>"
           f"{swatch(STATE_HEX[rules.NORMAL])}Battery over 50%"
           f"{swatch(STATE_HEX[rules.WATCH])}20-50%"
           f"{swatch(STATE_HEX[rules.NEEDS_DISPATCHER])}Under 20% or off"
           if dark else "")
        + "</div>"
    )
