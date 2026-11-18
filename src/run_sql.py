"""Load raw CSVs into SQLite, run the SQL layers in order, enforce SQL data tests,
and export every named analysis query to reports/sql/<name>.csv."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pandas as pd

from src.generate_data import load_config

RAW_TABLES = {"wells": "raw_wells", "daily_production": "raw_daily_production",
              "downtime_log": "raw_downtime_log", "well_tests": "raw_well_tests",
              "interventions": "raw_interventions"}


def named_queries(path: str) -> dict[str, str]:
    parts = re.split(r"^-- name:\s*(\w+)\s*$", Path(path).read_text(), flags=re.M)[1:]
    return dict(zip(parts[::2], parts[1::2]))


def build_warehouse(cfg: dict) -> sqlite3.Connection:
    Path(cfg["db"]).unlink(missing_ok=True)
    con = sqlite3.connect(cfg["db"])
    con.executescript(Path("sql/01_schema.sql").read_text())
    for csv, table in RAW_TABLES.items():
        pd.read_csv(Path(cfg["raw_dir"]) / f"{csv}.csv").to_sql(table, con, if_exists="append", index=False)
    con.executescript(Path("sql/02_clean.sql").read_text())
    return con


def run_quality_checks(con) -> tuple[pd.DataFrame, pd.DataFrame]:
    q = named_queries("sql/03_quality_checks.sql")
    checks = pd.read_sql(q["dq_checks"], con)
    profile = pd.read_sql(q["dq_raw_profile"], con)
    failed = checks[checks.failing_rows > 0]
    if len(failed):
        raise AssertionError(f"SQL data tests failed:\n{failed.to_string(index=False)}")
    return checks, profile


def run_analysis(con) -> dict[str, pd.DataFrame]:
    out = Path("reports/sql"); out.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, sql in named_queries("sql/04_analysis.sql").items():
        df = pd.read_sql(sql, con)
        if name == "downtime_events":            # materialise for downstream queries
            df.to_sql("downtime_event", con, if_exists="replace", index=False)
        df.to_csv(out / f"{name}.csv", index=False)
        results[name] = df
    return results


def main(config_path: str = "config/config.yaml") -> dict:
    cfg = load_config(config_path)
    con = build_warehouse(cfg)
    checks, profile = run_quality_checks(con)
    Path("reports").mkdir(exist_ok=True)
    checks.to_csv("reports/dq_checks.csv", index=False)
    profile.to_csv("reports/dq_raw_profile.csv", index=False)
    res = run_analysis(con)
    con.close()
    print(profile.to_string(index=False)); print()
    print(checks.to_string(index=False)); print()
    print(res["deferment_pareto"].to_string(index=False)); print()
    print(res["logging_compliance"].to_string(index=False))
    return res


if __name__ == "__main__":
    main()
