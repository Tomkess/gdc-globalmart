"""The execution loop: timeouts, retries, throttling, and the OK/EMPTY distinction.

Every test here runs against a hand-written fake rather than a mocking framework, because
what matters is the sequence of outcomes, and a fake that *behaves* (hangs, fails twice then
succeeds, returns nothing) reads as the scenario it represents.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from globalmart.classify import FailureCategory
from globalmart.execute import (
    ExecStatus,
    ExecutionOptions,
    Throttle,
    execute_visualization,
    execute_workspace,
)


class Viz:
    def __init__(self, viz_id: str, title: str | None = None) -> None:
        self.id = viz_id
        self.title = title or viz_id


class Table:
    def __init__(self, rows: int, columns: int = 2) -> None:
        self.data = [[0] * columns for _ in range(rows)]


class FakeTables:
    """Behaves like `sdk.tables`, scripted per visualization id."""

    def __init__(self, behaviour: dict[str, Any]) -> None:
        self.behaviour = behaviour
        self.calls: list[str] = []
        self.lock = threading.Lock()

    def for_visualization(self, workspace_id: str, viz: Any, **kwargs: Any) -> Any:
        with self.lock:
            self.calls.append(viz.id)
        action = self.behaviour.get(viz.id, Table(3))
        if isinstance(action, Exception):
            raise action
        if callable(action):
            return action()
        return action


class FakeSdkTables:
    def __init__(self, behaviour: dict[str, Any], visualizations: list[Viz] | None = None) -> None:
        self.tables = FakeTables(behaviour)
        self._visualizations = visualizations or [Viz(v) for v in behaviour]

        outer = self

        class _Viz:
            def get_visualizations(self, workspace_id: str) -> list[Viz]:
                return outer._visualizations

        self.visualizations = _Viz()


NO_SLEEP = ExecutionOptions(sleep=lambda _s: None)


def test_a_populated_result_is_ok() -> None:
    sdk = FakeSdkTables({"v1": Table(5, 3)})
    result = execute_visualization(sdk, "ws", Viz("v1"), options=NO_SLEEP)

    assert result.status is ExecStatus.OK
    assert result.row_count == 5
    assert result.column_count == 3
    assert result.attempts == 1


def test_zero_rows_is_empty_not_ok() -> None:
    """An unloaded warehouse would otherwise pass the whole goal-01 claim silently."""
    sdk = FakeSdkTables({"v1": Table(0)})
    result = execute_visualization(sdk, "ws", Viz("v1"), options=NO_SLEEP)

    assert result.status is ExecStatus.EMPTY
    assert result.row_count == 0
    assert result.category is FailureCategory.EMPTY_RESULT


def test_a_failure_is_recorded_verbatim() -> None:
    sdk = FakeSdkTables({"v1": RuntimeError("HTTP 400 general error while calculating")})
    result = execute_visualization(sdk, "ws", Viz("v1"), options=NO_SLEEP)

    assert result.status is ExecStatus.BROKEN
    assert result.category is FailureCategory.CALC_ERROR
    assert result.http_status == 400
    assert "general error" in (result.error or "")
    assert result.hint


def test_an_unsupported_type_is_skipped_not_broken() -> None:
    sdk = FakeSdkTables({"v1": KeyError("properties")})
    result = execute_visualization(sdk, "ws", Viz("v1"), options=NO_SLEEP)

    assert result.status is ExecStatus.SKIPPED
    assert result.category is FailureCategory.UNSUPPORTED_TYPE


def test_a_transient_failure_is_retried_then_succeeds() -> None:
    state = {"n": 0}

    def flaky() -> Any:
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("HTTP 503 Service Unavailable")
        return Table(2)

    sdk = FakeSdkTables({"v1": flaky})
    result = execute_visualization(
        sdk, "ws", Viz("v1"), options=ExecutionOptions(max_retries=2, sleep=lambda _s: None)
    )

    assert result.status is ExecStatus.OK
    assert result.attempts == 3  # a pass on attempt 3 is visible, never silently green


def test_retries_are_bounded() -> None:
    sdk = FakeSdkTables({"v1": RuntimeError("HTTP 500 Internal Server Error")})
    result = execute_visualization(
        sdk, "ws", Viz("v1"), options=ExecutionOptions(max_retries=2, sleep=lambda _s: None)
    )

    assert result.status is ExecStatus.BROKEN
    assert result.attempts == 3
    assert sdk.tables.calls == ["v1", "v1", "v1"]


def test_a_deterministic_failure_is_not_retried() -> None:
    """Retrying a real defect makes it a slow real defect."""
    sdk = FakeSdkTables({"v1": RuntimeError("HTTP 404 not found")})
    result = execute_visualization(
        sdk, "ws", Viz("v1"), options=ExecutionOptions(max_retries=3, sleep=lambda _s: None)
    )

    assert result.attempts == 1
    assert sdk.tables.calls == ["v1"]


def test_a_hung_execution_times_out_and_the_run_continues() -> None:
    """ThreadPoolExecutor cannot cancel in flight, which is why the timeout lives here."""

    def hang() -> Any:
        time.sleep(30)
        return Table(1)

    sdk = FakeSdkTables({"v1": hang})
    started = time.monotonic()
    result = execute_visualization(
        sdk, "ws", Viz("v1"), options=ExecutionOptions(viz_timeout=1, sleep=lambda _s: None)
    )
    elapsed = time.monotonic() - started

    assert result.status is ExecStatus.BROKEN
    assert result.category is FailureCategory.TIMEOUT
    assert elapsed < 10


def test_execute_workspace_covers_every_visualization() -> None:
    sdk = FakeSdkTables(
        {
            "v1": Table(1),
            "v2": Table(0),
            "v3": RuntimeError("HTTP 400 general error"),
            "v4": KeyError("properties"),
        }
    )
    results = execute_workspace(sdk, "ws", options=NO_SLEEP)

    assert [r.viz_id for r in results] == ["v1", "v2", "v3", "v4"]
    assert [r.status for r in results] == [
        ExecStatus.OK,
        ExecStatus.EMPTY,
        ExecStatus.BROKEN,
        ExecStatus.SKIPPED,
    ]


def test_results_are_sorted_so_reports_do_not_churn() -> None:
    sdk = FakeSdkTables({"v3": Table(1), "v1": Table(1), "v2": Table(1)})
    results = execute_workspace(sdk, "ws", options=NO_SLEEP)

    assert [r.viz_id for r in results] == ["v1", "v2", "v3"]


# --- throttling ---------------------------------------------------------------


def test_a_rate_limit_halves_the_budget() -> None:
    throttle = Throttle(max_workers=8)
    throttle.note_failure("ws", FailureCategory.RATE_LIMITED)

    assert throttle.current_budget() == 4
    assert throttle.events[0].trigger == "429"
    assert throttle.events[0].from_workers == 8
    assert throttle.events[0].to_workers == 4


def test_a_single_5xx_does_not_throttle() -> None:
    """One blip is noise; a burst is a signal."""
    throttle = Throttle(max_workers=8)
    throttle.note_failure("ws", FailureCategory.TRANSIENT_5XX)

    assert throttle.current_budget() == 8
    assert throttle.events == []


def test_a_burst_of_5xx_throttles() -> None:
    throttle = Throttle(max_workers=8)
    for _ in range(3):
        throttle.note_failure("ws", FailureCategory.TRANSIENT_5XX)

    assert throttle.current_budget() == 4
    assert throttle.events[0].trigger == "5xx-burst"


def test_a_success_between_failures_resets_the_burst_counter() -> None:
    throttle = Throttle(max_workers=8)
    throttle.note_failure("ws", FailureCategory.TRANSIENT_5XX)
    throttle.note_failure("ws", FailureCategory.CALC_ERROR)
    throttle.note_failure("ws", FailureCategory.TRANSIENT_5XX)

    assert throttle.current_budget() == 8


def test_the_budget_never_drops_below_one() -> None:
    throttle = Throttle(max_workers=2)
    for _ in range(10):
        throttle.note_failure("ws", FailureCategory.RATE_LIMITED)

    assert throttle.current_budget() == 1


def test_throttling_is_recorded_per_workspace() -> None:
    throttle = Throttle(max_workers=8)
    throttle.note_failure("ws-a", FailureCategory.RATE_LIMITED)

    assert [event.workspace_id for event in throttle.events] == ["ws-a"]
