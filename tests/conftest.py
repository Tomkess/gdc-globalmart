"""Shared fixtures.

``synthetic_model`` is a hand-built workspace model used to prove the writer, the pruner
and the normalizer without a live host. It is deliberately *not* the FEAT-001 mini fixture
(task 11), which is a trimmed real capture — this one exists so the offline tests can run
before that capture has happened, and so a shape can be constructed on demand.
"""

from __future__ import annotations

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
