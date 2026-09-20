"""Both output formats, and the property that makes them worth having.

The JSON and the Markdown are two renderings of one object, not two code paths — so a stored
run re-renders its own report months later with no host involved. That round trip is the
central assertion here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from globalmart.classify import FailureCategory
from globalmart.execute import ExecStatus, VizResult
from globalmart.expect import CountMismatch, CoverageReport, PruningViolation
from globalmart.report import LIMITS, load_run, render_json, render_markdown, write_reports
from globalmart.verification import VerificationRun, WorkspaceVerification


def a_run(*, passed: bool = True) -> VerificationRun:
    broken = VizResult(
        workspace_id="globalmart-sales",
        viz_id="viz_sales_0001",
        title="Revenue by Month",
        status=ExecStatus.BROKEN,
        error="HTTP 400: general error while calculating the result",
        http_status=400,
        category=FailureCategory.CALC_ERROR,
        hint="Check the data source permissions.",
        attempts=2,
    )
    ok = VizResult(
        workspace_id="globalmart-sales",
        viz_id="viz_sales_0002",
        title="Orders",
        status=ExecStatus.OK,
        row_count=42,
    )
    empty = VizResult(
        workspace_id="globalmart-sales",
        viz_id="viz_sales_0003",
        title="Returns",
        status=ExecStatus.EMPTY,
        row_count=0,
        category=FailureCategory.EMPTY_RESULT,
    )
    skipped = VizResult(
        workspace_id="globalmart-sales",
        viz_id="viz_sales_0004",
        title="A table",
        status=ExecStatus.SKIPPED,
        category=FailureCategory.UNSUPPORTED_TYPE,
    )

    workspace = WorkspaceVerification(
        workspace_id="globalmart-sales",
        role="domain",
        domain_key="sales",
        viz_total=4,
        viz_ok=1,
        viz_empty=1,
        viz_broken=1 if not passed else 0,
        viz_skipped=1,
        visualizations=[broken, ok, empty, skipped] if not passed else [ok, empty, skipped],
        count_mismatches=(
            [CountMismatch("globalmart-sales", "metrics", 10, 9)] if not passed else []
        ),
    )

    return VerificationRun(
        generated_at="2026-09-18T12:00:00+00:00",
        target="demo-cloud",
        host="https://example.invalid",
        organization_id="org",
        repo_commit="abc123",
        options={"max_workers": 8, "viz_timeout": 180, "max_retries": 2, "fail_on_empty": False},
        workspaces=[workspace],
        coverage=CoverageReport(
            parent_dashboards=32,
            parent_visualizations=384,
            covered_dashboards=32,
            covered_visualizations=384,
            passed=True,
        ),
        pruning_violations=[] if passed else [PruningViolation("globalmart-sales", "dim_x", "unreachable")],
        total_viz=4,
        total_ok=1,
        total_empty=1,
        total_broken=0 if passed else 1,
        total_skipped=1,
        duration_s=12.5,
        passed=passed,
        failure_reasons=[] if passed else ["1 visualization(s) failed to execute"],
    )


def test_json_puts_the_schema_version_first() -> None:
    payload = render_json(a_run())
    assert next(iter(payload)) == "schema_version"
    assert payload["schema_version"] == 1


def test_json_is_serialisable_with_enums_flattened() -> None:
    """A dataclass holding StrEnums must survive json.dumps without a custom encoder."""
    payload = render_json(a_run(passed=False))
    text = json.dumps(payload)

    assert "CALC_ERROR" in text
    assert "BROKEN" in text


def test_markdown_leads_with_the_verdict() -> None:
    assert render_markdown(a_run()).startswith("# GlobalMart verification — PASSED")
    assert render_markdown(a_run(passed=False)).startswith("# GlobalMart verification — FAILED")


def test_every_report_states_what_it_cannot_prove() -> None:
    """The limits belong where the numbers are, not only in a spec nobody opens."""
    markdown = render_markdown(a_run())

    assert LIMITS in markdown
    assert "proves execution, never semantics" in markdown


def test_a_failing_run_leads_with_why() -> None:
    markdown = render_markdown(a_run(passed=False))
    why_index = markdown.index("## Why this run failed")
    workspaces_index = markdown.index("## Workspaces")

    assert why_index < workspaces_index


def test_a_broken_visualization_is_reported_in_full() -> None:
    markdown = render_markdown(a_run(passed=False))

    assert "viz_sales_0001" in markdown
    assert "Revenue by Month" in markdown
    assert "CALC_ERROR" in markdown
    assert "general error while calculating" in markdown  # verbatim, not summarised
    assert "attempts: 2" in markdown
    assert "Check the data source permissions." in markdown


def test_empty_and_skipped_are_listed_separately_from_ok() -> None:
    markdown = render_markdown(a_run(passed=False))

    assert "#### Empty (1)" in markdown
    assert "#### Skipped (1)" in markdown


def test_a_clean_workspace_gets_no_detail_section() -> None:
    """A report whose first screen is 380 passes is one nobody reads to the end."""
    markdown = render_markdown(a_run())

    assert "#### Broken" not in markdown


def test_the_round_trip_regenerates_the_same_markdown(tmp_path: Path) -> None:
    """The reason to store JSON: re-render an old run with no host."""
    run = a_run(passed=False)
    json_path, markdown_path = write_reports(run, tmp_path)

    reloaded = load_run(json_path)
    assert render_markdown(reloaded) == markdown_path.read_text(encoding="utf-8")


def test_write_reports_creates_both_files(tmp_path: Path) -> None:
    json_path, markdown_path = write_reports(a_run(), tmp_path / "nested")

    assert json_path.name == "verification_result.json"
    assert markdown_path.name == "verification_report.md"
    assert json.loads(json_path.read_text(encoding="utf-8"))["passed"] is True


def test_an_unknown_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        load_run(path)


def test_pruning_violations_appear_in_the_report() -> None:
    markdown = render_markdown(a_run(passed=False))

    assert "dim_x" in markdown
    assert "unreachable" in markdown
