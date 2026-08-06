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
