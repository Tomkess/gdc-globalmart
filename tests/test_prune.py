"""The entity index and the join-ancestor closure.

The join direction is the single highest-consequence decision in this feature. Backwards,
children either carry the whole parent again or lose every dimension — and both look
plausible in a summary line. So it is asserted literally, against a hand-computed chain.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from globalmart.layout_io import read_tree
from globalmart.maql import RefKind
from globalmart.prune import (
    DanglingReferenceError,
    build_entity_index,
    dataset_column_usage,
    expand_join_ancestors,
    prune_ldm,
)

FIXTURE = Path(__file__).parent / "fixtures" / "mini_domains" / "mini_parent"


@pytest.fixture(scope="module")
def model():  # type: ignore[no-untyped-def]
    return read_tree(FIXTURE)


@pytest.fixture(scope="module")
def index(model):  # type: ignore[no-untyped-def]
    return build_entity_index(model.ldm)


def test_index_maps_attributes_and_facts_to_their_dataset(index) -> None:  # type: ignore[no-untyped-def]
    assert index.owner_of("dim_customer.customer_name") == (RefKind.DATASET, "dim_customer")
    assert index.owner_of("fact_orders.amount") == (RefKind.DATASET, "fact_orders")
    assert index.owner_of("fact_orders") == (RefKind.DATASET, "fact_orders")


def test_a_date_qualified_id_resolves_to_the_date_instance(index) -> None:  # type: ignore[no-untyped-def]
    """`order_date.month` is a date instance plus a granularity, not a dataset column."""
    assert index.owner_of("order_date.month") == (RefKind.DATE_INSTANCE, "order_date")
    assert index.owner_of("order_date") == (RefKind.DATE_INSTANCE, "order_date")


def test_a_dotted_column_id_is_not_mistaken_for_a_date(index) -> None:  # type: ignore[no-untyped-def]
    """The check order that keeps `fact_orders.amount` whole."""
    assert index.owner_of("fact_orders.amount") == (RefKind.DATASET, "fact_orders")


def test_an_unknown_id_resolves_to_nothing(index) -> None:  # type: ignore[no-untyped-def]
    assert index.owner_of("nope.nothing") is None
    with pytest.raises(DanglingReferenceError, match="nope.nothing"):
        index.resolve_entity("nope.nothing", context="a test")


def test_join_direction_is_forward_only(index) -> None:  # type: ignore[no-untyped-def]
    """fact_orders -> dim_customer -> dim_geo, hand-computed both ways.

    A retained fact table drags its dimensions in; a retained dimension never drags in the
    facts pointing at it. That asymmetry *is* the narrowing.
    """
    from_fact, _ = expand_join_ancestors(index, {"fact_orders"})
    assert from_fact == frozenset({"fact_orders", "dim_customer", "dim_geo", "dim_product"})

    from_leaf, _ = expand_join_ancestors(index, {"dim_geo"})
    assert from_leaf == frozenset({"dim_geo"})

    from_middle, _ = expand_join_ancestors(index, {"dim_customer"})
    assert from_middle == frozenset({"dim_customer", "dim_geo"})


def test_expansion_rejects_an_unknown_dataset(index) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(DanglingReferenceError, match="dim_missing"):
        expand_join_ancestors(index, {"dim_missing"})


def test_prune_keeps_only_what_it_is_given(model, index) -> None:  # type: ignore[no-untyped-def]
    pruned = prune_ldm(model.ldm, frozenset({"fact_headcount", "dim_employee"}), frozenset({"hire_date"}))

    assert sorted(d.id for d in pruned.datasets) == ["dim_employee", "fact_headcount"]
    assert [i.id for i in pruned.date_instances] == ["hire_date"]


def test_prune_keeps_every_column_of_a_retained_dataset(model) -> None:  # type: ignore[no-untyped-def]
    """Dataset-level pruning only. A label that looks unused may be a join grain."""
    pruned = prune_ldm(model.ldm, frozenset({"dim_customer", "dim_geo"}), frozenset())
    customer = next(d for d in pruned.datasets if d.id == "dim_customer")
    original = next(d for d in model.ldm.datasets if d.id == "dim_customer")

    assert [a.id for a in customer.attributes] == [a.id for a in original.attributes]


def test_prune_does_not_mutate_the_parent(model) -> None:  # type: ignore[no-untyped-def]
    """`split_all` runs every domain from one loaded tree; a mutation would poison the rest."""
    before = len(model.ldm.datasets)
    prune_ldm(model.ldm, frozenset({"dim_geo"}), frozenset())
    prune_ldm(model.ldm, frozenset({"fact_orders"}), frozenset())

    assert len(model.ldm.datasets) == before


def test_column_usage_counts_are_evidence_not_a_filter(model) -> None:  # type: ignore[no-untyped-def]
    usage = dataset_column_usage(model.ldm, frozenset({"fact_orders.amount"}))
    attributes_used, attributes_total, facts_used, facts_total = usage["fact_orders"]

    assert facts_used == 1
    assert facts_total == 2
    assert attributes_used == 0
    assert attributes_total == 1
