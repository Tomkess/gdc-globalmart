"""Execute every visualization against the warehouse and record what happened.

**Why execution is the only reliable detector.** No field on a visualization object marks it
as broken. A workspace can publish cleanly, pass every structural check, and still have
every tile render an error — because whether a visualization computes depends on the LDM,
the warehouse, the datasource and the data, none of which the layout knows about. The
predecessor established this over 13 workspaces: the only way to know is to run it.

Three details are inherited from that predecessor because each was learned the hard way:

1. **An inner daemon thread per execution.** `ThreadPoolExecutor` cannot cancel an in-flight
   task, so a hung query would otherwise block a worker forever. Each execution runs in its
   own thread joined with a hard timeout; on expiry the result is `TIMEOUT` and the run
   continues, leaking at most one daemon thread that dies with the process.
2. **`sdk.tables.for_visualization(...)`** rather than a hand-built AFM. It resolves the
   visualization's own filters and attributes exactly as the UI does, so it tests the
   content rather than this module's ability to construct an AFM.
3. **A non-insight type raises a bare `KeyError('properties')`.** That is `SKIPPED`, not
   broken — but it is counted, so "every visualization executed" is never quietly narrowed.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from globalmart.classify import FailureCategory, classify, extract_status, is_retryable


class ExecStatus(StrEnum):
    OK = "OK"
    EMPTY = "EMPTY"
    BROKEN = "BROKEN"
    SKIPPED = "SKIPPED"


@dataclass
class VizResult:
    """One visualization's outcome."""

    workspace_id: str
    viz_id: str
    title: str
    status: ExecStatus
    duration_ms: int = 0
    #: >1 means it was retried. A pass on attempt 3 is visible, never silently green.
    attempts: int = 1
    row_count: int | None = None
    column_count: int | None = None
    #: The server's body verbatim, untruncated — an aggregate count diagnoses nothing.
    error: str | None = None
    http_status: int | None = None
    category: FailureCategory | None = None
    hint: str | None = None


@dataclass
class ThrottleEvent:
    workspace_id: str
    at: str
    from_workers: int
    to_workers: int
    trigger: str


