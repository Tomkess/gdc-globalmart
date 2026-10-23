"""FEAT-019 tasks 12–15 — projecting the parent layout into gdcloud's data-product tree."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from globalmart.gdcloud_bridge import (
    DEFAULT_ENV_CONFIG_PATH,
    DEFAULT_RELEASE_CONFIG_PATH,
    ReleaseConfig,
    load_release_config,
)
from globalmart.gdcloud_project import (
    WDF_FILE,
    Projection,
    ProjectionError,
    diff_projection,
    project_parent,
    write_projection,
)
from globalmart.layout_io import read_tree, write_tree
from globalmart.normalize import normalize_workspace

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "mini_globalmart"
CANONICAL_ID = "gdc_ds_globalmart_motherduck"
CANONICAL_SCHEMA = "globalmart"


@pytest.fixture
def release(tmp_path: Path) -> ReleaseConfig:
    (tmp_path / "gd_data_product").mkdir()
    shutil.copy(REPO_ROOT / DEFAULT_RELEASE_CONFIG_PATH, tmp_path / "config.yml")
    shutil.copy(REPO_ROOT / DEFAULT_ENV_CONFIG_PATH, tmp_path / DEFAULT_ENV_CONFIG_PATH)
    return load_release_config(tmp_path / "config.yml")


@pytest.fixture
def layout(tmp_path: Path) -> Path:
    """The fixture in committed form: normalized, placeholder-bearing (ADR 001)."""
    model = read_tree(FIXTURE)
    normalize_workspace(model, datasource_schema=CANONICAL_SCHEMA)
    folder = tmp_path / "layout"
    write_tree(model, folder)
    return folder


@pytest.fixture
def projection(release: ReleaseConfig, layout: Path) -> Projection:
    return project_parent(release, layout)


def _datasets(projection: Projection) -> list[dict]:  # type: ignore[type-arg]
    return [
        yaml.safe_load(content)
        for path, content in projection.files.items()
        if path.parts[:2] == ("ldm", "datasets")
    ]


# --- content -------------------------------------------------------------------------------


def test_projects_one_data_product(projection: Projection) -> None:
    assert projection.dp_id == "globalmart"
    assert {path.parts[0] for path in projection.files} == {"ldm", "analytics_model", WDF_FILE}


def test_no_placeholder_survives(projection: Projection) -> None:
    for path, content in projection.files.items():
        assert b"{{" not in content, path


def test_every_dataset_points_at_the_canonical_data_source(projection: Projection) -> None:
    table_backed = [d for d in _datasets(projection) if d.get("dataSourceTableId")]
    assert table_backed
    for dataset in table_backed:
        table = dataset["dataSourceTableId"]
        assert table["dataSourceId"] == CANONICAL_ID
        # Positional, never sorted: [schema, table].
        assert table["path"] == [CANONICAL_SCHEMA, table["id"]]


def test_sql_datasets_resolve_the_schema(projection: Projection) -> None:
    sql = [d for d in _datasets(projection) if d.get("sql")]
    assert sql
    for dataset in sql:
        assert dataset["sql"]["dataSourceId"] == CANONICAL_ID
        assert f"{CANONICAL_SCHEMA}." in dataset["sql"]["statement"]


def test_ai_memory_travels(projection: Projection) -> None:
    assert any(path.parts[:2] == ("analytics_model", "memory_items") for path in projection.files)


def test_no_empty_wdf_reference_lists(projection: Projection) -> None:
    # gd-store writes no key where the API returns nothing; an explicit [] would differ.
    assert all("workspaceDataFilterReferences" not in d for d in _datasets(projection))


def test_wdf_file_is_the_empty_document(projection: Projection) -> None:
    assert json.loads(projection.files[Path(WDF_FILE)]) == {"data": []}


def test_projection_is_deterministic(release: ReleaseConfig, layout: Path, projection: Projection) -> None:
    assert project_parent(release, layout).files == projection.files


def test_user_references_are_refused(release: ReleaseConfig) -> None:
    # The raw fixture still carries createdBy/modifiedBy; only a normalized layout may project.
    with pytest.raises(ProjectionError, match="user reference"):
        project_parent(release, FIXTURE)


def test_missing_layout_is_refused(release: ReleaseConfig, tmp_path: Path) -> None:
    with pytest.raises(ProjectionError, match="not found"):
        project_parent(release, tmp_path / "nowhere")


# --- write and --check ---------------------------------------------------------------------


def test_check_passes_on_fresh_output(projection: Projection, tmp_path: Path) -> None:
    out = tmp_path / "gd_data_product"
    write_projection(projection, out)
    assert diff_projection(projection, out) == []
    assert write_projection(projection, out) == []  # a second write changes nothing


def test_check_fails_on_a_hand_edit(projection: Projection, tmp_path: Path) -> None:
    out = tmp_path / "gd_data_product"
    write_projection(projection, out)
    metric = next(p for p in projection.files if p.parts[:2] == ("analytics_model", "metrics"))
    target = out / "globalmart" / metric
    target.write_text(target.read_text().replace("title:", "title: EDITED", 1))
    assert diff_projection(projection, out) == [f"differs: {metric}"]


def test_check_fails_on_a_stale_file(projection: Projection, tmp_path: Path) -> None:
    out = tmp_path / "gd_data_product"
    write_projection(projection, out)
    stale = out / "globalmart" / "ldm" / "datasets" / "dim_gone.yaml"
    stale.write_text("id: dim_gone\n")
    assert diff_projection(projection, out) == ["stale: ldm/datasets/dim_gone.yaml"]
    write_projection(projection, out)
    assert not stale.exists()


def test_check_fails_on_a_missing_dataset(projection: Projection, tmp_path: Path) -> None:
    out = tmp_path / "gd_data_product"
    write_projection(projection, out)
    dataset = next(p for p in projection.files if p.parts[:2] == ("ldm", "datasets"))
    (out / "globalmart" / dataset).unlink()
    assert diff_projection(projection, out) == [f"missing: {dataset}"]


def test_dry_run_writes_nothing(projection: Projection, tmp_path: Path) -> None:
    out = tmp_path / "dry"
    changed = write_projection(projection, out, dry_run=True)
    assert len(changed) == len(projection.files)
    assert not out.exists()


def test_policy_files_are_never_touched(projection: Projection, tmp_path: Path) -> None:
    out = tmp_path / "gd_data_product"
    policy = out / "globalmart" / "config.ci_checks.yml"
    policy.parent.mkdir(parents=True)
    policy.write_text("checks: {}\n")
    write_projection(projection, out)
    assert policy.read_text() == "checks: {}\n"
    assert diff_projection(projection, out) == []


# --- the committed tree --------------------------------------------------------------------


def test_committed_projection_is_current() -> None:
    """The same gate as `globalmart gdcloud project --check` in CI."""
    committed = REPO_ROOT / "gd_data_product"
    if not (committed / "globalmart").is_dir():
        pytest.skip("gd_data_product/globalmart/ is not committed yet")
    config = load_release_config(REPO_ROOT / DEFAULT_RELEASE_CONFIG_PATH)
    projection = project_parent(config, REPO_ROOT / "layouts" / "workspaces" / "globalmart")
    assert diff_projection(projection, committed) == []
