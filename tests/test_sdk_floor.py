"""The SDK version floor is a correctness constraint, not a preference.

``CatalogDeclarativeAnalyticsLayer`` gained ``memory_items`` and ``parameters`` in
gooddata-sdk 1.74. On anything older, ``get_declarative_workspace()`` returns a model
with nowhere to put AI memory, so a capture drops it silently and a publish writes an
AI-empty workspace — with no error anywhere. STEERING § Portability Contract calls that
a defect ("AI context travels"), so the floor is asserted rather than trusted.

The GlobalMart parent carries zero memory items today, which is exactly why this needs a
test: the failure would be invisible until the first one is added.
"""

from __future__ import annotations

import attrs
from gooddata_sdk.catalog.workspace.declarative_model.workspace.analytics_model.analytics_model import (
    CatalogDeclarativeAnalyticsLayer,
)

#: Every channel STEERING requires to survive a capture and a cross-org publish.
REQUIRED_ANALYTICS_FIELDS = {
    "analytical_dashboards",
    "analytical_dashboard_extensions",
    "attribute_hierarchies",
    "dashboard_plugins",
    "export_definitions",
    "filter_contexts",
    "memory_items",
    "metrics",
    "parameters",
    "visualization_objects",
}


def test_analytics_layer_models_every_required_channel() -> None:
    present = {f.name for f in attrs.fields(CatalogDeclarativeAnalyticsLayer)}
    missing = REQUIRED_ANALYTICS_FIELDS - present
    assert not missing, (
        f"Installed gooddata-sdk does not model {sorted(missing)} on the declarative "
        "analytics layer. A capture would silently drop those objects. Raise the pin in "
        "pyproject.toml rather than relaxing this test."
    )


def test_memory_items_are_modelled() -> None:
    """Named separately: this is the one the user explicitly asked for."""
    present = {f.name for f in attrs.fields(CatalogDeclarativeAnalyticsLayer)}
    assert "memory_items" in present
