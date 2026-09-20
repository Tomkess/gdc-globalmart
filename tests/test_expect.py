"""Repo-derived expectations: counts, coverage and the pruning invariant.

These run against the **committed artifacts**, which is the point: FEAT-004's tests prove its
closure algorithm; these prove the bytes it wrote. A stale generated file, a hand-edited one,
or a child published from an artifact that no longer matches the parent are all invisible to
FEAT-004's unit tests and caught here.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from globalmart.counts import ObjectCounts, count_objects
from globalmart.domains import load_domains
from globalmart.expect import (
    PARENT_EXPECTED,
    check_coverage,
    check_parent_literals,
    check_pruning,
    compare_counts,
    reachable_datasets,
)
from globalmart.layout_io import read_model_json, read_tree

REPO = Path(__file__).resolve().parents[1]
LAYOUT = REPO / "layouts" / "workspaces" / "globalmart"
GENERATED = REPO / "generated" / "workspaces"
MANIFEST = REPO / "config" / "domains.yaml"

pytestmark = pytest.mark.skipif(
    not (LAYOUT.exists() and GENERATED.exists()), reason="artifacts not present"
)


@pytest.fixture(scope="module")
def parent():  # type: ignore[no-untyped-def]
    return read_tree(LAYOUT)


@pytest.fixture(scope="module")
def manifest():  # type: ignore[no-untyped-def]
    return load_domains(MANIFEST)


@pytest.fixture(scope="module")
def children(manifest):  # type: ignore[no-untyped-def]
    return {
        manifest.by_key(key).workspace_id: read_model_json(
            GENERATED / f"{manifest.by_key(key).workspace_id}.json"
        )
        for key in manifest.keys()  # noqa: SIM118 - DomainManifest.keys() is a method
    }


@pytest.fixture(scope="module")
def declared(manifest):  # type: ignore[no-untyped-def]
    return {
        manifest.by_key(key).workspace_id: set(manifest.by_key(key).ldm_include)
        for key in manifest.keys()  # noqa: SIM118 - DomainManifest.keys() is a method
    }


# --- counts -------------------------------------------------------------------


def test_the_parent_matches_its_pinned_literals(parent) -> None:  # type: ignore[no-untyped-def]
    """The one non-tautological count assertion: absolute numbers, not repo-vs-repo."""
    assert check_parent_literals(count_objects(parent)) == []
    assert PARENT_EXPECTED["visualization_objects"] == 384


def test_identical_counts_produce_no_mismatch() -> None:
    counts = ObjectCounts(datasets=10, metrics=5)
    assert compare_counts("ws", counts, counts) == []


def test_a_differing_count_is_named() -> None:
    expected = ObjectCounts(datasets=10, metrics=5)
    actual = ObjectCounts(datasets=10, metrics=4)

    (mismatch,) = compare_counts("ws", expected, actual)
    assert mismatch.object_type == "metrics"
    assert mismatch.expected == 5
    assert mismatch.actual == 4
    assert "metrics" in str(mismatch)


# --- coverage -----------------------------------------------------------------


def test_every_parent_object_reaches_a_child(parent, children) -> None:  # type: ignore[no-untyped-def]
    report = check_coverage(parent, children)

    assert report.passed
    assert report.covered_dashboards == report.parent_dashboards == 32
    assert report.covered_visualizations == report.parent_visualizations == 384


def test_a_child_dropped_from_the_set_fails_coverage(parent, children) -> None:  # type: ignore[no-untyped-def]
    """Without a negative case, the passing check above proves only that nothing is broken."""
    reduced = dict(children)
    reduced.pop("globalmart-hr")

    report = check_coverage(parent, reduced)

    assert not report.passed
    assert report.missing_dashboard_ids
    assert report.missing_visualization_ids


# --- pruning ------------------------------------------------------------------


def test_no_child_carries_a_dataset_it_cannot_explain(parent, children, declared) -> None:  # type: ignore[no-untyped-def]
    assert check_pruning(parent, children, declared=declared) == []


def test_an_injected_dataset_is_flagged_unreachable(parent, children, declared) -> None:  # type: ignore[no-untyped-def]
    """The predecessor's defect, asserted on the artifact rather than on the algorithm."""
    victim = copy.deepcopy(children["globalmart-risk"])
    stray = next(d for d in parent.ldm.datasets if d.id not in {x.id for x in victim.ldm.datasets})
    victim.ldm.datasets = [*victim.ldm.datasets, copy.deepcopy(stray)]

    violations = check_pruning(parent, {"globalmart-risk": victim}, declared=declared)

    assert [v.dataset_id for v in violations] == [str(stray.id)]
    assert violations[0].reason == "unreachable"


def test_a_child_carrying_the_whole_parent_ldm_fails_both_ways(parent, children) -> None:  # type: ignore[no-untyped-def]
    """Exactly what the predecessor shipped twelve times."""
    victim = copy.deepcopy(children["globalmart-risk"])
    victim.ldm = copy.deepcopy(parent.ldm)

    violations = check_pruning(parent, {"globalmart-risk": victim})
    reasons = {v.reason for v in violations}

    assert "unreachable" in reasons
    assert "dataset_count_not_reduced" in reasons


def test_declared_datasets_are_not_flagged(parent, children, manifest) -> None:  # type: ignore[no-untyped-def]
    """`ldm_include` is deliberate headroom; flagging it would make the check cry wolf."""
    victim = copy.deepcopy(children["globalmart-risk"])
    stray = next(d for d in parent.ldm.datasets if d.id not in {x.id for x in victim.ldm.datasets})
    victim.ldm.datasets = [*victim.ldm.datasets, copy.deepcopy(stray)]

    violations = check_pruning(
        parent,
        {"globalmart-risk": victim},
        declared={"globalmart-risk": {str(stray.id)}},
    )

    assert violations == []


def test_reachability_is_computed_from_the_child_alone(children) -> None:  # type: ignore[no-untyped-def]
    """No call into FEAT-004 — the artifact is checked independently of what wrote it."""
    child = children["globalmart-risk"]
    reachable = reachable_datasets(child)
    present = {str(d.id) for d in child.ldm.datasets}

    assert reachable
    assert present <= reachable


def test_every_child_is_strictly_narrower_than_the_parent(parent, children) -> None:  # type: ignore[no-untyped-def]
    parent_datasets = len(parent.ldm.datasets)

    for workspace_id, child in children.items():
        assert len(child.ldm.datasets) < parent_datasets, workspace_id
