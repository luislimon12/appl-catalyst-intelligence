# Data Schema

## Price Snapshots
Files: `data/raw/price/aapl_price_YYYYMMDD_HHMMSS.csv`

| Column | Type | Source | Purpose |
|--------|------|--------|---------|
| Date | datetime | yfinance | Price date |
| Open | float | yfinance | Open price |
| High | float | yfinance | High price |
| Low | float | yfinance | Low price |
| Close | float | yfinance | Close price |
| Volume | int | yfinance | Trading volume |
| Dividends | float | yfinance | Dividend amount |
| Stock Splits | float | yfinance | Split ratio |
| snapshot_time | datetime | pipeline | Collection timestamp |
| snapshot_str | str | pipeline | Unique snapshot ID |
| ticker | str | pipeline | AAPL |

## Options Snapshots  
Files: `data/raw/options/aapl_options_YYYYMMDD_HHMMSS.csv`

| Column | Type | Source | Purpose |
|--------|------|--------|---------|
| contractSymbol | str | yfinance | Contract ID |
| lastTradeDate | datetime | yfinance | Last trade time |
| strike | float | yfinance | Strike price |
| lastPrice | float | yfinance | Last traded price |
| bid | float | yfinance | Bid price |
| ask | float | yfinance | Ask price |
| volume | int | yfinance | Trading volume |
| openInterest | int | yfinance | Open interest |
| impliedVolatility | float | yfinance | IV |
| inTheMoney | bool | yfinance | ITM flag |
| snapshot_time | datetime | pipeline | Collection timestamp |
| snapshot_str | str | pipeline | Unique snapshot ID |
| ticker | str | pipeline | AAPL |
| expiry | str | pipeline | Expiry date |
| option_type | str | pipeline | call/put |
