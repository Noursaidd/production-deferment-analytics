"""Tests on tiny hand-made inputs, so each SQL rule and statistic is checked against a
known answer, plus validation of the full pipeline against the generator's ground truth."""
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.decline import arps
from src.intervention import bootstrap_did
from src.run_sql import named_queries

ROOT = Path(__file__).resolve().parents[1]


def mini_db(prod_rows, log_rows=(), tests=None):
    con = sqlite3.connect(":memory:")
    con.executescript((ROOT / "sql/01_schema.sql").read_text())
    con.executemany("INSERT INTO raw_wells VALUES (?,?,?,?)", [("P-001", "F", "ESP", "2020-01-01")])
    con.executemany("INSERT INTO raw_daily_production VALUES (?,?,?,?,?,?)", prod_rows)
    con.executemany("INSERT INTO raw_downtime_log VALUES (?,?,?,?,?)", log_rows)
    con.executemany("INSERT INTO raw_well_tests VALUES (?,?,?,?)",
                    tests or [("P-001", "2025-01-01", 1000.0, 30.0)])
    con.executescript((ROOT / "sql/02_clean.sql").read_text())
    return con


def test_clean_layer_rules():
    con = mini_db([
        ("P-001", "2025-01-01", 24, 1000, 500, 300),
        (" p-001 ", "2025-01-01", 24, 1000, 500, 300),   # duplicate with dirty ID
        ("P-001", "2025-01-02", 25, -1, 500, 300),       # impossible hours, sentinel oil
        ("P-001", "2025-01-04", 24, 990, 500, 300),      # 2025-01-03 missing
    ])
    p = pd.read_sql("SELECT * FROM daily_production ORDER BY prod_date", con)
    assert len(p) == 3
    assert p.loc[1, "hours_on"] == 24 and pd.isna(p.loc[1, "oil_bbl"])
    wd = pd.read_sql("SELECT * FROM well_day", con)
    assert wd.is_missing_report.sum() == 1                    # calendar spine exposes the gap
    for check in pd.read_sql(named_queries(str(ROOT / "sql/03_quality_checks.sql"))["dq_checks"], con).itertuples():
        assert check.failing_rows == 0, check.check_name


@pytest.mark.parametrize("raw,cause", [("esp tripped", "ESP trip"), ("PWR outage", "Power failure"),
                                       ("FL leak - isolated", "Flowline leak"), ("Separator full", "Facility constraint"),
                                       ("PM", "Planned maintenance"), ("WT", "Well test"), ("export constraint", "Facility constraint")])
def test_reason_mapping(raw, cause):
    con = mini_db([("P-001", "2025-01-01", 24, 1, 1, 1)],
                  [("P-001", "2025-01-01 05:00", "2025-01-01 09:00", raw, "x")])
    assert con.execute("SELECT cause FROM downtime_log").fetchone()[0] == cause


def test_gaps_and_islands_and_deferment():
    rows = [("P-001", f"2025-01-{d:02d}", h, 1000 * h / 24, 1, 1)
            for d, h in [(1, 24), (2, 12), (3, 0), (4, 6), (5, 24), (6, 18), (7, 24)]]
    con = mini_db(rows, [("P-001", "2025-01-02 12:00", "2025-01-04 06:00", "ESP trip", "x")])
    ev = pd.read_sql(named_queries(str(ROOT / "sql/04_analysis.sql"))["downtime_events"], con)
    ev = ev.sort_values("start_date").reset_index(drop=True)
    assert len(ev) == 2                                        # days 2-4 = one event, day 6 = another
    assert (ev.loc[0, "start_date"], ev.loc[0, "end_date"]) == ("2025-01-02", "2025-01-04")
    assert ev.loc[0, "hours_lost"] == 12 + 24 + 18
    assert ev.loc[0, "deferred_bbl"] == pytest.approx(1000 * 54 / 24, abs=1)
    assert ev.loc[0, "cause"] == "ESP trip"
    assert ev.loc[1, "cause"].startswith("Unexplained")       # day 6 never logged


def test_arps_recovers_known_parameters():
    from scipy.optimize import curve_fit
    t = np.arange(0, 600, 30.4)
    q = arps(t, 1500, 0.002, 0.5)
    p, _ = curve_fit(arps, t, q, p0=[1000, 0.001, 0.3], bounds=([0, 1e-6, 0.01], [1e4, 0.05, 0.99]))
    assert p == pytest.approx([1500, 0.002, 0.5], rel=0.02)


def test_bootstrap_ci_contains_true_difference():
    rng = np.random.default_rng(1)
    lo, hi = bootstrap_did(rng.normal(10, 2, 50), rng.normal(0, 2, 50), n=2000)
    assert lo < 10 < hi


@pytest.mark.skipif(not (ROOT / "reports/intervention_result.json").exists(), reason="run pipeline first")
def test_pipeline_rediscovers_ground_truth():
    gt = json.loads((ROOT / "data/raw/_ground_truth_for_tests.json").read_text())
    res = json.loads((ROOT / "reports/intervention_result.json").read_text())
    lo, hi = res["bootstrap_95ci_pct"]
    assert lo <= 12.0 <= hi + 1.5                              # true uplift 12% (slightly decayed)
    dec = pd.read_csv(ROOT / "reports/decline_forecasts.csv")
    flagged = set(dec[dec.status.str.startswith("Below")].well_id)
    assert set(gt["problem_wells"]) <= flagged                 # all hidden problem wells found
