# The defect: 32 dashboards shipped a date filter bound to nothing, so none of them filtered.
from __future__ import annotations

import json
from pathlib import Path

import pytest

from globalmart.datefilters import bind_date_filters, date_instances_for
from globalmart.layout_io import read_tree

REPO = Path(__file__).resolve().parents[1]
LAYOUT = REPO / "layouts" / "workspaces" / "globalmart"

pytestmark = pytest.mark.skipif(not LAYOUT.exists(), reason="layout tree not present")


@pytest.fixture(scope="module")
def model():  # type: ignore[no-untyped-def]
    return read_tree(LAYOUT)


def test_every_date_filter_is_bound(model) -> None:  # type: ignore[no-untyped-def]
    """The committed tree must stay bound. This is what the CI gate asserts."""
    report = bind_date_filters(model)

    assert report.ok(), report.summary_lines()
    assert report.bound == {}, (
        "some dashboards are unbound in the committed tree — run `globalmart datefilters bind`"
    )
    assert len(report.already_bound) == report.dashboards


def test_every_dashboard_resolves_to_exactly_one_date_instance(model) -> None:  # type: ignore[no-untyped-def]
    """Ambiguity must be impossible to ignore: zero or several is a build failure, not a guess."""
    for dashboard in model.analytics.analytical_dashboards:
        reached = date_instances_for(model, dashboard)
        assert len(reached) == 1, f"{dashboard.id} reached {reached or 'nothing'}"


def test_a_dashboard_reaches_dates_through_its_metrics(model) -> None:  # type: ignore[no-untyped-def]
    """The subtle half of the walk.

    A visualization that names only a metric carries no LDM ids of its own — the date is
    reached through the metric's MAQL, and through the metrics that metric uses. An earlier
    version of this walk missed that and silently resolved two dashboards to nothing.
    """
    analytics = model.analytics
    metrics = {m.id for m in analytics.metrics}
    visualizations = {v.id: v for v in analytics.visualization_objects}

    from globalmart.datefilters import _identifiers_in, _visualization_ids
    from globalmart.refs import iter_metric_refs

    metric_only = []
    for dashboard in analytics.analytical_dashboards:
        for viz_id in _visualization_ids(dashboard):
            viz = visualizations.get(viz_id)
            if viz is None:
                continue
            if not _identifiers_in(viz) and any(r.id in metrics for r in iter_metric_refs(viz)):
                metric_only.append((dashboard.id, viz_id))

    assert metric_only, "no metric-only visualization found, so this test proves nothing"
    dashboard_id = metric_only[0][0]
    dashboard = next(d for d in analytics.analytical_dashboards if d.id == dashboard_id)
    assert date_instances_for(model, dashboard), (
        f"{dashboard_id} has a metric-only visualization and reached no date instance"
    )


def test_binding_is_idempotent(model) -> None:  # type: ignore[no-untyped-def]
    """Running it twice must not rewrite anything the second time."""
    first = bind_date_filters(model)
    second = bind_date_filters(model)

    assert second.bound == {}
    assert len(second.already_bound) == first.dashboards


def test_an_override_wins_over_the_derivation(model) -> None:  # type: ignore[no-untyped-def]
    """An ambiguous dashboard is resolved by saying so, never by the tool choosing."""
    contexts = {c.id: c for c in model.analytics.filter_contexts}
    dashboard = model.analytics.analytical_dashboards[0]
    ref = (dashboard.content or {}).get("filterContextRef") or {}
    context = contexts[(ref.get("identifier") or {}).get("id")]
    for item in (context.content or {}).get("filters", []):
        item.get("dateFilter", {}).pop("dataSet", None)

    report = bind_date_filters(model, overrides={dashboard.id: "fiscal_date"})

    assert report.bound[dashboard.id] == "fiscal_date"
    assert "fiscal_date" in json.dumps(context.content)
