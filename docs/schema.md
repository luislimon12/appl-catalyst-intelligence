# Data Schema

## Price Snapshots

Files: `data/raw/price/aapl_price_YYYYMMDD_HHMMSS.csv`

| Column       | Type     | Source   | Purpose                                      |
|--------------|----------|----------|----------------------------------------------|
| Date         | datetime | yfinance | Price date                                   |
| Open         | float    | yfinance | Open price                                   |
| High         | float    | yfinance | High price                                   |
| Low          | float    | yfinance | Low price                                    |
| Close        | float    | yfinance | Close price                                  |
| Volume       | int      | yfinance | Trading volume                               |
| HV_20        | float    | pipeline | 20-day annualized historical volatility      |
| HV_252       | float    | pipeline | 252-day annualized historical volatility     |
| snapshot_time| datetime | pipeline | Collection timestamp                         |
| snapshot_str | str      | pipeline | Unique snapshot ID                           |
| ticker       | str      | pipeline | AAPL                                         |

> **Removed**: `Dividends`, `Stock Splits` — dropped during `clean_price()` as not relevant to options analysis.

---

## Options Snapshots

Files: `data/raw/options/aapl_options_YYYYMMDD_HHMMSS.csv`

| Column            | Type     | Source   | Purpose                                      |
|-------------------|----------|----------|----------------------------------------------|
| contractSymbol    | str      | yfinance | Unique contract identifier                   |
| expiry            | datetime | pipeline | Option expiration date                       |
| option_type       | str      | pipeline | `call` or `put`                              |
| strike            | float    | yfinance | Strike price                                 |
| bid               | float    | yfinance | Bid price                                    |
| ask               | float    | yfinance | Ask price                                    |
| lastPrice         | float    | yfinance | Last traded price                            |
| volume            | int      | yfinance | Trading volume                               |
| openInterest      | int      | yfinance | Open interest                                |
| impliedVolatility | float    | yfinance | Implied volatility (raw from market)         |
| delta             | float    | pipeline | BS Greek — price sensitivity to stock move   |
| gamma             | float    | pipeline | BS Greek — rate of delta change              |
| theta             | float    | pipeline | BS Greek — daily time decay                  |
| vega              | float    | pipeline | BS Greek — sensitivity to IV change (per 1%)|
| inTheMoney        | bool     | yfinance | Whether contract is ITM                      |
| snapshot_time     | datetime | pipeline | Collection timestamp                         |
| snapshot_str      | str      | pipeline | Unique snapshot ID                           |
| ticker            | str      | pipeline | AAPL                                         |

---

## Notes

- Greeks (`delta`, `gamma`, `theta`, `vega`) are calculated using the **Black-Scholes model** at collection time, using Yahoo Finance's `impliedVolatility` and a risk-free rate of `r = 0.05`.
- `HV_20` and `HV_252` are computed from log returns on the 2-year price history pulled at each snapshot.
- `snapshot_str` format: `YYYYMMDD_HHMMSS` — used as the unique run identifier across both tables.
- First **3 expiries** are collected per snapshot for the options chain.