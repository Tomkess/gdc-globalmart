"""The live regression gate: a dashboard's date filter must change its numbers (FEAT-011 AC 5).

`datefilters bind --check` proves the layout is well-formed — every `dateFilter` names a
date dataset. It cannot prove the filter *does* anything. The original defect passed every
structural check for two years: an unbound filter and a bound one both render without
error, and FEAT-006's execution harness asserts only that. A filter that does nothing is
indistinguishable from one that works until somebody compares two windows.

So this compares two windows. Per dashboard, it executes one visualization's metrics under
the dashboard's own shipped window (`-11..0` months today) and under the equally long window
immediately before it, on the date dataset the live filter context is bound to. Then:

* **recent window empty** — fails. The data has gone stale (or the warehouse is empty), and
  the dashboard a prospect opens is blank. This is the staleness half of the defect.
* **both windows identical** — fails. The filter binds to nothing the visualization uses.
* **different, recent non-empty** — passes.

A dashboard may show a visualization the date cannot reach (a snapshot fact has no date,
see `datefilters.UNDATED_FACTS`). So candidates are only the visualizations whose content
reaches the bound date dataset in the live LDM — the same walk `datefilters bind` derives
the binding from — and a dashboard with none fails. Up to `max_candidates` are tried in
dashboard order and the first that passes decides; each tried candidate's verdict is kept,
so a failure names what was tried and why each one did not count.

Read-only: it reads the live workspace layout and runs executions, nothing else. The live
filter context is read rather than the committed one on purpose — the gate tests what the
deployed workspace does, including any hand edit made to it (AC 8).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from gooddata_sdk import AbsoluteDateFilter, ObjId, RelativeDateFilter

from globalmart.classify import classify, extract_status, is_retryable
from globalmart.datefilters import DateReach
from globalmart.refs import iter_dashboard_viz_refs

#: Dashboard filter granularity -> the compute API's. Anything else falls back to months.
_GRANULARITY = {
    "GDC.time.year": "YEAR",
    "GDC.time.quarter": "QUARTER",
    "GDC.time.month": "MONTH",
    "GDC.time.week_us": "WEEK",
    "GDC.time.week": "WEEK",
    "GDC.time.date": "DAY",
}

#: What the shipped dashboards use; also the fallback when a live filter is not relative.
DEFAULT_WINDOW_FROM = -11
DEFAULT_WINDOW_TO = 0


@dataclass(frozen=True)
class Window:
    """A relative date window, in the compute API's granularity."""

    granularity: str
    from_shift: int
    to_shift: int

    @property
    def length(self) -> int:
        return self.to_shift - self.from_shift + 1

    def before(self) -> Window:
        """The equally long window immediately preceding this one."""
        return Window(self.granularity, self.from_shift - self.length, self.to_shift - self.length)

    def __str__(self) -> str:
        return f"{self.from_shift}..{self.to_shift} {self.granularity.lower()}"


@dataclass(frozen=True)
class DateBinding:
    """What a live filter context says about its date filter."""

    dataset: str | None
    window: Window
    #: False when the live filter was absolute or unreadable and the default window was used.
    relative: bool


def binding_of(date_filter: dict[str, Any]) -> DateBinding:
    """Read one `dateFilter` body. Never raises: an odd filter is reported, not crashed on."""
    data_set = (date_filter.get("dataSet") or {}).get("identifier") or {}
    dataset = data_set.get("id")
    default = Window("MONTH", DEFAULT_WINDOW_FROM, DEFAULT_WINDOW_TO)
    if date_filter.get("type") != "relative":
        return DateBinding(dataset, default, relative=False)
    try:
        window = Window(
            _GRANULARITY.get(str(date_filter.get("granularity")), "MONTH"),
            int(date_filter["from"]),
            int(date_filter["to"]),
        )
    except KeyError, TypeError, ValueError:
        return DateBinding(dataset, default, relative=False)
    return DateBinding(dataset, window, relative=True)


@dataclass(frozen=True)
class WindowResult:
    """One execution's metric values, or the error that stopped it."""

    values: tuple[float | None, ...] = ()
    error: str | None = None

    @property
    def empty(self) -> bool:
        return self.error is None and all(value is None for value in self.values)


