"""HTTP against a GoodData org. Standard library only, deliberately.

The orchestrator needs three things from a host: JSON GETs for metadata, JSON-RPC POSTs for
A2A, and an SSE stream for a lane that streams. None of that needs a dependency, and this
package is meant to be liftable into a customer's own runtime — a reference implementation
that drags in a transport stack is a worse reference.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


class TransportError(Exception):
    """The host refused, timed out, or answered with something that was not JSON."""


@dataclass(frozen=True)
class Host:
    """One GoodData org and the token to reach it with."""

    url: str
    token: str

    def __post_init__(self) -> None:
        if not self.url.startswith(("http://", "https://")):
            raise TransportError(f"host url must be absolute, got {self.url!r}")

    def _request(self, path: str, *, method: str, body: Any | None, timeout: float) -> Any:
        url = self.url.rstrip("/") + path
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:400]
            raise TransportError(f"{method} {path} -> HTTP {error.code}: {detail}") from error
        except OSError as error:  # timeouts, DNS, refused connections
            raise TransportError(f"{method} {path} -> {error}") from error

        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise TransportError(f"{method} {path} -> response was not JSON: {raw[:200]!r}") from error

    def get(self, path: str, *, params: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
        if params:
            path = f"{path}?{urllib.parse.urlencode(params)}"
        return self._request(path, method="GET", body=None, timeout=timeout)

    def post(self, path: str, body: Any, *, timeout: float = 120.0) -> Any:
        """A2A calls run long — the timeout default is generous for that reason."""
        return self._request(path, method="POST", body=body, timeout=timeout)


def entities(host: Host, workspace: str, kind: str, *, size: int = 250) -> list[dict[str, Any]]:
    """One page of a workspace's entities of some kind.

    One page on purpose. Everything this package reads is for *describing* a workspace, and a
    description built from 250 metrics is already longer than a routing prompt should carry.
    Paginating to completion would cost more and say less.
    """
    payload = host.get(f"/api/v1/entities/workspaces/{workspace}/{kind}", params={"size": size})
    return list((payload or {}).get("data") or [])
