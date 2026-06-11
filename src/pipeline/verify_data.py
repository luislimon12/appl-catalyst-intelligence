#!/opt/anaconda3/bin/python3
# ──────────────────────────────────────────────────────────────────────────────
# verify_data.py
# AAPL & INTC Catalyst Intelligence Pipeline — Data Verification Tool
#
# Session 3 (Jun 2026): Initial build
#
# Purpose: Pull contract data from Bronze and format it for manual cross-checking
#          against your broker (IBKR) or Market Chameleon (free, no account needed).
#
# Usage:
#   python3 verify_data.py                        # shows AAPL summary
#   python3 verify_data.py --ticker INTC           # shows INTC summary
#   python3 verify_data.py --contract AAPL260626C00320000  # single contract detail
#   python3 verify_data.py --iv                   # IV rank cross-check vs Market Chameleon
# ──────────────────────────────────────────────────────────────────────────────

import argparse
import duckdb
from pathlib import Path

# ── Setup ─────────────────────────────────────────────────────────────────────

# Resolve DB path relative to this file — works regardless of where script is called from
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH      = PROJECT_ROOT / "appl_catalyst.duckdb"

con = duckdb.connect(str(DB_PATH), read_only=True)

# ── Helpers ───────────────────────────────────────────────────────────────────

def divider(title: str):
    """Print a section header for readability."""
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")

def fmt_pct(val):
    """Format a decimal as a percentage string."""
    if val is None:
        return "N/A"
    return f"{val * 100:.2f}%"

# ── Verification functions ─────────────────────────────────────────────────────

def verify_iv(ticker: str):
    """
    Print IV rank data for cross-checking against Market Chameleon.
    Go to: https://marketchameleon.com/Overview/{ticker}/IV/
    Compare 'IV Current' and direction (rising/falling) with what MC shows.
    """
    divider(f"IV RANK — {ticker}  |  Cross-check: marketchameleon.com/Overview/{ticker}/IV/")

    row = con.execute(
        "SELECT * FROM gold_iv_rank WHERE ticker = ?", [ticker]
    ).df()

    if row.empty:
        print(f"  No IV data for {ticker}")
        return

    r = row.iloc[0]
    print(f"  IV Current:      {fmt_pct(r['iv_current'])}  ← compare this to MC 'Current IV'")
    print(f"  IV Min (history):{fmt_pct(r['iv_min'])}")
    print(f"  IV Max (history):{fmt_pct(r['iv_max'])}")
    print(f"  IV Rank:         {r['iv_rank']*100:.1f}%  ← compare to MC 'IV Rank'")
    print(f"  IV Percentile:   {r['iv_percentile']*100:.1f}%  ← compare to MC 'IV Percentile'")
    print(f"  Snapshots used:  {int(r['snapshot_count'])}")
    print(f"  Last snapshot:   {str(r['snapshot_time'])[:16]}")


def verify_contract(symbol: str):
    """
    Print full snapshot history for one contract.
    Cross-check lastPrice and IV against your broker for the same dates.
    IBKR: Account Management → Trade History → Options
    """
    divider(f"CONTRACT DETAIL — {symbol}")
    print(f"  Cross-check lastPrice and IV against your broker for these dates.\n")

    df = con.execute(
        """
        SELECT
            snapshot_time,
            lastPrice,
            impliedVolatility,
            delta,
            gamma,
            theta,
            volume,
            openInterest,
            bid,
            ask
        FROM bronze_options_raw
        WHERE contractSymbol = ?
          AND lastPrice > 0
          AND impliedVolatility > 0.01
        ORDER BY snapshot_time
        """,
        [symbol]
    ).df()

    if df.empty:
        print(f"  No valid snapshots found for {symbol}")
        return

    # Format for readability
    df["snapshot_time"] = df["snapshot_time"].astype(str).str[:16]
    df["impliedVolatility"] = (df["impliedVolatility"] * 100).round(2).astype(str) + "%"
    df["delta"]  = df["delta"].round(4)
    df["gamma"]  = df["gamma"].round(4)
    df["theta"]  = df["theta"].round(4)
    df["lastPrice"] = df["lastPrice"].round(2)

    df = df.rename(columns={
        "snapshot_time":      "Snapshot",
        "lastPrice":          "Last $",
        "impliedVolatility":  "IV",
        "delta":              "Delta",
        "gamma":              "Gamma",
        "theta":              "Theta",
        "volume":             "Vol",
        "openInterest":       "OI",
        "bid":                "Bid",
        "ask":                "Ask",
    })

    print(df.to_string(index=False))
    print(f"\n  {len(df)} snapshots  |  Price range: ${df['Last $'].min():.2f} – ${df['Last $'].max():.2f}")


