"""
Loads the raw CSVs + processed trust-engine outputs into a SQLite warehouse
so the SQL views and analytics queries can be validated locally without
standing up Postgres. Swap the connection string for a real Postgres DSN in
production — the DDL/views are portable SQL.
"""

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "warehouse.db"


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)

    schema_sql = (ROOT / "sql" / "ddl" / "schema.sql").read_text()
    conn.executescript(schema_sql)

    views_sql = (ROOT / "sql" / "views" / "analysis_views.sql").read_text()
    conn.executescript(views_sql)

    raw = ROOT / "data" / "raw"
    pd.read_csv(raw / "experiments.csv").to_sql("dim_experiment", conn, if_exists="append", index=False)
    pd.read_csv(raw / "users.csv").to_sql("dim_user", conn, if_exists="append", index=False)
    pd.read_csv(raw / "assignments.csv").to_sql("fact_assignment", conn, if_exists="append", index=False)
    pd.read_csv(raw / "events.csv").to_sql("fact_event", conn, if_exists="append", index=False)
    pd.read_csv(raw / "metric_definitions.csv").to_sql("dim_metric_definition", conn, if_exists="append", index=False)

    processed = ROOT / "data" / "processed"
    if (processed / "experiment_results.csv").exists():
        pd.read_csv(processed / "experiment_results.csv").to_sql(
            "fact_trust_score", conn, if_exists="replace", index=False
        )
    if (processed / "daily_lift.csv").exists():
        pd.read_csv(processed / "daily_lift.csv").to_sql(
            "fact_daily_lift", conn, if_exists="replace", index=False
        )

    conn.commit()
    counts = {}
    for t in ["dim_experiment", "dim_user", "fact_assignment", "fact_event",
              "dim_metric_definition", "fact_trust_score", "fact_daily_lift"]:
        try:
            counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            counts[t] = "N/A"
    conn.close()

    print(f"Warehouse built at {DB_PATH}")
    for t, c in counts.items():
        print(f"  {t}: {c}")


if __name__ == "__main__":
    main()
