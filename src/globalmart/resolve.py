"""Rebind a tree's data source to one target's, then prove nothing else survived.

The committed tree (``gd_data_product/globalmart/``, ADR 011 Stage B) carries one concrete data
source: the canonical id and schema in ``config.env.yml``. Publishing to a profile whose data
source differs rewrites every reference from the canonical pair to the profile's; when they
match — every gdcloud environment — the rewrite is a no-op and says so.

``assert_fully_resolved`` is the whole point of the module. The predecessor substituted its
datasource with a string replace of a literal that was not in the file, so the substitution
did nothing and *nothing raised* — a workspace shipped pointing at another org's datasource.
Here, every publish path runs the assertion, and it walks the entire serialized model rather
than only the slots that were rewritten, so a leftover ``{{ ... }}`` placeholder, a foreign
datasource id or a foreign table schema anywhere is caught.

Every function is pure and host-free: no SDK client, no network, fully testable offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.config import GlobalmartError
from globalmart.gdcloud_bridge import CanonicalDataSource
from globalmart.traversal import (
    iter_all_string_fields,
    iter_datasource_slots,
    iter_sql_statements,
    iter_table_schema_slots,
)

#: Any unresolved ``{{ ... }}`` placeholder — the retired Stage A form, or a token nobody
#: anticipated. Either one reaching an org is a defect.
_ANY_PLACEHOLDER = re.compile(r"\{\{\s*[\w.]+\s*\}\}")


class UnresolvedLayoutError(GlobalmartError):
    """A layout carries a placeholder, or a datasource id or schema other than the target's."""


@dataclass
class ResolveResult:
    """What the rewrite did, printed in the publish plan."""

    model: CatalogDeclarativeWorkspaceModel
    source: CanonicalDataSource
    target: CanonicalDataSource
    datasource_refs_rewritten: int = 0
    table_schemas_rewritten: int = 0
    sql_statements_rewritten: int = 0
    unresolved_paths: list[str] = field(default_factory=list)
    foreign_datasource_ids: dict[str, int] = field(default_factory=dict)

    @property
    def is_noop(self) -> bool:
        return self.source == self.target

    def summary_lines(self) -> list[str]:
        if self.is_noop:
            return [
                f"data source rewrite        : none — the tree already carries "
                f"{self.target.datasource_id} / {self.target.datasource_schema}"
            ]
        return [
            f"data source rewrite        : {self.source.datasource_id} / {self.source.datasource_schema}"
            f" -> {self.target.datasource_id} / {self.target.datasource_schema}",
            f"datasource refs rewritten  : {self.datasource_refs_rewritten}",
            f"table schemas rewritten    : {self.table_schemas_rewritten}",
            f"SQL statements rewritten   : {self.sql_statements_rewritten}",
        ]


def _schema_pattern(schema: str) -> re.Pattern[str]:
    """Match the schema only as a whole dotted identifier prefix.

    ``globalmart.fact_orders`` matches; a column called ``globalmart_id``, an alias
    ``my_globalmart`` or ``globalmart_rebuild.fact_orders`` does not. Optional double quotes
    cover a quoted identifier.
    """
    escaped = re.escape(schema)
    return re.compile(rf'(?<![\w"]) "?{escaped}"? \s* \. \s*', re.VERBOSE)


