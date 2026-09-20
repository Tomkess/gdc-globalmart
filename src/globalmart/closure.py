"""Transitive closure: what one domain's workspace has to contain.

The manifest names a domain's dashboards and visualizations. Everything else a child needs
is implied by them, and this module computes the implication to fixpoint.

**One rule throughout: reachability decides what travels, and whatever travels pulls its
dependencies in with it.** A dashboard pulls its visualizations; a visualization pulls its
metrics; a metric's MAQL pulls other metrics and LDM entities; an attribute hierarchy pulls
the datasets of the attributes it names. Nothing is ever excluded because a dependency did
not independently survive an earlier pass — the dependency is included instead. The only
failure is a reference to something that does not exist in the *parent* at all, which stops
the whole run.

The stages:

1. **Seed** — the domain's dashboards and visualizations, unioned with the manifest's
   ``shared`` block (shared objects belong in *every* child, so they are part of the seed,
   not an afterthought), plus ``ldm_include`` as declared dataset seeds.
2. **Dashboards** → visualizations, filter contexts, plugins, drill-target dashboards.
3. **Visualizations** → metrics and LDM entities, including inline MAQL.
4. **Metric MAQL closure** — a worklist, so a metric referencing a metric referencing a
   metric all travel. This is the one piece kept verbatim from the predecessor; without it
   a child fails to load with "metrics ... cannot be found".
4b. **Auxiliary objects** — hierarchies, export definitions, plugins, dashboard extensions,
   filter contexts — retained by reachability and then feeding their own references back in.
   Deciding this *before* datasets are resolved is what makes the pull-in rule work.
5. **Entities → datasets → join ancestors → date instances.**

Stages 2–4b loop together, because a retained export definition can name a dashboard that
pulls in new visualizations that pull in new metrics.

``why`` records what pulled each object in. It is what turns "metric X is missing" into a
sentence naming the dashboard and the visualization it came through, and what lets the split
report say a dataset arrived solely because one dashboard needed it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from globalmart.domains import Domain, DomainManifest
from globalmart.maql import RefKind, iter_maql_refs
from globalmart.prune import DanglingReferenceError, EntityIndex, expand_join_ancestors
from globalmart.refs import (
    iter_content_refs,
    iter_dashboard_dashboard_refs,
    iter_dashboard_filter_refs,
    iter_dashboard_plugin_refs,
    iter_dashboard_viz_refs,
    iter_entity_refs,
    iter_hierarchy_refs,
    iter_inline_maql,
)

#: Where each analytics channel lives on ``model.analytics``. One tuple per channel because
#: the SDK has grown these over time and a channel it does not model must be absent rather
#: than fatal.
_CHANNELS: dict[str, tuple[str, ...]] = {
    "metrics": ("metrics",),
    "visualization_objects": ("visualization_objects",),
    "analytical_dashboards": ("analytical_dashboards",),
    "filter_contexts": ("filter_contexts",),
    "attribute_hierarchies": ("attribute_hierarchies",),
    "dashboard_plugins": ("dashboard_plugins",),
    "export_definitions": ("export_definitions",),
    "analytical_dashboard_extensions": ("analytical_dashboard_extensions",),
}


def channel(model: Any, name: str) -> dict[str, Any]:
    """``{id: object}`` for one analytics channel, empty when the SDK does not model it."""
    analytics = model.analytics
    for attribute in _CHANNELS[name]:
        objects = getattr(analytics, attribute, None)
        if objects:
            return {str(obj.id): obj for obj in objects}
    return {}


class MetricPolicy(StrEnum):
    """Which of the parent's metrics a child keeps.

    ``REACHABLE`` is pure closure: a metric travels only when a retained visualization
    measures it, or another retained metric's MAQL names it. Minimal and obviously correct.

    ``DATASET_FIT`` additionally keeps any metric whose **entire** transitive LDM dependency
    already resolves inside the child. It cannot widen the LDM — a metric qualifies only
    because every dataset it needs is already there — so it is free in the one dimension
    this feature exists to control, while restoring the authored metric library.

    That library is the reason the choice matters. Measured on the parent: 1091 metrics, of
    which 344 sit on a visualization and **747 sit on none** — tagged L2–L5, a deliberate
    metric hierarchy. Under ``REACHABLE`` all 747 vanish from every child, which for a
    workspace built to exercise AI search, routing and MCP tooling removes most of what is
    being searched. Under ``DATASET_FIT`` a domain keeps the ones its own tables support.
    """

    REACHABLE = "reachable"
    DATASET_FIT = "dataset-fit"


@dataclass(frozen=True)
class DomainClosure:
    """Everything one domain's child workspace retains."""

    domain_key: str
    dashboard_ids: frozenset[str] = frozenset()
    visualization_ids: frozenset[str] = frozenset()
    metric_ids: frozenset[str] = frozenset()
    filter_context_ids: frozenset[str] = frozenset()
    attribute_hierarchy_ids: frozenset[str] = frozenset()
    export_definition_ids: frozenset[str] = frozenset()
    dashboard_plugin_ids: frozenset[str] = frozenset()
    dashboard_extension_ids: frozenset[str] = frozenset()
    #: Every LDM entity id any retained object touches — auxiliary objects included.
    entity_ids: frozenset[str] = frozenset()
    #: Datasets owning those entities, *before* join-ancestor expansion.
    seed_dataset_ids: frozenset[str] = frozenset()
    #: ``domain.ldm_include`` — authoring headroom, reported apart from closure reach.
    declared_dataset_ids: frozenset[str] = frozenset()
    dataset_ids: frozenset[str] = frozenset()
    date_instance_ids: frozenset[str] = frozenset()
    #: Metrics kept because the child's datasets already support them, not because anything
    #: retained references them. Empty under ``MetricPolicy.REACHABLE``.
    metrics_by_dataset_fit: frozenset[str] = frozenset()
    why: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def datasets_by_closure(self) -> frozenset[str]:
        return self.dataset_ids - (self.declared_dataset_ids - self.seed_dataset_ids)

    def datasets_from_ancestors_only(self) -> frozenset[str]:
        return self.dataset_ids - self.seed_dataset_ids - self.declared_dataset_ids


