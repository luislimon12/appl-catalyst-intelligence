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
import sys
import subprocess
import logging
from datetime import datetime             ## snapshot_time uses datetime.now()

import pandas as pd
import yfinance as yf  ## Sep 2026: removed unused numpy and scipy.stats imports — math lives in option_metrics.py

from price_metrics import clean_price, calculate_hv
from option_metrics import calculate_greeks
from pipeline_utils import (
    TICKERS, MARKET_HOLIDAYS, is_market_open,       ## Sep 2026: moved to pipeline_utils — shared with collect_chain_snapshot.py
    setup_logger, add_metadata,                      ## logger + metadata tagging helpers
    fetch_spot_price, fetch_risk_free_rate           ## market data helpers
)


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

        self.logger = setup_logger(self.__class__.__name__)  ## Sep 2026: moved to pipeline_utils — was 5 lines of boilerplate inline

        self.asset = yf.Ticker(self.ticker)

    # ── HELPERS ───────────────────────────────────────────────────────────────

    ## Sep 2026: add_metadata() moved to pipeline_utils — import at top of file

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
            prices = add_metadata(prices, self.snapshot_time, self.ticker)  ## Sep 2026: standalone function — pass snapshot_time and ticker explicitly

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

        spot_price = fetch_spot_price(self.asset, self.logger)  ## Sep 2026: moved to pipeline_utils
        if spot_price is None:                                   ## None = fetch failed — abort options collection
            return None

        r = fetch_risk_free_rate(self.logger)  ## Sep 2026: moved to pipeline_utils

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
                    r=r,                        ## Sep 2026: live T-bill rate instead of hardcoded 0.05
                    logger=self.logger          ## pass logger so Greeks failures appear in log
                )
                combined = add_metadata(combined, self.snapshot_time, self.ticker)  ## Sep 2026: standalone function — pass snapshot_time and ticker explicitly
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

    # ── ORCHESTRATOR ──────────────────────────────────────────────────────────

    def run(self) -> None:
        ## Entry point — check market, then collect price and options in sequence
        if not is_market_open():  ## Sep 2026: now a standalone function in pipeline_utils
            self.logger.info("Market closed. Skipping snapshot run.")
            return

        self.logger.info(f"Starting snapshot run | ticker={self.ticker} | snapshot={self.snapshot_str}")
        self.collect_price()
        self.collect_options()
        self.logger.info("Snapshot run complete.")


if __name__ == "__main__":
    pipeline_logger = setup_logger("pipeline")  ## Sep 2026: moved to pipeline_utils — was 5 lines of boilerplate inline

    for ticker in TICKERS:
        collector = MarketSnapshotCollector(ticker=ticker)
        collector.run()

    ## Run database pipeline after all tickers collected
    pipeline_dir = os.path.dirname(os.path.abspath(__file__))
    python       = sys.executable  ## always use the same Python that's running this script

    pipeline_logger.info("Running build_database.py...")
    subprocess.run([python, os.path.join(pipeline_dir, "build_database.py")], check=True)

    pipeline_logger.info("Running build_silver.py...")
    subprocess.run([python, os.path.join(pipeline_dir, "build_silver.py")], check=True)

    pipeline_logger.info("Pipeline complete — Gold tables updated.")