"""The gate every child passes before a byte of it is written.

Two directions, and both matter:

**Under-pruning** — every reference a retained object makes must resolve *inside the child*.
A metric whose MAQL reaches `{label/dim_store.region}` when `dim_store` was not retained
produces a workspace that loads fine and cannot compute. That failure surfaces at execution
time, in a dashboard tile, which is the worst place to find it.

**Over-pruning** — every dataset in the child's LDM must be explained: reached by the
closure, declared in `ldm_include`, or a join ancestor of one of those. This is the
predecessor's defect asserted as a test. It shipped `"ldm": model["ldm"]` into all twelve
children, so every child carried all 225 datasets; that check is exactly what would have
caught it, and `tests/test_verify.py` runs the degenerate case to prove it does.

A failure aborts the whole split — all domains, not just the offending one — so the output
directory never holds a half-consistent set of children.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from globalmart.closure import DomainClosure, channel
from globalmart.config import GlobalmartError
from globalmart.maql import RefKind, iter_maql_refs
from globalmart.prune import build_entity_index
from globalmart.refs import iter_content_refs, iter_entity_refs, iter_inline_maql


@dataclass(frozen=True)
class VerificationFailure:
    """One unresolvable reference or unexplained dataset."""

    domain: str
    object_id: str
    reference: str
    reason: str

    def __str__(self) -> str:
        return f"{self.domain}: {self.object_id} -> {self.reference} ({self.reason})"


class ChildVerificationError(GlobalmartError):
    """A generated child is internally inconsistent. Never written."""

    def __init__(self, failures: list[VerificationFailure]) -> None:
        listed = "\n    ".join(str(failure) for failure in failures)
        super().__init__(f"{len(failures)} verification failure(s):\n    {listed}")
        self.failures = failures


def verify_child(
    child: Any, domain_key: str, *, closure: DomainClosure | None = None
) -> None:
    """Raise unless every reference resolves and every dataset is explained."""
    failures: list[VerificationFailure] = []

    index = build_entity_index(child.ldm)
    metrics = channel(child, "metrics")
    visualizations = channel(child, "visualization_objects")
    dashboards = channel(child, "analytical_dashboards")
    filter_contexts = channel(child, "filter_contexts")
    hierarchies = channel(child, "attribute_hierarchies")

    def check_entity(object_id: str, identifier: str, path: str) -> None:
        if index.owner_of(identifier) is None:
            failures.append(
                VerificationFailure(
                    domain=domain_key,
                    object_id=object_id,
                    reference=identifier,
                    reason=f"not in this child's LDM (from {path})",
                )
            )

    # --- under-pruning: metrics ---
    for metric_id, metric in sorted(metrics.items()):
        content = getattr(metric, "content", None) or {}
        maql = content.get("maql") if isinstance(content, dict) else None
        for ref in iter_maql_refs(maql):
            if ref.kind is RefKind.METRIC:
                if ref.id not in metrics:
                    failures.append(
                        VerificationFailure(
                            domain=domain_key,
                            object_id=metric_id,
                            reference=ref.id,
                            reason="referenced metric is not in this child",
                        )
                    )
            else:
                check_entity(metric_id, ref.id, "MAQL")

    # --- under-pruning: content-bearing analytics objects ---
    for pool, label in (
        (visualizations, "visualization"),
        (dashboards, "dashboard"),
        (filter_contexts, "filterContext"),
        (hierarchies, "attributeHierarchy"),
    ):
        for object_id, obj in sorted(pool.items()):
            for entity_ref in iter_entity_refs(obj):
                check_entity(object_id, entity_ref.id, entity_ref.path)
            for path, maql in iter_inline_maql(obj):
                for maql_ref in iter_maql_refs(maql):
                    if maql_ref.kind is RefKind.METRIC:
                        if maql_ref.id not in metrics:
                            failures.append(
                                VerificationFailure(
                                    domain=domain_key,
                                    object_id=object_id,
                                    reference=maql_ref.id,
                                    reason=f"inline MAQL metric not in this child ({path})",
                                )
                            )
                    else:
                        check_entity(object_id, maql_ref.id, path)
            if label == "visualization":
                for content_ref in iter_content_refs(obj):
                    if content_ref.type == "metric" and content_ref.id not in metrics:
                        failures.append(
                            VerificationFailure(
                                domain=domain_key,
                                object_id=object_id,
                                reference=content_ref.id,
                                reason="measured metric is not in this child",
                            )
                        )

    # --- under-pruning: no dangling join ---
    for dataset_id, targets in sorted(index.references.items()):
        for target in targets:
            if target not in index.dataset_ids and target not in index.date_instance_ids:
                failures.append(
                    VerificationFailure(
                        domain=domain_key,
                        object_id=dataset_id,
                        reference=target,
                        reason="join target was pruned out of this child",
                    )
                )

    # --- over-pruning: every dataset explained ---
    if closure is not None:
        explained = closure.dataset_ids
        for dataset_id in sorted(index.dataset_ids):
            if dataset_id not in explained:
                failures.append(
                    VerificationFailure(
                        domain=domain_key,
                        object_id=dataset_id,
                        reference="(dataset)",
                        reason=(
                            "present in the child's LDM but reached by no retained object, "
                            "named by no ldm_include, and a join ancestor of neither — this is "
                            "the predecessor's full-LDM copy"
                        ),
                    )
                )

    if failures:
        raise ChildVerificationError(failures)
