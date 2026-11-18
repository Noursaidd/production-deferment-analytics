"""Generate 2 years of realistic, deliberately messy daily production data.

Physics: each well follows an Arps hyperbolic decline q(t) = qi / (1 + b*Di*t)^(1/b),
with rising water cut. Downtime (trips, power, facility, planned maintenance) cuts
hours on-line. A scale-squeeze campaign lifts the rate of 8 treated wells.

Mess injected, like real daily production reports and operator logs:
* duplicate rows, lower-case / padded well IDs, hours_on > 24, negative volumes
* missing days, free-text downtime reasons in many spellings
* ~25% of downtime never written in the log (the "unexplained deferment" problem)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

CAUSES = {  # category: (weight, typical duration days, raw spellings)
    "ESP trip": (0.30, (1, 4), ["ESP trip", "esp tripped", "ESP T/O", "pump trip - restarted"]),
    "Power failure": (0.20, (1, 2), ["power failure", "PWR outage", "Power dip GTG", "power"]),
    "Facility constraint": (0.15, (1, 6), ["facility constraint", "Separator full", "plant upset",
                                           "export constraint"]),
    "Flowline leak": (0.10, (3, 10), ["flowline leak", "FL leak - isolated", "pipeline leak"]),
    "Planned maintenance": (0.15, (2, 5), ["planned maintenance", "PM", "scheduled maint."]),
    "Well test": (0.10, (1, 1), ["well test", "WT", "testing"]),
}


def load_config(path="config/config.yaml"):
    with open(path) as f:
        return yaml.safe_load(f)


def main(config_path="config/config.yaml"):
    cfg = load_config(config_path)
    rng = np.random.default_rng(cfg["seed"])
    raw = Path(cfg["raw_dir"]); raw.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range(cfg["start_date"], cfg["end_date"], freq="D")
    n = cfg["n_wells"]

    wells = pd.DataFrame({
        "well_id": [f"P-{i:03d}" for i in range(1, n + 1)],
        "field": rng.choice(["Field A", "Field B", "Field C"], n),
        "lift_type": rng.choice(["ESP", "Gas lift", "Natural flow"], n, p=[0.6, 0.25, 0.15]),
        "online_date": [dates[0] - pd.Timedelta(days=int(d)) for d in rng.integers(100, 2000, n)],
    })
    treated = set(rng.choice(wells.well_id, cfg["intervention"]["n_treated"], replace=False))
    # hidden problem (e.g. scale build-up / pump wear) in 3 untreated wells from Aug-2025:
    # nobody told the analyst - the decline analysis has to find them.
    problem = set(rng.choice(sorted(set(wells.well_id) - treated), 3, replace=False))
    t_prob = pd.Timestamp("2025-08-01")
    t_int = pd.Timestamp(cfg["intervention"]["date"])

    prod, logs, tests = [], [], []
    cause_names = list(CAUSES)
    cause_p = np.array([CAUSES[c][0] for c in cause_names]); cause_p /= cause_p.sum()
    for _, w in wells.iterrows():
        qi = rng.uniform(600, 2500); Di = rng.uniform(0.0006, 0.0018); b = rng.uniform(0.3, 0.9)
        wc0 = rng.uniform(0.15, 0.6); wc_slope = rng.uniform(0.00005, 0.0003)
        gor = rng.uniform(0.4, 1.2)                       # mscf per bbl
        age0 = (dates[0] - w.online_date).days
        hours = np.full(len(dates), 24.0)
        month_noise = {m: rng.normal(1, 0.035) for m in pd.period_range(dates[0], dates[-1], freq="M")}
        # downtime events
        d = 0
        while d < len(dates):
            d += int(rng.exponential(28))
            if d >= len(dates):
                break
            c = rng.choice(cause_names, p=cause_p)
            lo, hi = CAUSES[c][1]
            dur = int(rng.integers(lo, hi + 1))
            partial_first = rng.uniform(2, 20)            # trips rarely start at midnight
            hours[d] = min(hours[d], partial_first)
            hours[d + 1: d + dur] = 0
            if d + dur < len(dates):
                hours[d + dur] = rng.uniform(4, 22)       # restart day, partial
            if rng.random() > 0.25:                       # 25% of events never logged
                start = dates[d] + pd.Timedelta(hours=float(partial_first))
                end = dates[min(d + dur, len(dates) - 1)] + pd.Timedelta(hours=float(rng.uniform(1, 20)))
                logs.append(dict(well_id=w.well_id, start_time=start, end_time=end,
                                 reason=rng.choice(CAUSES[c][2]), logged_by=rng.choice(["ops_A", "ops_B", "ops_C"])))
            d += dur + 1
        for i, day in enumerate(dates):
            t = age0 + i
            q = qi / (1 + b * Di * t) ** (1 / b)
            if w.well_id in treated and day >= t_int:
                q *= 1 + cfg["intervention"]["true_uplift"] * np.exp(-(day - t_int).days / 400)
            if w.well_id in problem and day >= t_prob:
                q *= 1 - 0.30 * min(1.0, (day - t_prob).days / 120)
            q *= month_noise[day.to_period("M")]
            wc = min(wc0 + wc_slope * i, 0.95)
            oil = q * hours[i] / 24 * rng.normal(1, 0.04)
            prod.append(dict(well_id=w.well_id, prod_date=day.date().isoformat(), hours_on=round(hours[i], 1),
                             oil_bbl=round(oil, 1), gas_mscf=round(oil * gor * rng.normal(1, 0.05), 1),
                             water_bbl=round(oil * wc / (1 - wc), 1)))
            if day.day == 15:                              # monthly well test (24 h, stabilised)
                tests.append(dict(well_id=w.well_id, test_date=day.date().isoformat(),
                                  test_oil_bopd=round(q * rng.normal(1, 0.03), 1),
                                  test_water_cut=round(wc * 100, 1)))

    prod = pd.DataFrame(prod)
    # ---- mess ----
    m = len(prod)
    prod = prod.drop(prod.sample(frac=0.01, random_state=1).index)            # missing days
    dup = prod.sample(frac=0.008, random_state=2)
    prod = pd.concat([prod, dup])                                              # duplicates
    idx = prod.sample(frac=0.05, random_state=3).index
    prod.loc[idx, "well_id"] = prod.loc[idx, "well_id"].str.lower().map(lambda s: f" {s} ")  # bad IDs
    prod.loc[prod.sample(n=40, random_state=4).index, "hours_on"] = 25.0        # impossible hours
    prod.loc[prod.sample(n=30, random_state=5).index, "oil_bbl"] = -1.0         # sentinel values
    prod = prod.sample(frac=1, random_state=6).reset_index(drop=True)

    wells.assign(online_date=wells.online_date.dt.date).to_csv(raw / "wells.csv", index=False)
    prod.to_csv(raw / "daily_production.csv", index=False)
    logs = pd.DataFrame(logs)
    for c in ["start_time", "end_time"]:
        logs[c] = logs[c].dt.floor("min").dt.strftime("%Y-%m-%d %H:%M")
    logs.to_csv(raw / "downtime_log.csv", index=False)
    pd.DataFrame(tests).to_csv(raw / "well_tests.csv", index=False)
    pd.DataFrame({"well_id": sorted(treated), "treatment": "scale squeeze",
                  "treatment_date": t_int.date().isoformat()}).to_csv(raw / "interventions.csv", index=False)
    (raw / "_ground_truth_for_tests.json").write_text(
        pd.Series({"treated": sorted(treated), "problem_wells": sorted(problem)}).to_json())
    print(f"wells={n} production_rows={len(prod):,} (clean={m:,}) downtime_logs={len(logs)} "
          f"well_tests={len(tests)} treated={len(treated)}")


if __name__ == "__main__":
    main()