class _Builder:
    """Mutable working state. `build_closure` is the only thing that constructs one."""

    def __init__(self, model: Any, index: EntityIndex, domain: Domain) -> None:
        self.model = model
        self.index = index
        self.domain = domain

        self.dashboards = channel(model, "analytical_dashboards")
        self.visualizations = channel(model, "visualization_objects")
        self.metrics = channel(model, "metrics")
        self.filter_contexts = channel(model, "filter_contexts")
        self.hierarchies = channel(model, "attribute_hierarchies")
        self.plugins = channel(model, "dashboard_plugins")
        self.export_definitions = channel(model, "export_definitions")
        self.extensions = channel(model, "analytical_dashboard_extensions")

        self.dashboard_ids: set[str] = set()
        self.visualization_ids: set[str] = set()
        self.metric_ids: set[str] = set()
        self.filter_context_ids: set[str] = set()
        self.hierarchy_ids: set[str] = set()
        self.export_definition_ids: set[str] = set()
        self.plugin_ids: set[str] = set()
        self.extension_ids: set[str] = set()
        self.entity_ids: set[str] = set()
        self.why: dict[str, tuple[str, ...]] = {}

    # --- bookkeeping ---

    def note(self, identifier: str, reason: str) -> None:
        """Record *why* something travelled, first reason only — the shortest chain."""
        self.why.setdefault(identifier, (reason,))

    def require(self, pool: dict[str, Any], identifier: str, kind: str, context: str) -> Any:
        obj = pool.get(identifier)
        if obj is None:
            raise DanglingReferenceError(
                f"domain {self.domain.key!r}: {context} references {kind} {identifier!r}, "
                "which does not exist in the parent"
            )
        return obj

    # --- stages ---

    def seed(self, manifest: DomainManifest) -> set[str]:
        for dashboard_id in sorted(self.domain.dashboards):
            self.require(self.dashboards, dashboard_id, "dashboard", "domains.yaml")
            self.dashboard_ids.add(dashboard_id)
            self.note(dashboard_id, f"domains.yaml: {self.domain.key}.dashboards")
        for dashboard_id in sorted(manifest.shared.dashboards):
            self.require(self.dashboards, dashboard_id, "dashboard", "domains.yaml shared")
            self.dashboard_ids.add(dashboard_id)
            self.note(dashboard_id, "domains.yaml: shared.dashboards")

        for viz_id in sorted(self.domain.visualizations):
            self.require(self.visualizations, viz_id, "visualization", "domains.yaml")
            self.visualization_ids.add(viz_id)
            self.note(viz_id, f"domains.yaml: {self.domain.key}.visualizations")
        for viz_id in sorted(manifest.shared.visualizations):
            self.require(self.visualizations, viz_id, "visualization", "domains.yaml shared")
            self.visualization_ids.add(viz_id)
            self.note(viz_id, "domains.yaml: shared.visualizations")

        declared: set[str] = set()
        for dataset_id in sorted(self.domain.ldm_include):
            if dataset_id not in self.index.dataset_ids:
                raise DanglingReferenceError(
                    f"domain {self.domain.key!r}: ldm_include names dataset {dataset_id!r}, "
                    "which does not exist in the parent LDM"
                )
            declared.add(dataset_id)
            self.note(dataset_id, f"domains.yaml: {self.domain.key}.ldm_include")
        return declared

    def _absorb_entities(self, obj: Any, owner: str) -> None:
        for object_ref in iter_entity_refs(obj):
            self.entity_ids.add(object_ref.id)
            self.note(object_ref.id, f"{owner} -> {object_ref.path}")
        for path, maql in iter_inline_maql(obj):
            for maql_ref in iter_maql_refs(maql):
                if maql_ref.kind is RefKind.METRIC:
                    self.metric_ids.add(maql_ref.id)
                else:
                    self.entity_ids.add(maql_ref.id)
                self.note(maql_ref.id, f"{owner} -> {path}")

    def expand_dashboards(self) -> bool:
        grew = False
        for dashboard_id in sorted(self.dashboard_ids):
            dashboard = self.dashboards[dashboard_id]
            owner = f"dashboard {dashboard_id}"

            for ref in iter_dashboard_viz_refs(dashboard):
                self.require(self.visualizations, ref.id, "visualization", owner)
                if ref.id not in self.visualization_ids:
                    self.visualization_ids.add(ref.id)
                    self.note(ref.id, f"{owner} -> {ref.path}")
                    grew = True

            for ref in iter_dashboard_dashboard_refs(dashboard):
                self.require(self.dashboards, ref.id, "dashboard", owner)
                if ref.id not in self.dashboard_ids:
                    self.dashboard_ids.add(ref.id)
                    self.note(ref.id, f"{owner} -> {ref.path}")
                    grew = True

            for ref in iter_dashboard_filter_refs(dashboard):
                self.require(self.filter_contexts, ref.id, "filter context", owner)
                if ref.id not in self.filter_context_ids:
                    self.filter_context_ids.add(ref.id)
                    self.note(ref.id, f"{owner} -> {ref.path}")
                    grew = True

            for ref in iter_dashboard_plugin_refs(dashboard):
                self.require(self.plugins, ref.id, "dashboard plugin", owner)
                if ref.id not in self.plugin_ids:
                    self.plugin_ids.add(ref.id)
                    self.note(ref.id, f"{owner} -> {ref.path}")
                    grew = True

            for ref in iter_hierarchy_refs(dashboard):
                self.require(self.hierarchies, ref.id, "attribute hierarchy", owner)
                if ref.id not in self.hierarchy_ids:
                    self.hierarchy_ids.add(ref.id)
                    self.note(ref.id, f"{owner} -> {ref.path}")
                    grew = True

            self._absorb_entities(dashboard, owner)
        return grew

    def expand_visualizations(self) -> bool:
        grew = False
        for viz_id in sorted(self.visualization_ids):
            viz = self.visualizations[viz_id]
            owner = f"visualization {viz_id}"

            for ref in iter_content_refs(viz):
                if ref.type == "metric":
                    self.require(self.metrics, ref.id, "metric", owner)
                    if ref.id not in self.metric_ids:
                        self.metric_ids.add(ref.id)
                        self.note(ref.id, f"{owner} -> {ref.path}")
                        grew = True

            for ref in iter_hierarchy_refs(viz):
                self.require(self.hierarchies, ref.id, "attribute hierarchy", owner)
                if ref.id not in self.hierarchy_ids:
                    self.hierarchy_ids.add(ref.id)
                    self.note(ref.id, f"{owner} -> {ref.path}")
                    grew = True

            self._absorb_entities(viz, owner)
        return grew

    def expand_metrics(self) -> None:
        """Stage 4 — worklist to fixpoint. The predecessor's one correct idea."""
        worklist = sorted(self.metric_ids)
        seen: set[str] = set()
        while worklist:
            metric_id = worklist.pop()
            if metric_id in seen:
                continue
            seen.add(metric_id)
            metric = self.require(self.metrics, metric_id, "metric", "metric closure")
            owner = f"metric {metric_id}"
            content = getattr(metric, "content", None) or {}
            maql = content.get("maql") if isinstance(content, dict) else None
            for ref in iter_maql_refs(maql):
                if ref.kind is RefKind.METRIC:
                    self.require(self.metrics, ref.id, "metric", owner)
                    if ref.id not in self.metric_ids:
                        self.metric_ids.add(ref.id)
                        self.note(ref.id, f"{owner} -> MAQL {{metric/{ref.id}}}")
                    worklist.append(ref.id)
                else:
                    self.entity_ids.add(ref.id)
                    self.note(ref.id, f"{owner} -> MAQL {{{ref.kind.value}/{ref.id}}}")

    def expand_auxiliary(self) -> bool:
        """Stage 4b — retain by reachability, then feed the retained objects' refs back in."""
        grew = False

        for hierarchy_id in sorted(self.hierarchy_ids):
            hierarchy = self.hierarchies[hierarchy_id]
            self._absorb_entities(hierarchy, f"attributeHierarchy {hierarchy_id}")

        for filter_context_id in sorted(self.filter_context_ids):
            filter_context = self.filter_contexts[filter_context_id]
            self._absorb_entities(filter_context, f"filterContext {filter_context_id}")

        for plugin_id in sorted(self.plugin_ids):
            self._absorb_entities(self.plugins[plugin_id], f"dashboardPlugin {plugin_id}")

        # An export definition travels when its target does. Its target can be a dashboard
        # or a visualization, so this can grow the retained set and the caller loops.
        for export_id, export in sorted(self.export_definitions.items()):
            if export_id in self.export_definition_ids:
                continue
            targets = {ref.id for ref in iter_content_refs(export)}
            hit = targets & (self.visualization_ids | self.dashboard_ids)
            if hit:
                self.export_definition_ids.add(export_id)
                self.note(export_id, f"exportDefinition target {sorted(hit)[0]} is retained")
                self._absorb_entities(export, f"exportDefinition {export_id}")
                grew = True

        # A dashboard extension travels when the dashboard it extends does. The SDK models
        # the link as the extension's own id matching the dashboard's.
        for extension_id, extension in sorted(self.extensions.items()):
            if extension_id in self.extension_ids:
                continue
            targets = {ref.id for ref in iter_content_refs(extension)} | {extension_id}
            hit = targets & self.dashboard_ids
            if hit:
                self.extension_ids.add(extension_id)
                self.note(extension_id, f"analyticalDashboardExtension for {sorted(hit)[0]}")
                self._absorb_entities(extension, f"analyticalDashboardExtension {extension_id}")
                grew = True

        return grew


