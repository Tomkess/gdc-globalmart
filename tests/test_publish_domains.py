"""Publishing the twelve children — a loop over FEAT-002's unchanged `publish_workspace`.

This feature adds no SDK call site, so what is worth testing here is the loop's behaviour:
which workspace ids it targets, which names it gives them, that `--apply` still gates every
write, and that a failure does not leave half an org rewritten.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from globalmart.config import GlobalmartError, load_profile
from globalmart.domains import load_domains
from globalmart.layout_io import read_tree
from globalmart.publish import publish_domains

from .conftest import FakeSdk

BASE = Path(__file__).parent / "fixtures" / "mini_domains"


@pytest.fixture(autouse=True)
def _token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD", "tok")
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "secret")


@pytest.fixture(scope="module")
def manifest():  # type: ignore[no-untyped-def]
    return load_domains(BASE / "domains.yaml")


@pytest.fixture(scope="module")
def models(manifest):  # type: ignore[no-untyped-def]
    from globalmart.closure import build_index
    from globalmart.split import split_domain

    model = read_tree(BASE / "mini_parent")
    index = build_index(model)
    return {
        key: split_domain(model, manifest.by_key(key), manifest, index=index)[0]
        for key in manifest.keys()  # noqa: SIM118 - DomainManifest.keys() is a method, not a mapping
    }


def test_rehearsal_writes_nothing(manifest, models) -> None:  # type: ignore[no-untyped-def]
    sdk = FakeSdk()
    results = publish_domains(sdk, manifest, load_profile("demo-cloud"), models=models)

    assert sdk.writes() == []
    assert len(results) == 2
    # A diff is still produced per child — ADR 002 applies per workspace.
    assert all(result.digest_after for result in results)


def test_apply_publishes_each_child_once(manifest, models) -> None:  # type: ignore[no-untyped-def]
    sdk = FakeSdk()
    publish_domains(sdk, manifest, load_profile("demo-cloud"), models=models, apply=True)

    puts = [args["id"] for name, args in sdk.calls if name == "put_declarative_workspace"]
    assert sorted(puts) == ["globalmart-hr", "globalmart-sales"]


def test_workspace_names_come_from_the_manifest(manifest, models) -> None:  # type: ignore[no-untyped-def]
    """Asserted against the manifest helper, never against a string built here."""
    sdk = FakeSdk()
    publish_domains(sdk, manifest, load_profile("demo-cloud"), models=models, apply=True)

    names = {args["id"]: args["name"] for name, args in sdk.calls if name == "create_or_update"}
    assert names["globalmart-sales"] == manifest.resolve_workspace_name(manifest.by_key("sales"))
    assert names["globalmart-sales"] == "GlobalMart — Sales"
    # The per-domain override, which the template must not overrule.
    assert names["globalmart-hr"] == "GlobalMart People (pilot)"


def test_the_workspace_id_prefix_applies_to_children(manifest, models, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    profile = load_profile("demo-cloud")
    prefixed = type(profile)(**{**profile.__dict__, "workspace_id_prefix": "ab-"})

    sdk = FakeSdk()
    publish_domains(sdk, manifest, prefixed, models=models, apply=True)

    puts = [args["id"] for name, args in sdk.calls if name == "put_declarative_workspace"]
    assert sorted(puts) == ["ab-globalmart-hr", "ab-globalmart-sales"]


def test_only_publishes_a_subset(manifest, models) -> None:  # type: ignore[no-untyped-def]
    sdk = FakeSdk()
    publish_domains(
        sdk, manifest, load_profile("demo-cloud"), models=models, only={"hr"}, apply=True
    )

    puts = [args["id"] for name, args in sdk.calls if name == "put_declarative_workspace"]
    assert puts == ["globalmart-hr"]


def test_a_missing_generated_model_fails_clearly(manifest, models) -> None:  # type: ignore[no-untyped-def]
    sdk = FakeSdk()
    with pytest.raises(GlobalmartError, match="globalmart split"):
        publish_domains(sdk, manifest, load_profile("demo-cloud"), models={"hr": models["hr"]})


def test_a_failure_stops_the_loop_and_names_what_was_not_attempted(manifest, models) -> None:  # type: ignore[no-untyped-def]
    """Twelve workspaces replaced against a misconfigured target is twelve restores."""
    sdk = FakeSdk(organization_id="some-other-org")

    with pytest.raises(GlobalmartError) as excinfo:
        publish_domains(sdk, manifest, load_profile("demo-cloud"), models=models, apply=True)

    assert "not attempted" in str(excinfo.value)
    assert sdk.writes() == []


def test_keep_going_continues_and_still_fails(manifest, models) -> None:  # type: ignore[no-untyped-def]
    sdk = FakeSdk(organization_id="some-other-org")

    with pytest.raises(GlobalmartError) as excinfo:
        publish_domains(
            sdk,
            manifest,
            load_profile("demo-cloud"),
            models=models,
            apply=True,
            keep_going=True,
        )

    assert "2 domain(s) failed" in str(excinfo.value)


def test_second_publish_is_idempotent(manifest, models) -> None:  # type: ignore[no-untyped-def]
    """The FakeSdk serves back what it was given, so `changed` must go False."""
    profile = load_profile("demo-cloud")

    for key in manifest.keys():  # noqa: SIM118 - DomainManifest.keys() is a method, not a mapping
        sdk = FakeSdk()
        one = {key: models[key]}
        first = publish_domains(sdk, manifest, profile, models=one, only={key}, apply=True)
        second = publish_domains(sdk, manifest, profile, models=one, only={key}, apply=True)

        assert first[0].changed is True
        assert second[0].changed is False
