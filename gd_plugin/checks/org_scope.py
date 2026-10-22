"""org_scope — this repo never releases or snapshots org-level objects (ecommerce ADR 002, ADR 011).

Both orgs GlobalMart releases to are shared with other demos. gdcloud's org release makes the org
hold exactly what git holds for each released kind and deletes the rest, with no ownership
scoping, so one demo repo releasing agents would delete every other demo's. A separate org repo is
the only owner. This check keeps that true here: the two automation flags stay off, and no
``gd_organization*/`` tree appears.
"""

from __future__ import annotations

from pathlib import Path

import yaml

FLAGS = ("org_release", "organization_snapshot")
FORBIDDEN_DIRS = ("gd_organization", "gd_organization_snapshot")


def find_violations(root: Path) -> list[str]:
    """Every way the repo at ``root`` would release or record org-level objects."""
    config = yaml.safe_load((root / "config.yml").read_text()) or {}
    automation = config.get("automation") or {}
    violations = [
        f"config.yml automation.{flag}.enabled is true"
        for flag in FLAGS
        if (automation.get(flag) or {}).get("enabled") is True
    ]
    violations += [f"{name}/ exists" for name in FORBIDDEN_DIRS if (root / name).exists()]
    return violations


def run_check_for_data_product(data_product_id: str, check_all: bool, base_branch: str) -> int:
    from gdcloud.utils.config import get_project_root

    violations = find_violations(Path(get_project_root()))
    if not violations:
        print("org_scope: no org-level release or snapshot is configured.")
        return 0
    print("org_scope: this repo must not release org-level objects (ecommerce ADR 002):")
    for violation in violations:
        print(f"  - {violation}")
    print("Org-level objects (agents, themes, …) belong in the org repo, which alone releases them.")
    return 1
