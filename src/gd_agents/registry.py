"""Which workspaces exist, and what each one covers.

The registry is the orchestrator's entire world view. It holds no catalog, no metric ids and
no schema — only a condensed account of what each workspace is *about*, because that is all
a routing decision needs and all that stays constant as the number of workspaces grows.

**Descriptions are generated, not authored.** `profile.py` builds them by querying each
workspace. That is a deliberate choice about what the demo is allowed to assume: whether an
orchestrator can discover what a workspace covers is the first item on AIS-55's gap list,
and hand-writing four descriptions would answer it by assumption rather than by finding out.
Infobip's portal adds A2A connections and will hit the same question on day one.

**Adding a workspace is a config entry.** No code changes, no prompt changes — which is the
property that has to hold if the four-workspace demo is to say anything credible about five.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_REGISTRY_PATH = Path("config/agents.yaml")


class RegistryError(Exception):
    """The registry is missing, malformed, or describes nothing."""


@dataclass(frozen=True)
class WorkspaceEntry:
    """One workspace, as the router sees it."""

    id: str
    title: str
    description: str
    """Condensed to what a routing decision needs: subject area, the kinds of question it
    can answer, its vocabulary. Not a catalog."""

    profiled_at: str | None = None
    """When the profiler last generated this description, so staleness is visible."""

    def prompt_line(self) -> str:
        return f"- {self.id} — {self.title}: {self.description}"


@dataclass(frozen=True)
class Registry:
    """Every workspace the orchestrator may reach, and the host it reaches them on."""

    host: str
    token_env: str
    entries: tuple[WorkspaceEntry, ...]

    def ids(self) -> tuple[str, ...]:
        return tuple(entry.id for entry in self.entries)

    def require(self, workspace: str) -> WorkspaceEntry:
        for entry in self.entries:
            if entry.id == workspace:
                return entry
        raise RegistryError(f"{workspace!r} is not in the registry")

    def prompt_block(self) -> str:
        """The workspace descriptions, as they appear in the routing prompt.

        One line each. At four workspaces this is a few hundred tokens and at forty it would
        still be a list — which is why no retrieval step is needed. The thing that grows is
        the number of workspaces a *caller* can see, and that is bounded by what they are
        entitled to, not by how many exist.
        """
        return "\n".join(entry.prompt_line() for entry in self.entries)

    @classmethod
    def load(cls, path: Path = DEFAULT_REGISTRY_PATH) -> Registry:
        path = Path(path)
        if not path.exists():
            raise RegistryError(f"No registry at {path}. Generate one with `gd-agents profile --apply`.")
        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        host = raw.get("host")
        token_env = raw.get("token_env")
        if not host or not token_env:
            raise RegistryError(f"{path}: `host` and `token_env` are both required")

        workspaces = raw.get("workspaces") or []
        if not workspaces:
            raise RegistryError(f"{path}: no workspaces — the orchestrator has nothing to route to")

        entries = []
        for item in workspaces:
            missing = [key for key in ("id", "title", "description") if not item.get(key)]
            if missing:
                raise RegistryError(
                    f"{path}: workspace {item.get('id', '<unnamed>')!r} is missing {missing}. "
                    "A workspace with no description cannot be routed to."
                )
            entries.append(
                WorkspaceEntry(
                    id=item["id"],
                    title=item["title"],
                    description=" ".join(str(item["description"]).split()),
                    profiled_at=item.get("profiled_at"),
                )
            )

        return cls(host=host, token_env=token_env, entries=tuple(entries))

    def write(self, path: Path = DEFAULT_REGISTRY_PATH) -> None:
        """Write the registry back, so a profiling run is reviewable as a diff."""
        payload = {
            "host": self.host,
            "token_env": self.token_env,
            "workspaces": [
                {
                    "id": entry.id,
                    "title": entry.title,
                    "description": entry.description,
                    **({"profiled_at": entry.profiled_at} if entry.profiled_at else {}),
                }
                for entry in self.entries
            ],
        }
        Path(path).write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=96),
            encoding="utf-8",
        )
