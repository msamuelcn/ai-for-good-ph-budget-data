from __future__ import annotations

from pathlib import Path
import argparse
import os

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from google.cloud.alloydb.connector import Connector, IPTypes

DEFAULT_SCHEMA = "ai_for_good_budget_drift"


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [col.lower() for col in df.columns]
    return df


def coerce_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = normalize_columns(df)

    for column in df.columns:
        if df[column].dtype == "object":
            df[column] = df[column].where(df[column].notna(), None)

    return df


def load_parquet_file(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    return coerce_dataframe(df)


def get_engine() -> Engine:
    use_connector = os.environ.get("ALLOYDB_USE_CONNECTOR", "true").lower() == "true"
    if use_connector:
        return get_engine_with_connector()
    return get_engine_with_direct_host()


def get_engine_with_direct_host() -> Engine:
    host = os.environ["ALLOYDB_HOST"]
    port = os.environ.get("ALLOYDB_PORT", "5432")
    database = os.environ["ALLOYDB_DATABASE"]
    username = os.environ["ALLOYDB_USER"]
    password = os.environ["ALLOYDB_PASSWORD"]

    url = f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{database}"
    return create_engine(url, pool_pre_ping=True)


def get_engine_with_connector() -> Engine:
    instance_uri = os.environ["ALLOYDB_INSTANCE_URI"]
    database = os.environ["ALLOYDB_DATABASE"]
    username = os.environ["ALLOYDB_USER"]
    password = os.environ["ALLOYDB_PASSWORD"]
    ip_type_name = os.environ.get("ALLOYDB_IP_TYPE", "PRIVATE").upper()
    ip_type = IPTypes.PRIVATE if ip_type_name == "PRIVATE" else IPTypes.PUBLIC

    connector = Connector()

    def get_connection() -> object:
        return connector.connect(
            instance_uri,
            "pg8000",
            user=username,
            password=password,
            db=database,
            ip_type=ip_type,
        )

    # NOTE: creator callback follows the official connector integration pattern.
    engine = create_engine(
        "postgresql+pg8000://", creator=get_connection, pool_pre_ping=True
    )
    return engine


def prepare_table(engine, schema: str, table_name: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        connection.execute(text(f"TRUNCATE TABLE {schema}.{table_name}"))


def bulk_insert(engine, schema: str, table_name: str, df: pd.DataFrame) -> None:
    if df.empty:
        print(f"Skipping empty dataframe for {table_name}")
        return

    df.to_sql(
        table_name,
        engine,
        schema=schema,
        if_exists="append",
        index=False,
        chunksize=5000,
        method="multi",
    )


def load_one(engine, schema: str, table_name: str, parquet_path: Path) -> None:
    print(f"Loading {parquet_path.name} -> {schema}.{table_name}")
    dataframe = load_parquet_file(parquet_path)
    print(f"Rows: {len(dataframe):,}")
    prepare_table(engine, schema, table_name)
    bulk_insert(engine, schema, table_name, dataframe)
    print(f"Done: {schema}.{table_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load parquet datasets into AlloyDB.")
    parser.add_argument(
        "--schema",
        default=DEFAULT_SCHEMA,
        help="Target AlloyDB schema name.",
    )
    parser.add_argument(
        "--detected-anomaly",
        type=Path,
        default=Path("detected_anomaly.parquet"),
        help="Path to detected_anomaly.parquet",
    )
    parser.add_argument(
        "--preaggregated-budget",
        type=Path,
        default=Path("preaggregated_budget_details.parquet"),
        help="Path to preaggregated_budget_details.parquet",
    )
    args = parser.parse_args()

    engine = get_engine()

    load_one(engine, args.schema, "detected_anomaly", args.detected_anomaly)
    load_one(
        engine,
        args.schema,
        "preaggregated_budget_details",
        args.preaggregated_budget,
    )

    with engine.begin() as connection:
        connection.execute(text(f"ANALYZE {args.schema}.detected_anomaly"))
        connection.execute(text(f"ANALYZE {args.schema}.preaggregated_budget_details"))

    print("All data loaded successfully.")


if __name__ == "__main__":
    main()