class GateStatus(StrEnum):
    PASS = "PASS"
    #: The recent window returned nothing: stale or missing data, a blank dashboard.
    EMPTY = "EMPTY"
    #: Both windows returned the same numbers: the filter does not reach this content.
    SAME = "SAME"
    ERROR = "ERROR"
    #: The visualization has no metric to compare.
    NO_METRICS = "NO_METRICS"
    #: The dashboard shows no visualization at all.
    NO_VISUALIZATION = "NO_VISUALIZATION"
    #: The date filter names no dataset — the original defect, live.
    UNBOUND = "UNBOUND"
    #: No visualization on the dashboard reaches the bound date: the filter cannot bite.
    NO_DATED_VISUALIZATION = "NO_DATED_VISUALIZATION"


def judge(recent: WindowResult, earlier: WindowResult) -> GateStatus:
    """The whole decision. Recent emptiness wins over sameness: blank is the worse finding."""
    if recent.error is not None or earlier.error is not None:
        return GateStatus.ERROR
    if recent.empty:
        return GateStatus.EMPTY
    if recent.values == earlier.values:
        return GateStatus.SAME
    return GateStatus.PASS


@dataclass
class CandidateOutcome:
    viz_id: str
    status: GateStatus
    recent: WindowResult = field(default_factory=WindowResult)
    earlier: WindowResult = field(default_factory=WindowResult)

    def describe(self) -> str:
        if self.status is GateStatus.ERROR:
            error = self.recent.error or self.earlier.error or ""
            return f"{self.viz_id}: ERROR {error.splitlines()[0][:160] if error else ''}"
        if self.status is GateStatus.NO_METRICS:
            return f"{self.viz_id}: no metric"
        return f"{self.viz_id}: {self.status} recent={_fmt(self.recent)} earlier={_fmt(self.earlier)}"


def _fmt(result: WindowResult) -> str:
    if result.empty:
        return "empty"
    return "/".join("-" if value is None else f"{value:g}" for value in result.values)


@dataclass
class DashboardOutcome:
    dashboard_id: str
    title: str
    dataset: str | None = None
    window: Window | None = None
    relative: bool = True
    candidates: list[CandidateOutcome] = field(default_factory=list)
    #: Set when the dashboard failed before any visualization ran.
    precondition: GateStatus | None = None

    @property
    def status(self) -> GateStatus:
        if self.precondition is not None:
            return self.precondition
        if any(candidate.status is GateStatus.PASS for candidate in self.candidates):
            return GateStatus.PASS
        decisive = [c for c in self.candidates if c.status is not GateStatus.NO_METRICS]
        if decisive:
            return decisive[0].status
        return GateStatus.NO_VISUALIZATION if not self.candidates else GateStatus.NO_METRICS

    @property
    def passed(self) -> bool:
        return self.status is GateStatus.PASS

    def describe(self) -> str:
        head = f"{self.dashboard_id} [{self.title}]: {self.status}"
        if self.window is not None:
            head += f" on {self.dataset} {self.window} vs {self.window.before()}"
        if self.passed:
            winner = next(c for c in self.candidates if c.status is GateStatus.PASS)
            return f"{head} — {winner.describe()}"
        tried = "; ".join(candidate.describe() for candidate in self.candidates)
        return f"{head} — {tried}" if tried else head


@dataclass
class WorkspaceGate:
    workspace_id: str
    dashboards: list[DashboardOutcome] = field(default_factory=list)
    #: Dashboards whose filter context carries no date filter — not gated, but counted.
    without_date_filter: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(dashboard.passed for dashboard in self.dashboards)

    @property
    def failures(self) -> list[DashboardOutcome]:
        return [dashboard for dashboard in self.dashboards if not dashboard.passed]

    @property
    def not_relative(self) -> list[DashboardOutcome]:
        """Live filters that are not the shipped relative window — a hand edit until proven not."""
        return [dashboard for dashboard in self.dashboards if not dashboard.relative]

    def summary_lines(self, *, verbose: bool = False) -> list[str]:
        if self.error is not None:
            return [f"{self.workspace_id}: UNREADABLE — {self.error}"]
        passed = sum(1 for dashboard in self.dashboards if dashboard.passed)
        lines = [
            f"{self.workspace_id}: {passed}/{len(self.dashboards)} dashboards filter"
            f" ({len(self.without_date_filter)} without a date filter)"
        ]
        for dashboard in self.dashboards if verbose else self.failures:
            lines.append(f"  {'ok  ' if dashboard.passed else 'FAIL'} {dashboard.describe()}")
        for dashboard in self.not_relative:
            lines.append(f"  NOTE {dashboard.dashboard_id}: live date filter is not relative")
        return lines


