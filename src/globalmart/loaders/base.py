"""The warehouse-agnostic half of loading.

One adapter per warehouse, one protocol, and every decision that is not warehouse-specific
made here — so "does Postgres behave the same as MotherDuck" is answered by the adapter
being 60 lines rather than by reading two loaders and comparing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from globalmart.config import GlobalmartError


class LoadError(GlobalmartError):
    """A load could not be completed."""


@dataclass
class TableLoad:
    """What happened to one table."""

    table: str
    rows_before: int = 0
    rows_after: int = 0
    loaded: bool = False
    error: str | None = None


@dataclass
class LoadReport:
    """What a whole load did. Printed by the CLI, asserted by the tests."""

    target: str
    schema: str
    warehouse: str
    applied: bool
    tables: list[TableLoad] = field(default_factory=list)
    #: Row counts per table read **before** anything was truncated (ADR 004). This is the
    #: record of what was overwritten, and it is taken even in a rehearsal.
    census: dict[str, int] = field(default_factory=dict)
    unknown_tables: tuple[str, ...] = ()

    def rows_loaded(self) -> int:
        return sum(entry.rows_after for entry in self.tables)

    def rows_overwritten(self) -> int:
        return sum(self.census.values())

    def summary_lines(self) -> list[str]:
        lines = [
            f"target            : {self.target} ({self.warehouse}, schema {self.schema})",
            f"tables            : {len(self.tables)}",
            f"rows before       : {self.rows_overwritten():,}",
            f"rows after        : {self.rows_loaded():,}",
            f"applied           : {self.applied}",
        ]
        if self.unknown_tables:
            lines.append(f"UNKNOWN in schema : {', '.join(self.unknown_tables)}")
        failed = [entry.table for entry in self.tables if entry.error]
        if failed:
            lines.append(f"FAILED            : {', '.join(failed)}")
        return lines


class WarehouseLoader(Protocol):
    """What a warehouse must be able to do to receive GlobalMart.

    Deliberately small. Everything else — which tables, what order, whether a load is
    allowed at all — is decided once, in `dataload.py`, for every warehouse.
    """

    def connect(self) -> None: ...

    def close(self) -> None: ...

    def apply_ddl(self, ddl: str) -> None:
        """Create the schema and every table. Must be safe to run repeatedly."""

    def existing_tables(self, schema: str) -> set[str]:
        """Every table currently in the schema, whether this repo knows it or not."""

    def row_count(self, schema: str, table: str) -> int: ...

    def max_value(self, schema: str, table: str, column: str) -> str | None:
        """The largest value in one column, or ``None`` when the table is empty.

        Used to ask how recent the loaded data is. A warehouse that holds rows is not the
        same as a warehouse that holds *current* rows, and only the second is useful to a
        dashboard whose filters are relative.
        """

    def truncate(self, schema: str, table: str) -> None: ...

    def load_csv(self, schema: str, table: str, csv_path: Path, columns: tuple[str, ...]) -> int:
        """Insert every row of an uncompressed CSV. Returns the number of rows inserted."""
