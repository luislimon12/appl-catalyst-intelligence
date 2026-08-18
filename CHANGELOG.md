# Changelog — AAPL & INTC Catalyst Intelligence Dashboard

All significant changes documented in reverse chronological order.

---

## [0.6.0] — Session 6 · August 2026

### GEX formula fix

* `build_silver.py` — upgraded `net_gamma_notional`, `call_gamma_notional`, and `put_gamma_notional` from simple notional (`gamma × OI × strike × 100`) to proper dollar gamma per 1% move (`gamma × OI × strike² × 0.01 × 100`). Higher-priced strikes were previously underweighted relative to their true hedging impact.
* `build_silver.py` — `net_gamma` and `net_gamma_notional` now flip sign for puts. Dealers are short gamma on put positions, so put GEX subtracts from net. The previous formula added calls and puts as both positive, overstating net GEX and hiding the gamma flip level.
* Requires `docker exec catalyst_dashboard python src/pipeline/build_silver.py` on the droplet to rebuild `gold_greeks_exposure` with corrected values.

---

## [0.5.0] — Session 5 · August 2026

### Production deployment

* `requirements.txt` — pinned exact versions of all dependencies for reproducible builds
* `Dockerfile` — containerized Streamlit app on `python:3.11-slim`, layer-cached pip install so code changes don't re-run pip
* `docker-compose.yml` — orchestrates Streamlit + Nginx on a private bridge network; DuckDB and watchlist mounted as host volumes
* `nginx.conf` — reverse proxy with TLS 1.2/1.3, ECDHE cipher suites (Perfect Forward Secrecy), rate limiting (token bucket 10r/s burst=20), security headers (HSTS, X-Frame-Options, nosniff, Referrer-Policy), Slow Loris protection, WebSocket passthrough for Streamlit live updates
* `.dockerignore` — excludes database, git history, notebooks, and dev-only directories from image
* Deployed to DigitalOcean Ubuntu droplet (NYC1, $6/mo) — Docker + Nginx running in containers
* SSL via Let's Encrypt / Certbot — dashboard live at `catalyst.luislimon.dev`
* Cloudflare registered domain and DNS — `catalyst.luislimon.dev` points to droplet

### Pipeline fixes (discovered during Docker deployment)

* `requirements.txt` — `yfinance` was missing entirely; Docker built the image without it causing `ModuleNotFoundError` on first pipeline run. Added `yfinance==0.2.66`. Also removed a duplicate `yfinance==0.2.54` entry from a previous session that was causing a pip dependency conflict.
* `collect_market_snapshots.py` — replaced hardcoded `/opt/anaconda3/bin/python3` with `sys.executable` — the Mac's Anaconda path doesn't exist inside Docker, causing `FileNotFoundError` when the pipeline tried to chain `build_database.py` as a subprocess
* `docker-compose.yml` — removed `:ro` (read-only) flag from DuckDB volume mount — the pipeline needs write access to update the database after each collection run; the dashboard only reads but the pipeline writes

### Dashboard fix

* `2_Options_Chain.py` — added `df = df[df["dte"] >= 0]` to filter out expired contracts; negative DTE rows (already-expired expiries stored in the database) were showing in the options chain table

---

## [0.4.0] — Session 4 · July 2026

### Dashboard — Goals 7–8 and multipage split

* **Goal 7** — Catalyst event markers: WWDC and iPhone Launch overlaid on term structure chart as dotted vertical lines, converted from calendar dates to DTE for x-axis positioning
* **Goal 8** — Split monolithic `app.py` into multipage layout: Market Overview / Options Chain / Contract Tracker / Distribution Analysis
* `2_Options_Chain.py` — ladder view using hash table keyed by `(strike, expiry, dte)` — one row per strike with calls on left, puts on right, ATM row highlighted gold, ITM calls shaded green, ITM puts shaded red, Skew column showing IV difference between sides
* `2_Options_Chain.py` — IV term structure chart: DTE on x-axis, volume-weighted ATM IV bubbles, slope bars (green = contango, red = backwardation), catalyst event markers as vertical dotted lines
* `2_Options_Chain.py` — IV skew chart by strike with volume bubble sizing — larger bubble = more liquid = more trustworthy IV reading
* `3_Contract_Tracker.py` — OI and Volume bar charts added alongside existing price/IV/delta line chart

