# ──────────────────────────────────────────────────────────────────────────────
# utils.py
# Shared config, DB connection, and helper functions used by all dashboard pages.
# Session 3 (Jun 2026): extracted from app.py during multipage split
# ──────────────────────────────────────────────────────────────────────────────

import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas
import plotly.graph_objects as go
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
# DB_PATH resolves relative to this file — works regardless of where streamlit is called from
DB_PATH = Path(__file__).parent.parent / "appl_catalyst.duckdb"

TICKERS = ["AAPL", "INTC"]

CATALYST_EVENTS = {
    "WWDC 2026":          "2026-06-09",
    "iPhone Launch 2026": "2026-09-09",
}

REFRESH_OPTIONS = {
    "Off":    None,
    "30 sec": 30,
    "1 min":  60,
    "5 min":  300,
}

# ── Dark theme CSS ────────────────────────────────────────────────────────────
DARK_THEME_CSS = """
<style>
    .stApp { background-color: #0e1117; color: #e0e0e0; }
    section[data-testid="stSidebar"] { background-color: #161b22; }
    div[data-testid="metric-container"] {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 12px 16px;
    }
    .stDataFrame { border: 1px solid #30363d; border-radius: 8px; }
    h1, h2, h3 { color: #58a6ff; }
    hr { border-color: #30363d; }
</style>
"""

# ── DB connection ─────────────────────────────────────────────────────────────
@st.cache_resource
def get_connection():
    # cache_resource keeps one connection alive for the whole session
    # read_only prevents any accidental writes from the dashboard
    return duckdb.connect(str(DB_PATH), read_only=True)

def query(sql: str, params=None) -> pandas.DataFrame:
    con = get_connection()
    if params:
        return con.execute(sql, params).df()
    return con.execute(sql).df()

# ── Helpers ───────────────────────────────────────────────────────────────────
def format_expiry(expiry: str) -> str:
    """Convert '2026-06-20' → "Jun 20 '26". Passes 'ALL' through unchanged."""
    if expiry == "ALL":
        return "ALL"
    dt = datetime.strptime(expiry, "%Y-%m-%d")
    return dt.strftime("%b %d '%y")

def pcr_color(val: float) -> str:
    """Return hex color based on PCR value. Green = bullish, red = bearish."""
    if val < 0.7:
        return "#2ea043"   # green  — call-heavy, bullish
    elif val <= 1.0:
        return "#e0e0e0"   # white  — neutral
    else:
        return "#f85149"   # red    — put-heavy, bearish

def get_spot_price(ticker: str):
    """Return the most recent closing price for ticker, or None if unavailable."""
    df = query(
        "SELECT price_close FROM gold_latest_snapshot WHERE ticker = ? LIMIT 1",
        [ticker]
    )
    if df.empty:
        return None
    return float(df.iloc[0]["price_close"])

def render_sidebar(page_title: str):
    """
    Render the shared sidebar controls and return (ticker, refresh_secs).
    Called at the top of every page so controls are consistent across pages.
    """
    with st.sidebar:
        st.title("⚙️ Controls")
        st.divider()
        ticker = st.selectbox("Ticker", TICKERS, index=0)
        st.divider()
        refresh_label = st.selectbox("Auto-refresh", list(REFRESH_OPTIONS.keys()), index=0)
        refresh_secs  = REFRESH_OPTIONS[refresh_label]
        st.divider()
        st.caption(f"DB: `{DB_PATH.name}`")
        st.caption(f"Last loaded: {time.strftime('%H:%M:%S')}")

    return ticker, refresh_secs
