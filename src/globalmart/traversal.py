"""The one place that knows *where* datasource ids and schema references live.

Both directions consume these generators: ``normalize`` replaces real values with
placeholders on capture, ``resolve`` replaces placeholders with real values on publish. If
the two enumerated slots separately they could drift, and a slot one side missed would be
silently left carrying the wrong org's identifier.

That is exactly how the predecessor failed. It rewrote the datasource with
``json.dumps(model).replace('"globalmart-postgres"', ...)`` over serialized JSON — a no-op,
because the layout actually carried ``globalmart-motherduck``. Nothing raised. Stale
references shipped.

``iter_all_string_fields`` exists for the post-resolution assertion: a defensive full walk
that catches a token hiding in a field nobody thought to enumerate.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, NamedTuple

from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)


class DataSourceSlot(NamedTuple):
    """One readable/writable datasource reference, with a path for error messages."""

    path: str
    get: Callable[[], str | None]
    set: Callable[[str], None]


class SqlStatementSlot(NamedTuple):
    """One SQL statement, with the dataset id that owns it."""

    dataset_id: str
    get: Callable[[], str]
    set: Callable[[str], None]


def _datasets(model: CatalogDeclarativeWorkspaceModel) -> list[Any]:
    ldm = model.ldm
    if ldm is None:
        return []
    return list(ldm.datasets or [])


def iter_datasource_slots(model: CatalogDeclarativeWorkspaceModel) -> Iterator[DataSourceSlot]:
    """Yield every place a dataset names its datasource.

    Two shapes, mutually exclusive on the real GlobalMart parent: a table-backed dataset
    carries ``data_source_table_id.data_source_id``, a SQL-backed one ``sql.data_source_id``.
    Measured 2026-09-18: 225 datasets = 214 table-backed + 11 SQL-backed, none carrying
    both, so this yields exactly 225 slots. A dataset carrying both would yield two, and
    every consumer handles that correctly.
    """
    for dataset in _datasets(model):
        table_id = getattr(dataset, "data_source_table_id", None)
        if table_id is not None:
            yield DataSourceSlot(
                path=f"ldm.datasets[{dataset.id}].dataSourceTableId.dataSourceId",
                get=lambda t=table_id: getattr(t, "data_source_id", None),  # type: ignore[misc]
                set=lambda value, t=table_id: setattr(t, "data_source_id", value),  # type: ignore[misc]
            )

        sql = getattr(dataset, "sql", None)
        if sql is not None:
            yield DataSourceSlot(
                path=f"ldm.datasets[{dataset.id}].sql.dataSourceId",
                get=lambda s=sql: getattr(s, "data_source_id", None),  # type: ignore[misc]
                set=lambda value, s=sql: setattr(s, "data_source_id", value),  # type: ignore[misc]
            )


def iter_sql_statements(model: CatalogDeclarativeWorkspaceModel) -> Iterator[SqlStatementSlot]:
    """Yield every SQL-backed dataset's statement. 11 on the real parent."""
    for dataset in _datasets(model):
        sql = getattr(dataset, "sql", None)
        if sql is None:
            continue
        yield SqlStatementSlot(
            dataset_id=str(dataset.id),
            get=lambda s=sql: s.statement or "",  # type: ignore[misc]
            set=lambda value, s=sql: setattr(s, "statement", value),  # type: ignore[misc]
        )


def iter_all_string_fields(model: CatalogDeclarativeWorkspaceModel) -> Iterator[tuple[str, str]]:
    """Walk the whole serialized model, yielding ``(path, value)`` for every string.

    Deliberately exhaustive rather than targeted: the enumerations above are the fast path,
    this is the safety net that catches a placeholder or a foreign datasource id hiding
    somewhere nobody modelled — a metric description, a dashboard's untyped ``content``
    blob, a field added by a future API version.
    """

    def walk(node: Any, path: str) -> Iterator[tuple[str, str]]:
        if isinstance(node, str):
            yield path, node
        elif isinstance(node, dict):
            for key, value in node.items():
                yield from walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                yield from walk(item, f"{path}[{index}]")

    yield from walk(model.to_dict(camel_case=True), "")
