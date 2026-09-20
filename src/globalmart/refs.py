"""The one module that knows where object references hide in *non-MAQL* content.

Dashboards, visualization objects and filter contexts carry their real structure in an
untyped `content` dict that the SDK models as free-form JSON. There is no schema to walk
against, and the shapes vary: a visualization reference can sit at
`sections[].items[].widget.insight.identifier`, inside `drills[].target.identifier`, or two
layout containers deep in a nested `IDashboardLayout`.

So this walks **generically**: it looks for the two ref shapes GoodData uses anywhere in the
tree, rather than enumerating paths.

    {"identifier": {"id": "...", "type": "..."}}     # the common one
    {"id": "...", "type": "..."}                     # the bare form

An enumerator that assumes a shape does not fail loudly when the shape changes — it returns
fewer references, the closure retains less, and the child loads with a tile that renders an
error. That failure looks exactly like success at build time, which is why the walk is
generic and why `tests/test_refs.py` plants a reference at a depth nothing enumerates.

Every yielded ref carries the dotted `path` where it was found, because "metric X is missing"
is a much worse error message than "metric X, referenced from
content.layout.sections[0].items[1].widget.drills[0].target, is missing".
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, NamedTuple

from globalmart.maql import RefKind

#: ``type`` values seen in content blobs, mapped onto the kinds the closure reasons about.
#: An unknown ``type`` (a widget kind, a layout marker) is not a reference and is skipped.
_TYPE_TO_KIND = {
    "metric": RefKind.METRIC,
    "fact": RefKind.FACT,
    "attribute": RefKind.ATTRIBUTE,
    "label": RefKind.LABEL,
    "dataset": RefKind.DATASET,
    "dateInstance": RefKind.DATE_INSTANCE,
}

#: Object references that are not LDM entities — the closure routes these to their own id
#: sets rather than to `entity_refs`.
VISUALIZATION_OBJECT = "visualizationObject"
ANALYTICAL_DASHBOARD = "analyticalDashboard"
FILTER_CONTEXT = "filterContext"
ATTRIBUTE_HIERARCHY = "attributeHierarchy"
DASHBOARD_PLUGIN = "dashboardPlugin"
EXPORT_DEFINITION = "exportDefinition"


class ObjectRef(NamedTuple):
    """One reference found in a content blob, with where it was found."""

    type: str
    id: str
    path: str

    @property
    def kind(self) -> RefKind | None:
        """The LDM entity kind, or ``None`` when this points at an analytics object."""
        return _TYPE_TO_KIND.get(self.type)


def content_of(obj: Any) -> Any:
    """An object's `content`, as a plain dict/list whatever the SDK handed us."""
    content = getattr(obj, "content", None)
    if isinstance(content, (dict, list)):
        return content
    to_dict = getattr(content, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return {}


def iter_content_refs(obj: Any, *, root: str = "content") -> Iterator[ObjectRef]:
    """Every `{id, type}` reference anywhere in an object's content, depth-first.

    This is the primitive; the named generators below are thin filters over it, kept
    separate only so call sites read as intent rather than as string comparisons.
    """
    yield from _walk(content_of(obj), root)


def _walk(node: Any, path: str) -> Iterator[ObjectRef]:
    if isinstance(node, dict):
        # Yield only when *this* node is the reference. Both the wrapped
        # (`{"identifier": {...}}`) and the bare (`{"id": ..., "type": ...}`) shapes are
        # covered by recursion alone — handling `identifier` specially here as well would
        # emit the wrapped form twice, once for the wrapper and once on the way down.
        ref = _as_ref(node, path)
        if ref is not None:
            yield ref
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _walk(item, f"{path}[{index}]")


def _as_ref(node: dict[str, Any], path: str) -> ObjectRef | None:
    node_type = node.get("type")
    node_id = node.get("id")
    if isinstance(node_type, str) and isinstance(node_id, str):
        return ObjectRef(type=node_type, id=node_id, path=path)
    return None


def _of_type(obj: Any, wanted: str) -> Iterator[ObjectRef]:
    for ref in iter_content_refs(obj):
        if ref.type == wanted:
            yield ref


def iter_dashboard_viz_refs(dashboard: Any) -> Iterator[ObjectRef]:
    """Visualizations a dashboard shows — widgets, nested layouts and drill targets alike."""
    yield from _of_type(dashboard, VISUALIZATION_OBJECT)


def iter_dashboard_dashboard_refs(dashboard: Any) -> Iterator[ObjectRef]:
    """Dashboards a dashboard drills to. Rare, but a drill target can be one."""
    for ref in _of_type(dashboard, ANALYTICAL_DASHBOARD):
        if ref.id != getattr(dashboard, "id", None):
            yield ref


def iter_dashboard_filter_refs(dashboard: Any) -> Iterator[ObjectRef]:
    yield from _of_type(dashboard, FILTER_CONTEXT)


def iter_dashboard_plugin_refs(dashboard: Any) -> Iterator[ObjectRef]:
    yield from _of_type(dashboard, DASHBOARD_PLUGIN)


def iter_hierarchy_refs(obj: Any) -> Iterator[ObjectRef]:
    """Attribute hierarchies referenced from a visualization, dashboard or drill."""
    yield from _of_type(obj, ATTRIBUTE_HIERARCHY)


#: The kinds that live in the LDM. `metric` is in `_TYPE_TO_KIND` because MAQL and buckets
#: both name metrics, but a metric is an analytics object, not an LDM entity — routing one
#: into the dataset resolver would fail to resolve an id that is perfectly valid.
LDM_KINDS = frozenset(
    {RefKind.FACT, RefKind.ATTRIBUTE, RefKind.LABEL, RefKind.DATASET, RefKind.DATE_INSTANCE}
)


def iter_entity_refs(obj: Any) -> Iterator[ObjectRef]:
    """Every LDM entity reference — attributes, labels, facts, datasets, date instances.

    Used for visualizations, filter contexts, attribute hierarchies and export definitions
    alike: they all express LDM dependencies the same way, so one generator serves them all.
    Metrics are deliberately excluded; the closure collects those separately.
    """
    for ref in iter_content_refs(obj):
        if ref.kind in LDM_KINDS:
            yield ref


def iter_metric_refs(obj: Any) -> Iterator[ObjectRef]:
    """Metrics a visualization measures."""
    yield from _of_type(obj, "metric")


def iter_inline_maql(obj: Any) -> Iterator[tuple[str, str]]:
    """Yield `(path, maql)` for inline-MAQL measures embedded in a visualization.

    A measure can carry raw MAQL instead of naming a metric, and those references are just
    as load-bearing. Missing them is the same class of hole as missing a `{metric/}` ref.
    """
    yield from _walk_maql(content_of(obj), "content")


def _walk_maql(node: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        maql = node.get("maql")
        if isinstance(maql, str):
            yield f"{path}.maql", maql
        for key, value in node.items():
            yield from _walk_maql(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _walk_maql(item, f"{path}[{index}]")
