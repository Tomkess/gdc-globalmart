"""A minimal viewer, standing where Portal Copilot stands.

Deliberately thin. Infobip already has an orchestrator with a front end, so this is not a
product and must not look like one — its job is to make a turn watchable and then be
deleted. Standard library `http.server`, one page, no build step, no CDN.

**The payload is the interface; this only renders it.** `Run.payload()` is what a host
actually consumes, and the page reads exactly that and nothing else. So anything visible
here is something their copilot could also show, and anything missing here is missing from
the interface rather than from the CSS.

Charts are inline SVG drawn from the `visualization` artifact's chart type and title and
the `visualization-data` artifact's rows. That is the honest version of "can a host render a
GoodData artifact": a plain page with no charting library managed it, which is a useful data
point for the gap list either way.

**Three routes matter, and each is a claim about the interface.**

`/ask` answers in one blocking call — the shape a host with no streaming would use.
`/ask/stream` answers the same question and narrates on the way, because a turn takes 30–120
seconds and one spinner for the whole of it hides the interesting part: the router chose
*these* workspaces, gave each a *different* sub-question, and they came back out of order.
The last event carries exactly the payload `/ask` would have returned, so the streaming
route adds narration and changes nothing about the result.

`/reply` answers a workspace that asked a question. With `ask_me` set, a lane that hits
`input-required` stops instead of auto-confirming, the question reaches the screen, and the
human's words go back to that one workspace on its own `contextId`. That is the honest
version of the feature: auto-confirming is the orchestrator guessing on the user's behalf.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from gd_agents.lane import Lane
from gd_agents.orchestrator.events import Observer
from gd_agents.orchestrator.run import Run, ask, enrich, respond
from gd_agents.orchestrator.session import Session
from gd_agents.registry import Registry
from gd_agents.script import load_script

PAGE = Path(__file__).parent / "static" / "index.html"


@dataclass
class Orchestrator:
    """What the handler needs, so the HTTP layer holds no orchestration logic."""

    registry: Registry
    lanes: Mapping[str, Lane]
    protocol: str = "a2a"
    """Which lane implementation is behind this server. Shown on the page because the demo
    runs two of these side by side, and two identical-looking tabs answering the same
    question differently is a trap rather than a comparison."""

    client: Any | None = None
    model: str | None = None
    sessions: dict[str, Session] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def session(self, key: str) -> Session:
        with self.lock:
            return self.sessions.setdefault(key, Session())

    def reset(self, key: str) -> None:
        with self.lock:
            self.sessions.pop(key, None)

    def lanes_for(self, *, ask_me: bool, observe: Observer | None) -> dict[str, Lane]:
        """The lanes for one request, with this request's clarification policy.

        The policy cannot live on the server: whether a lane auto-confirms depends on
        whether a human is watching *this* turn, and the same deployment serves both. Lanes
        are frozen-ish dataclasses, so each request gets its own copies rather than mutating
        shared state — two concurrent turns with different policies must not collide.
        """
        tuned: dict[str, Lane] = {}
        for name, lane in self.lanes.items():
            fields = getattr(lane, "__dataclass_fields__", {})
            changes: dict[str, Any] = {}
            if ask_me and "confirm_clarifications" in fields:
                changes["confirm_clarifications"] = False
            if observe is not None and "observe" in fields:
                changes["observe"] = observe
            tuned[name] = replace(lane, **changes) if changes else lane  # type: ignore[type-var]
        return tuned


def _handler(orchestrator: Orchestrator) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - base signature
            # The default logs every request to stderr, which buries the orchestrator's own
            # output during a demo.
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            self._send(status, json.dumps(payload).encode(), "application/json")

        def _open_stream(self) -> None:
            """Chunked, so progress lines arrive while the turn is still running.

            Chunked rather than `Connection: close` because a closed connection is
            indistinguishable from a crashed server at the far end, and the page has to be
            able to tell those apart when a lane takes two minutes.
            """
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def _chunk(self, kind: str, detail: dict[str, Any]) -> None:
            body = json.dumps({"event": kind, **detail}).encode() + b"\n"
            self.wfile.write(b"%x\r\n" % len(body) + body + b"\r\n")
            self.wfile.flush()

        def _close_stream(self) -> None:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's contract
            route = self.path.split("?")[0]
            if route in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                return
            if route == "/registry":
                self._json(
                    200,
                    {
                        "host": orchestrator.registry.host,
                        "protocol": orchestrator.protocol,
                        "workspaces": [
                            {"id": e.id, "title": e.title, "description": e.description}
                            for e in orchestrator.registry.entries
                        ],
                    },
                )
                return
            if route == "/questions":
                # The same script that measures routing and gates the regression set. The
                # page offers them as one-click prompts so a demo is not typed live, and
                # serving them from the file means the runbook and the buttons cannot drift.
                self._json(200, script_payload())
                return
            self._json(404, {"error": "not found"})

        def _run(self, route: str, body: dict[str, Any], observe: Observer | None) -> Run:
            key = str(body.get("session") or "default")
            ask_me = bool(body.get("ask_me"))
            lanes = orchestrator.lanes_for(ask_me=ask_me, observe=observe)

            if route == "/ask":
                question = str(body.get("question") or "").strip()
                if not question:
                    raise ValueError("no question")
                if body.get("reset"):
                    orchestrator.reset(key)
                return ask(
                    question,
                    orchestrator.registry,
                    lanes,
                    session=orchestrator.session(key),
                    client=orchestrator.client,
                    model=orchestrator.model,
                    inject_failure=body.get("inject_failure") or None,
                    observe=observe,
                )
            if route == "/enrich":
                return enrich(
                    orchestrator.registry,
                    lanes,
                    orchestrator.session(key),
                    client=orchestrator.client,
                    model=orchestrator.model,
                    observe=observe,
                )
            if route == "/reply":
                workspace = str(body.get("workspace") or "").strip()
                text = str(body.get("text") or "").strip()
                if not workspace or not text:
                    raise ValueError("a reply needs both `workspace` and `text`")
                return respond(
                    lanes,
                    orchestrator.session(key),
                    workspace,
                    text,
                    client=orchestrator.client,
                    model=orchestrator.model,
                    observe=observe,
                )
            raise LookupError(route)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "body was not JSON"})
                return

            route = self.path.split("?")[0]
            streaming = route.endswith("/stream")
            if streaming:
                route = route[: -len("/stream")]

            if not streaming:
                try:
                    run = self._run(route, body, None)
                except LookupError:
                    self._json(404, {"error": "not found"})
                except ValueError as error:
                    self._json(400, {"error": str(error)})
                except Exception as error:  # noqa: BLE001 - the page must always get a reply
                    # A 500 with no body during a demo is indistinguishable from a hang.
                    self._json(500, {"error": f"{type(error).__name__}: {error}"})
                else:
                    self._json(200, run.payload())
                return

            # Streaming. The status line is already sent by the time anything can fail, so
            # an error has to travel as an event rather than a status code.
            self._open_stream()
            lock = threading.Lock()

            def observe(kind: str, detail: dict[str, Any]) -> None:
                # Lanes report from their own threads, and two half-written JSON lines
                # interleaved on one socket is an unparseable stream.
                with lock:
                    self._chunk(kind, detail)

            try:
                self._run(route, body, observe)
            except Exception as error:  # noqa: BLE001
                with lock:
                    self._chunk("error", {"error": f"{type(error).__name__}: {error}"})
            finally:
                self._close_stream()

    return Handler


def script_payload(path: Path | None = None) -> dict[str, Any]:
    """The question script as the page's prompt buttons.

    A missing or broken script must not take the page down with it — the buttons are a
    convenience and the input box always works, so this degrades to an empty list.
    """
    try:
        questions, conversations = load_script(path) if path else load_script()
    except Exception:  # noqa: BLE001 - the page is usable without its prompt buttons
        return {"questions": [], "conversations": []}
    return {
        "questions": [
            {
                "id": q.id,
                "kind": q.kind,
                "question": q.question,
                "expect": list(q.expect),
                "shows": q.shows,
                "note": q.note,
                "inject_failure": q.inject_failure,
            }
            for q in questions
        ],
        "conversations": [
            {
                "id": c.id,
                "kind": c.kind,
                "shows": c.shows,
                "note": c.note,
                "turns": [
                    {
                        "question": t.question,
                        "expect": list(t.expect),
                        "shows": t.shows,
                        "enrich": t.enrich,
                        "reply_to": t.reply_to,
                        "from_memory": t.from_memory,
                        "inject_failure": t.inject_failure,
                    }
                    for t in c.turns
                ],
            }
            for c in conversations
        ],
    }


def serve(
    registry: Registry,
    lanes: Mapping[str, Lane],
    *,
    host: str = "127.0.0.1",
    port: int = 8900,
    client: Any | None = None,
    model: str | None = None,
    protocol: str = "a2a",
) -> None:
    """Run until interrupted. Threaded, so four lanes are not serialised by the HTTP layer."""
    orchestrator = Orchestrator(
        registry=registry, lanes=lanes, client=client, model=model, protocol=protocol
    )
    server = ThreadingHTTPServer((host, port), _handler(orchestrator))
    print(f"listening on http://{host}:{port}  [{protocol.upper()}]")
    print(f"workspaces: {', '.join(registry.ids())}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
