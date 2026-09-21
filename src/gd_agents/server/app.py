"""A minimal viewer, standing where Portal Copilot stands.

Deliberately thin. Infobip already has an orchestrator with a front end, so this is not a
product and must not look like one — its job is to make a turn watchable and then be
deleted. Standard library `http.server`, one page, no build step, no CDN.

**The payload is the interface; this only renders it.** `Run.payload()` is what a host
actually consumes, and the page reads exactly that and nothing else. So anything visible
here is something their copilot could also show, and anything missing here is missing from
the interface rather than from the CSS.

Charts are inline SVG drawn from the `visualization-data` rows. That is the honest version
of "can a host render a GoodData artifact": a plain page with no charting library managed it
in about sixty lines, which is a useful data point for the gap list either way.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from gd_agents.lane import Lane
from gd_agents.orchestrator.run import ask, enrich
from gd_agents.orchestrator.session import Session
from gd_agents.registry import Registry

PAGE = Path(__file__).parent / "static" / "index.html"


@dataclass
class Orchestrator:
    """What the handler needs, so the HTTP layer holds no orchestration logic."""

    registry: Registry
    lanes: Mapping[str, Lane]
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


def _handler(orchestrator: Orchestrator) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
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

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's contract
            if self.path.split("?")[0] in ("/", "/index.html"):
                self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                return
            if self.path.startswith("/registry"):
                self._json(
                    200,
                    {
                        "host": orchestrator.registry.host,
                        "workspaces": [
                            {"id": e.id, "title": e.title, "description": e.description}
                            for e in orchestrator.registry.entries
                        ],
                    },
                )
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._json(400, {"error": "body was not JSON"})
                return

            route = self.path.split("?")[0]
            key = str(body.get("session") or "default")

            try:
                if route == "/ask":
                    question = str(body.get("question") or "").strip()
                    if not question:
                        self._json(400, {"error": "no question"})
                        return
                    if body.get("reset"):
                        orchestrator.reset(key)
                    run = ask(
                        question,
                        orchestrator.registry,
                        orchestrator.lanes,
                        session=orchestrator.session(key),
                        client=orchestrator.client,
                        model=orchestrator.model,
                        inject_failure=body.get("inject_failure") or None,
                    )
                elif route == "/enrich":
                    run = enrich(
                        orchestrator.registry,
                        orchestrator.lanes,
                        orchestrator.session(key),
                        client=orchestrator.client,
                        model=orchestrator.model,
                    )
                else:
                    self._json(404, {"error": "not found"})
                    return
            except Exception as error:  # noqa: BLE001 - the page must always get a reply
                # A 500 with no body during a demo is indistinguishable from a hung server.
                self._json(500, {"error": f"{type(error).__name__}: {error}"})
                return

            self._json(200, run.payload())

    return Handler


def serve(
    registry: Registry,
    lanes: Mapping[str, Lane],
    *,
    host: str = "127.0.0.1",
    port: int = 8900,
    client: Any | None = None,
    model: str | None = None,
) -> None:
    """Run until interrupted. Threaded, so four lanes are not serialised by the HTTP layer."""
    orchestrator = Orchestrator(registry=registry, lanes=lanes, client=client, model=model)
    server = ThreadingHTTPServer((host, port), _handler(orchestrator))
    print(f"listening on http://{host}:{port}")
    print(f"workspaces: {', '.join(registry.ids())}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
