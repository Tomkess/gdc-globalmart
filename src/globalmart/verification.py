"""Verify a published target along four axes, and decide whether goal-01 holds today.

goal-01 claims a clean clone plus credentials rebuilds the parent and all twelve children
"with every visualization executing successfully and no manual step". Four things have to be
true for that sentence to hold, and each is an axis here:

1. **Executions succeed** — every visualization actually computes against the warehouse.
2. **The right objects arrived** — live counts match what the repo's own artifacts say.
3. **The split lost nothing** — every parent dashboard and visualization reaches a child,
   and no child carries a dataset it cannot explain.
4. **The result is org-independent** — `equivalence.py`, run separately.

**The workspace set comes from the repo, never from the org.** Thirteen: the parent plus one
per domain in `domains.yaml`. Deriving it from `list_workspaces()` would let the harness pass
by verifying fewer workspaces than it should — a workspace the repo expects and the org lacks
is a failure, not an absence.

Named `verification.py` rather than `verify.py` because FEAT-004 owns `verify.py` for the
offline split gate. Two unrelated concerns, two modules (CONTRACT.md).
"""

from __future__ import annotations

import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from globalmart.classify import FailureCategory
from globalmart.config import GlobalmartError, TargetProfile
from globalmart.counts import ObjectCounts, count_objects
from globalmart.domains import DomainManifest
from globalmart.equivalence import EquivalenceReport
from globalmart.execute import (
    ExecStatus,
    ExecutionOptions,
    Throttle,
    ThrottleEvent,
    VizResult,
    execute_workspace,
)
from globalmart.expect import (
    CountMismatch,
    CoverageReport,
    PruningViolation,
    check_coverage,
    check_pruning,
    compare_counts,
)
from globalmart.layout_io import read_model_json, read_tree
from globalmart.preflight import check_wdf_values

SCHEMA_VERSION = 1

#: Above this share of EMPTY results, the warehouse is probably unloaded or the schema is
#: wrong — a workspace-level diagnosis rather than N per-object ones.
EMPTY_WARNING_RATIO = 0.5


class VerificationFailedError(GlobalmartError):
    """The run completed and something did not hold. Sets exit code 1."""


@dataclass
class WorkspaceVerification:
    workspace_id: str
    role: str
    domain_key: str | None = None
    present: bool = True
    wdf_warning: str | None = None
    counts_expected: ObjectCounts = field(default_factory=ObjectCounts)
    counts_actual: ObjectCounts = field(default_factory=ObjectCounts)
    count_mismatches: list[CountMismatch] = field(default_factory=list)
    viz_total: int = 0
    viz_ok: int = 0
    viz_empty: int = 0
    viz_broken: int = 0
    viz_skipped: int = 0
    #: Set when every failure shares one category — one systemic finding, not N defects.
    systemic_category: FailureCategory | None = None
    empty_ratio: float = 0.0
    throttle_events: list[ThrottleEvent] = field(default_factory=list)
    duration_s: float = 0.0
    visualizations: list[VizResult] = field(default_factory=list)

    def passed(self, *, fail_on_empty: bool = False) -> bool:
        if not self.present:
            return False
        if self.viz_broken or self.count_mismatches:
            return False
        return not (fail_on_empty and self.viz_empty)


@dataclass
class VerificationRun:
    schema_version: int = SCHEMA_VERSION
    generated_at: str = ""
    target: str = ""
    host: str = ""
    organization_id: str = ""
    repo_commit: str = "unknown"
    options: dict[str, Any] = field(default_factory=dict)
    workspaces: list[WorkspaceVerification] = field(default_factory=list)
    coverage: CoverageReport = field(default_factory=CoverageReport)
    pruning_violations: list[PruningViolation] = field(default_factory=list)
    equivalence: EquivalenceReport | None = None
    rebuild: Any | None = None
    total_viz: int = 0
    total_ok: int = 0
    total_empty: int = 0
    total_broken: int = 0
    total_skipped: int = 0
    duration_s: float = 0.0
    passed: bool = True
    failure_reasons: list[str] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        return [
            f"target            : {self.target} ({self.host}, org {self.organization_id})",
            f"workspaces        : {len(self.workspaces)}",
            f"visualizations    : {self.total_viz}",
            f"  ok              : {self.total_ok}",
            f"  empty           : {self.total_empty}",
            f"  broken          : {self.total_broken}",
            f"  skipped         : {self.total_skipped}",
            f"coverage          : {'ok' if self.coverage.passed else 'FAILED'}",
            f"pruning           : {len(self.pruning_violations)} violation(s)",
            f"passed            : {self.passed}",
        ]


