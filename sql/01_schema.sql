-- Layered warehouse: raw_* (as received, never edited) -> clean tables (typed, validated).
-- Keeping raw untouched means every cleaning decision can be audited and re-run.

DROP TABLE IF EXISTS raw_daily_production;
DROP TABLE IF EXISTS raw_downtime_log;
DROP TABLE IF EXISTS raw_well_tests;
DROP TABLE IF EXISTS raw_wells;
DROP TABLE IF EXISTS raw_interventions;

CREATE TABLE raw_wells          (well_id TEXT, field TEXT, lift_type TEXT, online_date TEXT);
CREATE TABLE raw_daily_production (well_id TEXT, prod_date TEXT, hours_on REAL,
                                   oil_bbl REAL, gas_mscf REAL, water_bbl REAL);
CREATE TABLE raw_downtime_log   (well_id TEXT, start_time TEXT, end_time TEXT, reason TEXT, logged_by TEXT);
CREATE TABLE raw_well_tests     (well_id TEXT, test_date TEXT, test_oil_bopd REAL, test_water_cut REAL);
CREATE TABLE raw_interventions  (well_id TEXT, treatment TEXT, treatment_date TEXT);
