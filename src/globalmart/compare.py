"""Digest, diff and cross-org comparison of workspace models.

``mask_parameters`` is what makes the portability contract testable: publish the same repo
state into two orgs, mask the values that are *supposed* to differ, and anything still
differing is a defect.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.normalize import DATASOURCE_ID_TOKEN, DATASOURCE_SCHEMA_TOKEN


def _canonical(model: CatalogDeclarativeWorkspaceModel) -> Any:
    return json.loads(json.dumps(model.to_dict(camel_case=True), sort_keys=True, default=str))


def model_digest(model: CatalogDeclarativeWorkspaceModel) -> str:
    """A stable SHA-256 over the model, for detecting "did this publish change anything"."""
    payload = json.dumps(_canonical(model), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def model_diff(
    before: CatalogDeclarativeWorkspaceModel | None,
    after: CatalogDeclarativeWorkspaceModel,
    *,
    limit: int = 50,
) -> list[str]:
    """Flat ``path: old -> new`` lines, for the rehearsal report.

    A ``before`` of ``None`` means the workspace does not exist yet on the target.
    """
    if before is None:
        return ["(target workspace does not exist yet — everything is new)"]

    left = dict(_flatten(_canonical(before)))
    right = dict(_flatten(_canonical(after)))

    lines: list[str] = []
    for key in sorted(left.keys() | right.keys()):
        old, new = left.get(key), right.get(key)
        if old != new:
            lines.append(f"{key}: {old!r} -> {new!r}")
        if len(lines) >= limit:
            lines.append(f"... (diff truncated at {limit} entries)")
            break
    return lines


def _flatten(node: Any, path: str = "") -> list[tuple[str, Any]]:
    if isinstance(node, dict):
        out: list[tuple[str, Any]] = []
        for key, value in node.items():
            out.extend(_flatten(value, f"{path}.{key}" if path else str(key)))
        return out
    if isinstance(node, list):
        out = []
        for index, item in enumerate(node):
            out.extend(_flatten(item, f"{path}[{index}]"))
        return out
    return [(path, node)]


def mask_parameters(
    model: CatalogDeclarativeWorkspaceModel, *, datasource_id: str, datasource_schema: str
) -> Any:
    """Return the model with this target's values replaced by the placeholders again.

    Two orgs' published layouts, masked this way, must be byte-identical — that is the
    portability contract, expressed as an assertion rather than a hope.
    """
    payload = json.dumps(_canonical(model))
    payload = payload.replace(json.dumps(datasource_id)[1:-1], DATASOURCE_ID_TOKEN)
    payload = payload.replace(json.dumps(datasource_schema)[1:-1], DATASOURCE_SCHEMA_TOKEN)
    return json.loads(payload)
