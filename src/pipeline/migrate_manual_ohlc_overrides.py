# ──────────────────────────────────────────────────────────────────────────────
# migrate_manual_ohlc_overrides.py
# One-time migration: recreate manual_ohlc_overrides with PRIMARY KEY constraint
#
# Run once on the droplet:
#   docker exec catalyst_dashboard python src/pipeline/migrate_manual_ohlc_overrides.py
#
# Safe to run even if table doesn't exist yet — CREATE TABLE IF NOT EXISTS handles it
# Safe to run if table has data — existing rows are copied to new table before drop
# ──────────────────────────────────────────────────────────────────────────────
import os
import sys
from pathlib import Path

import duckdb

## Resolve DB path relative to this file — works regardless of where script is called from
BASE    = Path(__file__).parent.parent.parent         ## repo root
DB_PATH = BASE / "appl_catalyst.duckdb"               ## same path utils.py uses

print(f"Connecting to: {DB_PATH}")
con = duckdb.connect(str(DB_PATH))                    ## read-write connection

## Step 1 — check if old table exists
tables = con.execute("SHOW TABLES").df()["name"].tolist()
print(f"Existing tables: {tables}")

if "manual_ohlc_overrides" not in tables:
    ## Table doesn't exist yet — create it fresh with PRIMARY KEY
    print("Table not found — creating fresh with PRIMARY KEY...")
    con.execute("""
        CREATE TABLE manual_ohlc_overrides (
            symbol  VARCHAR,                          -- contract symbol e.g. AAPL260918C00220000
            date    DATE,                             -- trading date of the override
            high    DOUBLE,                           -- user-entered intraday high
            low     DOUBLE,                           -- user-entered intraday low
            PRIMARY KEY (symbol, date)                -- enforces one row per contract per day
        )
    """)
    print("Done — table created.")

else:
    ## Table exists — copy data, drop old, recreate with PRIMARY KEY, restore data
    print("Table found — migrating...")

    ## Step 2 — copy existing rows into a temp table
    con.execute("""
        CREATE TABLE manual_ohlc_overrides_backup AS
        SELECT * FROM manual_ohlc_overrides
    """)
    row_count = con.execute("SELECT COUNT(*) FROM manual_ohlc_overrides_backup").fetchone()[0]
    print(f"Backed up {row_count} rows to manual_ohlc_overrides_backup")

    ## Step 3 — drop old table (no PRIMARY KEY)
    con.execute("DROP TABLE manual_ohlc_overrides")
    print("Dropped old table")

    ## Step 4 — recreate with PRIMARY KEY
    con.execute("""
        CREATE TABLE manual_ohlc_overrides (
            symbol  VARCHAR,
            date    DATE,
            high    DOUBLE,
            low     DOUBLE,
            PRIMARY KEY (symbol, date)
        )
    """)
    print("Created new table with PRIMARY KEY")

    ## Step 5 — restore rows — DISTINCT ON keeps latest row if duplicates existed in old table
    con.execute("""
        INSERT INTO manual_ohlc_overrides
        SELECT DISTINCT ON (symbol, date) symbol, date, high, low
        FROM manual_ohlc_overrides_backup
    """)
    restored = con.execute("SELECT COUNT(*) FROM manual_ohlc_overrides").fetchone()[0]
    print(f"Restored {restored} rows")

    ## Step 6 — drop backup table
    con.execute("DROP TABLE manual_ohlc_overrides_backup")
    print("Dropped backup table")

con.close()
print("Migration complete — manual_ohlc_overrides now has PRIMARY KEY (symbol, date)")
