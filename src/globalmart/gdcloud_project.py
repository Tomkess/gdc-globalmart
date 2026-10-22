"""Project the parent layout into gdcloud's data-product tree (FEAT-019, ADR 011).

``layouts/workspaces/globalmart/`` stays the authoring surface: placeholder form, normalized,
org-agnostic (ADR 001). gdcloud releases ``gd_data_product/globalmart/`` instead, so that tree is
*derived* from the layout here: placeholders resolved to the canonical data source, then written
in exactly the form ``gd-store`` and ``gd-format-yaml`` produce. A hand edit to the derived tree,
or a ``gd-store`` into it, makes it differ from the projection, and ``--check`` (plus the
``projection_current`` gd-ci check) fails.

Offline and deterministic: nothing here reads a live org (STEERING § Architecture Constraints).

Byte parity with gdcloud
------------------------
The SDK's ``store_to_disk(sort=True)`` sorts mapping keys only. gdcloud additionally sorts LDM
lists by id and drops empty ``tags`` before storing, in ``gd-store`` and ``gd-format-yaml`` alike.
Rather than re-implement those rules and drift from them, the projection runs gdcloud's own
normalizers over the staged tree. That is the one place this package imports ``gdcloud`` — lazily,
from a module gdcloud does not declare public, so a pin bump that moves them fails the projector's
tests rather than silently changing the bytes.
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.config import GlobalmartError
from globalmart.gdcloud_bridge import ReleaseConfig
from globalmart.layout_io import model_to_dict, read_tree
from globalmart.resolve import resolve_and_assert

DEFAULT_LAYOUT_PATH = Path("layouts/workspaces/globalmart")
DEFAULT_OUT_PATH = Path("gd_data_product")

#: The folders the projection owns inside ``gd_data_product/<dp>/``. Anything else there
#: (``config.*.yml``) is hand-written policy and never touched.
CONTENT_FOLDERS = ("ldm", "analytics_model")

#: Workspace data filters are dropped for every target (STEERING § Portability Contract), so the
#: projection carries the empty document ``gd-store`` writes for a workspace without any.
WDF_FILE = "workspace_data_filters.json"
_EMPTY_WDF: dict[str, list[object]] = {"data": []}

#: Keys that would carry a source org's user ids. ``normalize`` strips them on capture.
_IDENTITY_KEYS = frozenset({"createdBy", "modifiedBy"})


class ProjectionError(GlobalmartError):
    """The parent layout cannot be projected into a releasable data product."""


@dataclass(frozen=True)
class Projection:
    dp_id: str
    files: dict[Path, bytes]   # path relative to gd_data_product/<dp_id>/ -> exact content

    def owns(self, relative: Path) -> bool:
        """Whether a file at this path inside the DP folder is the projection's to manage."""
        return relative.parts[:1] in {(folder,) for folder in CONTENT_FOLDERS} or relative == Path(WDF_FILE)


def project_parent(config: ReleaseConfig, layout: Path = DEFAULT_LAYOUT_PATH) -> Projection:
    """Resolve the parent layout against the canonical data source and render gdcloud's tree."""
    if not layout.is_dir():
        raise ProjectionError(f"Parent layout not found: {layout}")
    model = read_tree(layout)
    resolve_and_assert(
        model, datasource_id=config.datasource_id, datasource_schema=config.datasource_schema
    )
    _assert_portable(model)
    # The API omits an empty list here and gd-store writes no key; the captured layout carries
    # `[]`. Without this, every dataset file would differ from what gd-store writes back.
    for dataset in (model.ldm.datasets if model.ldm else None) or []:
        if not dataset.workspace_data_filter_references:
            dataset.workspace_data_filter_references = None

    with tempfile.TemporaryDirectory() as staging:
        dp_dir = Path(staging) / config.dp_id
        model.store_to_disk(workspace_folder=dp_dir)
        (dp_dir / WDF_FILE).write_text(json.dumps(_EMPTY_WDF))
        _format_like_gdcloud(dp_dir)
        files = {
            path.relative_to(dp_dir): path.read_bytes()
            for path in sorted(dp_dir.rglob("*"))
            if path.is_file()
        }
    return Projection(dp_id=config.dp_id, files=files)


def _assert_portable(model: CatalogDeclarativeWorkspaceModel) -> None:
    """No user ids and no workspace data filters may reach a released workspace."""
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in _IDENTITY_KEYS and value:
                    found.append(f"{path}.{key}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")

    document = model_to_dict(model)
    walk(document, "$")
    if found:
        shown = ", ".join(found[:5])
        raise ProjectionError(f"{len(found)} user reference(s) in the layout, e.g. {shown}")

    datasets = ((document.get("ldm") or {}).get("datasets")) or []
    with_wdf = [d["id"] for d in datasets if d.get("workspaceDataFilterReferences")]
    if with_wdf:
        raise ProjectionError(f"Workspace data filter references on {with_wdf[:5]}; they are dropped")


def _format_like_gdcloud(dp_dir: Path) -> None:
    """Run gdcloud's own normalizers over the staged tree, so the bytes match gd-store's."""
    from gdcloud.formatting_yaml import (  # type: ignore[import-untyped]  # lazily: see module docstring
        normalize_analytics_model,
        normalize_ldm,
        normalize_wdf_json,
    )
    from gooddata_sdk import GoodDataSdk

    # The normalizers only load from and store to disk; the SDK instance never connects.
    sdk = GoodDataSdk.create(host_="http://localhost", token_="offline")
    chatter = io.StringIO()
    with contextlib.redirect_stdout(chatter):
        succeeded = (
            normalize_analytics_model(sdk, dp_dir)
            and normalize_ldm(sdk, dp_dir)
            and normalize_wdf_json(dp_dir)
        )
    if not succeeded:
        raise ProjectionError(f"gdcloud normalization failed:\n{chatter.getvalue()}")


def write_projection(
    projection: Projection, out: Path = DEFAULT_OUT_PATH, *, dry_run: bool = False
) -> list[Path]:
    """Make ``out/<dp>/`` hold exactly the projection; return every path written or removed."""
    target = out / projection.dp_id
    changed: list[Path] = []
    for relative, content in projection.files.items():
        path = target / relative
        if path.exists() and path.read_bytes() == content:
            continue
        changed.append(path)
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    for stale in _stale_files(projection, target):
        changed.append(stale)
        if not dry_run:
            stale.unlink()
    if not dry_run:
        _prune_empty_dirs(target)
    return changed


def diff_projection(projection: Projection, out: Path = DEFAULT_OUT_PATH) -> list[str]:
    """Every way the committed tree differs from the projection; empty means current."""
    target = out / projection.dp_id
    problems: list[str] = []
    for relative, content in projection.files.items():
        path = target / relative
        if not path.exists():
            problems.append(f"missing: {relative}")
        elif path.read_bytes() != content:
            problems.append(f"differs: {relative}")
    problems.extend(f"stale: {path.relative_to(target)}" for path in _stale_files(projection, target))
    return problems


def _stale_files(projection: Projection, target: Path) -> list[Path]:
    if not target.is_dir():
        return []
    return [
        path
        for path in sorted(target.rglob("*"))
        if path.is_file()
        and projection.owns(path.relative_to(target))
        and path.relative_to(target) not in projection.files
    ]


def _prune_empty_dirs(root: Path) -> None:
    folders = sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True)
    for folder in folders:
        if not any(folder.iterdir()):
            folder.rmdir()
