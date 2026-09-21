"""What the orchestrator is doing, while it is still doing it.

A turn takes 30–120 seconds and, without this, the only honest thing a caller can show for
the whole of it is a spinner. That reads as a hang, and worse, it hides the part of the work
that is actually interesting: the router chose *these* workspaces, gave each a *different*
sub-question, and three of the four came back in twenty seconds while one took ninety.

So the orchestrator takes an `Observer` — a plain callable — and reports as it goes. It is
optional everywhere and defaults to nothing, because the payload remains the interface: an
`Observer` is a progress feed, never a source of truth. A host that ignores it loses only
the narration, and `Run.payload()` at the end says the same things with more care.

**An observer must never break a turn.** It is caller-supplied code running inside a
fan-out thread, so `emit` swallows whatever it raises: a front end with a broken renderer
should lose its progress bar, not the answer.

Events are `(kind, detail)` with a documented `kind` and a JSON-safe `detail`:

| kind | when | carries |
|---|---|---|
| `plan` | the router has chosen | workspaces, sub-questions, reasoning, combine_on |
| `lane_start` | a lane is dispatched | workspace, question |
| `lane_step` | inside a lane | workspace, step, detail — one line per round trip |
| `lane_done` | a lane returned | workspace, ok, latency_ms, round_trips, input_required |
| `checks` | the merge checks ran | verdicts |
| `merge_start` | the merge model was called | how many lanes it is given |
| `done` | the turn finished | the whole `Run.payload()` |
"""

from __future__ import annotations

from typing import Any, Protocol


class Observer(Protocol):
    """Told what happened, as it happens. Return value ignored."""

    def __call__(self, kind: str, detail: dict[str, Any]) -> None: ...


def emit(observer: Observer | None, kind: str, **detail: Any) -> None:
    """Report one event, if anyone is listening, and never let it matter if it fails."""
    if observer is None:
        return
    try:
        observer(kind, detail)
    except Exception:  # noqa: BLE001 - a broken progress feed must not fail the query
        return
