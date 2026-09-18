"""Task 21 — the one-time generator.

Two properties carry the weight. **ANY, not ALL:** a dashboard goes to every domain any of
its tiles belongs to, which is precisely the rule the predecessor got backwards. **Nothing is
omitted:** whatever the prefix cannot classify is parked under ``unassigned`` with a ``TODO:``
reason, so the residue is visible and ``--strict`` refuses to pass until a human has read it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from globalmart.coverage import CoverageError, check_coverage, raise_for_report
from globalmart.domain_bootstrap import (
    SEED_DOMAINS,
    bootstrap_manifest,
    domain_for_visualization_id,
)
from globalmart.domains import dump_domains, load_domains
from globalmart.layout_io import read_tree

PARENT = Path(__file__).parent / "fixtures" / "mini_globalmart"

#: The mini parent only carries these three domains' objects. Bootstrapping with the full
#: 12-key seed would produce nine domains with nothing in them, which the loader rejects —
#: correctly, since an empty domain is a child workspace with no content.
FIXTURE_SEED = (("sales", "Sales"), ("finance", "Finance"), ("customer", "Customers"))


@pytest.fixture(scope="module")
def model():  # type: ignore[no-untyped-def]
    return read_tree(PARENT)


def test_longest_prefix_wins() -> None:
    """``store_ops`` must beat a shorter key that is also a prefix of the same id."""
    assert domain_for_visualization_id("viz_store_ops_0287") == "store_ops"
    assert domain_for_visualization_id("viz_sales_0000") == "sales"
    assert domain_for_visualization_id("viz_orphan_0001") is None


def test_the_seed_carries_exactly_twelve_domains() -> None:
    assert len(SEED_DOMAINS) == 12
    assert len({key for key, _ in SEED_DOMAINS}) == 12
    assert len({label for _, label in SEED_DOMAINS}) == 12


def test_a_mixed_tile_dashboard_lands_in_both_domains(model) -> None:  # type: ignore[no-untyped-def]
    """The predecessor's ALL rule would have left dashboard_mixed in no domain at all."""
    manifest, _report = bootstrap_manifest(model, seed=FIXTURE_SEED)

    assert "dashboard_mixed" in manifest.by_key("sales").dashboards
    assert "dashboard_mixed" in manifest.by_key("finance").dashboards


def test_nothing_is_omitted(model) -> None:  # type: ignore[no-untyped-def]
    manifest, report = bootstrap_manifest(model, seed=FIXTURE_SEED)

    assert report.unmatched_visualizations == ("viz_orphan_0001",)
    assert manifest.unassigned_ids() >= {"viz_orphan_0001", "mem_sales_definitions"}
    assert all(
        exclusion.reason.startswith("TODO:")
        for exclusion in manifest.unassigned.all_exclusions()
    )
    assert report.ai_objects_parked == 1
    assert report.matched_visualizations == 4


def test_orphan_visualizations_are_listed_on_their_domain(model) -> None:  # type: ignore[no-untyped-def]
    """viz_customer_0096/0097 match a prefix but sit on no dashboard."""
    manifest, _report = bootstrap_manifest(model, seed=FIXTURE_SEED)

    assert manifest.by_key("customer").visualizations == (
        "viz_customer_0096",
        "viz_customer_0097",
    )
    # viz_sales_0000 is on dashboard_000, so sales must not list it redundantly.
    assert manifest.by_key("sales").visualizations == ()


def test_generation_is_deterministic(tmp_path: Path, model) -> None:  # type: ignore[no-untyped-def]
    first, _ = bootstrap_manifest(model, seed=FIXTURE_SEED)
    second, _ = bootstrap_manifest(model, seed=FIXTURE_SEED)

    a = dump_domains(first, tmp_path / "a.yaml")
    b = dump_domains(second, tmp_path / "b.yaml")

    assert a.read_bytes() == b.read_bytes()
    assert load_domains(a).domains == load_domains(b).domains


def test_a_generated_manifest_covers_everything_but_fails_strict(
    tmp_path: Path, model
) -> None:  # type: ignore[no-untyped-def]
    """The guard: an unreviewed bootstrap must not go green in CI."""
    manifest, _ = bootstrap_manifest(model, seed=FIXTURE_SEED)
    reloaded = load_domains(dump_domains(manifest, tmp_path / "generated.yaml"))

    report = check_coverage(model, reloaded)
    raise_for_report(report, strict=False)

    with pytest.raises(CoverageError, match="justified in words"):
        raise_for_report(report, strict=True)
