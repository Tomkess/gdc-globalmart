"""Coverage: does the manifest account for everything in the parent?

STEERING is explicit — "every dashboard and visualization in the parent must land in at
least one domain, or the split fails loudly". This module is that enforcement, and it is
pure: it takes a loaded model and a loaded manifest, touches no host, writes no file.

Three ways an object can be accounted for, and no fourth:

1. **assigned** — at least one domain lists it, or reaches it through a listed dashboard;
2. **shared** — the ``shared:`` block puts it in every child;
3. **excluded** — ``unassigned:`` names it *with a reason*.

Anything else is ``uncovered``, and uncovered is fatal. That is the whole point: the
predecessor's failure was not that it excluded a mixed-domain dashboard, it was that the
exclusion was invisible. Here an exclusion costs a sentence, and the absence of one costs a
red build.

AI context is **deny-by-default**: a memory item, parameter, agent personality or knowledge
object reaches a child only when a domain names it, a tag rule matches it, or ``shared.ai``
declares it. The failure mode STEERING names for AI is leakage, not absence — so an
unclassified AI object is uncovered rather than quietly inherited.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.config import GlobalmartError
from globalmart.domains import Domain, DomainManifest
from globalmart.traversal import iter_dashboard_insight_refs

#: The AI channels a workspace layout can carry, in report order. Attribute names are tried
#: in turn because the SDK has grown these one at a time (``memory_items`` and
#: ``parameters`` arrived in 1.74) and agent personalities are org-scoped today — a channel
#: the installed SDK does not model simply reports zero objects rather than raising.
AI_CHANNELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("memory_items", ("memory_items",)),
    ("parameters", ("parameters",)),
    ("agents", ("agents", "agent_personalities")),
    ("knowledge", ("ai_knowledge", "knowledge", "knowledge_items")),
)

#: Which `AiSelection` id list selects which channel.
_CHANNEL_SELECTOR = {
    "memory_items": "memory_item_ids",
    "parameters": "parameter_ids",
    "agents": "agent_ids",
    "knowledge": "knowledge_ids",
}


class CoverageError(GlobalmartError):
    """Something in the parent is in no domain, or the manifest names something absent."""

    def __init__(self, message: str, report: CoverageReport) -> None:
        super().__init__(message)
        self.report = report


@dataclass(frozen=True)
class DomainCounts:
    """What one domain actually received. Printed as a table row."""

    dashboards: int = 0
    visualizations_direct: int = 0
    visualizations_via_dashboards: int = 0
    memory_items: int = 0
    parameters: int = 0
    agents: int = 0
    knowledge: int = 0
    #: Declared LDM widening. Printed beside the others so it stays visible, never added to
    #: any coverage total — ``ldm_include`` is headroom, not membership.
    ldm_include: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class CoverageReport:
    """The whole picture: what is covered, by whom, and what is not."""

    dashboards_total: int = 0
    visualizations_total: int = 0
    ai_objects_total: int = 0

    assigned_dashboards: dict[str, tuple[str, ...]] = field(default_factory=dict)
    assigned_visualizations: dict[str, tuple[str, ...]] = field(default_factory=dict)
    assigned_ai: dict[str, tuple[str, ...]] = field(default_factory=dict)

    multi_homed: dict[str, tuple[str, ...]] = field(default_factory=dict)
    shared_ids: tuple[str, ...] = ()
    excluded: dict[str, str] = field(default_factory=dict)

    uncovered_dashboards: tuple[str, ...] = ()
    uncovered_visualizations: tuple[str, ...] = ()
    uncovered_ai: tuple[str, ...] = ()

    unknown_ids: dict[str, str] = field(default_factory=dict)
    placeholder_reasons: dict[str, str] = field(default_factory=dict)

    redundant_visualizations: dict[str, tuple[str, ...]] = field(default_factory=dict)
    cross_domain_tiles: dict[str, tuple[str, ...]] = field(default_factory=dict)

    per_domain: dict[str, DomainCounts] = field(default_factory=dict)

    def is_clean(self, *, strict: bool = False) -> bool:
        fatal = (
            self.uncovered_dashboards
            or self.uncovered_visualizations
            or self.uncovered_ai
            or self.unknown_ids
        )
        if fatal:
            return False
        return not (strict and self.placeholder_reasons)

    def as_dict(self) -> dict[str, Any]:
        """JSON-serialisable form, for ``--format json``."""
        return {
            "dashboards_total": self.dashboards_total,
            "visualizations_total": self.visualizations_total,
            "ai_objects_total": self.ai_objects_total,
            "assigned_dashboards": {k: list(v) for k, v in self.assigned_dashboards.items()},
            "assigned_visualizations": {
                k: list(v) for k, v in self.assigned_visualizations.items()
            },
            "assigned_ai": {k: list(v) for k, v in self.assigned_ai.items()},
            "multi_homed": {k: list(v) for k, v in self.multi_homed.items()},
            "shared_ids": list(self.shared_ids),
            "excluded": dict(self.excluded),
            "uncovered_dashboards": list(self.uncovered_dashboards),
            "uncovered_visualizations": list(self.uncovered_visualizations),
            "uncovered_ai": list(self.uncovered_ai),
            "unknown_ids": dict(self.unknown_ids),
            "placeholder_reasons": dict(self.placeholder_reasons),
            "redundant_visualizations": {
                k: list(v) for k, v in self.redundant_visualizations.items()
            },
            "cross_domain_tiles": {k: list(v) for k, v in self.cross_domain_tiles.items()},
            "per_domain": {k: v.as_dict() for k, v in self.per_domain.items()},
        }

    def summary_lines(self) -> list[str]:
        lines = [
            f"dashboards        : {len(self.assigned_dashboards)}/{self.dashboards_total} assigned",
            f"visualizations    : {len(self.assigned_visualizations)}/{self.visualizations_total} assigned",
            f"ai objects        : {len(self.assigned_ai)}/{self.ai_objects_total} assigned",
            f"shared            : {len(self.shared_ids)}",
            f"excluded          : {len(self.excluded)}",
            f"multi-homed       : {len(self.multi_homed)}",
        ]
        if self.uncovered_dashboards:
            lines.append(f"UNCOVERED dashboards    : {len(self.uncovered_dashboards)}")
        if self.uncovered_visualizations:
            lines.append(f"UNCOVERED visualizations: {len(self.uncovered_visualizations)}")
        if self.uncovered_ai:
            lines.append(f"UNCOVERED ai objects    : {len(self.uncovered_ai)}")
        if self.unknown_ids:
            lines.append(f"UNKNOWN manifest ids    : {len(self.unknown_ids)}")
        return lines

    def table_lines(self) -> list[str]:
        header = (
            f"{'domain':16s} {'dash':>5s} {'viz(direct)':>12s} {'viz(via dash)':>14s} "
            f"{'mem':>5s} {'param':>6s} {'agent':>6s} {'know':>5s} {'ldm+':>5s}"
        )
        lines = [header, "-" * len(header)]
        for key in sorted(self.per_domain):
            counts = self.per_domain[key]
            lines.append(
                f"{key:16s} {counts.dashboards:5d} {counts.visualizations_direct:12d} "
                f"{counts.visualizations_via_dashboards:14d} {counts.memory_items:5d} "
                f"{counts.parameters:6d} {counts.agents:6d} {counts.knowledge:5d} "
                f"{counts.ldm_include:5d}"
            )
        return lines


# --- parent enumeration ------------------------------------------------------


def _ids(container: Any, attribute: str) -> list[str]:
    return [str(obj.id) for obj in (getattr(container, attribute, None) or [])]


def _ai_objects(model: CatalogDeclarativeWorkspaceModel) -> dict[str, dict[str, tuple[str, ...]]]:
    """``channel -> {object id: tags}`` for every AI channel the model actually carries."""
    analytics = model.analytics
    out: dict[str, dict[str, tuple[str, ...]]] = {}
    for channel, attributes in AI_CHANNELS:
        objects: dict[str, tuple[str, ...]] = {}
        for attribute in attributes:
            for obj in getattr(analytics, attribute, None) or []:
                tags = tuple(str(tag) for tag in (getattr(obj, "tags", None) or []))
                objects[str(obj.id)] = tags
        out[channel] = objects
    return out


def _dataset_ids(model: CatalogDeclarativeWorkspaceModel) -> set[str]:
    ldm = model.ldm
    return {str(dataset.id) for dataset in (getattr(ldm, "datasets", None) or [])}


# --- the check ---------------------------------------------------------------


def _add(mapping: dict[str, set[str]], identifier: str, key: str) -> None:
    mapping.setdefault(identifier, set()).add(key)


def _freeze(mapping: dict[str, set[str]]) -> dict[str, tuple[str, ...]]:
    return {identifier: tuple(sorted(keys)) for identifier, keys in sorted(mapping.items())}


def check_coverage(
    model: CatalogDeclarativeWorkspaceModel, manifest: DomainManifest
) -> CoverageReport:
    """Classify every dashboard, visualization and AI object in the parent."""
    report = CoverageReport()

    analytics = model.analytics
    dashboard_ids = set(_ids(analytics, "analytical_dashboards"))
    visualization_ids = set(_ids(analytics, "visualization_objects"))
    ai_objects = _ai_objects(model)
    dataset_ids = _dataset_ids(model)

    report.dashboards_total = len(dashboard_ids)
    report.visualizations_total = len(visualization_ids)
    report.ai_objects_total = sum(len(objects) for objects in ai_objects.values())

    # Which visualizations each dashboard puts on screen. Refs to objects absent from the
    # parent are dropped here: they cannot be covered or uncovered because they do not
    # exist, and a dangling tile is FEAT-004's closure problem, not a membership question.
    refs: dict[str, set[str]] = {}
    for dashboard_id, viz_id in iter_dashboard_insight_refs(model):
        if viz_id in visualization_ids:
            refs.setdefault(dashboard_id, set()).add(viz_id)

    assigned_dashboards: dict[str, set[str]] = {}
    assigned_visualizations: dict[str, set[str]] = {}
    assigned_ai: dict[str, set[str]] = {}
    unknown: dict[str, str] = {}
    redundant: dict[str, set[str]] = {}
    cross_domain: dict[str, tuple[str, ...]] = {}
    per_domain: dict[str, DomainCounts] = {}

    def note_unknown(identifier: str, path: str) -> None:
        unknown.setdefault(identifier, path)

    for index, domain in enumerate(manifest.domains):
        path = f"domains[{index}]"
        via_dashboards: set[str] = set()

        for position, dashboard_id in enumerate(domain.dashboards):
            if dashboard_id not in dashboard_ids:
                note_unknown(dashboard_id, f"{path}.dashboards[{position}]")
                continue
            _add(assigned_dashboards, dashboard_id, domain.key)
            via_dashboards |= refs.get(dashboard_id, set())

        direct: set[str] = set()
        for position, viz_id in enumerate(domain.visualizations):
            if viz_id not in visualization_ids:
                note_unknown(viz_id, f"{path}.visualizations[{position}]")
                continue
            direct.add(viz_id)
            if viz_id in via_dashboards:
                redundant.setdefault(domain.key, set()).add(viz_id)

        for viz_id in direct | via_dashboards:
            _add(assigned_visualizations, viz_id, domain.key)

        counts = _domain_ai_counts(domain, manifest, ai_objects, assigned_ai, note_unknown, path)

        for position, dataset_id in enumerate(domain.ldm_include):
            if dataset_id not in dataset_ids:
                note_unknown(dataset_id, f"{path}.ldm_include[{position}]")

        per_domain[domain.key] = DomainCounts(
            dashboards=len([d for d in domain.dashboards if d in dashboard_ids]),
            visualizations_direct=len(direct),
            visualizations_via_dashboards=len(via_dashboards),
            memory_items=counts["memory_items"],
            parameters=counts["parameters"],
            agents=counts["agents"],
            knowledge=counts["knowledge"],
            ldm_include=len([d for d in domain.ldm_include if d in dataset_ids]),
        )

    # A tile shown by this domain's dashboard that some *other* domain also owns. Listing a
    # dashboard covers its tiles by construction, so this can never be uncovered — but it is
    # the shape of the split worth seeing: these visualizations get copied into more than one
    # child, which is the case the predecessor resolved by dropping the dashboard entirely.
    # Reported, never fatal.
    for domain in manifest.domains:
        for dashboard_id in domain.dashboards:
            strays = sorted(
                viz_id
                for viz_id in refs.get(dashboard_id, set())
                if assigned_visualizations.get(viz_id, set()) - {domain.key}
            )
            if strays:
                cross_domain[f"{domain.key}/{dashboard_id}"] = tuple(strays)

    # --- shared: in every child, so it covers by definition ---
    shared_ids: set[str] = set()
    shared_via_dashboards: set[str] = set()
    for position, dashboard_id in enumerate(manifest.shared.dashboards):
        if dashboard_id not in dashboard_ids:
            note_unknown(dashboard_id, f"shared.dashboards[{position}]")
            continue
        shared_ids.add(dashboard_id)
        shared_via_dashboards |= refs.get(dashboard_id, set())
    for position, viz_id in enumerate(manifest.shared.visualizations):
        if viz_id not in visualization_ids:
            note_unknown(viz_id, f"shared.visualizations[{position}]")
            continue
        shared_ids.add(viz_id)
    shared_ids |= shared_via_dashboards

    shared_ai_ids = _select_ai(manifest.shared.ai, ai_objects)
    for channel, selector in _CHANNEL_SELECTOR.items():
        for position, identifier in enumerate(getattr(manifest.shared.ai, selector)):
            if identifier not in ai_objects[channel]:
                note_unknown(identifier, f"shared.ai.{selector}[{position}]")
    shared_ids |= shared_ai_ids

    # --- unassigned: deliberate exclusions ---
    excluded: dict[str, str] = {}
    placeholders: dict[str, str] = {}
    known_by_kind = {
        "dashboards": dashboard_ids,
        "visualizations": visualization_ids,
        "ai": {i for objects in ai_objects.values() for i in objects},
    }
    for kind, known in known_by_kind.items():
        for position, exclusion in enumerate(getattr(manifest.unassigned, kind)):
            if exclusion.id not in known:
                note_unknown(exclusion.id, f"unassigned.{kind}[{position}]")
                continue
            excluded[exclusion.id] = exclusion.reason
            if exclusion.reason_is_placeholder():
                placeholders[exclusion.id] = exclusion.reason

    # --- what is left over ---
    covered_dashboards = set(assigned_dashboards) | shared_ids | set(excluded)
    covered_visualizations = set(assigned_visualizations) | shared_ids | set(excluded)
    covered_ai = set(assigned_ai) | shared_ai_ids | set(excluded)
    all_ai_ids = {i for objects in ai_objects.values() for i in objects}

    report.assigned_dashboards = _freeze(assigned_dashboards)
    report.assigned_visualizations = _freeze(assigned_visualizations)
    report.assigned_ai = _freeze(assigned_ai)
    report.multi_homed = {
        identifier: keys
        for identifier, keys in sorted(
            {
                **report.assigned_dashboards,
                **report.assigned_visualizations,
                **report.assigned_ai,
            }.items()
        )
        if len(keys) > 1
    }
    report.shared_ids = tuple(sorted(shared_ids))
    report.excluded = dict(sorted(excluded.items()))
    report.uncovered_dashboards = tuple(sorted(dashboard_ids - covered_dashboards))
    report.uncovered_visualizations = tuple(sorted(visualization_ids - covered_visualizations))
    report.uncovered_ai = tuple(sorted(all_ai_ids - covered_ai))
    report.unknown_ids = dict(sorted(unknown.items()))
    report.placeholder_reasons = dict(sorted(placeholders.items()))
    report.redundant_visualizations = _freeze(redundant)
    report.cross_domain_tiles = dict(sorted(cross_domain.items()))
    report.per_domain = per_domain

    return report


def _select_ai(
    selection: Any, ai_objects: dict[str, dict[str, tuple[str, ...]]]
) -> set[str]:
    """Which AI object ids a selection resolves to — id lists plus the tag rule."""
    selected: set[str] = set()
    for channel, selector in _CHANNEL_SELECTOR.items():
        objects = ai_objects[channel]
        for identifier in getattr(selection, selector):
            if identifier in objects:
                selected.add(identifier)
    tags = set(selection.memory_item_tags)
    if tags:
        for identifier, item_tags in ai_objects["memory_items"].items():
            if tags & set(item_tags):
                selected.add(identifier)
    return selected


def _domain_ai_counts(
    domain: Domain,
    manifest: DomainManifest,
    ai_objects: dict[str, dict[str, tuple[str, ...]]],
    assigned_ai: dict[str, set[str]],
    note_unknown: Any,
    path: str,
) -> dict[str, int]:
    """Record this domain's AI coverage and return its per-channel counts."""
    for channel, selector in _CHANNEL_SELECTOR.items():
        for position, identifier in enumerate(getattr(domain.ai, selector)):
            if identifier not in ai_objects[channel]:
                note_unknown(identifier, f"{path}.ai.{selector}[{position}]")

    selected = _select_ai(domain.ai, ai_objects)
    for identifier in selected:
        _add(assigned_ai, identifier, domain.key)

    # The shared block reaches every child, so it counts towards what this domain receives.
    shared = _select_ai(manifest.shared.ai, ai_objects)
    received = selected | shared

    return {
        channel: len(received & set(objects)) for channel, objects in ai_objects.items()
    }


