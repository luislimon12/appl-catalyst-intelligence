import duckdb
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH      = PROJECT_ROOT / "appl_catalyst.duckdb"

con = duckdb.connect(str(DB_PATH))

try:

    ## ── SILVER: PRICE ────────────────────────────────────────────────────────

    con.execute("""
    CREATE OR REPLACE TABLE silver_price_daily AS
    WITH ranked AS (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY ticker, Date
                   ORDER BY snapshot_time DESC
               ) AS rn
        FROM bronze_price_raw
        -- Filter null critical fields during Silver promotion so spot price lookups never return NULL
        WHERE ticker IS NOT NULL AND Date IS NOT NULL AND Close IS NOT NULL AND snapshot_time IS NOT NULL
    )
    SELECT
        Date,
        ticker,
        Open,
        High,
        Low,
        Close,
        Volume,
        HV_20,
        HV_252,
        snapshot_time,
        snapshot_str
    FROM ranked
    WHERE rn = 1
    """)

    count                = con.execute("SELECT COUNT(*) FROM silver_price_daily").fetchone()[0]
    duplicate_count      = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT ticker, Date, COUNT(*) AS n
            FROM silver_price_daily
            GROUP BY ticker, Date
            HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    null_count           = con.execute("""
        SELECT COUNT(*) FROM silver_price_daily
        WHERE ticker IS NULL OR Date IS NULL OR Close IS NULL OR snapshot_time IS NULL
    """).fetchone()[0]
    invalid_price_count  = con.execute("""
        SELECT COUNT(*) FROM silver_price_daily
        WHERE Open <= 0 OR High <= 0 OR Low <= 0 OR Close <= 0 OR Volume < 0
    """).fetchone()[0]
    price_logic_count    = con.execute("""
        SELECT COUNT(*) FROM silver_price_daily
        WHERE High < Low OR High < Open OR High < Close OR Low > Open OR Low > Close
    """).fetchone()[0]
    invalid_hv_count     = con.execute("""
        SELECT COUNT(*) FROM silver_price_daily
        WHERE HV_20 < 0 OR HV_252 < 0
    """).fetchone()[0]
    bronze_distinct_keys = con.execute("""
        SELECT COUNT(*) FROM (SELECT DISTINCT ticker, Date FROM bronze_price_raw)
    """).fetchone()[0]

    print("rows:",                  count)
    print("bronze_distinct_keys:",  bronze_distinct_keys)
    print("duplicate_keys:",        duplicate_count)
    print("null_critical_fields:",  null_count)
    print("invalid_price_values:",  invalid_price_count)
    print("invalid_price_logic:",   price_logic_count)
    print("invalid_hv_values:",     invalid_hv_count)

    assert duplicate_count     == 0, "Duplicate ticker/date keys found"
    assert invalid_price_count == 0, "Invalid numeric price values found"
    assert price_logic_count   == 0, "Price logic violations found"
    assert invalid_hv_count    == 0, "Invalid volatility values found"
    # Null rows filtered at source — Silver count may be slightly below Bronze distinct keys
    if null_count > 0:
        print(f"WARNING: {null_count} null rows filtered from bronze_price_raw during Silver promotion")
    if count != bronze_distinct_keys:
        print(f"WARNING: Silver rows ({count}) != Bronze distinct keys ({bronze_distinct_keys}) — {bronze_distinct_keys - count} null rows dropped")

    print("silver_price_daily validation passed")

    ## ── SILVER: OPTIONS (LATEST) ─────────────────────────────────────────────

    con.execute("""
    CREATE OR REPLACE TABLE silver_options_latest AS
    WITH ranked AS (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY contractSymbol
                   ORDER BY snapshot_time DESC
               ) AS rn
        FROM bronze_options_raw
        -- Filter out bad bid/ask data from source before promoting to Silver
        WHERE bid IS NULL OR ask IS NULL OR ask >= bid
    )
    SELECT
        contractSymbol,
        expiry,
        option_type,
        strike,
        bid,
        ask,
        lastPrice,
        volume,
        openInterest,
        impliedVolatility,
        delta,
        gamma,
        theta,
        vega,
        inTheMoney,
        snapshot_time,
        snapshot_str,
        ticker,
        _source_file
    FROM ranked
    WHERE rn = 1
    """)

    options_count                 = con.execute("SELECT COUNT(*) FROM silver_options_latest").fetchone()[0]
    options_duplicate_count       = con.execute("""
        SELECT COUNT(*) FROM (
            SELECT contractSymbol, COUNT(*) AS n
            FROM silver_options_latest
            GROUP BY contractSymbol
            HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    options_null_count            = con.execute("""
        SELECT COUNT(*) FROM silver_options_latest
        WHERE contractSymbol IS NULL OR expiry IS NULL OR option_type IS NULL
           OR strike IS NULL OR snapshot_time IS NULL OR ticker IS NULL
    """).fetchone()[0]
    options_bad_type_count        = con.execute("""
        SELECT COUNT(*) FROM silver_options_latest
        WHERE option_type NOT IN ('call', 'put')
    """).fetchone()[0]
    options_invalid_numeric_count = con.execute("""
        SELECT COUNT(*) FROM silver_options_latest
        WHERE strike <= 0
           OR bid < 0 OR ask < 0 OR lastPrice < 0
           OR volume < 0 OR openInterest < 0
           OR impliedVolatility < 0
           OR gamma < 0 OR vega < 0
    """).fetchone()[0]
    options_bad_market_count      = con.execute("""
        SELECT COUNT(*) FROM silver_options_latest
        WHERE bid IS NOT NULL AND ask IS NOT NULL AND ask < bid
    """).fetchone()[0]

    print("options_rows:",                   options_count)
    print("options_duplicate_contracts:",    options_duplicate_count)
    print("options_null_critical_fields:",   options_null_count)
    print("options_bad_type:",               options_bad_type_count)
    print("options_invalid_numeric_values:", options_invalid_numeric_count)
    print("options_ask_below_bid:",          options_bad_market_count)

    assert options_duplicate_count        == 0, "Duplicate contractSymbol values found"
    assert options_null_count             == 0, "Critical nulls found in silver_options_latest"
    assert options_bad_type_count         == 0, "Invalid option_type values found"
    assert options_invalid_numeric_count  == 0, "Invalid numeric values found in silver_options_latest"
    if options_bad_market_count > 0:
        print(f"WARNING: {options_bad_market_count} rows with ask < bid filtered during Silver promotion")

    print("silver_options_latest validation passed")

    ## ── GOLD: LATEST SNAPSHOT ────────────────────────────────────────────────

    con.execute("""
    CREATE OR REPLACE TABLE gold_latest_snapshot AS
    SELECT
        o.contractSymbol,
        o.expiry,
        o.option_type,
        o.strike,
        o.bid,
        o.ask,
        o.lastPrice         AS option_last,
        o.volume,
        o.openInterest,
        o.impliedVolatility AS iv,
        o.delta,
        o.gamma,
        o.theta,
        o.vega,
        o.inTheMoney,
        o.snapshot_time     AS options_snapshot_time,
        o.ticker,
        p.Date              AS price_date,
        p.Close             AS price_close,
        p.HV_20,
        p.HV_252
    FROM silver_options_latest o
    LEFT JOIN silver_price_daily p
           ON p.ticker = o.ticker
          AND p.Date   = (
              SELECT MAX(Date)
              FROM silver_price_daily
              WHERE ticker = o.ticker
          )
    """)

    gold_count     = con.execute("SELECT COUNT(*) FROM gold_latest_snapshot").fetchone()[0]
    gold_contracts = con.execute("SELECT COUNT(DISTINCT contractSymbol) FROM gold_latest_snapshot").fetchone()[0]

    print("gold_latest_snapshot_rows:", gold_count)
    print("gold_distinct_contracts:",   gold_contracts)

    assert gold_count     == options_count, \
        f"Gold row count ({gold_count}) does not match silver_options_latest ({options_count})"
    assert gold_contracts == options_count, \
        f"Gold distinct contracts ({gold_contracts}) does not match silver_options_latest ({options_count})"

    print("gold_latest_snapshot validation passed")

    ## ── GOLD: PUT/CALL RATIO ─────────────────────────────────────────────────

    con.execute("""
    CREATE OR REPLACE TABLE gold_pcr AS

    WITH by_expiry AS (
        SELECT
            ticker,
            expiry,
            -- volume PCR: sum put volume / sum call volume
            SUM(CASE WHEN option_type = 'put'  THEN volume ELSE 0 END)         AS put_volume,
            SUM(CASE WHEN option_type = 'call' THEN volume ELSE 0 END)         AS call_volume,
            ROUND(
                SUM(CASE WHEN option_type = 'put'  THEN volume ELSE 0 END)::FLOAT
              / NULLIF(SUM(CASE WHEN option_type = 'call' THEN volume ELSE 0 END), 0),
            4)                                                                  AS pcr_volume,
            -- OI PCR: sum put OI / sum call OI
            SUM(CASE WHEN option_type = 'put'  THEN openInterest ELSE 0 END)   AS put_oi,
            SUM(CASE WHEN option_type = 'call' THEN openInterest ELSE 0 END)   AS call_oi,
            ROUND(
                SUM(CASE WHEN option_type = 'put'  THEN openInterest ELSE 0 END)::FLOAT
              / NULLIF(SUM(CASE WHEN option_type = 'call' THEN openInterest ELSE 0 END), 0),
            4)                                                                  AS pcr_oi,
            MAX(snapshot_time)                                                  AS snapshot_time,
            MAX(snapshot_str)                                                   AS snapshot_str
        FROM silver_options_latest
        GROUP BY ticker, expiry
    ),

    -- ticker-level aggregate: label expiry as 'ALL' to keep one table
    ticker_level AS (
        SELECT
            ticker,
            'ALL'                                                               AS expiry,
            SUM(put_volume)                                                     AS put_volume,
            SUM(call_volume)                                                    AS call_volume,
            ROUND(SUM(put_volume)::FLOAT / NULLIF(SUM(call_volume), 0), 4)     AS pcr_volume,
            SUM(put_oi)                                                         AS put_oi,
            SUM(call_oi)                                                        AS call_oi,
            ROUND(SUM(put_oi)::FLOAT / NULLIF(SUM(call_oi), 0), 4)             AS pcr_oi,
            MAX(snapshot_time)                                                  AS snapshot_time,
            MAX(snapshot_str)                                                   AS snapshot_str
        FROM by_expiry
        GROUP BY ticker
    )

    SELECT * FROM by_expiry
    UNION ALL
    SELECT * FROM ticker_level
    ORDER BY ticker, expiry
    """)

    pcr_count        = con.execute("SELECT COUNT(*) FROM gold_pcr").fetchone()[0]
    pcr_null_ratio   = con.execute("""
        SELECT COUNT(*) FROM gold_pcr
        WHERE expiry != 'ALL'
          AND pcr_volume IS NULL
          AND pcr_oi IS NULL
    """).fetchone()[0]
    pcr_ticker_check = con.execute("""
        SELECT COUNT(*) FROM gold_pcr WHERE expiry = 'ALL'
    """).fetchone()[0]

    print("pcr_rows:",            pcr_count)
    print("pcr_both_null_rows:",  pcr_null_ratio)
    print("pcr_ticker_agg_rows:", pcr_ticker_check)

    assert pcr_ticker_check >= 1, "No ticker-level PCR aggregate found"
    if pcr_null_ratio > 0:
        print(f"WARNING: {pcr_null_ratio} expiry rows have null pcr_volume and pcr_oi — check sparse expiries")

    print("gold_pcr validation passed")

    ## ── GOLD: IV RANK / IV PERCENTILE ────────────────────────────────────────

    con.execute("""
    CREATE OR REPLACE TABLE gold_iv_rank AS

    WITH atm_iv_per_snapshot AS (
        -- average IV of near-ATM contracts per snapshot
        -- ATM defined as strikes within 2% of spot
        SELECT
            b.ticker,
            b.snapshot_str,
            b.snapshot_time,
            AVG(b.impliedVolatility) AS atm_iv
        FROM bronze_options_raw b
        INNER JOIN (
            -- spot price for each snapshot using the closest price date
            SELECT DISTINCT
                o.ticker,
                o.snapshot_str,
                p.Close AS spot
            FROM bronze_options_raw o
            LEFT JOIN silver_price_daily p
                   ON p.ticker = o.ticker
                  AND p.Date   = (
                      SELECT MAX(Date)
                      FROM silver_price_daily
                      WHERE ticker = o.ticker
                  )
        ) snap ON snap.ticker = b.ticker
              AND snap.snapshot_str = b.snapshot_str
        WHERE b.impliedVolatility > 0
          AND b.impliedVolatility < 5
          AND b.strike BETWEEN snap.spot * 0.98
                           AND snap.spot * 1.02
          -- Jun 17 2026: exclude overnight/pre-market snapshots from IV rank calculation
          -- Midnight runs return IV near 0% (bid=ask=0, market closed) which corrupts gold_iv_rank
          -- Only use snapshots collected between 9 AM and 6 PM (real market hours)
          AND HOUR(b.snapshot_time) BETWEEN 9 AND 18
        GROUP BY b.ticker, b.snapshot_str, b.snapshot_time
    ),

    iv_stats AS (
        -- min, max, and current IV across all snapshots
        SELECT
            ticker,
            MIN(atm_iv)                                         AS iv_min,
            MAX(atm_iv)                                         AS iv_max,
            MAX(atm_iv) FILTER (
                WHERE snapshot_time = (
                    SELECT MAX(snapshot_time)
                    FROM atm_iv_per_snapshot AS inner_snap
                    WHERE inner_snap.ticker = atm_iv_per_snapshot.ticker
                )
            )                                                   AS iv_current,
            COUNT(*)                                            AS snapshot_count
        FROM atm_iv_per_snapshot
        GROUP BY ticker
    ),

    iv_percentile AS (
        -- fraction of snapshots with IV below current
        SELECT
            a.ticker,
            ROUND(
                COUNT(*) FILTER (WHERE a.atm_iv < s.iv_current)::FLOAT
              / NULLIF(COUNT(*), 0),
            4)                                                  AS iv_percentile
        FROM atm_iv_per_snapshot a
        JOIN iv_stats s ON s.ticker = a.ticker
        GROUP BY a.ticker
    ),

    iv_zscore AS (
        -- Z-Score = (current IV - mean IV) / standard deviation across all snapshots
        -- measures how many std deviations today's IV is from its own historical average
        -- > +2.0 = IV is statistically expensive = premium selling zone
        -- < -2.0 = IV is statistically cheap = good for buying options / LEAPS
        -- STDDEV_POP = population std dev (uses all snapshots, not a sample)
        -- NULLIF(..., 0) prevents division by zero when only one snapshot exists
        SELECT
            a.ticker,
            ROUND(
                (s.iv_current - AVG(a.atm_iv))          -- distance from historical mean
              / NULLIF(STDDEV_POP(a.atm_iv), 0),         -- divided by population std dev
            4)                                           AS iv_zscore
        FROM atm_iv_per_snapshot a
        JOIN iv_stats s ON s.ticker = a.ticker           -- join to get iv_current
        GROUP BY a.ticker, s.iv_current                  -- group by ticker + current IV
    )

    SELECT
        s.ticker,
        ROUND(s.iv_current, 4)                                  AS iv_current,
        ROUND(s.iv_min, 4)                                      AS iv_min,
        ROUND(s.iv_max, 4)                                      AS iv_max,
        ROUND(
            (s.iv_current - s.iv_min)::FLOAT
          / NULLIF(s.iv_max - s.iv_min, 0),
        4)                                                       AS iv_rank,
        p.iv_percentile,
        z.iv_zscore,                                             -- Jul 2026: added Z-score column
        s.snapshot_count,
        (SELECT MAX(snapshot_time) FROM atm_iv_per_snapshot
         WHERE ticker = s.ticker)                                AS snapshot_time
    FROM iv_stats s
    JOIN iv_percentile p ON p.ticker = s.ticker
    JOIN iv_zscore     z ON z.ticker = s.ticker                  -- join Z-score CTE
    """)

    iv_count       = con.execute("SELECT COUNT(*) FROM gold_iv_rank").fetchone()[0]
    iv_null_check  = con.execute("""
        SELECT COUNT(*) FROM gold_iv_rank
        WHERE iv_current IS NULL OR iv_rank IS NULL OR iv_percentile IS NULL
    """).fetchone()[0]
    iv_range_check = con.execute("""
        SELECT COUNT(*) FROM gold_iv_rank
        WHERE iv_rank < 0 OR iv_rank > 1
           OR iv_percentile < 0 OR iv_percentile > 1
    """).fetchone()[0]

    print("iv_rank_rows:",    iv_count)
    print("iv_null_fields:",  iv_null_check)
    print("iv_out_of_range:", iv_range_check)

    assert iv_count       >= 1, "No rows in gold_iv_rank — check that silver_price_daily has valid Close values"
    assert iv_null_check  == 0, "Null IV rank or percentile values found"
    assert iv_range_check == 0, "IV rank or percentile out of 0-1 range"

    # Guard fetchone() — only print if table has rows
    if iv_count >= 1:
        print("snapshot_count:", con.execute("SELECT snapshot_count FROM gold_iv_rank").fetchone()[0])
        print("iv_current:",     con.execute("SELECT iv_current FROM gold_iv_rank").fetchone()[0])
        print("iv_rank:",        con.execute("SELECT iv_rank FROM gold_iv_rank").fetchone()[0])
        print("iv_percentile:",  con.execute("SELECT iv_percentile FROM gold_iv_rank").fetchone()[0])

    print("gold_iv_rank validation passed")

    ## ── GOLD: GREEKS EXPOSURE ────────────────────────────────────────────────

    con.execute("""
    CREATE OR REPLACE TABLE gold_greeks_exposure AS

    SELECT
        ticker,
        expiry,
        strike,

        -- raw delta: sum of (delta * OI) per side and net
        ROUND(SUM(CASE WHEN option_type = 'call' THEN delta * openInterest ELSE 0 END), 4)  AS call_delta,
        ROUND(SUM(CASE WHEN option_type = 'put'  THEN delta * openInterest ELSE 0 END), 4)  AS put_delta,
        ROUND(SUM(delta * openInterest), 4)                                                  AS net_delta,

        -- raw gamma: sum of (gamma * OI) per side and net
        ROUND(SUM(CASE WHEN option_type = 'call' THEN gamma * openInterest ELSE 0 END), 4)  AS call_gamma,
        ROUND(SUM(CASE WHEN option_type = 'put'  THEN gamma * openInterest ELSE 0 END), 4)  AS put_gamma,
        ROUND(SUM(gamma * openInterest), 4)                                                  AS net_gamma,

        -- notional delta: scaled to dollars (OI * strike * 100 shares per contract)
        ROUND(SUM(CASE WHEN option_type = 'call' THEN delta * openInterest * strike * 100 ELSE 0 END), 2)  AS call_delta_notional,
        ROUND(SUM(CASE WHEN option_type = 'put'  THEN delta * openInterest * strike * 100 ELSE 0 END), 2)  AS put_delta_notional,
        ROUND(SUM(delta * openInterest * strike * 100), 2)                                                  AS net_delta_notional,

        -- notional gamma: scaled to dollars
        ROUND(SUM(CASE WHEN option_type = 'call' THEN gamma * openInterest * strike * 100 ELSE 0 END), 2)  AS call_gamma_notional,
        ROUND(SUM(CASE WHEN option_type = 'put'  THEN gamma * openInterest * strike * 100 ELSE 0 END), 2)  AS put_gamma_notional,
        ROUND(SUM(gamma * openInterest * strike * 100), 2)                                                  AS net_gamma_notional,

        MAX(snapshot_time)  AS snapshot_time,
        MAX(snapshot_str)   AS snapshot_str

    FROM silver_options_latest
    WHERE delta IS NOT NULL
      AND gamma IS NOT NULL
      AND openInterest IS NOT NULL
    GROUP BY ticker, expiry, strike
    ORDER BY ticker, expiry, strike
    """)

    gex_count        = con.execute("SELECT COUNT(*) FROM gold_greeks_exposure").fetchone()[0]
    gex_null_check   = con.execute("""
        SELECT COUNT(*) FROM gold_greeks_exposure
        WHERE net_delta IS NULL OR net_gamma IS NULL
           OR net_delta_notional IS NULL OR net_gamma_notional IS NULL
    """).fetchone()[0]
    gex_strike_check = con.execute("""
        SELECT COUNT(*) FROM gold_greeks_exposure WHERE strike <= 0
    """).fetchone()[0]

    print("gex_rows:",         gex_count)
    print("gex_null_fields:",  gex_null_check)
    print("gex_bad_strikes:",  gex_strike_check)

    assert gex_count        >= 1, "No rows in gold_greeks_exposure"
    assert gex_null_check   == 0, "Null greeks exposure values found"
    assert gex_strike_check == 0, "Invalid strike values found"

    print("gold_greeks_exposure validation passed")


finally:
    con.close()