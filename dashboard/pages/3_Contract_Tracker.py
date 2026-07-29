"""
Page 3 — Contract Tracker
AAPL & INTC Catalyst Intelligence Dashboard
Session 3 (Jun 2026): Goal 6 — watchlist, line chart, candlestick with OI bars
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json                                ## built-in Python library for reading/writing JSON files
import pandas                              ## data manipulation
import plotly.graph_objects as go         ## plotly charts
import streamlit as st                    ## dashboard framework
from plotly.subplots import make_subplots ## multi-row chart layouts

from utils import CATALYST_EVENTS, DARK_THEME_CSS, bull_color, bear_color, format_expiry, query, render_sidebar, render_page_header

# ── Watchlist persistence ─────────────────────────────────────────────────────
WATCHLIST_FILE = Path(__file__).parent.parent / "watchlist.json"
## Path(__file__)      = absolute path to this file (3_Contract_Tracker.py)
## .parent             = goes up one level → pages/ folder
## .parent.parent      = goes up another level → project root
## / "watchlist.json"  = appends filename → project_root/watchlist.json

def load_ohlc_override(symbol: str, date: str) -> dict:
    ## read manual H/L correction from DB — pure read, uses existing read-only connection
    ## called inside get_today_ohlc() to merge user-corrected values over synthesised ones
    ## try/except: if table doesn't exist yet (script never run), returns {} safely
    try:
        df = query(
            """
            SELECT high, low FROM manual_ohlc_overrides
            WHERE symbol = ? AND date = CAST(? AS DATE)
            """,
            [symbol, date[:10]]   ## [:10] strips any midnight timestamp → "2026-07-13" only
        )
        if df.empty:
            return {}             ## no override saved for this symbol+date
        return df.iloc[0].to_dict()  ## {"high": 4.80, "low": 3.60}
    except Exception:
        return {}                 ## table doesn't exist yet — fall back to synthesised values

def load_watchlist(ticker: str) -> list:
    ## called on page load to restore saved contracts from disk
    ## ticker: str = "AAPL" or "INTC" — loads only that ticker's contracts
    ## -> list     = always returns a list (empty if nothing saved yet)
    if not WATCHLIST_FILE.exists():          ## check if file exists — first run it won't
        return []                            ## no file yet = empty watchlist
    with open(WATCHLIST_FILE, "r") as f:     ## open file in read mode
        data = json.load(f)                  ## json.load parses the file text into a Python dict
    return data.get(ticker, [])              ## .get(ticker, []) = return this ticker's list or [] if missing

def save_watchlist(ticker: str, watchlist: list):
    ## called every time user adds or removes a contract
    ## writes the updated list to disk so it survives restarts
    data = {}                                ## start with empty dict
    if WATCHLIST_FILE.exists():              ## if file already exists, load it first
        with open(WATCHLIST_FILE, "r") as f:
            data = json.load(f)              ## load existing data so other tickers aren't erased
    data[ticker] = watchlist                 ## overwrite only this ticker's list
    with open(WATCHLIST_FILE, "w") as f:     ## open file in write mode (creates if missing)
        json.dump(data, f, indent=2)         ## json.dump converts dict to JSON text, indent=2 = human readable

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="Contract Tracker · Catalyst Intelligence", page_icon="🔍", layout="wide", initial_sidebar_state="expanded")
st.markdown(DARK_THEME_CSS, unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
ticker, refresh_secs = render_sidebar("Contract Tracker")

# ── Header ────────────────────────────────────────────────────────────────────
render_page_header("🔍", "Contract Tracker", "Pin contracts to your watchlist and track price, IV, and delta over time", ticker)

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

@st.cache_data(ttl=60)  ## cache 60s — bronze_options_raw only changes when pipeline runs
def get_contract_history(symbol, metric_col="lastPrice"):
    ## Jun 25 2026: metric-aware snapshot filtering
    ##
    ## PROBLEM:
    ##   Multiple snapshots per day (9:35 AM + 4:15 PM + manual Refresh Data clicks)
    ##   created zigzag lines when plotting IV and Delta — same x position, different y values.
    ##
    ## SOLUTION — different filter per metric:
    ##
    ##   PRICE → show ALL market-hours snapshots (no daily dedup)
    ##     Reason: AM (open) and PM (close) are both meaningful for price.
    ##     Two dots per day = you can see intraday movement.
    ##     This is the same data the candlestick uses (open = AM, close = PM).
    ##
    ##   IV / DELTA → one snapshot per day (latest only)
    ##     Reason: IV and Delta don't need intraday resolution on a line chart.
    ##     Multiple snapshots same day create false zigzags (e.g. IV: 27% → 5% → 27%
    ##     within 10 minutes because of test button clicks). One daily dot = clean trend line.
    ##     We pick the LATEST snapshot because it has end-of-day settled values.

    if metric_col == "lastPrice":
        ## Price: no daily dedup — show AM + PM snapshots so line reflects intraday moves
        ## HOUR filter still applies to exclude midnight (stale) snapshots
        daily_dedup_filter = ""
    else:
        ## IV / Delta: deduplicate to one row per calendar day — the latest market-hours snapshot
        ## Correlated subquery: for each row b, check if its snapshot_time equals the
        ## MAX snapshot_time on the same date for the same contract.
        ## Only rows that match (i.e. the latest snapshot that day) pass through.
        daily_dedup_filter = """
            AND snapshot_time = (
                SELECT MAX(b2.snapshot_time)                          -- latest snapshot this day
                FROM bronze_options_raw b2
                WHERE b2.contractSymbol = b.contractSymbol            -- same contract
                AND DATE(b2.snapshot_time) = DATE(b.snapshot_time)    -- same calendar day
                AND HOUR(b2.snapshot_time) BETWEEN 9 AND 18          -- market hours only
            )
        """

    return query(
        f"""
        SELECT snapshot_time, lastPrice, impliedVolatility, delta, theta, gamma, volume, openInterest
        -- Jul 2026: added theta (daily decay) and gamma (delta sensitivity) to SELECT
        -- theta and gamma are stored in bronze layer from yfinance options chain
        FROM bronze_options_raw b
        WHERE contractSymbol = ?

        -- Jun 17 2026: exclude overnight/pre-market snapshots
        -- Midnight runs return IV near 0% (bid=ask=0, market closed) — corrupts the chart
        -- Only keep snapshots between 9 AM and 6 PM
        AND HOUR(snapshot_time) BETWEEN 9 AND 18

        -- Jun 25 2026: injected dynamically based on metric_col
        -- Empty string for Price (show all snapshots)
        -- Correlated subquery for IV/Delta (one point per day, latest only)
        {daily_dedup_filter}

        ORDER BY snapshot_time  -- chronological so line connects left to right
        """, [symbol]
    )

@st.cache_data(ttl=60)  ## cache 60s — lifetime high/low doesn't change mid-session
def get_contract_highlow(symbol: str) -> dict:
    ## fetch the lifetime high and low lastPrice for this contract
    ## used to draw horizontal reference lines on the Price + IV line chart
    ## lastPrice > 0 excludes stale zero prints from pre/post market
    ## HOUR filter excludes overnight garbage values
    df = query("""
        SELECT
            MAX(lastPrice) AS contract_high,  -- highest price ever recorded for this contract
            MIN(lastPrice) AS contract_low     -- lowest price ever recorded for this contract
        FROM bronze_options_raw
        WHERE contractSymbol = ?
        AND lastPrice > 0
        AND HOUR(snapshot_time) BETWEEN 9 AND 18
    """, [symbol])
    if df.empty:                              ## no data yet — return None so chart skips the lines
        return {"contract_high": None, "contract_low": None}
    return df.iloc[0].to_dict()              ## return as dict e.g. {"contract_high": 8.20, "contract_low": 0.50}

def get_today_ohlc(symbol: str) -> dict:
    ## reuse get_ohlc_data() which already builds open/high/low/close from AM+PM snapshots
    ## grab the most recent row = latest trading day with both AM and PM snapshots
    ohlc = get_ohlc_data(symbol)
    if ohlc.empty:                    ## no OHLC data yet — need at least one AM+PM pair
        return None
    row = ohlc.iloc[-1]               ## .iloc[-1] = last row = most recent trading day
    result = {
        "date":  str(row["date"]),    ## trading date e.g. "2026-07-13"
        "open":  row["open"],         ## AM snapshot price (9:35)
        "high":  row["high"],         ## higher of open/close — synthetic high (only 2 snapshots/day)
        "low":   row["low"],          ## lower of open/close — synthetic low
        "close": row["close"],        ## PM snapshot price (4:15)
    }
    ## merge manual override — user-entered values from script win over synthesised values
    ## only overwrites H/L — open and close come from actual snapshots, no correction needed
    override = load_ohlc_override(symbol, result["date"])
    if override.get("high") is not None:  ## only replace if an override exists for this date
        result["high"] = override["high"]
    if override.get("low") is not None:
        result["low"] = override["low"]
    return result

@st.cache_data(ttl=60)  ## cache 60s — Greeks only update when new snapshot arrives
def get_current_greeks(symbol):
    ## Jul 2026: fetch latest snapshot values for Δ Delta, Θ Theta, Γ Gamma metric cards
    ## These are shown as always-visible numbers below the watchlist — no chart needed
    ## ORDER BY snapshot_time DESC = most recent row first
    ## LIMIT 1 = we only want the single latest snapshot (current Greek values)
    ## HOUR BETWEEN 9 AND 18 = exclude overnight/pre-market rows where Greeks are stale
    return query("""
        SELECT delta, theta, gamma
        FROM bronze_options_raw
        WHERE contractSymbol = ?
        AND HOUR(snapshot_time) BETWEEN 9 AND 18
        ORDER BY snapshot_time DESC
        LIMIT 1
    """, [symbol])

@st.cache_data(ttl=60)  ## cache 60s — OHLC built from bronze snapshots, only changes when pipeline runs
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

# ── OI & Volume renderer ─────────────────────────────────────────────────────
def render_oi_volume(symbol, timeframe_days=None):
    ## Pull volume and OI for the pinned contract — market hours only (same filter as line chart)
    df = query(
        """
        SELECT snapshot_time, volume, openInterest
        FROM bronze_options_raw WHERE contractSymbol = ?
        -- Jun 18 2026: PM-only filter for OI & Volume
        -- OI updates once/day after market close (OCC report) — AM snapshot is identical to prior PM
        -- Volume resets to 0 at open — AM snapshot is partial, only PM shows full day volume
        AND HOUR(snapshot_time) >= 15
        ORDER BY snapshot_time
        """, [symbol]
    )
    if df.empty:
        return

    ## Apply same timeframe filter as main chart so both stay in sync
    if timeframe_days is not None:
        cutoff = pandas.to_datetime(df["snapshot_time"]).max() - pandas.Timedelta(days=timeframe_days)
        df = df[pandas.to_datetime(df["snapshot_time"]) >= cutoff]

    if df.empty:
        return

    df = df.copy()

    ## OI change: compare each snapshot to the previous one using shift(1)
    ## Green = OI increased (new contracts opened = bullish positioning signal)
    ## Red = OI decreased (contracts closed or expired)
    df["oi_prev"]   = df["openInterest"].shift(1)
    df["oi_change"] = df["openInterest"] - df["oi_prev"]
    ## Jun 21 2026: use bull/bear color helpers so colorblind toggle applies to OI bars
    oi_colors = [bull_color() if v >= 0 else bear_color() for v in df["oi_change"].fillna(0)]

    ## Stack OI on top, Volume below — shared x-axis so panning/zooming moves both together
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        row_heights=[0.5, 0.5], vertical_spacing=0.08,
        subplot_titles=["Open Interest", "Volume"]
    )

    ## OI hover text — shows total OI + delta vs previous snapshot (e.g. "OI: 22,968 (+524)")
    ## Jun 18 2026: added delta to hover so positioning changes are readable without comparing bars
    oi_hover = []
    for oi, chg in zip(df["openInterest"], df["oi_change"]):
        if pandas.isna(chg):
            oi_hover.append(f"OI: {int(oi):,}")
        else:
            sign = "+" if chg >= 0 else ""
            oi_hover.append(f"OI: {int(oi):,} ({sign}{int(chg):,})")

    ## OI bars — height = total OI, color = direction of change vs previous snapshot
    ## customdata used instead of text — text doesn't render in subplot hovertemplate
    ## width=43200000ms = 12 hours — makes bars visible even with sparse data
    fig.add_trace(go.Bar(
        x=df["snapshot_time"], y=df["openInterest"],
        marker_color=oi_colors, name="OI",
        customdata=oi_hover, width=43200000,
        hovertemplate="%{x|%b %d %H:%M}<br>%{customdata}<extra></extra>",
    ), row=1, col=1)

    ## Volume bars — blue; spikes before catalyst dates = unusual positioning signal
    fig.add_trace(go.Bar(
        x=df["snapshot_time"], y=df["volume"],
        marker_color="#388bfd", name="Volume", opacity=0.8, width=43200000,
        hovertemplate="%{x|%b %d %H:%M}<br>Vol: %{y:,.0f}<extra></extra>",
    ), row=2, col=1)

    ## Catalyst markers on both subplots — purple dotted lines matching main chart style
    for event_name, event_date in CATALYST_EVENTS.items():
        for row in [1, 2]:
            fig.add_vline(x=event_date, line_width=1, line_dash="dot", line_color="#bc8cff", row=row, col=1)

    ## Cap x-axis 30 days past last data point — prevents empty chart stretching to catalyst dates
    x_end = pandas.to_datetime(df["snapshot_time"]).max() + pandas.Timedelta(days=30)

    fig.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="#e0e0e0",
        height=350, margin=dict(t=30, b=40, l=60, r=20),
        showlegend=False, hovermode="x unified", bargap=0.1,
    )
    fig.update_xaxes(gridcolor="#21262d", color="#8b949e", range=[df["snapshot_time"].min(), x_end])
    ## rangemode=nonnegative locks y-axis min to 0 — OI and Volume are always positive
    fig.update_yaxes(gridcolor="#21262d", color="#8b949e", rangemode="nonnegative")
    fig.update_yaxes(title_text="OI", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)

    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"{symbol} · Green OI = contracts opened · Red OI = contracts closed · Market hours only")

# ── Candlestick renderer ──────────────────────────────────────────────────────
def render_candlestick(symbol, timeframe_days=None):
    ohlc = get_ohlc_data(symbol)
    if ohlc.empty:
        ## Jun 21 2026: descriptive empty state — explains what's needed for candlestick to render
        st.info("📊 Not enough data for candlestick yet.\n\nCandlestick needs at least one AM (9:35) and one PM (4:15) snapshot on the same day. Check back after 4:15 PM today.")
        return

    # Apply timeframe filter to OHLC candles
    # Slices from most recent candle backwards so weekends don't cause empty charts
    if timeframe_days is not None:
        cutoff = pandas.to_datetime(ohlc["date"]).max() - pandas.Timedelta(days=timeframe_days)
        ohlc = ohlc[pandas.to_datetime(ohlc["date"]) >= cutoff]

    if ohlc.empty:
        ## Jun 21 2026: suggests switching to All so user doesn't think data is missing entirely
        st.info(f"📅 No candles in the {timeframe_days}-day window.\n\nYour earliest data for this contract is outside this range. Try switching to 'All' to see everything available.")
        return

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.03)

    fig.add_trace(go.Candlestick(
        x=ohlc["date"], open=ohlc["open"], high=ohlc["high"], low=ohlc["low"], close=ohlc["close"],
        name=symbol,
        increasing_line_color=bull_color(), decreasing_line_color=bear_color(),  ## colorblind-aware
        increasing_fillcolor=bull_color(),  decreasing_fillcolor=bear_color(),
        hovertemplate="<b>%{x}</b><br>Open: $%{open:.2f}<br>High: $%{high:.2f}<br>Low: $%{low:.2f}<br>Close: $%{close:.2f}<extra></extra>",
    ), row=1, col=1)

    ## Jun 21 2026: EMA overlays on candlestick panel
    ## EMA = exponential moving average — weights recent prices more than older ones

    ## 8 EMA — fast, tracks price closely, good for short-term entries and exits
    ema_8   = ohlc["close"].ewm(span=8,   adjust=False).mean()  ## ewm = exponential weighted mean
    ## 27 EMA — mid trend, used to confirm direction of move
    ema_27  = ohlc["close"].ewm(span=27,  adjust=False).mean()  ## span=27 = lookback period
    ## 200 EMA — macro trend line used by institutional traders as key reference level
    ## NOTE: needs 200 candles to be fully meaningful — will be flat early with sparse data
    ema_200 = ohlc["close"].ewm(span=200, adjust=False).mean()  ## span=200 = lookback period

    ## Green line = 8 EMA — fast, sits close to price action
    fig.add_trace(go.Scatter(
        x=ohlc["date"],      ## x-axis = trading date
        y=ema_8,             ## y = 8-period EMA values
        name="EMA 8",        ## legend label
        mode="lines",        ## line only, no dots
        line=dict(color="#2ea043", width=1.5),  ## green, thin
        hovertemplate="EMA 8: $%{y:.2f}<extra></extra>",
    ), row=1, col=1)         ## candlestick panel only

    ## Blue line = 27 EMA — mid trend direction
    fig.add_trace(go.Scatter(
        x=ohlc["date"],      ## x-axis = trading date
        y=ema_27,            ## y = 27-period EMA values
        name="EMA 27",       ## legend label
        mode="lines",        ## line only, no dots
        line=dict(color="#388bfd", width=1.5),  ## blue, thin
        hovertemplate="EMA 27: $%{y:.2f}<extra></extra>",
    ), row=1, col=1)         ## candlestick panel only

    ## Purple dotted line = 200 EMA — institutional macro trend reference
    fig.add_trace(go.Scatter(
        x=ohlc["date"],      ## x-axis = trading date
        y=ema_200,           ## y = 200-period EMA values
        name="EMA 200",      ## legend label
        mode="lines",        ## line only, no dots
        line=dict(color="#bc8cff", width=2, dash="dot"),  ## purple dotted, slightly thicker
        hovertemplate="EMA 200: $%{y:.2f}<extra></extra>",
    ), row=1, col=1)         ## candlestick panel only

    ## Jun 21 2026: use bull/bear color helpers so colorblind toggle applies to candlestick OI bars
    oi_colors = [bull_color() if c >= o else bear_color() for o, c in zip(ohlc["open"], ohlc["close"])]
    fig.add_trace(go.Bar(x=ohlc["date"], y=ohlc["oi"], name="OI", marker_color=oi_colors, opacity=0.7,
        hovertemplate="OI: %{y:,.0f}<extra></extra>"), row=2, col=1)

    fig.update_layout(paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="#e0e0e0", height=500,
        margin=dict(t=20, b=40, l=60, r=20), hovermode="x unified", xaxis_rangeslider_visible=False,
        showlegend=True, legend=dict(bgcolor="#161b22", bordercolor="#30363d", borderwidth=1))
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
if "watchlist" not in st.session_state:          ## only runs on first page load, not every rerun
    st.session_state["watchlist"] = load_watchlist(ticker)  ## reads from JSON instead of starting empty
if "watchlist_ticker" not in st.session_state:
    st.session_state["watchlist_ticker"] = ticker

if st.session_state["watchlist_ticker"] != ticker:
    st.session_state["watchlist"] = load_watchlist(ticker)  ## load saved contracts for new ticker instead of clearing to empty
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
        if symbol not in st.session_state["watchlist"]:           ## prevent duplicates
            st.session_state["watchlist"].append(symbol)           ## add to in-memory list
            save_watchlist(ticker, st.session_state["watchlist"])  ## immediately write to JSON on disk

# ── Watchlist pills ───────────────────────────────────────────────────────────
if st.session_state["watchlist"]:            ## only render if at least one contract is pinned
    with st.container(border=True):          ## bordered card visually separates watchlist from controls below
        cols = st.columns(4)                 ## fixed 4 columns — buttons stay readable regardless of count
        for i, symbol in enumerate(st.session_state["watchlist"]):  ## loop through pinned contracts
            if cols[i % 4].button(           ## i % 4 cycles 0,1,2,3,0,1,2,3 — wraps to new row after 4
                f"✕ {symbol}",              ## button label shows contract symbol with X to remove
                key=f"remove_{symbol}"      ## unique key required by Streamlit when buttons are in a loop
            ):
                st.session_state["watchlist"].remove(symbol)           ## remove from in-memory list
                save_watchlist(ticker, st.session_state["watchlist"])  ## write updated list to JSON
                st.rerun()                                             ## refresh page to reflect removal

# ── Current Greeks metric cards ───────────────────────────────────────────────
## Jul 2026: always-visible Greek snapshot for the first pinned contract
## Shows Δ Delta, Θ Theta, Γ Gamma as number cards so user doesn't have to switch chart modes
## Only renders when at least one contract is pinned (watchlist not empty)
if st.session_state["watchlist"]:
    greeks_df = get_current_greeks(st.session_state["watchlist"][0])  ## fetch latest Greeks for first contract
    if not greeks_df.empty:                                            ## guard: no data yet = skip cards
        g = greeks_df.iloc[0]                                          ## .iloc[0] = grab the single row as a Series

        mc1, mc2, mc3 = st.columns(3)                                 ## three equal-width columns, one card each

        with mc1:
            ## Delta: how many dollars the option moves per $1 stock move
            ## Puts = negative (option gains when stock falls), Calls = positive
            ## .4f = show 4 decimal places (delta is small, e.g. -0.1042)
            ## pandas.notna() safely checks for NaN/None without raising TypeError on pandas.NA
            val = f"{g['delta']:.4f}" if pandas.notna(g['delta']) else "—"  ## "—" when no data
            st.metric("Δ Delta", val, help="$change in option price per $1 move in stock")

        with mc2:
            ## Theta: daily time decay in dollars — always negative for long options
            ## e.g. -0.08 means this option loses $0.08 per calendar day just from time passing
            ## Theta accelerates (gets more negative) in the final 30 days before expiry
            val = f"{g['theta']:.4f}" if pandas.notna(g['theta']) else "—"  ## "—" when no data
            st.metric("Θ Theta", val, help="Daily time decay. Negative = losing this much per day. Accelerates near expiry.")

        with mc3:
            ## Gamma: rate of change of delta per $1 stock move
            ## High gamma (near ATM, near expiry) = delta changes fast = option is explosive/risky
            ## Low gamma (deep OTM or far expiry) = delta barely moves = option is stable
            val = f"{g['gamma']:.4f}" if pandas.notna(g['gamma']) else "—"  ## "—" when no data
            st.metric("Γ Gamma", val, help="How fast delta changes per $1 stock move. Peaks ATM near expiry.")

    st.divider()                                                       ## visual separator before chart controls

# ── Today's OHLC metric cards ─────────────────────────────────────────────────
## Jul 2026: shows Open/High/Low/Close for the first pinned contract
## OHLC is synthesised from two snapshots: AM (≈9:35) = open, PM (≈4:15) = close
## High and Low are the max/min lastPrice seen across ALL snapshots that day
## Only renders when the watchlist has at least one contract
if st.session_state["watchlist"]:
    ohlc_today = get_today_ohlc(st.session_state["watchlist"][0])  ## pull OHLC for first pinned contract
    if ohlc_today:                                                  ## guard: None when no data for today
        st.caption(                                                 ## small note explaining data source
            f"📅 {ohlc_today['date']} · Open = 9:35 AM snapshot · Close = 4:15 PM snapshot"
        )
        c1, c2, c3, c4 = st.columns(4)                            ## four equal columns, one card per OHLC field

        c1.metric("Open",  f"${ohlc_today['open']:.2f}")          ## morning price — no delta (nothing to compare to)

        c2.metric(                                                  ## High card: delta = how far above open
            "High",
            f"${ohlc_today['high']:.2f}",
            delta=f"+${ohlc_today['high'] - ohlc_today['open']:.2f} from open",  ## positive $ move from open
            delta_color="normal"                                    ## green = higher than open is good
        )

        c3.metric(                                                  ## Low card: delta = how far below open
            "Low",
            f"${ohlc_today['low']:.2f}",
            delta=f"-${ohlc_today['open'] - ohlc_today['low']:.2f} from open",   ## negative $ move from open
            delta_color="inverse"                                   ## inverse: red means lower than open (expected for Low)
        )

        close_delta = ohlc_today['close'] - ohlc_today['open']     ## end-of-day P&L vs morning price
        c4.metric(                                                  ## Close card: shows net day move
            "Close",
            f"${ohlc_today['close']:.2f}",
            delta=f"{close_delta:+.2f} vs open",                   ## +/- format shows direction clearly
            delta_color="normal"                                    ## green = closed above open (profitable long)
        )

# ── Chart type + metric + timeframe ───────────────────────────────────────────
ctrl_a, ctrl_b, ctrl_c = st.columns([2, 2, 2])

with ctrl_a:
    chart_type = st.radio("Chart type", ["Line", "Candlestick"], horizontal=True, key="tracker_chart_type")

with ctrl_b:
    ## Jun 25 2026: replaced single-metric radio with dual-axis toggle + Delta option
    ## Price + IV always shown together on dual-axis chart (Price left, IV right)
    ## Delta kept as a separate toggle since it doesn't pair naturally with price
    if chart_type == "Line":
        ## Jul 2026: expanded from ["Price + IV", "Delta"] to include Theta and Gamma
        ## Price + IV = dual-axis (price left, IV right) — most useful for understanding option value
        ## Delta = directional exposure over time — shows how ATM/OTM the contract was each day
        ## Theta = time decay over time — shows how fast the option was bleeding each day
        ## Gamma = delta sensitivity over time — shows when the option was most explosive
        overlay = st.radio("Overlay", ["Price + IV", "Delta", "Theta", "Gamma"], horizontal=True, key="tracker_metric")

with ctrl_c:
    # Timeframe selector — shared across both line and candlestick chart types
    # Why shared: switching chart type while keeping the same time window avoids disorientation
    # Default 1M: wide enough for meaningful context, not so wide early sparse data dominates
    TIMEFRAMES = {
        "1D":  1,    # 1 day — AM + PM snapshots from most recent trading day
        "1W":  7,    # 7 days — ~14 data points at 2 snapshots/day
        "1M":  30,   # 30 days — ~60 data points
        "3M":  90,   # 90 days — covers WWDC to iPhone launch in one view
        "All": None, # no filter — full history from first snapshot
    }
    timeframe_label = st.radio(
        "Timeframe", list(TIMEFRAMES.keys()),
        index=2,            # default to 1M
        horizontal=True,
        key="tracker_timeframe"
    )
    timeframe_days = TIMEFRAMES[timeframe_label]

# ── Render chart ──────────────────────────────────────────────────────────────
if not st.session_state["watchlist"]:
    ## Jun 21 2026: descriptive empty state — tells user exactly what to do and when data updates
    st.info("📌 No contracts pinned yet.\n\nSelect an expiry, type, and strike above then click ➕ Add to Watchlist. Data updates at 9:35 AM and 4:15 PM on weekdays.")
    st.stop()

if chart_type == "Candlestick":
    if len(st.session_state["watchlist"]) > 1:
        st.warning("Candlestick shows one contract at a time. Displaying first pinned contract.")
    render_candlestick(st.session_state["watchlist"][0], timeframe_days=timeframe_days)
else:
    fig    = go.Figure()
    colors = ["#388bfd","#f0c040","#2ea043","#f85149","#bc8cff","#79c0ff"]  ## color cycle for multiple contracts

    for i, symbol in enumerate(st.session_state["watchlist"]):
        color = colors[i % len(colors)]  ## cycle through colors for each contract

        if overlay in ("Delta", "Theta", "Gamma"):
            ## Jul 2026: unified Greek chart — Delta, Theta, Gamma all use the same single-axis pattern
            ## Only the DB column name, y-axis label, and line color differ between them
            ## This avoids duplicating nearly identical code three times

            ## Map overlay label → DB column name → line color
            ## col_map: which column in bronze_options_raw to pull for this Greek
            col_map   = {"Delta": "delta",   "Theta": "theta",   "Gamma": "gamma"}
            ## color_map: fixed color per Greek so user can identify them by color even across contracts
            ## Blue = Delta (directional), Red = Theta (decay/negative connotation), Green = Gamma (explosive)
            color_map = {"Delta": "#388bfd", "Theta": "#f85149", "Gamma": "#2ea043"}

            col        = col_map[overlay]    ## e.g. "delta" — the actual column name to query and plot
            line_color = color_map[overlay]  ## e.g. "#388bfd" — fixed color for this Greek

            ## get_contract_history with metric_col=col triggers the daily dedup filter
            ## (one point per day, latest snapshot) — same logic as IV and Delta before
            df = get_contract_history(symbol, metric_col=col)
            if df.empty:   ## no data for this contract yet — skip silently
                continue
            df = df.dropna(subset=[col])  ## drop rows where this Greek is NULL (yfinance sometimes omits them)

            ## Timeframe filter: slice from most recent snapshot backwards by timeframe_days
            if timeframe_days is not None:
                cutoff = pandas.to_datetime(df["snapshot_time"]).max() - pandas.Timedelta(days=timeframe_days)
                df     = df[pandas.to_datetime(df["snapshot_time"]) >= cutoff]  ## keep only rows after cutoff

            ## Single-axis line chart — all Greeks live on the left y-axis
            ## mode="lines+markers" = connected line with a dot at each daily data point
            fig.add_trace(go.Scatter(
                x=df["snapshot_time"],     ## x = snapshot timestamp (one per day after dedup)
                y=df[col],                 ## y = Greek value (e.g. delta=-0.15, theta=-0.08, gamma=0.02)
                name=f"{symbol} {overlay}",## legend label e.g. "AAPL260717P00280000 Theta"
                mode="lines+markers",      ## line connects daily points; dots mark each snapshot
                line=dict(color=line_color, width=2),   ## fixed Greek color, 2px wide
                marker=dict(size=5),       ## small dots — visible but not dominating the line
                hovertemplate=f"{symbol}<br>%{{x|%b %d %H:%M}}<br>{overlay}: %{{y:.4f}}<extra></extra>",
                ## hovertemplate: on hover shows contract symbol, date+time, Greek name and value
                ## %{{...}} = Plotly format string (double braces escape the f-string outer braces)
                ## :.4f = 4 decimal places (Greeks are small numbers like -0.0842)
            ))

            ## x-axis bounds: start at earliest data, end 30 days past last snapshot
            x_start = pandas.to_datetime(df["snapshot_time"]).min()                               ## left edge of chart
            x_end   = pandas.to_datetime(df["snapshot_time"]).max() + pandas.Timedelta(days=30)   ## right padding

            fig.update_layout(
                ## y-axis label matches selected Greek name so axis is self-describing
                ## zeroline=True draws a horizontal line at y=0 — important for Theta (always negative)
                ## and Delta (crosses 0 when option flips ITM/OTM)
                yaxis=dict(title=overlay, gridcolor="#21262d", color="#8b949e", zeroline=True, zerolinecolor="#30363d"),
            )

        else:
            ## Jun 25 2026: Price + IV dual-axis mode
            ## Price (left y-axis, blue) + IV (right y-axis, yellow dotted)
            ## Lets you see IV crush and price reaction together — most important options relationship

            ## Price — all market-hours snapshots so AM + PM both show (intraday moves visible)
            df_price = get_contract_history(symbol, metric_col="lastPrice")
            if df_price.empty:
                continue
            df_price = df_price.dropna(subset=["lastPrice"])

            ## IV — one snapshot per day (latest only) so no zigzag from multiple daily runs
            df_iv = get_contract_history(symbol, metric_col="impliedVolatility")
            if df_iv.empty:
                continue
            df_iv = df_iv.dropna(subset=["impliedVolatility"])

            ## Apply timeframe filter to both dataframes independently
            if timeframe_days is not None:
                cutoff_p = pandas.to_datetime(df_price["snapshot_time"]).max() - pandas.Timedelta(days=timeframe_days)
                df_price = df_price[pandas.to_datetime(df_price["snapshot_time"]) >= cutoff_p]
                cutoff_i = pandas.to_datetime(df_iv["snapshot_time"]).max() - pandas.Timedelta(days=timeframe_days)
                df_iv    = df_iv[pandas.to_datetime(df_iv["snapshot_time"]) >= cutoff_i]

            ## Price trace — left y-axis (yaxis="y1"), solid line
            fig.add_trace(go.Scatter(
                x=df_price["snapshot_time"],   ## x = snapshot timestamp
                y=df_price["lastPrice"],        ## y = option last price in dollars
                name=f"{symbol} Price",         ## legend label
                mode="lines+markers",           ## line + dots at each snapshot
                line=dict(color=color, width=2),
                marker=dict(size=5),
                yaxis="y1",                     ## bind to left y-axis
                hovertemplate=f"{symbol}<br>%{{x|%b %d %H:%M}}<br>Price: $%{{y:.2f}}<extra></extra>",
            ))

            ## IV trace — right y-axis (yaxis="y2"), dotted yellow line
            ## Dotted so it's visually distinct from price even without looking at legend
            ## Multiplied by 100 to convert decimal (0.27) to percentage (27%)
            fig.add_trace(go.Scatter(
                x=df_iv["snapshot_time"],              ## x = snapshot timestamp
                y=df_iv["impliedVolatility"] * 100,    ## y = IV as percentage
                name=f"{symbol} IV %",                 ## legend label
                mode="lines+markers",
                line=dict(color="#f0c040", width=2, dash="dot"),  ## yellow dotted — matches IV theme throughout dashboard
                marker=dict(size=5),
                yaxis="y2",                            ## bind to RIGHT y-axis
                hovertemplate=f"{symbol}<br>%{{x|%b %d %H:%M}}<br>IV: %{{y:.1f}}%<extra></extra>",
            ))

            ## ── Contract high/low reference lines ────────────────────────────
            ## fetch lifetime high and low for this contract
            hl = get_contract_highlow(symbol)

            if hl["contract_high"] is not None:
                ## green dotted line at lifetime high — shows peak price this contract reached
                fig.add_hline(
                    y=hl["contract_high"],                                   ## y position = lifetime high price
                    line_dash="dot",                                         ## dotted so it doesn't overpower price line
                    line_color="#2ea043",                                    ## green = high
                    line_width=1,                                            ## thin line — reference only
                    annotation_text=f"High ${hl['contract_high']:.2f}",     ## label showing exact value
                    annotation_position="right",                             ## label on the right edge
                    annotation_font_color="#2ea043",                         ## green label matches line color
                )

            if hl["contract_low"] is not None:
                ## red dotted line at lifetime low — shows floor the contract hit
                fig.add_hline(
                    y=hl["contract_low"],                                    ## y position = lifetime low price
                    line_dash="dot",                                         ## dotted
                    line_color="#f85149",                                    ## red = low
                    line_width=1,                                            ## thin line
                    annotation_text=f"Low ${hl['contract_low']:.2f}",       ## label showing exact value
                    annotation_position="right",                             ## label on the right edge
                    annotation_font_color="#f85149",                         ## red label matches line color
                )

            ## ── Today's OHLC reference lines ──────────────────────────────────────
            ## Jul 2026: add today's Open/High/Low/Close as horizontal dashed lines
            ## dash="dash" visually distinguishes these from contract high/low (dash="dot")
            ## Loop avoids repeating nearly-identical add_hline calls for each level
            ohlc = get_today_ohlc(symbol)   ## fetch today's synthesised OHLC for this contract
            if ohlc:                         ## guard: None if no data yet today
                for level_val, line_color, annotation_label in [
                    ## tuple: (price level, line color, annotation text)
                    (ohlc["open"],  "#8b949e", f"Today O ${ohlc['open']:.2f}"),   ## gray  = open (neutral)
                    (ohlc["high"],  "#2ea043", f"Today H ${ohlc['high']:.2f}"),   ## green = high
                    (ohlc["low"],   "#f85149", f"Today L ${ohlc['low']:.2f}"),    ## red   = low
                    (ohlc["close"], "#f0c040", f"Today C ${ohlc['close']:.2f}"),  ## yellow= close (matches IV theme)
                ]:
                    fig.add_hline(
                        y=level_val,                          ## horizontal line at this price
                        line_dash="dash",                     ## long dashes — distinct from contract H/L dots
                        line_color=line_color,                ## color from tuple above
                        line_width=1,                         ## thin — reference only, not a data trace
                        annotation_text=annotation_label,     ## e.g. "Today O $2.45" — label on right edge
                        annotation_position="right",          ## right edge so it doesn't obscure the price line
                        annotation_font_color=line_color,     ## label color matches line color
                    )

            ## x-axis range — cap 30 days past last data point
            x_start = pandas.to_datetime(df_price["snapshot_time"]).min()
            x_end   = pandas.to_datetime(df_price["snapshot_time"]).max() + pandas.Timedelta(days=30)

            fig.update_layout(
                ## Left y-axis — Price
                yaxis=dict(title="Price ($)", gridcolor="#21262d", color="#8b949e", zeroline=False),
                ## Right y-axis — IV %
                ## overlaying="y" places it on the same chart area as the left axis
                ## side="right" pins it to the right edge
                ## showgrid=False prevents a second grid from overlapping the left grid
                yaxis2=dict(
                    title="IV %", overlaying="y", side="right",
                    color="#f0c040",   ## yellow to match IV line color
                    showgrid=False,    ## no second grid — would overlap left axis grid
                    zeroline=False,
                ),
            )

    ## Shared layout applied regardless of Price+IV or Delta mode
    fig.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="#e0e0e0", height=400,
        margin=dict(t=20, b=40, l=60, r=20),
        xaxis=dict(title="Snapshot Time", gridcolor="#21262d", color="#8b949e", range=[x_start, x_end]),
        legend=dict(bgcolor="#161b22", bordercolor="#30363d", borderwidth=1),
        hovermode="x unified",
    )

    for event_name, event_date in CATALYST_EVENTS.items():
        fig.add_vline(x=event_date, line_width=1, line_dash="dot", line_color="#bc8cff")
        fig.add_annotation(x=event_date, y=1, yref="paper", text=event_name, showarrow=False,
            font=dict(color="#bc8cff", size=11), bgcolor="#0e1117", bordercolor="#bc8cff",
            borderwidth=1, xanchor="left", yanchor="top")

    st.plotly_chart(fig, use_container_width=True)
    ## caption shows which overlay is active + how many contracts are on the chart
    st.caption(f"Data from Bronze layer · {len(st.session_state['watchlist'])} contract(s) tracked · Overlay: {overlay if chart_type == 'Line' else 'Candlestick'}")

## OI & Volume charts — always shown below main chart regardless of metric/chart type selected
## Jun 18 2026: added to track positioning signals around catalyst events
st.divider()
st.subheader("📊 OI & Volume")
render_oi_volume(st.session_state["watchlist"][0], timeframe_days=timeframe_days)

# ── Auto-refresh ──────────────────────────────────────────────────────────────
import time
if refresh_secs:
    time.sleep(refresh_secs)
    st.rerun()
