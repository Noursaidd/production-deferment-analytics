"""Did the scale-squeeze campaign actually work?  (difference-in-differences)

The naive answer compares treated wells before vs after, but wells decline anyway,
so a naive comparison *under-states* the uplift (and can even show a loss). The fair
comparison uses untreated wells over the same dates as a control group:

    effect = (after/before - 1)_treated  -  (after/before - 1)_control

Uncertainty: Welch t-test, Mann-Whitney U (no normality assumption) and a bootstrap
95% confidence interval, because with 8 treated wells the result must come with its error bar.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from src.generate_data import load_config


def per_well_change(db: str, t0: str, window: int) -> pd.DataFrame:
    con = sqlite3.connect(db)
    q = f"""
    WITH d AS (
        SELECT w.well_id,
               CASE WHEN w.prod_date <  DATE('{t0}') THEN 'before' ELSE 'after' END AS period,
               w.oil_bbl, w.hours_on
        FROM well_day w
        WHERE w.prod_date >= DATE('{t0}', '-{window} day')
          AND w.prod_date <  DATE('{t0}', '+{window} day')
          AND w.hours_on >= 12 AND w.oil_bbl IS NOT NULL   -- stable days only
    )
    SELECT d.well_id,
           (i.well_id IS NOT NULL) AS treated,
           SUM(CASE WHEN period='before' THEN oil_bbl END) / SUM(CASE WHEN period='before' THEN hours_on/24.0 END) AS rate_before,
           SUM(CASE WHEN period='after'  THEN oil_bbl END) / SUM(CASE WHEN period='after'  THEN hours_on/24.0 END) AS rate_after
    FROM d LEFT JOIN intervention i USING (well_id)
    GROUP BY d.well_id"""
    df = pd.read_sql(q, con)
    con.close()
    df["change_pct"] = (df.rate_after / df.rate_before - 1) * 100
    return df


def bootstrap_did(t: np.ndarray, c: np.ndarray, n: int = 10000, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    diffs = [rng.choice(t, len(t)).mean() - rng.choice(c, len(c)).mean() for _ in range(n)]
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def main(config_path="config/config.yaml"):
    cfg = load_config(config_path)
    ic = cfg["intervention"]
    df = per_well_change(cfg["db"], ic["date"], ic["window_days"])
    t = df[df.treated == 1].change_pct.to_numpy()
    c = df[df.treated == 0].change_pct.to_numpy()
    lo, hi = bootstrap_did(t, c)
    did = t.mean() - c.mean()
    # value: uplift x treated wells' pre-treatment rate x 365 days x oil price
    base_rate = df[df.treated == 1].rate_before.sum()
    res = {
        "treated_wells": int(len(t)), "control_wells": int(len(c)), "window_days": ic["window_days"],
        "naive_treated_change_pct": round(float(t.mean()), 2),
        "control_change_pct": round(float(c.mean()), 2),
        "did_effect_pct": round(float(did), 2),
        "bootstrap_95ci_pct": [round(lo, 2), round(hi, 2)],
        "welch_t_p_value": float(f"{stats.ttest_ind(t, c, equal_var=False).pvalue:.2g}"),
        "mann_whitney_p_value": float(f"{stats.mannwhitneyu(t, c, alternative='greater').pvalue:.2g}"),
        "extra_oil_bopd_first_period": round(base_rate * did / 100),
        "indicative_annual_value_usd": round(base_rate * did / 100 * 365 * cfg["oil_price_usd_per_bbl"] * 0.7),
        "value_note": "x0.7 haircut because the effect fades over time (re-measure at 6 months)",
    }
    Path("reports").mkdir(exist_ok=True)
    df.round(2).to_csv("reports/intervention_per_well.csv", index=False)
    Path("reports/intervention_result.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))
    return res


if __name__ == "__main__":
    main()
