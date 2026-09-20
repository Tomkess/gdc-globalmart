"""Reference extraction from untyped content blobs.

The point of every test here: the walk must find references at depths and in shapes nobody
enumerated. An extractor that assumes `sections[].items[].widget.insight` does not fail when
the shape changes — it silently returns fewer references, the closure retains less, and the
child renders a broken tile. That failure looks exactly like success at build time.
"""

from __future__ import annotations

from types import SimpleNamespace

from globalmart.maql import RefKind
from globalmart.refs import (
    iter_content_refs,
    iter_dashboard_filter_refs,
    iter_dashboard_viz_refs,
    iter_entity_refs,
    iter_inline_maql,
    iter_metric_refs,
)


def obj(content: dict) -> SimpleNamespace:  # type: ignore[type-arg]
    return SimpleNamespace(id="x", content=content)


def test_finds_the_identifier_wrapped_shape() -> None:
    dashboard = obj({"widget": {"insight": {"identifier": {"id": "v1", "type": "visualizationObject"}}}})
    assert [ref.id for ref in iter_dashboard_viz_refs(dashboard)] == ["v1"]


def test_finds_the_bare_shape() -> None:
    dashboard = obj({"widget": {"insight": {"id": "v1", "type": "visualizationObject"}}})
    assert [ref.id for ref in iter_dashboard_viz_refs(dashboard)] == ["v1"]


def test_finds_a_drill_target() -> None:
    dashboard = obj(
        {
            "layout": {
                "sections": [
                    {
                        "items": [
                            {
                                "widget": {
                                    "insight": {
                                        "identifier": {"id": "v1", "type": "visualizationObject"}
                                    },
                                    "drills": [
                                        {
                                            "target": {
                                                "identifier": {
                                                    "id": "v2",
                                                    "type": "visualizationObject",
                                                }
                                            }
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                ]
            }
        }
    )
    assert sorted(ref.id for ref in iter_dashboard_viz_refs(dashboard)) == ["v1", "v2"]


def test_finds_a_reference_at_a_depth_nothing_enumerates() -> None:
    """Defence against widget-schema drift, asserted rather than hoped for."""
    deep = {"identifier": {"id": "v9", "type": "visualizationObject"}}
    dashboard = obj({"a": {"b": [{"c": {"d": [deep]}}]}})
    assert [ref.id for ref in iter_dashboard_viz_refs(dashboard)] == ["v9"]


def test_paths_name_where_a_reference_was_found() -> None:
    insight = {"identifier": {"id": "v1", "type": "visualizationObject"}}
    dashboard = obj({"layout": {"sections": [{"items": [{"widget": {"insight": insight}}]}]}})
    (ref,) = list(iter_dashboard_viz_refs(dashboard))
    assert ref.path == "content.layout.sections[0].items[0].widget.insight.identifier"


def test_entity_refs_exclude_metrics() -> None:
    """A metric is an analytics object; routing one to the dataset resolver would fail."""
    viz = obj(
        {
            "buckets": [
                {"items": [{"measure": {"definition": {"item": {"identifier": {
                    "id": "m1", "type": "metric"}}}}}]},
                {"items": [{"attribute": {"displayForm": {"identifier": {
                    "id": "d.l", "type": "label"}}}}]},
            ]
        }
    )
    assert [ref.id for ref in iter_entity_refs(viz)] == ["d.l"]
    assert [ref.id for ref in iter_metric_refs(viz)] == ["m1"]
    assert {ref.kind for ref in iter_entity_refs(viz)} == {RefKind.LABEL}


def test_inline_maql_is_found() -> None:
    inline = {"inline": {"maql": "SELECT {metric/m2}"}}
    viz = obj({"buckets": [{"items": [{"measure": {"definition": inline}}]}]})
    found = list(iter_inline_maql(viz))
    assert len(found) == 1
    path, maql = found[0]
    assert maql == "SELECT {metric/m2}"
    assert path.endswith(".maql")


def test_filter_context_refs() -> None:
    dashboard = obj({"filterContextRef": {"identifier": {"id": "fc1", "type": "filterContext"}}})
    assert [ref.id for ref in iter_dashboard_filter_refs(dashboard)] == ["fc1"]


def test_missing_or_unusable_content_is_not_an_error() -> None:
    assert list(iter_content_refs(SimpleNamespace(id="x", content=None))) == []
    assert list(iter_content_refs(SimpleNamespace(id="x"))) == []


def test_an_unknown_type_is_not_a_reference() -> None:
    """Layout markers carry a `type` too; only known kinds are references."""
    dashboard = obj({"type": "IDashboardLayout", "id": "not-a-ref"})
    assert [ref.id for ref in iter_entity_refs(dashboard)] == []
