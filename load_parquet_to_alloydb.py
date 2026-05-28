from __future__ import annotations

from pathlib import Path
import argparse
import os

import duckdb
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from google.cloud.alloydb.connector import Connector, IPTypes

DEFAULT_SCHEMA = "ai_for_good_budget_drift"
DEFAULT_BATCH_SIZE = 100_000
DEFAULT_DB_CHUNKSIZE = 10_000

connector = Connector()


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
    password = os.environ.get("ALLOYDB_PASSWORD", "")
    use_iam_auth = os.environ.get("ALLOYDB_ENABLE_IAM_AUTH", "true").lower() == "true"

    ip_type_name = os.environ.get("ALLOYDB_IP_TYPE", "PUBLIC").upper()
    ip_type = IPTypes.PUBLIC if ip_type_name == "PUBLIC" else IPTypes.PRIVATE

    def get_connection() -> object:
        return connector.connect(
            instance_uri,
            "pg8000",
            user=username,
            password=password,
            db=database,
            enable_iam_auth=use_iam_auth,
            ip_type=ip_type,
        )

    return create_engine("postgresql+pg8000://", creator=get_connection, pool_pre_ping=True)


def prepare_table(engine: Engine, schema: str, table_name: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        connection.execute(text(f"TRUNCATE TABLE {schema}.{table_name}"))


def count_rows_from_parquet(duck_connection: duckdb.DuckDBPyConnection, parquet_path: Path) -> int:
    return int(
        duck_connection.execute(
            "SELECT COUNT(*) FROM read_parquet(?)",
            [str(parquet_path)],
        ).fetchone()[0]
    )


def fetch_batch_from_parquet(
    duck_connection: duckdb.DuckDBPyConnection,
    parquet_path: Path,
    batch_size: int,
    offset: int,
) -> pd.DataFrame:
    query = (
        "SELECT * FROM read_parquet(?) "
        f"LIMIT {int(batch_size)} OFFSET {int(offset)}"
    )
    batch = duck_connection.execute(query, [str(parquet_path)]).df()
    return coerce_dataframe(batch)


def insert_batch(
    engine: Engine,
    schema: str,
    table_name: str,
    dataframe: pd.DataFrame,
    db_chunksize: int,
) -> int:
    with engine.begin() as connection:
        dataframe.to_sql(
            table_name,
            connection,
            schema=schema,
            if_exists="append",
            index=False,
            chunksize=db_chunksize,
            method=None,
        )
    return len(dataframe)


def count_rows_in_table(
    engine: Engine,
    schema: str,
    table_name: str,
) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT COUNT(*) FROM {schema}.{table_name}")).scalar_one())


def load_one(
    engine: Engine,
    schema: str,
    table_name: str,
    parquet_path: Path,
    batch_size: int,
    db_chunksize: int,
) -> None:
    print(f"Loading {parquet_path.name} -> {schema}.{table_name}")
    if not parquet_path.exists():
        raise FileNotFoundError(f"Missing parquet file: {parquet_path}")

    prepare_table(engine, schema, table_name)

    duck_connection = duckdb.connect(database=":memory:")
    total_rows = count_rows_from_parquet(duck_connection, parquet_path)
    print(f"Source rows: {total_rows:,}")

    if total_rows == 0:
        print(f"Skipping empty source for {table_name}")
        return

    loaded_rows = 0
    batch_no = 0
    while loaded_rows < total_rows:
        batch_no += 1
        batch_df = fetch_batch_from_parquet(
            duck_connection,
            parquet_path,
            batch_size,
            loaded_rows,
        )
        if batch_df.empty:
            break

        inserted = insert_batch(engine, schema, table_name, batch_df, db_chunksize)
        loaded_rows += inserted
        progress = (loaded_rows / total_rows) * 100
        print(
            f"Batch {batch_no:>4}: +{inserted:,} rows | total={loaded_rows:,}/{total_rows:,} ({progress:,.2f}%)"
        )

    inserted_rows = count_rows_in_table(engine, schema, table_name)
    print(f"Inserted rows in database: {inserted_rows:,}")
    if inserted_rows != total_rows:
        raise RuntimeError(
            f"Row count mismatch for {table_name}: source={total_rows:,}, loaded={inserted_rows:,}"
        )

    print(f"Done: {schema}.{table_name}")
    duck_connection.close()


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
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Rows read from parquet per batch.",
    )
    parser.add_argument(
        "--db-chunksize",
        type=int,
        default=DEFAULT_DB_CHUNKSIZE,
        help="Rows per database insert chunk in pandas.to_sql.",
    )
    args = parser.parse_args()

    engine = get_engine()

    load_one(
        engine,
        args.schema,
        "detected_anomaly",
        args.detected_anomaly,
        args.batch_size,
        args.db_chunksize,
    )

    load_one(
        engine,
        args.schema,
        "preaggregated_budget_details",
        args.preaggregated_budget,
        args.batch_size,
        args.db_chunksize,
    )

    with engine.begin() as connection:
        connection.execute(text(f"ANALYZE {args.schema}.detected_anomaly"))
        connection.execute(text(f"ANALYZE {args.schema}.preaggregated_budget_details"))

    print("All data loaded successfully.")


if __name__ == "__main__":
    main()
