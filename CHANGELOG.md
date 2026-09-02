# Changelog — AAPL & INTC Catalyst Intelligence Dashboard

All significant changes documented in reverse chronological order.

---

## [0.9.1] — Session 9 continued · September 2026

### Optimization — prev_iv moved from Bronze runtime scan to Gold layer

* `build_silver.py` — added `prev_iv_cte` to the `gold_iv_rank` query. Uses `ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY MAX(snapshot_time) DESC)` to rank market-hours snapshots newest to oldest, selects the second most recent (`rn=2`), and averages its call IV. Result stored as `prev_iv` column in `gold_iv_rank`.
* `app.py` — removed 13-line `prev_df` Bronze subquery from `render_iv_cards()`. Replaced with `float(row["prev_iv"])` read from the Gold row already in memory. Eliminates a full 467k-row `bronze_options_raw` scan on every dashboard page load.
* `app.py` — uses `pandas.notna(row.get("prev_iv"))` guard so `None` is handled gracefully when only one snapshot exists (e.g. first run of the day).

### Bug fix — `Timestamp.now()` UTC offset in Options Chain

* `2_Options_Chain.py` — catalyst DTE calculation used `pandas.Timestamp.now()` which returns UTC on the droplet. After 8 PM EDT this made `now()` be already tomorrow in UTC, causing DTE to show one day short. Fixed to `pandas.Timestamp.today()` which returns midnight of the local calendar date regardless of timezone.

---

## [0.9.0] — Session 9 · September 2026

### Bug fix — gold_iv_rank using wrong historical spot price

* `build_silver.py` — `gold_iv_rank` CTE was joining every historical snapshot to `MAX(Date)` spot price (today's closing price ~$325). Snapshots from May 2024 when AAPL was at $171 were therefore looking for ATM strikes in the $318–$331 range — matching deep OTM contracts with near-zero IV. This poisoned the entire iv_rank baseline, causing IV to display as 0.7% when real IV was ~27%.
* Fix: changed spot join from `p.Date = (SELECT MAX(Date) ...)` to `p.Date = DATE(o.snapshot_time)` so each snapshot uses its own historical closing price to determine ATM strikes.
* Also raised IV floor filter from `impliedVolatility > 0` to `impliedVolatility > 0.05` (5%) as a permanent safeguard against stale pre-market snapshots returning near-zero IV.
* After fix: iv_current = 58.4%, iv_rank = 40.6%, snapshot_count = 128 (was 0.7%, poisoned baseline, 95 snapshots).

### Feature — Contract Tracker 2×2 small multiples grid

* `3_Contract_Tracker.py` — replaced single chart + overlay radio (Price+IV / Delta / Theta / Gamma) with a 2×2 grid showing all four metrics simultaneously. Panels: Price ($), IV %, Δ Delta, Θ Theta. All panels share x-axis so pan/zoom moves all four in sync. Catalyst vlines drawn on all four panels.
* Removed overlay radio button — no longer needed.

### Feature — Step chart for all line traces

* `3_Contract_Tracker.py` — all line chart traces now use `shape="hv"` (step chart). Flat line between snapshots is honest about the fact that we only have 2 data points per day. Marker size increased from 5 to 8 for all traces so each actual snapshot is clearly visible.

---

## [0.8.0] — Session 8 · August 2026

### Bug fix — UTC timestamp hour filters in Contract Tracker

* `3_Contract_Tracker.py` — all `HOUR(snapshot_time) BETWEEN 9 AND 18` filters extended to `BETWEEN 9 AND 23`. The pipeline previously ran on the Mac (EST timestamps), so the 4:15 PM snapshot was stored as hour 16. After moving to the droplet (UTC), it is stored as hour 21, which the old upper bound of 18 excluded. Greeks and IV were being read from the 9:35 AM snapshot only, which often shows near-zero values for deep OTM contracts.
* `3_Contract_Tracker.py` — `get_ohlc_data` morning/afternoon split changed from `hour < 12 / >= 12` to `hour < 17 / >= 17`. The 9:35 AM EST snapshot is hour 13 UTC — the old threshold put it in the afternoon bucket alongside the 4:15 PM snapshot (hour 21 UTC), causing open to always equal close. Now morning correctly captures hour 13 and afternoon captures hour 21.
* `3_Contract_Tracker.py` — fixed remaining `BETWEEN 9 AND 18` in the correlated dedup subquery inside `get_contract_history`, missed in the initial pass.
* `3_Contract_Tracker.py` — removed Python `##` comment from inside a triple-quoted SQL string; DuckDB received it as literal SQL text and threw a parser error (`syntax error at or near "#"`). Comments inside SQL strings must use `--` (SQL syntax) or be placed outside the string.

---

## [0.7.0] — Session 7 · August 2026

### Pipeline — moved to droplet cron job

* Diagnosed data collection gap (Aug 19–24): Mac LaunchAgent only fires when the Mac is on; droplet runs 24/7
* Removed dependency on Mac for pipeline execution
* Added two cron entries on the droplet running as root:
  * `35 13 * * 1-5` — 9:35 AM EST (13:35 UTC) — market open snapshot
  * `15 21 * * 1-5` — 4:15 PM EST (21:15 UTC) — market close snapshot
* Both entries run `docker exec catalyst_dashboard python src/pipeline/collect_market_snapshots.py` inside the running container

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
