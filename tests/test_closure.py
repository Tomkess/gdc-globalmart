"""The six closure stages, against a fixture whose expected sets are hand-computable.

Two tests here are the feature: `test_a_mixed_domain_dashboard_travels_to_both` (the
predecessor dropped it) and `test_a_hierarchy_pulls_its_datasets_in` (the pull-in rule —
dependencies are included, never used as grounds for exclusion).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from globalmart.closure import MetricPolicy, build_closure, build_index
from globalmart.domains import load_domains
from globalmart.layout_io import read_tree
from globalmart.prune import DanglingReferenceError

BASE = Path(__file__).parent / "fixtures" / "mini_domains"


@pytest.fixture(scope="module")
def model():  # type: ignore[no-untyped-def]
    return read_tree(BASE / "mini_parent")


@pytest.fixture(scope="module")
def manifest():  # type: ignore[no-untyped-def]
    return load_domains(BASE / "domains.yaml")


def closure_for(model, manifest, key, **kwargs):  # type: ignore[no-untyped-def]
    return build_closure(model, manifest.by_key(key), manifest, index=build_index(model), **kwargs)


# --- stage 2: the predecessor's bug ------------------------------------------


def test_a_mixed_domain_dashboard_travels_to_both(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """dash_exec's tiles span sales and hr. The all-tiles-must-match rule dropped it."""
    sales = closure_for(model, manifest, "sales")
    hr = closure_for(model, manifest, "hr")

    assert "dash_exec" in sales.dashboard_ids
    assert "dash_exec" in hr.dashboard_ids
    # And its tiles come with it, into both.
    assert "viz_sales_revenue" in sales.visualization_ids
    assert "viz_sales_revenue" in hr.visualization_ids