@dataclass
class GateOptions:
    max_candidates: int = 3
    max_workers: int = 4
    max_retries: int = 2
    backoff_s: float = 1.0
    #: Injected by tests so retry backoff does not make the suite slow.
    sleep: Any = field(default=time.sleep)


Measure = Callable[[str, Any, str, Window], WindowResult]


def measure_window(sdk: Any, workspace_id: str, viz: Any, dataset: str, window: Window) -> WindowResult:
    """Execute a visualization's metrics alone, as totals, under one window.

    Totals rather than the visualization's own buckets: one row per execution keeps the cost
    bounded, and the comparison needs only to know whether the numbers moved. The
    visualization's own filters are kept except a date filter on the same dataset, which the
    dashboard filter replaces in the UI as well.
    """
    metrics = [metric.as_computable() for metric in viz.metrics]
    filters = [
        computable
        for computable in (item.as_computable() for item in viz.filters)
        if not computable.is_noop() and not _same_date(computable, dataset)
    ]
    filters.append(
        RelativeDateFilter(ObjId(dataset, "dataset"), window.granularity, window.from_shift, window.to_shift)
    )
    table = sdk.tables.for_items(workspace_id, items=metrics, filters=filters)
    rows = list(table.read_all())
    first = rows[0] if rows else {}
    return WindowResult(values=tuple(_number(first.get(metric.local_id)) for metric in metrics))


def _same_date(computable: Any, dataset: str) -> bool:
    if not isinstance(computable, (RelativeDateFilter, AbsoluteDateFilter)):
        return False
    return getattr(computable.dataset, "id", None) == dataset


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _guarded(
    measure: Measure, workspace_id: str, viz: Any, dataset: str, window: Window, opts: GateOptions
) -> WindowResult:
    """`measure` with infrastructure retries. Never raises — an error is a result."""
    attempts = 0
    while True:
        attempts += 1
        try:
            return measure(workspace_id, viz, dataset, window)
        except Exception as exc:  # noqa: BLE001 - recorded as the candidate's verdict
            failure = classify(str(exc), extract_status(exc))
            if is_retryable(failure.category) and attempts <= opts.max_retries:
                opts.sleep(opts.backoff_s * attempts)
                continue
            return WindowResult(error=str(exc))


def _date_filters(context: Any) -> list[dict[str, Any]]:
    content = getattr(context, "content", None) or {}
    return [item["dateFilter"] for item in content.get("filters", []) if "dateFilter" in item]


