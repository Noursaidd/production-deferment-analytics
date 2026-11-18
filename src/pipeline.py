"""Run everything: raw data -> SQL warehouse + data tests -> analyses -> statistics -> report."""
from src import decline, generate_data, intervention, report, run_sql


def main() -> None:
    for name, fn in [("1/5 generate raw data", generate_data.main),
                     ("2/5 SQL: load, clean, data tests, analysis", run_sql.main),
                     ("3/5 decline-curve forecasts", decline.main),
                     ("4/5 treatment effect (difference-in-differences)", intervention.main),
                     ("5/5 report", report.main)]:
        print(f"\n=== {name} ===")
        fn()


if __name__ == "__main__":
    main()
