from __future__ import annotations

from pathlib import Path
import argparse

import pandas as pd


def to_partition_safe(value: object) -> str:
    return str(value).replace("/", "_").replace("\\", "_").strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build scoped preaggregated parquet folders from preaggregated_budget_details.parquet."
        )
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Workspace directory containing the preaggregated parquet.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help=(
            "Source parquet path. Defaults to <base-dir>/preaggregated_budget_details.parquet"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Output folder for scoped files. Defaults to <base-dir>/preaggregated_budget_details_scoped"
        ),
    )
    args = parser.parse_args()

    base_dir = args.base_dir.resolve()
    source_path = (
        args.source.resolve()
        if args.source is not None
        else base_dir / "preaggregated_budget_details.parquet"
    )
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else base_dir / "preaggregated_budget_details_scoped"
    )

    if not source_path.exists():
        raise FileNotFoundError(
            f"Missing source parquet: {source_path}. Run build_preaggregated_budget_details.py first."
        )

    df = pd.read_parquet(source_path)
    df.columns = [col.lower() for col in df.columns]

    required = {"fiscal_year", "department_code"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Source parquet is missing required columns: {missing}")

    output_dir.mkdir(parents=True, exist_ok=True)

    grouped = df.groupby(["fiscal_year", "department_code"], dropna=False, sort=False)

    total_groups = grouped.ngroups
    written = 0
    total_rows = 0

    for idx, ((fiscal_year, department_code), chunk) in enumerate(grouped, start=1):
        fiscal_year_int = int(fiscal_year)
        dept_code_safe = to_partition_safe(department_code)
        target_dir = (
            output_dir
            / f"fiscal_year={fiscal_year_int}"
            / f"department_code={dept_code_safe}"
        )
        target_dir.mkdir(parents=True, exist_ok=True)

        target_file = target_dir / "data.parquet"
        chunk.to_parquet(target_file, index=False)

        written += 1
        total_rows += len(chunk)
        print(
            f"[{idx}/{total_groups}] Wrote {target_file.relative_to(base_dir)} ({len(chunk):,} rows)",
            flush=True,
        )

    print(f"Source rows: {len(df):,}")
    print(f"Written scoped files: {written:,}")
    print(f"Written scoped rows: {total_rows:,}")
    print(f"Output directory: {output_dir}")


if __name__ == "__main__":
    main()
