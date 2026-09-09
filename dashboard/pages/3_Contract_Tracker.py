"""
Page 3 — Contract Tracker
AAPL & INTC Catalyst Intelligence Dashboard
Session 3 (Jun 2026): Goal 6 — watchlist, line chart, candlestick with OI bars
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb                               ## Sep 2026: read-write connection for manual H/L overrides
import json                                ## built-in Python library for reading/writing JSON files
import time                                ## Sep 2026: moved to top — used in write_manual_hl() retry loop
import pandas                              ## data manipulation
import plotly.graph_objects as go         ## plotly charts
import streamlit as st                    ## dashboard framework
from plotly.subplots import make_subplots ## multi-row chart layouts

from utils import CATALYST_EVENTS, DARK_THEME_CSS, bull_color, bear_color, format_expiry, query, render_sidebar, render_page_header, DB_PATH  ## Sep 2026: added DB_PATH for manual H/L write connection

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

def write_manual_hl(symbol: str, date: str, high: float, low: float) -> tuple[bool, str]:
    ## Write user-entered H/L to manual_ohlc_overrides table
    ## Uses a short-lived read-write connection — held for milliseconds then released
    ## Retries 3 times with 2s gap to survive the pipeline's ~30s write window at 9:35 AM / 4:15 PM
    ## Returns (True, "") on success or (False, error_message) on failure for caller to display
    last_error = ""                                       ## capture real exception message for diagnosis
    for attempt in range(3):                              ## 3 attempts = 6 seconds max wait
        try:
            con = duckdb.connect(str(DB_PATH))            ## read-write — no read_only flag
            con.execute("""
                CREATE TABLE IF NOT EXISTS manual_ohlc_overrides (
                    symbol  VARCHAR,                      -- contract symbol e.g. AAPL260918C00220000
                    date    DATE,                         -- trading date of the override
                    high    DOUBLE,                       -- user-entered intraday high
                    low     DOUBLE,                       -- user-entered intraday low
                    PRIMARY KEY (symbol, date)            -- one override row per contract per day
                )
            """)
            con.execute("""
                INSERT INTO manual_ohlc_overrides VALUES (?, ?, ?, ?)
                ON CONFLICT (symbol, date) DO UPDATE SET
                    high = CASE WHEN excluded.high > 0   -- only overwrite high if user entered a value (> 0)
                                THEN excluded.high        -- use the new value
                                ELSE manual_ohlc_overrides.high  -- keep existing value if field was left blank
                           END,
                    low  = CASE WHEN excluded.low > 0    -- same logic for low
                                THEN excluded.low
                                ELSE manual_ohlc_overrides.low
                           END
            """, [symbol, date, high, low])
            con.close()                                   ## release write lock immediately
            return True, ""                               ## success
        except Exception as e:
            last_error = str(e)                           ## capture real error — not swallowed
            try:
                con.close()                               ## always release — even if write failed mid-way
            except Exception:
                pass                                      ## con may not have opened — safe to ignore
            time.sleep(2)                                 ## wait 2s before next attempt
    return False, last_error                              ## all 3 attempts failed — return real error to caller

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
    ## Sep 2026: wrapped in try/except — Docker volume may be read-only or disk full;
    ## without this the write fails silently and watchlist is lost on container restart
    try:
        with open(WATCHLIST_FILE, "w") as f:     ## open file in write mode (creates if missing)
            json.dump(data, f, indent=2)         ## json.dump converts dict to JSON text, indent=2 = human readable
    except Exception as e:
        st.warning(f"Could not save watchlist to disk: {e} — watchlist will reset on restart.")

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
                AND HOUR(b2.snapshot_time) BETWEEN 9 AND 23          -- market hours only (UTC: 9:35 AM EST = 13 UTC, 4:15 PM EST = 21 UTC)
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
        AND HOUR(snapshot_time) BETWEEN 9 AND 23

        -- Sep 2026: exclude pre-market garbage snapshots from Mac LaunchAgent era
        -- Hours 9-12 UTC = 5-8 AM EST — market closed, IV near zero, corrupts chart
        AND impliedVolatility > 0.05

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
        AND HOUR(snapshot_time) BETWEEN 9 AND 23
    """, [symbol])
    if df.empty:                              ## no data yet — return None so chart skips the lines
        return {"contract_high": None, "contract_low": None}
    return df.iloc[0].to_dict()              ## return as dict e.g. {"contract_high": 8.20, "contract_low": 0.50}

