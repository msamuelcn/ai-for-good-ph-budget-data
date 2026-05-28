import os
import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import sqlalchemy
from google.cloud.alloydb.connector import Connector, IPTypes, RefreshStrategy
from sqlalchemy.engine import Engine

ALLOWED_SCHEMA = "ai_for_good_budget_drift"


class ConfigurationError(RuntimeError):
    pass


class QuerySafetyError(RuntimeError):
    pass


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_ip_type(raw: str) -> IPTypes:
    normalized = raw.strip().upper()
    if normalized == "PRIVATE":
        return IPTypes.PRIVATE
    return IPTypes.PUBLIC


@dataclass(frozen=True)
class DatabaseConfig:
    instance_uri: str
    db_user: str
    db_name: str
    db_password: Optional[str]
    enable_iam_auth: bool
    ip_type: IPTypes
    refresh_strategy: RefreshStrategy

    @staticmethod
    def from_env() -> "DatabaseConfig":
        enable_iam_auth = _read_bool("ALLOYDB_ENABLE_IAM_AUTH", True)
        db_password = os.getenv("ALLOYDB_DB_PASSWORD", "").strip() or None

        if not enable_iam_auth and not db_password:
            raise ConfigurationError(
                "ALLOYDB_DB_PASSWORD is required when ALLOYDB_ENABLE_IAM_AUTH=false"
            )

        refresh_mode = os.getenv("ALLOYDB_CONNECTOR_REFRESH", "LAZY").strip().upper()
        refresh_strategy = (
            RefreshStrategy.BACKGROUND
            if refresh_mode == "BACKGROUND"
            else RefreshStrategy.LAZY
        )

        return DatabaseConfig(
            instance_uri=_require_env("ALLOYDB_INSTANCE_URI"),
            db_user=_require_env("ALLOYDB_DB_USER"),
            db_name=_require_env("ALLOYDB_DB_NAME"),
            db_password=db_password,
            enable_iam_auth=enable_iam_auth,
            ip_type=_parse_ip_type(os.getenv("ALLOYDB_IP_TYPE", "PUBLIC")),
            refresh_strategy=refresh_strategy,
        )


def create_engine(config: Optional[DatabaseConfig] = None) -> Engine:
    cfg = config or DatabaseConfig.from_env()
    connector = Connector(refresh_strategy=cfg.refresh_strategy)

    def getconn():
        return connector.connect(
            cfg.instance_uri,
            "pg8000",
            user=cfg.db_user,
            password=cfg.db_password,
            db=cfg.db_name,
            enable_iam_auth=cfg.enable_iam_auth,
            ip_type=cfg.ip_type,
        )

    return sqlalchemy.create_engine(
        "postgresql+pg8000://",
        creator=getconn,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=2,
    )


def _normalize_sql(sql_query: str) -> str:
    cleaned = re.sub(r"--.*?$", "", sql_query, flags=re.MULTILINE).strip().rstrip(";")
    if ";" in cleaned:
        raise QuerySafetyError("Multiple SQL statements are not allowed")
    return cleaned


def _is_safe_read_query(sql_query: str) -> bool:
    normalized = sql_query.lower().strip()
    if not normalized.startswith(("select", "with")):
        return False

    blocked = [
        " insert ",
        " update ",
        " delete ",
        " drop ",
        " alter ",
        " truncate ",
        " grant ",
        " revoke ",
        " create ",
    ]
    haystack = f" {normalized} "
    return not any(token in haystack for token in blocked)


def run_readonly_query(
    engine: Engine,
    sql_query: str,
    row_limit: int = 500,
) -> pd.DataFrame:
    cleaned = _normalize_sql(sql_query)
    if not _is_safe_read_query(cleaned):
        raise QuerySafetyError("Only read-only SELECT/WITH queries are allowed")

    wrapped_query = f"SELECT * FROM ({cleaned}) AS result LIMIT {int(row_limit)}"

    with engine.connect() as connection:
        return pd.read_sql(sqlalchemy.text(wrapped_query), connection)


def fetch_schema_context(engine: Engine) -> str:
    query = sqlalchemy.text("""
        SELECT
            c.table_name,
            c.column_name,
            c.data_type,
            c.ordinal_position
        FROM information_schema.columns c
        WHERE c.table_schema = :schema
          AND c.table_name IN ('detected_anomaly', 'preaggregated_budget_details')
        ORDER BY c.table_name, c.ordinal_position
        """)

    with engine.connect() as connection:
        rows = connection.execute(
            query,
            {
                "schema": ALLOWED_SCHEMA,
            },
        ).fetchall()

    if not rows:
        raise RuntimeError(
            "No schema metadata found. Check table names/schema and DB permissions."
        )

    table_map: dict[str, list[str]] = {}
    for row in rows:
        column_def = f"{row.column_name} ({row.data_type})"
        table_map.setdefault(row.table_name, []).append(column_def)

    lines = [f"Schema: {ALLOWED_SCHEMA}"]
    for table_name, columns in table_map.items():
        lines.append(f"Table: {ALLOWED_SCHEMA}.{table_name}")
        lines.append("Columns:")
        lines.extend([f"- {column}" for column in columns])
        lines.append("")

    return "\n".join(lines).strip()
