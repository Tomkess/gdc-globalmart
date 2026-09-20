"""The portability contract, checked against two live orgs.

STEERING's final portability line: "publishing the same repo state into two different orgs
yields workspaces whose normalized layouts are identical except for the parameterized
values." FEAT-002 proved that offline with two `FakeSdk`s and, later, by capturing both real
orgs by hand. This makes it a command.

The masking is FEAT-002's `compare.mask_parameters()` — the same function, deliberately, so
the offline proof and the live one cannot disagree about what "except for the parameterized
values" means.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from globalmart.compare import mask_parameters, model_digest
from globalmart.config import TargetProfile


@dataclass
class EquivalenceReport:
    target_a: str
    target_b: str
    workspace_id: str
    digest_a: str = ""
    digest_b: str = ""
    equivalent: bool = False
    differing_paths: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        lines = [
            f"workspace         : {self.workspace_id}",
            f"{self.target_a:18s}: {self.digest_a[:16]}",
            f"{self.target_b:18s}: {self.digest_b[:16]}",
            f"equivalent        : {self.equivalent}",
        ]
        if self.differing_paths:
            lines.append(f"differing paths   : {len(self.differing_paths)}")
            lines.extend(f"  {path}" for path in self.differing_paths[:20])
            if len(self.differing_paths) > 20:
                lines.append(f"  ... ({len(self.differing_paths) - 20} more)")
        return lines


def dict_diff(left: Any, right: Any, path: str = "") -> list[str]:
    """Path-wise diff over two already-masked dicts.

    Only ever called on masked structures, so a difference it reports is by construction a
    difference that is *not* explained by the target — which is the whole question.
    """
    differences: list[str] = []

    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            child = f"{path}.{key}" if path else str(key)
            if key not in left:
                differences.append(f"{child}: missing on the left")
            elif key not in right:
                differences.append(f"{child}: missing on the right")
            else:
                differences.extend(dict_diff(left[key], right[key], child))
        return differences

    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            differences.append(f"{path}: {len(left)} item(s) vs {len(right)}")
        for index, (one, other) in enumerate(zip(left, right, strict=False)):
            differences.extend(dict_diff(one, other, f"{path}[{index}]"))
        return differences

    if left != right:
        differences.append(f"{path}: {left!r} != {right!r}")
    return differences


def compare_orgs(
    sdk_a: Any,
    profile_a: TargetProfile,
    sdk_b: Any,
    profile_b: TargetProfile,
    workspace_id: str,
) -> EquivalenceReport:
    """Fetch one workspace from two orgs, mask what is meant to differ, compare the rest."""
    model_a = sdk_a.catalog_workspace.get_declarative_workspace(workspace_id=workspace_id)
    model_b = sdk_b.catalog_workspace.get_declarative_workspace(workspace_id=workspace_id)

    masked_a = mask_parameters(
        model_a,
        datasource_id=profile_a.datasource_id,
        datasource_schema=profile_a.datasource_schema,
    )
    masked_b = mask_parameters(
        model_b,
        datasource_id=profile_b.datasource_id,
        datasource_schema=profile_b.datasource_schema,
    )

    differences = dict_diff(masked_a, masked_b)
    return EquivalenceReport(
        target_a=profile_a.name,
        target_b=profile_b.name,
        workspace_id=workspace_id,
        digest_a=model_digest(model_a),
        digest_b=model_digest(model_b),
        equivalent=not differences,
        differing_paths=differences,
    )
