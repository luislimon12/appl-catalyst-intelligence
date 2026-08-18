"""
Page 1 — Market Overview
AAPL & INTC Catalyst Intelligence Dashboard

Session 3 (Jun 2026):
  Goal 2 — IV Rank Gauge
  Goal 3 — PCR Table
  Goal 4 — GEX Bar Chart
"""

import sys
from pathlib import Path

# Add dashboard folder to path so utils.py is importable from pages/ too
sys.path.insert(0, str(Path(__file__).parent))

import pandas
import plotly.graph_objects as go
import streamlit as st

from utils import (
    CATALYST_EVENTS, DARK_THEME_CSS,
    format_expiry, get_spot_price, pcr_color,
    bull_color, bear_color, render_page_header,
    query, render_sidebar,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Market Overview · Catalyst Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
ticker, refresh_secs = render_sidebar("Market Overview")

# ── Header ────────────────────────────────────────────────────────────────────
render_page_header("📈", "Market Overview", "IV Rank · Put/Call Ratio · Gamma Exposure", ticker)

# ── IV Rank ───────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)  ## cache 5 min — gold_iv_rank only changes when pipeline runs
def get_iv_rank_data(ticker: str):
    ## single cached fetch shared by render_iv_gauge() and render_iv_cards()
    ## without this both functions independently queried gold_iv_rank = 2 DB calls per render
    return query("SELECT * FROM gold_iv_rank WHERE ticker = ?", [ticker])

def render_iv_gauge(ticker: str):
    ## gauge chart only — metric cards moved to render_iv_cards() in wider column
    df = get_iv_rank_data(ticker)  ## hits cache after first call — no second DB query
    if df.empty:                                                           ## no data yet — show warning and exit
        st.warning(f"No IV rank data for {ticker} yet.")
        return

    row      = df.iloc[0]          ## grab the single row as a pandas Series
    iv_rank  = row["iv_rank"]      ## 0.0–1.0 normalized rank (0 = lowest IV ever, 1 = highest)
    rank_pct = iv_rank * 100       ## convert to percentage for gauge display (0–100)

    if rank_pct < 25:   bar_color = "#2ea043"   ## green  = low IV — options cheap relative to history
    elif rank_pct < 50: bar_color = "#d29922"   ## yellow = moderate IV
    elif rank_pct < 75: bar_color = "#e3b341"   ## orange = elevated IV
    else:               bar_color = "#f85149"   ## red    = high IV — options expensive

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",                ## show arc gauge + number in center + delta vs reference
        value=round(rank_pct, 1),                 ## the needle position = current IV rank %
        title={"text": "IV Rank", "font": {"color": "#58a6ff", "size": 16}},   ## chart title in blue
        number={"suffix": "%", "font": {"color": "#e0e0e0", "size": 36}},       ## large number in center
        delta={"reference": 50,                   ## compare to 50% = midpoint of historical range
               "increasing": {"color": "#f85149"},  ## above 50% = red (IV rising toward expensive)
               "decreasing": {"color": "#2ea043"},  ## below 50% = green (IV falling toward cheap)
               "suffix": "% vs mid"},               ## label shown next to delta arrow
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#8b949e", "tickfont": {"color": "#8b949e"}},  ## axis 0–100
            "bar":  {"color": bar_color, "thickness": 0.25},   ## filled arc color matches IV regime
            "bgcolor": "#161b22", "bordercolor": "#30363d",    ## dark background, subtle border
            "steps": [                             ## background quadrant shading — gets darker as IV rises
                {"range": [0,  25], "color": "#0d1117"},   ## darkest = low IV zone
                {"range": [25, 50], "color": "#161b22"},   ## dark
                {"range": [50, 75], "color": "#1c2128"},   ## slightly lighter
                {"range": [75, 100],"color": "#21262d"},   ## lightest = high IV zone
            ],
            "threshold": {"line": {"color": "#58a6ff", "width": 2}, "thickness": 0.75, "value": rank_pct},
            ## threshold = blue tick mark at current value — visible reference even when arc is thin
        },
    ))
    fig.update_layout(
        paper_bgcolor="#0e1117",   ## outer background matches dashboard dark theme
        font_color="#e0e0e0",      ## default text color — light gray
        height=280,                ## compact height — shares row with metric cards
        margin=dict(t=40, b=10, l=20, r=20)  ## tight margins so gauge fills the column
    )
    st.plotly_chart(fig, use_container_width=True)  ## stretch to fill left column width


