"""Tasks 6, 7 — the manifest schema, its strict loader and its canonical dumper.

Nothing here reads a layout tree. ``load_domains`` is deliberately parent-blind: it validates
everything checkable from the file alone, and existence of the ids it names is
``check_coverage``'s job. Keeping that split is what lets these tests stay pure.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from globalmart.domains import (
    AiSelection,
    DomainManifestError,
    dump_domains,
    load_domains,
)

FIXTURES = Path(__file__).parent / "fixtures" / "domains"


def _mutate(tmp_path: Path, source: Path, change) -> Path:  # type: ignore[no-untyped-def]
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    change(document)
    destination = tmp_path / "mutated.yaml"
    destination.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return destination


def test_loads_every_schema_key() -> None:
    manifest = load_domains(FIXTURES / "templates.yaml")

    assert manifest.version == 1
    assert manifest.parent_workspace_id == "globalmart"
    assert manifest.keys() == ("sales", "store_ops")

    sales = manifest.by_key("sales")
    assert isinstance(sales.dashboards, tuple)
    assert sales.dashboards == ("dashboard_000",)
    assert sales.ai == AiSelection(
        memory_item_ids=("mem_sales_definitions",),
        memory_item_tags=("area/sales",),
        parameter_ids=("param_sales_fiscal_year_start",),
        agent_ids=("agent_sales_analyst",),
        knowledge_ids=("know_sales_playbook",),
    )

    store_ops = manifest.by_key("store_ops")
    assert store_ops.ldm_include == ("dim_geo", "dim_store")
    assert sales.ldm_include == ()


def test_store_ops_maps_to_kebab_workspace_id() -> None:
    """The snake/kebab split is the one place the naming convention can silently break."""
    manifest = load_domains(FIXTURES / "templates.yaml")
    assert manifest.by_key("store_ops").workspace_id == "globalmart-store-ops"


def test_workspace_name_comes_from_the_template_and_can_be_overridden() -> None:
    manifest = load_domains(FIXTURES / "templates.yaml")

    # The exact string FEAT-002's --workspace-name expects for a child.
    assert manifest.resolve_workspace_name(manifest.by_key("sales")) == "GlobalMart — Sales"
    assert (
        manifest.resolve_workspace_name(manifest.by_key("store_ops"))
        == "GlobalMart Store Ops (pilot)"
    )


def test_accessors() -> None:
    manifest = load_domains(FIXTURES / "templates.yaml")

    assert manifest.by_key("sales").label == "Sales"
    assert manifest.keys() == tuple(sorted(manifest.keys()))
    assert manifest.unassigned_ids() == frozenset(
        {"dashboard_eval_scratch", "viz_orphan_0001", "mem_org_onboarding_notes"}
    )
    assert isinstance(manifest.unassigned_ids(), frozenset)


def test_by_key_names_the_missing_key() -> None:
    manifest = load_domains(FIXTURES / "templates.yaml")
    with pytest.raises(DomainManifestError, match="nope"):
        manifest.by_key("nope")


def test_round_trip_is_byte_stable(tmp_path: Path) -> None:
    manifest = load_domains(FIXTURES / "templates.yaml")

    first = dump_domains(manifest, tmp_path / "a.yaml")
    second = dump_domains(load_domains(first), tmp_path / "b.yaml")

    assert first.read_bytes() == second.read_bytes()
    reloaded = load_domains(second)
    assert reloaded.domains == manifest.domains
    assert reloaded.shared == manifest.shared
    assert reloaded.unassigned == manifest.unassigned


def test_unknown_key_names_the_key_and_its_path() -> None:
    with pytest.raises(DomainManifestError) as excinfo:
        load_domains(FIXTURES / "unknown_key.yaml")

    message = str(excinfo.value)
    assert "dashboard" in message
    assert "domains[0]" in message


def test_unsupported_version_raises(tmp_path: Path) -> None:
    """A future v2 will mean something; guessing what is worse than refusing."""

    def change(document: dict) -> None:  # type: ignore[type-arg]
        document["version"] = 2

    path = _mutate(tmp_path, FIXTURES / "templates.yaml", change)
    with pytest.raises(DomainManifestError, match="version"):
        load_domains(path)


@pytest.mark.parametrize("attribute", ["key", "label", "workspace_id"])
def test_duplicate_domain_attributes_raise(tmp_path: Path, attribute: str) -> None:
    def change(document: dict) -> None:  # type: ignore[type-arg]
        first, second = document["domains"]
        second[attribute] = first[attribute]
        if attribute == "key":
            # keep workspace_id consistent with the template so the duplicate key is what fails
            second["workspace_id"] = first["workspace_id"]
            second["label"] = first["label"]

    path = _mutate(tmp_path, FIXTURES / "templates.yaml", change)
    with pytest.raises(DomainManifestError):
        load_domains(path)


def test_child_may_not_be_the_parent(tmp_path: Path) -> None:
    def change(document: dict) -> None:  # type: ignore[type-arg]
        document["domains"][0]["workspace_id"] = "globalmart"

    path = _mutate(tmp_path, FIXTURES / "templates.yaml", change)
    with pytest.raises(DomainManifestError, match="parent workspace"):
        load_domains(path)


def test_workspace_id_must_match_the_template(tmp_path: Path) -> None:
    def change(document: dict) -> None:  # type: ignore[type-arg]
        document["domains"][0]["workspace_id"] = "globalmart-selling"

    path = _mutate(tmp_path, FIXTURES / "templates.yaml", change)
    with pytest.raises(DomainManifestError, match="workspace_id_template"):
        load_domains(path)


def test_a_domain_needs_at_least_one_object(tmp_path: Path) -> None:
    """ldm_include is headroom, not membership — it must not satisfy this rule."""

    def change(document: dict) -> None:  # type: ignore[type-arg]
        domain = document["domains"][1]
        domain["dashboards"] = []
        domain["visualizations"] = []
        domain["ldm_include"] = ["dim_store"]

    path = _mutate(tmp_path, FIXTURES / "templates.yaml", change)
    with pytest.raises(DomainManifestError, match="ldm_include does not count"):
        load_domains(path)


def test_an_exclusion_without_a_reason_raises(tmp_path: Path) -> None:
    def change(document: dict) -> None:  # type: ignore[type-arg]
        document["unassigned"]["visualizations"][0].pop("reason")

    path = _mutate(tmp_path, FIXTURES / "templates.yaml", change)
    with pytest.raises(DomainManifestError, match="justified in words"):
        load_domains(path)


def test_duplicate_ids_within_one_list_raise(tmp_path: Path) -> None:
    def change(document: dict) -> None:  # type: ignore[type-arg]
        document["domains"][0]["dashboards"] = ["dashboard_000", "dashboard_000"]

    path = _mutate(tmp_path, FIXTURES / "templates.yaml", change)
    with pytest.raises(DomainManifestError, match="duplicate"):
        load_domains(path)


def test_missing_manifest_names_the_path(tmp_path: Path) -> None:
    with pytest.raises(DomainManifestError, match="No domain manifest"):
        load_domains(tmp_path / "nothing.yaml")
