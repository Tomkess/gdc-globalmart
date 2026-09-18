"""Make a captured workspace org-agnostic and byte-stable.

Six passes, applied in order. Passes 1–4 remove or parameterise whatever ties the layout
to the org it came from; passes 5–6 canonicalise whatever the earlier passes leave behind,
so two captures of an unchanged workspace produce identical bytes.

Everything here is a structured traversal of the attrs model. Nothing in this module
performs string replacement over serialized JSON — that was the predecessor's fatal bug
(it rewrote a datasource literal that did not appear in the file, silently doing nothing).

The one exception is inside a SQL statement, which *is* text: there, a schema prefix is
replaced as a whole dotted identifier, never as a bare substring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.config import GlobalmartError
from globalmart.counts import ObjectCounts, count_objects
from globalmart.traversal import iter_datasource_slots, iter_sql_statements

#: Placeholders left in the committed tree, resolved at publish time by FEAT-002.
#: Both use the same ``{{ ... }}`` form so one substitution mechanism covers them and an
#: unresolved token is greppable in a published layout.
DATASOURCE_ID_TOKEN = "{{ datasource_id }}"
DATASOURCE_SCHEMA_TOKEN = "{{ datasource_schema }}"

#: Audit fields present on every analytics object. They name a user in the source org and
#: churn on every capture, so they defeat both portability and byte-stability.
_AUDIT_FIELDS = ("created_by", "modified_by", "created_at", "modified_at")

#: Analytics collections carrying audit metadata.
_ANALYTICS_COLLECTIONS = (
    "metrics",
    "visualization_objects",
    "analytical_dashboards",
    "analytical_dashboard_extensions",
    "filter_contexts",
    "dashboard_plugins",
    "attribute_hierarchies",
    "export_definitions",
    "memory_items",
    "parameters",
)


class WdfPolicy(StrEnum):
    """What to do with workspace-data-filter references on datasets.

    ``DROP`` is the default: no WDF policy is in use today, so the references in the
    parent are demo-org residue. ``KEEP`` stays implemented and tested so a future
    row-level-security design is a flag flip rather than a rewrite.
    """

    DROP = "drop"
    KEEP = "keep"


class UnparameterizedSqlError(GlobalmartError):
    """A SQL dataset whose schema could be neither found nor parameterised."""


@dataclass
class NormalizeResult:
    """What the normalizer did, printed by the CLI and asserted by the tests."""

    model: CatalogDeclarativeWorkspaceModel
    user_refs_stripped: int = 0
    datasource_refs_rewritten: int = 0
    sql_datasets_parameterized: int = 0
    unparameterized_sql: list[str] = field(default_factory=list)
    wdf_refs_handled: int = 0
    wdf_policy: WdfPolicy = WdfPolicy.DROP
    counts: ObjectCounts = field(default_factory=ObjectCounts)

    def summary_lines(self) -> list[str]:
        lines = [
            f"user references stripped   : {self.user_refs_stripped}",
            f"datasource refs rewritten  : {self.datasource_refs_rewritten}",
            f"SQL datasets parameterised : {self.sql_datasets_parameterized}",
            f"WDF references handled     : {self.wdf_refs_handled} ({self.wdf_policy})",
        ]
        if self.unparameterized_sql:
            lines.append(f"UNPARAMETERISED SQL        : {', '.join(self.unparameterized_sql)}")
        return lines


def _iter_analytics_objects(model: CatalogDeclarativeWorkspaceModel) -> list[Any]:
    analytics = model.analytics
    if analytics is None:
        return []
    objects: list[Any] = []
    for name in _ANALYTICS_COLLECTIONS:
        objects.extend(getattr(analytics, name, None) or [])
    return objects


def _pass_1_strip_user_refs(model: CatalogDeclarativeWorkspaceModel) -> int:
    """Remove audit metadata: who made the object, in which org, and when."""
    stripped = 0
    for obj in _iter_analytics_objects(model):
        for attribute in _AUDIT_FIELDS:
            if getattr(obj, attribute, None) is not None:
                setattr(obj, attribute, None)
                stripped += 1
    return stripped


def _pass_2_parameterize_datasource(model: CatalogDeclarativeWorkspaceModel) -> int:
    """Replace every dataset's datasource id with the placeholder.

    Enumerated by ``traversal.iter_datasource_slots`` — the same generator the publisher's
    ``resolve`` uses in the opposite direction, so the two can never disagree about where a
    datasource reference lives.
    """
    rewritten = 0
    for slot in iter_datasource_slots(model):
        if slot.get() is not None:
            slot.set(DATASOURCE_ID_TOKEN)
            rewritten += 1
    return rewritten


def _schema_pattern(schema: str) -> re.Pattern[str]:
    """Match the schema only as a whole dotted identifier prefix.

    ``globalmart.fact_orders`` matches; a column called ``globalmart_id`` or an alias
    ``my_globalmart`` does not. Optional double quotes cover a quoted identifier.
    """
    escaped = re.escape(schema)
    return re.compile(rf'(?<![\w"]) "?{escaped}"? \s* \. \s*', re.VERBOSE)


def _pass_3_parameterize_schema(
    model: CatalogDeclarativeWorkspaceModel, schema: str
) -> tuple[int, list[str]]:
    """Replace the literal warehouse schema in SQL datasets with the placeholder.

    Measured on the live org 2026-09-18: all 11 SQL datasets carry a hardcoded
    ``globalmart.`` prefix and none carries a placeholder, because the substitution was
    performed historically and written back. So this pass *introduces* the placeholder;
    preserving an existing one is the rarer path.

    A statement matching neither is an error, not a pass — that silence is how
    ``sql_channel_attribution`` shipped broken for months.
    """
    pattern = _schema_pattern(schema)
    parameterized = 0
    unparameterized: list[str] = []

    for slot in iter_sql_statements(model):
        statement = slot.get()

        if DATASOURCE_SCHEMA_TOKEN in statement:
            parameterized += 1
            continue

        replaced, count = pattern.subn(f"{DATASOURCE_SCHEMA_TOKEN}.", statement)
        if count:
            slot.set(replaced)
            parameterized += 1
        else:
            unparameterized.append(slot.dataset_id)

    return parameterized, unparameterized


def _pass_4_handle_wdf(model: CatalogDeclarativeWorkspaceModel, policy: WdfPolicy) -> int:
    """Drop or keep workspace-data-filter references, which are org-scoped ids.

    ``workspace_data_filter_columns`` is left alone either way — those are physical
    columns, not references to an org's filter objects.
    """
    handled = 0
    for dataset in (model.ldm.datasets if model.ldm else None) or []:
        references = getattr(dataset, "workspace_data_filter_references", None) or []
        if not references:
            continue
        handled += len(references)
        if policy is WdfPolicy.DROP:
            dataset.workspace_data_filter_references = []
    return handled


def _sort_key(item: Any) -> str:
    for attribute in ("id", "title"):
        value = getattr(item, attribute, None)
        if value is not None:
            return str(value)
    identifier = getattr(item, "identifier", None)
    if identifier is not None and getattr(identifier, "id", None) is not None:
        return str(identifier.id)
    return str(item)


def _sort_in_place(owner: Any, attribute: str) -> None:
    value = getattr(owner, attribute, None)
    if isinstance(value, list) and value:
        value.sort(key=_sort_key)


def _pass_5_stabilise_order(model: CatalogDeclarativeWorkspaceModel) -> None:
    """Sort every list to a deterministic order.

    The SDK's ``deep_sort`` sorts mapping keys but explicitly preserves list order, so
    nested lists — which land inside the per-object files — are ours to stabilise.
    """
    ldm = model.ldm
    if ldm is not None:
        _sort_in_place(ldm, "datasets")
        _sort_in_place(ldm, "date_instances")
        _sort_in_place(ldm, "dataset_extensions")
        for dataset in ldm.datasets or []:
            for attribute_name in ("attributes", "facts", "aggregated_facts", "references", "grain"):
                _sort_in_place(dataset, attribute_name)
            for attribute in getattr(dataset, "attributes", None) or []:
                _sort_in_place(attribute, "labels")
                _sort_in_place(attribute, "tags")
            _sort_in_place(dataset, "tags")

    analytics = model.analytics
    if analytics is not None:
        for name in _ANALYTICS_COLLECTIONS:
            _sort_in_place(analytics, name)


def _pass_6_canonicalise_empties(model: CatalogDeclarativeWorkspaceModel) -> None:
    """Make an absent collection and an empty collection the same thing on disk.

    The API omits some empty collections and returns others as ``[]``; without this, two
    captures of an unchanged workspace can differ purely in which form came back.
    """
    for dataset in (model.ldm.datasets if model.ldm else None) or []:
        for attribute_name in ("tags", "aggregated_facts", "workspace_data_filter_references"):
            if getattr(dataset, attribute_name, None) is None:
                setattr(dataset, attribute_name, [])
        for attribute in getattr(dataset, "attributes", None) or []:
            if getattr(attribute, "tags", None) is None:
                attribute.tags = []


def normalize_workspace(
    model: CatalogDeclarativeWorkspaceModel,
    *,
    datasource_schema: str,
    wdf_policy: WdfPolicy = WdfPolicy.DROP,
    strict: bool = True,
) -> NormalizeResult:
    """Normalize a captured workspace in place and report what changed.

    ``strict`` raises when a SQL dataset could not be parameterised. Turning it off is for
    inspecting a broken capture, never for committing one.
    """
    user_refs = _pass_1_strip_user_refs(model)
    datasource_refs = _pass_2_parameterize_datasource(model)
    sql_count, unparameterized = _pass_3_parameterize_schema(model, datasource_schema)
    wdf_handled = _pass_4_handle_wdf(model, wdf_policy)
    _pass_5_stabilise_order(model)
    _pass_6_canonicalise_empties(model)

    if strict and unparameterized:
        raise UnparameterizedSqlError(
            "SQL dataset(s) carry neither the schema placeholder nor the literal schema "
            f"{datasource_schema!r}: {', '.join(unparameterized)}. "
            "Publishing these would hard-wire them to one warehouse."
        )

    return NormalizeResult(
        model=model,
        user_refs_stripped=user_refs,
        datasource_refs_rewritten=datasource_refs,
        sql_datasets_parameterized=sql_count,
        unparameterized_sql=unparameterized,
        wdf_refs_handled=wdf_handled,
        wdf_policy=wdf_policy,
        counts=count_objects(model),
    )
