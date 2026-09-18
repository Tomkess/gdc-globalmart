"""Resolve placeholders in a layout for one target, then prove none survived.

The inverse of ``normalize``: the committed tree carries ``{{ datasource_id }}`` and
``{{ datasource_schema }}``, and publishing to an org substitutes that org's real values.

``assert_fully_resolved`` is the whole point of the module. The predecessor substituted its
datasource with a string replace of a literal that was not in the file, so the substitution
did nothing and *nothing raised* — a workspace shipped pointing at another org's datasource.
Here, every publish path runs the assertion, and it walks the entire serialized model rather
than only the slots that were rewritten, so a token hiding anywhere is caught.

Both functions are pure and host-free: no SDK client, no network, fully testable offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.config import GlobalmartError
from globalmart.normalize import DATASOURCE_SCHEMA_TOKEN
from globalmart.traversal import (
    iter_all_string_fields,
    iter_datasource_slots,
    iter_sql_statements,
)

#: Any unresolved ``{{ ... }}`` placeholder, so a token nobody anticipated is still caught.
_ANY_PLACEHOLDER = re.compile(r"\{\{\s*[\w.]+\s*\}\}")


class UnresolvedLayoutError(GlobalmartError):
    """A layout still carries a placeholder, or a datasource id other than the target's."""


@dataclass
class ResolveResult:
    """What resolution did — deliberately parallel to ``NormalizeResult``."""

    model: CatalogDeclarativeWorkspaceModel
    datasource_refs_resolved: int = 0
    sql_statements_resolved: int = 0
    schema_substitutions: int = 0
    unresolved_paths: list[str] = field(default_factory=list)
    foreign_datasource_ids: dict[str, int] = field(default_factory=dict)

    def summary_lines(self) -> list[str]:
        return [
            f"datasource refs resolved   : {self.datasource_refs_resolved}",
            f"SQL statements resolved    : {self.sql_statements_resolved}",
            f"schema substitutions       : {self.schema_substitutions}",
        ]


def resolve_placeholders(
    model: CatalogDeclarativeWorkspaceModel,
    *,
    datasource_id: str,
    datasource_schema: str,
) -> ResolveResult:
    """Substitute this target's datasource id and schema into the model, in place.

    Structured traversal through the same generators ``normalize`` used, so the two
    directions cannot disagree about where a reference lives.
    """
    refs = 0
    for datasource_slot in iter_datasource_slots(model):
        if datasource_slot.get() is not None:
            datasource_slot.set(datasource_id)
            refs += 1

    statements = 0
    substitutions = 0
    for sql_slot in iter_sql_statements(model):
        statement = sql_slot.get() or ""
        if DATASOURCE_SCHEMA_TOKEN not in statement:
            continue
        # Substituted, never stripped — stripping the placeholder was a real defect that
        # produced SQL querying an unqualified table name.
        count = statement.count(DATASOURCE_SCHEMA_TOKEN)
        sql_slot.set(statement.replace(DATASOURCE_SCHEMA_TOKEN, datasource_schema))
        statements += 1
        substitutions += count

    return ResolveResult(
        model=model,
        datasource_refs_resolved=refs,
        sql_statements_resolved=statements,
        schema_substitutions=substitutions,
    )


def audit_resolution(
    model: CatalogDeclarativeWorkspaceModel, *, datasource_id: str
) -> tuple[list[str], dict[str, int]]:
    """Find every unresolved placeholder and every foreign datasource id.

    Returns ``(unresolved_paths, foreign_datasource_ids)`` rather than raising, so a caller
    can report before deciding to fail.
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

    return unresolved, foreign


def assert_fully_resolved(
    model: CatalogDeclarativeWorkspaceModel, *, datasource_id: str
) -> None:
    """Raise unless every placeholder is gone and every datasource id is the target's.

    This is the guard the predecessor lacked. It runs on every publish path, including the
    rehearsal, so a layout that would ship pointing at the wrong warehouse fails before a
    single byte reaches the host.
    """
    unresolved, foreign = audit_resolution(model, datasource_id=datasource_id)
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
            f"datasource id(s) other than {datasource_id!r}: {rendered}. "
            "Publishing would point this workspace at another org's warehouse."
        )

    raise UnresolvedLayoutError("; ".join(problems))


def resolve_and_assert(
    model: CatalogDeclarativeWorkspaceModel,
    *,
    datasource_id: str,
    datasource_schema: str,
) -> ResolveResult:
    """Resolve, then prove it worked. The only resolution entry point callers should use."""
    result = resolve_placeholders(
        model, datasource_id=datasource_id, datasource_schema=datasource_schema
    )
    assert_fully_resolved(model, datasource_id=datasource_id)
    result.unresolved_paths, result.foreign_datasource_ids = [], {}
    return result
