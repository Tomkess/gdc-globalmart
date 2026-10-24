"""FEAT-011 AC 5 — the live date-filter gate's decisions, run against fakes.

What the gate must never do is pass a filter that does nothing. Every test here is a way the
original defect, or its staleness twin, could come back — and the gate saying so by name.
The fakes behave (return numbers per window, fail, return nothing) rather than mock, so each
test reads as the scenario it represents.
"""

from __future__ import annotations

from types import SimpleNamespace as NS
from typing import Any

from gooddata_sdk import ObjId, PositiveAttributeFilter, RelativeDateFilter, SimpleMetric

from globalmart.datefilter_gate import (
    GateOptions,
    GateRun,
    GateStatus,
    Window,
    WindowResult,
    binding_of,
    gate_workspace,
    judge,
    measure_window,
)

SHIPPED = {
    "dataSet": {"identifier": {"id": "transaction_date", "type": "dataset"}},
    "from": "-11",
    "to": "0",
    "granularity": "GDC.time.month",
    "type": "relative",
}
NO_SLEEP = GateOptions(sleep=lambda _s: None)


# --- the decision ------------------------------------------------------------------------


def test_different_numbers_with_a_populated_recent_window_pass() -> None:
    assert judge(WindowResult((10.0,)), WindowResult((7.0,))) is GateStatus.PASS


def test_the_same_number_under_both_windows_fails() -> None:
    """The original defect: the filter binds to nothing, so every window agrees."""
    assert judge(WindowResult((960.0,)), WindowResult((960.0,))) is GateStatus.SAME


def test_an_empty_recent_window_fails_even_when_the_earlier_one_has_rows() -> None:
    """Staleness: data that stops before the window is a blank dashboard, not a pass."""
    assert judge(WindowResult((None,)), WindowResult((168.0,))) is GateStatus.EMPTY


def test_empty_under_every_window_fails_as_empty_not_same() -> None:
    assert judge(WindowResult((None, None)), WindowResult((None, None))) is GateStatus.EMPTY


def test_a_metric_moving_in_one_column_of_several_is_enough() -> None:
    assert judge(WindowResult((1.0, 5.0)), WindowResult((1.0, 4.0))) is GateStatus.PASS


def test_an_execution_error_is_never_a_pass() -> None:
    assert judge(WindowResult(error="400 Bad Request"), WindowResult((1.0,))) is GateStatus.ERROR
    assert judge(WindowResult((1.0,)), WindowResult(error="boom")) is GateStatus.ERROR


# --- reading the live filter ---------------------------------------------------------------


def test_the_shipped_filter_reads_as_a_twelve_month_window_and_the_one_before_it() -> None:
    binding = binding_of(SHIPPED)

    assert binding.dataset == "transaction_date"
    assert binding.relative
    assert binding.window == Window("MONTH", -11, 0)
    assert binding.window.before() == Window("MONTH", -23, -12)


def test_an_absolute_filter_is_flagged_and_gated_on_the_default_window() -> None:
    """The investigation's hand-patch was absolute — exactly what AC 8 must not leave behind."""
    patch = {
        "dataSet": {"identifier": {"id": "transaction_date", "type": "dataset"}},
        "from": "2024-01-01",
        "to": "2024-06-30",
        "granularity": "GDC.time.date",
        "type": "absolute",
    }
    binding = binding_of(patch)

    assert not binding.relative
    assert binding.window == Window("MONTH", -11, 0)


def test_a_filter_without_a_dataset_has_no_binding() -> None:
    assert binding_of({k: v for k, v in SHIPPED.items() if k != "dataSet"}).dataset is None


# --- a whole workspace, through fakes ------------------------------------------------------


def _metric(metric_id: str, fact: str) -> Any:
    return NS(id=metric_id, content={"maql": f"SELECT SUM({{fact/{fact}}})"})


def _viz(viz_id: str, metric_id: str) -> Any:
    measure = {
        "measure": {
            "definition": {"measureDefinition": {"item": {"identifier": {"id": metric_id, "type": "metric"}}}}
        }
    }
    return NS(id=viz_id, content={"buckets": [{"items": [measure]}]})


def _dashboard(dashboard_id: str, context_id: str, viz_ids: list[str]) -> Any:
    items = [
        {"widget": {"insight": {"identifier": {"id": v, "type": "visualizationObject"}}}} for v in viz_ids
    ]
    return NS(
        id=dashboard_id,
        title=dashboard_id.title(),
        content={
            "filterContextRef": {"identifier": {"id": context_id, "type": "filterContext"}},
            "layout": {"sections": [{"items": items}]},
        },
    )


def _context(context_id: str, *date_filters: dict[str, Any]) -> Any:
    return NS(id=context_id, content={"filters": [{"dateFilter": f} for f in date_filters]})


def _dataset(dataset_id: str, fact: str, references: list[str]) -> Any:
    return NS(
        id=dataset_id,
        attributes=[],
        facts=[NS(id=fact)],
        aggregated_facts=[],
        references=[NS(identifier=NS(id=r)) for r in references],
    )


