"""MAQL reference extraction — the cheapest place to prove the closure's foundation.

Everything downstream is only as complete as this. The predecessor extracted `{metric/}`
and nothing else, which is why its children loaded and could not compute.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from globalmart.maql import RefKind, iter_maql_refs, maql_metric_ids

REPO = Path(__file__).resolve().parents[1]
PARENT_METRICS = REPO / "layouts" / "workspaces" / "globalmart" / "analytics_model" / "metrics"


def test_extracts_every_kind() -> None:
    maql = (
        "SELECT SUM({fact/f.amount}) / {metric/m_base} "
        "BY {attribute/dim.a}, {label/dim.l} WHERE {dataset/ds} IS NOT NULL"
    )
    refs = list(iter_maql_refs(maql))

    assert [ref.kind for ref in refs] == [
        RefKind.FACT,
        RefKind.METRIC,
        RefKind.ATTRIBUTE,
        RefKind.LABEL,
        RefKind.DATASET,
    ]
    assert [ref.id for ref in refs] == ["f.amount", "m_base", "dim.a", "dim.l", "ds"]


def test_a_dotted_id_is_kept_whole() -> None:
    """The decision this module exists to *not* make.

    `fact_daily_store_sales.sales_amount` is one id; `transaction_date.month` is an id plus
    a granularity. Nothing in the syntax tells them apart, so both are captured whole and
    the LDM decides. Truncating at the dot here would break every fact reference in the
    parent while looking like it handled dates correctly.
    """
    (ref,) = list(iter_maql_refs("SELECT SUM({fact/fact_daily_store_sales.sales_amount})"))
    assert ref.id == "fact_daily_store_sales.sales_amount"
    assert ref.base == "fact_daily_store_sales"
    assert ref.suffix == "sales_amount"


def test_a_quoted_id_loses_its_quotes() -> None:
    (ref,) = list(iter_maql_refs('SELECT {metric/"my metric"}'))
    assert ref.id == "my metric"


def test_no_refs_and_no_maql_yield_nothing() -> None:
    assert list(iter_maql_refs("SELECT 1")) == []
    assert list(iter_maql_refs(None)) == []
    assert list(iter_maql_refs("")) == []


def test_metric_ids_helper() -> None:
    maql = "SELECT {metric/a} + {metric/b} - SUM({fact/f.x})"
    assert maql_metric_ids(maql) == {"a", "b"}


def test_duplicates_are_kept() -> None:
    """A caller counting references should get a true count; the closure works on sets."""
    assert len(list(iter_maql_refs("SELECT {metric/a} + {metric/a}"))) == 2


@pytest.mark.skipif(not PARENT_METRICS.exists(), reason="real parent tree not captured yet")
def test_every_reference_in_the_real_parent_resolves() -> None:
    """The corpus assertion: 1091 metrics, every extracted id must exist.

    An unresolvable extraction means either the regex is wrong or the parent is broken, and
    both are worth failing on. This is the guard that a future MAQL syntax the pattern does
    not cover gets noticed here rather than in a child that cannot compute.
    """
    from globalmart.layout_io import read_tree
    from globalmart.prune import build_entity_index

    model = read_tree(REPO / "layouts" / "workspaces" / "globalmart")
    index = build_entity_index(model.ldm)
    metric_ids = {str(metric.id) for metric in model.analytics.metrics}

    unresolved: list[str] = []
    total = 0
    for path in sorted(PARENT_METRICS.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for ref in iter_maql_refs(document["content"].get("maql")):
            total += 1
            if ref.kind is RefKind.METRIC:
                if ref.id not in metric_ids:
                    unresolved.append(f"{path.stem}: {{metric/{ref.id}}}")
            elif index.owner_of(ref.id) is None:
                unresolved.append(f"{path.stem}: {{{ref.kind.value}/{ref.id}}}")

    assert not unresolved, f"{len(unresolved)} unresolvable reference(s): {unresolved[:10]}"
    assert total > 2000, "the corpus assertion is only meaningful if it actually walked the corpus"
