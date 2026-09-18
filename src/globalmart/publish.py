"""Publish a workspace layout into a target org.

The sequence, in order, with every write gated on ``apply``:

    preflight (profile, org identity, portability)
      -> ensure datasource
      -> resolve placeholders
      -> assert fully resolved
      -> backup the target's current layout
      -> create or update the workspace
      -> put the declarative layout

``apply`` defaults to ``False`` and the default is a *rehearsal*: everything above runs
except the three write calls, and the diff is reported instead. ADR 002 explains why the
dangerous path is opt-in — ``put_declarative_workspace`` replaces a workspace's entire
content in one call, and the layout it replaces exists nowhere else.

Nothing here assumes the parent workspace. FEAT-004 publishes each domain child through the
same function with a different model, workspace id and display name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gooddata_sdk import CatalogWorkspace, GoodDataSdk
from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.backup import backup_workspace
from globalmart.compare import model_diff, model_digest
from globalmart.config import TargetProfile
from globalmart.counts import ObjectCounts, count_objects
from globalmart.datasource import DataSourceOutcome, ensure_data_source
from globalmart.preflight import check_organization, check_portability, check_profile
from globalmart.resolve import ResolveResult, resolve_and_assert

#: The parent workspace's display name. It travels with the content, not the target, so the
#: same GlobalMart carries the same name in every org. FEAT-004 passes each child's label
#: from domains.yaml through the same parameter.
PARENT_WORKSPACE_NAME = "GlobalMart"


@dataclass
class PublishResult:
    """What a publish did — printed by the CLI, asserted by the tests."""

    target: str
    host: str
    organization_id: str
    workspace_id: str
    workspace_name: str
    datasource_id: str
    datasource_outcome: DataSourceOutcome
    applied: bool
    digest_before: str | None = None
    digest_after: str = ""
    changed: bool = True
    backup_path: Path | None = None
    diff: list[str] = field(default_factory=list)
    resolve: ResolveResult | None = None
    counts: ObjectCounts = field(default_factory=ObjectCounts)

    def summary_lines(self) -> list[str]:
        lines = [
            f"target            : {self.target} ({self.host}, org {self.organization_id})",
            f"workspace         : {self.workspace_id}  [{self.workspace_name}]",
            f"datasource        : {self.datasource_id} — {self.datasource_outcome}",
            f"changed           : {self.changed}",
            f"backup            : {self.backup_path or '(nothing to back up)'}",
        ]
        if self.resolve is not None:
            lines.extend(self.resolve.summary_lines())
        return lines


def resolved_workspace_id(profile: TargetProfile, base_id: str) -> str:
    """Apply the profile's prefix, so several copies can coexist in one org."""
    return f"{profile.workspace_id_prefix}{base_id}"


def publish_workspace(
    sdk: GoodDataSdk,
    model: CatalogDeclarativeWorkspaceModel,
    profile: TargetProfile,
    *,
    workspace_id: str,
    workspace_name: str = PARENT_WORKSPACE_NAME,
    apply: bool = False,
    standalone_copy: bool = False,
    take_backup: bool = True,
) -> PublishResult:
    """Publish one workspace. Rehearsal unless ``apply=True``."""
    check_profile(profile)
    check_organization(sdk, profile)
    check_portability(model)

    target_id = resolved_workspace_id(profile, workspace_id)

    datasource_outcome = ensure_data_source(sdk, profile, apply=apply)

    resolve_result = resolve_and_assert(
        model,
        datasource_id=profile.datasource_id,
        datasource_schema=profile.datasource_schema,
    )

    # A read, so it happens in a rehearsal too — that is what makes the diff possible.
    try:
        before = sdk.catalog_workspace.get_declarative_workspace(workspace_id=target_id)
    except Exception:
        before = None

    digest_before = model_digest(before) if before is not None else None
    digest_after = model_digest(model)

    backup_path: Path | None = None
    if apply and take_backup:
        backup_path = backup_workspace(sdk, profile, target_id)

    if apply:
        sdk.catalog_workspace.create_or_update(
            CatalogWorkspace(workspace_id=target_id, name=workspace_name)
        )
        sdk.catalog_workspace.put_declarative_workspace(target_id, model, standalone_copy)

    return PublishResult(
        target=profile.name,
        host=profile.host,
        organization_id=profile.organization_id,
        workspace_id=target_id,
        workspace_name=workspace_name,
        datasource_id=profile.datasource_id,
        datasource_outcome=datasource_outcome,
        applied=apply,
        digest_before=digest_before,
        digest_after=digest_after,
        changed=digest_before != digest_after,
        backup_path=backup_path,
        diff=model_diff(before, model),
        resolve=resolve_result,
        counts=count_objects(model),
    )