def render_iv_cards(ticker: str):
    ## metric cards only — called in right column (2/3 width) so values won't truncate
    df = get_iv_rank_data(ticker)  ## reuses cached result from render_iv_gauge() — zero extra DB query
    if df.empty:   ## no data yet — exit silently (gauge already showed the warning)
        return

    row        = df.iloc[0]           ## single row as Series
    iv_current = row["iv_current"]    ## latest ATM IV as decimal (e.g. 0.27 = 27%)
    iv_min     = row["iv_min"]        ## historical minimum IV — lower bound of range
    iv_max     = row["iv_max"]        ## historical maximum IV — upper bound of range
    iv_pct     = row["iv_percentile"] ## fraction of days with lower IV than today (0–1)
    iv_zscore  = row["iv_zscore"]     ## std deviations from mean IV — negative = cheap, positive = expensive
    snap_count = int(row["snapshot_count"])     ## total snapshots used to compute rank/percentile
    snap_time  = str(row["snapshot_time"])[:16] ## latest snapshot timestamp, trimmed to minute

    prev_df = query(
        """
        SELECT AVG(impliedVolatility) as prev_iv
        FROM bronze_options_raw
        WHERE ticker = ? AND impliedVolatility > 0.01 AND option_type = 'call'
          AND snapshot_str = (
              SELECT snapshot_str FROM bronze_options_raw
              WHERE ticker = ? AND impliedVolatility > 0.01
              GROUP BY snapshot_str ORDER BY MAX(snapshot_time) DESC
              LIMIT 1 OFFSET 1  -- OFFSET 1 skips the latest, giving us the previous snapshot
          )
        """, [ticker, ticker]
    )
    prev_iv  = float(prev_df.iloc[0]["prev_iv"]) if not prev_df.empty else None  ## None if no previous snapshot
    iv_delta = (iv_current - prev_iv) if prev_iv else None  ## change vs previous snapshot, None if unavailable

    m1, m2, m3, m4 = st.columns(4)  ## 4 equal cards — now inside 2/3-width column so values have room

    if iv_delta is not None:  ## only show delta arrow if we have a previous snapshot to compare against
        m1.metric("IV Current", f"{iv_current*100:.1f}%", delta=f"{iv_delta*100:+.2f}% vs prev", delta_color="inverse")
        ## delta_color="inverse" = red when IV rises (expensive for buyers), green when IV falls
    else:
        m1.metric("IV Current", f"{iv_current*100:.1f}%")  ## no delta arrow — first snapshot of the day

    m2.metric("IV Range",   f"{iv_min*100:.1f}% – {iv_max*100:.1f}%")  ## e.g. "18.3% – 64.7%"
    m3.metric("Percentile", f"{iv_pct*100:.1f}%")  ## e.g. "72.0%" = IV higher than 72% of historical days

    m4.metric(
        "IV Z-Score",
        f"{iv_zscore:+.2f}σ",  ## +/- sign always shown, σ suffix = standard deviations from mean
        delta="Expensive" if iv_zscore > 2 else ("Cheap" if iv_zscore < -2 else "Normal"),
        ## plain-English label: >+2σ = statistically expensive, <-2σ = cheap, else normal
        delta_color="inverse" if iv_zscore > 2 else "normal",
        ## inverse = red when expensive (bad for buyers), normal = green when cheap
        help="> +2σ = IV is statistically high → sell premium zone · < -2σ = IV is cheap → buy options zone"
    )
    st.caption(f"Based on {snap_count} snapshots · Last snapshot: {snap_time}")  ## data freshness note

