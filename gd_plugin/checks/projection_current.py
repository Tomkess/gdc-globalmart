"""projection_current — gd_data_product/globalmart/ is exactly the projection of the parent layout.

``layouts/workspaces/globalmart/`` is the authoring surface (ADR 001, ADR 011 Stage A), and the
tree gdcloud releases is derived from it by ``globalmart gdcloud project``. A hand edit to the
derived tree, a ``gd-store`` into it (workflow 2a), or a layout change nobody re-projected would
each make the release diverge from the source of truth. ``ci.yml`` runs the same comparison as
``globalmart gdcloud project --check``; this puts it inside gd-ci, next to gdcloud's own gates.
"""

from __future__ import annotations

from pathlib import Path

LAYOUT = Path("layouts/workspaces/globalmart")


def find_problems(root: Path) -> list[str]:
    from globalmart.gdcloud_bridge import load_release_config
    from globalmart.gdcloud_project import diff_projection, project_parent

    config = load_release_config(root / "config.yml")
    projection = project_parent(config, root / LAYOUT)
    return diff_projection(projection, root / "gd_data_product")


def run_check_for_data_product(data_product_id: str, check_all: bool, base_branch: str) -> int:
    from gdcloud.utils.config import get_project_root

    problems = find_problems(Path(get_project_root()))
    if not problems:
        print(f"projection_current: gd_data_product/{data_product_id}/ matches {LAYOUT}.")
        return 0
    print(f"projection_current: gd_data_product/{data_product_id}/ differs from {LAYOUT}:")
    for problem in problems[:50]:
        print(f"  - {problem}")
    print("Edit the layout, then run `make project` and commit both. Never edit the projection.")
    return 1
