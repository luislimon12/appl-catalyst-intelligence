"""
Page 2 — Options Chain
AAPL & INTC Catalyst Intelligence Dashboard
Session 3 (Jun 2026): Goal 5 — filterable options chain
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date as date_type
import pandas
import plotly.graph_objects as go
import streamlit as st

from utils import DARK_THEME_CSS, format_expiry, get_spot_price, query, render_sidebar, render_page_header

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Options Chain · Catalyst Intelligence", page_icon="📋", layout="wide", initial_sidebar_state="expanded")
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
ticker, refresh_secs = render_sidebar("Options Chain")

# ── Header ────────────────────────────────────────────────────────────────────
render_page_header("📋", "Options Chain", "Full chain filterable by expiry, type, and strike range", ticker)

# ── Data ──────────────────────────────────────────────────────────────────────
def get_iv_skew(ticker, expiry):
    """Fetch IV by strike split by call/put for the skew chart."""
    if expiry == "ALL":
        return pandas.DataFrame()
    return query(
        """
        SELECT strike, option_type, iv
        FROM gold_latest_snapshot
        WHERE ticker = ? AND expiry = ? AND iv IS NOT NULL AND iv > 0
        ORDER BY strike
        """, [ticker, expiry]
    )

def render_skew_chart(ticker, expiry, spot):
    """IV skew — calls vs puts IV plotted against strike.
    Blue line = call IV, red line = put IV.
    A higher put IV than call IV at the same strike = bearish skew (market hedging downside).
    """
    df = get_iv_skew(ticker, expiry)
    if df.empty:
        return  # silently skip if ALL selected or no data

    calls = df[df["option_type"] == "call"]
    puts  = df[df["option_type"] == "put"]

    fig = go.Figure()

    # Call IV line — blue
    fig.add_trace(go.Scatter(
        x=calls["strike"], y=calls["iv"] * 100,
        mode="lines+markers", name="Calls",
        line=dict(color="#388bfd", width=2), marker=dict(size=5),
        hovertemplate="Strike: $%{x}<br>Call IV: %{y:.1f}%<extra></extra>",
    ))

    # Put IV line — red
    fig.add_trace(go.Scatter(
        x=puts["strike"], y=puts["iv"] * 100,
        mode="lines+markers", name="Puts",
        line=dict(color="#f85149", width=2), marker=dict(size=5),
        hovertemplate="Strike: $%{x}<br>Put IV: %{y:.1f}%<extra></extra>",
    ))

    # Spot price vertical line — shows where ATM is on the skew
    fig.add_vline(x=spot, line_width=2, line_dash="dash", line_color="#f0c040")
    fig.add_annotation(
        x=spot, y=1, yref="paper", text=f"Spot ${spot:.2f}",
        showarrow=False, font=dict(color="#f0c040", size=11),
        bgcolor="#0e1117", bordercolor="#f0c040", borderwidth=1,
        xanchor="left", yanchor="top"
    )

    fig.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="#e0e0e0",
        height=300, margin=dict(t=20, b=40, l=60, r=20),
        xaxis=dict(title="Strike", tickprefix="$", gridcolor="#21262d", color="#8b949e"),
        yaxis=dict(title="IV %", gridcolor="#21262d", color="#8b949e", zeroline=False),
        legend=dict(bgcolor="#161b22", bordercolor="#30363d", borderwidth=1),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"IV Skew · {format_expiry(expiry)} · Blue = Calls · Red = Puts · Spot marked in yellow")

def get_chain_data(ticker, expiry, option_type, spot, pct_range):
    sql = "SELECT * FROM gold_latest_snapshot WHERE ticker = ?"
    params = [ticker]
    if expiry != "ALL":
        sql += " AND expiry = ?"
        params.append(expiry)
    if option_type != "All":
        sql += " AND option_type = ?"
        params.append(option_type.lower().rstrip("s"))
    sql += " ORDER BY expiry, strike"
    df = query(sql, params)
    if df.empty:
        return df
    lower = spot * (1 - pct_range / 100)
    upper = spot * (1 + pct_range / 100)
    return df[(df["strike"] >= lower) & (df["strike"] <= upper)]

# ── Render ────────────────────────────────────────────────────────────────────
spot = get_spot_price(ticker)
if spot is None:
    st.warning(f"No options chain data for {ticker} yet.")
    st.stop()

ctrl1, ctrl2, ctrl3 = st.columns([2, 1, 1])

with ctrl1:
    expiries = query("SELECT DISTINCT expiry FROM gold_latest_snapshot WHERE ticker = ? ORDER BY expiry", [ticker])["expiry"].astype(str).str[:10].tolist()
    expiry_options = ["ALL"] + expiries
    expiry_labels  = ["All Expiries"] + [format_expiry(e) for e in expiries]
    today = date_type.today().isoformat()
    future = [e for e in expiries if e >= today]
    default_index = expiry_options.index(future[0]) if future else 0
    selected_label  = st.selectbox("Expiry", expiry_labels, index=default_index, key="chain_expiry")
    selected_expiry = expiry_options[expiry_labels.index(selected_label)]

with ctrl2:
    option_type = st.selectbox("Type", ["All", "Calls", "Puts"], index=0, key="chain_type")

with ctrl3:
    pct_range = st.slider("Strike range (±%)", min_value=5, max_value=30, value=10, step=5, key="chain_pct")

# IV Skew chart — driven by the same expiry selector above, sits above the chain table
st.subheader("📉 IV Skew")
render_skew_chart(ticker, selected_expiry, spot)
st.divider()

df = get_chain_data(ticker, selected_expiry, option_type, spot, pct_range)

if df.empty:
    st.warning("No contracts found for these filters.")
    st.stop()

## Jun 21 2026: reordered columns — most important (Strike, Last, IV%, Delta) first
## so they're visible without scrolling on smaller screens
display = df[["strike","option_type","option_last","iv","delta","bid","ask","volume","openInterest","gamma","theta","vega","expiry","inTheMoney"]].copy()
display["expiry"]      = display["expiry"].astype(str).str[:10].apply(format_expiry)
display["iv"]          = (display["iv"] * 100).round(2)
display["option_type"] = display["option_type"].str.capitalize()
display = display.rename(columns={"expiry":"Expiry","strike":"Strike","option_type":"Type","inTheMoney":"ITM",
    "bid":"Bid","ask":"Ask","option_last":"Last","volume":"Volume","openInterest":"OI","iv":"IV %",
    "delta":"Delta","gamma":"Gamma","theta":"Theta","vega":"Vega"})

def row_color(row):
    if row["ITM"]:
        return ["background-color: #0d2818"] * len(row)
    return [""] * len(row)

def fmt_greek(val):
    if pandas.isna(val): return "—"
    return f"{val:.4f}"

styled = (
    display.style
    .apply(row_color, axis=1)
    .format({"Strike":"${:.2f}","Bid":"${:.2f}","Ask":"${:.2f}","Last":"${:.2f}",
             "Volume":"{:,.0f}","OI":"{:,.0f}","IV %":"{:.2f}%",
             "Delta":fmt_greek,"Gamma":fmt_greek,"Theta":fmt_greek,"Vega":fmt_greek}, na_rep="—")
    .set_properties(**{"background-color": "#161b22", "color": "#e0e0e0"})
    .set_table_styles([{"selector": "th", "props": [("background-color", "#0d1117"), ("color", "#58a6ff")]}])
)

st.dataframe(styled, use_container_width=True, hide_index=True, height=600)
st.caption(f"Spot: ${spot:.2f} · Showing ±{pct_range}% strike range · {len(df)} contracts")

# ── Auto-refresh ──────────────────────────────────────────────────────────────
import time
if refresh_secs:
    time.sleep(refresh_secs)
    st.rerun()
