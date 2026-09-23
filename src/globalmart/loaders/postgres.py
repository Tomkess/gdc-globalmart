"""Postgres adapter.

Uses `COPY ... FROM STDIN WITH CSV HEADER`, which is the only way to load 174k rows without
a round trip per row, and names its columns explicitly so a CSV whose column order drifted
from the DDL fails rather than silently transposing values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from globalmart.config import TargetProfile
from globalmart.loaders.base import LoadError


class PostgresLoader:
    """Loads GlobalMart into a Postgres schema."""

    def __init__(self, profile: TargetProfile) -> None:
        self.profile = profile
        self._connection: Any | None = None

    @property
    def warehouse(self) -> str:
        return "postgres"

    def connect(self) -> None:
        try:
            import psycopg
        except ImportError as error:  # pragma: no cover - depends on the environment
            raise LoadError(
                "psycopg is not installed. Install the data extra: `uv sync --extra data`"
            ) from error

        password = self.profile.warehouse_secret()
        if not password:
            raise LoadError(
                f"Profile {self.profile.name!r} names secret env var "
                f"{self.profile.datasource_secret_env!r}, which is unset"
            )
        self._connection = psycopg.connect(
            host=self.profile.datasource_url,
            dbname=self.profile.datasource_database,
            user=self.profile.datasource_username,
            password=password,
            autocommit=True,
        )

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _require(self) -> Any:
        if self._connection is None:
            raise LoadError("not connected")
        return self._connection

    def apply_ddl(self, ddl: str) -> None:
        with self._require().cursor() as cursor:
            cursor.execute(ddl)

    def existing_tables(self, schema: str) -> set[str]:
        with self._require().cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
                (schema,),
            )
            return {row[0] for row in cursor.fetchall()}

    def row_count(self, schema: str, table: str) -> int:
        with self._require().cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM "{schema}"."{table}"')
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def max_value(self, schema: str, table: str, column: str) -> str | None:
        with self._require().cursor() as cursor:
            cursor.execute(f'SELECT MAX("{column}") FROM "{schema}"."{table}"')
            row = cursor.fetchone()
            value = row[0] if row else None
            return None if value is None else str(value)

    def columns(self, schema: str, table: str) -> tuple[str, ...]:
        with self._require().cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                (schema, table),
            )
            return tuple(row[0] for row in cursor.fetchall())

    def truncate(self, schema: str, table: str) -> None:
        with self._require().cursor() as cursor:
            cursor.execute(f'TRUNCATE TABLE "{schema}"."{table}"')

    def drop_table(self, schema: str, table: str) -> None:
        with self._require().cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS "{schema}"."{table}" CASCADE')

    def load_csv(self, schema: str, table: str, csv_path: Path, columns: tuple[str, ...]) -> int:
        column_list = ", ".join(f'"{column}"' for column in columns)
        statement = f'COPY "{schema}"."{table}" ({column_list}) FROM STDIN WITH (FORMAT csv, HEADER true)'
        with (
            self._require().cursor() as cursor,
            csv_path.open("rb") as handle,
            cursor.copy(statement) as copy,
        ):
            while chunk := handle.read(1 << 20):
                copy.write(chunk)
        return self.row_count(schema, table)
