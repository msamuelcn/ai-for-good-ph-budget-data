from __future__ import annotations

from pathlib import Path
import argparse

import pandas as pd


def find_cleaned_budget_files(base_dir: Path) -> list[Path]:
    return sorted(base_dir.glob("cleaned_budget_*.parquet"))


def aggregate_one_file(file: Path) -> pd.DataFrame:
    detail_group_cols = [
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
    ]

    required = set(detail_group_cols + ["budget_type", "budget_amount"])

    df = pd.read_parquet(file)
    df.columns = [col.lower() for col in df.columns]

    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{file.name} is missing required columns: {missing}")

    reduced = (
        df[detail_group_cols + ["budget_type", "budget_amount"]]
        .groupby(detail_group_cols + ["budget_type"], dropna=False)["budget_amount"]
        .sum()
        .reset_index()
    )
    return reduced


def build_preaggregated(base_dir: Path) -> tuple[pd.DataFrame, int]:
    files = find_cleaned_budget_files(base_dir)
    if not files:
        raise FileNotFoundError("No cleaned_budget_*.parquet files found.")

    partials: list[pd.DataFrame] = []
    for index, file in enumerate(files, start=1):
        print(f"[{index}/{len(files)}] Aggregating {file.name}...", flush=True)
        partials.append(aggregate_one_file(file))

    combined = pd.concat(partials, ignore_index=True)

    detail_group_cols = [
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
    ]

    final_grouped = (
        combined.groupby(detail_group_cols + ["budget_type"], dropna=False)[
            "budget_amount"
        ]
        .sum()
        .unstack(fill_value=0)
        .reset_index()
    )

    final_grouped["budget_amount_nep"] = final_grouped.get("NEP", 0)
    final_grouped["budget_amount_gaa"] = final_grouped.get("GAA", 0)
    final_grouped["abs_change"] = (
        final_grouped["budget_amount_gaa"] - final_grouped["budget_amount_nep"]
    )
    final_grouped["pct_change"] = final_grouped["abs_change"] / final_grouped[
        "budget_amount_nep"
    ].replace(0, pd.NA)
    final_grouped["is_inserted_budget"] = final_grouped["budget_amount_nep"] == 0
    final_grouped["is_unapproved_budget"] = final_grouped["budget_amount_gaa"] == 0

    source_rows = int(sum(len(partial) for partial in partials))
    return final_grouped, source_rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build preaggregated_budget_details.parquet from cleaned_budget_*.parquet files."
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Directory containing cleaned_budget_*.parquet files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output parquet path. Defaults to <base-dir>/preaggregated_budget_details.parquet",
    )
    args = parser.parse_args()

    base_dir = args.base_dir.resolve()
    output_path = (
        args.output.resolve()
        if args.output is not None
        else base_dir / "preaggregated_budget_details.parquet"
    )

    preaggregated_df, source_rows = build_preaggregated(base_dir)
    preaggregated_df.to_parquet(output_path, index=False)

    print(f"Aggregated source rows: {source_rows:,}")
    print(f"Preaggregated rows: {len(preaggregated_df):,}")
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
