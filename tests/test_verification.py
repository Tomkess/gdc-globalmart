"""Orchestration: the workspace set, the failure reasons, and what makes a run fail.

The assertion that matters most here is `test_the_workspace_set_comes_from_the_repo`. A
harness that asks the org what to verify can pass by verifying less than it should, and that
failure is invisible — the report looks clean, it is just shorter than it ought to be.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from globalmart.config import TargetProfile
from globalmart.domains import load_domains
from globalmart.verification import (
    VerifyOptions,
    empty_warnings,
    planned_workspaces,
    verify_target,
)

REPO = Path(__file__).resolve().parents[1]
LAYOUT = REPO / "layouts" / "workspaces" / "globalmart"
GENERATED = REPO / "generated" / "workspaces"
MANIFEST = REPO / "config" / "domains.yaml"

pytestmark = pytest.mark.skipif(
    not (LAYOUT.exists() and GENERATED.exists()), reason="artifacts not present"
)


@pytest.fixture(scope="module")
def manifest():  # type: ignore[no-untyped-def]
    return load_domains(MANIFEST)


def profile() -> TargetProfile:
    return TargetProfile(
        name="fake",
        host="https://example.invalid",
        token="tok",
        organization_id="org",
        datasource_id="ds",
        datasource_schema="globalmart",
    )


class Viz:
    def __init__(self, viz_id: str) -> None:
        self.id = viz_id
        self.title = viz_id


class VerifySdk:
    """Serves whatever layout it is given, and executes visualizations as scripted."""

    def __init__(self, layouts: dict[str, Any], behaviour: Any = None) -> None:
        outer = self
        self._layouts = layouts
        self._behaviour = behaviour

        class _Workspace:
            def get_declarative_workspace(self, workspace_id: str) -> Any:
                if workspace_id not in outer._layouts:
                    raise RuntimeError("404 not found")
                return outer._layouts[workspace_id]

        class _Viz:
            def get_visualizations(self, workspace_id: str) -> list[Viz]:
                model = outer._layouts.get(workspace_id)
                if model is None:
                    return []
                return [Viz(str(v.id)) for v in (model.analytics.visualization_objects or [])]

        class _Tables:
            def for_visualization(self, workspace_id: str, viz: Any, **kwargs: Any) -> Any:
                if outer._behaviour is not None:
                    return outer._behaviour(workspace_id, viz)
                return type("T", (), {"data": [[1, 2]]})()

        self.catalog_workspace = _Workspace()
        self.visualizations = _Viz()
        self.tables = _Tables()


@pytest.fixture(autouse=True)
def _no_wdf_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """The preflight reaches the network; it is exercised on its own in test_preflight."""
    import globalmart.verification as verification

    monkeypatch.setattr(verification, "check_wdf_values", lambda host, token, ws: None)


def _layouts(manifest) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    from globalmart.layout_io import read_model_json, read_tree

    layouts: dict[str, Any] = {manifest.parent_workspace_id: read_tree(LAYOUT)}
    for key in manifest.keys():  # noqa: SIM118 - DomainManifest.keys() is a method
        workspace_id = manifest.by_key(key).workspace_id
        layouts[workspace_id] = read_model_json(GENERATED / f"{workspace_id}.json")
    return layouts


def test_the_workspace_set_comes_from_the_repo(manifest) -> None:  # type: ignore[no-untyped-def]
    plan = planned_workspaces(manifest)

    assert len(plan) == 13
    assert plan[0] == ("globalmart", "parent", None)
    assert ("globalmart-store-ops", "domain", "store_ops") in plan


def test_a_workspace_the_org_lacks_is_a_failure_not_a_skip(manifest) -> None:  # type: ignore[no-untyped-def]
    layouts = _layouts(manifest)
    layouts.pop("globalmart-hr")
    sdk = VerifySdk(layouts)

    run = verify_target(
        sdk,
        profile(),
        manifest,
        options=VerifyOptions(
            layout_path=LAYOUT, generated_path=GENERATED, list_only=True, max_workers=2
        ),
    )

    missing = [w for w in run.workspaces if not w.present]
    assert [w.workspace_id for w in missing] == ["globalmart-hr"]
    assert not run.passed
    assert any("not in the org" in reason for reason in run.failure_reasons)


def test_a_clean_target_passes(manifest) -> None:  # type: ignore[no-untyped-def]
    sdk = VerifySdk(_layouts(manifest))

    run = verify_target(
        sdk,
        profile(),
        manifest,
        options=VerifyOptions(layout_path=LAYOUT, generated_path=GENERATED, max_workers=4),
    )

    assert run.passed, run.failure_reasons
    assert len(run.workspaces) == 13
    assert run.total_broken == 0
    assert run.total_viz > 0
    assert run.coverage.passed
    assert run.pruning_violations == []


def test_a_broken_visualization_fails_the_run(manifest) -> None:  # type: ignore[no-untyped-def]
    def behaviour(workspace_id: str, viz: Any) -> Any:
        if viz.id == "viz_risk_0324":
            raise RuntimeError("HTTP 400 general error while calculating")
        return type("T", (), {"data": [[1]]})()

    sdk = VerifySdk(_layouts(manifest), behaviour)
    run = verify_target(
        sdk,
        profile(),
        manifest,
        options=VerifyOptions(layout_path=LAYOUT, generated_path=GENERATED, max_workers=4),
    )

    assert not run.passed
    assert run.total_broken > 0
    assert any("failed to execute" in reason for reason in run.failure_reasons)


def test_empty_results_pass_by_default_and_fail_under_the_flag(manifest) -> None:  # type: ignore[no-untyped-def]
    def behaviour(workspace_id: str, viz: Any) -> Any:
        return type("T", (), {"data": []})()

    sdk = VerifySdk(_layouts(manifest), behaviour)
    options = dict(layout_path=LAYOUT, generated_path=GENERATED, max_workers=4)

    lenient = verify_target(sdk, profile(), manifest, options=VerifyOptions(**options))
    assert lenient.passed
    assert lenient.total_empty > 0
    assert lenient.total_ok == 0

    strict = verify_target(
        sdk, profile(), manifest, options=VerifyOptions(fail_on_empty=True, **options)
    )
    assert not strict.passed
    assert any("no rows" in reason for reason in strict.failure_reasons)


def test_a_mostly_empty_workspace_warns_about_the_warehouse(manifest) -> None:  # type: ignore[no-untyped-def]
    def behaviour(workspace_id: str, viz: Any) -> Any:
        return type("T", (), {"data": []})()

    sdk = VerifySdk(_layouts(manifest), behaviour)
    run = verify_target(
        sdk,
        profile(),
        manifest,
        options=VerifyOptions(layout_path=LAYOUT, generated_path=GENERATED, max_workers=4),
    )

    warnings = empty_warnings(run)
    assert warnings
    assert "warehouse is probably unloaded" in warnings[0]


def test_one_shared_cause_is_reported_as_one_finding(manifest) -> None:  # type: ignore[no-untyped-def]
    """384 defects that share a category are one configuration fault, not 384."""

    def behaviour(workspace_id: str, viz: Any) -> Any:
        raise RuntimeError("HTTP 400 the filter values are empty")

    sdk = VerifySdk(_layouts(manifest), behaviour)
    run = verify_target(
        sdk,
        profile(),
        manifest,
        options=VerifyOptions(
            layout_path=LAYOUT, generated_path=GENERATED, max_workers=4,
            workspaces=("globalmart-risk",),
        ),
    )

    (entry,) = run.workspaces
    assert entry.systemic_category is not None
    assert entry.systemic_category.value == "WDF_NO_VALUE"


def test_list_only_executes_nothing(manifest) -> None:  # type: ignore[no-untyped-def]
    def behaviour(workspace_id: str, viz: Any) -> Any:
        raise AssertionError("nothing should execute under --list-only")

    sdk = VerifySdk(_layouts(manifest), behaviour)
    run = verify_target(
        sdk,
        profile(),
        manifest,
        options=VerifyOptions(
            layout_path=LAYOUT, generated_path=GENERATED, list_only=True, max_workers=2
        ),
    )

    assert run.total_viz == 0
    assert run.passed


def test_a_count_mismatch_fails_the_run(manifest) -> None:  # type: ignore[no-untyped-def]
    """The org answering differently from the repo is the whole point of the comparison."""
    import copy

    layouts = _layouts(manifest)
    trimmed = copy.deepcopy(layouts["globalmart-risk"])
    trimmed.analytics.metrics = list(trimmed.analytics.metrics)[:-1]
    layouts["globalmart-risk"] = trimmed

    sdk = VerifySdk(layouts)
    run = verify_target(
        sdk,
        profile(),
        manifest,
        options=VerifyOptions(
            layout_path=LAYOUT, generated_path=GENERATED, list_only=True, max_workers=2
        ),
    )

    assert not run.passed
    assert any("counts differ" in reason for reason in run.failure_reasons)


def test_the_run_records_its_own_options(manifest) -> None:  # type: ignore[no-untyped-def]
    """A run has to be reproducible from its own output."""
    sdk = VerifySdk(_layouts(manifest))
    run = verify_target(
        sdk,
        profile(),
        manifest,
        options=VerifyOptions(
            layout_path=LAYOUT, generated_path=GENERATED, list_only=True,
            max_workers=3, viz_timeout=42, max_retries=1,
        ),
    )

    assert run.options == {
        "max_workers": 3,
        "viz_timeout": 42,
        "max_retries": 1,
        "fail_on_empty": False,
    }
    assert run.schema_version == 1
