"""
style.py - the dashboard's look: colors, a little CSS, and small HTML helpers.

The theme itself (background, font, corners, status colors) lives in
.streamlit/config.toml. This file adds what the theme can't do: the toolbar, square
widgets with a small title, "query value" tiles that change color by threshold (like
Datadog), a status list, one-line tables, the legend, and a shared chart style.

Look: an operations console. Cool grey page, white square widgets with thin borders,
dense but calm, one indigo accent for controls. Status colors mean the same everywhere:
green ok, amber warning, red critical. Built for a projector.
"""

from html import escape

import rules

# ---------------------------------------------------------------------------
# Colors (keep in step with .streamlit/config.toml)
# ---------------------------------------------------------------------------
ACCENT = "#4f46e5"       # indigo: controls, links, the selected tab
OK = "#22a55b"           # green
WARN = "#f0a30a"         # amber
CORAL = "#e5484d"        # red: critical ("Needs dispatcher", outages, the crisis)
INFO = "#3b82f6"         # blue
FONT = "Geist, Inter, Helvetica Neue, Arial, sans-serif"   # same as the theme's font
MONO = '"Geist Mono", ui-monospace, monospace'
INK = "#1d2129"          # text
MUTED = "#6b7280"        # captions and labels
PAGE = "#f3f4f7"         # page background
LINE = "#dfe2e8"         # thin borders
GRID = "#eef0f4"         # chart gridlines


def rgb(hex_color, alpha=None):
    """'#e5484d' -> [229, 72, 77] (plus alpha if given), for the map."""
    h = hex_color.lstrip("#")
    values = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return values + [alpha] if alpha is not None else values


# Battery state colors: the same on the map, in the alerts and in the legend.
STATE_HEX = {
    rules.NEEDS_DISPATCHER: CORAL,       # red
    rules.WATCH: WARN,                   # amber
    rules.CAN_WAIT: INFO,                # blue
    rules.NORMAL: OK,                    # green
}
# Household rings: kept away from the state colors so they never look like a state
RING_HEX = {"vulnerable": "#1d2129", "medical": "#c026d3"}   # thin ink ring, thick magenta ring
BUILDING_HEX = "#475569"                                     # slate squares
ZONE_HEX = {"OK": "#94a3b8", "Busy": "#f97316", "Strained": CORAL}
DARK_ZONE_HEX = "#4b5563"   # a zone without grid power: shaded grey
ZONE_LINE_HEX = ["#4f46e5", "#0ea5e9", "#14b8a6", "#a855f7"]   # one line color per zone in charts

# Tag colors: (background, text)
TAG = {
    "ok": ("#e3f5ea", "#15803d"),
    "warn": ("#fef3d6", "#92600a"),
    "crit": ("#fde8e8", "#b42318"),
    "info": ("#e6effe", "#1d4ed8"),
    "grey": ("#eef0f4", "#4b5563"),
    "accent": ("#eceafd", ACCENT),
    "solid": (CORAL, "#ffffff"),
}
TONE_HEX = {"ok": OK, "warn": WARN, "crit": CORAL, "info": INFO, "grey": "#94a3b8"}


