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


#: Fact datasets that reach no date instance at all, each decided rather than overlooked
#: (FEAT-011 AC 7). A date filter cannot touch these, by design; a tile built on one shows
#: the same number under every window, and the live gate skips it for that reason.
#:
#: `fact_purchase_order_line` is deliberately NOT here. It has no date column of its own, but
#: it references `fact_purchase_order_header`, whose `po_date` is `transaction_date`, so a
#: date filter reaches its lines through the header. `undecided_facts` walks references
#: transitively and finds that; `tests/test_datefilters.py` pins it.
UNDATED_FACTS: dict[str, str] = {
    "fact_aged_inventory": (
        "a point-in-time snapshot of stock by age: `age_days` is its time axis, and no event "
        "date exists to filter on (aged_id, product_id, store_id, age_days, quantity)"
    ),
}


def _dates_reached_transitively(index: Any, dataset_id: str) -> set[str]:
    """Date instances reachable from a dataset along references, any number of hops."""
    reached: set[str] = set()
    seen: set[str] = set()
    pending = [dataset_id]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for target in index.references.get(current, ()):
            if target in index.date_instance_ids:
                reached.add(target)
            else:
                pending.append(target)
    return reached


def undecided_facts(model: Any, *, allowlist: dict[str, str] | None = None) -> dict[str, str]:
    """Fact datasets whose relation to dates is undecided: fact id -> why it is a finding.

    Two ways to be undecided: a `fact_*` dataset that reaches no date and is not in the
    allowlist, or an allowlist entry that no longer matches the model (it reaches a date
    now, or it is gone) — a stale entry would hide the next dateless fact behind its name.
    """
    allowed = UNDATED_FACTS if allowlist is None else allowlist
    index = build_entity_index(model.ldm)
    facts = sorted(dataset_id for dataset_id in index.dataset_ids if dataset_id.startswith("fact_"))
    findings: dict[str, str] = {}
    for fact in facts:
        dated = bool(_dates_reached_transitively(index, fact))
        if not dated and fact not in allowed:
            findings[fact] = "reaches no date and is not in UNDATED_FACTS"
        elif dated and fact in allowed:
            findings[fact] = "is in UNDATED_FACTS but reaches a date — remove the entry"
    for fact in sorted(set(allowed) - set(facts)):
        findings[fact] = "is in UNDATED_FACTS but no longer exists — remove the entry"
    return findings


@dataclass
class BindReport:
    dashboards: int = 0
    bound: dict[str, str] = field(default_factory=dict)
    already_bound: tuple[str, ...] = ()
    no_date_filter: tuple[str, ...] = ()
    unresolved: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """Dashboard id -> the date instances it reached. Empty tuple means none at all."""
    undecided_facts: dict[str, str] = field(default_factory=dict)
    """Fact id -> why its relation to dates is undecided (AC 7). Must be empty."""

    def ok(self) -> bool:
        return not self.unresolved and not self.undecided_facts

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
        if self.undecided_facts:
            lines.append(f"UNDECIDED FACTS   : {len(self.undecided_facts)}")
            for fact, reason in sorted(self.undecided_facts.items()):
                lines.append(f"  {fact}: {reason}")
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


class DateReach:
    """Which date instances a visualization's content reaches. Index built once per model.

    Walks a visualization, then the metrics it uses and the metrics *those* use, down to the
    facts and labels that resolve to datasets, then out along dataset references to any date
    instance. The dashboard derivation and the live gate both ask this one question, so they
    cannot disagree about what a date filter can reach.
    """

    def __init__(self, model: Any) -> None:
        self.index = build_entity_index(model.ldm)
        analytics = model.analytics
        self.metrics_by_id = {metric.id: metric for metric in analytics.metrics or []}
        self.visualizations = {viz.id: viz for viz in analytics.visualization_objects or []}

    def _metric_identifiers(self, metric_id: str, seen: set[str], identifiers: set[str]) -> None:
        if metric_id in seen:
            return
        seen.add(metric_id)
        metric = self.metrics_by_id.get(metric_id)
        if metric is None:
            return
        maql = (metric.content or {}).get("maql")
        for ref in iter_maql_refs(maql):
            if ref.kind == "metric":
                self._metric_identifiers(ref.id, seen, identifiers)
            else:
                identifiers.add(ref.id)

    def identifiers_of(self, viz_ids: set[str] | list[str] | tuple[str, ...]) -> set[str]:
        seen_metrics: set[str] = set()
        identifiers: set[str] = set()
        for viz_id in viz_ids:
            viz = self.visualizations.get(viz_id)
            if viz is None:
                continue
            identifiers |= _identifiers_in(viz)
            # A measure names a metric, or carries raw MAQL inline. Both are how a
            # visualization reaches a fact, and therefore a dataset, and therefore a date.
            for ref in iter_metric_refs(viz):
                self._metric_identifiers(ref.id, seen_metrics, identifiers)
            for _, maql in iter_inline_maql(viz):
                for inline in iter_maql_refs(maql):
                    if inline.kind == "metric":
                        self._metric_identifiers(inline.id, seen_metrics, identifiers)
                    else:
                        identifiers.add(inline.id)
        return identifiers

    def dates_of_identifiers(self, identifiers: set[str]) -> set[str]:
        index = self.index
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
        return reached

    def for_visualizations(self, viz_ids: set[str] | list[str] | tuple[str, ...]) -> tuple[str, ...]:
        """Sorted, so the caller decides what to do with none or several — never a guess."""
        return tuple(sorted(self.dates_of_identifiers(self.identifiers_of(viz_ids))))


def date_instances_for(model: Any, dashboard: Any) -> tuple[str, ...]:
    """Which date instances one dashboard's content actually depends on."""
    return DateReach(model).for_visualizations(sorted(_visualization_ids(dashboard)))


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
    report.undecided_facts = undecided_facts(model)
    return report
