"""End-to-end split against the mini fixture, plus the assertions on the real 12 children.

The numbers in this module are hand-computable from `tests/fixtures/mini_domains/` and are
regression pins: an over-broad closure change makes them fail rather than quietly producing
children that look like the parent again.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from globalmart.closure import MetricPolicy
from globalmart.domains import load_domains
from globalmart.layout_io import read_model_json, read_tree
from globalmart.split import SplitCoverageError, SplitFailedError, split_all

BASE = Path(__file__).parent / "fixtures" / "mini_domains"
REPO = Path(__file__).resolve().parents[1]
GENERATED = REPO / "generated" / "workspaces"


@pytest.fixture(scope="module")
def model():  # type: ignore[no-untyped-def]
    return read_tree(BASE / "mini_parent")


@pytest.fixture(scope="module")
def manifest():  # type: ignore[no-untyped-def]
    return load_domains(BASE / "domains.yaml")


@pytest.fixture(scope="module")
def result(model, manifest):  # type: ignore[no-untyped-def]
    return split_all(model, manifest, write=False)


def by_key(result, key):  # type: ignore[no-untyped-def]
    return next(d for d in result.domains if d.domain_key == key)


# --- narrowing ----------------------------------------------------------------


def test_one_child_per_domain(result) -> None:  # type: ignore[no-untyped-def]
    assert sorted(d.domain_key for d in result.domains) == ["hr", "sales"]


def test_children_are_narrower_than_the_parent(model, result) -> None:  # type: ignore[no-untyped-def]
    parent_datasets = len(model.ldm.datasets)

    assert by_key(result, "sales").datasets_retained == 7
    assert by_key(result, "hr").datasets_retained == 9
    assert all(d.datasets_retained < parent_datasets for d in result.domains)


def test_the_declared_and_closure_sources_are_reported_apart(result) -> None:  # type: ignore[no-untyped-def]
    hr = by_key(result, "hr")

    assert hr.datasets_declared == 1
    assert hr.datasets_by_closure == 8
    assert "1 declared" in hr.summary_line()


def test_date_instances_are_per_domain(result) -> None:  # type: ignore[no-untyped-def]
    assert by_key(result, "sales").date_instances_retained == 1
    assert by_key(result, "hr").date_instances_retained == 1


# --- the collections the predecessor emptied ----------------------------------


def test_a_hierarchy_lands_in_the_child_that_references_it(result) -> None:  # type: ignore[no-untyped-def]
    assert by_key(result, "hr").hierarchies_retained == ("hier_geo_region",)
    assert by_key(result, "sales").hierarchies_retained == ()


def test_filter_contexts_are_not_emptied(model, manifest) -> None:  # type: ignore[no-untyped-def]
    children = _children(model, manifest)
    assert [fc.id for fc in children["sales"].analytics.filter_contexts] == ["fc_sales"]
    assert [fc.id for fc in children["hr"].analytics.filter_contexts] == ["fc_hr"]


def _children(model, manifest, **kwargs):  # type: ignore[no-untyped-def]
    from globalmart.closure import build_index
    from globalmart.split import split_domain

    index = build_index(model)
    return {
        key: split_domain(model, manifest.by_key(key), manifest, index=index, **kwargs)[0]
        for key in manifest.keys()  # noqa: SIM118 - DomainManifest.keys() is a method, not a mapping
    }


# --- shared (AC #17) ----------------------------------------------------------


def test_shared_objects_reach_every_child(model, manifest) -> None:  # type: ignore[no-untyped-def]
    for child in _children(model, manifest).values():
        assert "dash_shared_overview" in {d.id for d in child.analytics.analytical_dashboards}
        assert "viz_shared_geo" in {v.id for v in child.analytics.visualization_objects}
        # And the dataset that shared object needs is in each child's pruned LDM.
        assert "dim_geo" in {d.id for d in child.ldm.datasets}


def test_shared_ai_reaches_every_child(model, manifest) -> None:  # type: ignore[no-untyped-def]
    for child in _children(model, manifest).values():
        assert [p.id for p in child.analytics.parameters] == ["param_currency"]


# --- AI context ---------------------------------------------------------------


def test_ai_context_does_not_leak_between_domains(model, manifest, result) -> None:  # type: ignore[no-untyped-def]
    children = _children(model, manifest)

    sales_memory = {m.id for m in children["sales"].analytics.memory_items}
    hr_memory = {m.id for m in children["hr"].analytics.memory_items}

    assert sales_memory == {"mem_sales_defs"}
    assert hr_memory == {"mem_hr_defs"}
    assert not sales_memory & hr_memory


def test_a_memory_item_matched_only_by_tag_travels(model, manifest) -> None:  # type: ignore[no-untyped-def]
    """hr selects by `memory_item_tags`, not by id."""
    children = _children(model, manifest)
    assert {m.id for m in children["hr"].analytics.memory_items} == {"mem_hr_defs"}


def test_the_pairwise_ai_intersection_is_exactly_the_shared_set(result) -> None:  # type: ignore[no-untyped-def]
    sales = by_key(result, "sales").ai_context_ids
    hr = by_key(result, "hr").ai_context_ids
    assert sales & hr == {"param_currency"}


def test_an_unknown_ai_id_fails(model, manifest) -> None:  # type: ignore[no-untyped-def]
    from globalmart.ai_context import MissingAiContextError
    from globalmart.domains import AiSelection

    broken_domain = dataclasses.replace(
        manifest.by_key("sales"), ai=AiSelection(memory_item_ids=("mem_nope",))
    )
    broken = dataclasses.replace(manifest, domains=(manifest.by_key("hr"), broken_domain))

    with pytest.raises((MissingAiContextError, SplitFailedError), match="mem_nope"):
        split_all(model, broken, write=False)


# --- determinism and placeholders ---------------------------------------------


def test_emission_is_byte_stable(model, manifest, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    first = tmp_path / "a"
    second = tmp_path / "b"
    split_all(model, manifest, out=first, write=True)
    split_all(model, manifest, out=second, write=True)

    for path in sorted(first.glob("*.json")):
        assert path.read_bytes() == (second / path.name).read_bytes()


def test_placeholders_survive_into_the_generated_json(model, manifest, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """Substitution is publish-time work (FEAT-002's resolve.py), never done here."""
    split_all(model, manifest, out=tmp_path, write=True)

    for path in sorted(tmp_path.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        assert "{{ datasource_id }}" in text
        assert "globalmart-motherduck" not in text
    sales = (tmp_path / "globalmart-sales.json").read_text(encoding="utf-8")
    assert "{{ datasource_schema }}" in sales


def test_generated_json_round_trips(model, manifest, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    split_all(model, manifest, out=tmp_path, write=True)
    reloaded = read_model_json(tmp_path / "globalmart-hr.json")

    assert {d.id for d in reloaded.ldm.datasets} == {"dim_customer", "dim_employee", "dim_geo",
                                                     "dim_product", "dim_region", "dim_store",
                                                     "fact_headcount", "fact_orders", "sql_basket"}


# --- all-or-nothing and coverage ----------------------------------------------


def test_one_failing_domain_writes_nothing(model, manifest, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """A half-written directory looks like a successful split of a smaller manifest."""
    broken_domain = dataclasses.replace(manifest.by_key("sales"), dashboards=("dash_nope",))
    broken = dataclasses.replace(manifest, domains=(manifest.by_key("hr"), broken_domain))

    with pytest.raises(SplitFailedError, match="dash_nope"):
        split_all(model, broken, out=tmp_path, write=True)

    assert list(tmp_path.glob("*.json")) == []


def test_an_unreached_dashboard_fails_coverage(model, manifest, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    stripped = dataclasses.replace(
        manifest,
        domains=(
            manifest.by_key("hr"),
            dataclasses.replace(manifest.by_key("sales"), dashboards=("dash_exec",)),
        ),
    )
    with pytest.raises(SplitCoverageError, match="dash_sales"):
        split_all(model, stripped, out=tmp_path, write=True)


def test_only_restricts_the_run(model, manifest, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    result = split_all(model, manifest, only={"hr"}, out=tmp_path, write=True)

    assert [d.domain_key for d in result.domains] == ["hr"]
    assert [p.name for p in tmp_path.glob("*.json")] == ["globalmart-hr.json"]


def test_only_rejects_an_unknown_domain(model, manifest) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(Exception, match="nope"):
        split_all(model, manifest, only={"nope"}, write=False)


# --- the workspace name comes from the manifest -------------------------------


def test_workspace_names_come_from_the_manifest(result) -> None:  # type: ignore[no-untyped-def]
    assert by_key(result, "sales").workspace_name == "GlobalMart — Sales"
    assert by_key(result, "hr").workspace_name == "GlobalMart People (pilot)"
    assert by_key(result, "hr").label == "People"


# --- the real, committed children ---------------------------------------------


@pytest.mark.skipif(not GENERATED.exists(), reason="children not generated yet")
def test_the_twelve_committed_children_exist() -> None:
    files = sorted(p.name for p in GENERATED.glob("*.json"))
    assert len(files) == 12
    assert "globalmart-store-ops.json" in files
    assert "globalmart-real-estate.json" in files


@pytest.mark.skipif(not GENERATED.exists(), reason="children not generated yet")
def test_no_committed_child_carries_the_whole_parent_ldm() -> None:
    """The one number that says the predecessor's defect is gone."""
    for path in sorted(GENERATED.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        datasets = len(payload["ldm"]["datasets"])
        assert 1 <= datasets <= 60, f"{path.name} carries {datasets} datasets"


@pytest.mark.skipif(not GENERATED.exists(), reason="children not generated yet")
def test_committed_children_carry_no_resolved_datasource() -> None:
    for path in sorted(GENERATED.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        assert "{{ datasource_id }}" in text
        assert "globalmart-motherduck" not in text


@pytest.mark.skipif(not GENERATED.exists(), reason="children not generated yet")
def test_committed_children_match_a_fresh_split() -> None:
    """`split --check` as a test, so a parent edit without a re-split fails here too."""
    manifest = load_domains(REPO / "config" / "domains.yaml")
    model = read_tree(REPO / "layouts" / "workspaces" / "globalmart")

    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        split_all(model, manifest, out=Path(scratch), write=True,
                  metric_policy=MetricPolicy.DATASET_FIT)
        for path in sorted(Path(scratch).glob("*.json")):
            committed = GENERATED / path.name
            assert committed.exists(), f"{path.name} is not committed"
            assert path.read_text(encoding="utf-8") == committed.read_text(encoding="utf-8")