def rewrite_data_source(
    model: CatalogDeclarativeWorkspaceModel,
    *,
    source: CanonicalDataSource,
    target: CanonicalDataSource,
) -> ResolveResult:
    """Rewrite the canonical data source to the target's, in place. A no-op when they match.

    Structured traversal, never a string replace over serialized JSON: only a slot holding the
    canonical value is rewritten, so anything else (a foreign id, a placeholder) is left for
    ``assert_fully_resolved`` to report rather than silently overwritten.
    """
    result = ResolveResult(model=model, source=source, target=target)
    if result.is_noop:
        return result

    if source.datasource_id != target.datasource_id:
        for slot in iter_datasource_slots(model):
            if slot.get() == source.datasource_id:
                slot.set(target.datasource_id)
                result.datasource_refs_rewritten += 1

    if source.datasource_schema != target.datasource_schema:
        for table_slot in iter_table_schema_slots(model):
            if table_slot.get() == source.datasource_schema:
                table_slot.set(target.datasource_schema)
                result.table_schemas_rewritten += 1

        # SQL is text, so the schema is replaced as a whole dotted identifier, never as a bare
        # substring — `globalmart_id` is a column, not a schema reference.
        pattern = _schema_pattern(source.datasource_schema)
        for sql_slot in iter_sql_statements(model):
            replaced, count = pattern.subn(f"{target.datasource_schema}.", sql_slot.get())
            if count:
                sql_slot.set(replaced)
                result.sql_statements_rewritten += 1

    return result


def audit_resolution(
    model: CatalogDeclarativeWorkspaceModel,
    *,
    datasource_id: str,
    datasource_schema: str | None = None,
) -> tuple[list[str], dict[str, int]]:
    """Find every unresolved placeholder, every foreign datasource id and every foreign schema.

    Returns ``(unresolved_paths, foreign)`` rather than raising, so a caller can report before
    deciding to fail. ``foreign`` counts datasource ids and, when ``datasource_schema`` is
    given, table schemas (as ``schema:<name>``) other than the target's.
    """
    unresolved: list[str] = []
    for path, value in iter_all_string_fields(model):
        if _ANY_PLACEHOLDER.search(value):
            unresolved.append(path)

    foreign: dict[str, int] = {}
    for slot in iter_datasource_slots(model):
        current = slot.get()
        if current is not None and current != datasource_id:
            foreign[current] = foreign.get(current, 0) + 1

    if datasource_schema is not None:
        for table_slot in iter_table_schema_slots(model):
            schema = table_slot.get()
            if schema is not None and schema != datasource_schema:
                key = f"schema:{schema}"
                foreign[key] = foreign.get(key, 0) + 1

    return unresolved, foreign


def assert_fully_resolved(
    model: CatalogDeclarativeWorkspaceModel,
    *,
    datasource_id: str,
    datasource_schema: str | None = None,
) -> None:
    """Raise unless no placeholder survives and every datasource id and schema is the target's.

    This is the guard the predecessor lacked. It runs on every publish path, including the
    rehearsal, so a layout that would ship pointing at the wrong warehouse fails before a
    single byte reaches the host.
    """
    unresolved, foreign = audit_resolution(
        model, datasource_id=datasource_id, datasource_schema=datasource_schema
    )
    if not unresolved and not foreign:
        return

    problems: list[str] = []
    if unresolved:
        shown = ", ".join(unresolved[:5])
        more = f" (+{len(unresolved) - 5} more)" if len(unresolved) > 5 else ""
        problems.append(f"{len(unresolved)} unresolved placeholder(s) at: {shown}{more}")
    if foreign:
        rendered = ", ".join(f"{k!r} x{v}" for k, v in sorted(foreign.items()))
        problems.append(
            f"datasource id(s) or schema(s) other than {datasource_id!r}"
            f"{f' / {datasource_schema!r}' if datasource_schema else ''}: {rendered}. "
            "Publishing would point this workspace at another org's warehouse."
        )

    raise UnresolvedLayoutError("; ".join(problems))


def resolve_and_assert(
    model: CatalogDeclarativeWorkspaceModel,
    *,
    canonical: CanonicalDataSource,
    datasource_id: str,
    datasource_schema: str,
) -> ResolveResult:
    """Rewrite, then prove it worked. The only entry point a publish path should use."""
    target = CanonicalDataSource(datasource_id=datasource_id, datasource_schema=datasource_schema)
    result = rewrite_data_source(model, source=canonical, target=target)
    assert_fully_resolved(model, datasource_id=datasource_id, datasource_schema=datasource_schema)
    return result