def test_a_drill_target_travels(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """dash_exec drills to viz_sales_basket. A missing drill target breaks at runtime."""
    hr = closure_for(model, manifest, "hr")
    assert "viz_sales_basket" in hr.visualization_ids


# --- stage 4: the part kept from the predecessor ------------------------------


def test_the_metric_chain_is_transitive(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """m_adjusted_revenue -> m_net_revenue -> m_revenue, three deep.

    Without the worklist the child loads and fails with "metrics ... cannot be found".
    """
    sales = closure_for(model, manifest, "sales", metric_policy=MetricPolicy.REACHABLE)

    assert {"m_adjusted_revenue", "m_net_revenue", "m_revenue"} <= sales.metric_ids
    assert sales.why["m_revenue"][0].startswith("metric m_net_revenue")


def test_a_metric_pulls_in_the_dataset_its_maql_reaches(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """m_revenue_per_product names a label on dim_product; no visualization touches it."""
    sales = closure_for(model, manifest, "sales", metric_policy=MetricPolicy.REACHABLE)
    assert "dim_product" in sales.dataset_ids


# --- stage 4b: the pull-in rule ----------------------------------------------


def test_a_hierarchy_pulls_its_datasets_in(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """hier_geo_region names an attribute on dim_region, which nothing else reaches.

    A design that decided hierarchy retention *after* pruning would drop the hierarchy from
    hr for naming an attribute the LDM no longer had. The pull-in rule includes dim_region
    instead. This assertion is the difference between the two designs.
    """
    hr = closure_for(model, manifest, "hr")

    assert "hier_geo_region" in hr.attribute_hierarchy_ids
    assert "dim_region" in hr.dataset_ids
    assert "dim_region.region_id" in hr.entity_ids


def test_a_domain_referencing_no_hierarchy_simply_has_none(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """Correct absence, not a loss — and nothing reports it as one."""
    sales = closure_for(model, manifest, "sales")

    assert sales.attribute_hierarchy_ids == frozenset()
    assert "dim_region" not in sales.dataset_ids


def test_filter_contexts_travel_with_their_dashboard(model, manifest) -> None:  # type: ignore[no-untyped-def]
    sales = closure_for(model, manifest, "sales")
    assert "fc_sales" in sales.filter_context_ids
    assert "fc_hr" not in sales.filter_context_ids


# --- stage 1: shared and ldm_include ------------------------------------------


def test_shared_objects_are_seeded_into_every_domain(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """Building from `domain.dashboards` alone would silently drop these from both children."""
    for key in manifest.keys():  # noqa: SIM118 - DomainManifest.keys() is a method, not a mapping
        closure = closure_for(model, manifest, key)
        assert "dash_shared_overview" in closure.dashboard_ids
        assert "viz_shared_geo" in closure.visualization_ids
        assert closure.why["dash_shared_overview"][0] == "domains.yaml: shared.dashboards"


def test_ldm_include_widens_only_the_ldm(model, manifest) -> None:  # type: ignore[no-untyped-def]
    hr = closure_for(model, manifest, "hr")

    assert hr.declared_dataset_ids == frozenset({"dim_store"})
    assert "dim_store" in hr.dataset_ids
    assert "dim_store" not in hr.seed_dataset_ids
    assert hr.why["dim_store"][0].endswith("hr.ldm_include")

    sales = closure_for(model, manifest, "sales")
    assert "dim_store" not in sales.dataset_ids


def test_an_unknown_ldm_include_dataset_fails(model, manifest) -> None:  # type: ignore[no-untyped-def]
    broken = dataclasses.replace(manifest.by_key("hr"), ldm_include=("dim_nope",))
    with pytest.raises(DanglingReferenceError, match="dim_nope"):
        build_closure(model, broken, manifest, index=build_index(model))


def test_an_unknown_dashboard_fails_naming_the_domain(model, manifest) -> None:  # type: ignore[no-untyped-def]
    broken = dataclasses.replace(manifest.by_key("sales"), dashboards=("dash_nope",))
    with pytest.raises(DanglingReferenceError, match="dash_nope"):
        build_closure(model, broken, manifest, index=build_index(model))


# --- stage 5 + 6 --------------------------------------------------------------


def test_only_the_date_instances_a_domain_needs_travel(model, manifest) -> None:  # type: ignore[no-untyped-def]
    sales = closure_for(model, manifest, "sales")
    hr = closure_for(model, manifest, "hr")

    assert sales.date_instance_ids == frozenset({"order_date"})
    assert hr.date_instance_ids == frozenset({"hire_date"})


def test_dataset_fit_adds_metrics_but_never_datasets(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """The whole justification for the policy: free in the dimension being controlled."""
    reachable = closure_for(model, manifest, "sales", metric_policy=MetricPolicy.REACHABLE)
    fitted = closure_for(model, manifest, "sales", metric_policy=MetricPolicy.DATASET_FIT)

    assert fitted.dataset_ids == reachable.dataset_ids
    assert fitted.date_instance_ids == reachable.date_instance_ids
    assert reachable.metric_ids < fitted.metric_ids
    assert "m_orphan_sales_ratio" in fitted.metric_ids
    assert "m_orphan_sales_ratio" not in reachable.metric_ids


def test_dataset_fit_excludes_a_metric_whose_tables_are_absent(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """m_orphan_region needs dim_region, which only hr has via the hierarchy."""
    sales = closure_for(model, manifest, "sales", metric_policy=MetricPolicy.DATASET_FIT)
    hr = closure_for(model, manifest, "hr", metric_policy=MetricPolicy.DATASET_FIT)

    assert "m_orphan_region" not in sales.metric_ids
    assert "m_orphan_region" in hr.metric_ids


def test_dataset_fit_respects_date_instances(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """m_revenue_by_month needs order_date, which hr does not have."""
    hr = closure_for(model, manifest, "hr", metric_policy=MetricPolicy.DATASET_FIT)
    assert "m_revenue_by_month" not in hr.metric_ids


def test_dataset_fit_keeps_a_metric_chain_whole(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """Admitting a metric without the metrics it names is the same old failure."""
    sales = closure_for(model, manifest, "sales", metric_policy=MetricPolicy.DATASET_FIT)
    assert {"m_orphan_sales_ratio", "m_revenue", "m_orders"} <= sales.metric_ids