def repo_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - provenance is nice to have, never required
        return "unknown"


@dataclass
class VerifyOptions:
    max_workers: int = 8
    viz_timeout: int = 180
    max_retries: int = 2
    fail_on_empty: bool = False
    list_only: bool = False
    layout_path: Path = Path("layouts/workspaces/globalmart")
    generated_path: Path = Path("generated/workspaces")
    workspaces: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_workers": self.max_workers,
            "viz_timeout": self.viz_timeout,
            "max_retries": self.max_retries,
            "fail_on_empty": self.fail_on_empty,
        }


def planned_workspaces(manifest: DomainManifest) -> list[tuple[str, str, str | None]]:
    """`(workspace_id, role, domain_key)` for the parent and every domain — 13 today."""
    plan: list[tuple[str, str, str | None]] = [(manifest.parent_workspace_id, "parent", None)]
    for key in manifest.keys():  # noqa: SIM118 - DomainManifest.keys() is a method
        plan.append((manifest.by_key(key).workspace_id, "domain", key))
    return plan


def _summarise(entry: WorkspaceVerification, results: list[VizResult]) -> None:
    entry.visualizations = results
    entry.viz_total = len(results)
    entry.viz_ok = sum(1 for r in results if r.status is ExecStatus.OK)
    entry.viz_empty = sum(1 for r in results if r.status is ExecStatus.EMPTY)
    entry.viz_broken = sum(1 for r in results if r.status is ExecStatus.BROKEN)
    entry.viz_skipped = sum(1 for r in results if r.status is ExecStatus.SKIPPED)
    entry.empty_ratio = entry.viz_empty / entry.viz_total if entry.viz_total else 0.0

    categories = {r.category for r in results if r.status is ExecStatus.BROKEN}
    if entry.viz_broken and len(categories) == 1:
        entry.systemic_category = next(iter(categories))


