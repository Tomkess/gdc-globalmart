"""Binds each dashboard's date filter to the date dataset its own content uses.

Every GlobalMart dashboard ships a relative date filter. None of them was bound to
anything, so none of them filtered. Found by hand on 2026-09-21: changing the filter
changed no number, in the parent or in any of the twelve domain workspaces.

A dashboard `dateFilter` carries an optional `dataSet`. Without it the filter is a *common*
date filter, resolved against whatever date dataset each insight declares — and no insight
in this tree declares one. So the filter bound to nothing and was silently ignored, which
is indistinguishable from working until somebody checks a number.

**The date dataset is derived, never assumed.** A dashboard's content reaches metrics,
metrics reach facts, facts reach datasets, and datasets reach date instances. Whatever that
walk arrives at is what the filter must bind to. GlobalMart declares two date instances and
some workspaces carry both, so a blanket substitution could be wrong for some dashboards
while looking right everywhere — and a filter bound to the wrong date is worse than one
that is obviously unbound, because it produces numbers.

As it happens every dashboard currently resolves to the same date instance, and the second
is referenced by no visualization or metric at all. That is a fact about today's content,
not a rule: the derivation stands so the next dashboard cannot quietly break it.

**Ambiguity stops the build.** A dashboard resolving to no date instance, or to several
with no override, is named and the run fails. Guessing here is how the original defect got
in: something plausible was written, nothing checked it, and it was wrong for two years.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from globalmart.config import GlobalmartError
from globalmart.maql import iter_maql_refs
from globalmart.prune import build_entity_index
from globalmart.refs import (
    iter_dashboard_viz_refs,
    iter_entity_refs,
    iter_inline_maql,
    iter_metric_refs,
)


class DateFilterError(GlobalmartError):
    """A dashboard's date filter cannot be bound without guessing."""


@dataclass
class BindReport:
    dashboards: int = 0
    bound: dict[str, str] = field(default_factory=dict)
    already_bound: tuple[str, ...] = ()
    no_date_filter: tuple[str, ...] = ()
    unresolved: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """Dashboard id -> the date instances it reached. Empty tuple means none at all."""

    def ok(self) -> bool:
        return not self.unresolved

    def summary_lines(self) -> list[str]:
        lines = [
            f"dashboards        : {self.dashboards}",
            f"bound             : {len(self.bound)}",
            f"already bound     : {len(self.already_bound)}",
            f"no date filter    : {len(self.no_date_filter)}",
        ]
        by_dataset: dict[str, int] = {}
        for dataset in self.bound.values():
            by_dataset[dataset] = by_dataset.get(dataset, 0) + 1
        for dataset, count in sorted(by_dataset.items()):
            lines.append(f"  -> {dataset:22} {count}")
        if self.unresolved:
            lines.append(f"UNRESOLVED        : {len(self.unresolved)}")
            for dashboard, reached in sorted(self.unresolved.items())[:10]:
                found = ", ".join(reached) if reached else "none"
                lines.append(f"  {dashboard}: reached {found}")
        return lines


def _visualization_ids(dashboard: Any) -> set[str]:
    """The visualizations a dashboard shows — widgets, nested layouts, drill targets."""
    return {ref.id for ref in iter_dashboard_viz_refs(dashboard)}


def _identifiers_in(obj: Any) -> set[str]:
    """LDM ids a visualization refers to directly — attributes, labels, facts, dates.

    Deliberately excludes metrics, which `iter_entity_refs` also omits: they are followed
    separately so their MAQL can be walked. A visualization that names only a metric has no
    LDM ids of its own, and reaching its dates means going through that metric.
    """
    return {ref.id for ref in iter_entity_refs(obj)}


def date_instances_for(model: Any, dashboard: Any) -> tuple[str, ...]:
    """Which date instances one dashboard's content actually depends on.

    Walks visualizations, then the metrics they use and the metrics *those* use, down to the
    facts and labels that resolve to datasets, then out along dataset references to any date
    instance. Returns them sorted, so the caller decides what to do with none or several
    rather than being handed a guess.
    """
    index = build_entity_index(model.ldm)
    analytics = model.analytics

    metrics_by_id = {metric.id: metric for metric in analytics.metrics}
    visualizations = {viz.id: viz for viz in analytics.visualization_objects}

    seen_metrics: set[str] = set()
    identifiers: set[str] = set()

    def absorb_metric(metric_id: str) -> None:
        if metric_id in seen_metrics:
            return
        seen_metrics.add(metric_id)
        metric = metrics_by_id.get(metric_id)
        if metric is None:
            return
        maql = (metric.content or {}).get("maql")
        for ref in iter_maql_refs(maql):
            if ref.kind == "metric":
                absorb_metric(ref.id)
            else:
                identifiers.add(ref.id)

    for viz_id in _visualization_ids(dashboard):
        viz = visualizations.get(viz_id)
        if viz is None:
            continue
        identifiers |= _identifiers_in(viz)
        # A measure names a metric, or carries raw MAQL inline. Both are how a
        # visualization reaches a fact, and therefore a dataset, and therefore a date.
        for ref in iter_metric_refs(viz):
            absorb_metric(ref.id)
        for _, maql in iter_inline_maql(viz):
            for inline in iter_maql_refs(maql):
                if inline.kind == "metric":
                    absorb_metric(inline.id)
                else:
                    identifiers.add(inline.id)

    reached: set[str] = set()
    for identifier in identifiers:
        # A label or fact id carries its owner as a prefix — `transaction_date.month`
        # resolves to the date instance directly, which is the common case here.
        head = identifier.split(".", 1)[0]
        for candidate in (identifier, head):
            if candidate in index.date_instance_ids:
                reached.add(candidate)
                break
        else:
            owner = index.owner_of(identifier) or index.owner_of(head)
            if owner is None:
                continue
            _, owner_id = owner
            if owner_id in index.date_instance_ids:
                reached.add(owner_id)
                continue
            for target in index.references.get(owner_id, ()):
                if target in index.date_instance_ids:
                    reached.add(target)

    return tuple(sorted(reached))


def bind_date_filters(model: Any, *, overrides: dict[str, str] | None = None) -> BindReport:
    """Write `dataSet` into every dashboard date filter. Mutates the model in place."""
    overrides = overrides or {}
    analytics = model.analytics
    contexts = {context.id: context for context in analytics.filter_contexts}
    report = BindReport()

    already: list[str] = []
    missing: list[str] = []

    for dashboard in analytics.analytical_dashboards:
        report.dashboards += 1
        ref = (dashboard.content or {}).get("filterContextRef") or {}
        context_id = (ref.get("identifier") or {}).get("id")
        context = contexts.get(context_id)
        if context is None:
            missing.append(dashboard.id)
            continue

        date_filters = [
            item["dateFilter"] for item in (context.content or {}).get("filters", []) if "dateFilter" in item
        ]
        if not date_filters:
            missing.append(dashboard.id)
            continue
        if all("dataSet" in item for item in date_filters):
            already.append(dashboard.id)
            continue

        chosen = overrides.get(dashboard.id)
        if chosen is None:
            reached = date_instances_for(model, dashboard)
            if len(reached) != 1:
                report.unresolved[dashboard.id] = reached
                continue
            chosen = reached[0]

        for item in date_filters:
            item["dataSet"] = {"identifier": {"id": chosen, "type": "dataset"}}
        report.bound[dashboard.id] = chosen

    report.already_bound = tuple(sorted(already))
    report.no_date_filter = tuple(sorted(missing))
    return report
