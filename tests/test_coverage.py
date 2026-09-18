"""Tasks 16, 17, 18 — coverage enforcement, which is the feature.

The first test in this module is the one that matters: a dashboard whose tiles span two
domains. The predecessor required *every* tile to match one domain, so this dashboard matched
nothing and was dropped with no error, no report and no count. Here it is listed under both
domains, coverage passes, and it is reported as multi-homed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from globalmart.coverage import CoverageError, check_coverage, raise_for_report
from globalmart.domains import load_domains
from globalmart.layout_io import read_tree

FIXTURES = Path(__file__).parent / "fixtures" / "domains"
PARENT = Path(__file__).parent / "fixtures" / "mini_globalmart"


@pytest.fixture(scope="module")
def model():  # type: ignore[no-untyped-def]
    return read_tree(PARENT)


def _report(model, name: str):  # type: ignore[no-untyped-def]
    return check_coverage(model, load_domains(FIXTURES / name))


# --- the predecessor-bug test ------------------------------------------------


def test_a_dashboard_spanning_two_domains_is_covered_by_both(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "valid.yaml")

    assert report.assigned_dashboards["dashboard_mixed"] == ("finance", "sales")
    assert report.multi_homed["dashboard_mixed"] == ("finance", "sales")
    assert "dashboard_mixed" not in report.uncovered_dashboards
    assert not report.uncovered_visualizations
    raise_for_report(report, strict=True)


def test_the_same_dashboard_in_no_domain_is_fatal(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "missing_coverage.yaml")

    assert "dashboard_mixed" in report.uncovered_dashboards
    with pytest.raises(CoverageError, match="dashboard_mixed"):
        raise_for_report(report)


def test_the_clean_manifest_covers_everything(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "valid.yaml")

    assert report.dashboards_total == 2
    assert report.visualizations_total == 5
    assert report.ai_objects_total == 1
    assert report.is_clean(strict=True)


# --- coverage through dashboards ---------------------------------------------


def test_a_visualization_on_a_listed_dashboard_is_covered_without_being_listed(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "valid.yaml")

    # viz_finance_0216 is named by no domain; finance reaches it through dashboard_mixed,
    # and only through a *drill target* at that.
    assert "finance" in report.assigned_visualizations["viz_finance_0216"]
    assert report.per_domain["finance"].visualizations_direct == 0
    assert report.per_domain["finance"].visualizations_via_dashboards == 2


def test_a_visualization_on_no_dashboard_and_in_no_list_is_fatal(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "missing_coverage.yaml")

    assert "viz_orphan_0001" in report.uncovered_visualizations
    with pytest.raises(CoverageError, match="viz_orphan_0001"):
        raise_for_report(report)


# --- integrity ---------------------------------------------------------------


def test_an_id_absent_from_the_parent_is_fatal_and_carries_its_path(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "unknown_id.yaml")

    assert report.unknown_ids["dashboard_999"].endswith(".dashboards[1]")
    with pytest.raises(CoverageError, match="dashboard_999"):
        raise_for_report(report)


def test_an_unknown_ldm_include_dataset_is_fatal(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "unknown_id.yaml")

    assert "ldm_include[0]" in report.unknown_ids["dim_does_not_exist"]


def test_a_valid_ldm_include_is_counted_and_changes_no_coverage(model) -> None:  # type: ignore[no-untyped-def]
    """Headroom, not membership: it must move the ldm_include count and nothing else."""
    with_include = _report(model, "valid.yaml")
    without_include = check_coverage(model, _drop_ldm_include(FIXTURES / "valid.yaml"))

    assert with_include.per_domain["sales"].ldm_include == 1
    assert without_include.per_domain["sales"].ldm_include == 0
    assert with_include.assigned_dashboards == without_include.assigned_dashboards
    assert with_include.assigned_visualizations == without_include.assigned_visualizations
    assert with_include.uncovered_visualizations == without_include.uncovered_visualizations


def _drop_ldm_include(path: Path):  # type: ignore[no-untyped-def]
    import dataclasses

    manifest = load_domains(path)
    domains = tuple(dataclasses.replace(d, ldm_include=()) for d in manifest.domains)
    return dataclasses.replace(manifest, domains=domains)


# --- strict mode -------------------------------------------------------------


def test_a_placeholder_reason_passes_plain_and_fails_strict(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "empty_reason.yaml")

    raise_for_report(report)  # plain: an exclusion is an exclusion
    assert report.placeholder_reasons["viz_orphan_0001"] == "TODO: classify"
    with pytest.raises(CoverageError, match="justified in words"):
        raise_for_report(report, strict=True)


def test_a_real_sentence_passes_both(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "valid.yaml")

    assert not report.placeholder_reasons
    raise_for_report(report, strict=True)


# --- AI context: deny by default ---------------------------------------------


def test_a_memory_item_matched_only_by_tag_is_covered(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "valid.yaml")

    assert report.assigned_ai["mem_sales_definitions"] == ("sales",)
    assert report.per_domain["sales"].memory_items == 1


def test_no_other_domain_receives_that_memory_item(model) -> None:  # type: ignore[no-untyped-def]
    """The no-leak assertion. Cross-domain AI memory in a child is a defect, not a default."""
    report = _report(model, "valid.yaml")

    assert report.per_domain["finance"].memory_items == 0
    assert report.per_domain["customer"].memory_items == 0


def test_an_unclassified_ai_object_is_fatal(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "uncovered_ai.yaml")

    assert report.uncovered_ai == ("mem_sales_definitions",)
    with pytest.raises(CoverageError, match="mem_sales_definitions"):
        raise_for_report(report)


# --- secondary reports -------------------------------------------------------


def test_shared_objects_cover_and_reach_every_child(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "shared_and_redundant.yaml")

    assert "viz_customer_0096" in report.shared_ids
    assert "viz_customer_0096" not in report.uncovered_visualizations
    raise_for_report(report, strict=True)


def test_a_redundant_listing_is_reported_but_not_fatal(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "shared_and_redundant.yaml")

    assert report.redundant_visualizations["sales"] == ("viz_sales_0000",)
    raise_for_report(report, strict=True)


def test_cross_domain_tiles_show_what_gets_copied_into_two_children(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "valid.yaml")

    # Both domains list dashboard_mixed, so both of its tiles land in two children. That is
    # the correct outcome — and the thing worth seeing before the split runs. Never fatal.
    assert report.cross_domain_tiles["finance/dashboard_mixed"] == (
        "viz_finance_0216",
        "viz_sales_0000",
    )
    assert report.cross_domain_tiles["sales/dashboard_mixed"] == (
        "viz_finance_0216",
        "viz_sales_0000",
    )
    # And it is transitive: dashboard_000 is sales-only, but the tile it shares with
    # dashboard_mixed means finance gets a copy of that visualization too.
    assert report.cross_domain_tiles["sales/dashboard_000"] == ("viz_sales_0000",)


def test_cross_domain_tiles_is_empty_when_nothing_is_shared_between_domains(model) -> None:  # type: ignore[no-untyped-def]
    report = _report(model, "missing_coverage.yaml")

    assert report.cross_domain_tiles == {}
