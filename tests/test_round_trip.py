"""Tasks 28–29 — the acceptance harness.

AC #8 requires the round-trip be "asserted by a test rather than eyeballed". Two halves:

1. capture → normalize → write → read is semantically lossless;
2. the normalized tree equals the normalized raw API payload once the fields the
   normalizer is *supposed* to change are masked — so anything else that differs is a bug.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.counts import count_objects
from globalmart.layout_io import read_tree, write_tree
from globalmart.normalize import (
    DATASOURCE_ID_TOKEN,
    DATASOURCE_SCHEMA_TOKEN,
    normalize_workspace,
)

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE = FIXTURES / "mini_globalmart"
RAW_CAPTURE = FIXTURES / "raw_capture.json"
SCHEMA = "globalmart"

#: Field names the normalizer deliberately removes or rewrites. Anything outside this set
#: differing between the raw capture and the committed tree is a defect.
MASKED_KEYS = {
    "createdBy",
    "modifiedBy",
    "createdAt",
    "modifiedAt",
    "dataSourceId",
    "statement",
    "workspaceDataFilterReferences",
}


def _mask(node: Any) -> Any:
    """Drop the keys the normalizer owns, recursively, so the rest can be compared."""
    if isinstance(node, dict):
        return {k: _mask(v) for k, v in sorted(node.items()) if k not in MASKED_KEYS}
    if isinstance(node, list):
        return [_mask(item) for item in node]
    return node


def _sorted_payload(model: CatalogDeclarativeWorkspaceModel) -> Any:
    return json.loads(json.dumps(model.to_dict(camel_case=True), sort_keys=True, default=str))


def test_round_trip_through_disk_is_lossless(tmp_path: Path) -> None:
    """read -> normalize -> write -> read must produce an identical model."""
    model = read_tree(FIXTURE)
    normalize_workspace(model, datasource_schema=SCHEMA)
    expected = _sorted_payload(model)

    destination = tmp_path / "tree"
    write_tree(model, destination)

    assert _sorted_payload(read_tree(destination)) == expected


def test_round_trip_preserves_object_counts(tmp_path: Path) -> None:
    model = read_tree(FIXTURE)
    before = count_objects(model)

    normalize_workspace(model, datasource_schema=SCHEMA)
    destination = tmp_path / "tree"
    write_tree(model, destination)

    assert count_objects(read_tree(destination)) == before


def test_normalized_tree_matches_raw_capture_modulo_parameters(tmp_path: Path) -> None:
    """Everything the normalizer does not own must survive the capture unchanged."""
    raw_payload = json.loads(RAW_CAPTURE.read_text(encoding="utf-8"))
    from_raw = CatalogDeclarativeWorkspaceModel.from_dict(raw_payload, camel_case=True)
    normalize_workspace(from_raw, datasource_schema=SCHEMA)

    from_tree = read_tree(FIXTURE)
    normalize_workspace(from_tree, datasource_schema=SCHEMA)

    assert _mask(_sorted_payload(from_raw)) == _mask(_sorted_payload(from_tree))


def test_masked_fields_are_actually_parameterised(tmp_path: Path) -> None:
    """Guard: masking must not be hiding a normalizer that did nothing."""
    model = read_tree(FIXTURE)
    normalize_workspace(model, datasource_schema=SCHEMA)
    blob = json.dumps(_sorted_payload(model))

    assert DATASOURCE_ID_TOKEN in blob
    assert DATASOURCE_SCHEMA_TOKEN in blob
    assert "globalmart-motherduck" not in blob
    assert '"createdBy"' not in blob


def test_writing_a_normalized_tree_twice_is_byte_stable(tmp_path: Path) -> None:
    """AC #6 end to end: the committed tree must not churn between captures."""
    model = read_tree(FIXTURE)
    normalize_workspace(model, datasource_schema=SCHEMA)

    first = tmp_path / "first"
    second = tmp_path / "second"
    write_tree(model, first)
    write_tree(read_tree(first), second)

    left = {str(p.relative_to(first)): p.read_text(encoding="utf-8") for p in first.rglob("*.yaml")}
    right = {
        str(p.relative_to(second)): p.read_text(encoding="utf-8") for p in second.rglob("*.yaml")
    }
    assert left == right
