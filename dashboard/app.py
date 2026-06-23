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
def render_iv_rank(ticker: str):
    df = query("SELECT * FROM gold_iv_rank WHERE ticker = ?", [ticker])
    if df.empty:
        st.warning(f"No IV rank data for {ticker} yet.")
        return

    row        = df.iloc[0]
    iv_current = row["iv_current"]
    iv_min     = row["iv_min"]
    iv_max     = row["iv_max"]
    iv_rank    = row["iv_rank"]
    iv_pct     = row["iv_percentile"]
    snap_count = int(row["snapshot_count"])
    snap_time  = str(row["snapshot_time"])[:16]

    rank_pct = iv_rank * 100
    if rank_pct < 25:   bar_color = "#2ea043"
    elif rank_pct < 50: bar_color = "#d29922"
    elif rank_pct < 75: bar_color = "#e3b341"
    else:               bar_color = "#f85149"

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=round(rank_pct, 1),
        title={"text": "IV Rank", "font": {"color": "#58a6ff", "size": 16}},
        number={"suffix": "%", "font": {"color": "#e0e0e0", "size": 36}},
        delta={"reference": 50, "increasing": {"color": "#f85149"}, "decreasing": {"color": "#2ea043"}, "suffix": "% vs mid"},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": "#8b949e", "tickfont": {"color": "#8b949e"}},
            "bar":  {"color": bar_color, "thickness": 0.25},
            "bgcolor": "#161b22", "bordercolor": "#30363d",
            "steps": [
                {"range": [0,  25], "color": "#0d1117"},
                {"range": [25, 50], "color": "#161b22"},
                {"range": [50, 75], "color": "#1c2128"},
                {"range": [75, 100],"color": "#21262d"},
            ],
            "threshold": {"line": {"color": "#58a6ff", "width": 2}, "thickness": 0.75, "value": rank_pct},
        },
    ))
    fig.update_layout(paper_bgcolor="#0e1117", font_color="#e0e0e0", height=280, margin=dict(t=40, b=10, l=20, r=20))
    st.plotly_chart(fig, use_container_width=True)

    prev_df = query(
        """
        SELECT AVG(impliedVolatility) as prev_iv
        FROM bronze_options_raw
        WHERE ticker = ? AND impliedVolatility > 0.01 AND option_type = 'call'
          AND snapshot_str = (
              SELECT snapshot_str FROM bronze_options_raw
              WHERE ticker = ? AND impliedVolatility > 0.01
              GROUP BY snapshot_str ORDER BY MAX(snapshot_time) DESC
              LIMIT 1 OFFSET 1
          )
        """, [ticker, ticker]
    )
    prev_iv  = float(prev_df.iloc[0]["prev_iv"]) if not prev_df.empty else None
    iv_delta = (iv_current - prev_iv) if prev_iv else None

    m1, m2, m3 = st.columns(3)
    if iv_delta is not None:
        m1.metric("IV Current", f"{iv_current*100:.1f}%", delta=f"{iv_delta*100:+.2f}% vs prev", delta_color="inverse")
    else:
        m1.metric("IV Current", f"{iv_current*100:.1f}%")
    m2.metric("IV Range",   f"{iv_min*100:.1f}% – {iv_max*100:.1f}%")
    m3.metric("Percentile", f"{iv_pct*100:.1f}%")
    st.caption(f"Based on {snap_count} snapshots · Last snapshot: {snap_time}")

