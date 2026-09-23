"""MotherDuck (DuckDB) adapter.

`duckdb` is an optional dependency: capturing, splitting and publishing never need it, and
requiring it would make a 15 MB wheel mandatory for people who only publish layouts. The
import therefore lives inside `connect` and says what to install when it is missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from globalmart.config import TargetProfile
from globalmart.loaders.base import LoadError


class MotherDuckLoader:
    """Loads GlobalMart into a MotherDuck database."""

    def __init__(self, profile: TargetProfile) -> None:
        self.profile = profile
        self._connection: Any | None = None

    @property
    def warehouse(self) -> str:
        return "motherduck"

    def connect(self) -> None:
        try:
            import duckdb
        except ImportError as error:  # pragma: no cover - depends on the environment
            raise LoadError(
                "duckdb is not installed. Install the data extra: `uv sync --extra data`"
            ) from error

        token = self.profile.warehouse_secret()
        if not token:
            raise LoadError(
                f"Profile {self.profile.name!r} names secret env var "
                f"{self.profile.datasource_secret_env!r}, which is unset"
            )
        database = self.profile.warehouse_database or self.profile.datasource_database
        if not database:
            raise LoadError(f"Profile {self.profile.name!r} names no warehouse database")
        self._connection = duckdb.connect(f"md:{database}?motherduck_token={token}")

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _require(self) -> Any:
        if self._connection is None:
            raise LoadError("not connected")
        return self._connection

    def apply_ddl(self, ddl: str) -> None:
        self._require().execute(ddl)

    def existing_tables(self, schema: str) -> set[str]:
        rows = self._require().execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
            [schema],
        ).fetchall()
        return {row[0] for row in rows}

    def row_count(self, schema: str, table: str) -> int:
        row = self._require().execute(f'SELECT count(*) FROM "{schema}"."{table}"').fetchone()
        return int(row[0]) if row else 0

    def max_value(self, schema: str, table: str, column: str) -> str | None:
        cursor = self._require().execute(f'SELECT MAX("{column}") FROM "{schema}"."{table}"')
        row = cursor.fetchone()
        value = row[0] if row else None
        return None if value is None else str(value)

    def columns(self, schema: str, table: str) -> tuple[str, ...]:
        rows = self._require().execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position",
            [schema, table],
        ).fetchall()
        return tuple(row[0] for row in rows)

    def truncate(self, schema: str, table: str) -> None:
        self._require().execute(f'DELETE FROM "{schema}"."{table}"')

    def drop_table(self, schema: str, table: str) -> None:
        self._require().execute(f'DROP TABLE IF EXISTS "{schema}"."{table}"')

    def load_csv(self, schema: str, table: str, csv_path: Path, columns: tuple[str, ...]) -> int:
        connection = self._require()
        # read_csv with an explicit column list, so a CSV whose column order drifted from the
        # DDL fails here rather than loading values into the wrong columns.
        column_list = ", ".join(f'"{column}"' for column in columns)
        connection.execute(
            f'INSERT INTO "{schema}"."{table}" ({column_list}) '
            f"SELECT {column_list} FROM read_csv_auto(?, header=true)",
            [str(csv_path)],
        )
        return self.row_count(schema, table)