@st.cache_data(ttl=60)  ## cache 60s — history only changes when pipeline runs or user saves H/L
def get_ohlc_history(symbol: str) -> pandas.DataFrame:
    ## Build full OHLC history for this contract across all trading days
    ## Open/Close from Bronze AM/PM snapshots — H/L from manual_ohlc_overrides
    ## Overnight gap and session return computed via LAG() on prev day's close
    ## symbol passed twice — once for the WHERE filter, once for the LEFT JOIN condition
    return query(
        """
        WITH daily AS (
            -- Step 1: collapse 2 Bronze rows per day into 1 row with open + close columns
            SELECT
                DATE(snapshot_time)                              AS date,
                MAX(CASE WHEN HOUR(snapshot_time) < 17
                    THEN lastPrice END)                          AS open,   -- 9:35 AM EST = hour 13 UTC
                MAX(CASE WHEN HOUR(snapshot_time) >= 17
                    THEN lastPrice END)                          AS close   -- 4:15 PM EST = hour 21 UTC
            FROM bronze_options_raw
            WHERE contractSymbol = ?
              AND lastPrice > 0
              AND impliedVolatility > 0.01
              AND HOUR(snapshot_time) BETWEEN 9 AND 23
            GROUP BY DATE(snapshot_time)
        ),
        with_prev AS (
            -- Step 2: add prev_close by looking at the previous row's close via LAG()
            SELECT
                date,
                open,
                close,
                LAG(close) OVER (ORDER BY date)                  AS prev_close
            FROM daily
        )
        -- Step 3: attach manual H/L and compute overnight gap + session return
        SELECT
            w.date                                               AS Date,
            w.prev_close                                         AS "Prev Close",
            w.open                                               AS Open,
            m.high                                               AS High,
            m.low                                                AS Low,
            w.close                                              AS Close,
            w.open  - w.prev_close                              AS "Overnight Gap",
            w.close - w.prev_close                              AS "Session Return"
        FROM with_prev w
        LEFT JOIN manual_ohlc_overrides m                        -- LEFT JOIN keeps days with no manual H/L
            ON m.symbol = ? AND m.date = w.date
        ORDER BY w.date DESC                                     -- most recent day first
        """, [symbol, symbol]
    )

