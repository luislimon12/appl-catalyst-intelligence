## ── Base image ────────────────────────────────────────────────────────────────
## python:3.11-slim = official Python image built on Debian, stripped of extras
## "slim" removes compilers, docs, and test files — cuts image size from ~1GB to ~150MB
## We use 3.11 specifically because that's what runs on your Mac (avoids version mismatch bugs)
FROM python:3.11-slim

## ── Working directory ─────────────────────────────────────────────────────────
## All subsequent commands run from /app inside the container
## CRITICAL: must match how utils.py resolves the DB path:
##   DB_PATH = Path(__file__).parent.parent / "appl_catalyst.duckdb"
##   __file__ = /app/dashboard/utils.py → .parent.parent = /app/
## So the .duckdb volume must also mount to /app/appl_catalyst.duckdb
WORKDIR /app

## ── Install dependencies ──────────────────────────────────────────────────────
## Copy requirements.txt BEFORE copying the rest of the code
## Docker builds in layers — each instruction is a cached layer
## If only code changes (not requirements), Docker reuses the pip install layer
## Without this order, every code change would re-run pip install (~2 min)
COPY requirements.txt .

## --no-cache-dir: don't save pip's download cache inside the image
## saves ~50MB — we don't need the cache after install is done
RUN pip install --no-cache-dir -r requirements.txt

## ── Copy source code ──────────────────────────────────────────────────────────
## Copy dashboard/ — contains app.py, utils.py, and all pages/
## Copy src/ — contains the pipeline scripts (collect, build_database, build_silver)
## We do NOT copy appl_catalyst.duckdb here — it's mounted as a Docker volume
## Volume mount means the DB file lives on the host (droplet), not inside the image
## This lets you scp a new .duckdb to the server without rebuilding the container
COPY dashboard/ ./dashboard/
COPY src/ ./src/

## ── Network port ──────────────────────────────────────────────────────────────
## EXPOSE tells Docker this container listens on 8501
## This does NOT publish the port to the host — it's internal documentation
## Nginx reaches Streamlit on this port via the internal Docker network
## Port 8501 is never reachable from the internet directly
EXPOSE 8501

## ── Start command ─────────────────────────────────────────────────────────────
## CMD runs when the container starts — this launches Streamlit
## dashboard/app.py = the main Market Overview page (entry point for multipage app)
## --server.port=8501            match the EXPOSE port above
## --server.address=0.0.0.0     listen on all network interfaces inside the container
##                               required so Nginx can reach it from another container
##                               default (127.0.0.1) would only accept connections from localhost
## --server.headless=true        disables "open in browser" prompt — no browser on a server
## --server.fileWatcherType=none disables auto-reload on file change — not needed in production
##                               saves CPU and prevents unexpected restarts
CMD ["streamlit", "run", "dashboard/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--server.fileWatcherType=none"]