def _unique(ids: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def gate_dashboard(
    dashboard: Any,
    context: Any,
    *,
    workspace_id: str,
    get_viz: Callable[[str], Any],
    measure: Measure,
    options: GateOptions,
    reaches: Callable[[str, str], bool] | None = None,
) -> DashboardOutcome | None:
    """Gate one dashboard. `None` means it has no date filter, so there is nothing to gate."""
    outcome = DashboardOutcome(
        dashboard_id=str(dashboard.id), title=str(getattr(dashboard, "title", None) or dashboard.id)
    )
    date_filters = _date_filters(context) if context is not None else []
    if not date_filters:
        return None

    binding = binding_of(date_filters[0])
    outcome.dataset, outcome.window, outcome.relative = binding.dataset, binding.window, binding.relative
    if binding.dataset is None:
        outcome.precondition = GateStatus.UNBOUND
        return outcome

    dataset = binding.dataset
    # Only a visualization whose content reaches the bound date can show the filter working.
    # A snapshot tile (lifetime value, RFM quartiles, stock ageing) legitimately ignores it,
    # and trying one would be a false failure; skipping it here is a decision, not a guess.
    viz_ids = [
        viz_id
        for viz_id in _unique([ref.id for ref in iter_dashboard_viz_refs(dashboard)])
        if reaches is None or reaches(viz_id, dataset)
    ]
    if not viz_ids:
        outcome.precondition = GateStatus.NO_DATED_VISUALIZATION
        return outcome

    for viz_id in viz_ids:
        if len(outcome.candidates) >= options.max_candidates:
            break
        try:
            viz = get_viz(viz_id)
        except Exception as exc:  # noqa: BLE001 - a missing visualization is a finding
            outcome.candidates.append(
                CandidateOutcome(viz_id, GateStatus.ERROR, WindowResult(error=str(exc)))
            )
            continue
        if not list(getattr(viz, "metrics", None) or []):
            outcome.candidates.append(CandidateOutcome(viz_id, GateStatus.NO_METRICS))
            continue
        recent = _guarded(measure, workspace_id, viz, dataset, binding.window, options)
        earlier = _guarded(measure, workspace_id, viz, dataset, binding.window.before(), options)
        candidate = CandidateOutcome(viz_id, judge(recent, earlier), recent, earlier)
        outcome.candidates.append(candidate)
        if candidate.status is GateStatus.PASS:
            break
    return outcome


def gate_workspace(
    sdk: Any,
    workspace_id: str,
    *,
    options: GateOptions | None = None,
    measure: Measure | None = None,
) -> WorkspaceGate:
    """Gate every dashboard of one live workspace that carries a date filter."""
    opts = options or GateOptions()
    gate = WorkspaceGate(workspace_id=workspace_id)
    try:
        # The whole workspace, LDM included: which tiles the date can reach is an LDM question.
        model = sdk.catalog_workspace.get_declarative_workspace(workspace_id=workspace_id)
    except Exception as exc:  # noqa: BLE001 - an unreadable workspace fails the gate, named
        gate.error = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
        return gate

    analytics = model.analytics
    contexts = {context.id: context for context in (analytics.filter_contexts or [])}
    run = measure or (lambda ws, viz, dataset, window: measure_window(sdk, ws, viz, dataset, window))
    reach = DateReach(model)

    def reaches(viz_id: str, dataset: str) -> bool:
        return dataset in reach.for_visualizations([viz_id])

    def get_viz(viz_id: str) -> Any:
        return sdk.visualizations.get_visualization(workspace_id, viz_id)

    def one(dashboard: Any) -> DashboardOutcome | None:
        ref = (getattr(dashboard, "content", None) or {}).get("filterContextRef") or {}
        context = contexts.get((ref.get("identifier") or {}).get("id"))
        return gate_dashboard(
            dashboard,
            context,
            workspace_id=workspace_id,
            get_viz=get_viz,
            measure=run,
            options=opts,
            reaches=reaches,
        )

    dashboards = sorted(analytics.analytical_dashboards or [], key=lambda dashboard: str(dashboard.id))
    with ThreadPoolExecutor(max_workers=max(opts.max_workers, 1)) as pool:
        outcomes = list(pool.map(one, dashboards))

    for dashboard, outcome in zip(dashboards, outcomes, strict=True):
        if outcome is None:
            gate.without_date_filter.append(str(dashboard.id))
        else:
            gate.dashboards.append(outcome)
    return gate


@dataclass
class GateRun:
    target: str
    host: str
    workspaces: list[WorkspaceGate] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        # A workspace with no gated dashboard proves nothing; treat it as a failure, not a pass.
        return bool(self.workspaces) and all(gate.passed and gate.dashboards for gate in self.workspaces)

    def summary_lines(self, *, verbose: bool = False) -> list[str]:
        lines = [f"target            : {self.target} ({self.host})"]
        for gate in self.workspaces:
            lines.extend(gate.summary_lines(verbose=verbose))
            if gate.error is None and not gate.dashboards:
                lines.append(
                    f"  FAIL {gate.workspace_id}: no dashboard carries a date filter — nothing was gated"
                )
        return lines
