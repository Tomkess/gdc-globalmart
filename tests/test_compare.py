"""Task 16 — digest stability, diff readability, and cross-org masking."""

from __future__ import annotations

from pathlib import Path

import pytest
from gooddata_sdk.catalog.workspace.declarative_model.workspace.workspace import (
    CatalogDeclarativeWorkspaceModel,
)

from globalmart.compare import mask_parameters, model_diff, model_digest
from globalmart.layout_io import read_tree
from globalmart.normalize import normalize_workspace
from globalmart.resolve import resolve_and_assert

FIXTURE = Path(__file__).parent / "fixtures" / "mini_globalmart"
SOURCE_SCHEMA = "globalmart"


@pytest.fixture
def normalized() -> CatalogDeclarativeWorkspaceModel:
    model = read_tree(FIXTURE)
    normalize_workspace(model, datasource_schema=SOURCE_SCHEMA)
    return model


def test_digest_is_stable_across_loads() -> None:
    assert model_digest(read_tree(FIXTURE)) == model_digest(read_tree(FIXTURE))


def test_digest_changes_when_content_changes(
    normalized: CatalogDeclarativeWorkspaceModel,
) -> None:
    before = model_digest(normalized)
    normalized.analytics.metrics[0].title = "Something else entirely"

    assert model_digest(normalized) != before


def test_diff_of_identical_models_is_empty(
    normalized: CatalogDeclarativeWorkspaceModel,
) -> None:
    other = read_tree(FIXTURE)
    normalize_workspace(other, datasource_schema=SOURCE_SCHEMA)

    assert model_diff(normalized, other) == []


def test_diff_names_the_changed_path(normalized: CatalogDeclarativeWorkspaceModel) -> None:
    other = read_tree(FIXTURE)
    normalize_workspace(other, datasource_schema=SOURCE_SCHEMA)
    other.analytics.metrics[0].title = "Renamed"

    lines = model_diff(normalized, other)
    assert any("title" in line and "Renamed" in line for line in lines)


def test_diff_against_a_missing_target_says_so(
    normalized: CatalogDeclarativeWorkspaceModel,
) -> None:
    assert "does not exist yet" in model_diff(None, normalized)[0]


def test_two_orgs_are_identical_once_masked() -> None:
    """The portability contract, asserted offline.

    Publish the same repo state to two different targets, mask the values that are meant to
    differ, and the results must be byte-identical. Anything else differing is a defect.
    """
    demo = read_tree(FIXTURE)
    normalize_workspace(demo, datasource_schema=SOURCE_SCHEMA)
    resolve_and_assert(demo, datasource_id="globalmart-motherduck", datasource_schema="main")

    li = read_tree(FIXTURE)
    normalize_workspace(li, datasource_schema=SOURCE_SCHEMA)
    resolve_and_assert(li, datasource_id="globalmart-postgres", datasource_schema="public_gm")

    assert mask_parameters(
        demo, datasource_id="globalmart-motherduck", datasource_schema="main"
    ) == mask_parameters(li, datasource_id="globalmart-postgres", datasource_schema="public_gm")


def test_masking_actually_masks_something() -> None:
    """Guard: a mask that matched nothing would make the test above vacuous."""
    model = read_tree(FIXTURE)
    normalize_workspace(model, datasource_schema=SOURCE_SCHEMA)
    resolve_and_assert(model, datasource_id="globalmart-postgres", datasource_schema="public_gm")

    import json

    masked = json.dumps(
        mask_parameters(model, datasource_id="globalmart-postgres", datasource_schema="public_gm")
    )
    assert "globalmart-postgres" not in masked
    assert "public_gm" not in masked
    assert "{{ datasource_id }}" in masked
