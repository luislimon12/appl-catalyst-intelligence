# AAPL & INTC Catalyst Intelligence Dashboard

Options market intelligence dashboard for tracking IV rank, Put/Call ratio,
Gamma Exposure, and full options chain data for AAPL and INTC around
seasonal catalysts.

🌐 Live at https://catalyst.luislimon.dev

---

## Stack

Python · DuckDB · Streamlit · Docker · Nginx · DigitalOcean · Cloudflare

---

## How the data flows

yfinance snapshots → Bronze (raw) → Silver (cleaned) → Gold (analytics-ready)

Collected twice daily at market open and close via a scheduled pipeline.

---

## Database architecture

Three-tier Medallion pipeline backed by DuckDB:

**Bronze — raw ingestion**  
Append-only tables that store every snapshot exactly as collected from
yfinance. Nothing is deleted or transformed here. Acts as the source
of truth for replaying history.

**Silver — cleaned and validated**  
Deduplicates Bronze, filters bad data (ask < bid, null Greeks, invalid
prices), and computes derived fields like historical volatility (HV_20,
HV_252) and Black-Scholes Greeks. Fails loudly if the data doesn't pass
validation.

**Gold — analytics-ready**  
Pre-aggregated tables built for the dashboard to query directly:

- `gold_latest_snapshot` — one row per contract, joined to the most recent price close, HV_20, HV_252
- `gold_iv_rank` — ATM IV rank and percentile across all historical snapshots
- `gold_pcr` — put/call ratio by expiry and ticker (volume + OI)
- `gold_greeks_exposure` — net delta and gamma by strike and expiry

---

## Running locally

```bash
pip install -r requirements.txt
streamlit run dashboard/app.py
```

---

## Deployment

Runs on a DigitalOcean droplet behind Nginx with TLS. Both containers
managed by Docker Compose.

```bash
docker compose up -d
```
