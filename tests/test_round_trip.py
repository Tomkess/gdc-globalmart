"""The acceptance harness for the parent's tree (ADR 011 Stage B).

The tree is gdcloud's ``gd_data_product/globalmart/``: whatever writes it — ``gd-store`` from a dev
workspace, ``gd-format-yaml``, or this package's ``write_tree`` — must agree byte for byte, and
reading it back must lose nothing. Three halves:

1. read → write → read is semantically lossless;
2. a raw API capture, stored the way gd-store stores it, equals the committed tree;
3. the real committed tree survives ``write_tree`` byte for byte, so a ``datefilters bind`` or
   ``knowledge build`` never churns an object it did not change.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.counts import count_objects
from globalmart.layout_io import read_tree, write_tree

from .conftest import FIXTURES, PARENT_TREE, committed_mini, strip_activity_info

RAW_CAPTURE = FIXTURES / "raw_capture.json"


def _sorted_payload(model: CatalogDeclarativeWorkspaceModel) -> Any:
    return json.loads(json.dumps(model.to_dict(camel_case=True), sort_keys=True, default=str))


def _drop_empty(node: Any) -> Any:
    """The API omits an empty list where a disk load yields ``[]``; neither means anything else."""
    if isinstance(node, dict):
        return {k: _drop_empty(v) for k, v in node.items() if v not in ([], None, {})}
    if isinstance(node, list):
        return [_drop_empty(item) for item in node]
    return node


def _files(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_round_trip_through_disk_is_lossless(tmp_path: Path) -> None:
    """read -> write -> read must produce the same model."""
    model = committed_mini()
    expected = _drop_empty(_sorted_payload(model))

    destination = tmp_path / "tree"
    write_tree(model, destination)

    assert _drop_empty(_sorted_payload(read_tree(destination))) == expected


def test_round_trip_preserves_object_counts(tmp_path: Path) -> None:
    model = committed_mini()
    before = count_objects(model)

    destination = tmp_path / "tree"
    write_tree(model, destination)

    assert count_objects(read_tree(destination)) == before


def test_raw_capture_stored_like_gd_store_matches_the_tree(tmp_path: Path) -> None:
    """Everything except the activity info gd-store excludes must survive a capture unchanged."""
    raw_payload = json.loads(RAW_CAPTURE.read_text(encoding="utf-8"))
    from_raw = strip_activity_info(CatalogDeclarativeWorkspaceModel.from_dict(raw_payload, camel_case=True))
    write_tree(from_raw, tmp_path / "from_raw")

    write_tree(committed_mini(), tmp_path / "from_tree")

    assert _files(tmp_path / "from_raw") == _files(tmp_path / "from_tree")


def test_writing_a_tree_twice_is_byte_stable(tmp_path: Path) -> None:
    """The committed tree must not churn between writes."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_tree(committed_mini(), first)
    write_tree(read_tree(first), second)

    assert _files(first) == _files(second)


def test_the_committed_parent_survives_write_tree_byte_for_byte(tmp_path: Path) -> None:
    """gd_data_product/globalmart/ is already in gd-store's form, so rewriting it changes nothing.

    This is what makes a gd-store from a dev workspace (gdcloud workflow 2a) and a local
    `datefilters bind` / `knowledge build` interchangeable: neither churns the other's bytes.
    """
    tree = tmp_path / "globalmart"
    shutil.copytree(PARENT_TREE, tree)
    before = _files(tree)

    write_tree(read_tree(tree), tree)

    assert _files(tree) == before


def test_gdcloud_files_beside_the_model_are_left_alone(tmp_path: Path) -> None:
    """workspace_data_filters.json and anything else outside ldm/ and analytics_model/ is gdcloud's."""
    tree = tmp_path / "globalmart"
    write_tree(committed_mini(), tree)
    wdf = tree / "workspace_data_filters.json"
    wdf.write_text('{"data": []}', encoding="utf-8")

    write_tree(committed_mini(), tree)

    assert wdf.read_text(encoding="utf-8") == '{"data": []}'