@st.cache_data(ttl=60)  ## cache 60s — prev close only changes when pipeline runs (9:35 AM / 4:15 PM)
def get_prev_close(symbol: str) -> float | None:
    ## Fetch yesterday's 4:15 PM snapshot price — the market's last settled price before today
    ## This is the reference anchor for overnight gap (Open − Prev Close) and session return (Close − Prev Close)
    ## "Yesterday" = the most recent trading day before today — skips weekends and holidays automatically
    ## because we only have snapshots on days the pipeline ran (market days only)
    df = query(
        """
        SELECT lastPrice
        FROM bronze_options_raw
        WHERE contractSymbol = ?
          AND lastPrice > 0                        -- exclude zero prints
          AND HOUR(snapshot_time) >= 17            -- PM snapshot only (4:15 PM EST = 21:15 UTC, hour >= 17 covers it)
          AND DATE(snapshot_time) < CURRENT_DATE   -- strictly before today — excludes today's AM/PM snapshots
        ORDER BY snapshot_time DESC                -- most recent first
        LIMIT 1                                    -- only the single most recent prior PM snapshot
        """, [symbol]
    )
    if df.empty:                                   ## no prior PM snapshot — first day of data
        return None
    return float(df.iloc[0]["lastPrice"])          ## return as plain float for arithmetic in metric cards

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
        AND HOUR(snapshot_time) BETWEEN 9 AND 23
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
    morning     = df[df["hour"] < 17].groupby("trade_date")["lastPrice"].first()   ## Aug 2026: split at 17 UTC — 9:35 AM EST = 13 UTC (morning), 4:15 PM EST = 21 UTC (afternoon)
    afternoon   = df[df["hour"] >= 17].groupby("trade_date")["lastPrice"].last()  ## was < 12 / >= 12 which assumed EST timestamps; droplet runs UTC so both snapshots fell into afternoon
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
## Sep 2026: 5-card layout — Prev Close as primary reference anchor
## Prev Close = yesterday's PM snapshot — baseline for overnight gap and session return
## High/Low = manual entry only (from ✏️ form below) — show "—" until user enters them
if st.session_state["watchlist"]:
    ohlc_today = get_today_ohlc(st.session_state["watchlist"][0])  ## pull OHLC for first pinned contract
    prev_close = get_prev_close(st.session_state["watchlist"][0])  ## yesterday's PM snapshot price — our reference anchor
    if ohlc_today:
        st.caption(
            f"📅 {ohlc_today['date']} · Open = 9:35 AM snapshot · Close = 4:15 PM snapshot"
        )
        c1, c2, c3, c4, c5 = st.columns(5)  ## 5 equal cards — one per OHLC field + Prev Close

        ## ── 1. PREV CLOSE — Reference point ──────────────────────────────────
        ## Yesterday's 4:15 PM snapshot — the market's last agreed price before today
        ## No delta shown — this IS the baseline everything else compares against
        ## If None (first day of data), show "—" so card still renders cleanly
        c1.metric(
            "Prev Close",
            f"${prev_close:.2f}" if prev_close else "—"
        )

        ## ── 2. OPEN — Overnight gap ───────────────────────────────────────────
        ## Today's 9:35 AM snapshot — first price we captured after market opened
        ## Delta = Open − Prev Close = how much the contract moved while market was closed
        ## Positive gap = opened higher than yesterday (bullish overnight news/sentiment)
        ## Negative gap = opened lower (bearish overnight — earnings, macro, etc.)
        ## delta_color="normal" = green when positive (gapped up = favorable for long calls)
        if prev_close is not None and ohlc_today["open"] is not None:
            c2.metric(
                "Open",
                f"${ohlc_today['open']:.2f}",
                delta=f"{ohlc_today['open'] - prev_close:+.2f} overnight gap",
                delta_color="normal"   ## green = gapped up, red = gapped down
            )
        else:
            c2.metric("Open", f"${ohlc_today['open']:.2f}" if ohlc_today["open"] is not None else "—")  ## guard: None if no AM snapshot yet today

        ## ── 3. HIGH — Max favorable excursion from open ──────────────────────
        ## Entered manually via ✏️ form — shows "—" until user enters today's high from broker
        ## Delta = High − Open = how far above open the contract ran at its peak
        ## delta_color="normal" = green because higher than open is favorable for longs
        if ohlc_today["open"] is not None and ohlc_today["high"] is not None:
            c3.metric(
                "High",
                f"${ohlc_today['high']:.2f}",
                delta=f"+${ohlc_today['high'] - ohlc_today['open']:.2f} from open",
                delta_color="normal"   ## green = ran above open
            )
        else:
            c3.metric("High", "—")    ## no manual entry yet — prompt user to use ✏️ form below

        ## ── 4. LOW — Max adverse excursion from open ─────────────────────────
        ## Entered manually via ✏️ form — shows "—" until user enters today's low from broker
        ## Delta = Open − Low = how far below open the contract fell at its worst
        ## delta_color="inverse" = red because lower than open is adverse for longs
        if ohlc_today["open"] is not None and ohlc_today["low"] is not None:
            c4.metric(
                "Low",
                f"${ohlc_today['low']:.2f}",
                delta=f"-${ohlc_today['open'] - ohlc_today['low']:.2f} from open",
                delta_color="inverse"  ## inverse: red means lower than open (expected for Low)
            )
        else:
            c4.metric("Low", "—")     ## no manual entry yet — prompt user to use ✏️ form below

        ## ── 5. CLOSE — Complete session-to-session return ────────────────────
        ## Today's 4:15 PM snapshot — final price of the trading day
        ## Delta = Close − Prev Close = net move from yesterday's close to today's close
        ## This is the number that shows on your broker watchlist as today's P&L
        ## delta_color="normal" = green when positive (gained value vs yesterday)
        if prev_close is not None and ohlc_today["close"] is not None:
            c5.metric(
                "Close",
                f"${ohlc_today['close']:.2f}",
                delta=f"{ohlc_today['close'] - prev_close:+.2f} session return",
                delta_color="normal"   ## green = closed above yesterday, red = closed below
            )
        else:
            c5.metric("Close", f"${ohlc_today['close']:.2f}" if ohlc_today["close"] is not None else "—")  ## guard: None if no PM snapshot yet today