def raise_for_report(report: CoverageReport, *, strict: bool = False) -> None:
    """Turn an unclean report into a loud failure. Silence is the bug being designed out."""
    problems: list[str] = []

    for label, ids in (
        ("dashboard", report.uncovered_dashboards),
        ("visualization", report.uncovered_visualizations),
        ("AI object", report.uncovered_ai),
    ):
        if ids:
            problems.append(
                f"{len(ids)} {label}(s) in the parent belong to no domain, no shared: block "
                f"and no unassigned: entry:\n    " + "\n    ".join(ids)
            )

    if report.unknown_ids:
        listed = "\n    ".join(
            f"{identifier}  ({path})" for identifier, path in report.unknown_ids.items()
        )
        problems.append(
            f"{len(report.unknown_ids)} manifest id(s) do not exist in the parent — a stale "
            f"id after a parent edit:\n    {listed}"
        )

    if strict and report.placeholder_reasons:
        listed = "\n    ".join(
            f"{identifier}: {reason!r}" for identifier, reason in report.placeholder_reasons.items()
        )
        problems.append(
            f"{len(report.placeholder_reasons)} exclusion(s) carry a placeholder reason. A "
            f"deliberate exclusion must be justified in words:\n    {listed}"
        )

    if problems:
        raise CoverageError("\n\n".join(problems), report)
