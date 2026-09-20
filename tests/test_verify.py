"""Both verification gates.

The over-pruning test is the predecessor's defect stated as an assertion: it shipped
`"ldm": model["ldm"]` into twelve children, so an "HR workspace" carried all 225 retail
tables. The degenerate case is run explicitly — a child holding the *whole* parent LDM must
fail — because that is precisely what was shipped.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from globalmart.closure import build_closure, build_index
from globalmart.domains import load_domains
from globalmart.layout_io import read_tree
from globalmart.prune import prune_ldm
from globalmart.split import split_domain
from globalmart.verify import ChildVerificationError, verify_child

BASE = Path(__file__).parent / "fixtures" / "mini_domains"


@pytest.fixture(scope="module")
def model():  # type: ignore[no-untyped-def]
    return read_tree(BASE / "mini_parent")


@pytest.fixture(scope="module")
def manifest():  # type: ignore[no-untyped-def]
    return load_domains(BASE / "domains.yaml")


def built(model, manifest, key):  # type: ignore[no-untyped-def]
    domain = manifest.by_key(key)
    index = build_index(model)
    closure = build_closure(model, domain, manifest, index=index)
    child, _result = split_domain(model, domain, manifest, index=index)
    return child, closure


def test_a_correct_child_passes(model, manifest) -> None:  # type: ignore[no-untyped-def]
    child, closure = built(model, manifest, "hr")
    verify_child(child, "hr", closure=closure)


# --- under-pruning ------------------------------------------------------------


def test_a_metric_reaching_a_pruned_dataset_fails(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """The failure that would otherwise surface in a dashboard tile at execution time."""
    child, closure = built(model, manifest, "hr")
    child.ldm = prune_ldm(
        child.ldm, closure.dataset_ids - {"fact_headcount"}, closure.date_instance_ids
    )

    with pytest.raises(ChildVerificationError) as excinfo:
        verify_child(child, "hr", closure=closure)
    assert "fact_headcount.headcount" in str(excinfo.value)
    assert "m_headcount" in str(excinfo.value)


def test_a_missing_referenced_metric_fails(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """m_net_revenue without m_revenue is "metrics ... cannot be found", caught early."""
    child, closure = built(model, manifest, "sales")
    child.analytics.metrics = [m for m in child.analytics.metrics if m.id != "m_revenue"]

    with pytest.raises(ChildVerificationError, match="m_revenue"):
        verify_child(child, "sales", closure=closure)


def test_a_dangling_join_fails(model, manifest) -> None:  # type: ignore[no-untyped-def]
    child, closure = built(model, manifest, "sales")
    child.ldm.datasets = [d for d in child.ldm.datasets if d.id != "dim_geo"]

    with pytest.raises(ChildVerificationError, match="dim_geo"):
        verify_child(child, "sales", closure=closure)


def test_a_missing_measured_metric_fails(model, manifest) -> None:  # type: ignore[no-untyped-def]
    child, closure = built(model, manifest, "sales")
    child.analytics.metrics = [m for m in child.analytics.metrics if m.id != "m_basket_size"]

    with pytest.raises(ChildVerificationError, match="m_basket_size"):
        verify_child(child, "sales", closure=closure)


# --- over-pruning: the defect regression --------------------------------------


def test_an_unexplained_dataset_fails(model, manifest) -> None:  # type: ignore[no-untyped-def]
    child, closure = built(model, manifest, "sales")
    stray = next(d for d in model.ldm.datasets if d.id == "dim_region")
    child.ldm.datasets = [*child.ldm.datasets, copy.deepcopy(stray)]

    with pytest.raises(ChildVerificationError) as excinfo:
        verify_child(child, "sales", closure=closure)
    assert "dim_region" in str(excinfo.value)


def test_the_full_parent_ldm_in_a_child_fails(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """Exactly what the predecessor shipped, twelve times, silently."""
    child, closure = built(model, manifest, "sales")
    child.ldm = copy.deepcopy(model.ldm)

    with pytest.raises(ChildVerificationError) as excinfo:
        verify_child(child, "sales", closure=closure)
    assert "predecessor's full-LDM copy" in str(excinfo.value)


def test_a_dataset_present_only_via_a_hierarchy_passes(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """The gate must not be readable as "unreferenced by analytics ⇒ unused"."""
    child, closure = built(model, manifest, "hr")

    assert "dim_region" in {d.id for d in child.ldm.datasets}
    verify_child(child, "hr", closure=closure)


def test_a_dataset_present_only_via_ldm_include_passes(model, manifest) -> None:  # type: ignore[no-untyped-def]
    child, closure = built(model, manifest, "hr")

    assert "dim_store" in {d.id for d in child.ldm.datasets}
    verify_child(child, "hr", closure=closure)


def test_every_failure_is_reported_not_just_the_first(model, manifest) -> None:  # type: ignore[no-untyped-def]
    child, closure = built(model, manifest, "sales")
    child.ldm = prune_ldm(child.ldm, frozenset({"dim_geo"}), frozenset())

    with pytest.raises(ChildVerificationError) as excinfo:
        verify_child(child, "sales", closure=closure)
    assert len(excinfo.value.failures) > 1
