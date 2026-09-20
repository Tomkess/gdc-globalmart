"""What the repo says each workspace should contain.

Every expectation here is computed from a **committed artifact** — the parent tree, the
generated child JSONs, `domains.yaml` — and never from a live org. That asymmetry is what
makes the comparison meaningful: the repo asserts, the org answers.

The pruning and coverage checks deliberately re-derive their answers from the artifacts
rather than calling FEAT-004's closure code. That is not duplication for its own sake. These
catch what FEAT-004's unit tests structurally cannot: a generated file committed before a
pruner fix, a hand-edited generated file (which STEERING calls a defect), or a child
published from an artifact that no longer matches the parent. FEAT-004 proves its algorithm;
this proves the bytes on disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from globalmart.counts import ObjectCounts, count_objects
from globalmart.layout_io import read_model_json, read_tree
from globalmart.maql import RefKind, iter_maql_refs
from globalmart.prune import build_entity_index
from globalmart.refs import iter_content_refs, iter_entity_refs

#: Pinned so a wholesale regeneration that halves the parent fails loudly rather than
#: quietly becoming the new expectation. Measured on the tree committed 2026-09-18.
PARENT_EXPECTED = {
    "datasets": 225,
    "metrics": 1091,
    "visualization_objects": 384,
    "analytical_dashboards": 32,
    "date_instances": 2,
}


@dataclass
class CountMismatch:
    workspace_id: str
    object_type: str
    expected: int
    actual: int

    def __str__(self) -> str:
        return (
            f"{self.workspace_id}: {self.object_type} expected {self.expected}, "
            f"org reports {self.actual}"
        )


@dataclass
class CoverageReport:
    parent_dashboards: int = 0
    parent_visualizations: int = 0
    covered_dashboards: int = 0
    covered_visualizations: int = 0
    missing_dashboard_ids: list[str] = field(default_factory=list)
    missing_visualization_ids: list[str] = field(default_factory=list)
    #: Informational: a visualization in several children is legal and expected.
    multi_domain_visualization_ids: list[str] = field(default_factory=list)
    passed: bool = True


@dataclass
class PruningViolation:
    workspace_id: str
    dataset_id: str
    reason: str

    def __str__(self) -> str:
        return f"{self.workspace_id}: {self.dataset_id} ({self.reason})"


def expected_parent_counts(tree_path: Path) -> ObjectCounts:
    return count_objects(read_tree(Path(tree_path)))


def expected_child_counts(json_path: Path) -> ObjectCounts:
    return count_objects(read_model_json(Path(json_path)))


#: Channels worth comparing. Ones the SDK does not model on every version are skipped rather
#: than asserted as zero, which would make a count check fail for a reason nobody cares about.
COMPARED_CHANNELS = (
    "datasets",
    "date_instances",
    "metrics",
    "visualization_objects",
    "analytical_dashboards",
    "filter_contexts",
    "attribute_hierarchies",
    "memory_items",
    "parameters",
)


def compare_counts(
    workspace_id: str, expected: ObjectCounts, actual: ObjectCounts
) -> list[CountMismatch]:
    """Every channel where the org disagrees with the repo."""
    expected_map = expected.as_dict()
    actual_map = actual.as_dict()
    return [
        CountMismatch(
            workspace_id=workspace_id,
            object_type=channel,
            expected=expected_map.get(channel, 0),
            actual=actual_map.get(channel, 0),
        )
        for channel in COMPARED_CHANNELS
        if expected_map.get(channel, 0) != actual_map.get(channel, 0)
    ]


def check_coverage(parent: Any, children: dict[str, Any]) -> CoverageReport:
    """Every parent dashboard and visualization must appear in at least one child."""
    parent_dashboards = {str(d.id) for d in (parent.analytics.analytical_dashboards or [])}
    parent_visualizations = {str(v.id) for v in (parent.analytics.visualization_objects or [])}

    seen_dashboards: set[str] = set()
    viz_owners: dict[str, list[str]] = {}
    for workspace_id, child in children.items():
        seen_dashboards |= {str(d.id) for d in (child.analytics.analytical_dashboards or [])}
        for viz in child.analytics.visualization_objects or []:
            viz_owners.setdefault(str(viz.id), []).append(workspace_id)

    missing_dashboards = sorted(parent_dashboards - seen_dashboards)
    missing_visualizations = sorted(parent_visualizations - set(viz_owners))

    return CoverageReport(
        parent_dashboards=len(parent_dashboards),
        parent_visualizations=len(parent_visualizations),
        covered_dashboards=len(parent_dashboards & seen_dashboards),
        covered_visualizations=len(parent_visualizations & set(viz_owners)),
        missing_dashboard_ids=missing_dashboards,
        missing_visualization_ids=missing_visualizations,
        multi_domain_visualization_ids=sorted(
            viz_id for viz_id, owners in viz_owners.items() if len(owners) > 1
        ),
        passed=not (missing_dashboards or missing_visualizations),
    )


def reachable_datasets(child: Any) -> set[str]:
    """Datasets this child's own retained content actually needs.

    Computed from the child alone — its metrics' MAQL, its visualizations', dashboards' and
    hierarchies' entity references, then the join-ancestor closure over the result. No call
    into FEAT-004: the point is to check the artifact independently of the code that wrote it.
    """
    index = build_entity_index(child.ldm)
    entity_ids: set[str] = set()

    for metric in child.analytics.metrics or []:
        content = getattr(metric, "content", None) or {}
        maql = content.get("maql") if isinstance(content, dict) else None
        for maql_ref in iter_maql_refs(maql):
            if maql_ref.kind is not RefKind.METRIC:
                entity_ids.add(maql_ref.id)

    for channel in (
        child.analytics.visualization_objects,
        child.analytics.analytical_dashboards,
        child.analytics.filter_contexts,
        getattr(child.analytics, "attribute_hierarchies", None),
    ):
        for obj in channel or []:
            for entity_ref in iter_entity_refs(obj):
                entity_ids.add(entity_ref.id)
            for content_ref in iter_content_refs(obj):
                if content_ref.id in index.dataset_ids:
                    entity_ids.add(content_ref.id)

    seeds: set[str] = set()
    for entity_id in entity_ids:
        owner = index.owner_of(entity_id)
        if owner is not None and owner[0] is RefKind.DATASET:
            seeds.add(owner[1])

    # Join ancestors of anything reached are reached too.
    reached = set(seeds)
    worklist = list(seeds)
    while worklist:
        current = worklist.pop()
        for target in index.references.get(current, ()):
            if target in index.dataset_ids and target not in reached:
                reached.add(target)
                worklist.append(target)
    return reached


def check_pruning(
    parent: Any, children: dict[str, Any], *, declared: dict[str, set[str]] | None = None
) -> list[PruningViolation]:
    """Two invariants per child: nothing unexplained, and strictly narrower than the parent.

    `declared` carries each domain's `ldm_include` — datasets deliberately added beyond
    closure reach for authoring headroom. Without it those would read as unreachable, which
    is the one way this check can cry wolf.
    """
    parent_dataset_count = len(parent.ldm.datasets or [])
    violations: list[PruningViolation] = []

    for workspace_id, child in sorted(children.items()):
        child_datasets = {str(d.id) for d in (child.ldm.datasets or [])}
        allowed = reachable_datasets(child) | (declared or {}).get(workspace_id, set())

        for dataset_id in sorted(child_datasets - allowed):
            violations.append(
                PruningViolation(
                    workspace_id=workspace_id,
                    dataset_id=dataset_id,
                    reason="unreachable",
                )
            )

        if len(child_datasets) >= parent_dataset_count:
            violations.append(
                PruningViolation(
                    workspace_id=workspace_id,
                    dataset_id=f"({len(child_datasets)} datasets)",
                    reason="dataset_count_not_reduced",
                )
            )

    return violations


def check_parent_literals(counts: ObjectCounts) -> list[str]:
    """The parent's absolute numbers, pinned.

    A count check that only compares the repo against itself is tautological; this is the
    one place a literal is asserted, so a regeneration that halves the parent fails.
    """
    actual = counts.as_dict()
    return [
        f"parent {channel}: pinned {expected}, tree has {actual.get(channel, 0)}"
        for channel, expected in PARENT_EXPECTED.items()
        if actual.get(channel, 0) != expected
    ]
