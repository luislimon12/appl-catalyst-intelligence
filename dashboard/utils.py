# ──────────────────────────────────────────────────────────────────────────────
# utils.py
# Shared config, DB connection, and helper functions used by all dashboard pages.
# Session 3 (Jun 2026): extracted from app.py during multipage split
# ──────────────────────────────────────────────────────────────────────────────

import subprocess  ## Jun 22 2026: needed to launch pipeline script as a child process
import sys          ## Jun 22 2026: gives us the current Python interpreter path
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
    "WWDC 2026":         "2026-06-09",   ## past — still shows on Contract Tracker historical charts
    "Q3 Earnings":       "2026-07-30",   ## confirmed — Tim Cook + Kevan Parekh call at 5PM EDT
    "~CEO Transition":   "2026-09-01",   ## estimated — John Ternus assumes CEO, Cook → Exec Chairman
    "~iPhone 18 Keynote":"2026-09-09",   ## estimated — iPhone 18 Pro / Pro Max / foldable unveil
    "~iPhone Ultra":     "2026-10-28",   ## estimated — staggered release, late Oct/early Nov window
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
        min-width: 140px;
        min-height: 80px;
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

## Jun 21 2026: colorblind mode toggle — blue/orange replaces green/red across all charts
## Toggle lives in sidebar (render_sidebar), state stored in st.session_state["colorblind_mode"]
def bull_color() -> str:
    """Bullish/up color. Blue in colorblind mode, green in normal mode."""
    if st.session_state.get("colorblind_mode"):
        return "#388bfd"  # blue — safe for red-green colorblindness
    return "#2ea043"      # green — normal mode

def bear_color() -> str:
    """Bearish/down color. Orange in colorblind mode, red in normal mode."""
    if st.session_state.get("colorblind_mode"):
        return "#f0a500"  # orange — safe for red-green colorblindness
    return "#f85149"      # red — normal mode

def pcr_color(val: float) -> str:
    """Return hex color based on PCR value. Uses bull/bear colors from current mode."""
    if val < 0.7:
        return bull_color()   # call-heavy, bullish
    elif val <= 1.0:
        return "#e0e0e0"      # neutral
    else:
        return bear_color()   # put-heavy, bearish

def metric_card(label: str, value: str, delta: str = None, delta_color: str = "normal"):
    ## Jun 21 2026: standardized metric card used across all pages
    ## Wraps st.metric so all cards share the same CSS styling defined in DARK_THEME_CSS
    ## delta_color "normal" = green up/red down, "inverse" = red up/green down (used for IV)
    st.metric(label=label, value=value, delta=delta, delta_color=delta_color)

def get_spot_price(ticker: str):
    """Return the most recent closing price for ticker, or None if unavailable."""
    df = query(
        "SELECT price_close FROM gold_latest_snapshot WHERE ticker = ? LIMIT 1",
        [ticker]
    )
    if df.empty:
        return None
    return float(df.iloc[0]["price_close"])

def render_page_header(icon: str, title: str, subtitle: str, ticker: str):
    ## Jun 21 2026: standardized header used across all pages
    ## Shows icon + title + ticker on left, last snapshot time on right — same layout everywhere
    last_snap = query("SELECT MAX(snapshot_time) FROM bronze_options_raw WHERE ticker = ?", [ticker]).iloc[0, 0]
    snap_str  = pandas.to_datetime(last_snap).strftime("%b %d %I:%M %p") if last_snap else "No data yet"

    col1, col2 = st.columns([3, 1])
    with col1:
        st.title(f"{icon} {title} — {ticker}")
        st.caption(subtitle)
    with col2:
        st.markdown(
            f"<div style='text-align:right; color:#8b949e; padding-top:16px'>🕐 {snap_str}</div>",
            unsafe_allow_html=True
        )
    st.divider()

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
        ## Jun 21 2026: colorblind mode toggle — switches all charts from green/red to blue/orange
        st.toggle("🎨 Colorblind mode", value=False, key="colorblind_mode")
        st.divider()

        ## Jun 21 2026: data freshness indicator
        ## Green = within 8h (normal), Yellow = 8-24h (missed session), Red = >24h (LaunchAgent failed)
        last_snap = query("SELECT MAX(snapshot_time) FROM bronze_options_raw").iloc[0, 0]
        if last_snap:
            last_snap_dt = pandas.to_datetime(last_snap)
            hours_ago    = (pandas.Timestamp.now() - last_snap_dt).total_seconds() / 3600
            snap_str     = last_snap_dt.strftime("%b %d %I:%M %p")
            if hours_ago > 24:
                st.error(f"⚠️ Data stale: {snap_str}")
            elif hours_ago > 8:
                st.warning(f"🕐 Last snap: {snap_str}")
            else:
                st.success(f"✅ Last snap: {snap_str}")

        st.divider()

        ## Jun 22 2026: manual pipeline trigger — lets user refresh data without opening Terminal
        ## Clicking this runs collect_market_snapshots.py which chains build_database + build_silver
        if st.button("🔄 Refresh Data", help="Collect new snapshot & rebuild Silver/Gold tables"):
            with st.spinner("Collecting data..."):  ## show loading spinner while script runs

                ## Build absolute paths using this file's location as anchor
                ## __file__ = utils.py, .parent = dashboard/, .parent.parent = project root
                project_root    = Path(__file__).parent.parent                                ## ~/Apple-Project/appl-catalyst-intelligence
                pipeline_script = project_root / "src" / "pipeline" / "collect_market_snapshots.py"

                ## CRITICAL: release the DuckDB connection BEFORE launching the pipeline.
                ## build_database.py opens the .duckdb file in read-write mode.
                ## If the dashboard still holds a connection (even read-only), DuckDB will
                ## reject the write-mode open and exit with code 1.
                ## st.cache_resource.clear() destroys the cached connection object,
                ## so the file is free when the subprocess opens it.
                st.cache_resource.clear()  ## releases DuckDB connection so pipeline can open in write mode
                st.cache_data.clear()      ## flushes all @st.cache_data results so next render fetches fresh data

                ## Launch the script using the same Python that's running Streamlit right now.
                ## cwd=project_root — build_database.py uses relative path "appl_catalyst.duckdb"
                ##   which resolves against cwd, so we must set it to the project root.
                ## capture_output=True — catch stdout+stderr so we can show the full error in the UI.
                ## text=True — return output as a string (not bytes).
                ## timeout=180 — 3 min timeout; collecting all expiries can take 2+ minutes.
                result = subprocess.run(
                    [sys.executable, str(pipeline_script)],
                    cwd=str(project_root),
                    capture_output=True, text=True, timeout=180
                )

                if result.returncode == 0:  ## 0 = success (Unix convention)
                    st.success("✅ Data refreshed!")
                    st.rerun()  ## reload page — get_connection() will re-cache a fresh connection
                else:
                    ## Show full stdout + stderr so we can see exactly what failed
                    full_output = (result.stdout + "\n" + result.stderr).strip()
                    st.error(f"Pipeline failed:\n\n{full_output}")

        st.caption(f"DB: `{DB_PATH.name}`")
        st.caption(f"Last loaded: {time.strftime('%H:%M:%S')}")

    return ticker, refresh_secs