def _workspace(dashboards: list[Any], contexts: list[Any]) -> Any:
    ldm = NS(
        datasets=[
            _dataset("fact_sales", "fact_sales.amount", ["transaction_date"]),
            _dataset("fact_aged_inventory", "fact_aged_inventory.quantity", []),
        ],
        date_instances=[NS(id="transaction_date")],
    )
    analytics = NS(
        metrics=[
            _metric("m_sales", "fact_sales.amount"),
            _metric("m_aged", "fact_aged_inventory.quantity"),
        ],
        visualization_objects=[
            _viz("v_sales", "m_sales"),
            _viz("v_aged", "m_aged"),
            _viz("v_sales2", "m_sales"),
        ],
        analytical_dashboards=dashboards,
        filter_contexts=contexts,
    )
    return NS(ldm=ldm, analytics=analytics)


class FakeSdk:
    def __init__(self, workspace: Any | None) -> None:
        outer = self
        self.fetched_viz: list[str] = []

        class _Workspaces:
            def get_declarative_workspace(self, workspace_id: str) -> Any:
                if workspace is None:
                    raise RuntimeError("404 Not Found: workspace does not exist")
                return workspace

        class _Viz:
            def get_visualization(self, workspace_id: str, viz_id: str) -> Any:
                outer.fetched_viz.append(viz_id)
                return NS(id=viz_id, metrics=[object()])

        self.catalog_workspace = _Workspaces()
        self.visualizations = _Viz()


def _measure(per_viz: dict[str, dict[int, WindowResult]]) -> Any:
    """Scripted results: viz id -> window start -> result."""
    calls: list[tuple[str, int]] = []

    def measure(workspace_id: str, viz: Any, dataset: str, window: Window) -> WindowResult:
        calls.append((viz.id, window.from_shift))
        return per_viz[viz.id][window.from_shift]

    measure.calls = calls  # type: ignore[attr-defined]
    return measure


MOVES = {-11: WindowResult((12.0,)), -23: WindowResult((9.0,))}
FLAT = {-11: WindowResult((5.0,)), -23: WindowResult((5.0,))}
STALE = {-11: WindowResult((None,)), -23: WindowResult((None,))}


def test_a_working_filter_passes_and_runs_one_visualization_twice() -> None:
    sdk = FakeSdk(_workspace([_dashboard("d1", "fc1", ["v_sales", "v_sales2"])], [_context("fc1", SHIPPED)]))
    measure = _measure({"v_sales": MOVES})

    gate = gate_workspace(sdk, "ws", options=NO_SLEEP, measure=measure)

    assert gate.passed
    assert [d.status for d in gate.dashboards] == [GateStatus.PASS]
    assert measure.calls == [("v_sales", -11), ("v_sales", -23)]


def test_a_filter_that_changes_nothing_fails_naming_the_dashboard() -> None:
    sdk = FakeSdk(_workspace([_dashboard("d_flat", "fc1", ["v_sales"])], [_context("fc1", SHIPPED)]))

    gate = gate_workspace(sdk, "ws", options=NO_SLEEP, measure=_measure({"v_sales": FLAT}))

    assert not gate.passed
    assert [d.dashboard_id for d in gate.failures] == ["d_flat"]
    assert any("d_flat" in line and "SAME" in line for line in gate.summary_lines())


def test_stale_data_fails() -> None:
    sdk = FakeSdk(_workspace([_dashboard("d1", "fc1", ["v_sales"])], [_context("fc1", SHIPPED)]))

    gate = gate_workspace(sdk, "ws", options=NO_SLEEP, measure=_measure({"v_sales": STALE}))

    assert gate.failures[0].status is GateStatus.EMPTY


def test_a_snapshot_tile_is_skipped_rather_than_blamed() -> None:
    """Aged inventory reaches no date; trying it would be a false failure. The next tile decides."""
    sdk = FakeSdk(_workspace([_dashboard("d1", "fc1", ["v_aged", "v_sales"])], [_context("fc1", SHIPPED)]))

    gate = gate_workspace(sdk, "ws", options=NO_SLEEP, measure=_measure({"v_sales": MOVES}))

    assert gate.passed
    assert sdk.fetched_viz == ["v_sales"]


def test_a_dashboard_whose_tiles_cannot_reach_the_date_fails() -> None:
    sdk = FakeSdk(_workspace([_dashboard("d_snap", "fc1", ["v_aged"])], [_context("fc1", SHIPPED)]))

    gate = gate_workspace(sdk, "ws", options=NO_SLEEP, measure=_measure({}))

    assert gate.failures[0].status is GateStatus.NO_DATED_VISUALIZATION


def test_an_unbound_live_filter_fails_without_executing_anything() -> None:
    """The original defect, deployed: caught even if the offline bind check was bypassed."""
    unbound = {k: v for k, v in SHIPPED.items() if k != "dataSet"}
    sdk = FakeSdk(_workspace([_dashboard("d1", "fc1", ["v_sales"])], [_context("fc1", unbound)]))
    measure = _measure({})

    gate = gate_workspace(sdk, "ws", options=NO_SLEEP, measure=measure)

    assert gate.failures[0].status is GateStatus.UNBOUND
    assert measure.calls == []


