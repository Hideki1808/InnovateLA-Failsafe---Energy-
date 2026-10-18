"""
style.py - the dashboard's look: colors, a little CSS, and small HTML helpers.

The theme itself (background, fonts, corners, status colors) lives in
.streamlit/config.toml. This file only adds what the theme can't do: the slim header,
metric cards, small monospace tags, one-line tables and the legend.

Look: minimal and calm. Light grey page, white cards with thin borders, deep forest-green
ink and buttons, a soft mint accent, small monospace uppercase labels. Red is for alarms
only. Built for a projector.
"""

from html import escape

import rules

# ---------------------------------------------------------------------------
# Colors (keep in step with .streamlit/config.toml)
# ---------------------------------------------------------------------------
FOREST = "#123d1f"       # the brand: buttons, title, the selected tab
MINT = "#d4f5cf"         # soft accent tint
MINT_INK = "#1d6b2c"     # text on mint
CORAL = "#e5484d"        # alarms only: "Needs dispatcher", outages, the crisis
FONT = "Inter, Helvetica Neue, Arial, sans-serif"   # same as the theme's body font
HEAD = '"Hanken Grotesk", Inter, sans-serif'        # headings and big numbers
MONO = '"JetBrains Mono", ui-monospace, monospace'   # small uppercase tags
INK = "#0f2416"          # text
MUTED = "#6b7069"        # captions and labels
PAGE = "#f5f6f3"         # page background
LINE = "#e3e6e0"         # thin borders


def rgb(hex_color, alpha=None):
    """'#e5484d' -> [229, 72, 77] (plus alpha if given), for the map."""
    h = hex_color.lstrip("#")
    values = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return values + [alpha] if alpha is not None else values


# Battery state colors: the same on the map, in the alerts and in the legend.
# Red means "Needs dispatcher" (and, in dark zones, a nearly empty battery).
STATE_HEX = {
    rules.NEEDS_DISPATCHER: CORAL,       # red
    rules.WATCH: "#d99a00",              # amber
    rules.CAN_WAIT: "#2f6fdb",           # blue
    rules.NORMAL: "#2e9e5b",             # green
}
# Household rings: kept away from the state colors so they never look like a state
RING_HEX = {"vulnerable": "#0f2416", "medical": "#7b4fd6"}   # thin ink ring, thick violet ring
BUILDING_HEX = "#3d4a41"                                     # dark slate-green squares
ZONE_HEX = {"OK": "#9aa39c", "Busy": "#f08a24", "Strained": CORAL}
DARK_ZONE_HEX = "#5f655e"   # a zone without grid power: shaded grey

# Tag colors: (background, text)
TAG = {
    "mint": (MINT, MINT_INK),
    "red": ("#fde2e2", "#b42318"),
    "amber": ("#fdf3d8", "#8a6100"),
    "grey": ("#eef0ec", "#4b5148"),
    "dark": (FOREST, "#ffffff"),
    "violet": ("#efe8fc", "#5b34b5"),
}


