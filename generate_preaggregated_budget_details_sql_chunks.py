from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

PARQUET_PATH = Path("preaggregated_budget_details.parquet")
OUTPUT_DIR = Path("sql_chunks_preaggregated_budget_details")
TABLE_NAME = "ai_for_good_budget_drift.preaggregated_budget_details"
ROWS_PER_INSERT = 1000
ROWS_PER_FILE = 1_000_000

COLUMNS = [
    "fiscal_year",
    "department_code",
    "department_name",
    "region_code",
    "region_description",
    "uacs_object_code",
    "org_code",
    "org_name",
    "budget_description",
    "funding_source",
    "full_agency_code",
    "agency_name",
    "budget_amount_nep",
    "budget_amount_gaa",
    "abs_change",
    "pct_change",
    "is_inserted_budget",
    "is_unapproved_budget",
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


def write_chunk_file(chunk_df: pd.DataFrame, chunk_index: int) -> tuple[Path, int]:
    output_path = (
        OUTPUT_DIR / f"preaggregated_budget_details_part_{chunk_index:04d}.sql"
    )
    col_sql = ", ".join(COLUMNS)

    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("-- Generated from preaggregated_budget_details.parquet\n")
        f.write(
            "-- Target table: ai_for_good_budget_drift.preaggregated_budget_details\n"
        )
        f.write(f"-- Chunk: {chunk_index}\n")
        f.write("BEGIN;\n\n")

        for start in range(0, len(chunk_df), ROWS_PER_INSERT):
            batch = chunk_df.iloc[start : start + ROWS_PER_INSERT]
            f.write(f"INSERT INTO {TABLE_NAME} ({col_sql}) VALUES\n")

            rows_sql = []
            for row in batch.itertuples(index=False, name=None):
                values = ", ".join(sql_literal(v) for v in row)
                rows_sql.append(f"({values})")

            f.write(",\n".join(rows_sql))
            f.write(";\n\n")

        f.write("COMMIT;\n")

    return output_path, len(chunk_df)


def main() -> None:
    if not PARQUET_PATH.exists():
        raise FileNotFoundError(f"Missing parquet file: {PARQUET_PATH}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(PARQUET_PATH)

    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Parquet is missing expected columns: {missing}")

    df = df[COLUMNS]

    total_rows = len(df)
    chunk_index = 1
    written_rows = 0

    manifest_path = OUTPUT_DIR / "manifest.txt"
    with manifest_path.open("w", encoding="utf-8", newline="\n") as manifest:
        manifest.write(
            "# SQL chunks for ai_for_good_budget_drift.preaggregated_budget_details\n"
        )
        manifest.write(f"# Source parquet: {PARQUET_PATH}\n")
        manifest.write(f"# Total rows: {total_rows:,}\n")
        manifest.write(f"# Rows per file: {ROWS_PER_FILE:,}\n")
        manifest.write("#\n")

        for start in range(0, total_rows, ROWS_PER_FILE):
            chunk_df = df.iloc[start : start + ROWS_PER_FILE]
            output_path, row_count = write_chunk_file(chunk_df, chunk_index)
            written_rows += row_count
            manifest.write(f"{output_path.name}|rows={row_count}\n")
            print(f"Created {output_path} with {row_count:,} rows")
            chunk_index += 1

    print(f"Done. Created {chunk_index - 1} files with {written_rows:,} rows total.")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
