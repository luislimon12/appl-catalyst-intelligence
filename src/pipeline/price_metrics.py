import numpy as np
import pandas as pd


def clean_price(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean and standardize historical price data.

    Steps
    -----
    - Convert Date to plain date format
    - Round OHLC price columns
    - Drop unused corporate action columns if present
    """
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"]).dt.date
    price_cols = ["Open", "High", "Low", "Close"]
    df[price_cols] = df[price_cols].round(2)
    df = df.drop(columns=["Dividends", "Stock Splits"], errors="ignore")
    return df


def calculate_hv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate historical volatility features from Close prices.

    Method
    ------
    - Compute log returns
    - Calculate rolling volatility windows
    - Annualize using sqrt(252)
    """
    df = df.copy()
    df["log_return"] = np.log(df["Close"] / df["Close"].shift(1))
    df["HV_20"] = df["log_return"].rolling(window=20).std() * np.sqrt(252)
    df["HV_252"] = df["log_return"].rolling(window=252).std() * np.sqrt(252)
    df = df.drop(columns=["log_return"])
    df[["HV_20", "HV_252"]] = df[["HV_20", "HV_252"]].round(4)
    return df