# ── PCR Table ─────────────────────────────────────────────────────────────────
def render_pcr(ticker: str):
    df = query("""
        SELECT * FROM gold_pcr
        WHERE ticker = ?
        AND (
            expiry = 'ALL'                           -- always include the aggregate ALL row
            OR CAST(expiry AS DATE) >= CURRENT_DATE  -- only show expiries from today onwards
        )
        ORDER BY expiry ASC                          -- chronological order, ALL sorts last (string > date)
    """, [ticker])
    if df.empty:
        st.warning(f"No PCR data for {ticker} yet.")
        return

    all_row    = df[df["expiry"] == "ALL"]
    dated_rows = df[df["expiry"] != "ALL"].sort_values("expiry")
    df         = pandas.concat([dated_rows, all_row], ignore_index=True)
    df["expiry"] = df["expiry"].apply(format_expiry)

    display = df[["expiry","put_volume","call_volume","pcr_volume","put_oi","call_oi","pcr_oi"]].rename(columns={
        "expiry":"Expiry","put_volume":"Put Vol","call_volume":"Call Vol","pcr_volume":"PCR Vol",
        "put_oi":"Put OI","call_oi":"Call OI","pcr_oi":"PCR OI",
    })
    display["Put OI"]  = display["Put OI"].fillna(0)
    display["Call OI"] = display["Call OI"].fillna(0)
    display["PCR OI"]  = display["PCR OI"].fillna(0)

    all_idx = display[display["Expiry"] == "ALL"].index.tolist()

    def style_row(row):
        if row.name in all_idx:
            return ["border-top: 2px solid #58a6ff; font-weight: bold; color: #58a6ff"] * len(row)
        return [""] * len(row)

    styled = (
        display.style
        .apply(style_row, axis=1)
        .applymap(lambda v: f"color: {pcr_color(v)}", subset=["PCR Vol", "PCR OI"])
        .format({"Put Vol":"{:,.0f}","Call Vol":"{:,.0f}","PCR Vol":"{:.3f}","Put OI":"{:,.0f}","Call OI":"{:,.0f}","PCR OI":"{:.3f}"}, na_rep="—")
        .set_properties(**{"background-color": "#161b22", "color": "#e0e0e0"})
        .set_table_styles([{"selector": "th", "props": [("background-color", "#0d1117"), ("color", "#58a6ff")]}])
    )
    snap_time = query("SELECT MAX(snapshot_time) FROM gold_pcr WHERE ticker = ?", [ticker]).iloc[0, 0]
    st.dataframe(styled, use_container_width=True, hide_index=True)
    st.caption(f"Last snapshot: {str(snap_time)[:16]}")

