"""The two output formats, and the only module that knows about presentation.

`verification_result.json` is the CI gate and the historical record; `verification_report.md`
is what a person reads. They are two renderings of one object rather than two code paths, so
a stored JSON re-renders its own Markdown months later with no host involved.

**Broken first.** The predecessor's shape, kept because it is right: a report whose first
screen is 380 passing visualizations is a report nobody reads to the end.

**The limits are printed in every report.** A harness that proves executions succeed but
cannot judge the numbers they return has to say so where the numbers are, not only in a spec
nobody opens.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from globalmart.execute import ExecStatus
from globalmart.verification import VerificationRun, empty_warnings

LIMITS = """\
**What this report cannot tell you.** A visualization that computes and returns *wrong
numbers* passes here — the harness proves execution, never semantics. Empty results are
surfaced but not judged. Dashboard rendering, drills and filter contexts are never exercised,
so a dashboard can be green here and broken on screen. AI context is counted, never
behaviourally tested.\
"""


def _plain(value: Any) -> Any:
    """`asdict` with enums flattened, so the JSON is stable and re-loadable."""
    if is_dataclass(value) and not isinstance(value, type):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def render_json(run: VerificationRun) -> dict[str, Any]:
    payload = _plain(run)
    # schema_version first, so a future reader can dispatch on it before parsing the rest.
    return {"schema_version": run.schema_version, **payload}


def load_run(path: Path) -> dict[str, Any]:
    """Re-hydrate a stored run as plain data.

    Deliberately a dict rather than a `VerificationRun`: the reason to load an old run is to
    re-render it, and reconstructing dataclasses would fail the moment the schema moved —
    which is exactly when reading the old report matters most.
    """
    payload: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    version = payload.get("schema_version")
    if version != 1:
        raise ValueError(f"{path}: unsupported schema_version {version!r}")
    return payload


def render_markdown(run: VerificationRun | dict[str, Any]) -> str:
    """The human report. Accepts a live run or a loaded JSON payload."""
    data = render_json(run) if isinstance(run, VerificationRun) else run

    lines: list[str] = []
    verdict = "PASSED" if data["passed"] else "FAILED"
    lines.append(f"# GlobalMart verification — {verdict}")
    lines.append("")
    lines.append(f"- target: `{data['target']}`")
    lines.append(f"- host: `{data['host']}` (org `{data['organization_id']}`)")
    lines.append(f"- commit: `{data['repo_commit']}`")
    lines.append(f"- generated: {data['generated_at']}")
    lines.append(f"- duration: {data['duration_s']:.1f}s")
    lines.append("")
    lines.append(LIMITS)
    lines.append("")

    if data["failure_reasons"]:
        lines.append("## Why this run failed")
        lines.append("")
        lines.extend(f"{index}. {reason}" for index, reason in enumerate(data["failure_reasons"], 1))
        lines.append("")

    warnings = empty_warnings(run) if isinstance(run, VerificationRun) else []
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")

    lines.append("## Workspaces")
    lines.append("")
    lines.append("| workspace | role | present | viz | ok | empty | broken | skipped | counts |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---|")
    for entry in data["workspaces"]:
        counts = "ok" if not entry["count_mismatches"] else f"{len(entry['count_mismatches'])} off"
        lines.append(
            f"| `{entry['workspace_id']}` | {entry['role']} | {'yes' if entry['present'] else 'NO'} "
            f"| {entry['viz_total']} | {entry['viz_ok']} | {entry['viz_empty']} "
            f"| {entry['viz_broken']} | {entry['viz_skipped']} | {counts} |"
        )
    lines.append("")

    lines.append("## Coverage and pruning")
    lines.append("")
    coverage = data["coverage"]
    lines.append(
        f"- dashboards covered: {coverage['covered_dashboards']}/{coverage['parent_dashboards']}"
    )
    lines.append(
        f"- visualizations covered: {coverage['covered_visualizations']}"
        f"/{coverage['parent_visualizations']}"
    )
    if coverage["missing_dashboard_ids"]:
        lines.append(f"- **missing dashboards**: {', '.join(coverage['missing_dashboard_ids'])}")
    if coverage["missing_visualization_ids"]:
        listed = ", ".join(coverage["missing_visualization_ids"][:20])
        lines.append(f"- **missing visualizations**: {listed}")
    lines.append(f"- pruning violations: {len(data['pruning_violations'])}")
    for violation in data["pruning_violations"][:20]:
        lines.append(
            f"  - `{violation['workspace_id']}` {violation['dataset_id']} "
            f"({violation['reason']})"
        )
    lines.append("")

    for entry in data["workspaces"]:
        broken = [v for v in entry["visualizations"] if v["status"] == ExecStatus.BROKEN.value]
        empty = [v for v in entry["visualizations"] if v["status"] == ExecStatus.EMPTY.value]
        skipped = [v for v in entry["visualizations"] if v["status"] == ExecStatus.SKIPPED.value]

        if not (broken or empty or skipped or entry["wdf_warning"] or entry["count_mismatches"]):
            continue

        lines.append(f"### `{entry['workspace_id']}`")
        lines.append("")

        if entry["wdf_warning"]:
            lines.append(f"> **Workspace-level:** {entry['wdf_warning']}")
            lines.append("")

        if entry["systemic_category"]:
            lines.append(
                f"> **Systemic:** every failure in this workspace is "
                f"`{entry['systemic_category']}` — one cause, not {entry['viz_broken']} defects."
            )
            lines.append("")

        for mismatch in entry["count_mismatches"]:
            lines.append(
                f"- count mismatch: **{mismatch['object_type']}** — repo says "
                f"{mismatch['expected']}, org reports {mismatch['actual']}"
            )
        if entry["count_mismatches"]:
            lines.append("")

        if broken:
            lines.append(f"#### Broken ({len(broken)})")
            lines.append("")
            for result in broken:
                lines.append(f"- **`{result['viz_id']}`** — {result['title']}")
                lines.append(
                    f"  - category: `{result['category']}` · HTTP "
                    f"{result['http_status'] or '—'} · attempts: {result['attempts']}"
                )
                if result["hint"]:
                    lines.append(f"  - hint: {result['hint']}")
                if result["error"]:
                    lines.append("  - error:")
                    lines.append("    ```")
                    lines.extend(f"    {line}" for line in str(result["error"]).splitlines())
                    lines.append("    ```")
            lines.append("")

        if empty:
            lines.append(f"#### Empty ({len(empty)})")
            lines.append("")
            lines.append(", ".join(f"`{result['viz_id']}`" for result in empty[:50]))
            lines.append("")

        if skipped:
            lines.append(f"#### Skipped ({len(skipped)})")
            lines.append("")
            for result in skipped:
                lines.append(f"- `{result['viz_id']}` — {result['category']}")
            lines.append("")

    if data.get("equivalence"):
        equivalence = data["equivalence"]
        lines.append("## Cross-org equivalence")
        lines.append("")
        lines.append(
            f"- `{equivalence['target_a']}` vs `{equivalence['target_b']}` on "
            f"`{equivalence['workspace_id']}`: "
            f"{'equivalent' if equivalence['equivalent'] else 'DIFFERENT'}"
        )
        for path in equivalence["differing_paths"][:20]:
            lines.append(f"  - {path}")
        lines.append("")

    if data.get("rebuild"):
        rebuild = data["rebuild"]
        lines.append("## Rebuild")
        lines.append("")
        lines.append(f"- started from an empty org: {rebuild['started_from_empty_org']}")
        lines.append("")
        lines.append("| step | status | duration | detail |")
        lines.append("|---|---|---:|---|")
        for step in rebuild["steps"]:
            lines.append(
                f"| `{step['name']}` | {step['status']} | {step['duration_s']:.1f}s "
                f"| {step['detail'] or step['error'] or ''} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


def write_reports(run: VerificationRun, output_dir: Path) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "verification_result.json"
    json_path.write_text(
        json.dumps(render_json(run), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    markdown_path = output_dir / "verification_report.md"
    markdown_path.write_text(render_markdown(run), encoding="utf-8")

    return json_path, markdown_path
