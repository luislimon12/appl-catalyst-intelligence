# ──────────────────────────────────────────────────────────────────────────────
# collect_market_snapshots.py
# AAPL & INTC Catalyst Intelligence Pipeline — Orchestrator
#
# Session 1 (May 2026): Initial AAPL-only collector, LaunchAgent at 16:15
# Session 2 (May 2026): Multi-ticker support, all expiries, Greeks via option_metrics.py
# Session 3 (Jun 2026): Loop through TICKERS list, chain build_database + build_silver
#                        after collection. LaunchAgent updated to fire at 9:35 + 16:15.
# ──────────────────────────────────────────────────────────────────────────────
import os
import subprocess
import logging
from datetime import datetime, date

import pandas as pd
import numpy as np
from scipy.stats import norm
import yfinance as yf

from price_metrics import clean_price, calculate_hv
from option_metrics import calculate_greeks

## US market holidays for 2026 — extend annually
MARKET_HOLIDAYS = {
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
}

## Tickers to collect — add or remove here
TICKERS = ["AAPL", "INTC"]


class MarketSnapshotCollector:
    ## Orchestrates one market snapshot run for a ticker.
    ## Responsible for: collecting raw data, calling transformations,
    ## adding metadata, saving outputs, and logging pipeline activity.
    ##
    ## Architecture:
    ## - File 1: orchestration  -> this class
    ## - File 2: price metrics  -> price_metrics.py
    ## - File 3: option metrics -> option_metrics.py

    _BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def __init__(self, ticker="AAPL", price_dir=None, options_dir=None):
        ## Initialize paths, logger, timestamp metadata, and yfinance handle
        self.ticker        = ticker
        self.snapshot_time = datetime.now()
        self.snapshot_str  = self.snapshot_time.strftime("%Y%m%d_%H%M%S")
        self.price_dir     = price_dir   or os.path.join(self._BASE, "data", "raw", "price")
        self.options_dir   = options_dir or os.path.join(self._BASE, "data", "raw", "options")

        os.makedirs(self.price_dir,   exist_ok=True)
        os.makedirs(self.options_dir, exist_ok=True)

        self.logger = logging.getLogger(self.__class__.__name__)
        if not self.logger.handlers:
            handler   = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

        self.asset = yf.Ticker(self.ticker)

    # ── HELPERS ───────────────────────────────────────────────────────────────

    def add_metadata(self, df: pd.DataFrame) -> pd.DataFrame:
        ## Tag every row with snapshot timestamp and ticker for downstream joins
        df = df.copy()
        df["snapshot_time"] = self.snapshot_time
        df["snapshot_str"]  = self.snapshot_str
        df["ticker"]        = self.ticker
        return df

    def save_dataframe(self, df: pd.DataFrame, path: str) -> None:
        ## Save DataFrame to CSV; log success or failure with shape
        try:
            df.to_csv(path, index=False)
            self.logger.info(f"Saved: {path} | shape={df.shape}")
        except Exception as e:
            self.logger.error(f"Failed to save {path}: {e}")

    # ── COLLECTORS ────────────────────────────────────────────────────────────

    def collect_price(self) -> pd.DataFrame | None:
        ## Fetch 2y price history, compute HV, clean, tag metadata, save CSV
        try:
            prices = self.asset.history(period="2y")
            if prices.empty:
                self.logger.warning("Price history returned empty DataFrame.")
                return None

            prices = prices.reset_index()
            prices = calculate_hv(prices)
            prices = clean_price(prices)
            prices = self.add_metadata(prices)

            path = f"{self.price_dir}/{self.ticker.lower()}_price_{self.snapshot_str}.csv"
            self.save_dataframe(prices, path)
            return prices

        except Exception as e:
            self.logger.error(f"Failed to collect price: {e}")
            return None

    def collect_options(self) -> pd.DataFrame | None:
        ## Fetch full options chain (all expiries), compute Greeks, tag metadata, save CSV
        try:
            expiries = self.asset.options
        except Exception as e:
            self.logger.error(f"Failed to fetch option expiries: {e}")
            return None

        if not expiries:
            self.logger.warning("No option expiries returned.")
            return None

        self.logger.info(f"Fetching {len(expiries)} expiries for {self.ticker}")

        spot_price = self.asset.history(period="1d")["Close"].iloc[-1]
        self.logger.info(f"Spot price: {spot_price:.2f}")

        options_list = []

        for expiry in expiries:                          ## no slice — all expiries
            try:
                chain = self.asset.option_chain(expiry)

                calls = chain.calls.copy()
                calls["expiry"]      = expiry
                calls["option_type"] = "call"

                puts = chain.puts.copy()
                puts["expiry"]      = expiry
                puts["option_type"] = "put"

                combined = pd.concat([calls, puts], ignore_index=True)
                combined = calculate_greeks(
                    combined,
                    spot_price=spot_price,
                    logger=self.logger          ## pass logger so Greeks failures appear in log
                )
                combined = self.add_metadata(combined)
                options_list.append(combined)

                self.logger.info(f"Collected expiry {expiry} | rows={combined.shape[0]}")

            except Exception as e:
                self.logger.error(f"Failed to collect options for expiry {expiry}: {e}")
                continue

        if not options_list:
            self.logger.warning("No options data collected.")
            return None

        options_list = [df for df in options_list if not df.empty]  ## drop empty/all-NA frames before concat — suppresses FutureWarning
        options_df = pd.concat(options_list, ignore_index=True)

        keep_cols = [
            "contractSymbol", "expiry", "option_type", "strike",
            "bid", "ask", "lastPrice", "volume", "openInterest",
            "impliedVolatility", "delta", "gamma", "theta", "vega",
            "inTheMoney", "snapshot_time", "snapshot_str", "ticker"
        ]
        existing_cols = [col for col in keep_cols if col in options_df.columns]
        options_df    = options_df[existing_cols]

        self.logger.info(f"Total options collected | rows={options_df.shape[0]} contracts={options_df['contractSymbol'].nunique()}")

        path = f"{self.options_dir}/{self.ticker.lower()}_options_{self.snapshot_str}.csv"
        self.save_dataframe(options_df, path)
        return options_df

    def is_market_open(self) -> bool:
        ## Returns True on weekdays that are not US market holidays
        now   = datetime.now()
        today = now.date()
        if today in MARKET_HOLIDAYS:
            return False
        return now.weekday() < 5

    # ── ORCHESTRATOR ──────────────────────────────────────────────────────────

    def run(self) -> None:
        ## Entry point — check market, then collect price and options in sequence
        if not self.is_market_open():
            self.logger.info("Market closed. Skipping snapshot run.")
            return

        self.logger.info(f"Starting snapshot run | ticker={self.ticker} | snapshot={self.snapshot_str}")
        self.collect_price()
        self.collect_options()
        self.logger.info("Snapshot run complete.")


if __name__ == "__main__":
    for ticker in TICKERS:
        collector = MarketSnapshotCollector(ticker=ticker)
        collector.run()

    ## Run database pipeline after all tickers collected
    pipeline_dir = os.path.dirname(os.path.abspath(__file__))
    python       = "/opt/anaconda3/bin/python3"

    logging.info("Running build_database.py...")
    subprocess.run([python, os.path.join(pipeline_dir, "build_database.py")], check=True)

    logging.info("Running build_silver.py...")
    subprocess.run([python, os.path.join(pipeline_dir, "build_silver.py")], check=True)

    logging.info("Pipeline complete — Gold tables updated.")