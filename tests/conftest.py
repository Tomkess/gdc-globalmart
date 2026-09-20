"""Shared fixtures.

``synthetic_model`` is a hand-built workspace model used to prove the writer, the pruner
and the normalizer without a live host. It is deliberately *not* the FEAT-001 mini fixture
(task 11), which is a trimmed real capture — this one exists so the offline tests can run
before that capture has happened, and so a shape can be constructed on demand.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)


def workspace_payload(*, metric_ids: tuple[str, ...] = ("m_revenue", "m_orders")) -> dict[str, Any]:
    """A minimal but structurally real declarative workspace payload (camelCase, as the API returns).

    Carries the shapes the normalizer has to handle: a table-backed dataset, a SQL-backed
    dataset with a schema placeholder, nested labels, a grain, a dataset reference, and
    audit fields on the analytics objects.
    """
    return {
        "ldm": {
            "datasets": [
                {
                    "id": "dim_customer",
                    "title": "Customer",
                    "grain": [],
                    "attributes": [
                        {
                            "id": "customer_id",
                            "title": "Customer ID",
                            "sourceColumn": "customer_id",
                            "sourceColumnDataType": "STRING",
                            "labels": [
                                {
                                    "id": "customer_name",
                                    "title": "Customer Name",
                                    "sourceColumn": "customer_name",
                                    "sourceColumnDataType": "STRING",
                                },
                                {
                                    "id": "customer_segment",
                                    "title": "Customer Segment",
                                    "sourceColumn": "segment_id",
                                    "sourceColumnDataType": "STRING",
                                },
                            ],
                        }
                    ],
                    "facts": [],
                    "references": [],
                    "dataSourceTableId": {
                        "dataSourceId": "globalmart-motherduck",
                        "id": "dim_customer",
                        "type": "dataSource",
                    },
                },
                {
                    "id": "fact_orders",
                    "title": "Orders",
                    "grain": [{"id": "order_id", "type": "attribute"}],
                    "attributes": [
                        {
                            "id": "order_id",
                            "title": "Order ID",
                            "sourceColumn": "order_id",
                            "sourceColumnDataType": "STRING",
                            "labels": [],
                        }
                    ],
                    "facts": [
                        {
                            "id": "order_amount",
                            "title": "Order Amount",
                            "sourceColumn": "amount",
                            "sourceColumnDataType": "NUMERIC",
                        }
                    ],
                    "references": [
                        {
                            "identifier": {"id": "dim_customer", "type": "dataset"},
                            "multivalue": False,
                            "sourceColumns": ["customer_id"],
                        }
                    ],
                    "dataSourceTableId": {
                        "dataSourceId": "globalmart-motherduck",
                        "id": "fact_orders",
                        "type": "dataSource",
                    },
                },
                {
                    "id": "sql_channel_summary",
                    "title": "Channel Summary",
                    "grain": [],
                    "attributes": [
                        {
                            "id": "channel",
                            "title": "Channel",
                            "sourceColumn": "channel",
                            "sourceColumnDataType": "STRING",
                            "labels": [],
                        }
                    ],
                    "facts": [],
                    "references": [],
                    "sql": {
                        "dataSourceId": "globalmart-motherduck",
                        "statement": (
                            "SELECT channel, count(*) AS n "
                            "FROM {{ datasource_schema }}.fact_orders GROUP BY 1"
                        ),
                    },
                },
            ],
            "dateInstances": [
                {
                    "id": "date_order",
                    "title": "Order Date",
                    "granularities": ["YEAR", "MONTH", "DAY"],
                    "granularitiesFormatting": {
                        "titleBase": "",
                        "titlePattern": "%titleBase - %granularityTitle",
                    },
                }
            ],
        },
        "analytics": {
            "metrics": [
                {
                    "id": metric_id,
                    "title": metric_id.replace("m_", "").title(),
                    "content": {"format": "#,##0", "maql": "SELECT SUM({fact/order_amount})"},
                    "createdBy": {"id": "demo-user", "type": "user"},
                    "modifiedBy": {"id": "demo-user", "type": "user"},
                    "createdAt": "2026-06-01 10:00",
                    "modifiedAt": "2026-06-25 14:30",
                }
                for metric_id in metric_ids
            ],
            "visualizationObjects": [
                {
                    "id": "viz_sales_overview",
                    "title": "Sales Overview",
                    "content": {
                        "version": "2",
                        "visualizationUrl": "local:column",
                        "buckets": [],
                        "filters": [],
                        "sorts": [],
                    },
                    "createdBy": {"id": "demo-user", "type": "user"},
                    "modifiedBy": {"id": "demo-user", "type": "user"},
                }
            ],
            "analyticalDashboards": [
                {
                    "id": "dash_sales",
                    "title": "Sales",
                    "content": {"version": "2", "layout": {"type": "IDashboardLayout", "sections": []}},
                    "createdBy": {"id": "demo-user", "type": "user"},
                    "modifiedBy": {"id": "demo-user", "type": "user"},
                }
            ],
            "filterContexts": [
                {
                    "id": "fc_sales",
                    "title": "Sales filters",
                    "content": {"version": "2", "filters": []},
                }
            ],
            "attributeHierarchies": [],
            "dashboardPlugins": [],
            "exportDefinitions": [],
            "analyticalDashboardExtensions": [],
            "memoryItems": [],
            "parameters": [],
        },
    }


@pytest.fixture
def synthetic_payload() -> dict[str, Any]:
    return workspace_payload()


@pytest.fixture
def synthetic_model(synthetic_payload: dict[str, Any]) -> CatalogDeclarativeWorkspaceModel:
    return CatalogDeclarativeWorkspaceModel.from_dict(synthetic_payload, camel_case=True)


class FakeSdk:
    """A hand-written SDK double that records what was sent to the host.

    Not a mocking framework: the assertions read as "these calls, in this order, with these
    arguments", which is what the tests actually care about. It also serves back whatever it
    was given, so idempotency can be proven without a host.
    """

    def __init__(
        self,
        *,
        organization_id: str = "gm-ddebmti",
        existing_workspace: Any = None,
        existing_datasource: bool = False,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._organization_id = organization_id
        self._workspace = existing_workspace
        self._datasource_exists = existing_datasource

        outer = self

        class _DataSource:
            def get_data_source(self, data_source_id: str) -> Any:
                outer.calls.append(("get_data_source", {"id": data_source_id}))
                if not outer._datasource_exists:
                    raise RuntimeError("404 not found")
                return object()

            def create_or_update_data_source(self, data_source: Any) -> None:
                outer.calls.append(
                    ("create_or_update_data_source", {"id": getattr(data_source, "id", None)})
                )
                outer._datasource_exists = True

        class _Organization:
            def get_organization(self) -> Any:
                outer.calls.append(("get_organization", {}))
                return SimpleNamespace(id=outer._organization_id)

        class _Workspace:
            def get_declarative_workspace(self, workspace_id: str) -> Any:
                outer.calls.append(("get_declarative_workspace", {"id": workspace_id}))
                if outer._workspace is None:
                    raise RuntimeError("404 not found")
                return outer._workspace

            def create_or_update(self, workspace: Any) -> None:
                outer.calls.append(
                    ("create_or_update", {"id": workspace.workspace_id, "name": workspace.name})
                )

            def put_declarative_workspace(
                self, workspace_id: str, workspace: Any, standalone_copy: bool = False
            ) -> None:
                outer.calls.append(
                    (
                        "put_declarative_workspace",
                        {"id": workspace_id, "standalone_copy": standalone_copy},
                    )
                )
                outer._workspace = workspace

        self.catalog_data_source = _DataSource()
        self.catalog_organization = _Organization()
        self.catalog_workspace = _Workspace()

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def writes(self) -> list[str]:
        """Only the calls that change something on the host."""
        writing = {"create_or_update_data_source", "create_or_update", "put_declarative_workspace"}
        return [name for name in self.call_names() if name in writing]


@pytest.fixture
def fake_sdk() -> FakeSdk:
    return FakeSdk()


@pytest.fixture(autouse=True)
def _backups_stay_out_of_the_repo(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point `backup_dir` at a temp directory for every test.

    `publish_workspace(apply=True)` takes a backup before the PUT, and the `FakeSdk` serves
    a real model back, so a publish test writes a genuine YAML tree — into `backups/` in the
    working tree, by default. Harmless (it is gitignored) but confusing: it leaves folders
    named after workspaces that were never published, including one under a `workspace_id_prefix`
    that only exists inside a test.
    """
    monkeypatch.setenv("GLOBALMART_BACKUP_DIR", str(tmp_path_factory.mktemp("backups")))
