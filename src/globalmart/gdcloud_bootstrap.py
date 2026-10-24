"""Prepare one gdcloud environment before its first deploy (FEAT-019, ADR 011).

gdcloud deploys workspace *content*. Three things it does not do have to exist first:

1. **Room.** The demo orgs cap workspaces (``WorkspaceCount`` entitlement, DEMO tier: 25 on
   demo.cloud, child workspaces included). A deploy that cannot create its master fails halfway
   through a workflow. The cap is checked up front instead, and a missing master on a full org
   stops here, not in CI.
2. **The data source** the committed tree names, ``gdc_ds_globalmart_motherduck``. gdcloud never
   releases data sources.
3. **A titled master.** gdcloud names a master it creates after the bare data product id, so dev
   and test would both read "globalmart" on a shared org. The master is created here, before
   gdcloud ever sees it, as "GlobalMart (DEV)" etc.; gdcloud then only updates its content.

A collision audit runs before any write: a planned master id that already exists under a title
that is not GlobalMart's belongs to someone else, and nothing is touched.

Read-only rehearsal by default; ``apply=True`` is the only path to a write (ADR 002), and an
existing master is backed up before its title is changed.
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gooddata_sdk import CatalogWorkspace, GoodDataSdk

from globalmart.backup import backup_workspace
from globalmart.config import GlobalmartError, TargetProfile
from globalmart.datasource import DataSourceOutcome, ensure_data_source
from globalmart.gdcloud_bridge import ReleaseConfig, master_workspace_id
from globalmart.preflight import check_organization, check_profile

#: The title each environment's master carries. prod is the plain name a viewer of the
#: production org expects; the rest say which copy they are, because they share an org.
MASTER_TITLES = {
    "dev": "GlobalMart (DEV)",
    "test": "GlobalMart (TEST)",
    "preprod": "GlobalMart (PREPROD)",
    "prod": "GlobalMart",
}
OUR_TITLE_PREFIX = "GlobalMart"


class BootstrapError(GlobalmartError):
    """The environment cannot be prepared without risking someone else's workspace or the cap."""


@dataclass(frozen=True)
class Capacity:
    limit: int | None  # None: the org reports no WorkspaceCount entitlement
    used: int

    @property
    def free(self) -> int | None:
        return None if self.limit is None else self.limit - self.used


@dataclass
class BootstrapReport:
    environment: str
    workspace_id: str
    title: str
    applied: bool
    capacity: Capacity
    existing_title: str | None = None
    datasource_outcome: DataSourceOutcome | None = None
    created: bool = False
    retitled: bool = False
    backup_path: Path | None = None
    notes: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        cap = self.capacity
        room = "no cap reported" if cap.limit is None else f"{cap.used}/{cap.limit} used, {cap.free} free"
        state = f"exists as {self.existing_title!r}" if self.existing_title is not None else "does not exist"
        lines = [
            f"environment       : {self.environment}",
            f"master            : {self.workspace_id} ({state})",
            f"title             : {self.title}",
            f"workspace slots   : {room}",
            f"data source       : {self.datasource_outcome.value if self.datasource_outcome else '-'}",
        ]
        if self.applied:
            action = "created" if self.created else ("retitled" if self.retitled else "unchanged")
            lines.append(f"master            : {action}")
        if self.backup_path:
            lines.append(f"backup            : {self.backup_path}")
        lines.extend(self.notes)
        return lines


def fetch_capacity(profile: TargetProfile) -> Capacity:
    """The org's workspace cap and current usage.

    Raw REST: the SDK has no entitlement or usage API (gooddata-sdk 1.75.0).
    """

    def get(path: str) -> Any:
        request = urllib.request.Request(
            f"{profile.host}{path}", headers={"Authorization": f"Bearer {profile.token}"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())

    entitlements = get("/api/v1/entities/entitlements")
    usage = get("/api/v1/actions/collectUsage")
    limit = next(
        (
            int(item["attributes"]["value"])
            for item in (entitlements or {}).get("data", [])
            if item.get("id") == "WorkspaceCount" and "value" in item.get("attributes", {})
        ),
        None,
    )
    used = next(
        (int(row["count"]) for row in usage or [] if row.get("name") == "WorkspaceCount"),
        0,
    )
    return Capacity(limit=limit, used=used)


def bootstrap_environment(
    sdk: GoodDataSdk,
    profile: TargetProfile,
    release: ReleaseConfig,
    *,
    apply: bool = False,
    take_backup: bool = True,
    capacity: Callable[[TargetProfile], Capacity] = fetch_capacity,
) -> BootstrapReport:
    """Check room and ownership, then (under ``apply``) ensure the data source and titled master."""
    environment = profile.gdcloud_environment
    if environment is None:
        raise BootstrapError(f"Profile {profile.name!r} is not a gdcloud release target")
    check_profile(profile)
    check_organization(sdk, profile)

    workspace_id = master_workspace_id(release, environment)
    title = MASTER_TITLES[environment]
    existing = {ws.id: ws.name for ws in sdk.catalog_workspace.list_workspaces()}
    existing_title = existing.get(workspace_id)

    report = BootstrapReport(
        environment=environment,
        workspace_id=workspace_id,
        title=title,
        applied=apply,
        capacity=capacity(profile),
        existing_title=existing_title,
    )

    # Collision audit: an id we plan to deploy into, owned by something that is not GlobalMart.
    if existing_title is not None and not existing_title.startswith(OUR_TITLE_PREFIX):
        raise BootstrapError(
            f"{workspace_id!r} already exists as {existing_title!r}, which is not GlobalMart's. "
            "Nothing was changed."
        )

    # Capacity: only a master that still has to be created needs a free slot.
    if existing_title is None and report.capacity.free is not None and report.capacity.free < 1:
        raise BootstrapError(
            f"{profile.host} has no free workspace slot ({report.capacity.used}/"
            f"{report.capacity.limit}); {workspace_id!r} cannot be created. Nothing was changed."
        )

    report.datasource_outcome = ensure_data_source(sdk, profile, apply=apply)
    if not apply:
        report.notes.append("REHEARSAL — no writes. Re-run with --apply.")
        return report

    if existing_title is None:
        sdk.catalog_workspace.create_or_update(CatalogWorkspace(workspace_id=workspace_id, name=title))
        report.created = True
    elif existing_title != title:
        if take_backup:
            report.backup_path = backup_workspace(sdk, profile, workspace_id)
        sdk.catalog_workspace.create_or_update(CatalogWorkspace(workspace_id=workspace_id, name=title))
        report.retitled = True
    return report