def verify_summary(ticker: str):
    """
    Print a summary of all contracts with 3+ snapshots.
    Use this to pick contracts to verify in detail.
    """
    divider(f"TRACKABLE CONTRACTS — {ticker}  (3+ snapshots, valid IV)")

    df = con.execute(
        """
        SELECT
            contractSymbol,
            expiry::VARCHAR AS expiry,
            option_type,
            strike,
            COUNT(DISTINCT snapshot_str)                    AS snapshots,
            ROUND(MIN(lastPrice), 2)                        AS price_min,
            ROUND(MAX(lastPrice), 2)                        AS price_max,
            ROUND(AVG(impliedVolatility) * 100, 2)          AS iv_avg_pct,
            ROUND(AVG(delta), 3)                            AS delta_avg
        FROM bronze_options_raw
        WHERE ticker = ?
          AND lastPrice > 0
          AND impliedVolatility > 0.01
        GROUP BY contractSymbol, expiry, option_type, strike
        HAVING COUNT(DISTINCT snapshot_str) >= 3
        ORDER BY expiry, strike, option_type
        """,
        [ticker]
    ).df()

    if df.empty:
        print(f"  No trackable contracts for {ticker} yet.")
        return

    df["expiry"] = df["expiry"].str[:10]

    print(df.to_string(index=False))
    print(f"\n  Total trackable contracts: {len(df)}")
    print(f"\n  To inspect a specific contract, run:")
    print(f"  python3 verify_data.py --contract <contractSymbol>")


def verify_pipeline_health():
    """
    Quick health check — shows snapshot counts, last run times, and row counts.
    Run this after each pipeline run to confirm everything ingested correctly.
    """
    divider("PIPELINE HEALTH CHECK")

    # Bronze snapshot counts
    bronze = con.execute("""
        SELECT ticker,
               COUNT(DISTINCT snapshot_str) AS total_snapshots,
               MAX(snapshot_time)::VARCHAR  AS last_snapshot,
               COUNT(*)                     AS total_rows
        FROM bronze_options_raw
        GROUP BY ticker
        ORDER BY ticker
    """).df()

    print("\n  Bronze (raw ingestion):")
    print(bronze.to_string(index=False))

    # Silver row counts
    silver = con.execute("""
        SELECT ticker, COUNT(*) AS contracts
        FROM silver_options_latest
        GROUP BY ticker
    """).df()

    print("\n  Silver (latest per contract):")
    print(silver.to_string(index=False))

    # Gold IV rank
    iv = con.execute("SELECT ticker, ROUND(iv_current*100,2) AS iv_pct, ROUND(iv_rank*100,1) AS iv_rank_pct, snapshot_count FROM gold_iv_rank").df()
    print("\n  Gold IV Rank:")
    print(iv.to_string(index=False))

    # Gold GEX row count
    gex = con.execute("SELECT ticker, COUNT(*) AS rows FROM gold_greeks_exposure GROUP BY ticker").df()
    print("\n  Gold GEX rows:")
    print(gex.to_string(index=False))


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify pipeline data against broker/Market Chameleon")

    parser.add_argument("--ticker",   default="AAPL",  help="Ticker to verify (default: AAPL)")
    parser.add_argument("--contract", default=None,    help="Specific contract symbol to inspect")
    parser.add_argument("--iv",       action="store_true", help="Show IV rank cross-check")
    parser.add_argument("--health",   action="store_true", help="Show pipeline health summary")

    args = parser.parse_args()

    if args.health:
        verify_pipeline_health()
    elif args.contract:
        verify_contract(args.contract)
    elif args.iv:
        verify_iv(args.ticker)
    else:
        # Default: show summary + IV
        verify_summary(args.ticker)
        verify_iv(args.ticker)
        print("\n  Run with --health to see full pipeline health check.")
        print("  Run with --contract <symbol> to inspect a specific contract.")