class Throttle:
    """The run's concurrency budget, shared across every workspace.

    One budget for the whole run, not one per workspace: the host does not care which
    workspace a request belongs to, and N per-workspace pools would multiply the load by N
    while each looked individually well-behaved.

    On a 429 or a burst of 5xx the budget halves for the remainder of the run. It never
    recovers on its own — a host that asked us to slow down once is not asked again.
    """

    def __init__(self, max_workers: int = 8) -> None:
        self.max_workers = max_workers
        self._budget = max_workers
        self._lock = threading.Lock()
        self._semaphore = threading.Semaphore(max_workers)
        self.events: list[ThrottleEvent] = []
        self._consecutive_5xx = 0

    def acquire(self) -> None:
        self._semaphore.acquire()

    def release(self) -> None:
        self._semaphore.release()

    def current_budget(self) -> int:
        with self._lock:
            return self._budget

    def note_failure(self, workspace_id: str, category: FailureCategory | None) -> None:
        """Halve the budget on a rate limit, or on three consecutive 5xx."""
        with self._lock:
            trigger: str | None = None
            if category is FailureCategory.RATE_LIMITED:
                trigger = "429"
                self._consecutive_5xx = 0
            elif category is FailureCategory.TRANSIENT_5XX:
                self._consecutive_5xx += 1
                if self._consecutive_5xx >= 3:
                    trigger = "5xx-burst"
                    self._consecutive_5xx = 0
            else:
                self._consecutive_5xx = 0

            if trigger is None or self._budget <= 1:
                return

            new_budget = max(1, self._budget // 2)
            for _ in range(self._budget - new_budget):
                # Permanently consume permits rather than resizing the semaphore.
                self._semaphore.acquire(blocking=False)
            self.events.append(
                ThrottleEvent(
                    workspace_id=workspace_id,
                    at=datetime.now(UTC).isoformat(timespec="seconds"),
                    from_workers=self._budget,
                    to_workers=new_budget,
                    trigger=trigger,
                )
            )
            self._budget = new_budget


@dataclass
class ExecutionOptions:
    max_workers: int = 8
    viz_timeout: int = 180
    max_retries: int = 2
    backoff_s: float = 1.0
    #: Injected by tests so retry backoff does not make the suite slow.
    sleep: Any = field(default=time.sleep)


def viz_id_of(viz: Any) -> str:
    return str(getattr(viz, "id", None) or getattr(viz, "viz_id", None) or viz)


def viz_title_of(viz: Any) -> str:
    return str(getattr(viz, "title", None) or viz_id_of(viz))


def _table_shape(table: Any) -> tuple[int | None, int | None]:
    """`(rows, columns)` from whatever `for_visualization` returned.

    Deliberately forgiving: the point is to tell an empty result from a populated one, and
    a shape this cannot read must not turn a successful execution into a failure.
    """
    for attribute in ("data", "rows", "_data"):
        value = getattr(table, attribute, None)
        if isinstance(value, list):
            columns = len(value[0]) if value and isinstance(value[0], (list, tuple)) else None
            return len(value), columns
    if isinstance(table, list):
        return len(table), None
    return None, None


def execute_visualization(
    sdk: Any,
    workspace_id: str,
    viz: Any,
    *,
    options: ExecutionOptions | None = None,
    throttle: Throttle | None = None,
) -> VizResult:
    """Run one visualization. Never raises — every outcome becomes a `VizResult`."""
    opts = options or ExecutionOptions()
    identifier = viz_id_of(viz)
    title = viz_title_of(viz)
    started = time.monotonic()
    holder: list[VizResult] = []

    def attempt_once() -> VizResult:
        attempts = 0
        while True:
            attempts += 1
            try:
                table = sdk.tables.for_visualization(
                    workspace_id, viz, always_two_dimensional=True
                )
            except Exception as exc:  # noqa: BLE001 - recorded, never propagated
                status = extract_status(exc)
                failure = classify(str(exc), status)
                if throttle is not None:
                    throttle.note_failure(workspace_id, failure.category)
                if is_retryable(failure.category) and attempts <= opts.max_retries:
                    opts.sleep(opts.backoff_s * attempts)
                    continue
                exec_status = (
                    ExecStatus.SKIPPED
                    if failure.category is FailureCategory.UNSUPPORTED_TYPE
                    else ExecStatus.BROKEN
                )
                return VizResult(
                    workspace_id=workspace_id,
                    viz_id=identifier,
                    title=title,
                    status=exec_status,
                    attempts=attempts,
                    error=str(exc),
                    http_status=status,
                    category=failure.category,
                    hint=failure.hint,
                )

            rows, columns = _table_shape(table)
            if rows == 0:
                failure = classify("", None)
                return VizResult(
                    workspace_id=workspace_id,
                    viz_id=identifier,
                    title=title,
                    status=ExecStatus.EMPTY,
                    attempts=attempts,
                    row_count=0,
                    column_count=columns,
                    category=FailureCategory.EMPTY_RESULT,
                    hint=None,
                )
            return VizResult(
                workspace_id=workspace_id,
                viz_id=identifier,
                title=title,
                status=ExecStatus.OK,
                attempts=attempts,
                row_count=rows,
                column_count=columns,
            )

    def run() -> None:
        holder.append(attempt_once())

    # The pool cannot cancel an in-flight task, so the timeout lives here.
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=opts.viz_timeout)

    elapsed_ms = int((time.monotonic() - started) * 1000)

    if worker.is_alive() or not holder:
        message = f"Timeout: visualization did not respond within {opts.viz_timeout}s"
        failure = classify(message, None)
        return VizResult(
            workspace_id=workspace_id,
            viz_id=identifier,
            title=title,
            status=ExecStatus.BROKEN,
            duration_ms=elapsed_ms,
            error=message,
            category=failure.category,
            hint=failure.hint,
        )

    result = holder[0]
    result.duration_ms = elapsed_ms
    return result


def list_visualizations(sdk: Any, workspace_id: str) -> list[Any]:
    return list(sdk.visualizations.get_visualizations(workspace_id))


def execute_workspace(
    sdk: Any,
    workspace_id: str,
    *,
    options: ExecutionOptions | None = None,
    throttle: Throttle | None = None,
    pool: ThreadPoolExecutor | None = None,
) -> list[VizResult]:
    """Execute every visualization in one workspace, on the run's shared pool."""
    opts = options or ExecutionOptions()
    budget = throttle or Throttle(opts.max_workers)
    visualizations = list_visualizations(sdk, workspace_id)

    def one(viz: Any) -> VizResult:
        budget.acquire()
        try:
            return execute_visualization(
                sdk, workspace_id, viz, options=opts, throttle=budget
            )
        finally:
            budget.release()

    if pool is not None:
        results = list(pool.map(one, visualizations))
    else:
        with ThreadPoolExecutor(max_workers=max(opts.max_workers, 1)) as owned:
            results = list(owned.map(one, visualizations))

    results.sort(key=lambda result: result.viz_id)
    return results
