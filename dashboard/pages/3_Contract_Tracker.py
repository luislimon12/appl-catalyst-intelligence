"""
Page 3 — Contract Tracker
AAPL & INTC Catalyst Intelligence Dashboard
Session 3 (Jun 2026): Goal 6 — watchlist, line chart, candlestick with OI bars
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from utils import CATALYST_EVENTS, DARK_THEME_CSS, format_expiry, query, render_sidebar

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Contract Tracker · Catalyst Intelligence", page_icon="🔍", layout="wide", initial_sidebar_state="expanded")
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
ticker, refresh_secs = render_sidebar("Contract Tracker")

# ── Header ────────────────────────────────────────────────────────────────────
st.title(f"🔍 Contract Tracker — {ticker}")
st.caption("Pin contracts to your watchlist and track price, IV, and delta over time")
st.divider()

# ── Data helpers ──────────────────────────────────────────────────────────────
def get_watchlist_contracts(ticker):
    return query(
        """
        SELECT contractSymbol, expiry, option_type, strike
        FROM bronze_options_raw WHERE ticker = ?
        GROUP BY contractSymbol, expiry, option_type, strike
        HAVING COUNT(DISTINCT snapshot_str) >= 2
        ORDER BY expiry, strike, option_type
        """, [ticker]
    )

def get_contract_history(symbol):
    return query(
        """
        SELECT snapshot_time, lastPrice, impliedVolatility, delta, volume, openInterest
        FROM bronze_options_raw WHERE contractSymbol = ?
        ORDER BY snapshot_time
        """, [symbol]
    )

def get_ohlc_data(symbol):
    """Build synthetic OHLC from open(9:35)+close(16:15) snapshots."""
    df = query(
        """
        SELECT snapshot_time::DATE AS trade_date, snapshot_time, lastPrice, openInterest
        FROM bronze_options_raw
        WHERE contractSymbol = ? AND lastPrice > 0 AND impliedVolatility > 0.01
        ORDER BY snapshot_time
        """, [symbol]
    )
    if df.empty:
        return pandas.DataFrame(columns=["date","open","high","low","close","oi"])

    df["hour"]  = pandas.to_datetime(df["snapshot_time"]).dt.hour
    morning     = df[df["hour"] < 12].groupby("trade_date")["lastPrice"].first()
    afternoon   = df[df["hour"] >= 12].groupby("trade_date")["lastPrice"].last()
    oi_daily    = df.groupby("trade_date")["openInterest"].last()

    ohlc = pandas.DataFrame({"open": morning, "close": afternoon}).reindex(sorted(set(morning.index) | set(afternoon.index)))
    ohlc["open"]  = ohlc["open"].combine_first(ohlc["close"])
    ohlc["close"] = ohlc["close"].combine_first(ohlc["open"])
    ohlc["high"]  = ohlc[["open","close"]].max(axis=1)
    ohlc["low"]   = ohlc[["open","close"]].min(axis=1)
    ohlc["oi"]    = oi_daily
    return ohlc.reset_index().rename(columns={"trade_date":"date"}).dropna(subset=["open","close"])

# ── Candlestick renderer ──────────────────────────────────────────────────────
def render_candlestick(symbol, timeframe_days=None):
    ohlc = get_ohlc_data(symbol)
    if ohlc.empty:
        st.info("Not enough open/close snapshot pairs yet — check back after market open tomorrow.")
        return

    # Apply timeframe filter to OHLC candles
    # Slices from most recent candle backwards so weekends don't cause empty charts
    if timeframe_days is not None:
        cutoff = pandas.to_datetime(ohlc["date"]).max() - pandas.Timedelta(days=timeframe_days)
        ohlc = ohlc[pandas.to_datetime(ohlc["date"]) >= cutoff]

    if ohlc.empty:
        st.info(f"No candles in the selected {timeframe_days}-day window yet.")
        return

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.03)

    fig.add_trace(go.Candlestick(
        x=ohlc["date"], open=ohlc["open"], high=ohlc["high"], low=ohlc["low"], close=ohlc["close"],
        name=symbol,
        increasing_line_color="#2ea043", decreasing_line_color="#f85149",
        increasing_fillcolor="#2ea043",  decreasing_fillcolor="#f85149",
        hovertemplate="<b>%{x}</b><br>Open: $%{open:.2f}<br>High: $%{high:.2f}<br>Low: $%{low:.2f}<br>Close: $%{close:.2f}<extra></extra>",
    ), row=1, col=1)

    oi_colors = ["#2ea043" if c >= o else "#f85149" for o, c in zip(ohlc["open"], ohlc["close"])]
    fig.add_trace(go.Bar(x=ohlc["date"], y=ohlc["oi"], name="OI", marker_color=oi_colors, opacity=0.7,
        hovertemplate="OI: %{y:,.0f}<extra></extra>"), row=2, col=1)

    fig.update_layout(paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="#e0e0e0", height=500,
        margin=dict(t=20, b=40, l=60, r=20), showlegend=False, hovermode="x unified", xaxis_rangeslider_visible=False)
    fig.update_xaxes(gridcolor="#21262d", color="#8b949e", row=1, col=1)
    fig.update_yaxes(title_text="Price ($)", gridcolor="#21262d", color="#8b949e", row=1, col=1)
    fig.update_xaxes(gridcolor="#21262d", color="#8b949e", row=2, col=1)
    fig.update_yaxes(title_text="Open Interest", gridcolor="#21262d", color="#8b949e", row=2, col=1)

    for event_name, event_date in CATALYST_EVENTS.items():
        for row in [1, 2]:
            fig.add_vline(x=event_date, line_width=1, line_dash="dot", line_color="#bc8cff", row=row, col=1)
        fig.add_annotation(x=event_date, y=1, yref="paper", text=event_name, showarrow=False,
            font=dict(color="#bc8cff", size=11), bgcolor="#0e1117", bordercolor="#bc8cff",
            borderwidth=1, xanchor="left", yanchor="top")

    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"{symbol} · Open = 9:35 AM · Close = 4:15 PM · {len(ohlc)} trading days · OI bars match candle direction")

# ── Session state ─────────────────────────────────────────────────────────────
if "watchlist" not in st.session_state:
    st.session_state["watchlist"] = []
if "watchlist_ticker" not in st.session_state:
    st.session_state["watchlist_ticker"] = ticker

if st.session_state["watchlist_ticker"] != ticker:
    st.session_state["watchlist"] = []
    st.session_state["watchlist_ticker"] = ticker

# ── Contract selector ─────────────────────────────────────────────────────────
contracts_df = get_watchlist_contracts(ticker)
if contracts_df.empty:
    st.warning(f"No trackable contracts for {ticker} yet.")
    st.stop()

sel1, sel2, sel3, sel4 = st.columns([2, 1, 1, 1])

with sel1:
    expiries      = contracts_df["expiry"].astype(str).str[:10].unique().tolist()
    expiry_labels = [format_expiry(e) for e in expiries]
    sel_expiry_label = st.selectbox("Expiry", expiry_labels, key="tracker_expiry")
    sel_expiry = expiries[expiry_labels.index(sel_expiry_label)]

filtered = contracts_df[contracts_df["expiry"].astype(str).str[:10] == sel_expiry]

with sel2:
    sel_type = st.selectbox("Type", ["Call", "Put"], key="tracker_type")

filtered = filtered[filtered["option_type"] == sel_type.lower()]

with sel3:
    strikes = sorted(filtered["strike"].unique().tolist())
    sel_strike = st.selectbox("Strike", [f"${s:.0f}" for s in strikes], key="tracker_strike")
    sel_strike_val = float(sel_strike.replace("$", ""))

with sel4:
    st.write("")
    st.write("")
    add_clicked = st.button("➕ Add to Watchlist", key="tracker_add")

if add_clicked:
    row = filtered[filtered["strike"] == sel_strike_val]
    if not row.empty:
        symbol = row.iloc[0]["contractSymbol"]
        if symbol not in st.session_state["watchlist"]:
            st.session_state["watchlist"].append(symbol)

# ── Watchlist pills ───────────────────────────────────────────────────────────
if st.session_state["watchlist"]:
    st.markdown("**Watchlist:**")
    cols = st.columns(len(st.session_state["watchlist"]))
    for i, symbol in enumerate(st.session_state["watchlist"]):
        with cols[i]:
            if st.button(f"✕ {symbol}", key=f"remove_{symbol}"):
                st.session_state["watchlist"].remove(symbol)
                st.rerun()

# ── Chart type + metric + timeframe ───────────────────────────────────────────
ctrl_a, ctrl_b, ctrl_c = st.columns([2, 2, 2])

with ctrl_a:
    chart_type = st.radio("Chart type", ["Line", "Candlestick"], horizontal=True, key="tracker_chart_type")

with ctrl_b:
    metric_map = {
        "Price": ("lastPrice",         "Price ($)"),
        "IV":    ("impliedVolatility", "IV %"),
        "Delta": ("delta",             "Delta"),
    }
    if chart_type == "Line":
        metric_label = st.radio("Metric", list(metric_map.keys()), horizontal=True, key="tracker_metric")
        metric_col, y_label = metric_map[metric_label]

with ctrl_c:
    # Timeframe selector — shared across both line and candlestick chart types
    # Why shared: switching chart type while keeping the same time window avoids disorientation
    # Default 1M: wide enough for meaningful context, not so wide early sparse data dominates
    TIMEFRAMES = {
        "1W":  7,    # 7 days — ~14 data points at 2 snapshots/day
        "1M":  30,   # 30 days — ~60 data points
        "3M":  90,   # 90 days — covers WWDC to iPhone launch in one view
        "All": None, # no filter — full history from first snapshot
    }
    timeframe_label = st.radio(
        "Timeframe", list(TIMEFRAMES.keys()),
        index=1,            # default to 1M
        horizontal=True,
        key="tracker_timeframe"
    )
    timeframe_days = TIMEFRAMES[timeframe_label]

# ── Render chart ──────────────────────────────────────────────────────────────
if not st.session_state["watchlist"]:
    st.info("Select a contract above and click ➕ Add to Watchlist to begin tracking.")
    st.stop()

if chart_type == "Candlestick":
    if len(st.session_state["watchlist"]) > 1:
        st.warning("Candlestick shows one contract at a time. Displaying first pinned contract.")
    render_candlestick(st.session_state["watchlist"][0], timeframe_days=timeframe_days)
else:
    fig    = go.Figure()
    colors = ["#388bfd","#f0c040","#2ea043","#f85149","#bc8cff","#79c0ff"]

    for i, symbol in enumerate(st.session_state["watchlist"]):
        df = get_contract_history(symbol)
        if df.empty or metric_col not in df.columns:
            continue
        df = df.dropna(subset=[metric_col])

        # Apply timeframe filter — slice to last N days from most recent snapshot
        # Why from most recent snapshot not today: avoids empty charts on weekends/holidays
        if timeframe_days is not None:
            cutoff = pandas.to_datetime(df["snapshot_time"]).max() - pandas.Timedelta(days=timeframe_days)
            df = df[pandas.to_datetime(df["snapshot_time"]) >= cutoff]
        color   = colors[i % len(colors)]
        y_vals  = df[metric_col] * 100 if metric_col == "impliedVolatility" else df[metric_col]
        h_fmt   = ".2f%" if metric_col == "impliedVolatility" else ".4f"

        fig.add_trace(go.Scatter(
            x=df["snapshot_time"], y=y_vals, mode="lines+markers", name=symbol,
            line=dict(color=color, width=2), marker=dict(size=6),
            hovertemplate=f"{symbol}<br>%{{x|%b %d %H:%M}}<br>{metric_label}: %{{y:{h_fmt}}}<extra></extra>",
        ))

    fig.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="#e0e0e0", height=400,
        margin=dict(t=20, b=40, l=60, r=20),
        xaxis=dict(title="Snapshot Time", gridcolor="#21262d", color="#8b949e"),
        yaxis=dict(title=y_label, gridcolor="#21262d", color="#8b949e", zeroline=False),
        legend=dict(bgcolor="#161b22", bordercolor="#30363d", borderwidth=1),
        hovermode="x unified",
    )

    for event_name, event_date in CATALYST_EVENTS.items():
        fig.add_vline(x=event_date, line_width=1, line_dash="dot", line_color="#bc8cff")
        fig.add_annotation(x=event_date, y=1, yref="paper", text=event_name, showarrow=False,
            font=dict(color="#bc8cff", size=11), bgcolor="#0e1117", bordercolor="#bc8cff",
            borderwidth=1, xanchor="left", yanchor="top")

    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Data from Bronze layer · {len(st.session_state['watchlist'])} contract(s) tracked")

# ── Auto-refresh ──────────────────────────────────────────────────────────────
import time
if refresh_secs:
    time.sleep(refresh_secs)
    st.rerun()
