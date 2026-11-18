"""Arps decline-curve analysis per well (the standard petroleum-engineering forecast).

q(t) = qi / (1 + b*Di*t)^(1/b)      hyperbolic, 0 < b < 1

* Rate is *uptime-normalised* (oil / days on-line) so downtime is not mistaken for decline.
* Fit on Jan-2024..Mar-2025, compare with actuals Apr..Dec-2025, then
  flag wells producing well below their own forecast -> candidates for investigation
  (scale, pump wear, reservoir issue). Wells well ABOVE forecast are flagged too:
  something changed (e.g. a stimulation) and the forecast needs updating.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from src.generate_data import load_config

FIT_END = "2025-03"   # fit on history BEFORE the Apr-2025 treatment campaign


def arps(t, qi, di, b):
    return qi / np.power(1 + b * di * t, 1 / b)


def monthly_rates(db: str) -> pd.DataFrame:
    con = sqlite3.connect(db)
    df = pd.read_sql("""
        SELECT well_id, SUBSTR(prod_date, 1, 7) AS month,
               SUM(oil_bbl) / NULLIF(SUM(hours_on) / 24.0, 0) AS rate_on_bopd
        FROM well_day WHERE is_missing_report = 0 AND oil_bbl IS NOT NULL
        GROUP BY well_id, month ORDER BY well_id, month""", con)
    con.close()
    return df


def fit_well(g: pd.DataFrame, horizon: int) -> dict:
    g = g.reset_index(drop=True)
    g["t"] = np.arange(len(g)) * 30.4                    # days since first month
    tr, te = g[g.month <= FIT_END], g[g.month > FIT_END]
    p0 = [tr.rate_on_bopd.iloc[0], 0.001, 0.5]
    params, _ = curve_fit(arps, tr.t, tr.rate_on_bopd, p0=p0,
                          bounds=([0, 1e-6, 0.01], [10000, 0.05, 0.99]), maxfev=20000)
    pred_tr = arps(tr.t, *params)
    r2 = 1 - ((tr.rate_on_bopd - pred_tr) ** 2).sum() / ((tr.rate_on_bopd - tr.rate_on_bopd.mean()) ** 2).sum()
    pred_te = arps(te.t, *params)
    last3 = te.tail(3)                                   # most recent quarter: is the well on track NOW?
    dev = (last3.rate_on_bopd.mean() - arps(last3.t, *params).mean()) / arps(last3.t, *params).mean() * 100
    fut_t = g.t.iloc[-1] + 30.4 * np.arange(1, horizon + 1)
    return {"qi": params[0], "di_per_day": params[1], "b": params[2], "r2_fit": r2,
            "holdout_mape_pct": float(np.mean(np.abs(te.rate_on_bopd - pred_te) / te.rate_on_bopd) * 100),
            "recent_actual_vs_forecast_pct": dev,
            "annual_decline_pct": (1 - arps(365, *params) / arps(0, *params)) * 100,
            "next_12m_forecast_bbl": float(arps(fut_t, *params).sum() * 30.4),
            "_curve": (g.month.tolist(), g.rate_on_bopd.tolist(), arps(g.t, *params).tolist())}


def main(config_path="config/config.yaml"):
    cfg = load_config(config_path)
    rates = monthly_rates(cfg["db"])
    thr = cfg["decline"]["underperform_pct"]
    rows, curves = [], {}
    for w, g in rates.groupby("well_id"):
        r = fit_well(g, cfg["decline"]["forecast_months"])
        curves[w] = r.pop("_curve")
        dev = r["recent_actual_vs_forecast_pct"]
        r["status"] = ("Below forecast - investigate" if dev < -thr else
                       "Above forecast - re-forecast" if dev > thr else "On track")
        rows.append({"well_id": w, **r})
    out = pd.DataFrame(rows).round(3).sort_values("recent_actual_vs_forecast_pct")
    Path("reports").mkdir(exist_ok=True)
    out.to_csv("reports/decline_forecasts.csv", index=False)
    pd.to_pickle(curves, "reports/.decline_curves.pkl")
    print(out[["well_id", "r2_fit", "holdout_mape_pct", "recent_actual_vs_forecast_pct",
               "annual_decline_pct", "status"]].to_string(index=False))
    print("\nmedian R2:", round(out.r2_fit.median(), 3), " median hold-out MAPE %:",
          round(out.holdout_mape_pct.median(), 1))
    return out


if __name__ == "__main__":
    main()