### Bug fixes

* Options Chain calls/puts filter returning wrong option type
* IV metric cards truncating long values
* IV line chart showing raw decimal instead of percentage
* PCR table showing `None` in OI column
* GEX chart caption text incorrect
* Options Chain defaulting to wrong expiry on load
* GEX chart missing permanent spot price label
* PCR table ALL row not visually separated from expiry rows
* IV gauge missing direction indicator (▲/▼ vs previous snapshot)

---

## [0.3.0] — Session 3 · June 2026

### Dashboard — Goals 1–6

* Built `dashboard/app.py` — Streamlit dashboard with dark terminal theme
* **Goal 1** — Foundation: DuckDB connection, ticker toggle (AAPL/INTC), auto-refresh timer, sidebar controls
* **Goal 2** — IV Rank Gauge: Plotly gauge with color-coded quartile zones, metric row (IV current, range, percentile, Z-score), snapshot caption
* **Goal 3** — PCR Table: Put/call ratio by expiry, color-coded by threshold (0.7/1.0), ALL row pinned to bottom, expiry formatted as `Jun 20 '26`
* **Goal 4** — GEX Bar Chart: Net gamma by strike, spot price overlay, expiry selector, ±20% strike filter, bars colored blue (long) / red (short)
* **Goal 5** — Options Chain Table: Filterable by expiry, call/put, ±% strike range, ITM rows highlighted green, NaN Greeks shown as `—`
* **Goal 6** — Contract Tracker: Watchlist with session state, select by expiry/strike/type, multi-line chart, metric toggle (Price/IV/Delta)

### Pipeline automation

* `collect_market_snapshots.py` — updated `__main__` to loop through all `TICKERS` (AAPL + INTC) instead of hardcoded AAPL only
* `collect_market_snapshots.py` — added `subprocess.run` calls after collection to automatically chain `build_database.py` → `build_silver.py`
* LaunchAgent `com.luislimon.market-data-collector.plist` — added 9:35 AM open trigger alongside existing 4:15 PM close trigger for open/close snapshots

### Data quality fix

* `build_silver.py` — filter `ask < bid` rows during Silver promotion instead of crashing on assertion. Downgraded to WARNING log.

### Git hygiene

* `.gitignore` — added `*.duckdb`, `*.duckdb.wal`, raw CSV exclusions

---

## [0.2.0] — Session 2 · May 2026

### Pipeline expansion

* `collect_market_snapshots.py` — expanded from AAPL-only to multi-ticker `TICKERS` list (`["AAPL", "INTC"]`)
* `collect_market_snapshots.py` — full options chain collection (all expiries, no slice limit)
* `option_metrics.py` — Black-Scholes Greeks with timezone-safe T calculation anchored to 4 PM expiry close
* `price_metrics.py` — HV_20 and HV_252 historical volatility, OHLC cleaning

### Database — Bronze → Silver → Gold

* `build_database.py` — Bronze ingestion with source file deduplication
* `build_silver.py` — Silver validation suite (nulls, duplicates, price logic, schema checks)
* Five Gold tables built:
  * `gold_latest_snapshot` — one row per contract joined to most recent price close, HV_20, HV_252
  * `gold_pcr` — put/call ratio by expiry and ticker aggregate (volume + OI)
  * `gold_iv_rank` — ATM IV rank and percentile across all historical snapshots
  * `gold_greeks_exposure` — net delta and gamma by strike and expiry (raw + notional dollars)

---

## [0.1.0] — Session 1 · May 2026

### Initial setup

* Repo initialized with Bronze → Silver → Gold medallion architecture
* `collect_market_snapshots.py` — initial AAPL-only collector via yfinance
* LaunchAgent configured to fire at 16:15 Monday–Friday
* `data/raw/price/` and `data/raw/options/` directories established
* DuckDB chosen as the local warehouse (`appl_catalyst.duckdb`)
* `notebooks/01_yfinance_data_check.ipynb` — initial data exploration
