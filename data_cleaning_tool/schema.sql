-- =====================================================================
-- BDSA retail sales database schema for Neon (PostgreSQL)
-- Run once:  psql "$NEON_CONNECTION_STRING" -f schema.sql
-- =====================================================================

-- ---------------------------------------------------------------------
-- Fact table: one row per BDSA product/attribute/month observation.
-- Column order matches the CSV produced by clean_bdsa.py exactly,
-- so \copy works with no column list.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bdsa_sales (
    period_month        DATE,
    state               TEXT,
    category_l1         TEXT,
    category_l2         TEXT,
    category_l3         TEXT,
    category_l4         TEXT,
    category_l5         TEXT,
    brand               TEXT,
    product             TEXT,
    pack_size           TEXT,
    infusion_type       TEXT,
    phenotype           TEXT,
    strain              TEXT,
    is_live_extract     TEXT,
    mood_effect         TEXT,
    cannabinoid_mix     TEXT,
    sugar_free          TEXT,
    fast_acting         TEXT,
    flavor              TEXT,
    total_item_weight   TEXT,
    items_per_pack      NUMERIC(12,2),
    pct_thc_potency     NUMERIC(8,4),
    total_thc_mg        NUMERIC(12,2),
    total_cbd_mg        NUMERIC(12,2),
    total_retail_sales  NUMERIC(16,4),
    total_units         NUMERIC(16,4),
    original_list_price NUMERIC(12,4),
    source_file         TEXT,
    period_year         INT,
    is_suppressed       BOOLEAN DEFAULT FALSE
);

-- ---------------------------------------------------------------------
-- Indexes tuned for the chatbot/API query patterns:
-- "state + time window" is in almost every query; brand and category
-- are the most common filters/groupings on top of that.
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_sales_state_month
    ON bdsa_sales (state, period_month);
CREATE INDEX IF NOT EXISTS idx_sales_brand
    ON bdsa_sales (brand);
CREATE INDEX IF NOT EXISTS idx_sales_category
    ON bdsa_sales (category_l1, category_l2, category_l3);
CREATE INDEX IF NOT EXISTS idx_sales_year
    ON bdsa_sales (period_year);

-- ---------------------------------------------------------------------
-- Rollup 1: brand x category x state x month.
-- Serves "top brands", brand trend, and market share questions without
-- touching the fact table. Suppressed rows are excluded.
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_brand_monthly AS
SELECT
    state,
    period_month,
    period_year,
    category_l1,
    category_l2,
    category_l3,
    brand,
    SUM(total_retail_sales)                  AS total_sales,
    SUM(total_units)                         AS total_units,
    COUNT(*)                                 AS sku_rows,
    SUM(total_retail_sales) / NULLIF(SUM(total_units), 0)
                                             AS avg_price_per_unit
FROM bdsa_sales
WHERE NOT is_suppressed
GROUP BY 1, 2, 3, 4, 5, 6, 7;

CREATE INDEX IF NOT EXISTS idx_mv_brand_monthly
    ON mv_brand_monthly (state, period_month, category_l1, brand);

-- ---------------------------------------------------------------------
-- Rollup 2: category x state x month (no brand).
-- Serves category sizing, trend, and pricing questions.
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_category_monthly AS
SELECT
    state,
    period_month,
    period_year,
    category_l1,
    category_l2,
    category_l3,
    SUM(total_retail_sales)                  AS total_sales,
    SUM(total_units)                         AS total_units,
    COUNT(DISTINCT brand)                    AS brand_count,
    SUM(total_retail_sales) / NULLIF(SUM(total_units), 0)
                                             AS avg_price_per_unit
FROM bdsa_sales
WHERE NOT is_suppressed
GROUP BY 1, 2, 3, 4, 5, 6;

CREATE INDEX IF NOT EXISTS idx_mv_category_monthly
    ON mv_category_monthly (state, period_month, category_l1);

-- ---------------------------------------------------------------------
-- After every data load, refresh the rollups:
--   REFRESH MATERIALIZED VIEW mv_brand_monthly;
--   REFRESH MATERIALIZED VIEW mv_category_monthly;
-- ---------------------------------------------------------------------
