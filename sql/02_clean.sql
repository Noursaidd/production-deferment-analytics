-- ============================================================
-- 02 · CLEAN LAYER  (all cleaning done in SQL, every rule commented)
-- ============================================================

DROP TABLE IF EXISTS well;
CREATE TABLE well AS
SELECT UPPER(TRIM(well_id)) AS well_id, field, lift_type, DATE(online_date) AS online_date
FROM raw_wells;

-- Daily production
--  rule 1: standardise IDs (' p-004 ' -> 'P-004')
--  rule 2: de-duplicate (pump, day) keeping one row -> ROW_NUMBER()
--  rule 3: hours_on outside 0..24 is impossible -> cap at 24 and flag
--  rule 4: negative volumes are sentinel/error values -> NULL and flag
DROP TABLE IF EXISTS daily_production;
CREATE TABLE daily_production AS
WITH std AS (
    SELECT UPPER(TRIM(well_id)) AS well_id,
           DATE(prod_date)      AS prod_date,
           hours_on, oil_bbl, gas_mscf, water_bbl
    FROM raw_daily_production
), ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY well_id, prod_date ORDER BY hours_on DESC) AS rn
    FROM std
)
SELECT well_id, prod_date,
       MIN(MAX(hours_on, 0), 24)                      AS hours_on,
       CASE WHEN oil_bbl   < 0 THEN NULL ELSE oil_bbl   END AS oil_bbl,
       CASE WHEN gas_mscf  < 0 THEN NULL ELSE gas_mscf  END AS gas_mscf,
       CASE WHEN water_bbl < 0 THEN NULL ELSE water_bbl END AS water_bbl,
       (hours_on > 24 OR hours_on < 0)                 AS flag_hours_fixed,
       (oil_bbl < 0)                                   AS flag_oil_invalid
FROM ranked
WHERE rn = 1;
CREATE UNIQUE INDEX ux_prod ON daily_production(well_id, prod_date);

-- Downtime log: map free-text reasons to a standard cause list (CASE + LIKE)
DROP TABLE IF EXISTS downtime_log;
CREATE TABLE downtime_log AS
SELECT UPPER(TRIM(well_id)) AS well_id,
       start_time, end_time,
       ROUND((JULIANDAY(end_time) - JULIANDAY(start_time)) * 24, 1) AS duration_h,
       reason AS reason_raw,
       CASE
         WHEN LOWER(reason) LIKE '%esp%' OR LOWER(reason) LIKE '%pump%'        THEN 'ESP trip'
         WHEN LOWER(reason) LIKE '%pwr%' OR LOWER(reason) LIKE '%power%'        THEN 'Power failure'
         WHEN LOWER(reason) LIKE '%leak%'                                        THEN 'Flowline leak'
         WHEN LOWER(reason) LIKE '%facility%' OR LOWER(reason) LIKE '%separator%'
           OR LOWER(reason) LIKE '%plant%'    OR LOWER(reason) LIKE '%export%'  THEN 'Facility constraint'
         WHEN LOWER(reason) IN ('pm') OR LOWER(reason) LIKE '%maint%'           THEN 'Planned maintenance'
         WHEN LOWER(reason) IN ('wt') OR LOWER(reason) LIKE '%test%'            THEN 'Well test'
         ELSE 'Unclassified'
       END AS cause,
       CASE WHEN LOWER(reason) IN ('pm') OR LOWER(reason) LIKE '%maint%'
              OR LOWER(reason) IN ('wt') OR LOWER(reason) LIKE '%test%'
            THEN 'Planned' ELSE 'Unplanned' END AS category
FROM raw_downtime_log;

DROP TABLE IF EXISTS well_test;
CREATE TABLE well_test AS
SELECT UPPER(TRIM(well_id)) AS well_id, DATE(test_date) AS test_date,
       test_oil_bopd, test_water_cut
FROM raw_well_tests;

DROP TABLE IF EXISTS intervention;
CREATE TABLE intervention AS
SELECT UPPER(TRIM(well_id)) AS well_id, treatment, DATE(treatment_date) AS treatment_date
FROM raw_interventions;

-- Calendar spine: one row per well per day, so MISSING days become visible
DROP TABLE IF EXISTS well_day;
CREATE TABLE well_day AS
WITH RECURSIVE cal(d) AS (
    SELECT (SELECT MIN(prod_date) FROM daily_production)
    UNION ALL
    SELECT DATE(d, '+1 day') FROM cal WHERE d < (SELECT MAX(prod_date) FROM daily_production)
)
SELECT w.well_id, c.d AS prod_date,
       p.hours_on, p.oil_bbl, p.gas_mscf, p.water_bbl,
       (p.well_id IS NULL) AS is_missing_report
FROM well w CROSS JOIN cal c
LEFT JOIN daily_production p ON p.well_id = w.well_id AND p.prod_date = c.d;
CREATE UNIQUE INDEX ux_wd ON well_day(well_id, prod_date);

-- Production POTENTIAL: the most recent well test on or before each day ("as-of join").
-- Deferment = what the well could have made at 24 h - what it actually made.
DROP TABLE IF EXISTS daily_deferment;
CREATE TABLE daily_deferment AS
SELECT d.well_id, d.prod_date, d.hours_on, d.oil_bbl, d.is_missing_report,
       COALESCE(
         (SELECT t.test_oil_bopd FROM well_test t                -- latest test on/before the day
           WHERE t.well_id = d.well_id AND t.test_date <= d.prod_date
           ORDER BY t.test_date DESC LIMIT 1),
         (SELECT t.test_oil_bopd FROM well_test t                -- days before the first test:
           WHERE t.well_id = d.well_id                           -- back-fill with the first test
           ORDER BY t.test_date ASC LIMIT 1))                    AS potential_bopd
FROM well_day d;
ALTER TABLE daily_deferment ADD COLUMN deferred_bbl REAL;
UPDATE daily_deferment
   SET deferred_bbl = CASE WHEN is_missing_report = 1 OR hours_on IS NULL THEN NULL
                           ELSE potential_bopd * (24 - hours_on) / 24.0 END;
CREATE INDEX ix_def ON daily_deferment(well_id, prod_date);
