"""Reading and writing the parent workspace's YAML tree, in the form gdcloud releases.

The parent lives in ``gd_data_product/globalmart/`` (ADR 011 Stage B): one file per object, in
exactly the bytes ``gd-store`` and ``gd-format-yaml`` produce. That makes every writer in this
package — ``datefilters bind``, ``knowledge build``, a backup — interchangeable with a ``gd-store``
from a dev workspace: whichever wrote the tree, the next one leaves an unchanged object unchanged.

Two things the SDK does not give us:

1. **gdcloud's byte form.** ``store_to_disk(sort=True)`` sorts mapping keys only. gdcloud also
   sorts LDM lists by id and drops empty ``tags`` / ``keywords`` before storing. Rather than
   re-implement those rules and drift from them, ``write_tree`` runs gdcloud's own normalizers over
   a staged tree. They are imported lazily, from a module gdcloud does not declare public, so a pin
   bump that moves them fails this module's tests rather than silently changing the bytes.

2. **Orphan pruning.** The SDK writes with ``create_directory``, not ``recreate_directory``, so a
   file for an object that has since been deleted is left behind forever. ``write_tree`` diffs
   what it wrote against what is on disk under ``ldm/`` and ``analytics_model/`` and removes the
   remainder. Anything else in the folder (``workspace_data_filters.json``) is gdcloud's and is
   never touched.

Paths never contain an org id: the folder is passed explicitly, never derived from
``layout_organization_folder()``. See ``capture.py`` for why.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path
from typing import Any

from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.config import GlobalmartError

#: The parent workspace's tree: gdcloud's data-product folder, and the only authoring surface
#: (ADR 011 Stage B). Every reader defaults to it.
DEFAULT_LAYOUT_PATH = Path("gd_data_product/globalmart")

#: The folders a workspace model owns inside a tree. Everything else is left alone.
CONTENT_FOLDERS = ("ldm", "analytics_model")


class LayoutWriteError(GlobalmartError):
    """gdcloud's normalizers could not format a staged tree."""


def read_tree(workspace_folder: Path) -> CatalogDeclarativeWorkspaceModel:
    """Load a workspace model from a tree.

    ``gd_data_product/<dp>/`` is the SDK's standard ``store_to_disk`` layout (``ldm/`` and
    ``analytics_model/``), so the SDK's own ``load_from_disk`` reads it; gdcloud's
    ``workspace_data_filters.json`` beside them is ignored. Takes an explicit folder — the
    org-agnostic read path, and the reason ``load_declarative_workspace`` is never used.

    The SDK's loader creates a folder for every collection it looks for, empty ones included
    (``analytical_dashboard_extensions/``, ``parameters/``, …). git cannot hold an empty folder
    and gd-store never writes one, so they are removed again rather than left as clutter.
    """
    workspace_folder = Path(workspace_folder)
    model = CatalogDeclarativeWorkspaceModel.load_from_disk(workspace_folder=workspace_folder)
    for folder in CONTENT_FOLDERS:
        if (workspace_folder / folder).exists():
            _prune_empty_dirs(workspace_folder / folder)
    return model