def build_closure(
    model: Any,
    domain: Domain,
    manifest: DomainManifest,
    *,
    index: EntityIndex | None = None,
    metric_policy: MetricPolicy = MetricPolicy.DATASET_FIT,
) -> DomainClosure:
    """Expand a domain's manifest seed into everything its child workspace must contain."""
    entity_index = index if index is not None else build_index(model)
    builder = _Builder(model, entity_index, domain)

    declared = builder.seed(manifest)

    # Stages 2-4b loop together: a retained export definition can name a dashboard that in
    # turn pulls new visualizations and metrics in.
    for _ in range(100):
        grew = builder.expand_dashboards()
        grew |= builder.expand_visualizations()
        builder.expand_metrics()
        grew |= builder.expand_auxiliary()
        if not grew:
            break
    else:  # pragma: no cover - a cycle that grows forever is a bug, not a shape
        raise DanglingReferenceError(
            f"domain {domain.key!r}: closure did not reach a fixpoint in 100 iterations"
        )

    # Stage 5 — entities to datasets, then join ancestors, then date instances.
    seed_datasets: set[str] = set()
    date_instances: set[str] = set()
    for entity_id in sorted(builder.entity_ids):
        kind, owner = entity_index.resolve_entity(
            entity_id, context=f"domain {domain.key!r}: {builder.why.get(entity_id, ('?',))[0]}"
        )
        if kind is RefKind.DATE_INSTANCE:
            date_instances.add(owner)
        else:
            seed_datasets.add(owner)

    dataset_ids, ancestor_dates = expand_join_ancestors(entity_index, seed_datasets | declared)
    date_instances |= set(ancestor_dates)

    # Stage 6 (optional) — the authored metric library. Deliberately *after* the LDM is
    # final, so a metric can only be admitted by datasets that are already there and can
    # never widen the child. See MetricPolicy for why this is not simply the default.
    by_fit: frozenset[str] = frozenset()
    if metric_policy is MetricPolicy.DATASET_FIT:
        by_fit = _metrics_fitting_datasets(
            builder.metrics, entity_index, dataset_ids, frozenset(date_instances)
        )
        for metric_id in sorted(by_fit - builder.metric_ids):
            builder.note(metric_id, "dataset-fit: every table this metric needs is in this child")
        builder.metric_ids |= set(by_fit)

    return DomainClosure(
        domain_key=domain.key,
        dashboard_ids=frozenset(builder.dashboard_ids),
        visualization_ids=frozenset(builder.visualization_ids),
        metric_ids=frozenset(builder.metric_ids),
        filter_context_ids=frozenset(builder.filter_context_ids),
        attribute_hierarchy_ids=frozenset(builder.hierarchy_ids),
        export_definition_ids=frozenset(builder.export_definition_ids),
        dashboard_plugin_ids=frozenset(builder.plugin_ids),
        dashboard_extension_ids=frozenset(builder.extension_ids),
        metrics_by_dataset_fit=by_fit,
        entity_ids=frozenset(builder.entity_ids),
        seed_dataset_ids=frozenset(seed_datasets),
        declared_dataset_ids=frozenset(declared),
        dataset_ids=dataset_ids,
        date_instance_ids=frozenset(date_instances),
        why=dict(sorted(builder.why.items())),
    )


