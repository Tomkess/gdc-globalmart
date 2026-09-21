"""The one interface both protocols implement, and the shape an answer comes back in.

A *lane* is one workspace, asked one sub-question, returning one answer. The orchestrator
knows nothing else about it — not which protocol carries it, not how the answer was
computed, not what tools or models were involved on the other side.

That indifference is load-bearing rather than tidy. FEAT-014 runs the same router,
decomposition and merge over MCP instead of A2A, and a protocol comparison whose
orchestrator differs between the two arms measures the orchestrator, not the protocol. One
interface, two implementations, is what makes the numbers mean anything.

The asymmetry underneath is real and is the point. An A2A lane sends an English sentence
and receives an answer, because the workspace agent resolves metrics, writes MAQL and picks
a chart against its own model. An MCP lane has no such shape — MCP offers tools, so
something must still do that reasoning, and `gd_agents.mcp` has to build a per-workspace
sub-agent to stand in the same place. Conforming to this interface is exactly what costs
MCP the extra work, which is why the interface is defined here and not inside either
protocol package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class Shape:
    """What an answer covers, so the merge can judge whether two of them combine.

    Without this the merge has two paragraphs of prose and no way to tell that one is
    monthly and the other quarterly, or that one was filtered to a region. Every field is
    optional because a lane may not know — and "unknown" must be distinguishable from
    "none", since a check cannot pass on an absence it never established.
    """

    grain: str | None = None
    """The dimension and granularity the answer is broken down by — "month", "campaign"."""

    time_from: str | None = None
    """ISO date the answer covers from, when it is time-bounded."""

    time_to: str | None = None
    """ISO date the answer covers to."""

    grains: tuple[str, ...] = ()
    """*Every* breakdown the answer contains, where it contains more than one.

    One sub-question can legitimately ask for two things — "rank campaigns by spend, and
    also give me spend by month" — and the workspace then returns two charts. Reading only
    the first made such a lane look as if it had answered at the wrong grain, and the merge
    refused a pair that did in fact share one. `grain` stays the first, for a reader; the
    checks look for an overlap across these.
    """

    windows: tuple[str, ...] = ()
    """Every period the answer covers, for the same reason as `grains`."""

    filters: tuple[str, ...] = ()
    """Filters applied, as the lane understood them. Order is not significant."""

    units: str | None = None
    """Currency or unit, where the answer is quantitative."""

    population: str | None = None
    """Who or what the rows are — "customers who purchased", "all stores"."""

    returned_data: bool = True
    """False when the lane answered but found nothing. Not the same as failing."""


@dataclass(frozen=True)
class Answer:
    """One lane's reply, with everything the merge and the report need.

    `numbers` exists so the no-computation rule can be enforced rather than requested: every
    numeral in a merged answer must appear in some lane's `numbers`. A merge that invents a
    ratio across two workspaces produces a value that is in neither, and that is detectable.
    """

    workspace: str
    question: str
    """The sub-question this lane was actually asked — not the user's original question."""

    text: str
    shape: Shape = field(default_factory=Shape)
    numbers: tuple[str, ...] = ()
    """Every numeric value in `text`, verbatim as rendered, for provenance checking."""

    artifacts: tuple[dict[str, Any], ...] = ()
    """Protocol-native payloads — A2A DataParts, MCP results. Rendered, never interpreted."""

    latency_ms: int = 0
    round_trips: int = 1
    """Model turns between sub-question and answer. One for A2A; more for MCP, which is
    most of the cost once its tool set is small."""

    tokens_in: int = 0
    tokens_out: int = 0
    context_id: str | None = None
    """The conversation this lane ended on, so a follow-up resumes it rather than starting
    cold. Per lane: each workspace runs its own A2A conversation."""

    error: str | None = None

    input_required: bool = False
    """The lane stopped to ask the caller something, and `text` is that question.

    Not a failure and not an answer — a third state the protocol has and most callers do
    not model. Carried up so a host can put the question to a human and reply on the same
    `context_id`, which is the only way the lane ever contributes. A fan-out with nobody
    watching auto-confirms instead; that is a guess, and this field is what makes the
    non-guessing path available.
    """

    def ok(self) -> bool:
        return self.error is None


@runtime_checkable
class Lane(Protocol):
    """One workspace, reachable by some protocol.

    Deliberately two methods. Anything richer would leak a protocol's shape into the
    orchestrator and quietly make the comparison unfair.
    """

    workspace: str

    def describe(self) -> str:
        """A condensed account of what this workspace covers, for the routing prompt.

        Generated by the profiler rather than hand-written: whether an orchestrator *can*
        discover this is the first question on the gap list, and hand-authoring four
        descriptions would answer it by assumption.
        """
        ...

    def ask(self, question: str, *, context_id: str | None = None) -> Answer:
        """Ask this workspace one sub-question.

        `context_id` continues a prior exchange with this workspace, so a follow-up does not
        start cold. It is per lane: a conversation holds one per engaged workspace, and a
        workspace engaged for the first time on turn three has no earlier turns to resume.

        Must not raise for an expected failure — a timeout or a refusal comes back as an
        `Answer` with `error` set, so one dead lane degrades the reply rather than ending
        the query.
        """
        ...