# ── GEX Chart ─────────────────────────────────────────────────────────────────
def render_gex(ticker: str):
    spot = get_spot_price(ticker)
    if spot is None:
        st.warning(f"No GEX data for {ticker} yet.")
        return

    expiries = query("SELECT DISTINCT expiry FROM gold_greeks_exposure WHERE ticker = ? ORDER BY expiry", [ticker])["expiry"].astype(str).tolist()
    expiry_options = ["ALL"] + expiries
    expiry_labels  = ["All Expiries"] + [format_expiry(e) for e in expiries]
    selected_label  = st.selectbox("Expiry", expiry_labels, index=0, key="gex_expiry")
    selected_expiry = expiry_options[expiry_labels.index(selected_label)]

    ## single-bar chart only needs net GEX per strike
    if selected_expiry == "ALL":
        df = query("""
            SELECT strike,
                   SUM(net_gamma_notional) AS net_gex  -- aggregate net GEX across all expiries
            FROM gold_greeks_exposure WHERE ticker = ?
            GROUP BY strike ORDER BY strike
        """, [ticker])
    else:
        df = query("""
            SELECT strike,
                   net_gamma_notional AS net_gex        -- net GEX for this expiry only
            FROM gold_greeks_exposure WHERE ticker = ? AND expiry = ?
            ORDER BY strike
        """, [ticker, selected_expiry])

    if df.empty:
        st.warning("No GEX data for this expiry.")
        return

    df = df.copy()
    df = df[(df["strike"] >= spot * 0.80) & (df["strike"] <= spot * 1.20)]  ## ±20% of spot

    ## Step 5 — scale to $M
    df["net_gex_m"] = df["net_gex"] / 1_000_000

    ## Step 6 — color by sign
    df["color"] = df["net_gex_m"].apply(lambda v: "#2ea043" if v >= 0 else "#f85149")

    ## Step 7 — gamma flip: find where sign changes between adjacent strikes
    s = df.sort_values("strike")
    flip_strike = None
    for i in range(len(s) - 1):
        a, b = s.iloc[i]["net_gex_m"], s.iloc[i + 1]["net_gex_m"]
        if a * b < 0:                                           ## opposite signs → crossed zero
            flip_strike = s.iloc[i]["strike"] if abs(a) < abs(b) else s.iloc[i + 1]["strike"]
            break

    ## Step 8 — call wall: highest positive bar
    pos = df[df["net_gex_m"] > 0]
    cw  = pos.nlargest(1, "net_gex_m").iloc[0] if not pos.empty else None

    ## Step 9 — put wall: deepest negative bar
    neg = df[df["net_gex_m"] < 0]
    pw  = neg.nsmallest(1, "net_gex_m").iloc[0] if not neg.empty else None

    ## Step 10 — draw chart
    fig = go.Figure()

    ## bars — one per strike, green or red
    fig.add_trace(go.Bar(
        x=df["strike"], y=df["net_gex_m"],
        marker_color=df["color"].tolist(),
        hovertemplate="Strike: $%{x}<br>Net GEX: $%{y:.2f}M<extra></extra>",
    ))

    ## spot line
    fig.add_vline(x=spot, line_width=2, line_dash="dash", line_color="#f0c040")
    fig.add_annotation(x=spot, y=1, yref="paper", text=f"Spot ${spot:.2f}",
        showarrow=False, font=dict(color="#f0c040", size=12),
        bgcolor="#0e1117", bordercolor="#f0c040", borderwidth=1, xanchor="left", yanchor="top")

    ## gamma flip line
    if flip_strike:
        fig.add_vline(x=flip_strike, line_width=1, line_dash="dot", line_color="#8b949e")
        fig.add_annotation(x=flip_strike, y=0.05, yref="paper", text=f"Flip ${flip_strike:.0f}",
            showarrow=False, font=dict(color="#8b949e", size=11),
            bgcolor="#0e1117", bordercolor="#8b949e", borderwidth=1, xanchor="center")

    ## call wall label
    if cw is not None:
        fig.add_annotation(x=cw["strike"], y=cw["net_gex_m"], text=f"Call Wall<br>${cw['strike']:.0f}",
            showarrow=True, arrowhead=2, font=dict(color="#2ea043", size=11),
            bgcolor="#0e1117", bordercolor="#2ea043", borderwidth=1, ay=-35)

    ## put wall label
    if pw is not None:
        fig.add_annotation(x=pw["strike"], y=pw["net_gex_m"], text=f"Put Wall<br>${pw['strike']:.0f}",
            showarrow=True, arrowhead=2, font=dict(color="#f85149", size=11),
            bgcolor="#0e1117", bordercolor="#f85149", borderwidth=1, ay=35)

    fig.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="#e0e0e0", height=400,
        margin=dict(t=40, b=40, l=60, r=20), showlegend=False,
        xaxis=dict(title="Strike", tickprefix="$", gridcolor="#21262d", color="#8b949e"),
        yaxis=dict(title="Net GEX ($M)", gridcolor="#21262d", color="#8b949e",
                   zeroline=True, zerolinecolor="#30363d", zerolinewidth=2),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Spot: ${spot:.2f} · Green = Dealers Long Gamma · Red = Dealers Short Gamma · ±20% of spot")

# ── Layout ────────────────────────────────────────────────────────────────────
gauge_col, cards_col = st.columns([1, 2])  ## left = 1/3 width (gauge), right = 2/3 width (cards)
with gauge_col:
    st.subheader("🎯 IV Rank")             ## section heading for gauge column
    render_iv_gauge(ticker)                 ## gauge only — no cards crammed in here
with cards_col:
    st.subheader("📊 IV Stats")            ## section heading for metric cards column
    render_iv_cards(ticker)                 ## cards now have 2/3 page width — no truncation

st.divider()                               ## horizontal rule between IV section and PCR

st.subheader("📊 Put/Call Ratio")          ## PCR now full width — all 7 columns readable
render_pcr(ticker)

st.divider()                               ## horizontal rule between PCR and GEX
st.subheader("⚡ Gamma Exposure (GEX)")
render_gex(ticker)

# ── Auto-refresh ──────────────────────────────────────────────────────────────
import time
if refresh_secs:
    time.sleep(refresh_secs)
    st.rerun()