# ---------------------------------------------------------------------------
# CSS: only what the theme in config.toml can't do
# ---------------------------------------------------------------------------
CSS = f"""
<style>
  /* No grey-out while the page redraws (every step of Play), so nothing flickers */
  [data-stale='true'] {{ opacity: 1 !important; transition: none !important; }}

  /* Page spacing: dense, so the map and tiles fit on a 720 px projector */
  [data-testid="stMainBlockContainer"] {{ padding: .6rem 1.2rem 1.2rem; max-width: 100%; }}
  [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {{ gap: .55rem; }}
  [data-testid="stHorizontalBlock"] {{ gap: .55rem; }}

  /* Widgets: white, square, thin border (Streamlit containers created with key="panel_...") */
  [class*="st-key-panel_"] {{ background: #fff; border: 1px solid {LINE}; border-radius: 4px;
                              padding: .6rem .75rem; gap: .45rem; }}
  .st-key-panel_top {{ padding: .35rem .7rem !important; }}
  .st-key-panel_map {{ padding: .4rem !important; }}

  /* Widget title: small and bold, with an optional grey note */
  .wt {{ font-size: .82rem; font-weight: 600; color: {INK}; margin: 0 0 .15rem; display: flex;
         align-items: baseline; gap: .5rem; }}
  .wt .ws {{ font-weight: 400; color: {MUTED}; font-size: .76rem; }}
  .lbl {{ font-size: .72rem; font-weight: 600; color: {MUTED}; margin: .2rem 0 .3rem;
          text-transform: uppercase; letter-spacing: .05em; }}

  /* Tags / chips */
  .tag {{ display: inline-block; font-size: .68rem; font-weight: 600; letter-spacing: .03em;
          text-transform: uppercase; padding: .12rem .4rem; border-radius: 3px; line-height: 1.4;
          white-space: nowrap; vertical-align: 1px; }}

  /* Toolbar: product mark and breadcrumb */
  .brand {{ display: flex; align-items: center; gap: .5rem; white-space: nowrap; margin: 0; }}
  .brand .mark {{ width: 20px; height: 20px; border-radius: 4px; background: {ACCENT}; flex: none;
                  display: grid; place-items: center; }}
  .brand .mark i {{ display: block; width: 10px; height: 10px; border: 2px solid #fff; border-radius: 2px;
                    border-right-color: transparent; }}
  .brand .name {{ font-weight: 600; font-size: .95rem; color: {INK}; }}
  .brand .crumb {{ color: {MUTED}; font-size: .9rem; }}
  .st-key-panel_top [data-testid="stMarkdownContainer"] p {{ white-space: nowrap; }}
  .st-key-panel_top button p {{ font-size: .85rem; }}

  /* Status strip: time, weather, crisis and wildfire risk */
  .status {{ display: flex; align-items: center; gap: .7rem; flex-wrap: wrap; font-size: .82rem;
             color: {INK}; padding: 0 .1rem; }}
  .status .time {{ font-family: {MONO}; font-weight: 600; font-size: .9rem; }}
  .status .sep {{ width: 1px; height: 13px; background: {LINE}; }}
  .status .muted {{ color: {MUTED}; }}
  .status .right {{ margin-left: auto; display: flex; gap: .45rem; align-items: center; }}
  .sev {{ color: {CORAL}; letter-spacing: .04em; font-size: .75rem; }}

  /* Query-value tiles (like Datadog): a title, one big number, color by threshold */
  .tiles {{ display: grid; grid-template-columns: repeat(var(--cols), 1fr); gap: .55rem; }}
  .tile {{ background: #fff; border: 1px solid {LINE}; border-radius: 4px; padding: .55rem .7rem;
           display: flex; flex-direction: column; min-height: 104px; }}
  .tile .k {{ font-size: .78rem; font-weight: 600; color: {INK}; }}
  .tile .v {{ font-family: {MONO}; font-size: 2.15rem; font-weight: 600; line-height: 1.15;
              letter-spacing: -.03em; margin-top: auto; color: {INK}; white-space: nowrap; }}
  .tile .s {{ font-size: .74rem; color: {MUTED}; white-space: nowrap; overflow: hidden;
              text-overflow: ellipsis; min-height: 1.1em; }}
  .tile.ok .v {{ color: {OK}; }}
  .tile.crit {{ background: {CORAL}; border-color: {CORAL}; }}
  .tile.crit .k, .tile.crit .v, .tile.crit .s {{ color: #fff; }}
  .tile.warn {{ background: {WARN}; border-color: {WARN}; }}
  .tile.warn .k, .tile.warn .v, .tile.warn .s {{ color: #2b1d00; }}

  /* Older key-number row (used by the Normal day tab) */
  .stats {{ display: grid; grid-template-columns: repeat(var(--n), 1fr); gap: .55rem; margin-bottom: .3rem; }}
  .stat {{ border: 1px solid {LINE}; border-radius: 4px; padding: .5rem .7rem; }}
  .stat .num {{ font-family: {MONO}; font-size: 1.5rem; font-weight: 600; color: {INK}; line-height: 1.1;
                white-space: nowrap; }}
  .stat .num:not(.ink) {{ color: {ACCENT}; }}
  .stat .cap {{ font-size: .74rem; color: {MUTED}; margin-top: .2rem; }}

  /* Status list (next steps): a colored status square, then one line */
  .mlist {{ margin: 0 !important; padding: 0 !important; list-style: none; }}
  .mlist li {{ margin: 0 !important; display: flex; gap: .55rem; align-items: baseline; padding: .42rem .1rem;
               border-bottom: 1px solid {GRID}; font-size: .86rem; line-height: 1.35; }}
  .mlist li:last-child {{ border-bottom: none; }}
  .mlist .sq {{ width: 9px; height: 9px; border-radius: 2px; flex: none; transform: translateY(1px); }}
  .mlist .more {{ color: {MUTED}; font-size: .78rem; }}

  /* One-line tables: a header row, thin lines between rows, hover highlight */
  .tbl {{ width: 100%; font-size: .84rem; }}
  .tbl .tr {{ display: grid; grid-template-columns: var(--cols); gap: .6rem; align-items: center;
              padding: .34rem .35rem; border-bottom: 1px solid {GRID}; }}
  .tbl .tr:not(.th):hover {{ background: #f7f8fb; }}
  .tbl .th {{ font-size: .72rem; font-weight: 600; color: {MUTED}; border-bottom-color: {LINE}; }}
  .tbl .tr span {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .tbl .n {{ font-weight: 600; }}
  .tbl .m {{ color: {MUTED}; }}
  .tbl .num {{ font-family: {MONO}; }}
  .tbl .dot {{ display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: .45rem;
               vertical-align: 0; }}
  .tbl .pin {{ box-shadow: inset 3px 0 0 var(--pin); }}
  .tbl .scroll {{ max-height: 360px; overflow-y: auto; }}
  .bar {{ height: 6px; background: {GRID}; border-radius: 1px; overflow: hidden; }}
  .bar span {{ display: block; height: 100%; }}
  .facts {{ display: flex; gap: .4rem; flex-wrap: wrap; margin: .1rem 0 .45rem; }}

  /* Footer: data sources and credits, small and quiet */
  .sources {{ font-size: .7rem; color: {MUTED}; line-height: 2; margin-top: .2rem; }}
  .src {{ display: inline-block; padding: .02rem .4rem; border-radius: 3px; margin-right: .3rem; }}
  .credit {{ margin-right: 1.1rem; }}

  /* Map credits, pulled up into the map's bottom-left corner */
  .map-credit {{ position: relative; top: -44px; z-index: 5; display: block; width: fit-content;
                 margin: 0 0 -30px .45rem; padding: .05rem .45rem; border-radius: 3px;
                 background: rgba(255,255,255,.88); color: {MUTED}; font-size: .64rem; pointer-events: none; }}

  /* Legend under the map: one quiet line */
  .legend {{ font-size: .74rem; color: {MUTED}; line-height: 1.9; padding: 0 .3rem; }}
  .legend b {{ font-weight: 600; color: {INK}; margin: 0 .2rem 0 .9rem; }}
  .legend b:first-child {{ margin-left: 0; }}
  .sw {{ display: inline-block; width: 9px; height: 9px; vertical-align: -1px; margin: 0 .28rem 0 .5rem; }}

  /* Tabs: plain, indigo underline on the selected one */
  [data-baseweb="tab-highlight"] {{ background-color: {ACCENT} !important; }}
  [data-baseweb="tab-border"] {{ background-color: {LINE} !important; }}
  button[role="tab"] p {{ font-size: .86rem; font-weight: 600; }}

  /* Small pill (kept for the wildfire card) */
  .pill {{ display: inline-block; font-size: .68rem; font-weight: 600; letter-spacing: .03em;
           text-transform: uppercase; padding: .12rem .4rem; border-radius: 3px; }}

  /* Charts sit flush in their widget */
  [data-testid="stVegaLiteChart"] {{ margin-top: -.2rem; }}

  /* The map-gesture helper frame (map_gestures.py) does its work invisibly */
  .st-key-gesture_helper {{ display: none !important; }}

  /* Notices (the pause note): square and compact */
  [data-testid="stAlert"] > div {{ border-radius: 4px; padding: .45rem .8rem; font-size: .84rem; }}

  /* Expanders: thin border, square */
  [data-testid="stExpander"] details {{ border-color: {LINE}; border-radius: 4px; }}
</style>
"""


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
def title(text, note=""):
    """A widget title: small and bold, with an optional grey note beside it."""
    return f'<div class="wt">{escape(text)}' + (f'<span class="ws">{escape(note)}</span>' if note else "") + "</div>"