def verify_target(
    sdk: Any,
    profile: TargetProfile,
    manifest: DomainManifest,
    *,
    options: VerifyOptions | None = None,
) -> VerificationRun:
    """Run every read-only axis against a published target."""
    opts = options or VerifyOptions()
    started = time.monotonic()

    run = VerificationRun(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        target=profile.name,
        host=profile.host,
        organization_id=profile.organization_id,
        repo_commit=repo_commit(),
        options=opts.as_dict(),
    )

    parent_model = read_tree(opts.layout_path)
    plan = planned_workspaces(manifest)
    if opts.workspaces:
        plan = [entry for entry in plan if entry[0] in opts.workspaces]

    throttle = Throttle(opts.max_workers)
    exec_options = ExecutionOptions(
        max_workers=opts.max_workers,
        viz_timeout=opts.viz_timeout,
        max_retries=opts.max_retries,
    )

    children: dict[str, Any] = {}
    declared: dict[str, set[str]] = {}
    for key in manifest.keys():  # noqa: SIM118 - DomainManifest.keys() is a method
        domain = manifest.by_key(key)
        path = opts.generated_path / f"{domain.workspace_id}.json"
        if path.exists():
            children[domain.workspace_id] = read_model_json(path)
            declared[domain.workspace_id] = set(domain.ldm_include)

    with ThreadPoolExecutor(max_workers=max(opts.max_workers, 1)) as pool:
        for workspace_id, role, domain_key in plan:
            entry = WorkspaceVerification(
                workspace_id=workspace_id, role=role, domain_key=domain_key
            )
            workspace_started = time.monotonic()

            expected_model = (
                parent_model if role == "parent" else children.get(workspace_id)
            )
            if expected_model is not None:
                entry.counts_expected = count_objects(expected_model)

            try:
                live = sdk.catalog_workspace.get_declarative_workspace(workspace_id=workspace_id)
            except Exception:  # noqa: BLE001 - absence is the finding, not an error
                entry.present = False
                entry.duration_s = time.monotonic() - workspace_started
                run.workspaces.append(entry)
                continue

            entry.counts_actual = count_objects(live)
            if expected_model is not None:
                entry.count_mismatches = compare_counts(
                    workspace_id, entry.counts_expected, entry.counts_actual
                )

            # Before execution, so a workspace-wide 400 is one finding, not N.
            entry.wdf_warning = check_wdf_values(profile.host, profile.token, workspace_id)

            if not opts.list_only:
                results = execute_workspace(
                    sdk,
                    workspace_id,
                    options=exec_options,
                    throttle=throttle,
                    pool=pool,
                )
                _summarise(entry, results)

            entry.throttle_events = [
                event for event in throttle.events if event.workspace_id == workspace_id
            ]
            entry.duration_s = time.monotonic() - workspace_started
            run.workspaces.append(entry)

    if children:
        run.coverage = check_coverage(parent_model, children)
        run.pruning_violations = check_pruning(parent_model, children, declared=declared)

    run.total_viz = sum(entry.viz_total for entry in run.workspaces)
    run.total_ok = sum(entry.viz_ok for entry in run.workspaces)
    run.total_empty = sum(entry.viz_empty for entry in run.workspaces)
    run.total_broken = sum(entry.viz_broken for entry in run.workspaces)
    run.total_skipped = sum(entry.viz_skipped for entry in run.workspaces)
    run.duration_s = time.monotonic() - started

    run.failure_reasons = _failure_reasons(run, opts)
    run.passed = not run.failure_reasons
    return run


def _failure_reasons(run: VerificationRun, opts: VerifyOptions) -> list[str]:
    """One human sentence per reason the run failed. Empty iff it passed."""
    reasons: list[str] = []

    missing = [entry.workspace_id for entry in run.workspaces if not entry.present]
    if missing:
        reasons.append(
            f"{len(missing)} workspace(s) the repo expects are not in the org: "
            + ", ".join(missing)
        )

    broken = [entry for entry in run.workspaces if entry.viz_broken]
    if broken:
        reasons.append(
            f"{run.total_broken} visualization(s) failed to execute across "
            f"{len(broken)} workspace(s)"
        )

    mismatched = [entry for entry in run.workspaces if entry.count_mismatches]
    if mismatched:
        detail = "; ".join(
            str(mismatch) for entry in mismatched for mismatch in entry.count_mismatches[:3]
        )
        reasons.append(f"object counts differ from the repo: {detail}")

    if not run.coverage.passed:
        reasons.append(
            f"{len(run.coverage.missing_dashboard_ids)} dashboard(s) and "
            f"{len(run.coverage.missing_visualization_ids)} visualization(s) reach no child"
        )

    if run.pruning_violations:
        reasons.append(
            f"{len(run.pruning_violations)} pruning violation(s): "
            + "; ".join(str(v) for v in run.pruning_violations[:3])
        )

    if opts.fail_on_empty and run.total_empty:
        reasons.append(f"{run.total_empty} visualization(s) returned no rows (--fail-on-empty)")

    return reasons


def empty_warnings(run: VerificationRun) -> list[str]:
    """Workspaces mostly empty — the shape of an unloaded warehouse, not broken content."""
    return [
        f"{entry.workspace_id}: {entry.viz_empty}/{entry.viz_total} visualizations returned "
        "no rows — the warehouse is probably unloaded or the schema is wrong"
        for entry in run.workspaces
        if entry.viz_total and entry.empty_ratio > EMPTY_WARNING_RATIO
    ]