def test_candidates_are_bounded_and_the_first_pass_decides() -> None:
    sdk = FakeSdk(_workspace([_dashboard("d1", "fc1", ["v_sales", "v_sales2"])], [_context("fc1", SHIPPED)]))
    opts = GateOptions(max_candidates=1, sleep=lambda _s: None)

    gate = gate_workspace(sdk, "ws", options=opts, measure=_measure({"v_sales": FLAT, "v_sales2": MOVES}))

    # One candidate allowed, and it does not filter: v_sales2 is never tried.
    assert not gate.passed
    assert sdk.fetched_viz == ["v_sales"]


def test_a_dashboard_without_a_date_filter_is_counted_not_gated() -> None:
    sdk = FakeSdk(
        _workspace(
            [_dashboard("d1", "fc1", ["v_sales"]), _dashboard("d2", "fc2", ["v_sales"])],
            [_context("fc1", SHIPPED), _context("fc2")],
        )
    )

    gate = gate_workspace(sdk, "ws", options=NO_SLEEP, measure=_measure({"v_sales": MOVES}))

    assert gate.passed
    assert gate.without_date_filter == ["d2"]


def test_a_retryable_failure_is_retried_and_a_deterministic_one_is_not() -> None:
    attempts: list[int] = []

    def flaky(workspace_id: str, viz: Any, dataset: str, window: Window) -> WindowResult:
        attempts.append(window.from_shift)
        if len(attempts) == 1:
            raise RuntimeError("HTTP 503 Service Unavailable")
        return MOVES[window.from_shift]

    sdk = FakeSdk(_workspace([_dashboard("d1", "fc1", ["v_sales"])], [_context("fc1", SHIPPED)]))
    assert gate_workspace(sdk, "ws", options=NO_SLEEP, measure=flaky).passed
    assert attempts == [-11, -11, -23]

    def broken(workspace_id: str, viz: Any, dataset: str, window: Window) -> WindowResult:
        raise RuntimeError("HTTP 400 Bad Request: unknown metric")

    gate = gate_workspace(sdk, "ws", options=NO_SLEEP, measure=broken)
    assert gate.failures[0].status is GateStatus.ERROR
    assert "unknown metric" in gate.failures[0].describe()


def test_an_unreadable_workspace_fails_the_run() -> None:
    gate = gate_workspace(FakeSdk(None), "ghost", options=NO_SLEEP, measure=_measure({}))
    run = GateRun(target="t", host="h", workspaces=[gate])

    assert gate.error and "404" in gate.error
    assert not run.passed


def test_a_workspace_with_nothing_to_gate_does_not_pass() -> None:
    """Gating zero dashboards proves nothing, so it must not read as green."""
    sdk = FakeSdk(_workspace([_dashboard("d1", "fc1", ["v_sales"])], [_context("fc1")]))
    run = GateRun(target="t", host="h", workspaces=[gate_workspace(sdk, "ws", options=NO_SLEEP)])

    assert not run.passed


# --- the execution itself ------------------------------------------------------------------


class FakeTables:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[list[Any], list[Any]]] = []

    def for_items(self, workspace_id: str, items: list[Any], filters: list[Any]) -> Any:
        self.calls.append((items, filters))
        return NS(read_all=lambda: iter(self.rows))


class FakeVizFilter:
    def __init__(self, computable: Any) -> None:
        self.computable = computable

    def as_computable(self) -> Any:
        return self.computable


def test_measure_window_replaces_the_tiles_own_date_filter_and_keeps_the_rest() -> None:
    metric = SimpleMetric(local_id="m1", item=ObjId("m_sales", "metric"))
    own_date = RelativeDateFilter(ObjId("transaction_date", "dataset"), "YEAR", -1, -1)
    attribute = PositiveAttributeFilter(label=ObjId("dim_store.region", "label"), values=["West"])
    viz = NS(
        metrics=[NS(as_computable=lambda: metric)],
        filters=[FakeVizFilter(own_date), FakeVizFilter(attribute)],
    )
    sdk = NS(tables=FakeTables([{"m1": "42.5"}]))

    result = measure_window(sdk, "ws", viz, "transaction_date", Window("MONTH", -11, 0))

    assert result == WindowResult((42.5,))
    _, filters = sdk.tables.calls[0]
    assert attribute in filters and own_date not in filters
    added = filters[-1]
    assert isinstance(added, RelativeDateFilter)
    assert (added.dataset.id, added.granularity, added.from_shift, added.to_shift) == (
        "transaction_date",
        "MONTH",
        -11,
        0,
    )


def test_measure_window_reads_an_empty_result_as_empty() -> None:
    metric = SimpleMetric(local_id="m1", item=ObjId("m_sales", "metric"))
    viz = NS(metrics=[NS(as_computable=lambda: metric)], filters=[])

    for rows in ([], [{}]):
        result = measure_window(
            NS(tables=FakeTables(rows)), "ws", viz, "transaction_date", Window("MONTH", -11, 0)
        )
        assert result.empty
