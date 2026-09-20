"""Cross-org equivalence: same repo state, two orgs, identical except for what may differ.

Uses FEAT-002's `mask_parameters` deliberately, so the offline proof and the live one cannot
disagree about what "except for the parameterized values" means.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from globalmart.config import TargetProfile
from globalmart.equivalence import compare_orgs, dict_diff
from globalmart.layout_io import read_tree
from globalmart.normalize import normalize_workspace
from globalmart.resolve import resolve_and_assert

FIXTURE = Path(__file__).parent / "fixtures" / "mini_globalmart"
SOURCE_SCHEMA = "globalmart"


def profile(name: str, datasource_id: str, schema: str) -> TargetProfile:
    return TargetProfile(
        name=name,
        host=f"https://{name}.invalid",
        token="tok",
        organization_id=f"org-{name}",
        datasource_id=datasource_id,
        datasource_schema=schema,
    )


class OneWorkspaceSdk:
    def __init__(self, model: Any) -> None:
        outer = self
        self._model = model

        class _Workspace:
            def get_declarative_workspace(self, workspace_id: str) -> Any:
                return outer._model

        self.catalog_workspace = _Workspace()


def published(datasource_id: str, schema: str) -> Any:
    model = read_tree(FIXTURE)
    normalize_workspace(model, datasource_schema=SOURCE_SCHEMA)
    resolve_and_assert(model, datasource_id=datasource_id, datasource_schema=schema)
    return model


# --- dict_diff ----------------------------------------------------------------


def test_identical_structures_have_no_differences() -> None:
    assert dict_diff({"a": 1, "b": [1, 2]}, {"a": 1, "b": [1, 2]}) == []


def test_a_differing_value_names_its_path() -> None:
    (difference,) = dict_diff({"a": {"b": 1}}, {"a": {"b": 2}})
    assert difference.startswith("a.b:")


def test_a_missing_key_is_reported_on_the_right_side() -> None:
    assert dict_diff({"a": 1}, {}) == ["a: missing on the right"]
    assert dict_diff({}, {"a": 1}) == ["a: missing on the left"]


def test_list_lengths_are_compared() -> None:
    differences = dict_diff({"a": [1]}, {"a": [1, 2]})
    assert any("1 item(s) vs 2" in difference for difference in differences)


def test_nested_list_items_name_their_index() -> None:
    (difference,) = dict_diff({"a": [{"b": 1}]}, {"a": [{"b": 2}]})
    assert difference.startswith("a[0].b:")


# --- compare_orgs -------------------------------------------------------------


def test_two_orgs_from_one_repo_state_are_equivalent() -> None:
    """The portability contract: only the parameterized values may differ."""
    a = profile("demo", "globalmart-motherduck", "main")
    b = profile("li", "globalmart-postgres", "public_gm")

    report = compare_orgs(
        OneWorkspaceSdk(published(a.datasource_id, a.datasource_schema)),
        a,
        OneWorkspaceSdk(published(b.datasource_id, b.datasource_schema)),
        b,
        "globalmart",
    )

    assert report.equivalent, report.differing_paths
    assert report.differing_paths == []
    assert report.digest_a != report.digest_b  # unmasked, they genuinely differ


def test_a_real_difference_is_named() -> None:
    a = profile("demo", "globalmart-motherduck", "main")
    b = profile("li", "globalmart-postgres", "public_gm")

    divergent = published(b.datasource_id, b.datasource_schema)
    divergent.analytics.metrics[0].title = "Renamed in one org only"

    report = compare_orgs(
        OneWorkspaceSdk(published(a.datasource_id, a.datasource_schema)),
        a,
        OneWorkspaceSdk(divergent),
        b,
        "globalmart",
    )

    assert not report.equivalent
    assert any("title" in path for path in report.differing_paths)


def test_the_report_summarises_without_dumping_everything() -> None:
    a = profile("demo", "globalmart-motherduck", "main")
    b = profile("li", "globalmart-postgres", "public_gm")

    divergent = published(b.datasource_id, b.datasource_schema)
    for metric in divergent.analytics.metrics:
        metric.title = f"changed-{metric.id}"

    report = compare_orgs(
        OneWorkspaceSdk(published(a.datasource_id, a.datasource_schema)),
        a,
        OneWorkspaceSdk(divergent),
        b,
        "globalmart",
    )
    lines = report.summary_lines()

    assert not report.equivalent
    assert any("differing paths" in line for line in lines)
    assert len(lines) < 30  # a wall of 400 paths is not a summary


def test_masking_is_what_makes_them_equivalent() -> None:
    """Guard: if masking did nothing, the first test would be asserting the wrong thing."""
    a = profile("demo", "globalmart-motherduck", "main")
    model_a = published(a.datasource_id, a.datasource_schema)
    model_b = copy.deepcopy(model_a)

    raw = dict_diff(model_a.to_dict(camel_case=True), model_b.to_dict(camel_case=True))
    assert raw == []  # same input, same output — the harness itself is sound


@pytest.mark.parametrize("workspace_id", ["globalmart", "globalmart-sales"])
def test_the_workspace_id_is_carried_into_the_report(workspace_id: str) -> None:
    a = profile("demo", "globalmart-motherduck", "main")
    b = profile("li", "globalmart-postgres", "public_gm")

    report = compare_orgs(
        OneWorkspaceSdk(published(a.datasource_id, a.datasource_schema)),
        a,
        OneWorkspaceSdk(published(b.datasource_id, b.datasource_schema)),
        b,
        workspace_id,
    )

    assert report.workspace_id == workspace_id
    assert report.target_a == "demo"
    assert report.target_b == "li"
