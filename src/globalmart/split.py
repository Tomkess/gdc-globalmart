"""Derive every domain workspace from the parent.

This is the feature the repo is shaped around: one editing surface (the parent), twelve
derived children, and a script that "just ensures the separation". `assemble_child` decides
nothing on its own — every collection it emits is a lookup into an id set the closure already
settled, which is what makes the result reviewable as a diff rather than as a program.

**All-or-nothing.** `split_all` collects every domain's failures before raising, so one run
names every problem rather than only the first, and writes no file for any domain if any
domain failed. A half-written `generated/workspaces/` is worse than none: it looks like a
successful split of a smaller manifest.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from globalmart.ai_context import AI_CHANNELS, AiContextSelection, filter_ai_context
from globalmart.closure import DomainClosure, MetricPolicy, build_closure, build_index, channel
from globalmart.compare import model_digest
from globalmart.config import GlobalmartError
from globalmart.counts import ObjectCounts, count_objects
from globalmart.domains import Domain, DomainManifest
from globalmart.layout_io import write_model_json
from globalmart.prune import dataset_column_usage, prune_ldm
from globalmart.verify import verify_child


class SplitCoverageError(GlobalmartError):
    """An object in the parent reached no child and is on no exclusion list."""


class SplitFailedError(GlobalmartError):
    """One or more domains failed. Nothing was written."""

    def __init__(self, failures: list[str]) -> None:
        listed = "\n\n  ".join(failures)
        super().__init__(
            f"{len(failures)} domain(s) failed; no file was written for any domain:\n\n  {listed}"
        )
        self.failures = failures


@dataclass
class DomainSplitResult:
    """What one child turned out to be. Printed by the CLI, asserted by the tests."""

    domain_key: str
    workspace_id: str
    label: str
    workspace_name: str
    counts: ObjectCounts
    datasets_retained: int = 0
    datasets_by_closure: int = 0
    datasets_declared: int = 0
    datasets_pruned: int = 0
    datasets_from_ancestors_only: int = 0
    date_instances_retained: int = 0
    metrics_from_maql_closure: int = 0
    metrics_by_dataset_fit: int = 0
    hierarchies_retained: tuple[str, ...] = ()
    export_definitions_retained: tuple[str, ...] = ()
    plugins_retained: tuple[str, ...] = ()
    extensions_retained: tuple[str, ...] = ()
    ai_context_ids: frozenset[str] = frozenset()
    unmatched_ai_tags: tuple[str, ...] = ()
    dataset_column_usage: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)
    digest: str = ""
    path: Path | None = None

    def summary_line(self) -> str:
        return (
            f"{self.domain_key:14s} {self.datasets_retained:4d} datasets "
            f"({self.datasets_by_closure} by closure, {self.datasets_declared} declared)  "
            f"{self.counts.metrics:5d} metrics  {self.counts.visualization_objects:4d} viz  "
            f"{self.counts.analytical_dashboards:3d} dash  "
            f"{len(self.ai_context_ids):3d} ai"
        )


@dataclass
class SplitResult:
    """The whole run."""

    domains: list[DomainSplitResult] = field(default_factory=list)
    unassigned_ids: frozenset[str] = frozenset()
    shared_ids: frozenset[str] = frozenset()
    coverage_ok: bool = True

    def summary_lines(self) -> list[str]:
        lines = [result.summary_line() for result in self.domains]
        lines.append("")
        lines.append(f"shared objects in every child : {len(self.shared_ids)}")
        lines.append(f"excluded by the manifest      : {len(self.unassigned_ids)}")
        return lines


def _set_channel(analytics: Any, name: str, objects: list[Any]) -> None:
    """Assign a channel if the SDK models it; silently skip one it does not."""
    if hasattr(analytics, name):
        setattr(analytics, name, objects)


def _retain(pool: dict[str, Any], keep: frozenset[str]) -> list[Any]:
    return [copy.deepcopy(pool[key]) for key in sorted(keep) if key in pool]


def assemble_child(
    model: Any,
    domain: Domain,
    manifest: DomainManifest,
    closure: DomainClosure,
    ai: AiContextSelection,
) -> Any:
    """Build the child model. Pure lookups — the closure already decided everything."""
    child = copy.deepcopy(model)
    child.ldm = prune_ldm(model.ldm, closure.dataset_ids, closure.date_instance_ids)

    analytics = child.analytics
    _set_channel(analytics, "metrics", _retain(channel(model, "metrics"), closure.metric_ids))
    _set_channel(
        analytics,
        "visualization_objects",
        _retain(channel(model, "visualization_objects"), closure.visualization_ids),
    )
    _set_channel(
        analytics,
        "analytical_dashboards",
        _retain(channel(model, "analytical_dashboards"), closure.dashboard_ids),
    )
    _set_channel(
        analytics,
        "filter_contexts",
        _retain(channel(model, "filter_contexts"), closure.filter_context_ids),
    )
    # The four the predecessor hardcoded to []. Each is retained by reachability and its
    # dependencies are already in the LDM, because stage 4b fed them in before pruning.
    _set_channel(
        analytics,
        "attribute_hierarchies",
        _retain(channel(model, "attribute_hierarchies"), closure.attribute_hierarchy_ids),
    )
    _set_channel(
        analytics,
        "export_definitions",
        _retain(channel(model, "export_definitions"), closure.export_definition_ids),
    )
    _set_channel(
        analytics,
        "dashboard_plugins",
        _retain(channel(model, "dashboard_plugins"), closure.dashboard_plugin_ids),
    )
    _set_channel(
        analytics,
        "analytical_dashboard_extensions",
        _retain(
            channel(model, "analytical_dashboard_extensions"), closure.dashboard_extension_ids
        ),
    )

    for channel_name, attributes, _field in AI_CHANNELS:
        objects = list(ai.objects.get(channel_name, ()))
        for attribute in attributes:
            if hasattr(analytics, attribute):
                setattr(analytics, attribute, [copy.deepcopy(obj) for obj in objects])
                break

    return child


def split_domain(
    model: Any,
    domain: Domain,
    manifest: DomainManifest,
    *,
    index: Any = None,
    metric_policy: MetricPolicy = MetricPolicy.DATASET_FIT,
) -> tuple[Any, DomainSplitResult]:
    """Closure -> prune -> assemble -> verify, for one domain."""
    entity_index = index if index is not None else build_index(model)
    closure = build_closure(model, domain, manifest, index=entity_index, metric_policy=metric_policy)
    ai = filter_ai_context(model, domain, manifest)
    child = assemble_child(model, domain, manifest, closure, ai)

    verify_child(child, domain.key, closure=closure)

    parent_datasets = len(getattr(model.ldm, "datasets", None) or [])
    directly_measured = _directly_measured_metrics(model, closure)

    result = DomainSplitResult(
        domain_key=domain.key,
        workspace_id=domain.workspace_id,
        label=domain.label,
        workspace_name=manifest.resolve_workspace_name(domain),
        counts=count_objects(child),
        datasets_retained=len(closure.dataset_ids),
        datasets_by_closure=len(closure.datasets_by_closure()),
        datasets_declared=len(closure.declared_dataset_ids - closure.seed_dataset_ids),
        datasets_pruned=parent_datasets - len(closure.dataset_ids),
        datasets_from_ancestors_only=len(closure.datasets_from_ancestors_only()),
        date_instances_retained=len(closure.date_instance_ids),
        metrics_from_maql_closure=len(
            closure.metric_ids - directly_measured - closure.metrics_by_dataset_fit
        ),
        metrics_by_dataset_fit=len(closure.metrics_by_dataset_fit - directly_measured),
        hierarchies_retained=tuple(sorted(closure.attribute_hierarchy_ids)),
        export_definitions_retained=tuple(sorted(closure.export_definition_ids)),
        plugins_retained=tuple(sorted(closure.dashboard_plugin_ids)),
        extensions_retained=tuple(sorted(closure.dashboard_extension_ids)),
        ai_context_ids=ai.ids(),
        unmatched_ai_tags=ai.unmatched_tags,
        dataset_column_usage=dataset_column_usage(child.ldm, closure.entity_ids),
        digest=model_digest(child),
    )
    return child, result


def _directly_measured_metrics(model: Any, closure: DomainClosure) -> frozenset[str]:
    """Metrics a retained visualization names outright — the rest came from MAQL closure."""
    from globalmart.refs import iter_content_refs

    visualizations = channel(model, "visualization_objects")
    direct: set[str] = set()
    for viz_id in closure.visualization_ids:
        viz = visualizations.get(viz_id)
        if viz is None:
            continue
        for ref in iter_content_refs(viz):
            if ref.type == "metric":
                direct.add(ref.id)
    return frozenset(direct)


def split_all(
    model: Any,
    manifest: DomainManifest,
    *,
    only: set[str] | None = None,
    out: Path | None = None,
    write: bool = True,
    metric_policy: MetricPolicy = MetricPolicy.DATASET_FIT,
) -> SplitResult:
    """Split every domain. Writes nothing unless every domain succeeded."""
    index = build_index(model)
    keys = [key for key in manifest.keys() if only is None or key in only]  # noqa: SIM118 - DomainManifest.keys() is a method, not a mapping

    if only:
        unknown = sorted(only - set(manifest.keys()))  # noqa: SIM118 - DomainManifest.keys() is a method, not a mapping
        if unknown:
            raise GlobalmartError(
                f"--only names domain(s) absent from the manifest: {', '.join(unknown)}"
            )

    children: list[tuple[Any, DomainSplitResult]] = []
    failures: list[str] = []

    for key in keys:
        domain = manifest.by_key(key)
        try:
            children.append(
                split_domain(model, domain, manifest, index=index, metric_policy=metric_policy)
            )
        except GlobalmartError as error:
            failures.append(f"[{key}] {error}")

    if failures:
        raise SplitFailedError(failures)

    result = SplitResult(
        domains=[split_result for _child, split_result in children],
        unassigned_ids=manifest.unassigned_ids(),
        shared_ids=frozenset(manifest.shared.dashboards) | frozenset(manifest.shared.visualizations),
    )

    # Output coverage (AC #9): a valid manifest can still leave an object unreached, because
    # coverage on input is about the manifest's lists and this is about what the closure
    # actually retained.
    if only is None:
        _assert_output_coverage(model, manifest, result)

    if write and out is not None:
        for (child, split_result), key in zip(children, keys, strict=True):
            domain = manifest.by_key(key)
            split_result.path = write_model_json(
                child, Path(out) / f"{domain.workspace_id}.json"
            )

    return result


def _assert_output_coverage(model: Any, manifest: DomainManifest, result: SplitResult) -> None:
    reached: set[str] = set()
    for split_result in result.domains:
        reached |= {split_result.domain_key}

    covered_dashboards: set[str] = set()
    covered_visualizations: set[str] = set()
    for domain in manifest.domains:
        covered_dashboards |= set(domain.dashboards)
        covered_visualizations |= set(domain.visualizations)
    covered_dashboards |= set(manifest.shared.dashboards)
    covered_visualizations |= set(manifest.shared.visualizations)

    # Everything a retained dashboard shows counts as reached.
    from globalmart.refs import iter_dashboard_viz_refs

    dashboards = channel(model, "analytical_dashboards")
    for dashboard_id in covered_dashboards:
        dashboard = dashboards.get(dashboard_id)
        if dashboard is not None:
            covered_visualizations |= {ref.id for ref in iter_dashboard_viz_refs(dashboard)}

    excluded = manifest.unassigned_ids()
    parent_dashboards = set(dashboards)
    parent_visualizations = set(channel(model, "visualization_objects"))

    missing_dashboards = sorted(parent_dashboards - covered_dashboards - excluded)
    missing_visualizations = sorted(parent_visualizations - covered_visualizations - excluded)

    if missing_dashboards or missing_visualizations:
        result.coverage_ok = False
        raise SplitCoverageError(
            "the split reached no child for:\n"
            + "".join(f"    dashboard      {i}\n" for i in missing_dashboards)
            + "".join(f"    visualization  {i}\n" for i in missing_visualizations)
            + "Assign them in config/domains.yaml or list them under unassigned: with a reason."
        )
