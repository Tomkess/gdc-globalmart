"""Everything that can fail before a byte is written to a host.

Ordering matters. ``check_profile`` runs before an SDK client is built, so an incomplete
profile fails locally rather than after authenticating. ``check_organization`` is the guard
against an over-scoped token publishing over the wrong org — the profile pins the expected
organization id and the publisher refuses if the host disagrees.
"""

from __future__ import annotations

from gooddata_sdk import GoodDataSdk
from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.config import (
    GlobalmartError,
    MissingProfileKeyError,
    TargetProfile,
    validate_for_publish,
)
from globalmart.normalize import _ANALYTICS_COLLECTIONS, _AUDIT_FIELDS


class OrganizationMismatchError(GlobalmartError):
    """The host's organization is not the one the profile expects."""


class PortabilityError(GlobalmartError):
    """The model still carries something org-specific that a target would reject."""


def check_profile(profile: TargetProfile) -> None:
    """Raise unless the profile carries everything a publish needs. No network."""
    missing = validate_for_publish(profile)
    if missing:
        raise MissingProfileKeyError(
            f"Profile {profile.name!r} cannot publish — missing: {', '.join(missing)}. "
            "Add them to config/targets.yaml (or the named environment variable)."
        )


def check_organization(sdk: GoodDataSdk, profile: TargetProfile) -> None:
    """Refuse to write to an org other than the one the profile names.

    An API token is often scoped more broadly than the workspace being published. Without
    this, a mistyped host publishes over real content in a different org.
    """
    organization = sdk.catalog_organization.get_organization()
    actual = getattr(organization, "id", None)
    if actual != profile.organization_id:
        raise OrganizationMismatchError(
            f"Profile {profile.name!r} expects organization {profile.organization_id!r} but "
            f"{profile.host} reports {actual!r}. Refusing to write."
        )


def check_portability(model: CatalogDeclarativeWorkspaceModel) -> None:
    """Assert no user references survive, so a cross-org 400 is diagnosed locally.

    A foreign ``createdBy`` makes the target org reject the whole layout with a generic
    error. Catching it here names the object instead.
    """
    analytics = model.analytics
    if analytics is None:
        return

    offenders: list[str] = []
    for collection in _ANALYTICS_COLLECTIONS:
        for obj in getattr(analytics, collection, None) or []:
            for attribute in _AUDIT_FIELDS:
                if getattr(obj, attribute, None) is not None:
                    offenders.append(f"{collection}.{getattr(obj, 'id', '?')}.{attribute}")

    if offenders:
        shown = ", ".join(offenders[:5])
        more = f" (+{len(offenders) - 5} more)" if len(offenders) > 5 else ""
        raise PortabilityError(
            f"{len(offenders)} user reference(s) survive in the model: {shown}{more}. "
            "Run `globalmart normalize` before publishing."
        )


def check_wdf_values(host: str, token: str, workspace_id: str) -> str | None:
    """The preflight for the single most common cause of "everything is broken".

    A workspace that inherits a workspace-data-filter *definition* but has no filter *value*
    set fails **every** execution with HTTP 400 ("...filter values...are empty..."), which in
    the UI reads as "SORRY, WE CAN'T DISPLAY THIS VISUALIZATION" on every tile. Without this
    check that presents as 384 visualization defects instead of one configuration fault — the
    predecessor's highest-value finding, and the reason this runs before execution rather
    than being inferred from the results afterwards.

    Raw REST: the SDK models no `workspaceDataFilter*` endpoint (STEERING § Coding Standards
    requires saying so where we go around it).

    **Never raises.** A preflight that blocks the run it is meant to inform is worse than no
    preflight, so every failure here returns ``None`` and the run proceeds.

    FEAT-001 defaults to ``WdfPolicy.DROP``, so in a repo-built org this must always return
    ``None``. The check stays precisely to prove that, rather than to assume it.
    """
    import requests

    base = host.rstrip("/")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.gooddata.api+json",
    }
    try:
        filters = requests.get(
            f"{base}/api/v1/entities/workspaces/{workspace_id}/workspaceDataFilters",
            headers=headers,
            timeout=30,
        )
        settings = requests.get(
            f"{base}/api/v1/entities/workspaces/{workspace_id}/workspaceDataFilterSettings",
            headers=headers,
            timeout=30,
        )
        if filters.status_code != 200 or settings.status_code != 200:
            return None
        defined = len(filters.json().get("data", []))
        valued = len(settings.json().get("data", []))
    except Exception:  # noqa: BLE001 - a preflight must never block the run
        return None

    if defined > 0 and valued == 0:
        return (
            f"workspace {workspace_id!r} has {defined} workspace data filter(s) and 0 value(s) "
            "set — EVERY visualization in it will fail with HTTP 400. Set a filter value "
            "before reading the per-object failures below as real defects."
        )
    return None
