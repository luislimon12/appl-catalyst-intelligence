import os
import logging
from datetime import datetime
import numpy as np                  # ← ADDED (missing from your imports)
import pandas as pd
from scipy.stats import norm        # ← ADDED (missing from your imports)
import yfinance as yf


class MarketSnapshotCollector:
    """
    Collects timestamped snapshots of price history and options chains for a ticker.

    Each run creates two CSV files:
    - price: 5-day OHLCV history with snapshot metadata
    - options: calls + puts for first 3 expiries with metadata

    Designed for append-only scheduled runs.

    """
    _BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


    def __init__(self, ticker="AAPL", price_dir=None, options_dir=None):
        self.ticker = ticker
        self.snapshot_time = datetime.now()
        self.snapshot_str = self.snapshot_time.strftime("%Y%m%d_%H%M%S")
        self.price_dir = price_dir or os.path.join(self._BASE, "data", "raw", "price")
        self.options_dir = options_dir or os.path.join(self._BASE, "data", "raw", "options")


        os.makedirs(self.price_dir, exist_ok=True)
        os.makedirs(self.options_dir, exist_ok=True)

        self.logger = logging.getLogger(self.__class__.__name__)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s | %(name)s | %(levelname)s | %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

        self.asset = yf.Ticker(self.ticker)

    # ── HELPERS ───────────────────────────────────────────────────────────────

    def add_metadata(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add snapshot_time, snapshot_str, and ticker columns to DataFrame."""
        df = df.copy()
        df["snapshot_time"] = self.snapshot_time
        df["snapshot_str"] = self.snapshot_str
        df["ticker"] = self.ticker
        return df

    def save_dataframe(self, df: pd.DataFrame, path: str) -> None:
        """Save DataFrame to timestamped CSV with error handling."""
        try:
            df.to_csv(path, index=False)
            self.logger.info(f"Saved file: {path} | shape={df.shape}")
        except Exception as e:
            self.logger.error(f"Failed to save {path}: {e}")

    def clean_price(self, df: pd.DataFrame) -> pd.DataFrame:       # ← FIXED indentation (extra space before def)
        """Strip timezone, round prices, drop irrelevant columns."""
        df["Date"] = pd.to_datetime(df["Date"]).dt.date
        price_cols = ["Open", "High", "Low", "Close"]
        df[price_cols] = df[price_cols].round(2)
        df = df.drop(columns=["Dividends", "Stock Splits"], errors="ignore")
        return df

    def calculate_hv(self, df: pd.DataFrame) -> pd.DataFrame:      # ← FIXED indentation (extra space before def)
        """Calculate 20-day and annualized historical volatility from Close prices."""
        df["log_return"] = np.log(df["Close"] / df["Close"].shift(1))
        df["HV_20"] = df["log_return"].rolling(window=20).std() * np.sqrt(252)
        df["HV_252"] = df["log_return"].rolling(window=252).std() * np.sqrt(252)
        df = df.drop(columns=["log_return"])
        df[["HV_20", "HV_252"]] = df[["HV_20", "HV_252"]].round(4)
        return df

    def calculate_greeks(self, df: pd.DataFrame, spot_price: float, r: float = 0.05) -> pd.DataFrame:
        """Calculate Black-Scholes Greeks for each options contract row."""

        # Make a copy so we don't modify the original DataFrame passed in
        df = df.copy()

        # Create empty lists to collect each Greek value row by row
        greeks = {"delta": [], "gamma": [], "theta": [], "vega": []}

        # Loop through every row — each row is one options contract
        for _, row in df.iterrows():
            try:
                # Current stock price (same for every row, passed in from collect_options)
                S = spot_price

                # Strike price of this specific contract
                K = row["strike"]

                # Implied volatility returned by Yahoo Finance for this contract
                sigma = row["impliedVolatility"]

                # Time to expiry expressed as a fraction of a year
                T = (pd.to_datetime(row["expiry"]) - pd.Timestamp.now()).days / 365

                # Whether this row is a call or a put
                option_type = row["option_type"]

                # Guard: skip if inputs would cause divide-by-zero or nonsense
                if T <= 0 or sigma <= 0 or K <= 0:
                    raise ValueError("Invalid input values")

                # d1: standardized distance between stock price and strike
                d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))

                # d2: d1 shifted down by one volatility unit
                d2 = d1 - sigma * np.sqrt(T)

                # Delta: how much option price moves per $1 move in stock
                delta = norm.cdf(d1) if option_type == "call" else norm.cdf(d1) - 1

                # Gamma: how fast delta changes per $1 move in stock
                gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))

                # Theta: daily time decay (divided by 365 for daily)
                if option_type == "call":
                    theta = (
                        (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)))
                        - r * K * np.exp(-r * T) * norm.cdf(d2)
                    ) / 365
                else:
                    theta = (
                        (-S * norm.pdf(d1) * sigma / (2 * np.sqrt(T)))
                        + r * K * np.exp(-r * T) * norm.cdf(-d2)
                    ) / 365

                # Vega: option price change per 1% move in IV
                vega = S * norm.pdf(d1) * np.sqrt(T) / 100

                # Append all four Greeks rounded to 4 decimal places
                greeks["delta"].append(round(float(delta), 4))
                greeks["gamma"].append(round(float(gamma), 4))
                greeks["theta"].append(round(float(theta), 4))
                greeks["vega"].append(round(float(vega), 4))


            except Exception as e:
                # Append None placeholders so the row still exists in output
                self.logger.warning(f"Greeks failed for row: {e}")
                greeks["delta"].append(None)
                greeks["gamma"].append(None)
                greeks["theta"].append(None)
                greeks["vega"].append(None)

        # Attach all four Greek lists as new columns
        df["delta"] = greeks["delta"]
        df["gamma"] = greeks["gamma"]
        df["theta"] = greeks["theta"]
        df["vega"] = greeks["vega"]
        return df

    # ── COLLECTORS ────────────────────────────────────────────────────────────

    def collect_price(self) -> pd.DataFrame | None:
        """Collect 5-day price history with HV. Returns DataFrame or None if failed/empty."""
        try:
            prices = self.asset.history(period="2y")
            if prices.empty:
                self.logger.warning("Price history returned empty DataFrame.")
                return None

            prices = prices.reset_index()
            prices = self.calculate_hv(prices)  
            prices = self.clean_price(prices)       #
               
            prices = self.add_metadata(prices)

            path = f"{self.price_dir}/{self.ticker.lower()}_price_{self.snapshot_str}.csv"
            self.save_dataframe(prices, path)
            return prices

        except Exception as e:
            self.logger.error(f"Failed to collect price: {e}")
            return None

    def collect_options(self, max_expiries=3) -> pd.DataFrame | None:
        """Collect calls + puts with Greeks for first N expiries."""
        try:
            expiries = self.asset.options
        except Exception as e:
            self.logger.error(f"Failed to fetch option expiries: {e}")
            return None

        if not expiries:
            self.logger.warning("No option expiries returned.")
            return None

        # Get current stock price once for Greeks calculation
        spot_price = self.asset.history(period="1d")["Close"].iloc[-1]  # ← ADDED

        options_list = []
        for expiry in expiries[:max_expiries]:
            try:
                chain = self.asset.option_chain(expiry)

                calls = chain.calls.copy()
                calls["expiry"] = expiry
                calls["option_type"] = "call"

                puts = chain.puts.copy()
                puts["expiry"] = expiry
                puts["option_type"] = "put"

                combined = pd.concat([calls, puts], ignore_index=True)
                combined = self.calculate_greeks(combined, spot_price=spot_price)   # ← ADDED
                combined = self.add_metadata(combined)
                options_list.append(combined)

                self.logger.info(f"Collected options for expiry {expiry} | rows={combined.shape[0]}")

            except Exception as e:
                self.logger.error(f"Failed to collect options for expiry {expiry}: {e}")
                continue

        if not options_list:
            self.logger.warning("No options data collected.")
            return None

        options_df = pd.concat(options_list, ignore_index=True)

        # Updated schema includes Greeks, removes junk columns
        keep_cols = [
            "contractSymbol", "expiry", "option_type", "strike",
            "bid", "ask", "lastPrice", "volume", "openInterest",
            "impliedVolatility", "delta", "gamma", "theta", "vega",
            "inTheMoney", "snapshot_time", "snapshot_str", "ticker"
        ]
        existing_cols = [col for col in keep_cols if col in options_df.columns]
        options_df = options_df[existing_cols]

        path = f"{self.options_dir}/{self.ticker.lower()}_options_{self.snapshot_str}.csv"
        self.save_dataframe(options_df, path)
        return options_df

    # ── ORCHESTRATOR ──────────────────────────────────────────────────────────

    def run(self) -> None:
        """Execute full pipeline: price + options collection."""
        self.logger.info(f"Starting snapshot run for {self.ticker} | snapshot={self.snapshot_str}")
        self.collect_price()
        self.collect_options(max_expiries=3)
        self.logger.info("Snapshot run complete.")


if __name__ == "__main__":
    collector = MarketSnapshotCollector(ticker="AAPL")
    collector.run()
