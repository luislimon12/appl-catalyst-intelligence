"""
scripts/add_ohlc_override.py
────────────────────────────
Manually enter intraday High / Low for any contract in your watchlist.
Writes directly to DuckDB — dashboard stays 100% read-only.

Usage:
    python scripts/add_ohlc_override.py                      # interactive menu
    python scripts/add_ohlc_override.py AAPL270115C00400000  # pre-select contract
"""

import sys                          ## sys.exit() on bad input
import json                         ## read watchlist.json
from datetime import date, timedelta ## default date = today, walk back by day
from pathlib import Path            ## resolve paths relative to this file
import duckdb                       ## direct read-write DB connection

# ── Paths ─────────────────────────────────────────────────────────────────────
## __file__ = .../appl-catalyst-intelligence/scripts/add_ohlc_override.py
## .parent  = .../scripts/
## .parent.parent = project root = .../appl-catalyst-intelligence/
ROOT           = Path(__file__).parent.parent
DB_PATH        = ROOT / "appl_catalyst.duckdb"          ## main DuckDB file
WATCHLIST_PATH = ROOT / "dashboard" / "watchlist.json"  ## watchlist written by Streamlit

# ── DB helpers ────────────────────────────────────────────────────────────────
def get_connection():
    ## open a standard read-write connection — no read_only=True
    ## safe because the dashboard holds a SEPARATE cached read-only connection
    ## and this script runs in a different process (terminal, not Streamlit)
    return duckdb.connect(str(DB_PATH))

def create_table(con):
    ## idempotent — safe to call every run, does nothing if table already exists
    con.execute("""
        CREATE TABLE IF NOT EXISTS manual_ohlc_overrides (
            symbol     VARCHAR,    -- contract e.g. AAPL270115C00400000
            date       DATE,       -- trading date this correction applies to
            high       DOUBLE,     -- manually entered intraday high
            low        DOUBLE,     -- manually entered intraday low
            updated_at TIMESTAMP   -- when this row was last written
        )
    """)

def upsert(con, symbol: str, trade_date: str, high: float, low: float):
    ## delete any existing row for this symbol+date, then insert fresh
    ## avoids UPSERT syntax differences across DuckDB versions
    con.execute(
        "DELETE FROM manual_ohlc_overrides WHERE symbol = ? AND date = CAST(? AS DATE)",
        [symbol, trade_date]
    )
    con.execute(
        """
        INSERT INTO manual_ohlc_overrides (symbol, date, high, low, updated_at)
        VALUES (?, CAST(? AS DATE), ?, ?, NOW())
        """,
        [symbol, trade_date, high, low]
    )

def show_existing(con, symbol: str):
    ## print all saved overrides for this contract so user can see what's already there
    df = con.execute(
        """
        SELECT date, high, low,
               ROUND(high - low, 2) AS range,  -- daily premium range
               updated_at
        FROM manual_ohlc_overrides
        WHERE symbol = ?
        ORDER BY date DESC
        """,
        [symbol]
    ).df()
    if df.empty:
        print("  (no overrides saved for this contract yet)")
    else:
        print(df.to_string(index=False))

# ── Watchlist helpers ─────────────────────────────────────────────────────────
def load_watchlist() -> list:
    ## reads dashboard/watchlist.json — returns flat list of all contract symbols
    ## across all tickers e.g. ["AAPL270115C00400000", "AAPL260717P00280000"]
    if not WATCHLIST_PATH.exists():
        return []                               ## watchlist file not created yet
    with open(WATCHLIST_PATH, "r") as f:
        data = json.load(f)                     ## {"AAPL": [...], "INTC": [...]}
    ## flatten all tickers into one list
    contracts = []
    for symbols in data.values():               ## iterate over each ticker's list
        contracts.extend(symbols)               ## add all symbols to flat list
    return contracts

def pick_contract(preselect: str = None) -> str:
    ## show watchlist as a numbered menu — user picks by number or types manually
    ## preselect: if passed as CLI arg, skip the menu entirely
    contracts = load_watchlist()

    if preselect:
        ## CLI arg provided — validate it looks like a contract symbol
        print(f"  Contract: {preselect}")
        return preselect.strip().upper()

    if contracts:
        print("\nWatchlist contracts:")
        for i, sym in enumerate(contracts, 1):
            print(f"  {i}. {sym}")              ## e.g. "  1. AAPL270115C00400000"
        print()
        choice = input("Pick a number or type a symbol manually: ").strip()
        if choice.isdigit():
            idx = int(choice) - 1              ## convert "1" → index 0
            if 0 <= idx < len(contracts):
                return contracts[idx]          ## return selected symbol
        return choice.upper()                  ## user typed a symbol manually
    else:
        ## no watchlist yet — ask for symbol directly
        return input("Contract symbol (e.g. AAPL270115C00400000): ").strip().upper()

# ── Input helpers ─────────────────────────────────────────────────────────────
def ask_date(default: str) -> str:
    ## prompt for date — pressing Enter accepts the default (today or previous day)
    val = input(f"Date [{default}] (Enter to confirm): ").strip()
    return val if val else default             ## empty input = keep default

def ask_float(label: str) -> float:
    ## prompt for a price — loops until valid float is entered
    while True:
        raw = input(f"{label}: $").strip()
        try:
            return float(raw)
        except ValueError:
            print(f"  Invalid — enter a number e.g. 4.80")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ## CLI arg: optional contract symbol passed directly
    ## e.g. python scripts/add_ohlc_override.py AAPL270115C00400000
    preselect = sys.argv[1].upper() if len(sys.argv) > 1 else None

    print(f"\n── OHLC Override Tool ───────────────────────────────")
    print(f"   DB: {DB_PATH}")

    con = get_connection()      ## open read-write connection
    create_table(con)           ## ensure table exists before any query

    ## pick contract once per session — user can enter multiple dates for same contract
    symbol = pick_contract(preselect)

    ## show what's already saved for this contract before entering new data
    print(f"\nExisting overrides for {symbol}:")
    show_existing(con, symbol)

    ## loop — user enters one date at a time, saves, then decides whether to continue
    ## default_date walks backwards: today → yesterday → day before → ...
    ## so user can backfill recent history by just pressing Enter each time
    default_date = str(date.today())           ## start at today

    while True:
        print(f"\n── Enter High / Low ─────────────────────────────────")
        trade_date = ask_date(default_date)    ## accept default or type a date

        high = ask_float("High")
        low  = ask_float("Low")

        ## validate before writing
        if high < low:
            print(f"  ERROR: High ({high}) < Low ({low}) — nothing saved. Try again.")
            continue                           ## re-prompt without advancing date

        upsert(con, symbol, trade_date, high, low)
        print(f"  Saved: {symbol} | {trade_date} | H=${high:.2f} | L=${low:.2f} | Range=${high - low:.2f}")

        ## advance default date backwards by one day for the next iteration
        ## so pressing Enter on the next loop gives the previous calendar day
        default_date = str(
            date.fromisoformat(trade_date) - timedelta(days=1)
        )

        ## ask whether to continue
        again = input("\nAdd another date for this contract? (y/n): ").strip().lower()
        if again != "y":
            break

    con.close()                                ## release connection immediately after all writes
    print(f"\nDone. Refresh your dashboard to see updated values.\n")

if __name__ == "__main__":
    main()
