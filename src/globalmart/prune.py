"""LDM pruning: which datasets a child actually needs, and the join closure over them.

This is the module that exists because the predecessor wrote `"ldm": model["ldm"]` into all
twelve children. A workforce-only workspace exposing all 225 retail tables is not a domain
workspace, and it distorts exactly the AI search and routing evaluation these workspaces
exist for.

Two pieces:

**`EntityIndex`** maps every attribute, label, fact, dataset and date-instance id to the
dataset that owns it, so a `{label/dim_customer.customer_name}` reference can be turned into
"retain `dim_customer`". It is also where the dotted-id ambiguity `maql.py` deliberately left
open is resolved: `transaction_date.month` is a date instance plus a granularity only because
`transaction_date` is in `date_instances`, and `fact_daily_store_sales.sales_amount` is a
whole fact id only because it is in the fact map. Measured on the parent: 359 attributes, 220
facts, 225 datasets, 2 date instances, and zero separate label objects — an attribute with no
explicit labels is referenced by its own id, which is why lookup falls through attributes.

**`expand_join_ancestors`** follows `dataset.references[].identifier.id` **forward only**.
That direction is the whole narrowing: a dataset's references point at the datasets it joins
*to* — its dimensions — so retaining a fact table drags its dimensions in, while retaining a
dimension never drags in the facts that point at it. Getting it backwards produces children
that are either the whole parent again or missing every dimension, and both look plausible
until something fails to compute.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from globalmart.config import GlobalmartError
from globalmart.maql import RefKind


class DanglingReferenceError(GlobalmartError):
    """A reference points at something that does not exist in the parent."""


@dataclass(frozen=True)
class EntityIndex:
    """Every LDM id, mapped to what owns it. Built once per split run."""

    attribute_to_dataset: dict[str, str] = field(default_factory=dict)
    label_to_dataset: dict[str, str] = field(default_factory=dict)
    fact_to_dataset: dict[str, str] = field(default_factory=dict)
    dataset_ids: frozenset[str] = frozenset()
    date_instance_ids: frozenset[str] = frozenset()
    #: dataset id -> the datasets it joins to (its dimensions). Forward edges only.
    references: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def owner_of(self, identifier: str) -> tuple[RefKind, str] | None:
        """Resolve one id to ``(kind, owner id)``, or ``None`` when it is unknown.

        ``kind`` is ``DATE_INSTANCE`` when the owner is a date instance and ``DATASET``
        otherwise, so the caller routes it to the right retained set without re-deriving
        what it just looked up.
        """
        if identifier in self.dataset_ids:
            return RefKind.DATASET, identifier
        if identifier in self.date_instance_ids:
            return RefKind.DATE_INSTANCE, identifier
        for mapping in (self.attribute_to_dataset, self.label_to_dataset, self.fact_to_dataset):
            owner = mapping.get(identifier)
            if owner is not None:
                return RefKind.DATASET, owner
        # `transaction_date.month` — a date instance plus a granularity. Checked last, so a
        # real dotted attribute or fact id never gets truncated into one.
        base = identifier.split(".", 1)[0]
        if base in self.date_instance_ids:
            return RefKind.DATE_INSTANCE, base
        return None

    def resolve_entity(self, identifier: str, *, context: str) -> tuple[RefKind, str]:
        """Same as ``owner_of``, but an unknown id is a failure rather than a ``None``."""
        owner = self.owner_of(identifier)
        if owner is None:
            raise DanglingReferenceError(
                f"{context}: reference to {identifier!r}, which exists nowhere in the parent LDM "
                "— no dataset, attribute, label, fact or date instance carries that id"
            )
        return owner


def _datasets(ldm: Any) -> list[Any]:
    return list(getattr(ldm, "datasets", None) or [])


def _date_instances(ldm: Any) -> list[Any]:
    return list(getattr(ldm, "date_instances", None) or [])


def build_entity_index(ldm: Any) -> EntityIndex:
    """Index the parent LDM once; every domain's closure reads it."""
    attribute_to_dataset: dict[str, str] = {}
    label_to_dataset: dict[str, str] = {}
    fact_to_dataset: dict[str, str] = {}
    references: dict[str, tuple[str, ...]] = {}

    for dataset in _datasets(ldm):
        dataset_id = str(dataset.id)

        for attribute in getattr(dataset, "attributes", None) or []:
            attribute_to_dataset[str(attribute.id)] = dataset_id
            for label in getattr(attribute, "labels", None) or []:
                label_to_dataset[str(label.id)] = dataset_id

        for fact in getattr(dataset, "facts", None) or []:
            fact_to_dataset[str(fact.id)] = dataset_id
        for fact in getattr(dataset, "aggregated_facts", None) or []:
            fact_to_dataset[str(fact.id)] = dataset_id

        targets: list[str] = []
        for reference in getattr(dataset, "references", None) or []:
            identifier = getattr(reference, "identifier", None)
            target = getattr(identifier, "id", None)
            if isinstance(target, str):
                targets.append(target)
        references[dataset_id] = tuple(sorted(set(targets)))

    return EntityIndex(
        attribute_to_dataset=attribute_to_dataset,
        label_to_dataset=label_to_dataset,
        fact_to_dataset=fact_to_dataset,
        dataset_ids=frozenset(str(dataset.id) for dataset in _datasets(ldm)),
        date_instance_ids=frozenset(str(instance.id) for instance in _date_instances(ldm)),
        references=references,
    )