def _metric_dependencies(
    metrics: dict[str, Any], metric_id: str, cache: dict[str, tuple[frozenset[str], frozenset[str]]]
) -> tuple[frozenset[str], frozenset[str]]:
    """``(entity ids, metric ids)`` a metric needs, transitively. Memoised per split run."""
    cached = cache.get(metric_id)
    if cached is not None:
        return cached

    entities: set[str] = set()
    reached: set[str] = set()
    worklist = [metric_id]
    while worklist:
        current = worklist.pop()
        if current in reached:
            continue
        metric = metrics.get(current)
        if metric is None:
            # A metric naming a metric that does not exist is the parent's problem, and
            # `verify_child` reports it against whatever retained it. Here it just means
            # this metric cannot be admitted on fit.
            return frozenset({"\0missing"}), frozenset()
        reached.add(current)
        content = getattr(metric, "content", None) or {}
        maql = content.get("maql") if isinstance(content, dict) else None
        for ref in iter_maql_refs(maql):
            if ref.kind is RefKind.METRIC:
                worklist.append(ref.id)
            else:
                entities.add(ref.id)

    result = (frozenset(entities), frozenset(reached))
    cache[metric_id] = result
    return result


def _metrics_fitting_datasets(
    metrics: dict[str, Any],
    index: EntityIndex,
    dataset_ids: frozenset[str],
    date_instance_ids: frozenset[str],
) -> frozenset[str]:
    """Metrics whose every transitive dependency already resolves inside this child."""
    cache: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    fitting: set[str] = set()

    for metric_id in metrics:
        entities, reached = _metric_dependencies(metrics, metric_id, cache)
        if not reached:
            continue
        fits = True
        for entity_id in entities:
            owner = index.owner_of(entity_id)
            if owner is None:
                fits = False
                break
            kind, owner_id = owner
            container = date_instance_ids if kind is RefKind.DATE_INSTANCE else dataset_ids
            if owner_id not in container:
                fits = False
                break
        if fits:
            # The whole chain travels: admitting a metric without the metrics it names is
            # the "metrics ... cannot be found" failure in a new costume.
            fitting |= reached

    return frozenset(fitting)


def build_index(model: Any) -> EntityIndex:
    """Convenience re-export so callers need one import, not two."""
    from globalmart.prune import build_entity_index

    return build_entity_index(model.ldm)
