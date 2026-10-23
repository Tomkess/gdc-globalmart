"""GlobalMart's gdcloud CI checks, registered via the ``gdcloud.ci_checks`` entry point (FEAT-019).

Neither reads the metadata DB, so neither declares ``requires_views``. ``run`` stays a string so
gdcloud imports a check module only when something runs it.
"""

from gdcloud.ci_checks.registry import CheckSpec

CHECKS = [
    CheckSpec(
        name="org_scope",
        description="Org-level objects are never released or snapshotted from this repo",
        run="gd_plugin.checks.org_scope:run_check_for_data_product",
        all_dps=True,
        once=True,
        order=1,
        source="gd_plugin",
    ),
    CheckSpec(
        name="projection_current",
        description="gd_data_product/globalmart/ is exactly the projection of the parent layout",
        run="gd_plugin.checks.projection_current:run_check_for_data_product",
        order=2,
        source="gd_plugin",
    ),
]
