"""Task 30 — the guard against the real parent tree.

This is the acceptance criterion the whole feature exists for, and it runs in CI: every one
of the 32 dashboards and all 384 visualizations in the committed parent is accounted for,
strictly. A PR that adds a dashboard without assigning it to a domain fails here.

Skipped cleanly when either artifact is missing, so the suite stays runnable on a fresh
checkout before a bootstrap has happened.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from globalmart.coverage import check_coverage, raise_for_report
from globalmart.domains import load_domains
from globalmart.layout_io import read_tree

REPO = Path(__file__).resolve().parents[1]
LAYOUT = REPO / "layouts" / "workspaces" / "globalmart"
MANIFEST = REPO / "config" / "domains.yaml"

pytestmark = pytest.mark.skipif(
    not (LAYOUT.exists() and MANIFEST.exists()),
    reason="the real parent tree or config/domains.yaml is not present",
)

EXPECTED_KEYS = {
    "customer",
    "ecommerce",
    "finance",
    "hr",
    "inventory",
    "loyalty",
    "marketing",
    "product",
    "real_estate",
    "risk",
    "sales",
    "store_ops",
}


@pytest.fixture(scope="module")
def manifest():  # type: ignore[no-untyped-def]
    return load_domains(MANIFEST)


@pytest.fixture(scope="module")
def report(manifest):  # type: ignore[no-untyped-def]
    return check_coverage(read_tree(LAYOUT), manifest)


def test_twelve_domains(manifest) -> None:  # type: ignore[no-untyped-def]
    assert set(manifest.keys()) == EXPECTED_KEYS


def test_child_workspace_ids_are_kebab_case_and_unique(manifest) -> None:  # type: ignore[no-untyped-def]
    ids = {manifest.resolve_workspace_id(d) for d in manifest.domains}

    assert len(ids) == 12
    assert "globalmart-store-ops" in ids
    assert "globalmart-real-estate" in ids
    assert manifest.parent_workspace_id not in ids


def test_workspace_names_are_unique(manifest) -> None:  # type: ignore[no-untyped-def]
    names = {manifest.resolve_workspace_name(d) for d in manifest.domains}

    assert len(names) == 12
    assert "GlobalMart — Sales" in names


def test_the_parent_is_fully_covered(report) -> None:  # type: ignore[no-untyped-def]
    assert report.dashboards_total == 32
    assert report.visualizations_total == 384
    raise_for_report(report, strict=True)


def test_every_visualization_reaches_exactly_one_domain(report) -> None:  # type: ignore[no-untyped-def]
    """Measured fact today, not a rule: all 32 dashboards are single-domain.

    If a future dashboard genuinely spans two domains this test is the one to update — and
    the point of the manifest is that doing so is a deliberate edit rather than a silent
    drop. `multi_homed` being empty is what makes that change visible.
    """
    assert report.multi_homed == {}
    assert all(len(keys) == 1 for keys in report.assigned_visualizations.values())
