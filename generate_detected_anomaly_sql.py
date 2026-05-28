from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

PARQUET_PATH = Path("detected_anomaly.parquet")
OUTPUT_SQL_PATH = Path("detected_anomaly_seed.sql")
TABLE_NAME = "ai_for_good_budget_drift.detected_anomaly"
BATCH_SIZE = 1000

COLUMNS = [
    "fiscal_year",
    "department_code",
    "department_name",
    "full_agency_code",
    "agency_name",
    "region_code",
    "region_description",
    "uacs_object_code",
    "uacs_sub_object_name",
    "budget_amount_nep",
    "budget_amount_gaa",
    "unapproved_budget",
    "inserted_budget",
    "abs_change",
    "pct_change",
    "adjustment_type",
    "anomaly_threshold",
    "z_score",
    "anomaly_zscore",
    "region_mean",
    "region_std",
    "region_anomaly",
    "historical_mean",
    "historical_std",
    "historical_anomaly",
    "anomaly_score",
    "is_anomaly",
    "explanation",
]


def sql_literal(value: Any) -> str:
    if value is None or pd.isna(value):
        return "NULL"

    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"

    if isinstance(value, int):
        return str(value)

    if isinstance(value, float):
        return format(value, ".15g")

    text = str(value).replace("'", "''")
    return f"'{text}'"


def main() -> None:
    if not PARQUET_PATH.exists():
        raise FileNotFoundError(f"Missing parquet file: {PARQUET_PATH}")

    df = pd.read_parquet(PARQUET_PATH)

    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Parquet is missing expected columns: {missing}")

    df = df[COLUMNS]

    with OUTPUT_SQL_PATH.open("w", encoding="utf-8", newline="\n") as f:
        f.write("-- Generated from detected_anomaly.parquet\n")
        f.write("-- Target table: ai_for_good_budget_drift.detected_anomaly\n")
        f.write("BEGIN;\n\n")

        col_sql = ", ".join(COLUMNS)

        for start in range(0, len(df), BATCH_SIZE):
            batch = df.iloc[start : start + BATCH_SIZE]
            f.write(f"INSERT INTO {TABLE_NAME} ({col_sql}) VALUES\n")

            rows_sql = []
            for row in batch.itertuples(index=False, name=None):
                values = ", ".join(sql_literal(v) for v in row)
                rows_sql.append(f"({values})")

            f.write(",\n".join(rows_sql))
            f.write(";\n\n")

        f.write("COMMIT;\n")
        f.write("ANALYZE ai_for_good_budget_drift.detected_anomaly;\n")

    print(f"Created {OUTPUT_SQL_PATH} with {len(df):,} rows")


if __name__ == "__main__":
    main()
