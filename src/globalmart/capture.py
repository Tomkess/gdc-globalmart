"""Read a workspace layout off a live host, org-agnostically.

Why not ``store_declarative_workspace`` / ``load_declarative_workspace``
----------------------------------------------------------------------
Those convenience wrappers route through ``CatalogServiceBase.layout_organization_folder()``,
which computes ``layout_root_path / "gooddata_layouts" / self.organization_id``
(``gooddata_sdk/catalog/catalog_service_base.py:34-35``). That bakes the source org id —
``petertomko`` today — into the on-disk path, so the committed tree would carry a trace of
the org it happened to be captured from. STEERING § Portability Contract forbids that.

Instead this module reads with ``get_declarative_workspace()`` and the caller writes with
``CatalogDeclarativeWorkspaceModel.store_to_disk(workspace_folder=...)``, which takes an
explicit folder and never consults the org id. ``load_from_disk(workspace_folder=...)`` is
the matching read. Capture is the only routine that talks to a host at all — everything
downstream reads the committed tree.
"""

from __future__ import annotations

from typing import Any

from gooddata_sdk import GoodDataSdk
from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)


def capture_workspace(sdk: GoodDataSdk, workspace_id: str) -> CatalogDeclarativeWorkspaceModel:
    """Fetch one workspace's declarative layout (LDM + analytics) from a live host."""
    return sdk.catalog_workspace.get_declarative_workspace(workspace_id=workspace_id)


def capture_wdf_list(sdk: GoodDataSdk) -> Any:
    """Fetch the org's workspace-data-filter declarations — for reporting only.

    WDFs are org-scoped rather than workspace-scoped and are never committed. The
    normalizer reports how many references it handled so the number is visible rather
    than silently absorbed.
    """
    return sdk.catalog_workspace.get_declarative_workspace_data_filters()
