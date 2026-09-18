"""Deterministic reading and writing of the parent workspace's YAML tree.

Two things the SDK does not give us, both load-bearing for FEAT-001's acceptance criteria:

1. **Byte stability.** ``store_to_disk(sort=True)`` sorts mapping keys but leaves the YAML
   dumper's own formatting choices (width, flow style, unicode escaping) up to defaults
   that can shift between releases. ``write_tree`` re-dumps every emitted file through one
   fixed configuration so a re-capture of an unchanged workspace produces an empty
   ``git diff``.

2. **Orphan pruning.** The SDK writes with ``create_directory`` (``utils.py:168``), not
   ``recreate_directory``, so a file for an object that has since been deleted is left
   behind forever. ``write_tree`` diffs what it wrote against what is on disk and removes
   the remainder.

Paths never contain an org id: the folder is passed explicitly, never derived from
``layout_organization_folder()``. See ``capture.py`` for why.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import yaml
from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)


def _canonicalise(path: Path) -> None:
    """Re-dump one YAML file through one fixed configuration, with a trailing newline.

    The configuration is spelled out at the call site rather than held in a dict so the
    type checker sees the real overload — and so a future change to any of these knobs is
    visible as a diff on the line that produces the bytes.
    """
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    text = yaml.safe_dump(
        content,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
        width=120,
        indent=2,
    )
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def write_tree(model: CatalogDeclarativeWorkspaceModel, workspace_folder: Path) -> set[Path]:
    """Write a workspace model as a YAML tree, deterministically, pruning orphans.

    The model is staged into a temporary directory first, so the set of files *this* write
    produced is known exactly. Writing straight into the target cannot tell a freshly
    written file from a stale one left by an earlier write — both are simply present — and
    the orphan diff would always come out empty.

    Returns the set of paths written, so a caller (or a test) can assert exactly what
    landed on disk.
    """
    workspace_folder = Path(workspace_folder)

    with tempfile.TemporaryDirectory(prefix="globalmart-layout-") as staging_root:
        staging = Path(staging_root) / "workspace"
        staging.mkdir(parents=True)
        model.store_to_disk(workspace_folder=staging, sort=True)

        staged = sorted(staging.rglob("*.yaml"))
        for path in staged:
            _canonicalise(path)

        relative = {path.relative_to(staging) for path in staged}

        existing = set(workspace_folder.rglob("*.yaml")) if workspace_folder.exists() else set()

        written: set[Path] = set()
        for rel in sorted(relative):
            destination = workspace_folder / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(staging / rel, destination)
            written.add(destination)

    # Files that survive from an earlier write but were not produced by this one belong to
    # objects that no longer exist. The SDK never removes them (it uses create_directory,
    # not recreate_directory), so a deleted object would otherwise be republished forever.
    for orphan in sorted(existing - written):
        orphan.unlink()

    _prune_empty_dirs(workspace_folder)
    return written


def _prune_empty_dirs(root: Path) -> None:
    """Remove directories left empty by orphan pruning, deepest first."""
    for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()


def read_tree(workspace_folder: Path) -> CatalogDeclarativeWorkspaceModel:
    """Load a workspace model from a YAML tree.

    Takes an explicit folder — this is the org-agnostic read path, and the reason
    ``load_declarative_workspace`` is never used.
    """
    return CatalogDeclarativeWorkspaceModel.load_from_disk(workspace_folder=Path(workspace_folder))