def write_tree(model: CatalogDeclarativeWorkspaceModel, workspace_folder: Path) -> set[Path]:
    """Write a workspace model as gdcloud's YAML tree, deterministically, pruning orphans.

    The model is staged into a temporary directory first, so the set of files *this* write
    produced is known exactly. Writing straight into the target cannot tell a freshly written
    file from a stale one left by an earlier write — both are simply present — and the orphan
    diff would always come out empty.

    Returns the set of paths written, so a caller (or a test) can assert exactly what landed.
    """
    workspace_folder = Path(workspace_folder)
    _drop_empty_wdf_references(model)

    with tempfile.TemporaryDirectory(prefix="globalmart-layout-") as staging_root:
        staging = Path(staging_root) / "workspace"
        staging.mkdir(parents=True)
        model.store_to_disk(workspace_folder=staging, sort=True)
        _format_like_gdcloud(staging)

        relative = {path.relative_to(staging) for path in staging.rglob("*.yaml")}
        existing = {
            path
            for folder in CONTENT_FOLDERS
            if (workspace_folder / folder).exists()
            for path in (workspace_folder / folder).rglob("*.yaml")
        }

        written: set[Path] = set()
        for rel in sorted(relative):
            destination = workspace_folder / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            content = (staging / rel).read_bytes()
            if not destination.exists() or destination.read_bytes() != content:
                destination.write_bytes(content)
            written.add(destination)

    # Files that survive from an earlier write but were not produced by this one belong to
    # objects that no longer exist. Left behind, a deleted object would be released forever.
    for orphan in sorted(existing - written):
        orphan.unlink()

    for folder in CONTENT_FOLDERS:
        if (workspace_folder / folder).exists():
            _prune_empty_dirs(workspace_folder / folder)
    return written


def _drop_empty_wdf_references(model: CatalogDeclarativeWorkspaceModel) -> None:
    """The API omits an empty list here and ``gd-store`` writes no key; a model built in memory
    may carry ``[]``. Without this, every dataset file would differ from what gd-store writes."""
    for dataset in (model.ldm.datasets if model.ldm else None) or []:
        if not dataset.workspace_data_filter_references:
            dataset.workspace_data_filter_references = None


def _format_like_gdcloud(folder: Path) -> None:
    """Run gdcloud's own normalizers over a staged tree, so the bytes match gd-store's."""
    from gdcloud.formatting_yaml import (  # lazily: see the module docstring
        normalize_analytics_model,
        normalize_ldm,
    )
    from gooddata_sdk import GoodDataSdk

    # The normalizers only load from and store to disk; the SDK instance never connects.
    sdk = GoodDataSdk.create(host_="http://localhost", token_="offline")
    chatter = io.StringIO()
    with contextlib.redirect_stdout(chatter), contextlib.redirect_stderr(chatter):
        succeeded = True
        if (folder / "analytics_model").exists():
            succeeded = normalize_analytics_model(sdk, folder) and succeeded
        if (folder / "ldm").exists():
            succeeded = normalize_ldm(sdk, folder) and succeeded
    if not succeeded:
        raise LayoutWriteError(f"gdcloud normalization failed:\n{chatter.getvalue()}")


def _prune_empty_dirs(root: Path) -> None:
    """Remove directories left empty by orphan pruning, deepest first."""
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()


# --- the JSON side (ADR 001: derived children are committed declarative JSON) -------------


def model_to_dict(model: CatalogDeclarativeWorkspaceModel) -> dict[str, Any]:
    """The model as the API spells it.

    Mapping order is fixed by ``sort_keys`` at dump time. **List order is left exactly as
    the model has it**, which is a deliberate reversal of the obvious idea.

    Sorting every list looks like the way to make emission deterministic, and it corrupts
    the document: ``dataSourceTableId.path`` is ``[schema, table]`` positionally, so sorting
    it put the schema second and the publish failed — and it would equally have reordered a
    visualization's ``buckets``, its ``sorts``, and a date instance's ``granularities``, none
    of which announce that they are ordered.

    Determinism comes from the producer instead: ``prune_ldm`` sorts datasets and date
    instances by id, ``split._retain`` emits each analytics channel in sorted-id order, and
    the parent tree is read from files in a fixed order. `test_emission_is_byte_stable`
    holds this honest.
    """
    payload: dict[str, Any] = model.to_dict(camel_case=True)
    return payload


def write_model_json(model: CatalogDeclarativeWorkspaceModel, path: Path) -> Path:
    """Write a workspace model as one deterministic JSON document."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(model_to_dict(model), sort_keys=True, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def read_model_json(path: Path) -> CatalogDeclarativeWorkspaceModel:
    """Load a workspace model from a JSON document written by ``write_model_json``."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return CatalogDeclarativeWorkspaceModel.from_dict(payload, camel_case=True)
