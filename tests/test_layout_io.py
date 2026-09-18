"""Task 10 — determinism, orphan pruning, and the org-agnostic path guarantee."""

from __future__ import annotations

from pathlib import Path

from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.counts import count_objects
from globalmart.layout_io import read_tree, write_tree

from .conftest import workspace_payload


def _relative_contents(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.yaml"))
    }


def test_two_writes_are_byte_identical(
    synthetic_model: CatalogDeclarativeWorkspaceModel, tmp_path: Path
) -> None:
    """AC #6, expressed without git: an unchanged model must produce identical bytes."""
    first = tmp_path / "first"
    second = tmp_path / "second"

    write_tree(synthetic_model, first)
    write_tree(synthetic_model, second)

    assert _relative_contents(first) == _relative_contents(second)


def test_rewriting_same_folder_is_stable(
    synthetic_model: CatalogDeclarativeWorkspaceModel, tmp_path: Path
) -> None:
    """The realistic case: a re-capture into the committed tree leaves it untouched."""
    folder = tmp_path / "ws"

    write_tree(synthetic_model, folder)
    before = _relative_contents(folder)

    write_tree(synthetic_model, folder)
    assert _relative_contents(folder) == before


def test_every_file_ends_with_a_newline(
    synthetic_model: CatalogDeclarativeWorkspaceModel, tmp_path: Path
) -> None:
    folder = tmp_path / "ws"
    for path in write_tree(synthetic_model, folder):
        assert path.read_text(encoding="utf-8").endswith("\n"), path


def test_orphan_file_is_pruned_on_rewrite(tmp_path: Path) -> None:
    """The SDK writes with create_directory, never removing files for deleted objects."""
    folder = tmp_path / "ws"

    both = CatalogDeclarativeWorkspaceModel.from_dict(
        workspace_payload(metric_ids=("m_revenue", "m_orders")), camel_case=True
    )
    write_tree(both, folder)
    stale = folder / "analytics_model" / "metrics" / "m_orders.yaml"
    assert stale.exists()

    fewer = CatalogDeclarativeWorkspaceModel.from_dict(
        workspace_payload(metric_ids=("m_revenue",)), camel_case=True
    )
    write_tree(fewer, folder)

    assert not stale.exists(), "metric removed from the model must not survive on disk"
    assert (folder / "analytics_model" / "metrics" / "m_revenue.yaml").exists()


def test_orphan_pruning_survives_a_read_back(tmp_path: Path) -> None:
    """A pruned tree must load as the smaller model, not the stale one."""
    folder = tmp_path / "ws"

    write_tree(
        CatalogDeclarativeWorkspaceModel.from_dict(
            workspace_payload(metric_ids=("m_revenue", "m_orders")), camel_case=True
        ),
        folder,
    )
    write_tree(
        CatalogDeclarativeWorkspaceModel.from_dict(
            workspace_payload(metric_ids=("m_revenue",)), camel_case=True
        ),
        folder,
    )

    assert count_objects(read_tree(folder)).metrics == 1


def test_no_path_segment_carries_an_org_id(
    synthetic_model: CatalogDeclarativeWorkspaceModel, tmp_path: Path
) -> None:
    """STEERING § Portability Contract: the tree must not name the org it came from."""
    folder = tmp_path / "layouts" / "workspaces" / "globalmart"
    written = write_tree(synthetic_model, folder)

    assert written, "expected files to be written"
    for path in written:
        relative = str(path.relative_to(folder))
        assert "petertomko" not in relative
        assert "gooddata_layouts" not in relative


def test_round_trip_preserves_every_channel(
    synthetic_model: CatalogDeclarativeWorkspaceModel, tmp_path: Path
) -> None:
    folder = tmp_path / "ws"
    write_tree(synthetic_model, folder)

    assert count_objects(read_tree(folder)) == count_objects(synthetic_model)


def test_sql_schema_placeholder_is_preserved_verbatim(
    synthetic_model: CatalogDeclarativeWorkspaceModel, tmp_path: Path
) -> None:
    """Stripping this placeholder was a real predecessor defect — assert it survives I/O."""
    folder = tmp_path / "ws"
    write_tree(synthetic_model, folder)

    text = (folder / "ldm" / "datasets" / "sql_channel_summary.yaml").read_text(encoding="utf-8")
    assert "{{ datasource_schema }}" in text