def label(text):
    """A small grey uppercase section label (inside the settings menus)."""
    return f'<div class="lbl">{escape(text)}</div>'


def tag(text, tone="grey"):
    """A small uppercase chip, e.g. tag("Medical", "crit")."""
    bg, fg = TAG[tone]
    return f'<span class="tag" style="background:{bg};color:{fg}">{escape(str(text))}</span>'


def brand(name, crumb):
    """The toolbar's product mark, name and breadcrumb ("Home Battery Fleet / Austin")."""
    return (f'<div class="brand"><span class="mark"><i></i></span><span class="name">{escape(name)}</span>'
            f'<span class="crumb">/ {escape(crumb)}</span></div>')


def tiles(items, cols=2):
    """
    Query-value tiles. items = [(title, value, note, status), ...]
    status: "crit" (solid red), "warn" (solid amber), "ok" (green number) or "" (plain).
    """
    cards = "".join(
        f'<div class="tile {status}"><div class="k">{escape(k)}</div><div class="v">{escape(str(v))}</div>'
        f'<div class="s">{escape(s)}</div></div>'
        for k, v, s, status in items)
    return f'<div class="tiles" style="--cols:{cols}">{cards}</div>'


def stats(items):
    """A row of key numbers (Normal day tab). items = [(number, caption, accent), ...]"""
    cells = "".join(
        f'<div class="stat"><div class="num{"" if accent else " ink"}">{escape(str(number))}</div>'
        f'<div class="cap">{escape(caption)}</div></div>'
        for number, caption, accent in items
    )
    return f'<div class="stats" style="--n:{len(items)}">{cells}</div>'


