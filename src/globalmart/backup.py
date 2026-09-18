"""Snapshot a target workspace before overwriting it.

``put_declarative_workspace`` has REPLACE semantics: it overwrites a workspace's entire
content in one call, and the layout it replaces exists nowhere else. ADR 002 requires a
backup immediately before that call.

Backups are written as the same YAML tree the repo uses, so a rollback is just
``globalmart publish parent --from backups/... --apply`` rather than a bespoke restore path.
They are gitignored: local artifacts, never committed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from gooddata_sdk import GoodDataSdk

from globalmart.capture import capture_workspace
from globalmart.config import TargetProfile
from globalmart.layout_io import write_tree


def backup_workspace(
    sdk: GoodDataSdk, profile: TargetProfile, workspace_id: str
) -> Path | None:
    """Write the target's current layout to a timestamped folder.

    Returns ``None`` when the workspace does not exist yet — a first publish has nothing to
    back up, which is reported rather than treated as a failure.
    """
    try:
        model = capture_workspace(sdk, workspace_id)
    except Exception:
        return None

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = Path(profile.backup_dir) / profile.name / workspace_id / stamp
    write_tree(model, destination)
    return destination