# ── Manual H/L entry form ────────────────────────────────────────────────────
## Only shown when a contract is pinned AND we have today's OHLC data to anchor the date
if st.session_state["watchlist"] and ohlc_today:
    with st.expander("✏️ Correct Today's H/L"):
        st.caption(
            "Pipeline captures 2 snapshots/day — 9:35 AM open and 4:15 PM close. "
            "Enter the true intraday High and Low from your broker."
        )

        ## Pre-fill inputs with any override already saved for today
        ## ohlc_today["high"/"low"] are None if no override exists yet
        existing_high = float(ohlc_today["high"]) if ohlc_today["high"] is not None else 0.0  ## cast numpy float32 → Python float — Streamlit requires all numeric args same type
        existing_low  = float(ohlc_today["low"])  if ohlc_today["low"]  is not None else 0.0

        with st.form("manual_hl_form"):                  ## st.form batches all inputs — only fires on button click, not on every keystroke
            col_h, col_l = st.columns(2)                 ## side-by-side — compact, mirrors the card layout above

            with col_h:
                high_val = st.number_input(
                    "Today's High ($)",
                    min_value=0.01,                      ## options can't be zero or negative
                    value=existing_high if existing_high > 0 else None,  ## pre-fill if already saved
                    format="%.2f",                       ## 2 decimal places — matches option price display
                    placeholder="e.g. 4.80",
                )
            with col_l:
                low_val = st.number_input(
                    "Today's Low ($)",
                    min_value=0.01,
                    value=existing_low if existing_low > 0 else None,
                    format="%.2f",
                    placeholder="e.g. 2.10",
                )

            submitted = st.form_submit_button("💾 Save H/L")

        if submitted:
            symbol_0  = st.session_state["watchlist"][0]  ## always saves for first pinned contract
            today_str = ohlc_today["date"]                 ## e.g. "2026-09-08" — anchors the row to today

            if high_val and low_val and high_val < low_val:   ## basic sanity check
                st.error("High must be ≥ Low.")
            elif high_val or low_val:                          ## at least one field filled
                success, err = write_manual_hl(
                    symbol_0, today_str,
                    high_val or 0.0,                      ## send 0.0 if only one field filled
                    low_val  or 0.0,
                )
                if success:
                    st.success(f"Saved — High: ${high_val:.2f} · Low: ${low_val:.2f}")
                    st.cache_data.clear()                 ## force OHLC cards to re-query with new values
                    st.rerun()                            ## refresh page so cards update immediately
                else:
                    st.error(f"Write failed: {err}")      ## show real DuckDB error for diagnosis
            else:
                st.warning("Enter at least one value.")

# ── OHLC History table ───────────────────────────────────────────────────────
if st.session_state["watchlist"]:
    symbol_0 = st.session_state["watchlist"][0]   ## first pinned contract
    history  = get_ohlc_history(symbol_0)          ## fetch full history
    if not history.empty:
        st.subheader("📋 OHLC History")
        st.caption(f"{symbol_0} · Open/Close from snapshots · H/L from manual entry · most recent first")
        st.dataframe(
            history.style.format({
                "Prev Close":     lambda x: f"${x:.2f}" if pandas.notna(x) else "—",
                "Open":           lambda x: f"${x:.2f}" if pandas.notna(x) else "—",
                "High":           lambda x: f"${x:.2f}" if pandas.notna(x) else "—",
                "Low":            lambda x: f"${x:.2f}" if pandas.notna(x) else "—",
                "Close":          lambda x: f"${x:.2f}" if pandas.notna(x) else "—",
                "Overnight Gap":  lambda x: f"{x:+.2f}" if pandas.notna(x) else "—",
                "Session Return": lambda x: f"{x:+.2f}" if pandas.notna(x) else "—",
            }),
            use_container_width=True,
            hide_index=True,
        )

# ── Chart type + metric + timeframe ───────────────────────────────────────────
ctrl_a, ctrl_b, ctrl_c = st.columns([2, 2, 2])

with ctrl_a:
    chart_type = st.radio("Chart type", ["Line", "Candlestick"], horizontal=True, key="tracker_chart_type")

