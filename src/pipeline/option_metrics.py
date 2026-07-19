import re
import numpy as np
import pandas as pd
from scipy.stats import norm
from datetime import datetime


def calculate_greeks(
    df: pd.DataFrame,
    spot_price: float,
    r: float = 0.05,
    logger=None
) -> pd.DataFrame:
    """
    Calculate Black-Scholes Greeks for each options contract row.

    Works for all expiries: same-day (0 DTE) through 2027/2028 LEAPS.
    Uses total_seconds() anchored to 4 PM market close to avoid T=0
    on near-expiry contracts.

    Parameters
    ----------
    df          : Combined options chain (calls + puts, all expiries).
    spot_price  : Current underlying price.
    r           : Risk-free rate (default 5%).
    logger      : Optional logger from the orchestrator.

    Returns
    -------
    DataFrame with delta, gamma, theta, vega columns appended.
    """
    df     = df.copy()
    greeks = {"delta": [], "gamma": [], "theta": [], "vega": []}

    for _, row in df.iterrows():
        try:
            S           = spot_price
            K           = float(row["strike"])
            sigma       = float(row["impliedVolatility"])
            option_type = row["option_type"]                ## assigned before guard

            if sigma <= 0 or K <= 0:                        ## T > 0 guaranteed by max() below
                raise ValueError(f"Invalid inputs: K={K}, sigma={sigma}")

            ## Anchor to 4 PM close on expiry day; floor at 1/365 to prevent T=0
            expiry_close = pd.to_datetime(row["expiry"]).tz_localize("America/New_York") + pd.Timedelta(hours=16)
            now_eastern  = pd.Timestamp.now(tz="America/New_York")
            T = max(
                (expiry_close - now_eastern).total_seconds() / (365 * 24 * 3600),
                1 / 365
            )

            d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
            d2 = d1 - sigma * np.sqrt(T)

            delta = norm.cdf(d1) if option_type == "call" else norm.cdf(d1) - 1
            gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))

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

            vega = S * norm.pdf(d1) * np.sqrt(T) / 100

            greeks["delta"].append(round(float(delta), 4))
            greeks["gamma"].append(round(float(gamma), 4))
            greeks["theta"].append(round(float(theta), 4))
            greeks["vega"].append(round(float(vega),  4))

        except Exception as e:
            if logger:
                logger.warning(f"Greeks failed for {row.get('contractSymbol', '?')}: {e}")
            greeks["delta"].append(None)
            greeks["gamma"].append(None)
            greeks["theta"].append(None)
            greeks["vega"].append(None)

    df["delta"] = greeks["delta"]
    df["gamma"] = greeks["gamma"]
    df["theta"] = greeks["theta"]
    df["vega"]  = greeks["vega"]
    return df


def make_contract_label(symbol: str, style: str = "short") -> str:
    """
    Convert raw OCC contract symbol into a human-readable label.

    AAPL260518P00295000 ->
        short:   '$295P 05/18/26'   <- default
        full:    'AAPL $295 Put  May 18 '26'
        minimal: '$295P'
    """
    try:
        match = re.match(r"([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})", symbol)
        if not match:
            return symbol

        ticker, yy, mm, dd, cp, strike_raw = match.groups()
        strike      = int(strike_raw) / 1000
        option_type = "Call" if cp == "C" else "Put"
        strike_str  = f"${strike:.0f}" if strike == int(strike) else f"${strike:.2f}"
        date        = datetime(2000 + int(yy), int(mm), int(dd))

        if style == "short":
            return f"{strike_str}{cp} {date.strftime('%m/%d/%y')}"
        elif style == "full":
            date_str = date.strftime("%b %d '%y")          ## pre-compute outside f-string — backslash not allowed inside f-string on Python < 3.12
            return f"{ticker} {strike_str} {option_type}  {date_str}"
        elif style == "minimal":
            return f"{strike_str}{cp}"
        else:
            return symbol

    except Exception:
        return symbol