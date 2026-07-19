#!/opt/anaconda3/bin/python3
# ──────────────────────────────────────────────────────────────────────────────
# build_database.py
# AAPL & INTC Catalyst Intelligence Pipeline — Bronze Ingestion
#
# Session 2 (May 2026): Initial Bronze ingestion with source file deduplication
# Session 3 (Jun 2026): No changes — called automatically by collect_market_snapshots.py
# ──────────────────────────────────────────────────────────────────────────────
import os
import glob
import duckdb


class DatabaseBuilder:
    def __init__(self, db_path="appl_catalyst.duckdb", data_dir="data/raw"):
        self.db_path = db_path
        self.data_dir = data_dir
        self.con = duckdb.connect(db_path)

    def create_schema(self):
        """Create Bronze layer tables only (Step 1)."""
        print("Creating Bronze tables...")

        # Bronze Price - raw CSV mirror, NO constraints
        self.con.execute("""
        CREATE TABLE IF NOT EXISTS bronze_price_raw (
            Date DATE,
            Open FLOAT,
            High FLOAT,
            Low FLOAT,
            Close FLOAT,
            Volume INTEGER,
            HV_20 FLOAT,
            HV_252 FLOAT,
            snapshot_time TIMESTAMP,
            snapshot_str VARCHAR,
            ticker VARCHAR,
            _source_file VARCHAR
        )""")

        # Bronze Options - raw CSV mirror, NO constraints
        self.con.execute("""
        CREATE TABLE IF NOT EXISTS bronze_options_raw (
            contractSymbol VARCHAR,
            expiry DATE,
            option_type VARCHAR,
            strike FLOAT,
            bid FLOAT,
            ask FLOAT,
            lastPrice FLOAT,
            volume INTEGER,
            openInterest INTEGER,
            impliedVolatility FLOAT,
            delta FLOAT,
            gamma FLOAT,
            theta FLOAT,
            vega FLOAT,
            inTheMoney BOOLEAN,
            snapshot_time TIMESTAMP,
            snapshot_str VARCHAR,
            ticker VARCHAR,
            _source_file VARCHAR
        )""")

        print("✅ Bronze schema created")

    def is_file_loaded(self, table_name, file_path):
        """
        Check whether a source file has already been loaded into a Bronze table.
        """
        result = self.con.execute(f"""
            SELECT COUNT(*)
            FROM {table_name}
            WHERE _source_file = ?
        """, [file_path]).fetchone()[0]

        return result > 0

    def load_bronze_price(self):
        """
        Load all raw price CSV files into the bronze_price_raw table.
        Skip files that were already loaded.
        """
        price_files = sorted(glob.glob(os.path.join(self.data_dir, "price", "*.csv")))

        if not price_files:
            print("No price CSV files found.")
            return

        print(f"Found {len(price_files)} price file(s).")

        for file_path in price_files:
            if self.is_file_loaded("bronze_price_raw", file_path):
                print(f"Skipping already loaded price file: {file_path}")
                continue

            print(f"Loading price file: {file_path}")

            self.con.execute(f"""
                INSERT INTO bronze_price_raw
                SELECT *,
                       '{file_path}' AS _source_file
                FROM read_csv_auto('{file_path}', header=True)
            """)

        print("✅ Price ingestion complete")

    def check_bronze_price(self):
        """
        Show row count and a sample of bronze_price_raw.
        """
        count = self.con.execute("""
            SELECT COUNT(*) FROM bronze_price_raw
        """).fetchone()[0]

        print(f"bronze_price_raw row count: {count}")

        sample = self.con.execute("""
            SELECT *
            FROM bronze_price_raw
            ORDER BY snapshot_time DESC
            LIMIT 5
        """).fetchall()

        print("Latest 5 rows:")
        for row in sample:
            print(row)

    def load_bronze_options(self):
        """
        Load all raw options CSV files into the bronze_options_raw table.
        Skip files that were already loaded.
        """
        option_files = sorted(glob.glob(os.path.join(self.data_dir, "options", "*.csv")))

        if not option_files:
            print("No options CSV files found.")
            return

        print(f"Found {len(option_files)} options file(s).")

        for file_path in option_files:
            if self.is_file_loaded("bronze_options_raw", file_path):
                print(f"Skipping already loaded options file: {file_path}")
                continue

            print(f"Loading options file: {file_path}")

            self.con.execute(f"""
                INSERT INTO bronze_options_raw
                SELECT
                    contractSymbol, expiry, option_type, strike,
                    bid, ask, lastPrice, volume, openInterest,
                    impliedVolatility, delta, gamma, theta, vega,
                    -- inTheMoney arrives as 'True'/'False' OR '1.0'/'0.0' depending on pandas version
                    -- types={{'inTheMoney':'VARCHAR'}} forces DuckDB to read it as a string first
                    -- CASE then normalises both formats into a proper BOOLEAN
                    CASE
                        WHEN LOWER(inTheMoney) IN ('true',  '1', '1.0') THEN TRUE
                        WHEN LOWER(inTheMoney) IN ('false', '0', '0.0') THEN FALSE
                        ELSE NULL
                    END AS inTheMoney,
                    snapshot_time, snapshot_str, ticker,
                    '{file_path}' AS _source_file
                FROM read_csv_auto('{file_path}', header=True, types={{'inTheMoney': 'VARCHAR'}})
            """)

        print("✅ Options ingestion complete")

    def check_bronze_options(self):
        """
        Show row count and a sample of bronze_options_raw.
        """
        count = self.con.execute("""
            SELECT COUNT(*) FROM bronze_options_raw
        """).fetchone()[0]

        print(f"bronze_options_raw row count: {count}")

        sample = self.con.execute("""
            SELECT *
            FROM bronze_options_raw
            ORDER BY snapshot_time DESC
            LIMIT 5
        """).fetchall()

        print("Latest 5 options rows:")
        for row in sample:
            print(row)

    def close(self):
        """Close the DuckDB connection."""
        self.con.close()


if __name__ == "__main__":
    builder = DatabaseBuilder()
    builder.create_schema()
    builder.load_bronze_price()
    builder.check_bronze_price()
    builder.load_bronze_options()
    builder.check_bronze_options()
    builder.close()
