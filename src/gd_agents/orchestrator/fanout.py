"""Calls the chosen lanes at once, and never lets one of them end the query.

Fan-out is where the latency lives. A2A calls ran 14–74 seconds against the live agents, and
the cost of a fan-out is the *slowest* lane, not the sum — which is the only reason four
workspaces is viable at all. Calling them in sequence would turn a 30-second answer into two
minutes, so concurrency here is not an optimisation, it is the feature.

**One dead lane degrades the answer; it does not end the query.** A lane that times out, or
whose agent refuses, comes back as an `Answer` carrying `error`. The merge then reports what
did return and says plainly what did not. The alternative — failing the whole question
because one of four workspaces was slow — is the behaviour a demo cannot survive.

**Timeouts are per lane and enforced here**, not left to the transport. A lane blocked on a
socket would otherwise hold the whole fan-out past any sensible wait, and the one thing worse
than a missing lane is an answer that never arrives.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from gd_agents.lane import Answer, Lane
from gd_agents.orchestrator.events import Observer, emit
from gd_agents.orchestrator.plan import Plan

#: Long enough for a real agent call — 74s was observed live — with headroom, and short
#: enough that a hung lane does not outlast the audience's patience.
DEFAULT_TIMEOUT = 150.0

#: Four lanes is the demo, five is Infobip's near future. Bounded so a wide plan cannot
#: open an unbounded number of connections to one org.
MAX_WORKERS = 8


@dataclass
class FanoutReport:
    answers: tuple[Answer, ...] = ()
    wall_ms: int = 0
    """End to end. Compare against the slowest lane: if they differ much, the lanes did not
    actually run in parallel, which is the thing this module exists to guarantee."""

    notes: list[str] = field(default_factory=list)

    def ok(self) -> tuple[Answer, ...]:
        return tuple(answer for answer in self.answers if answer.ok())

    def failed(self) -> tuple[Answer, ...]:
        return tuple(answer for answer in self.answers if not answer.ok())

    def with_data(self) -> tuple[Answer, ...]:
        """Lanes that answered *and* found something. A clarification request is neither."""
        return tuple(a for a in self.answers if a.ok() and a.shape.returned_data)

    def slowest_ms(self) -> int:
        return max((answer.latency_ms for answer in self.answers), default=0)

    def total_tokens(self) -> tuple[int, int]:
        return (
            sum(answer.tokens_in for answer in self.answers),
            sum(answer.tokens_out for answer in self.answers),
        )

    def round_trips(self) -> int:
        """Model turns across all lanes. One per lane for A2A; more for MCP, where it is
        most of the cost once the tool set is small."""
        return sum(answer.round_trips for answer in self.answers)

    def summary_lines(self) -> list[str]:
        tokens_in, tokens_out = self.total_tokens()
        lines = [
            f"lanes             : {len(self.answers)}",
            f"answered          : {len(self.ok())}",
            f"with data         : {len(self.with_data())}",
            f"failed            : {len(self.failed())}",
            f"wall              : {self.wall_ms} ms",
            f"slowest lane      : {self.slowest_ms()} ms",
            f"round trips       : {self.round_trips()}",
            f"lane tokens       : {tokens_in:,} in / {tokens_out:,} out",
        ]
        for answer in self.answers:
            state = "ok" if answer.ok() else "FAILED"
            if answer.ok() and not answer.shape.returned_data:
                state = "no data"
            lines.append(f"  {answer.workspace:24} {state:8} {answer.latency_ms:>6} ms")
            if answer.error:
                lines.append(f"    {answer.error[:120]}")
        for note in self.notes:
            lines.append(f"  note: {note}")
        return lines


def fanout(
    plan: Plan,
    lanes: Mapping[str, Lane],
    *,
    contexts: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_workers: int = MAX_WORKERS,
    only: frozenset[str] | None = None,
    inject_failure: str | None = None,
    observe: Observer | None = None,
) -> FanoutReport:
    """Run the plan's steps concurrently and collect every answer, failures included.

    `contexts` carries `workspace -> context_id` so a follow-up resumes that lane's own
    conversation rather than starting cold. It is per lane on purpose: a workspace engaged
    for the first time on turn three has no earlier turns to resume, and handing it another
    workspace's context would be worse than handing it none.

    `only` restricts execution to named workspaces — the enrich path, which retries a failed
    lane alone and keeps the answers that already succeeded.

    `inject_failure` forces one lane to fail, so the script's degradation case can be
    demonstrated without waiting for a real outage.

    `observe` is told as each lane starts and finishes. Lanes finish out of order and are
    reported that way, which is the point: it is how a watcher can see that the fan-out is
    concurrent rather than take the wall-clock number on trust.
    """
    contexts = contexts or {}
    steps = [step for step in plan.steps if only is None or step.workspace in only]
    report = FanoutReport()

    missing = [step.workspace for step in steps if step.workspace not in lanes]
    if missing:
        report.notes.append(f"no lane configured for {', '.join(missing)}")
        steps = [step for step in steps if step.workspace in lanes]

    if not steps:
        return report

    started = time.monotonic()
    collected: list[Answer] = []

    def report_done(answer: Answer) -> None:
        emit(
            observe,
            "lane_done",
            workspace=answer.workspace,
            ok=answer.ok(),
            returned_data=answer.shape.returned_data,
            input_required=answer.input_required,
            latency_ms=answer.latency_ms,
            round_trips=answer.round_trips,
            grain=answer.shape.grain,
            error=answer.error,
        )

    def run(workspace: str, question: str) -> Answer:
        emit(observe, "lane_start", workspace=workspace, question=question)
        if workspace == inject_failure:
            return Answer(
                workspace=workspace,
                question=question,
                text="",
                error="injected failure (demonstration)",
            )
        return lanes[workspace].ask(question, context_id=contexts.get(workspace))

    with ThreadPoolExecutor(max_workers=min(max_workers, len(steps))) as pool:
        futures: dict[Future[Answer], str] = {}
        for step in steps:
            futures[pool.submit(run, step.workspace, step.question)] = step.workspace

        for future in as_completed(futures, timeout=None):
            workspace = futures[future]
            try:
                answer = future.result(timeout=timeout)
            except Exception as error:  # noqa: BLE001 - a lane must never raise upward
                # Includes the timeout. The lane is reported as failed and the query goes on;
                # letting this propagate would fail the whole question over one slow agent.
                answer = Answer(
                    workspace=workspace,
                    question=next(s.question for s in steps if s.workspace == workspace),
                    text="",
                    error=f"{type(error).__name__}: {error}"[:300],
                )
            collected.append(answer)
            report_done(answer)

    report.wall_ms = int((time.monotonic() - started) * 1000)
    # Plan order, not completion order: the report should read the way the plan was written.
    order = [step.workspace for step in steps]
    report.answers = tuple(sorted(collected, key=lambda answer: order.index(answer.workspace)))
    return report


def context_map(answers: tuple[Answer, ...], previous: Mapping[str, str] | None = None) -> dict[str, str]:
    """Carry each lane's conversation id forward, keeping what earlier turns established.

    Placeholder for the A2A `contextId`, which the lane exposes separately — wired when the
    conversation loop lands. Kept here so the merge and the server have one place to ask.
    """
    carried = dict(previous or {})
    return carried


def lanes_for(
    plan: Plan, build: Callable[[str], Lane], *, cache: dict[str, Lane] | None = None
) -> dict[str, Lane]:
    """Lanes for exactly the workspaces a plan named, built once and reused across turns."""
    store = cache if cache is not None else {}
    for step in plan.steps:
        if step.workspace not in store:
            store[step.workspace] = build(step.workspace)
    return store
