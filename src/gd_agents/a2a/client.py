"""One workspace, reached over A2A. An implementation of `Lane`.

A2A's shape is the reason this is short. The orchestrator sends an English sub-question and
receives an answer: metric resolution, MAQL, filter choice and chart selection all happen
inside the workspace, against a model that already knows the semantic layer. There is no
catalog to hold and no tool loop to run, so a lane is a JSON-RPC POST and some careful
reading of the Task that comes back.

Compare `gd_agents.mcp`, which has to build a per-workspace sub-agent to stand in the same
place. The difference in length between the two modules is the protocol comparison's most
honest single number.

**Reading the answer: `status.message` first.** Measured against the live agent on
2026-09-21, a completed Task looks like this:

    status.message.parts[].text   "Created a line chart showing {metric/…} by month for
                                   the last 6 months."          <- the answer
    history[]                     four agent turns of chain-of-thought:
                                   "**Creating a chart** I need to focus on…"
    artifacts[]                    visualization (chart definition) and
                                   visualization-data (columns, rows, formattedRows)

So the answer is in `status.message`, the numbers are in the `visualization-data` artifact,
and `history` carries the agent's *reasoning* — which reads like an answer and is not one.
An orchestrator that reads history, which is a reasonable first guess and what the existing
reference client does, gets chain-of-thought presented as a result. Recorded in the gap
list; handled here by reading status first and treating history as a last resort.

**Failure is a value, never an exception.** One dead lane must degrade the reply, not end
the query, so a timeout or a refusal comes back as an `Answer` carrying `error`.

**`input-required` is a wall, and the orchestrator has to climb it.** Observed live: asked
to rank campaigns by spend, the agent replied

    state: input-required
    "I found the exact spend metric, but it does not have a campaign field available for
     ranking. I can still create the list using {metric/…} and {attribute/…}. Should I
     create the ranked campaign spend table with these fields?"

It had done the work, found a viable path, and stopped for permission — with no human in the
lane. Left alone that lane contributes nothing, and in a four-lane fan-out it is the
difference between an answer and a shrug.

So a lane confirms once, continuing the same `contextId`. Bounded to one confirmation so it
cannot loop, counted in `round_trips` so the cost is visible, and the original question is
recorded so the reply can say the answer rested on an assumption.

This is a product ask, not just a workaround: an agent serving a programmatic caller needs a
mode that resolves its own ambiguity rather than asking. Auto-confirming is us guessing that
"yes" was the right answer, and sometimes it will not be.

**One retry on a transient server error.** Observed live on 2026-09-21: a lane returned
HTTP 502 while an identical request seconds later succeeded. Losing a workspace from an
answer because the gateway hiccuped is not a finding about federation, it is noise — and on
stage it is indistinguishable from the feature being broken. Retried once, counted in
`round_trips` so the cost stays visible. A 4xx is never retried: that is the server saying
the request was wrong, and asking again will not change it.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any

from gd_agents.lane import Answer, Shape
from gd_agents.orchestrator.events import Observer, emit
from gd_agents.transport import Host, TransportError

#: The states the GoodData A2A server actually uses (`executor.py`).
COMPLETED = "completed"
FAILED = "failed"
INPUT_REQUIRED = "input-required"

#: GoodData-specific DataPart names. Carried through and rendered, never interpreted here.
ARTIFACT_KINDS = (
    "visualization",
    "visualization-data",
    "key-driver-analysis",
    "what-if-analysis",
    "search-results",
    "alert-proposal",
)

#: A number as a reader sees it, so `numeric_provenance` can check a merged answer against
#: what the lanes actually returned. Keeps separators and decimals; ignores bare years.
#: `(?<![\w.])` keeps it out of identifiers: `metric_l1_total_campaign_spend` must not
#: contribute a "1" to a merged answer's provenance.
_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?(?![\w])")


def message_payload(text: str, context_id: str | None = None) -> dict[str, Any]:
    """The JSON-RPC envelope. `message/send` rather than `message/stream`.

    Non-streaming on purpose: the orchestrator fans out and waits for the slowest lane, so
    per-lane streaming buys nothing for the answer itself. The UI streams lane *status*,
    which is a different thing and does not need the protocol's help.
    """
    message: dict[str, Any] = {
        "kind": "message",
        "messageId": str(uuid.uuid4()),
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
    }
    if context_id:
        message["contextId"] = context_id
    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {"message": message},
    }


#: Server-side hiccups worth one more try. A 4xx means the request was wrong.
_TRANSIENT = ("HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "timed out", "timeout")


#: What a lane says to get past an `input-required`. Deliberately content-free: the agent has
#: already proposed what it would do, so the only thing to add is consent.
CONFIRMATION = (
    "Yes, proceed with the fields you proposed. Do not ask further questions — "
    "there is no human available to answer. If something is ambiguous, choose the most "
    "reasonable option and say which you chose."
)


def context_id_of(payload: Any) -> str | None:
    """The conversation id to continue, from a Task."""
    value = _root(payload).get("contextId")
    return str(value) if value else None


def is_transient(error: Exception) -> bool:
    """Whether asking again might plausibly work."""
    text = str(error)
    return any(marker in text for marker in _TRANSIENT)


def _root(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and "result" in payload:
        payload = payload["result"]
    return payload if isinstance(payload, dict) else {}


def _part_texts(parts: Any) -> list[str]:
    if not isinstance(parts, list):
        return []
    return [p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)]


def answer_text(payload: Any) -> tuple[str, str]:
    """The agent's answer and where it came from.

    Order matters and is not obvious: `status.message` carries the reply, artifacts may
    carry narration alongside their data, and `history` is the agent thinking aloud. Getting
    this order wrong yields chain-of-thought that reads convincingly like a result.
    """
    node = _root(payload)

    status = node.get("status") or {}
    if isinstance(status, dict):
        inner = status.get("message")
        if isinstance(inner, dict):
            texts = _part_texts(inner.get("parts"))
            if texts:
                return texts[-1], "status.message"

    artifact_texts: list[str] = []
    for artifact in node.get("artifacts") or []:
        if isinstance(artifact, dict):
            artifact_texts += _part_texts(artifact.get("parts"))
    if artifact_texts:
        return artifact_texts[-1], "artifact"

    # Last resort, and flagged as such: these are reasoning turns, not a reply.
    history: list[str] = []
    for message in node.get("history") or []:
        if isinstance(message, dict) and str(message.get("role", "")).lower() in {
            "agent",
            "assistant",
            "ai",
            "model",
        }:
            history += _part_texts(message.get("parts"))
    if history:
        return history[-1], "history (reasoning, not a reply)"
    return "", "none"


def data_artifacts(payload: Any) -> tuple[dict[str, Any], ...]:
    """GoodData DataParts, kept whole so the front end can render them."""
    found: list[dict[str, Any]] = []
    for artifact in _root(payload).get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        name = str(artifact.get("name") or "")
        for part in artifact.get("parts") or []:
            if isinstance(part, dict) and part.get("kind") == "data":
                found.append({"name": name, "data": part.get("data")})
    return tuple(found)


def shape_from_artifacts(artifacts: tuple[dict[str, Any], ...]) -> Shape:
    """Derive the answer's shape from the `visualization` artifact.

    The merge checks are only as good as the shape they are given, and the answer *text*
    does not carry it: "created a line chart showing spend by month" tells a reader the
    grain and tells code nothing. Without this, `shared_dimension`, `time_window_match` and
    `filter_parity` all return UNKNOWN on every real answer, which is not a passing check —
    it is a check that never ran.

    The artifact does carry it, in a form meant for rendering rather than reasoning:

        view_by   ["d_month"]                      -> resolve through query.fields
        fields    {"d_month": {"using": "label/transaction_date.month"}}
        filter_by {"last_6_months": {"type": "date_filter", "granularity": "MONTH",
                                     "from": -5, "to": 0, "using": "dataset/..."}}

    Windows are kept in whatever form the agent expressed them — relative bounds stay
    relative. Two lanes both saying `-5..0 MONTH` agree; resolving them to absolute dates
    would invent a precision the agent never claimed, and comparing a resolved window with
    an unresolved one would fail for the wrong reason.

    **Every visualization, not the first.** One sub-question can legitimately ask a workspace
    for two things — "rank campaigns by spend, and also give me spend by month" — and the
    agent returns two charts. Observed live 2026-09-21: reading only the first gave the
    marketing lane a grain of `campaign_id` when it had also returned the monthly series the
    plan asked for, so `shared_dimension` refused a pair that agreed on month. The first
    chart remains `grain`/`time_from` for a reader; the full sets are what the checks use.
    """
    visualizations = [
        a.get("data")
        for a in artifacts
        if a.get("name") == "visualization" and isinstance(a.get("data"), dict)
    ]
    if not visualizations:
        return Shape()

    all_grains: list[str] = []
    all_windows: list[str] = []
    other: list[str] = []

    for visualization in visualizations:
        assert isinstance(visualization, dict)  # noqa: S101 - narrowed by the filter above
        query = visualization.get("query") or {}
        fields = query.get("fields") or {}

        def using(key: str, fields: dict[str, Any] = fields) -> str:
            entry = fields.get(key) or {}
            return str(entry.get("using") or key)

        grains: list[str] = []
        for key in visualization.get("view_by") or []:
            reference = using(str(key))
            # `label/transaction_date.month` -> `month`: the part after the last dot is the
            # granularity, which is what two lanes have to agree on.
            grains.append(reference.rsplit(".", 1)[-1] if "." in reference else reference.split("/")[-1])
        if grains:
            all_grains.append(", ".join(grains))

        for name, spec in (query.get("filter_by") or {}).items():
            if not isinstance(spec, dict):
                continue
            if spec.get("type") == "date_filter":
                granularity = str(spec.get("granularity") or "")
                all_windows.append(f"{spec.get('from')}..{spec.get('to')} {granularity}".strip())
            else:
                other.append(f"{name}={spec.get('type') or 'filter'}")

    grain_set = tuple(dict.fromkeys(all_grains))
    window_set = tuple(dict.fromkeys(all_windows))
    window = window_set[0] if window_set else None
    return Shape(
        grain=grain_set[0] if grain_set else None,
        time_from=window,
        time_to=window,
        grains=grain_set,
        windows=window_set,
        filters=tuple(sorted(set(other))),
        units=None,
    )


def numbers_from_artifacts(artifacts: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    """Values a `visualization-data` artifact returned, as rendered.

    The answer text narrates — "created a line chart showing X by month" — while the numbers
    live in the artifact's `formattedRows`. Provenance has to come from here, or the
    no-computation rule would have nothing to check a merged answer against.
    """
    found: list[str] = []
    for artifact in artifacts:
        data = artifact.get("data")
        if not isinstance(data, dict):
            continue
        rows = data.get("formattedRows") or data.get("rows") or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            # A row is a list of cells, or a dict keyed by column title. Stringifying a dict
            # whole would put `{'Month/Year': '2026-04', ...}` into provenance, which
            # matches nothing a merged answer would ever write.
            if isinstance(row, dict):
                cells: list[Any] = list(row.values())
            elif isinstance(row, list):
                cells = list(row)
            else:
                cells = [row]
            for cell in cells:
                if cell is None:
                    continue
                text = str(cell).strip()
                if text and any(char.isdigit() for char in text):
                    found.append(text)
    return tuple(dict.fromkeys(found))


def numbers_in(text: str) -> tuple[str, ...]:
    """Every number a reader would see, so the merge can be held to them.

    The no-computation rule is enforced by comparing a merged answer's numerals against
    these. A four-digit run on its own is almost always a year, and treating years as
    provenance would let a merge invent any value between 1000 and 9999.
    """
    found: list[str] = []
    for match in _NUMBER.finditer(text or ""):
        value = match.group(0).strip()
        if not value:
            continue
        bare = value.replace(",", "").replace(" ", "")
        if bare.isdigit() and len(bare) == 4 and 1900 <= int(bare) <= 2200:
            continue
        found.append(value)
    return tuple(dict.fromkeys(found))


@dataclass
class A2ALane:
    """One workspace, asked in English."""

    host: Host
    workspace: str
    timeout: float = 120.0
    description: str = ""
    retries: int = 1
    """Attempts *after* the first, and only for transient server errors."""

    confirm_clarifications: bool = True
    """Answer one `input-required` by telling the agent to proceed. Off makes a lane that
    asks contribute nothing, which is honest but useless in a fan-out."""

    retry_failed_state: bool = True
    """Ask again once when the agent reports a terminal `failed` with no detail.

    Not obviously right — a deterministic failure retried is only slower. But the observed
    failures are not deterministic: the same workspace answered the same question in 27s and
    then returned `failed` on a rephrasing of it minutes later. Since `failed` arrives with
    no reason attached, a caller cannot tell the two apart, which is itself the product ask.
    One retry is the cheaper mistake."""

    observe: Observer | None = None
    """Told what this lane is doing, round trip by round trip.

    A lane is 30–120 seconds of silence otherwise, and the interesting part is *why* — one
    POST, or a POST plus a confirmation, or a retry after a 502. Optional and inert by
    default: the `Answer` is the result, this is only narration."""

    def describe(self) -> str:
        return self.description

    def endpoint(self) -> str:
        return f"/api/v1/ai/workspaces/{self.workspace}/a2a"

    def agent_card(self) -> dict[str, Any]:
        return dict(self.host.get(self.endpoint()) or {})

    def _step(self, step: str, detail: str = "", **extra: Any) -> None:
        emit(self.observe, "lane_step", workspace=self.workspace, step=step, detail=detail, **extra)

    def ask(self, question: str, *, context_id: str | None = None) -> Answer:
        started = time.monotonic()
        attempts = 0
        payload = None
        last_error: TransportError | None = None

        self._step(
            "message/send",
            f"POST {self.endpoint()}"
            + (f" · resuming contextId {context_id[:8]}…" if context_id else " · new conversation"),
        )

        while attempts <= self.retries:
            attempts += 1
            try:
                payload = self.host.post(
                    self.endpoint(), message_payload(question, context_id), timeout=self.timeout
                )
                break
            except TransportError as error:
                last_error = error
                if not is_transient(error) or attempts > self.retries:
                    break
                self._step("retry", f"{error} — transient, asking once more")

        # A terminal `failed` carries no reason, so it is indistinguishable from a transient
        # one. Retried once, with the round trip counted.
        if self.retry_failed_state and payload is not None:
            first = _root(payload)
            if str(((first.get("status") or {}) or {}).get("state") or "") == FAILED:
                self._step("retry", "agent reported state 'failed' with no detail — asking again")
                try:
                    payload = self.host.post(
                        self.endpoint(),
                        message_payload(question, context_id),
                        timeout=self.timeout,
                    )
                    attempts += 1
                except TransportError:
                    pass  # keep the failed Task; the lane reports it honestly

        if payload is None:
            self._step("failed", str(last_error))
            return Answer(
                workspace=self.workspace,
                question=question,
                text="",
                latency_ms=int((time.monotonic() - started) * 1000),
                round_trips=attempts,
                error=str(last_error),
            )

        node = _root(payload)
        state = str(((node.get("status") or {}) if isinstance(node, dict) else {}).get("state") or "")
        asked_for_clarification = state == INPUT_REQUIRED

        if asked_for_clarification and not self.confirm_clarifications:
            self._step(
                "input-required",
                "the agent stopped to ask a question — passing it to the caller",
            )

        if asked_for_clarification and self.confirm_clarifications:
            self._step("input-required", "the agent stopped to ask — auto-confirming")
            continued = context_id or context_id_of(payload)
            try:
                payload = self.host.post(
                    self.endpoint(),
                    message_payload(CONFIRMATION, continued),
                    timeout=self.timeout,
                )
                attempts += 1
                node = _root(payload)
                state = str(((node.get("status") or {}) or {}).get("state") or "")
            except TransportError:
                pass  # keep the clarification as the answer; the lane still reports honestly

        elapsed = int((time.monotonic() - started) * 1000)
        text, source = answer_text(payload)
        pending = state == INPUT_REQUIRED
        self._step(
            "read",
            f"state {state or '?'} · answer read from {source}",
            latency_ms=elapsed,
        )

        if state == FAILED:
            return Answer(
                workspace=self.workspace,
                question=question,
                text=text,
                latency_ms=elapsed,
                round_trips=attempts,
                error=f"agent reported {FAILED}",
            )

        artifacts = data_artifacts(payload)
        return Answer(
            workspace=self.workspace,
            question=question,
            text=text,
            shape=replace(
                shape_from_artifacts(artifacts),
                population=f"answer source: {source}"
                + (" (after confirming an assumption)" if asked_for_clarification else ""),
                # An agent still asking has not answered, and a merge that treats the
                # question as data would narrate a prompt back to the user.
                returned_data=bool(text) and not pending,
            ),
            input_required=pending,
            # Text narrates, artifacts carry the values — so provenance is the union.
            numbers=tuple(dict.fromkeys(numbers_from_artifacts(artifacts) + numbers_in(text))),
            artifacts=artifacts,
            context_id=context_id_of(payload),
            latency_ms=elapsed,
            round_trips=attempts,
            error=None if state in {COMPLETED, INPUT_REQUIRED, ""} else f"agent state {state!r}",
        )

    def context_id_of(self, payload: Any) -> str | None:
        """The conversation id to reuse for a follow-up to this workspace."""
        return context_id_of(payload)