def expand_join_ancestors(
    index: EntityIndex, seed_dataset_ids: set[str]
) -> tuple[frozenset[str], frozenset[str]]:
    """Follow join edges forward to fixpoint.

    Returns ``(dataset_ids, date_instance_ids)`` — an edge can point at a date instance, in
    which case that date instance is required by the join itself and travels too.

    Forward only. A retained fact table pulls its dimensions in; a retained dimension does
    not pull in the facts pointing at it. That asymmetry is the narrowing.
    """
    datasets: set[str] = set()
    date_instances: set[str] = set()
    worklist = list(seed_dataset_ids)

    while worklist:
        current = worklist.pop()
        if current in datasets:
            continue
        if current in index.date_instance_ids:
            date_instances.add(current)
            continue
        if current not in index.dataset_ids:
            raise DanglingReferenceError(
                f"join closure: dataset {current!r} does not exist in the parent LDM"
            )
        datasets.add(current)
        worklist.extend(index.references.get(current, ()))

    return frozenset(datasets), frozenset(date_instances)


def prune_ldm(ldm: Any, dataset_ids: frozenset[str], date_instance_ids: frozenset[str]) -> Any:
    """A new LDM holding only the named datasets and date instances.

    Deep-copied, so the parent model is untouched and `split_all` can run every domain from
    one loaded tree.

    Each retained dataset keeps **every** attribute, label and fact it has: pruning is
    dataset-level only (ADR/spec § Out of Scope). A label that looks unused may be a join
    grain or another dataset's reference target, and stripping it breaks the child only at
    execution time — while keeping it is exactly the authoring headroom a child needs. Its
    `references` need no filtering either, because the ancestor closure guarantees every
    target is present; `verify_child` asserts that rather than trusting it.
    """
    pruned = copy.deepcopy(ldm)
    pruned.datasets = sorted(
        (dataset for dataset in _datasets(ldm) if str(dataset.id) in dataset_ids),
        key=lambda dataset: str(dataset.id),
    )
    pruned.datasets = [copy.deepcopy(dataset) for dataset in pruned.datasets]
    pruned.date_instances = [
        copy.deepcopy(instance)
        for instance in sorted(_date_instances(ldm), key=lambda i: str(i.id))
        if str(instance.id) in date_instance_ids
    ]
    if hasattr(pruned, "dataset_extensions"):
        pruned.dataset_extensions = [
            copy.deepcopy(extension)
            for extension in sorted(
                getattr(ldm, "dataset_extensions", None) or [], key=lambda e: str(e.id)
            )
            if str(extension.id) in dataset_ids
        ]
    return pruned


def dataset_column_usage(
    ldm: Any, used_entity_ids: frozenset[str]
) -> dict[str, tuple[int, int, int, int]]:
    """Per dataset: ``(attributes used, attributes total, facts used, facts total)``.

    Evidence, not a pruning input. Columns are never pruned; this exists so that a future
    proposal to prune them is argued from measurement rather than intuition.
    """
    usage: dict[str, tuple[int, int, int, int]] = {}
    for dataset in _datasets(ldm):
        attributes = list(getattr(dataset, "attributes", None) or [])
        facts = list(getattr(dataset, "facts", None) or []) + list(
            getattr(dataset, "aggregated_facts", None) or []
        )
        attributes_used = sum(
            1
            for attribute in attributes
            if str(attribute.id) in used_entity_ids
            or any(
                str(label.id) in used_entity_ids
                for label in (getattr(attribute, "labels", None) or [])
            )
        )
        facts_used = sum(1 for fact in facts if str(fact.id) in used_entity_ids)
        usage[str(dataset.id)] = (attributes_used, len(attributes), facts_used, len(facts))
    return usage
