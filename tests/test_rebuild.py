"""The cold-rebuild chain: step order, the empty-org probe, and short-circuiting.

The probe is the assertion that carries the weight. A cold rebuild that only ever runs
against an already-populated org proves nothing about a cold start, so claiming one over a
warm org has to be impossible by default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from globalmart.config import TargetProfile
from globalmart.domains import load_domains
from globalmart.rebuild import (
    RebuildAbortedError,
    RebuildOptions,
    StepStatus,
    cold_rebuild,
    probe_empty_org,
    step_runner,
)

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "config" / "domains.yaml"

pytestmark = pytest.mark.skipif(not MANIFEST.exists(), reason="manifest not present")


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


class Workspace:
    def __init__(self, workspace_id: str) -> None:
        self.id = workspace_id


class ProbeSdk:
    def __init__(self, existing: list[str] | None = None, *, raises: bool = False) -> None:
        outer = self
        self._existing = existing or []
        self._raises = raises

        class _Workspace:
            def list_workspaces(self) -> list[Workspace]:
                if outer._raises:
                    raise RuntimeError("no permission to list")
                return [Workspace(w) for w in outer._existing]

        self.catalog_workspace = _Workspace()


# --- the probe ----------------------------------------------------------------


def test_an_org_with_none_of_our_workspaces_is_empty(manifest) -> None:  # type: ignore[no-untyped-def]
    assert probe_empty_org(ProbeSdk(["someone-elses-workspace"]), profile(), manifest)


def test_an_org_holding_the_parent_is_not_empty(manifest) -> None:  # type: ignore[no-untyped-def]
    assert not probe_empty_org(ProbeSdk(["globalmart"]), profile(), manifest)


def test_an_org_holding_one_child_is_not_empty(manifest) -> None:  # type: ignore[no-untyped-def]
    assert not probe_empty_org(ProbeSdk(["globalmart-sales"]), profile(), manifest)


def test_an_unreadable_list_is_not_treated_as_empty(manifest) -> None:  # type: ignore[no-untyped-def]
    """Not knowing is not the same as knowing it is empty."""
    assert not probe_empty_org(ProbeSdk(raises=True), profile(), manifest)


# --- the gate -----------------------------------------------------------------


def test_a_warm_org_aborts_rather_than_claiming_a_cold_rebuild(manifest) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(RebuildAbortedError, match="cold rebuild"):
        cold_rebuild(ProbeSdk(["globalmart"]), profile(), manifest, apply=False)


def test_allow_existing_permits_it_but_records_the_truth(manifest) -> None:  # type: ignore[no-untyped-def]
    report = cold_rebuild(
        ProbeSdk(["globalmart"]),
        profile(),
        manifest,
        apply=False,
        options=RebuildOptions(allow_existing=True),
    )

    assert report.started_from_empty_org is False
    assert report.allow_existing is True


# --- the plan -----------------------------------------------------------------


def test_a_rehearsal_plans_every_step_and_runs_none(manifest) -> None:  # type: ignore[no-untyped-def]
    report = cold_rebuild(ProbeSdk([]), profile(), manifest, apply=False)

    names = [step.name for step in report.steps]
    assert names == [
        "probe-org",
        "verify-data",
        "load-warehouse",
        "publish-parent",
        "split",
        "publish-domains",
        "verify",
    ]
    # Only the probe actually ran; everything else is planned.
    assert [s.status for s in report.steps[1:]] == [StepStatus.PLANNED] * 6


def test_every_step_carries_the_command_that_reproduces_it(manifest) -> None:  # type: ignore[no-untyped-def]
    """"The script did it" is a poor answer when one step fails."""
    report = cold_rebuild(ProbeSdk([]), profile(), manifest, apply=False)

    for step in report.steps:
        assert step.cli_equivalent.startswith("globalmart ")
    publish = next(s for s in report.steps if s.name == "publish-domains")
    assert "--apply" in publish.cli_equivalent


def test_skip_data_drops_the_two_data_steps(manifest) -> None:  # type: ignore[no-untyped-def]
    report = cold_rebuild(
        ProbeSdk([]), profile(), manifest, apply=False, options=RebuildOptions(skip_data=True)
    )

    names = [step.name for step in report.steps]
    assert "load-warehouse" not in names
    assert "publish-parent" in names


def test_every_planned_step_has_a_runner(manifest) -> None:  # type: ignore[no-untyped-def]
    """A planned step with no runner would be silently skipped under --apply."""
    report = cold_rebuild(ProbeSdk([]), profile(), manifest, apply=False)

    for step in report.steps:
        if step.name == "probe-org":
            continue
        assert callable(step_runner(step.name))


def test_an_unknown_step_name_raises() -> None:
    with pytest.raises(RebuildAbortedError, match="no runner"):
        step_runner("step-that-does-not-exist")


# --- execution ----------------------------------------------------------------


def test_a_failing_step_stops_the_chain(manifest, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    """The rest must not run against a half-built target."""
    import globalmart.rebuild as rebuild_module

    calls: list[str] = []

    def runner_for(name: str) -> Any:
        def run(sdk: Any, profile_: Any, manifest_: Any, opts: Any) -> str:
            calls.append(name)
            if name == "load-warehouse":
                raise RuntimeError("warehouse unreachable")
            return "ok"

        return run

    monkeypatch.setattr(rebuild_module, "step_runner", runner_for)

    with pytest.raises(RebuildAbortedError, match="load-warehouse"):
        cold_rebuild(ProbeSdk([]), profile(), manifest, apply=True)

    assert calls == ["verify-data", "load-warehouse"]


def test_a_successful_chain_runs_every_step_in_order(
    manifest, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    import globalmart.rebuild as rebuild_module

    calls: list[str] = []

    def runner_for(name: str) -> Any:
        def run(sdk: Any, profile_: Any, manifest_: Any, opts: Any) -> str:
            calls.append(name)
            return f"{name} detail"

        return run

    monkeypatch.setattr(rebuild_module, "step_runner", runner_for)

    report = cold_rebuild(ProbeSdk([]), profile(), manifest, apply=True)

    assert calls == [
        "verify-data",
        "load-warehouse",
        "publish-parent",
        "split",
        "publish-domains",
        "verify",
    ]
    assert report.passed
    assert all(step.status is StepStatus.OK for step in report.steps)
    assert all(step.detail for step in report.steps)