PILL = {  # summary level -> (text, tag tone)
    "error": ("Action needed", "crit"),
    "warning": ("Heads up", "warn"),
    "ok": ("All clear", "ok"),
}


def pill(level):
    text, tone = PILL[level]
    return tag(text, tone)


FIRE_TONE = {"Extreme": "solid", "High": "crit", "Moderate": "warn", "Low": "ok"}


def fire_pill(level):
    """A small chip like "WILDFIRE HIGH", colored by level."""
    return tag(f"Wildfire {level}", FIRE_TONE[level])


def status_list(items, more=0):
    """Next steps as a status list. items = [(tone, html text), ...]; tone: crit/warn/info/ok.
    more = how many were left out."""
    if not items:
        return (f'<ul class="mlist"><li><span class="sq" style="background:{OK}"></span>'
                f'<span>Nothing to do right now.</span></li></ul>')
    lis = "".join(f'<li><span class="sq" style="background:{TONE_HEX[tone]}"></span><span>{text}</span></li>'
                  for tone, text in items)
    if more:
        lis += f'<li><span class="more">+{more} more in the tabs below</span></li>'
    return f'<ul class="mlist">{lis}</ul>'


# While a crisis is on, the map's border pulses red: slow (2 s) and faint
MAP_PULSE_CSS = f"""<style>
  @keyframes crisis-pulse {{
    0%, 100% {{ box-shadow: 0 0 0 1px {CORAL}33; }}
    50%      {{ box-shadow: 0 0 0 5px {CORAL}44; }}
  }}
  .st-key-panel_map [data-testid="stDeckGlJsonChart"] {{
    border-radius: 3px; animation: crisis-pulse 2s ease-in-out infinite;
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
    return OK if pct > 50 else WARN if pct >= 20 else CORAL


def zone_battery_list(facts_html, rows):
    """The outage-zone table: key facts as chips, then one line per battery or building:
    name, type, charge %, time left, and a small bar (colored like the map's dark-zone dots).
    Medical homes (magenta edge) and critical buildings (slate edge) are pinned on top.
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

    cols = "--cols: minmax(0,1.4fr) minmax(0,1fr) 4.5em 5em minmax(60px,1fr)"
    lines = ['<div class="tr th"><span>Name</span><span>Type</span><span>Charge</span>'
             '<span>Left</span><span>Level</span></div>']
    for x in rows:
        pct = x["pct"]
        pin = {"medical": RING_HEX["medical"], "building": BUILDING_HEX}.get(x["kind"])
        attrs = f' class="tr pin" style="--pin:{pin}"' if pin else ' class="tr"'
        lines.append(
            f'<div{attrs}>'
            f'<span class="n" title="{escape(x["name"])}">{escape(x["name"])}</span>'
            f'<span class="m" title="{escape(x["type"])}">{escape(x["type"])}</span>'
            f'<span class="num">{"-" if pct is None else f"{pct:.0f}%"}</span>'
            f'<span class="num">{hours_text(x)}</span>'
            f'<span class="bar"><span style="width:{0 if pct is None else max(pct, 2):.0f}%;'
            f'background:{level_hex(pct)}"></span></span></div>')
    return (f'<div class="facts">{facts_html}</div>'
            f'<div class="tbl" style="{cols}"><div class="scroll">{"".join(lines)}</div></div>')


def severity_dots(severity):
    """3 -> '●●●○○' in red (filled dots = severity out of 5)."""
    return f'<span class="sev">{"●" * severity}{"○" * (5 - severity)}</span>'


def status_line(left_parts, right_parts):
    """The status strip under the toolbar: pieces of HTML on the left (time, weather, the
    crisis), chips on the right (wildfire risk). A thin divider between left pieces."""
    left = '<span class="sep"></span>'.join(left_parts)
    return f'<div class="status">{left}<span class="right">{"".join(right_parts)}</span></div>'


def alert_lines(rows):
    """Alerts as a one-line table: state square + home, type, charge, time left, issue.
    The full reason shows when hovering the line.
    rows: dicts with category, name, type, pct (or None), hours (or None), problem, reason."""
    cols = "--cols: minmax(0,1fr) minmax(0,1fr) 4.5em 4.8em minmax(0,2.6fr)"
    lines = ['<div class="tr th"><span>Home</span><span>Type</span><span>Charge</span>'
             '<span>Left</span><span>Issue</span></div>']
    for a in rows:
        pct = "-" if a["pct"] is None else f"{a['pct']:.0f}%"
        hours = "-" if a["hours"] is None else rules.hrs(a["hours"])
        lines.append(
            f'<div class="tr" title="{escape(a["reason"])}">'
            f'<span class="n"><span class="dot" style="background:{STATE_HEX[a["category"]]}"></span>'
            f'{escape(a["name"])}</span><span class="m">{escape(a["type"])}</span>'
            f'<span class="num">{pct}</span><span class="num">{hours}</span><span>{escape(a["problem"])}</span></div>')
    return f'<div class="tbl" style="{cols}">{"".join(lines)}</div>'


def sources(items):
    """
    The footer: data-source chips and credits. items = [(label, is_real, credit), ...], e.g.
    ("Weather: real (typical October day, 2025 data)", True, "Weather: Open-Meteo").
    Real data gets a green chip, simulated a grey one; the credit follows in plain text.
    """
    out = []
    for text, real, credit in items:
        bg, fg = TAG["ok"] if real else TAG["grey"]
        out.append(f'<span class="src" style="background:{bg};color:{fg}">{escape(text)}</span>')
        if credit:
            out.append(f'<span class="credit">{escape(credit)}</span>')
    return '<div class="sources">' + "".join(out) + "</div>"


def swatch(color, ring=None, ring_px=0, square=False):
    border = f"{ring_px}px solid {ring}" if ring else "none"
    radius = "1px" if square else "50%"
    return f'<span class="sw" style="background:{color};border:{border};border-radius:{radius}"></span>'


def legend(dark=False, forecast=False):
    """What every color and shape on the map means, in one or two quiet lines.
    dark / forecast: also explain the dark-zone dots / the dashed outline (only while
    there are some)."""
    grey = "#cbd5e1"
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
           f"{swatch(OK)}over 50%"
           f"{swatch(WARN)}20-50%"
           f"{swatch(CORAL)}under 20% or off"
           if dark else "")
        + "</div>"
    )


# ---------------------------------------------------------------------------
# Charts: one shared look for every Altair chart (like a monitoring timeseries)
# ---------------------------------------------------------------------------
def chart_style(chart, height=170):
    """Thin lines, light gridlines, small grey axis labels, no chart border, legend below."""
    return (chart.properties(height=height)
            .configure(font=FONT, background="#ffffff")
            .configure_view(strokeWidth=0, fill="#ffffff")
            .configure_axis(labelColor=MUTED, titleColor=MUTED, labelFontSize=11, titleFontSize=11,
                            titleFontWeight=500, gridColor=GRID, domain=False, tickColor=GRID, tickSize=4)
            .configure_legend(orient="bottom", labelFontSize=11, labelColor=INK, title=None,
                              symbolSize=60, symbolStrokeWidth=2, columnPadding=14)
            .configure_axisX(grid=False, domain=True, domainColor=LINE, labelAngle=0))