with ctrl_b:
    pass  ## Aug 2026: overlay radio removed — 2x2 grid shows all metrics simultaneously

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
    ## Aug 2026: replaced single chart + overlay radio with 2×2 small multiples grid
    ## Each panel shows one metric — Price, IV, Delta, Theta — all step charts
    ## shared_xaxes=True: pan/zoom on any panel moves all four in sync
    fig    = make_subplots(
        rows=2, cols=2,
        shared_xaxes=True,
        subplot_titles=["Price ($)", "IV %", "Δ Delta", "Θ Theta"],
        vertical_spacing=0.14,
        horizontal_spacing=0.10,
    )
    colors = ["#388bfd","#f0c040","#2ea043","#f85149","#bc8cff","#79c0ff"]  ## color cycle for multiple contracts

    ## Panel definitions — one dict per cell in the 2×2 grid
    ## col_name: DB column to fetch | mult: multiplier (IV ×100 converts 0.27 → 27%) | fmt: hover decimal format
    panels = [
        {"row": 1, "col": 1, "col_name": "lastPrice",        "label": "Price", "unit": "$",  "mult": 1,   "fmt": ".2f"},
        {"row": 1, "col": 2, "col_name": "impliedVolatility", "label": "IV",    "unit": "%",  "mult": 100, "fmt": ".1f"},
        {"row": 2, "col": 1, "col_name": "delta",             "label": "Delta", "unit": "",   "mult": 1,   "fmt": ".4f"},
        {"row": 2, "col": 2, "col_name": "theta",             "label": "Theta", "unit": "",   "mult": 1,   "fmt": ".4f"},
    ]

    x_start, x_end = None, None  ## track x-axis bounds across all panels — filled during loop

    for i, symbol in enumerate(st.session_state["watchlist"]):
        color = colors[i % len(colors)]  ## cycle through colors for each contract

        for panel in panels:
            df = get_contract_history(symbol, metric_col=panel["col_name"])  ## dedup logic inside get_contract_history
            if df.empty:                                                       ## no data for this contract+metric
                continue
            df = df.dropna(subset=[panel["col_name"]])  ## drop NULLs — yfinance sometimes omits Greeks

            ## Timeframe filter — slice from most recent snapshot backwards by timeframe_days
            if timeframe_days is not None:
                cutoff = pandas.to_datetime(df["snapshot_time"]).max() - pandas.Timedelta(days=timeframe_days)
                df     = df[pandas.to_datetime(df["snapshot_time"]) >= cutoff]

            if df.empty:  ## guard: all data may be outside the selected timeframe window
                continue

            y_vals = df[panel["col_name"]] * panel["mult"]  ## apply multiplier — IV: 0.27 × 100 = 27

            ## Expand x-axis bounds to cover all panels and all contracts
            ts = pandas.to_datetime(df["snapshot_time"])
            if x_start is None:               ## first panel with data — initialize bounds
                x_start = ts.min()
                x_end   = ts.max() + pandas.Timedelta(days=5)   ## Sep 2026: reduced from 30 to 5 — 30 days of empty space compressed all data into left third of chart
            else:                             ## subsequent panels — expand if data goes further
                x_start = min(x_start, ts.min())
                x_end   = max(x_end, ts.max() + pandas.Timedelta(days=30))

            ## showlegend only on top-left panel — prevents 4× duplicate legend entries per contract
            show_leg = (panel["row"] == 1 and panel["col"] == 1)

            fig.add_trace(go.Scatter(
                x=df["snapshot_time"],   ## x = snapshot timestamp
                y=y_vals,                ## y = metric value (multiplier already applied)
                name=symbol,             ## one legend entry per contract, not per panel
                mode="lines+markers",
                line=dict(color=color, width=2, shape="hv"),  ## step chart — honest about discrete AM/PM snapshots
                marker=dict(size=6),     ## slightly smaller than single-chart (6 vs 8) — panels are smaller
                showlegend=show_leg,
                hovertemplate=f"{panel['label']}: %{{y:{panel['fmt']}}}{panel['unit']}<extra>{symbol}</extra>",
            ), row=panel["row"], col=panel["col"])  ## place trace in correct grid cell

        ## Catalyst vlines — draw on all 4 panels so events are visible in every metric
        for event_name, event_date in CATALYST_EVENTS.items():
            for panel in panels:
                fig.add_vline(
                    x=event_date, line_width=1, line_dash="dot", line_color="#bc8cff",
                    row=panel["row"], col=panel["col"]
                )

    ## Shared layout across all 4 panels
    fig.update_layout(
        paper_bgcolor="#0e1117", plot_bgcolor="#0e1117", font_color="#e0e0e0",
        height=550,                ## taller than single chart (was 400) — 2 rows need more space
        margin=dict(t=40, b=40, l=60, r=20),
        legend=dict(bgcolor="#161b22", bordercolor="#30363d", borderwidth=1),
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor="#21262d", color="#8b949e")
    fig.update_yaxes(gridcolor="#21262d", color="#8b949e")

    if x_start is not None and x_end is not None:  ## Sep 2026: explicit None check — Timestamp is truthy but intent is clearer this way
        fig.update_xaxes(range=[x_start, x_end])

    st.plotly_chart(fig, use_container_width=True)
    st.caption(f"Data from Bronze layer · {len(st.session_state['watchlist'])} contract(s) · Step chart — dots = actual snapshots")

## OI & Volume charts — always shown below main chart regardless of metric/chart type selected
## Jun 18 2026: added to track positioning signals around catalyst events
st.divider()
st.subheader("📊 OI & Volume")
render_oi_volume(st.session_state["watchlist"][0], timeframe_days=timeframe_days)

# ── Auto-refresh ──────────────────────────────────────────────────────────────
if refresh_secs:
    time.sleep(refresh_secs)
    st.rerun()
