"""Do the 11 SQL-backed datasets actually run against the loaded schema?

This is the check that would have caught `sql_channel_attribution` years ago. It selects
`FROM {{ datasource_schema }}.fact_search_event`, a table for which no DDL and no CSV has
ever existed — so the dataset was broken from the day it was written, and nothing in the
pipeline noticed, because a layout publishes fine whether or not its SQL can run.

Two levels, cheapest first:

- **static** — every table a statement names must exist in the registry. Offline, no
  warehouse, runs in CI.
- **live** — the statement is actually executed (wrapped in `SELECT * FROM (...) LIMIT 0`,
  so the plan is built and the columns resolved without moving rows). Needs a loaded
  warehouse.

The static pass is the one that matters for a cold rebuild: it fails on a missing table
without needing credentials at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from globalmart.config import GlobalmartError
from globalmart.normalize import DATASOURCE_SCHEMA_TOKEN
from globalmart.registry import TableRegistry
from globalmart.traversal import iter_sql_statements

#: `FROM <schema>.<table>` and `JOIN <schema>.<table>`, the only two ways these statements
#: name a table. Matched after the schema placeholder has been substituted.
_TABLE_REF_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)", re.IGNORECASE)


class SqlCheckError(GlobalmartError):
    """A SQL-backed dataset cannot run against the loaded schema."""


@dataclass
class SqlDatasetCheck:
    """One dataset's verdict."""

    dataset_id: str
    tables: tuple[str, ...] = ()
    missing_tables: tuple[str, ...] = ()
    executed: bool = False
    error: str | None = None

    def ok(self) -> bool:
        return not self.missing_tables and self.error is None


@dataclass
class SqlCheckReport:
    checks: list[SqlDatasetCheck] = field(default_factory=list)

    def ok(self) -> bool:
        return all(check.ok() for check in self.checks)

    def failures(self) -> list[SqlDatasetCheck]:
        return [check for check in self.checks if not check.ok()]

    def summary_lines(self) -> list[str]:
        lines = [f"sql datasets      : {len(self.checks)}"]
        executed = sum(1 for check in self.checks if check.executed)
        if executed:
            lines.append(f"executed live     : {executed}")
        for check in self.failures():
            detail = (
                f"missing table(s): {', '.join(check.missing_tables)}"
                if check.missing_tables
                else check.error
            )
            lines.append(f"  FAILED {check.dataset_id}: {detail}")
        return lines


def referenced_tables(statement: str, schema: str) -> tuple[str, ...]:
    """Every `<schema>.<table>` the statement names, unqualified and deduplicated."""
    resolved = statement.replace(DATASOURCE_SCHEMA_TOKEN, schema)
    found = {
        table
        for found_schema, table in _TABLE_REF_RE.findall(resolved)
        if found_schema.lower() == schema.lower()
    }
    return tuple(sorted(found))


def check_sql_datasets(
    model: Any,
    registry: TableRegistry,
    *,
    schema: str,
    loader: Any | None = None,
) -> SqlCheckReport:
    """Static check always; live execution too when a connected loader is supplied."""
    report = SqlCheckReport()

    for slot in iter_sql_statements(model):
        statement = slot.get() or ""
        tables = referenced_tables(statement, schema)
        check = SqlDatasetCheck(
            dataset_id=slot.dataset_id,
            tables=tables,
            missing_tables=tuple(t for t in tables if t not in registry.names()),
        )

        if loader is not None and not check.missing_tables:
            resolved = statement.replace(DATASOURCE_SCHEMA_TOKEN, schema)
            try:
                # LIMIT 0: the planner resolves every column and join without moving rows.
                loader.execute(f"SELECT * FROM ({resolved}) AS _check LIMIT 0")
                check.executed = True
            except Exception as error:  # noqa: BLE001 - reported per dataset
                check.error = str(error)

        report.checks.append(check)

    return report


def raise_for_sql_report(report: SqlCheckReport) -> None:
    failures = report.failures()
    if not failures:
        return
    listed = "\n  ".join(
        f"{check.dataset_id}: "
        + (
            f"references table(s) that do not exist: {', '.join(check.missing_tables)}"
            if check.missing_tables
            else str(check.error)
        )
        for check in failures
    )
    raise SqlCheckError(f"{len(failures)} SQL dataset(s) cannot run:\n  {listed}")


def ddl_path_default() -> Path:
    from globalmart.registry import DEFAULT_DDL_PATH

    return DEFAULT_DDL_PATH