# ---------------------------------------------------------------------------
# CSS: only what the theme in config.toml can't do
# ---------------------------------------------------------------------------
CSS = f"""
<style>
  /* No grey-out while the page redraws (every step of Play), so nothing flickers */
  [data-stale='true'] {{ opacity: 1 !important; transition: none !important; }}

  /* Page spacing: compact, so the map fits on a 720 px projector */
  [data-testid="stMainBlockContainer"] {{ padding-top: 1rem; padding-bottom: 1.2rem; }}
  [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {{ gap: .65rem; }}

  /* White cards with a thin border (Streamlit containers created with key="panel_...") */
  [class*="st-key-panel_"] {{ background: #fff; border: 1px solid {LINE}; border-radius: 12px;
                              padding: 1rem 1.1rem; }}
  .st-key-panel_top {{ padding: .55rem 1rem !important; }}
  .st-key-panel_map {{ padding: .6rem !important; }}

  /* Small monospace uppercase labels and tags, like "NEXT STEPS" */
  .lbl {{ font-family: {MONO}; font-size: .68rem; font-weight: 600; letter-spacing: .08em;
          text-transform: uppercase; color: {MUTED}; margin: 0 0 .45rem 0; }}
  .tag {{ display: inline-block; font-family: {MONO}; font-size: .66rem; font-weight: 600;
          letter-spacing: .06em; text-transform: uppercase; padding: .16rem .45rem;
          border-radius: 4px; line-height: 1.4; vertical-align: 1px; white-space: nowrap; }}

  /* The header: logo mark, name and region tag */
  .brand {{ display: flex; align-items: center; gap: .55rem; margin: 0; white-space: nowrap; }}
  .brand .mark {{ width: 22px; height: 22px; border-radius: 5px; background: {FOREST};
                  position: relative; flex: none; }}
  .brand .mark::after {{ content: ""; position: absolute; left: 6px; top: 5px; width: 4px; height: 12px;
                         background: {MINT}; border-radius: 1px; box-shadow: 6px 4px 0 -0px {MINT}; }}
  .brand .name {{ font-family: {HEAD}; font-size: 1.15rem; font-weight: 700; color: {INK};
                  letter-spacing: -.01em; }}
  .st-key-panel_top [data-testid="stMarkdownContainer"] p {{ white-space: nowrap; }}

  /* The status line: time, weather, crisis and wildfire risk as one quiet row of tags */
  .status {{ display: flex; align-items: center; gap: .55rem; flex-wrap: wrap; font-size: .9rem;
             color: {INK}; padding: .1rem .2rem; }}
  .status .time {{ font-family: {HEAD}; font-weight: 700; font-size: 1.05rem; }}
  .status .sep {{ width: 1px; height: 14px; background: {LINE}; }}
  .status .muted {{ color: {MUTED}; }}
  .status .right {{ margin-left: auto; display: flex; gap: .45rem; align-items: center; }}
  .sev {{ color: {CORAL}; letter-spacing: .06em; font-size: .8rem; }}

  /* Metric cards: a small label on top, one big number, a short note */
  .metrics {{ display: grid; grid-template-columns: repeat(var(--n), 1fr); gap: .65rem; }}
  .metric {{ background: #fff; border: 1px solid {LINE}; border-radius: 12px; padding: .7rem 1rem; }}
  .metric .k {{ font-family: {MONO}; font-size: .66rem; font-weight: 600; letter-spacing: .08em;
                text-transform: uppercase; color: {MUTED}; }}
  .metric .v {{ font-family: {HEAD}; font-size: 2rem; font-weight: 700; line-height: 1.1;
                letter-spacing: -.02em; color: {INK}; margin-top: .2rem; white-space: nowrap; }}
  .metric .s {{ font-size: .8rem; color: {MUTED}; white-space: nowrap; overflow: hidden;
                text-overflow: ellipsis; min-height: 1.1em; }}
  .metric.alarm {{ border-color: #f6c9ca; }}
  .metric.alarm .v {{ color: {CORAL}; }}
  .metric.dark {{ background: {FOREST}; border-color: {FOREST}; }}
  .metric.dark .k, .metric.dark .s {{ color: {MINT}; }}
  .metric.dark .v {{ color: #fff; }}

  /* Older key-number row (used by the Normal day tab) */
  .stats {{ display: grid; grid-template-columns: repeat(var(--n), 1fr); gap: 1rem; margin-bottom: .4rem; }}
  .stat .num {{ font-family: {HEAD}; font-size: 1.7rem; font-weight: 700; color: {FOREST}; line-height: 1;
                white-space: nowrap; }}
  .stat .num.ink {{ color: {INK}; }}
  .stat .cap {{ font-size: .8rem; color: {MUTED}; margin-top: .3rem; }}

  /* Next steps: numbered one-liners */
  .steps {{ margin: 0 !important; padding: 0 !important; list-style: none; }}
  .steps li {{ margin: 0 !important; display: flex; gap: .6rem; align-items: baseline; padding: .4rem 0;
               border-bottom: 1px solid {LINE}; font-size: .92rem; line-height: 1.35; }}
  .steps li:last-child {{ border-bottom: none; }}
  .steps .no {{ font-family: {MONO}; font-size: .68rem; font-weight: 600; color: #fff;
                background: {FOREST}; border-radius: 4px; padding: .05rem .38rem; flex: none; }}
  .steps .more {{ color: {MUTED}; font-size: .82rem; }}

  /* One-line tables (alerts, outage zone): a header row, thin lines between rows */
  .tbl {{ width: 100%; font-size: .88rem; }}
  .tbl .tr {{ display: grid; grid-template-columns: var(--cols); gap: .5rem; align-items: center;
              padding: .38rem .2rem; border-bottom: 1px solid {LINE}; }}
  .tbl .th {{ font-family: {MONO}; font-size: .64rem; font-weight: 600; letter-spacing: .08em;
              text-transform: uppercase; color: {MUTED}; padding-top: 0; }}
  .tbl .tr span {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .tbl .n {{ font-weight: 600; }}
  .tbl .m {{ color: {MUTED}; }}
  .tbl .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: .45rem;
               vertical-align: 1px; }}
  .tbl .pin {{ box-shadow: inset 3px 0 0 var(--pin); }}
  .tbl .scroll {{ max-height: 340px; overflow-y: auto; }}
  .bar {{ height: 6px; background: #eceee9; border-radius: 3px; overflow: hidden; }}
  .bar span {{ display: block; height: 100%; border-radius: 3px; }}
  .facts {{ display: flex; gap: .45rem; flex-wrap: wrap; margin: .2rem 0 .55rem; }}

  /* Footer: data sources and credits, small and quiet */
  .sources {{ font-family: {MONO}; font-size: .66rem; color: {MUTED}; letter-spacing: .02em;
              line-height: 2; margin-top: .3rem; }}
  .src {{ display: inline-block; padding: .05rem .45rem; border-radius: 4px; margin-right: .3rem; }}
  .credit {{ margin-right: 1.1rem; }}

  /* Map credits, pulled up into the map's bottom-left corner */
  .map-credit {{ position: relative; top: -50px; z-index: 5; display: block; width: fit-content;
                 margin: 0 0 -30px .5rem; padding: .1rem .5rem; border-radius: 4px;
                 background: rgba(255,255,255,.88); color: {MUTED}; font-family: {MONO};
                 font-size: .62rem; pointer-events: none; }}

  /* Legend under the map: one quiet line */
  .legend {{ font-size: .76rem; color: {MUTED}; line-height: 1.9; padding: .1rem .3rem 0; }}
  .legend b {{ font-family: {MONO}; font-weight: 600; font-size: .62rem; letter-spacing: .08em;
               text-transform: uppercase; margin: 0 .3rem 0 .9rem; color: {INK}; }}
  .legend b:first-child {{ margin-left: 0; }}
  .sw {{ display: inline-block; width: 10px; height: 10px; vertical-align: -1px; margin: 0 .3rem 0 .55rem; }}

  /* Tabs: plain, with a forest-green underline on the selected one */
  [data-baseweb="tab-highlight"] {{ background-color: {FOREST} !important; }}
  [data-baseweb="tab-border"] {{ background-color: {LINE} !important; }}
  button[role="tab"] p {{ font-size: .88rem; font-weight: 600; }}

  /* Small pill (kept for the wildfire card) */
  .pill {{ display: inline-block; font-family: {MONO}; font-size: .66rem; font-weight: 600;
           letter-spacing: .06em; text-transform: uppercase; padding: .16rem .45rem; border-radius: 4px; }}

  /* The map-gesture helper frame (map_gestures.py) does its work invisibly */
  .st-key-gesture_helper {{ display: none !important; }}

  /* Expanders: thin border, small corners */
  [data-testid="stExpander"] details {{ border-color: {LINE}; border-radius: 10px; }}
</style>
"""


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
def label(text):
    """A small monospace uppercase section label."""
    return f'<div class="lbl">{escape(text)}</div>'