# ── PCR Table ─────────────────────────────────────────────────────────────────
def render_pcr(ticker: str):
    df = query("SELECT * FROM gold_pcr WHERE ticker = ? ORDER BY expiry ASC", [ticker])
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

    ## Jun 21 2026: fetch call, put, and net GEX separately so we can show split bars
    if selected_expiry == "ALL":
        df = query("""
            SELECT strike,
                   SUM(call_gamma_notional) AS call_gex,  -- dealer gamma from calls at this strike
                   SUM(put_gamma_notional)  AS put_gex,   -- dealer gamma from puts at this strike
                   SUM(net_gamma_notional)  AS net_gex    -- net = call + put combined
            FROM gold_greeks_exposure WHERE ticker = ?
            GROUP BY strike ORDER BY strike
        """, [ticker])
    else:
        df = query("""
            SELECT strike,
                   call_gamma_notional AS call_gex,  -- dealer gamma from calls at this strike
                   put_gamma_notional  AS put_gex,   -- dealer gamma from puts at this strike
                   net_gamma_notional  AS net_gex    -- net = call + put combined
            FROM gold_greeks_exposure WHERE ticker = ? AND expiry = ?
            ORDER BY strike
        """, [ticker, selected_expiry])

    if df.empty:
        st.warning("No GEX data for this expiry.")
        return

    df = df.copy()
    lower, upper = spot * 0.80, spot * 1.20                ## limit to ±20% of spot
    df = df[(df["strike"] >= lower) & (df["strike"] <= upper)]  ## filter strikes

    ## Scale from dollars to $K so y-axis numbers are readable (22000 → 22.0)
    df["call_gex_k"] = df["call_gex"] / 1000   ## call GEX in thousands
    df["put_gex_k"]  = df["put_gex"]  / 1000   ## put GEX in thousands
    df["net_gex_k"]  = df["net_gex"]  / 1000   ## net GEX in thousands

    fig = go.Figure()

    ## Blue bars = call GEX — dealer gamma from call contracts at each strike
    ## Positive = dealers are long gamma here (stabilizing — they sell into rallies)
    fig.add_trace(go.Bar(
        x=df["strike"],           ## x-axis = strike price
        y=df["call_gex_k"],       ## height = call GEX in $K
        name="Call GEX",          ## legend label
        marker_color="#388bfd",   ## blue — calls
        opacity=0.8,              ## slight transparency so bars don't overpower
        hovertemplate="Strike: $%{x}<br>Call GEX: $%{y:.1f}K<extra></extra>",
    ))

    ## Orange bars = put GEX — dealer gamma from put contracts at each strike
    ## Negative = dealers are short gamma here (destabilizing — they sell into drops)
    fig.add_trace(go.Bar(
        x=df["strike"],           ## x-axis = strike price
        y=df["put_gex_k"],        ## height = put GEX in $K (typically negative)
        name="Put GEX",           ## legend label
        marker_color="#f0a500",   ## orange — puts
        opacity=0.8,              ## slight transparency
        hovertemplate="Strike: $%{x}<br>Put GEX: $%{y:.1f}K<extra></extra>",
    ))

    ## White dotted line = net GEX — where call and put gamma cancel out
    ## Zero crossing = gamma flip point — price tends to accelerate past this level
    fig.add_trace(go.Scatter(
        x=df["strike"],                                     ## x-axis = strike price
        y=df["net_gex_k"],                                  ## y = net GEX in $K
        name="Net GEX",                                     ## legend label
        mode="lines",                                       ## line only, no dots
        line=dict(color="#e0e0e0", width=2, dash="dot"),    ## white dotted line
        hovertemplate="Strike: $%{x}<br>Net GEX: $%{y:.1f}K<extra></extra>",
    ))

    ## Spot price vertical line — shows current price relative to gamma walls
    fig.add_vline(x=spot, line_width=2, line_dash="dash", line_color="#f0c040")
    fig.add_annotation(
        x=spot, y=1, yref="paper", text=f"Spot ${spot:.2f}", showarrow=False,
        font=dict(color="#f0c040", size=12), bgcolor="#0e1117",
        bordercolor="#f0c040", borderwidth=1, xanchor="left", yanchor="top"
    )

    fig.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="#e0e0e0", height=400,
        margin=dict(t=40, b=40, l=60, r=20),
        barmode="group",   ## side-by-side bars — easier to compare call vs put GEX per strike
        xaxis=dict(title="Strike", tickprefix="$", gridcolor="#21262d", color="#8b949e"),
        yaxis=dict(title="GEX ($K)", gridcolor="#21262d", color="#8b949e", zeroline=True, zerolinecolor="#30363d", zerolinewidth=2),
        legend=dict(bgcolor="#161b22", bordercolor="#30363d", borderwidth=1),
        bargap=0.15,   ## small gap between strike groups
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Spot: ${spot:.2f} · Blue = Call GEX · Orange = Put GEX · Dotted = Net · ±20% of spot")

# ── Layout ────────────────────────────────────────────────────────────────────
col1, col2 = st.columns([1, 2])
with col1:
    st.subheader("🎯 IV Rank")
    render_iv_rank(ticker)
with col2:
    st.subheader("📊 Put/Call Ratio")
    render_pcr(ticker)

st.divider()
st.subheader("⚡ Gamma Exposure (GEX)")
render_gex(ticker)

# ── Auto-refresh ──────────────────────────────────────────────────────────────
import time
if refresh_secs:
    time.sleep(refresh_secs)
    st.rerun()
