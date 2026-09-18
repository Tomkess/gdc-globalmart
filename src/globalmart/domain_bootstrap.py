"""The one-time generator that produces the first ``config/domains.yaml``.

**This module is seed data, and it runs once.** It is the only sanctioned place in the
repo where the ``viz_<domain>_`` prefix convention and the 12 domain labels appear in code,
and ``tests/test_single_source_of_domains.py`` allow-lists exactly this file so the list
cannot quietly reappear elsewhere. No runtime code may import ``SEED_DOMAINS``: after the
manifest is generated and reviewed, membership is read from it and the prefix is dead.

Two rules distinguish this from the predecessor's splitter, which used the same prefixes:

* **ANY, not ALL.** A dashboard is assigned to *every* domain any of its tiles belongs to.
  The predecessor required every tile to match one domain, so a dashboard mixing Sales and
  Finance tiles matched nothing and was silently dropped. That is the bug this whole feature
  exists to kill, and it would be absurd to reintroduce it in the generator.
* **Nothing is omitted.** Anything the prefix cannot classify — an unmatched visualization,
  a dashboard referencing nothing, any AI-context object — lands under ``unassigned:`` with
  a ``TODO:`` reason. ``validate --strict`` fails on a ``TODO:`` reason, so an unreviewed
  generated manifest cannot pass CI. The residue is visible by construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.coverage import AI_CHANNELS, DomainCounts
from globalmart.domains import (
    DEFAULT_WORKSPACE_ID_TEMPLATE,
    DEFAULT_WORKSPACE_NAME_TEMPLATE,
    SCHEMA_VERSION,
    AiSelection,
    Domain,
    DomainManifest,
    Exclusion,
    SharedSelection,
    UnassignedSelection,
    key_kebab,
)
from globalmart.traversal import iter_dashboard_insight_refs

#: The 12 ``(key, label)`` pairs, taken from the existing workspace's object ids. Seed data
#: only — see the module docstring.
SEED_DOMAINS: tuple[tuple[str, str], ...] = (
    ("sales", "Sales"),
    ("ecommerce", "E-commerce"),
    ("product", "Products"),
    ("customer", "Customers"),
    ("loyalty", "Loyalty"),
    ("inventory", "Inventory & Supply Chain"),
    ("marketing", "Marketing"),
    ("finance", "Finance"),
    ("store_ops", "Store Operations"),
    ("hr", "HR"),
    ("risk", "Risk & Compliance"),
    ("real_estate", "Real Estate & Facilities"),
)

TODO_DESCRIPTION = "TODO: describe this domain in one sentence."


@dataclass
class BootstrapReport:
    """What the generator managed to classify — printed before anything is written."""

    matched_visualizations: int = 0
    unmatched_visualizations: tuple[str, ...] = ()
    dashboards_assigned: int = 0
    dashboards_unreferenced: tuple[str, ...] = ()
    ai_objects_parked: int = 0
    per_domain: dict[str, DomainCounts] = field(default_factory=dict)

    def summary_lines(self) -> list[str]:
        lines = [
            f"visualizations matched by prefix : {self.matched_visualizations}",
            f"visualizations unmatched (parked): {len(self.unmatched_visualizations)}",
            f"dashboards assigned              : {self.dashboards_assigned}",
            f"dashboards unreferenced (parked) : {len(self.dashboards_unreferenced)}",
            f"ai objects parked                : {self.ai_objects_parked}",
        ]
        if self.unmatched_visualizations:
            preview = ", ".join(self.unmatched_visualizations[:10])
            more = len(self.unmatched_visualizations) - 10
            lines.append(f"  unmatched: {preview}{f' ... (+{more})' if more > 0 else ''}")
        if self.dashboards_unreferenced:
            lines.append(f"  unreferenced: {', '.join(self.dashboards_unreferenced)}")
        return lines


def domain_for_visualization_id(
    viz_id: str, seed: tuple[tuple[str, str], ...] = SEED_DOMAINS
) -> str | None:
    """``viz_store_ops_0252`` -> ``store_ops``.

    Longest key first, so ``store_ops`` wins over a hypothetical ``store`` that is also a
    prefix of the same id. Getting this backwards would assign every Store Operations
    visualization to the wrong domain while looking like it worked.
    """
    for key, _label in sorted(seed, key=lambda pair: len(pair[0]), reverse=True):
        if viz_id.startswith(f"viz_{key}_"):
            return key
    return None


def bootstrap_manifest(
    model: CatalogDeclarativeWorkspaceModel,
    *,
    seed: tuple[tuple[str, str], ...] = SEED_DOMAINS,
    parent_workspace_id: str = "globalmart",
) -> tuple[DomainManifest, BootstrapReport]:
    """Produce the first manifest from the prefix convention, parking everything else."""
    analytics = model.analytics
    dashboards = list(getattr(analytics, "analytical_dashboards", None) or [])
    visualizations = list(getattr(analytics, "visualization_objects", None) or [])

    dashboard_ids = [str(dashboard.id) for dashboard in dashboards]
    visualization_ids = [str(viz.id) for viz in visualizations]

    refs: dict[str, set[str]] = {}
    for dashboard_id, viz_id in iter_dashboard_insight_refs(model):
        if viz_id in set(visualization_ids):
            refs.setdefault(dashboard_id, set()).add(viz_id)

    viz_domain: dict[str, str] = {}
    unmatched: list[str] = []
    for viz_id in visualization_ids:
        key = domain_for_visualization_id(viz_id, seed)
        if key is None:
            unmatched.append(viz_id)
        else:
            viz_domain[viz_id] = key

    # ANY, not ALL — see the module docstring.
    domain_dashboards: dict[str, set[str]] = {key: set() for key, _ in seed}
    unreferenced: list[str] = []
    for dashboard_id in dashboard_ids:
        tiles = refs.get(dashboard_id, set())
        keys = {viz_domain[viz_id] for viz_id in tiles if viz_id in viz_domain}
        if not keys:
            unreferenced.append(dashboard_id)
            continue
        for key in keys:
            domain_dashboards[key].add(dashboard_id)

    covered_by_dashboards: dict[str, set[str]] = {}
    for key, ids in domain_dashboards.items():
        covered: set[str] = set()
        for dashboard_id in ids:
            covered |= refs.get(dashboard_id, set())
        covered_by_dashboards[key] = covered

    domains: list[Domain] = []
    per_domain: dict[str, DomainCounts] = {}
    for key, label in seed:
        listed_dashboards = domain_dashboards[key]
        covered = covered_by_dashboards[key]
        # Only visualizations this domain owns that no listed dashboard already shows.
        orphans = sorted(
            viz_id for viz_id, owner in viz_domain.items() if owner == key and viz_id not in covered
        )
        domains.append(
            Domain(
                key=key,
                label=label,
                description=TODO_DESCRIPTION,
                workspace_id=DEFAULT_WORKSPACE_ID_TEMPLATE.format(key_kebab=key_kebab(key)),
                dashboards=tuple(sorted(listed_dashboards)),
                visualizations=tuple(orphans),
                ai=AiSelection(),
            )
        )
        per_domain[key] = DomainCounts(
            dashboards=len(listed_dashboards),
            visualizations_direct=len(orphans),
            visualizations_via_dashboards=len(covered),
        )

    ai_ids: list[str] = []
    for _channel, attributes in AI_CHANNELS:
        for attribute in attributes:
            for obj in getattr(analytics, attribute, None) or []:
                ai_ids.append(str(obj.id))

    unassigned = UnassignedSelection(
        dashboards=tuple(
            Exclusion(
                id=dashboard_id,
                reason="TODO: references no visualization the prefix convention could classify.",
            )
            for dashboard_id in sorted(unreferenced)
        ),
        visualizations=tuple(
            Exclusion(
                id=viz_id,
                reason="TODO: id matches no viz_<domain>_ prefix; classify or exclude with a reason.",
            )
            for viz_id in sorted(unmatched)
        ),
        ai=tuple(
            Exclusion(
                id=identifier,
                reason="TODO: AI context is deny-by-default; assign to a domain or exclude.",
            )
            for identifier in sorted(set(ai_ids))
        ),
    )

    manifest = DomainManifest(
        version=SCHEMA_VERSION,
        parent_workspace_id=parent_workspace_id,
        workspace_id_template=DEFAULT_WORKSPACE_ID_TEMPLATE,
        workspace_name_template=DEFAULT_WORKSPACE_NAME_TEMPLATE,
        domains=tuple(sorted(domains, key=lambda domain: domain.key)),
        shared=SharedSelection(),
        unassigned=unassigned,
        path=None,
    )

    report = BootstrapReport(
        matched_visualizations=len(viz_domain),
        unmatched_visualizations=tuple(sorted(unmatched)),
        dashboards_assigned=len({d for ids in domain_dashboards.values() for d in ids}),
        dashboards_unreferenced=tuple(sorted(unreferenced)),
        ai_objects_parked=len(set(ai_ids)),
        per_domain=per_domain,
    )
    return manifest, report