def tag(text, tone="grey"):
    """A small monospace uppercase tag, e.g. tag("Medical", "violet")."""
    bg, fg = TAG[tone]
    return f'<span class="tag" style="background:{bg};color:{fg}">{escape(str(text))}</span>'


def brand(name, region):
    """The header: a small logo mark, the name and a region tag."""
    return (f'<div class="brand"><span class="mark"></span><span class="name">{escape(name)}</span>'
            f'{tag(region, "mint")}</div>')


def metrics(items):
    """
    A row of metric cards. items = [(label, value, note, tone), ...]
    tone: "" (plain), "alarm" (red number) or "dark" (forest-green card).
    """
    cards = "".join(
        f'<div class="metric {tone}"><div class="k">{escape(k)}</div><div class="v">{escape(str(v))}</div>'
        f'<div class="s">{escape(s)}</div></div>'
        for k, v, s, tone in items)
    return f'<div class="metrics" style="--n:{len(items)}">{cards}</div>'


def stats(items):
    """A row of key numbers (Normal day tab). items = [(number, caption, accent), ...]"""
    cells = "".join(
        f'<div class="stat"><div class="num{"" if accent else " ink"}">{escape(str(number))}</div>'
        f'<div class="cap">{escape(caption)}</div></div>'
        for number, caption, accent in items
    )
    return f'<div class="stats" style="--n:{len(items)}">{cells}</div>'


