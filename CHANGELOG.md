# Changelog — AAPL & INTC Catalyst Intelligence Pipeline

All significant changes are documented here in reverse chronological order.

---

## [Unreleased] — Session 3 · June 4, 2026

### Dashboard — Goals 1–6
- Built `dashboard/app.py` — Streamlit dashboard with dark terminal theme
- **Goal 1** — Foundation: DuckDB connection, ticker toggle (AAPL/INTC), auto-refresh timer, sidebar controls
- **Goal 2** — IV Rank Gauge: Plotly gauge with color-coded quartile zones, metric row, snapshot caption
- **Goal 3** — PCR Table: Put/call ratio by expiry, color-coded by threshold (0.7/1.0), ALL row pinned to bottom, expiry formatted as `Jun 20 '26`
- **Goal 4** — GEX Bar Chart: Net gamma by strike, spot price overlay, expiry selector, ±20% strike filter, bars colored blue (long) / red (short)
- **Goal 5** — Options Chain Table: Filterable by expiry, call/put, ±% strike range, ITM rows highlighted green, NaN Greeks shown as `—`
- **Goal 6** — Contract Tracker: Watchlist with session state, select by expiry/strike/type, multi-line chart, metric toggle (Price/IV/Delta)

### Pipeline automation
- `collect_market_snapshots.py` — updated `__main__` to loop through all `TICKERS` (AAPL + INTC) instead of hardcoded AAPL only
- `collect_market_snapshots.py` — added `subprocess.run` calls after collection to automatically chain `build_database.py` → `build_silver.py`
- LaunchAgent `com.luislimon.market-data-collector.plist` — added 9:35 AM open trigger alongside existing 4:15 PM close trigger for open/close snapshots

### Data quality fix
- `build_silver.py` — filter `ask < bid` rows during Silver promotion instead of crashing on assertion. Downgraded to WARNING log.

### Git hygiene
- `.gitignore` — added `*.duckdb`, `*.duckdb.wal`, raw CSV exclusions

---

## [0.2.0] — Session 2 · May 2026

### Pipeline expansion
- `collect_market_snapshots.py` — expanded from AAPL-only to multi-ticker `TICKERS` list (`["AAPL", "INTC"]`)
- `collect_market_snapshots.py` — full options chain collection (all expiries, no slice limit)
- `option_metrics.py` — Black-Scholes Greeks with timezone-safe T calculation anchored to 4 PM expiry close
- `price_metrics.py` — HV_20 and HV_252 historical volatility, OHLC cleaning

### Database — Bronze → Silver → Gold
- `build_database.py` — Bronze ingestion with source file deduplication
- `build_silver.py` — Silver validation suite (nulls, duplicates, price logic, schema checks)
- Five Gold tables built:
  - `gold_latest_snapshot` — one row per contract joined to most recent price close, HV_20, HV_252
  - `gold_pcr` — put/call ratio by expiry and ticker aggregate (volume + OI)
  - `gold_iv_rank` — ATM IV rank and percentile across all historical snapshots
  - `gold_greeks_exposure` — net delta and gamma by strike and expiry (raw + notional dollars)

---

## [0.1.0] — Session 1 · May 2026

### Initial setup
- Repo initialized with Bronze → Silver → Gold medallion architecture
- `collect_market_snapshots.py` — initial AAPL-only collector via yfinance
- LaunchAgent configured to fire at 16:15 Monday–Friday
- `data/raw/price/` and `data/raw/options/` directories established
- DuckDB chosen as the local warehouse (`appl_catalyst.duckdb`)
- `notebooks/01_yfinance_data_check.ipynb` — initial data exploration
