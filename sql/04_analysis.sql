-- ============================================================
-- 04 · ANALYSIS QUERIES  (each block is run by src/run_sql.py and saved to reports/sql/<name>.csv)
-- ============================================================

-- name: downtime_events
-- GAPS-AND-ISLANDS: collapse consecutive days with hours_on < 24 into one downtime EVENT.
-- Trick: day_number - ROW_NUMBER() is constant within a run of consecutive down days.
WITH down AS (
    SELECT well_id, prod_date, hours_on, potential_bopd, deferred_bbl,
           CAST(JULIANDAY(prod_date) AS INT)
             - ROW_NUMBER() OVER (PARTITION BY well_id ORDER BY prod_date) AS island
    FROM daily_deferment
    WHERE hours_on < 24 AND is_missing_report = 0
), events AS (
    SELECT well_id, island,
           MIN(prod_date) AS start_date, MAX(prod_date) AS end_date,
           COUNT(*) AS days_affected,
           ROUND(SUM(24 - hours_on), 1) AS hours_lost,
           ROUND(SUM(deferred_bbl), 0) AS deferred_bbl
    FROM down GROUP BY well_id, island
)
-- attribute each event to the operator log entry that OVERLAPS it (if any)
SELECT e.well_id, e.start_date, e.end_date, e.days_affected, e.hours_lost, e.deferred_bbl,
       COALESCE(l.cause, 'Unexplained (not logged)')      AS cause,
       COALESCE(l.category, 'Unknown')                    AS category
FROM events e
LEFT JOIN downtime_log l
  ON l.well_id = e.well_id
 AND DATE(l.start_time) <= e.end_date
 AND DATE(l.end_time)   >= e.start_date
GROUP BY e.well_id, e.start_date   -- one log match per event (SQLite returns the first overlapping entry)
ORDER BY e.deferred_bbl DESC;

-- name: deferment_pareto
-- PARETO: which causes make up 80% of lost oil? Running SUM() OVER + share of total.
WITH ev AS (
    SELECT * FROM downtime_event
), by_cause AS (
    SELECT cause, category, COUNT(*) AS events, SUM(deferred_bbl) AS deferred_bbl
    FROM ev GROUP BY cause, category
)
SELECT cause, category, events,
       ROUND(deferred_bbl, 0) AS deferred_bbl,
       ROUND(100.0 * deferred_bbl / SUM(deferred_bbl) OVER (), 1) AS pct_of_total,
       ROUND(100.0 * SUM(deferred_bbl) OVER (ORDER BY deferred_bbl DESC
                                             ROWS UNBOUNDED PRECEDING)
             / SUM(deferred_bbl) OVER (), 1) AS cumulative_pct
FROM by_cause
ORDER BY deferred_bbl DESC;

-- name: monthly_kpis
-- Production efficiency = actual / potential. Month-over-month change with LAG().
WITH m AS (
    SELECT SUBSTR(prod_date, 1, 7) AS month,
           SUM(oil_bbl)                         AS actual_bbl,
           SUM(potential_bopd)                  AS potential_bbl,
           SUM(deferred_bbl)                    AS deferred_bbl,
           SUM(is_missing_report)               AS missing_reports
    FROM daily_deferment GROUP BY month
)
SELECT month,
       ROUND(actual_bbl, 0) AS actual_bbl, ROUND(potential_bbl, 0) AS potential_bbl,
       ROUND(deferred_bbl, 0) AS deferred_bbl,
       ROUND(100.0 * actual_bbl / potential_bbl, 1) AS production_efficiency_pct,
       ROUND(100.0 * (actual_bbl - LAG(actual_bbl) OVER (ORDER BY month))
             / LAG(actual_bbl) OVER (ORDER BY month), 1) AS mom_change_pct,
       missing_reports
FROM m ORDER BY month;

-- name: well_ranking
-- Rank wells by unplanned deferment, with quartile (NTILE) and share of field total.
WITH w AS (
    SELECT e.well_id, wl.field, wl.lift_type,
           SUM(CASE WHEN e.category <> 'Planned' THEN e.deferred_bbl ELSE 0 END) AS unplanned_deferred_bbl,
           SUM(CASE WHEN e.category <> 'Planned' THEN 1 ELSE 0 END) AS unplanned_events
    FROM downtime_event e JOIN well wl USING (well_id)
    GROUP BY e.well_id, wl.field, wl.lift_type
)
SELECT RANK() OVER (ORDER BY unplanned_deferred_bbl DESC) AS rank,
       well_id, field, lift_type, unplanned_events,
       ROUND(unplanned_deferred_bbl, 0) AS unplanned_deferred_bbl,
       NTILE(4) OVER (ORDER BY unplanned_deferred_bbl DESC) AS quartile,
       ROUND(100.0 * unplanned_deferred_bbl
             / SUM(unplanned_deferred_bbl) OVER (PARTITION BY field), 1) AS pct_of_field
FROM w ORDER BY rank;

-- name: lift_type_reliability
-- Mean time between unplanned events per lift type (exposure-based, not just counts).
SELECT wl.lift_type,
       COUNT(DISTINCT wl.well_id) AS wells,
       SUM(CASE WHEN e.category <> 'Planned' THEN 1 ELSE 0 END) AS unplanned_events,
       ROUND(1.0 * COUNT(DISTINCT wl.well_id) * (SELECT COUNT(DISTINCT prod_date) FROM well_day)
             / NULLIF(SUM(CASE WHEN e.category <> 'Planned' THEN 1 ELSE 0 END), 0), 0) AS mtbe_days,
       ROUND(AVG(e.deferred_bbl), 0) AS avg_bbl_lost_per_event
FROM well wl LEFT JOIN downtime_event e USING (well_id)
GROUP BY wl.lift_type ORDER BY mtbe_days;

-- name: water_cut_trend
-- Water cut trend per well from well tests: first vs last test and change per year.
WITH t AS (
    SELECT well_id, test_date, test_water_cut,
           FIRST_VALUE(test_water_cut) OVER w AS wc_first,
           LAST_VALUE(test_water_cut)  OVER w AS wc_last,
           FIRST_VALUE(test_date)      OVER w AS d_first,
           LAST_VALUE(test_date)       OVER w AS d_last
    FROM well_test
    WINDOW w AS (PARTITION BY well_id ORDER BY test_date
                 ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
)
SELECT DISTINCT well_id, wc_first, wc_last,
       ROUND((wc_last - wc_first) * 365.0 / (JULIANDAY(d_last) - JULIANDAY(d_first)), 1) AS wc_change_pts_per_year
FROM t ORDER BY wc_change_pts_per_year DESC;

-- name: logging_compliance
-- How much downtime was never explained in the operator log? (data-governance finding)
SELECT CASE WHEN cause = 'Unexplained (not logged)' THEN 'Not logged' ELSE 'Logged' END AS status,
       COUNT(*) AS events,
       ROUND(SUM(deferred_bbl), 0) AS deferred_bbl,
       ROUND(100.0 * SUM(deferred_bbl) / (SELECT SUM(deferred_bbl) FROM downtime_event), 1) AS pct_bbl
FROM downtime_event GROUP BY status;