PILL = {  # summary level -> (text, tag tone)
    "error": ("Action needed", "red"),
    "warning": ("Heads up", "amber"),
    "ok": ("All clear", "mint"),
}


def pill(level):
    text, tone = PILL[level]
    return tag(text, tone)


FIRE_TONE = {"Extreme": "red", "High": "red", "Moderate": "amber", "Low": "mint"}


def fire_pill(level):
    """A small tag like "WILDFIRE HIGH", colored by level."""
    return tag(f"Wildfire {level}", FIRE_TONE[level])


def steps_list(items, more=0):
    """Next steps: numbered one-liners. items = [text, ...]; more = how many are left out."""
    if not items:
        return f'<ul class="steps"><li><span class="more">Nothing to do right now.</span></li></ul>'
    lis = "".join(f'<li><span class="no">{i}</span><span>{text}</span></li>' for i, text in enumerate(items, 1))
    if more:
        lis += f'<li><span class="more">+{more} more in the tabs below</span></li>'
    return f'<ul class="steps">{lis}</ul>'


# While a crisis is on, the map's border pulses red: slow (2 s) and faint
MAP_PULSE_CSS = f"""<style>
  @keyframes crisis-pulse {{
    0%, 100% {{ box-shadow: 0 0 0 1px {CORAL}22; }}
    50%      {{ box-shadow: 0 0 0 6px {CORAL}44; }}
  }}
  .st-key-panel_map [data-testid="stDeckGlJsonChart"] {{
    border-radius: 8px; animation: crisis-pulse 2s ease-in-out infinite;
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


def level_hex(pct):
    """Battery level color: green over 50%, amber 20-50%, red under 20%, grey if unknown."""
    if pct is None:
        return MUTED
    return STATE_HEX[rules.NORMAL] if pct > 50 else STATE_HEX[rules.WATCH] if pct >= 20 else CORAL


def zone_battery_list(facts_html, rows):
    """The outage-zone table: key facts as tags, then one line per battery or building:
    name, type, charge %, time left, and a small bar (colored like the map's dark-zone dots).
    Medical homes (violet edge) and critical buildings (slate edge) are pinned on top.
    rows: dicts with name, type, pct (None = unknown), hours (None = unknown), kind, pinned."""
    def hours_text(x):
        if x.get("no_backup"):
            return "no backup"
        if x.get("off"):
            return "off"                     # tripped: switched off, whatever its charge
        if x["hours"] is None:
            return "silent"
        if x["hours"] <= 0.01:
            return "empty"
        return rules.hrs(x["hours"])

    cols = "--cols: minmax(0,1.3fr) minmax(0,1fr) 3em 4.4em 44px"
    lines = [f'<div class="tr th"><span>Name</span><span>Type</span><span>Charge</span>'
             f'<span>Left</span><span></span></div>']
    for x in rows:
        pct = x["pct"]
        pin = {"medical": RING_HEX["medical"], "building": BUILDING_HEX}.get(x["kind"])
        pin_attr = f' class="tr pin" style="--pin:{pin}"' if pin else ' class="tr"'
        lines.append(
            f'<div{pin_attr}>'
            f'<span class="n" title="{escape(x["name"])}">{escape(x["name"])}</span>'
            f'<span class="m" title="{escape(x["type"])}">{escape(x["type"])}</span>'
            f'<span>{"-" if pct is None else f"{pct:.0f}%"}</span><span>{hours_text(x)}</span>'
            f'<span class="bar"><span style="width:{0 if pct is None else max(pct, 2):.0f}%;'
            f'background:{level_hex(pct)}"></span></span></div>')
    return (f'<div class="facts">{facts_html}</div>'
            f'<div class="tbl" style="{cols}"><div class="scroll">{"".join(lines)}</div></div>')


def severity_dots(severity):
    """3 -> '●●●○○' in red (filled dots = severity out of 5)."""
    return f'<span class="sev">{"●" * severity}{"○" * (5 - severity)}</span>'


def status_line(left_parts, right_parts, crisis=False):
    """The quiet status row under the header: pieces of HTML on the left (time, weather,
    the crisis), tags on the right (wildfire risk). A thin divider between left pieces."""
    left = '<span class="sep"></span>'.join(left_parts)
    return (f'<div class="status">{left}<span class="right">{"".join(right_parts)}</span></div>')


def alert_lines(rows):
    """Alerts as a one-line table: state dot + home, type, charge, time left, issue.
    The full reason shows when hovering the line.
    rows: dicts with category, name, type, pct (or None), hours (or None), problem, reason."""
    cols = "--cols: minmax(0,1.15fr) minmax(0,1fr) 3em 4em minmax(0,1.9fr)"
    lines = ['<div class="tr th"><span>Home</span><span>Type</span><span>Charge</span>'
             '<span>Left</span><span>Issue</span></div>']
    for a in rows:
        pct = "-" if a["pct"] is None else f"{a['pct']:.0f}%"
        hours = "-" if a["hours"] is None else rules.hrs(a["hours"])
        lines.append(
            f'<div class="tr" title="{escape(a["reason"])}">'
            f'<span class="n"><span class="dot" style="background:{STATE_HEX[a["category"]]}"></span>'
            f'{escape(a["name"])}</span><span class="m">{escape(a["type"])}</span>'
            f'<span>{pct}</span><span>{hours}</span><span>{escape(a["problem"])}</span></div>')
    return f'<div class="tbl" style="{cols}">{"".join(lines)}</div>'


def sources(items):
    """
    The footer: data-source tags and credits. items = [(label, is_real, credit), ...], e.g.
    ("Weather: real (typical October day, 2025 data)", True, "Weather: Open-Meteo").
    Real data gets a mint tag, simulated a grey one; the credit follows in plain text.
    """
    out = []
    for text, real, credit in items:
        bg, fg = TAG["mint"] if real else TAG["grey"]
        out.append(f'<span class="src" style="background:{bg};color:{fg}">{escape(text)}</span>')
        if credit:
            out.append(f'<span class="credit">{escape(credit)}</span>')
    return '<div class="sources">' + "".join(out) + "</div>"


def swatch(color, ring=None, ring_px=0, square=False):
    border = f"{ring_px}px solid {ring}" if ring else "none"
    radius = "2px" if square else "50%"
    return f'<span class="sw" style="background:{color};border:{border};border-radius:{radius}"></span>'


def legend(dark=False, forecast=False):
    """What every color and shape on the map means, in one or two quiet lines.
    dark / forecast: also explain the dark-zone dots / the dashed outline (only while
    there are some)."""
    grey = "#c9ccc6"
    return (
        '<div class="legend">'
        "<b>Battery</b>"
        f"{swatch(STATE_HEX[rules.NORMAL])}Normal"
        f"{swatch(STATE_HEX[rules.WATCH])}Watch"
        f"{swatch(STATE_HEX[rules.CAN_WAIT])}Can wait"
        f"{swatch(STATE_HEX[rules.NEEDS_DISPATCHER], CORAL + '55', 3)}Needs dispatcher"
        "<b>Home</b>"
        f"{swatch(grey, RING_HEX['vulnerable'], 2)}Vulnerable"
        f"{swatch(grey, RING_HEX['medical'], 3)}Medical"
        f"{swatch(BUILDING_HEX, square=True)}Critical building"
        "<b>Zone</b>"
        f"{swatch(ZONE_HEX['Busy'] + '66', square=True)}Busy 70%+"
        f"{swatch(ZONE_HEX['Strained'] + '66', square=True)}Strained 80%+"
        f"{swatch(DARK_ZONE_HEX + '99', square=True)}No grid"
        + (f'<span class="sw" style="border:2px dashed {CORAL};background:none"></span>Outage forecast'
           if forecast else "")
        + ("<b>Dark zones</b>"
           f"{swatch(STATE_HEX[rules.NORMAL])}over 50%"
           f"{swatch(STATE_HEX[rules.WATCH])}20-50%"
           f"{swatch(CORAL)}under 20% or off"
           if dark else "")
        + "</div>"
    )
