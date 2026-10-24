"""GlobalMart's gdcloud CI checks, registered via the ``gdcloud.ci_checks`` entry point (FEAT-019).

``projection_current`` retired with ADR 011 Stage B: ``gd_data_product/globalmart/`` is authored
directly, so there is no projection left to compare against. ``org_scope`` does not read the
metadata DB, so it declares no ``requires_views``. ``run`` stays a string so
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
]
