# ──────────────────────────────────────────────────────────────────────────────
# pipeline_utils.py
# Shared constants and helpers used by all pipeline scripts.
# Extracted Sep 2026 to avoid duplication between collect_market_snapshots.py
# and collect_chain_snapshot.py
# ──────────────────────────────────────────────────────────────────────────────
import logging                              ## stdlib — structured log output
import zoneinfo                             ## stdlib (Python 3.9+) — timezone-aware datetimes
from datetime import datetime, date         ## stdlib — date comparisons for holiday + weekend checks

import pandas as pd                         ## DataFrame metadata tagging
import yfinance as yf                       ## market data source

# ── Constants ─────────────────────────────────────────────────────────────────

TICKERS = ["AAPL", "INTC"]                 ## tickers tracked across all pipeline scripts

## US market holidays — extend each December for the following year
## Both collect_market_snapshots.py and collect_chain_snapshot.py use this set
MARKET_HOLIDAYS = {
    ## 2026
    date(2026, 1, 1),   ## New Year's Day
    date(2026, 1, 19),  ## MLK Day
    date(2026, 2, 16),  ## Presidents Day
    date(2026, 4, 3),   ## Good Friday
    date(2026, 5, 25),  ## Memorial Day
    date(2026, 7, 3),   ## Independence Day (observed)
    date(2026, 9, 7),   ## Labor Day
    date(2026, 11, 26), ## Thanksgiving
    date(2026, 11, 27), ## Day after Thanksgiving (early close — skip for safety)
    date(2026, 12, 25), ## Christmas
    ## 2027
    date(2027, 1, 1),   ## New Year's Day
    date(2027, 1, 18),  ## MLK Day
    date(2027, 2, 15),  ## Presidents Day
    date(2027, 3, 26),  ## Good Friday
    date(2027, 5, 31),  ## Memorial Day
    date(2027, 7, 5),   ## Independence Day (observed)
    date(2027, 9, 6),   ## Labor Day
    date(2027, 11, 25), ## Thanksgiving
    date(2027, 11, 26), ## Day after Thanksgiving
    date(2027, 12, 24), ## Christmas (observed)
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def is_market_open() -> bool:
    ## Returns True only on weekdays that are not US market holidays
    ## Uses America/New_York explicitly — droplet runs UTC so datetime.now()
    ## without tz would return UTC and break weekend/holiday checks near midnight
    now   = datetime.now(tz=zoneinfo.ZoneInfo("America/New_York"))  ## current EST/EDT time
    today = now.date()                      ## date portion only — for holiday set lookup
    if today in MARKET_HOLIDAYS:            ## holiday check — set lookup is O(1)
        return False
    return now.weekday() < 5               ## 0=Mon … 4=Fri → open; 5=Sat, 6=Sun → closed


def setup_logger(name: str) -> logging.Logger:
    ## Create and return a named logger with a consistent format
    ## name: caller passes __name__ or a descriptive string e.g. "pipeline", "ChainCollector"
    ## Reusing the same name returns the same logger object — Python logging is global by name
    logger = logging.getLogger(name)       ## get existing logger or create new one by name
    if not logger.handlers:                ## guard: only add handler if none exist yet
                                           ## prevents duplicate log lines on hot reload or double-call
        handler   = logging.StreamHandler()                                         ## print logs to stdout
        formatter = logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")
                                           ## asctime = timestamp | name = logger name | levelname = INFO/ERROR | message = log text
        handler.setFormatter(formatter)    ## attach the format string to this handler
        logger.addHandler(handler)         ## attach the handler to the logger
        logger.setLevel(logging.INFO)      ## capture INFO, WARNING, ERROR, CRITICAL — skip DEBUG
    return logger                          ## return configured logger to the caller


def add_metadata(
    df:            pd.DataFrame,   ## the DataFrame to tag — caller passes options or price df
    snapshot_time: datetime,       ## exact datetime this snapshot was taken — from collector.__init__
    ticker:        str             ## underlying ticker e.g. "AAPL" or "INTC"
) -> pd.DataFrame:
    ## Tag every row with snapshot timestamp and ticker for downstream DB joins
    ## Called after every fetch — Silver and Gold queries filter by ticker and snapshot_time
    ## df.copy() — avoids mutating the caller's original DataFrame (defensive copy)
    df = df.copy()                              ## work on a copy — never mutate the input
    df["snapshot_time"] = snapshot_time        ## datetime column — used for HOUR() filters in SQL
    df["snapshot_str"]  = snapshot_time.strftime("%Y%m%d_%H%M%S")  ## string version — used in CSV filenames
    df["ticker"]        = ticker               ## which underlying this contract belongs to
    return df                                  ## return tagged copy — caller assigns result


def fetch_spot_price(
    asset:  yf.Ticker,          ## yfinance Ticker object already instantiated by the caller
    logger: logging.Logger      ## logger from the caller — keeps log output consistent
) -> float | None:
    ## Fetch the most recent closing price for the underlying stock
    ## Used as spot price input for Black-Scholes Greeks calculation
    ## Returns None on failure — caller should abort options collection if None
    try:
        hist = asset.history(period="1d")    ## fetch last trading day OHLCV from yfinance
        if hist.empty:                        ## empty = holiday, network error, or bad ticker
            logger.error("Spot price fetch returned empty — skipping options collection")
            return None                       ## signal to caller: abort, don't calculate Greeks with no spot
        spot = float(hist["Close"].iloc[-1]) ## most recent close — iloc[-1] = last row
        logger.info(f"Spot price: {spot:.2f}")   ## confirm what price was used
        return spot                           ## return plain float — yfinance sometimes returns numpy float
    except Exception as e:
        logger.error(f"Spot price fetch failed: {e}")  ## log real error for diagnosis
        return None                           ## caller handles None the same way as empty


def fetch_risk_free_rate(logger: logging.Logger) -> float:
    ## Fetch the current 13-week T-bill annualized yield from ^IRX via yfinance
    ## Used as the risk-free rate input for Black-Scholes Greeks calculation
    ## ^IRX returns yield in percent e.g. 4.25 = 4.25% — divide by 100 for decimal
    ## Falls back to 0.043 (4.3%) if fetch fails — approximate rate as of Sep 2026
    try:
        irx = yf.Ticker("^IRX").fast_info["last_price"]  ## annualized T-bill yield in percent
        r   = irx / 100                                   ## convert percent → decimal for Black-Scholes
        logger.info(f"Risk-free rate: {r:.4f} (from ^IRX)")  ## confirm rate used this run
        return r                                          ## return decimal rate to caller
    except Exception:
        logger.warning("^IRX fetch failed — using fallback r=0.043")  ## network issue or bad response
        return 0.043                                      ## fallback: ~4.3% approximate Sep 2026 rate
