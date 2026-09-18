"""Task 24 — object counts, and the guard that the provenance doc cannot drift."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from globalmart.counts import count_objects
from globalmart.layout_io import read_tree

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "mini_globalmart"
PROVENANCE = REPO_ROOT / "docs" / "bootstrap-provenance.md"
LAYOUT = REPO_ROOT / "layouts" / "workspaces" / "globalmart"


def test_fixture_counts_are_known() -> None:
    counts = count_objects(read_tree(FIXTURE))

    assert counts.datasets == 5
    assert counts.metrics == 8
    assert counts.visualization_objects == 5
    assert counts.analytical_dashboards == 2
    assert counts.memory_items == 1
    assert counts.filter_contexts == 1
    assert counts.date_instances == 1


def test_non_zero_hides_empty_channels() -> None:
    counts = count_objects(read_tree(FIXTURE))

    assert "parameters" in counts.as_dict()
    assert "parameters" not in counts.non_zero()


@pytest.mark.skipif(not LAYOUT.exists(), reason="real layout tree not captured yet")
def test_provenance_counts_match_the_committed_tree() -> None:
    """The doc records what was captured; parse it back so it cannot rot silently."""
    assert PROVENANCE.exists(), "a committed layout tree must come with its provenance doc"

    documented = {
        match.group(1): int(match.group(2))
        for match in re.finditer(r"^\|\s*`([a-z_]+)`\s*\|\s*(\d+)\s*\|", PROVENANCE.read_text(), re.M)
    }
    assert documented, "no counts table found in docs/bootstrap-provenance.md"

    actual = count_objects(read_tree(LAYOUT)).as_dict()
    for name, value in documented.items():
        assert actual[name] == value, f"{name}: doc says {value}, tree has {actual[name]}"
