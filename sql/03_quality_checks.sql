-- Data tests written in SQL. Each query returns ONE row: (check_name, failing_rows).
-- Pipeline fails if any check on the CLEAN layer is > 0. Raw-layer counts are reported.

-- name: dq_checks
SELECT 'clean: duplicate (well, day) rows' AS check_name,
       COUNT(*) AS failing_rows
FROM (SELECT well_id, prod_date FROM daily_production GROUP BY 1, 2 HAVING COUNT(*) > 1)
UNION ALL
SELECT 'clean: hours_on outside 0..24', COUNT(*) FROM daily_production WHERE hours_on NOT BETWEEN 0 AND 24
UNION ALL
SELECT 'clean: negative volumes', COUNT(*) FROM daily_production
 WHERE oil_bbl < 0 OR gas_mscf < 0 OR water_bbl < 0
UNION ALL
SELECT 'clean: well_id not in master', COUNT(*) FROM daily_production p
 WHERE NOT EXISTS (SELECT 1 FROM well w WHERE w.well_id = p.well_id)
UNION ALL
SELECT 'clean: unclassified downtime reasons', COUNT(*) FROM downtime_log WHERE cause = 'Unclassified'
UNION ALL
SELECT 'clean: downtime end before start', COUNT(*) FROM downtime_log WHERE end_time < start_time;

-- name: dq_raw_profile
SELECT 'raw: rows' AS metric, COUNT(*) AS value FROM raw_daily_production
UNION ALL SELECT 'raw: non-standard well IDs', COUNT(*) FROM raw_daily_production WHERE well_id <> UPPER(TRIM(well_id))
UNION ALL SELECT 'raw: duplicate rows removed', (SELECT COUNT(*) FROM raw_daily_production) - (SELECT COUNT(*) FROM daily_production)
UNION ALL SELECT 'raw: hours_on > 24 (capped)', SUM(flag_hours_fixed) FROM daily_production
UNION ALL SELECT 'raw: negative oil (set NULL)', SUM(flag_oil_invalid) FROM daily_production
UNION ALL SELECT 'calendar: missing daily reports', SUM(is_missing_report) FROM well_day
UNION ALL SELECT 'raw: distinct downtime reason spellings', COUNT(DISTINCT reason) FROM raw_downtime_log;
