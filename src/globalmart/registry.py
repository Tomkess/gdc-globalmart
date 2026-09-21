"""What tables exist, what columns they have, and what order to touch them in.

Derived from `data/ddl/globalmart.sql` — the DDL is the single source of truth for the
physical schema, so a table added there is known here automatically. The predecessor kept a
hardcoded 214-entry `LOAD_ORDER` list beside the DDL; the two could disagree, and adding a
table meant editing both.

**On load order.** The DDL declares no `PRIMARY KEY` and no `FOREIGN KEY` — zero of either
across all 215 tables — so no warehouse will actually reject a load for ordering reasons
today. Order is derived anyway, from the LDM's `references` graph (dataset ids are 1:1 with
table names), because that graph *is* the real dependency structure whether or not the DDL
enforces it. If constraints are ever added, the ordering is already correct rather than
being discovered to be wrong at that moment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from globalmart.config import GlobalmartError

DEFAULT_DDL_PATH = Path("data/ddl/globalmart.sql")
DEFAULT_TABLES_DIR = Path("data/tables")
DEFAULT_MANIFEST_PATH = Path("data/table-manifest.json")

#: `CREATE TABLE IF NOT EXISTS {schema_name}.<table> (` — the one shape the DDL uses.
_CREATE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?\{schema_name\}\.(\w+)\s*\((.*?)\n\);",
    re.DOTALL | re.IGNORECASE,
)
_COLUMN_RE = re.compile(r"^\s*(\w+)\s+([A-Za-z]+(?:\([\d,\s]+\))?)", re.MULTILINE)

#: The placeholder every statement carries, substituted per target at load time.
SCHEMA_PLACEHOLDER = "{schema_name}"


class RegistryError(GlobalmartError):
    """The DDL could not be read, or does not describe what the data claims."""


@dataclass(frozen=True)
class Column:
    name: str
    sql_type: str


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]

    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


@dataclass(frozen=True)
class TableRegistry:
    """Every table the DDL defines, in a deterministic load order."""

    tables: dict[str, Table]
    #: Load order: a table appears after everything it references.
    load_order: tuple[str, ...]

    def names(self) -> frozenset[str]:
        return frozenset(self.tables)

    def truncate_order(self) -> tuple[str, ...]:
        """Reverse of the load order, so a dependent is emptied before its dimension."""
        return tuple(reversed(self.load_order))

    def require(self, name: str) -> Table:
        table = self.tables.get(name)
        if table is None:
            raise RegistryError(f"{name!r} is not a table this repo knows about")
        return table


def parse_ddl(path: Path = DEFAULT_DDL_PATH) -> dict[str, Table]:
    """Every `CREATE TABLE` in the DDL, with its columns."""
    path = Path(path)
    if not path.exists():
        raise RegistryError(f"No DDL at {path}")

    text = path.read_text(encoding="utf-8")
    tables: dict[str, Table] = {}
    for name, body in _CREATE_RE.findall(text):
        columns = tuple(
            Column(name=column, sql_type=sql_type.strip()) for column, sql_type in _COLUMN_RE.findall(body)
        )
        if not columns:
            raise RegistryError(f"table {name!r} in {path} parsed with zero columns")
        tables[name] = Table(name=name, columns=columns)

    if not tables:
        raise RegistryError(f"{path} contains no CREATE TABLE statements")
    return tables


def _dependency_edges(model: Any | None) -> dict[str, tuple[str, ...]]:
    """`table -> the tables it references`, from the LDM join graph. Empty without a model."""
    if model is None:
        return {}
    from globalmart.prune import build_entity_index

    index = build_entity_index(model.ldm)
    return dict(index.references)


def _topological(names: list[str], edges: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Referenced tables first, then their dependants. Alphabetical within a tier.

    A cycle cannot deadlock the load: whatever is still unplaced when no further progress is
    possible is appended in sorted order. Ordering is a courtesy to constraint-enforcing
    warehouses, not a correctness requirement — there are no constraints to violate.
    """
    remaining = set(names)
    placed: list[str] = []
    seen: set[str] = set()

    while remaining:
        ready = sorted(
            name
            for name in remaining
            if all(target in seen or target not in remaining for target in edges.get(name, ()))
        )
        if not ready:
            placed.extend(sorted(remaining))
            break
        placed.extend(ready)
        seen.update(ready)
        remaining.difference_update(ready)

    return tuple(placed)


def build_registry(ddl_path: Path = DEFAULT_DDL_PATH, *, model: Any | None = None) -> TableRegistry:
    """The table registry, ordered by the LDM join graph when a model is supplied."""
    tables = parse_ddl(ddl_path)
    edges = _dependency_edges(model)
    order = _topological(sorted(tables), {k: v for k, v in edges.items() if k in tables})
    return TableRegistry(tables=tables, load_order=order)


def render_ddl(ddl_path: Path, schema: str) -> str:
    """The DDL with its `{schema_name}` placeholder resolved for one target."""
    return Path(ddl_path).read_text(encoding="utf-8").replace(SCHEMA_PLACEHOLDER, schema)


def foreign_key_target(column_name: str, known_tables: frozenset[str] | set[str]) -> str | None:
    """Resolve a `<base>_id` column to the table that owns it, or ``None``.

    Lives here rather than in the generator because it is a fact about the schema, and the
    generator should not become the second place that knows how tables relate.

    The DDL declares no foreign keys at all, so this is inference from naming — which is
    why an unresolvable `_id` is not an error. `session_id` on a table with no `dim_session`
    is a local identifier, not a dangling reference.
    """
    if not column_name.endswith("_id"):
        return None
    base = column_name[: -len("_id")]
    for candidate in (f"dim_{base}", base, f"fact_{base}"):
        if candidate in known_tables:
            return candidate
    return None


def own_key_column(table: Table, known_tables: frozenset[str] | set[str] | None = None) -> str | None:
    """The column that identifies a row of this table, if one is discernible.

    Prefers an `_id` column whose base matches the table's own name (`dim_customer` ->
    `customer_id`), and falls back to the first `_id` column. A table with none simply has
    no key space for others to draw from.

    The fallback is only safe when the candidate is not a reference to somewhere else.
    `fact_daily_store_sales` has no identity of its own — its grain is a date and a store —
    and taking its first `_id` made it mint `store_id` values of its own instead of drawing
    them from `dim_store`, so the table joined to nothing. Nine tables were affected. Pass
    ``known_tables`` and a candidate that resolves to another table is rejected, leaving the
    column free to be planned as the foreign key it is.
    """
    names = [column.name for column in table.columns if column.name.endswith("_id")]
    if not names:
        return None

    stem = re.sub(r"^(dim|fact)_", "", table.name)
    preferred = f"{stem}_id"
    if preferred in names:
        return preferred

    candidate = names[0]
    if known_tables is not None:
        target = foreign_key_target(candidate, known_tables)
        if target is not None and target != table.name:
            return None
    return candidate
