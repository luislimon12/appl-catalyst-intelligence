"""
Page 2 — Options Chain
AAPL & INTC Catalyst Intelligence Dashboard
Session 3 (Jun 2026): Goal 5 — filterable options chain
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import date as date_type
from datetime import datetime  ## Jun 25 2026: needed to compute DTE (days to expiry)
import pandas
import plotly.graph_objects as go
from plotly.subplots import make_subplots  ## Jul 2026: needed for 2-row term structure + slope subplot
import streamlit as st

from utils import CATALYST_EVENTS, DARK_THEME_CSS, format_expiry, get_spot_price, query, render_sidebar, render_page_header

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Options Chain · Catalyst Intelligence", page_icon="📋", layout="wide", initial_sidebar_state="expanded")
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
ticker, refresh_secs = render_sidebar("Options Chain")

# ── Header ────────────────────────────────────────────────────────────────────
render_page_header("📋", "Options Chain", "Full chain filterable by expiry, type, and strike range", ticker)

# ── Data ──────────────────────────────────────────────────────────────────────

def render_skew_chart(ticker, expiry, spot):
    ## Jun 25 2026: rewrote skew chart — bubbles replace lines, volume slider added
    ## Bubble size = volume so you can instantly see which IV points are trustworthy
    ## High volume = tight bid-ask = reliable IV. Low/zero volume = noise.
    ## Min volume slider lets you filter out unreliable low-volume strikes

    if expiry == "ALL":
        return  ## no skew chart when all expiries selected — makes no sense to mix expiries

    ## Single query — iv and volume in same table, no merge needed
    df = query("""
        SELECT strike, option_type, iv, volume
        FROM gold_latest_snapshot
        WHERE ticker = ? AND expiry = ? AND iv > 0
        ORDER BY strike
    """, [ticker, expiry])
    if df.empty:
        return

    df["volume"] = df["volume"].fillna(0)  ## replace NA with 0 so size calc doesn't break

    ## Min volume slider — raise to filter out strikes with unreliable IV (wide spread, no trades)
    min_vol = st.slider("Min volume (skew)", 0, 500, 0, 10, key="skew_min_vol")

    calls = df[(df["option_type"] == "call") & (df["volume"] >= min_vol)]
    puts  = df[(df["option_type"] == "put")  & (df["volume"] >= min_vol)]

    ## Scale volume to bubble size: 0 → 4px (minimum visible), max volume → 40px
    max_vol = df["volume"].max() or 1          ## avoid div by zero if all volume is 0
    size_c  = (calls["volume"] / max_vol * 36 + 4).clip(4, 40)  ## calls bubble sizes
    size_p  = (puts["volume"]  / max_vol * 36 + 4).clip(4, 40)  ## puts bubble sizes

    fig = go.Figure()

    ## Call IV bubbles — blue, size = call volume at that strike
    fig.add_trace(go.Scatter(
        x=calls["strike"], y=calls["iv"] * 100,
        mode="markers", name="Calls",
        marker=dict(color="#388bfd", size=size_c, opacity=0.8),
        customdata=calls["volume"],
        hovertemplate="Strike: $%{x}<br>Call IV: %{y:.1f}%<br>Vol: %{customdata:,.0f}<extra></extra>",
    ))

    ## Put IV bubbles — red, size = put volume at that strike
    fig.add_trace(go.Scatter(
        x=puts["strike"], y=puts["iv"] * 100,
        mode="markers", name="Puts",
        marker=dict(color="#f85149", size=size_p, opacity=0.8),
        customdata=puts["volume"],
        hovertemplate="Strike: $%{x}<br>Put IV: %{y:.1f}%<br>Vol: %{customdata:,.0f}<extra></extra>",
    ))

    ## Spot price vertical line — marks ATM on the skew
    fig.add_vline(x=spot, line_width=2, line_dash="dash", line_color="#f0c040")
    fig.add_annotation(x=spot, y=1, yref="paper", text=f"Spot ${spot:.2f}",
        showarrow=False, font=dict(color="#f0c040", size=11),
        bgcolor="#0e1117", bordercolor="#f0c040", borderwidth=1, xanchor="left", yanchor="top")

    fig.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="#e0e0e0",
        height=320, margin=dict(t=20, b=40, l=60, r=20), hovermode="closest",
        xaxis=dict(title="Strike", tickprefix="$", gridcolor="#21262d", color="#8b949e"),
        yaxis=dict(title="IV %", gridcolor="#21262d", color="#8b949e", zeroline=False),
        legend=dict(bgcolor="#161b22", bordercolor="#30363d", borderwidth=1),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"IV Skew · {format_expiry(expiry)} · Bubble size = volume · Blue = Calls · Red = Puts · Spot in yellow")

def render_term_structure(ticker, spot):
    ## CHANGED Jul 2026: switched x-axis from calendar date → DTE (days to expiry)
    ## REASON: calendar date clusters weekly AAPL options on the left making chart unreadable
    ## DTE spaces expiries evenly regardless of how many weeklies exist near-term

    ## unchanged query — volume-weighted ATM IV grouped by expiry
    ## BETWEEN spot*0.95 and spot*1.05 = near-money strikes only (5% range)
    ## SUM(iv * volume) / NULLIF(SUM(volume), 0) = volume-weighted IV to reduce noise
    ## HAVING SUM(volume) > 10 = skip illiquid expiries with almost no trading
    df = query("""
        SELECT expiry,
               SUM(iv * volume) / NULLIF(SUM(volume), 0) * 100 AS atm_iv,  ## volume-weighted IV %
               SUM(volume) AS vol                                            ## total volume this expiry
        FROM gold_latest_snapshot
        WHERE ticker = ? AND iv > 0 AND strike BETWEEN ? AND ?
        GROUP BY expiry
        HAVING SUM(volume) > 10
        ORDER BY expiry
    """, [ticker, spot * 0.95, spot * 1.05])
    if df.empty:
        return

    ## NEW: compute DTE — integer days from today to each expiry
    df["dte"] = (pandas.to_datetime(df["expiry"]) - pandas.Timestamp.now()).dt.days

    ## NEW: filter DTE < 7 — near-expiry options have artificially inflated IV
    ## annualization math (IV × √252) blows up when DTE approaches 0 — not real signal
    ## REMOVED: date-based x_start/x_end cap → replaced with DTE cap (7 to 540 days = ~18 months)
    df = df[(df["dte"] >= 7) & (df["dte"] <= 540)]

    if df.empty:
        return

    ## unchanged — bubble sizing by volume
    ## bigger bubble = more actively traded expiry = more trustworthy IV
    max_vol = df["vol"].max() or 1
    sizes   = (df["vol"] / max_vol * 36 + 8).clip(8, 44)

    ## CHANGED: slope now uses DTE gap instead of calendar days between expiry dates
    ## REMOVED: df["expiry_dt"] and df["days"] columns (date-based gap calculation)
    ## REPLACED WITH: df["dte_gap"] — difference in DTE between consecutive expiries
    ## Positive slope → IV rises further out (contango). Negative → backwardation.
    df["dte_gap"]   = df["dte"] - df["dte"].shift(1)                ## DTE gap between consecutive expiries
    df["iv_change"] = df["atm_iv"] - df["atm_iv"].shift(1)          ## IV % change between expiries
    df["slope"]     = (df["iv_change"] / df["dte_gap"]).fillna(0)   ## rate of change per DTE day; NaN → 0 for first row

    ## unchanged — color logic: green = contango, red = backwardation
    slope_colors = ["#2ea043" if s >= 0 else "#f85149" for s in df["slope"]]

    ## unchanged — two-row subplot layout
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,                  ## zoom one row → other follows
        row_heights=[0.65, 0.35],           ## top row gets 65% of height
        vertical_spacing=0.08,
        subplot_titles=["ATM IV by DTE", "Slope (dIV/dDTE) — IV% per day"],  ## CHANGED: titles reflect DTE
    )

    ## CHANGED: x=df["dte"] instead of x=df["expiry"]
    ## CHANGED: hover now shows both DTE and expiry date for context
    fig.add_trace(go.Scatter(
        x=df["dte"],
        y=df["atm_iv"],
        mode="lines+markers",
        marker=dict(color="#58a6ff", size=sizes, opacity=0.85),
        line=dict(color="#58a6ff", width=2),
        name="ATM IV",
        customdata=df[["vol", "expiry"]].values,             ## CHANGED: added expiry to customdata for hover
        hovertemplate="DTE: %{x}d<br>Expiry: %{customdata[1]}<br>ATM IV: %{y:.1f}%<br>Vol: %{customdata[0]:,.0f}<extra></extra>",
    ), row=1, col=1)

    ## CHANGED: x=df["dte"] instead of x=df["expiry"]
    fig.add_trace(go.Bar(
        x=df["dte"],
        y=df["slope"],
        marker_color=slope_colors,
        name="Slope",
        hovertemplate="DTE: %{x}d<br>dIV/dDTE: %{y:.3f}%/day<extra></extra>",
    ), row=2, col=1)

    ## unchanged — zero reference line on slope panel
    fig.add_hline(y=0, line_width=1, line_color="#30363d", row=2, col=1)

    ## CHANGED: catalyst markers converted from calendar date → DTE for x-axis positioning
    ## REMOVED: pandas.to_datetime(date) <= x_end date check
    ## REPLACED WITH: DTE range check (7 to 540)
    for event_name, event_date in CATALYST_EVENTS.items():
        cat_dte = (pandas.to_datetime(event_date) - pandas.Timestamp.now()).days
        if 7 <= cat_dte <= 540:           ## only show if within our DTE window
            fig.add_vline(x=cat_dte, line_width=1, line_dash="dot", line_color="#bc8cff")
            fig.add_annotation(
                x=cat_dte, y=1, yref="paper", text=event_name, showarrow=False,
                font=dict(color="#bc8cff", size=11), bgcolor="#0e1117",
                bordercolor="#bc8cff", borderwidth=1, xanchor="left", yanchor="top",
            )

    ## CHANGED: xaxis range now 0-540 DTE instead of date range
    ## CHANGED: xaxis2 title updated to "Days to Expiry (DTE)"
    ## REMOVED: x_start, x_end date variables
    fig.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="#e0e0e0",
        height=480,
        margin=dict(t=40, b=40, l=60, r=20),
        showlegend=False,
        xaxis=dict(gridcolor="#21262d", color="#8b949e", range=[0, 540]),
        xaxis2=dict(title="Days to Expiry (DTE)", gridcolor="#21262d", color="#8b949e", range=[0, 540]),
        yaxis=dict(title="ATM IV %", gridcolor="#21262d", color="#8b949e"),
        yaxis2=dict(title="IV%/day", gridcolor="#21262d", color="#8b949e", zeroline=False),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Term Structure · DTE x-axis · Volume-weighted ATM IV · Bubble = volume · Slope = dIV/dDTE · Green = contango · Red = backwardation")

## Jun 25 2026: DTE bucket helper
## Maps days-to-expiry integer to a labeled bucket matching the theta decay curve zones
## < 30 days  = rapid decay (most expensive to hold, theta accelerates exponentially)
## 30-60 days = accelerating decay
## 60-90 days = moderate decay
## 90-120 days = slow decay
## 120+ days  = minimal theta impact (safest zone for long option holders)
def dte_bucket(days: int) -> str:
    if days < 30:   return "⚡ <30d"    ## rapid decay — danger zone for buyers
    if days < 60:   return "🔥 30-60d"  ## accelerating
    if days < 90:   return "📉 60-90d"  ## moderate
    if days < 120:  return "🐢 90-120d" ## slow
    return          "💤 120d+"          ## minimal theta impact

def get_chain_data(ticker, expiry, option_type, spot, pct_range):
    ## Jun 25 2026: added DTE and Vol/OI ratio columns for new filters
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

    ## Strike range filter — keep only strikes within ±pct_range% of spot
    lower = spot * (1 - pct_range / 100)
    upper = spot * (1 + pct_range / 100)
    df = df[(df["strike"] >= lower) & (df["strike"] <= upper)].copy()

    ## Jun 25 2026: compute DTE — days from today to expiry
    ## Used by the DTE bucket filter and displayed as a column in the chain table
    today = pandas.Timestamp(date_type.today())
    df["dte"] = (pandas.to_datetime(df["expiry"]) - today).dt.days

    ## Jun 25 2026: compute Vol/OI and OI/Vol using vectorized pandas — avoids NA errors
    ## lambda + round() fails when either column contains pandas.NA (NAType has no __round__)
    ## Vectorized approach: fillna(0) cleans NAs, replace(0, NA) prevents division by zero,
    ## final fillna(0) converts NA results back to 0, round(2) formats to 2 decimal places

    ## Vol/OI: volume ÷ open interest — activity signal (unusual flow detector)
    df["vol_oi_ratio"] = (
        df["volume"].fillna(0) /
        df["openInterest"].fillna(0).replace(0, pandas.NA)
    ).fillna(0).round(2)

    ## OI/Vol: open interest ÷ volume — liquidity signal (established contract detector)
    df["oi_vol_ratio"] = (
        df["openInterest"].fillna(0) /
        df["volume"].fillna(0).replace(0, pandas.NA)
    ).fillna(0).round(2)

    return df

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

## Jun 25 2026: second row of filters — DTE bucket + OI/Volume ratio
## These sit below the main controls so the layout stays clean
ctrl4, ctrl5 = st.columns([2, 2])

with ctrl4:
    ## DTE bucket filter — maps to theta decay zones from the decay curve
    ## "All" = no DTE filter, just show everything in the strike range
    dte_options = ["All", "⚡ <30d", "🔥 30-60d", "📉 60-90d", "🐢 90-120d", "💤 120d+"]
    dte_filter  = st.selectbox("DTE Zone (theta decay)", dte_options, index=0, key="chain_dte")

with ctrl5:
    ## Combined Vol/OI and OI/Vol filter dropdown
    ## Vol/OI filters → detect unusual activity / new positioning (activity signal)
    ## OI/Vol filters → detect established liquid contracts (liquidity signal)
    ## Raw filters → simple threshold on OI or Volume alone
    flow_options = [
        "All",
        ## Vol/OI — activity signal (volume relative to open interest)
        "Vol/OI > 1.0 (unusual flow)",   ## volume exceeds all open contracts — very unusual
        "Vol/OI > 0.5 (elevated flow)",  ## heavy activity vs existing positioning
        ## OI/Vol — liquidity signal (open interest relative to volume)
        "OI/Vol > 10 (liquid)",          ## established contracts, low daily turnover
        "OI/Vol > 50 (very liquid)",     ## most stable, tightest spreads
        ## Raw thresholds
        "High OI (>1000)",               ## most open contracts — most established
        "High Vol (>500)",               ## most active today
    ]
    flow_filter = st.selectbox("Activity / Liquidity Filter", flow_options, index=0, key="chain_flow")

## Jun 25 2026: switch between term structure and IV skew based on expiry selection
## ALL selected → term structure (IV across expiries — shows which expiry has event premium)
## Specific expiry → IV skew (IV across strikes — shows put/call skew for that expiry)
if selected_expiry == "ALL":
    st.subheader("📈 Volatility Term Structure")
    render_term_structure(ticker, spot)
else:
    st.subheader("📉 IV Skew")
    render_skew_chart(ticker, selected_expiry, spot)
st.divider()

df = get_chain_data(ticker, selected_expiry, option_type, spot, pct_range)

if df.empty:
    st.warning("No contracts found for these filters.")
    st.stop()

## Jun 25 2026: apply DTE bucket filter
## dte_bucket(row["dte"]) converts the integer DTE to a zone label like "⚡ <30d"
## We compare that label to what the user selected in the dropdown
if dte_filter != "All":
    df = df[df["dte"].apply(dte_bucket) == dte_filter]

## Jun 25 2026: apply activity/liquidity filter
## Vol/OI filters = activity signal (unusual new positioning)
## OI/Vol filters = liquidity signal (established, liquid contracts)
if flow_filter == "Vol/OI > 1.0 (unusual flow)":
    ## Volume exceeded total open interest — very unusual, strong new position signal
    df = df[df["vol_oi_ratio"] > 1.0]
elif flow_filter == "Vol/OI > 0.5 (elevated flow)":
    ## Volume more than half of OI — elevated activity vs existing positioning
    df = df[df["vol_oi_ratio"] > 0.5]
elif flow_filter == "OI/Vol > 10 (liquid)":
    ## OI is 10x daily volume — established, liquid contract with tight spreads
    df = df[df["oi_vol_ratio"] > 10]
elif flow_filter == "OI/Vol > 50 (very liquid)":
    ## OI is 50x daily volume — most stable, institutional-grade liquidity
    df = df[df["oi_vol_ratio"] > 50]
elif flow_filter == "High OI (>1000)":
    ## Raw OI threshold — most established contracts
    df = df[df["openInterest"] > 1000]
elif flow_filter == "High Vol (>500)":
    ## Raw volume threshold — most actively traded today
    df = df[df["volume"] > 500]

if df.empty:
    st.warning("No contracts match these filters. Try relaxing the DTE Zone or OI/Volume filter.")
    st.stop()

## Jun 21 2026: reordered columns — most important (Strike, Last, IV%, Delta) first
## Jun 25 2026: added DTE and Vol/OI columns so decay zone and activity are visible in table
## Jun 25 2026: added dte, vol_oi_ratio, oi_vol_ratio columns
## Zone = theta decay bucket label, Vol/OI = activity signal, OI/Vol = liquidity signal
display = df[["strike","option_type","option_last","iv","delta","dte","vol_oi_ratio","oi_vol_ratio","bid","ask","volume","openInterest","gamma","theta","vega","expiry","inTheMoney"]].copy()
display["expiry"]      = display["expiry"].astype(str).str[:10].apply(format_expiry)
display["iv"]          = (display["iv"] * 100).round(2)
display["option_type"] = display["option_type"].str.capitalize()

## DTE zone label — maps integer DTE to theta decay bucket for quick visual reference
display["dte_zone"] = display["dte"].apply(dte_bucket)

display = display.rename(columns={
    "expiry":"Expiry","strike":"Strike","option_type":"Type","inTheMoney":"ITM",
    "bid":"Bid","ask":"Ask","option_last":"Last","volume":"Volume","openInterest":"OI",
    "iv":"IV %","delta":"Delta","gamma":"Gamma","theta":"Theta","vega":"Vega",
    "dte":"DTE","dte_zone":"Zone","vol_oi_ratio":"Vol/OI","oi_vol_ratio":"OI/Vol",
})

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
             "Vol/OI":"{:.2f}","OI/Vol":"{:.2f}","DTE":"{:.0f}",  ## Jun 25 2026: format new ratio columns
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
