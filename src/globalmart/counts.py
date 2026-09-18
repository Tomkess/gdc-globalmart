"""Object counts for a workspace model.

Shared by the bootstrap report, the round-trip tests and (later) FEAT-006's verification.
Counting every channel — including the AI ones that are empty today — is deliberate: a
channel that silently stops being captured shows up here as a number going to zero.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)


@dataclass(frozen=True)
class ObjectCounts:
    """How many of each object a workspace model holds."""

    datasets: int = 0
    date_instances: int = 0
    dataset_extensions: int = 0
    metrics: int = 0
    visualization_objects: int = 0
    analytical_dashboards: int = 0
    analytical_dashboard_extensions: int = 0
    filter_contexts: int = 0
    attribute_hierarchies: int = 0
    dashboard_plugins: int = 0
    export_definitions: int = 0
    memory_items: int = 0
    parameters: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)

    def non_zero(self) -> dict[str, int]:
        """Only the populated channels — what a human wants to read in a report."""
        return {key: value for key, value in self.as_dict().items() if value}


def _count(container: Any, attribute: str) -> int:
    value = getattr(container, attribute, None) or []
    return len(value)


def count_objects(model: CatalogDeclarativeWorkspaceModel) -> ObjectCounts:
    """Count every object channel in a declarative workspace model.

    ``model.ldm`` is a ``CatalogDeclarativeLdm`` and ``model.analytics`` a
    ``CatalogDeclarativeAnalyticsLayer`` — both flat, despite the extra ``ldm`` /
    ``analytics`` wrapper types that exist elsewhere in the SDK for the org-level layout.
    """
    ldm = model.ldm
    analytics = model.analytics

    return ObjectCounts(
        datasets=_count(ldm, "datasets"),
        date_instances=_count(ldm, "date_instances"),
        dataset_extensions=_count(ldm, "dataset_extensions"),
        metrics=_count(analytics, "metrics"),
        visualization_objects=_count(analytics, "visualization_objects"),
        analytical_dashboards=_count(analytics, "analytical_dashboards"),
        analytical_dashboard_extensions=_count(analytics, "analytical_dashboard_extensions"),
        filter_contexts=_count(analytics, "filter_contexts"),
        attribute_hierarchies=_count(analytics, "attribute_hierarchies"),
        dashboard_plugins=_count(analytics, "dashboard_plugins"),
        export_definitions=_count(analytics, "export_definitions"),
        memory_items=_count(analytics, "memory_items"),
        parameters=_count(analytics, "parameters"),
    )
