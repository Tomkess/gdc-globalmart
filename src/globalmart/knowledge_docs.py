"""The only module that touches the AI Knowledge document API.

Endpoints, verified against the GoodData Cloud OpenAPI definition and
`@gooddata/api-client-tiger`'s generated `KnowledgeAi` on **2026-09-21**:

    PUT    /api/v1/ai/workspaces/{ws}/knowledge/documents                 upsert by filename
    POST   /api/v1/ai/workspaces/{ws}/knowledge/documents                 create (409 if exists)
    GET    /api/v1/ai/workspaces/{ws}/knowledge/documents                 list, cursor-paginated
    GET    /api/v1/ai/workspaces/{ws}/knowledge/documents/{id}            metadata
    GET    /api/v1/ai/workspaces/{ws}/knowledge/documents/{id}/download   the raw file
    DELETE /api/v1/ai/workspaces/{ws}/knowledge/documents/{id}            document + its chunks
    GET    /api/v1/ai/workspaces/{ws}/knowledge/search                    semantic search

The organization level (FEAT-017, ADR 010) takes the same verbs under
`/api/v1/ai/organization/knowledge/documents`, with no search of its own. Probed against
demo-cloud on **2026-09-25** by `scripts/probe_org_knowledge.py`: upsert, list, download and
delete answer in the workspace shapes; an org-level document reports `workspaceId: null` both in
the org listing and in a workspace listing; the org listing holds org-level documents only; and a
workspace search returns org-level chunks with no extra parameter.

The feature is flagged **Experimental** (shipped 2026-03-26), which is why every call lives
behind this one module and the date above is written down: when the surface moves, there is
one file to fix and a record of what it was checked against.

**Standard library only.** `gooddata-python-sdk` models no knowledge document — the only
generated client is the TypeScript one — so this is raw REST, as STEERING § Coding Standards
permits with the gap noted. `requests` is present in the environment but is *not* a declared
dependency of this package, and `gd_agents.transport` is JSON-only, so the multipart body is
built here. It is thirty lines and it costs nothing to carry.

**Ownership is doubly marked.** `scopes` carries `OWNER_SCOPE`, and the published filename
carries `corpus.FILENAME_PREFIX`. Either one identifies our work, because a listing that
omitted `scopes` would otherwise make every document look foreign and a reconcile would
propose recreating all of them. A document with neither marker is somebody else's: it is
never updated, never deleted, and never counted as ours. That is FEAT-008's
`test_a_build_never_touches_an_item_it_does_not_own` lesson, on a channel where the blast
radius is a whole file rather than a 255-character directive.

**Pruning additionally requires locality.** A workspace listing includes documents inherited
from parents and from the organization, and those are read-only from below. So a prune
candidate must be ours *and* live at the workspace being written — an inherited document that
happens to carry our markers belongs to whoever published it upstream.

**A level is a workspace id or `None`.** `None` is the organization level everywhere in this
module, the convention `RemoteDocument.is_local_to` already used for documents read from a
workspace listing. Which levels a target writes, and which it vacates, is decided once, in
`publish_for_target` / `verify_for_target`, from the profile's `knowledge_scope` (ADR 010).
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from globalmart.config import GlobalmartError, KnowledgeScope, TargetProfile
from globalmart.corpus import FILENAME_PREFIX, CorpusDocument

if TYPE_CHECKING:
    from globalmart.domains import DomainManifest

#: Ownership marker #2. A reserved `scopes` entry, the analogue of `knowledge.OWNER_TAG`.
OWNER_SCOPE = "globalmart-corpus"

WORKSPACE_BASE = "/api/v1/ai/workspaces/{workspace_id}/knowledge"
ORGANIZATION_BASE = "/api/v1/ai/organization/knowledge"

#: A workspace id, or `None` for the organization level.
LevelId = str | None

#: `size` ceiling is 2000; 200 keeps a page small enough to be a cheap retry.
LIST_PAGE_SIZE = 200

#: What `retrieval.py` asks search for by default.
DEFAULT_SEARCH_LIMIT = 10

Action = Literal["created", "updated", "unchanged", "would-upsert", "failed"]


class KnowledgeDocsError(GlobalmartError):
    """The knowledge-document API refused, or answered with something unusable.

    `status` is the HTTP status when the host answered, so a caller can tell "nothing here"
    (404) and "not allowed to look" (403) from a real failure.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class KnowledgeScopeError(KnowledgeDocsError):
    """A flag that has no meaning under the target's `knowledge_scope`."""


def level_label(level: LevelId) -> str:
    return "organization" if level is None else level


@dataclass(frozen=True)
class RemoteDocument:
    """One document as a listing reports it."""

    id: str
    filename: str
    title: str | None = None
    scopes: tuple[str, ...] = ()
    num_chunks: int | None = None
    workspace_id: str | None = None
    is_disabled: bool | None = None

    def is_ours(self) -> bool:
        """Prefix **or** scope. An OR rather than an AND, deliberately.

        The prefix is the more reliable of the two: filename is this API's identity, so a
        listing always carries it. `scopes` is documented on write and returned on read, but
        an AND would mean a single missing field turns our own corpus into foreign content
        and the next publish silently proposes recreating all of it.
        """
        return self.filename.startswith(FILENAME_PREFIX) or OWNER_SCOPE in self.scopes

    def is_local_to(self, workspace_id: LevelId) -> bool:
        """Whether this document is managed *here*, rather than inherited.

        A `None` workspace id means organization level. Anything that is not positively
        local is excluded from pruning: deleting an inherited document is not even possible
        from below, and proposing it would be a lie in the report.
        """
        return self.workspace_id == workspace_id

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> RemoteDocument:
        return cls(
            id=str(payload["id"]),
            filename=str(payload["filename"]),
            title=payload.get("title"),
            scopes=tuple(str(s) for s in (payload.get("scopes") or [])),
            num_chunks=payload.get("numChunks"),
            workspace_id=payload.get("workspaceId"),
            is_disabled=payload.get("isDisabled"),
        )


@dataclass(frozen=True)
class UpsertResult:
    """What `PUT /documents` answers."""

    id: str
    filename: str
    success: bool
    message: str
    num_chunks: int | None


@dataclass(frozen=True)
class SearchResult:
    """One chunk returned by `GET /knowledge/search`."""

    id: str
    filename: str
    content: str
    score: float
    chunk_index: int
    total_chunks: int
    scopes: tuple[str, ...] = ()
    title: str | None = None
    workspace_id: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SearchResult:
        return cls(
            id=str(payload["id"]),
            filename=str(payload["filename"]),
            content=str(payload["content"]),
            score=float(payload["score"]),
            chunk_index=int(payload.get("chunkIndex", 0)),
            total_chunks=int(payload.get("totalChunks", 0)),
            scopes=tuple(str(s) for s in (payload.get("scopes") or [])),
            title=payload.get("title"),
            workspace_id=payload.get("workspaceId"),
        )


@dataclass
class PublishDocResult:
    filename: str
    action: Action
    num_chunks: int | None = None
    error: str | None = None


@dataclass
class KnowledgeDocsReport:
    """What `publish` and `verify` print, and what the tests assert on."""

    target: str = ""
    workspace_id: LevelId = ""
    applied: bool = False
    results: list[PublishDocResult] = field(default_factory=list)
    missing_in_org: tuple[str, ...] = ()
    orphaned_in_org: tuple[str, ...] = ()
    foreign_left_alone: tuple[str, ...] = ()
    inherited_ours: tuple[str, ...] = ()
    pruned: tuple[str, ...] = ()
    #: filename -> (before, after). Logged only. Chunking is the server's business, and
    #: asserting on it would couple this repo to an implementation detail it cannot see.
    chunk_deltas: dict[str, tuple[int | None, int | None]] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return any(r.action in ("created", "updated", "would-upsert") for r in self.results) or bool(
            self.pruned
        )

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(r.filename for r in self.results if r.action == "failed")

    @property
    def level_label(self) -> str:
        return level_label(self.workspace_id)

    @property
    def stale(self) -> bool:
        """What `verify` treats as "does not match the repo"."""
        return bool(self.missing_in_org or self.orphaned_in_org or self.changed)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for result in self.results:
            out[result.action] = out.get(result.action, 0) + 1
        return out

    def summary_lines(self) -> list[str]:
        lines = [
            f"target            : {self.target}",
            f"level             : {self.level_label}",
            f"applied           : {self.applied}",
            f"documents         : {len(self.results)}",
        ]
        lines.extend(f"{action:18s}: {count}" for action, count in sorted(self.counts().items()))
        if self.missing_in_org:
            lines.append(f"missing in org    : {len(self.missing_in_org)}")
            lines.extend(f"  missing: {name}" for name in self.missing_in_org[:10])
        if self.orphaned_in_org:
            lines.append(f"orphaned in org   : {len(self.orphaned_in_org)}")
            lines.extend(f"  orphan : {name}" for name in self.orphaned_in_org[:10])
        if self.pruned:
            lines.append(f"pruned            : {len(self.pruned)}")
        if self.foreign_left_alone:
            lines.append(f"foreign (untouched): {len(self.foreign_left_alone)}")
        if self.inherited_ours:
            lines.append(f"ours but inherited : {len(self.inherited_ours)}")
        deltas = {k: v for k, v in self.chunk_deltas.items() if v[0] != v[1]}
        if deltas:
            lines.append(f"chunk count moved : {len(deltas)} document(s)")
            lines.extend(
                f"  {name}: {before} -> {after}"
                for name, (before, after) in list(deltas.items())[:10]
            )
        return lines


# --- the API ------------------------------------------------------------------


class KnowledgeApi(Protocol):
    """What `publish_corpus` and `verify_corpus` need from a host.

    A Protocol so the tests' `FakeKnowledgeApi` satisfies it structurally, without importing
    anything from here and without a live host in the unit suite.
    """

    def list_documents(self) -> list[RemoteDocument]: ...

    def download_document(self, document_id: str) -> str: ...

    def upsert_document(
        self, *, filename: str, body: str, title: str, scopes: tuple[str, ...]
    ) -> UpsertResult: ...

    def delete_document(self, document_id: str) -> None: ...

    def search(
        self, query: str, *, limit: int = DEFAULT_SEARCH_LIMIT, min_score: float = 0.0
    ) -> list[SearchResult]: ...


def _multipart(
    *, filename: str, body: str, title: str, scopes: tuple[str, ...]
) -> tuple[bytes, str]:
    """Encode one `multipart/form-data` body. Returns `(payload, content_type)`.

    `scopes` is sent as a **repeated field**, which is what the documented `curl` example
    does and what the FastAPI-shaped endpoint (note the 422 `HTTPValidationError` schema)
    parses into a list. The generated TypeScript client comma-joins instead; that would
    arrive as one scope with commas in it, so it is not followed here.
    """
    boundary = f"----globalmart-{uuid.uuid4().hex}"
    parts: list[bytes] = []

    def field_part(name: str, value: str) -> None:
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()
        )

    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: text/markdown\r\n\r\n"
        ).encode()
    )
    parts.append(body.encode("utf-8"))
    parts.append(b"\r\n")

    field_part("title", title)
    for scope in scopes:
        field_part("scopes", scope)

    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


@dataclass(frozen=True)
class HttpKnowledgeApi:
    """The live implementation. One org, one level, one token.

    `workspace_id=None` addresses the organization level.
    """

    host: str
    token: str
    workspace_id: str | None

    @classmethod
    def for_profile(cls, profile: TargetProfile, workspace_id: str | None = None) -> HttpKnowledgeApi:
        """Build from a target profile, for one workspace (the parent when none is given).

        `validate_for_publish` is deliberately not called: it checks warehouse and datasource
        keys that a knowledge-document publish never touches, so a capture-only profile would
        fail for reasons that have nothing to do with this operation.
        """
        cls._require_credentials(profile)
        return cls(
            host=profile.host,
            token=profile.token,
            workspace_id=workspace_id or profile.parent_workspace_id,
        )

    @classmethod
    def for_organization(cls, profile: TargetProfile) -> HttpKnowledgeApi:
        """Build from a target profile, for the organization level (ADR 010)."""
        cls._require_credentials(profile)
        return cls(host=profile.host, token=profile.token, workspace_id=None)

    @classmethod
    def for_level(cls, profile: TargetProfile, level: LevelId) -> HttpKnowledgeApi:
        return cls.for_organization(profile) if level is None else cls.for_profile(profile, level)

    @staticmethod
    def _require_credentials(profile: TargetProfile) -> None:
        missing = [
            name
            for name in ("host", "token")
            if not getattr(profile, name, None)
        ]
        if missing:
            raise KnowledgeDocsError(
                f"profile {profile.name!r} is missing {', '.join(missing)} — a knowledge "
                "publish needs a host and a token"
            )

    @property
    def base(self) -> str:
        if self.workspace_id is None:
            return ORGANIZATION_BASE
        return WORKSPACE_BASE.format(workspace_id=urllib.parse.quote(self.workspace_id))

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: bytes | None = None,
        content_type: str | None = None,
        raw: bool = False,
        timeout: float = 120.0,
    ) -> Any:
        url = self.host.rstrip("/") + path
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "*/*" if raw else "application/json"}
        if content_type:
            headers["Content-Type"] = content_type

        request = urllib.request.Request(url, data=payload, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:500]
            raise KnowledgeDocsError(
                f"{method} {path} -> HTTP {error.code}: {detail}", status=error.code
            ) from error
        except OSError as error:
            raise KnowledgeDocsError(f"{method} {path} -> {error}") from error

        if raw:
            return body.decode("utf-8", "replace")
        if not body:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise KnowledgeDocsError(
                f"{method} {path} -> response was not JSON: {body[:200]!r}"
            ) from error

    def list_documents(self) -> list[RemoteDocument]:
        """Every document visible here: local, inherited, and organization level.

        Paginated to completion, unlike `gd_agents.transport.entities`, which reads one page
        on purpose. Here a partial listing would mean a partial reconcile — a document on
        page two would look missing and be recreated on every run.
        """
        documents: list[RemoteDocument] = []
        params: dict[str, Any] = {"size": LIST_PAGE_SIZE, "metaInclude": "page"}
        seen_tokens: set[str] = set()

        while True:
            query = urllib.parse.urlencode(params)
            payload = self._request(f"{self.base}/documents?{query}") or {}
            for row in payload.get("documents") or []:
                documents.append(RemoteDocument.from_payload(row))

            token = payload.get("nextPageToken")
            if not token or token in seen_tokens:
                return documents
            seen_tokens.add(str(token))
            params = {"size": LIST_PAGE_SIZE, "pageToken": token}

    def download_document(self, document_id: str) -> str:
        return str(
            self._request(
                f"{self.base}/documents/{urllib.parse.quote(document_id)}/download", raw=True
            )
        )

    def upsert_document(
        self, *, filename: str, body: str, title: str, scopes: tuple[str, ...]
    ) -> UpsertResult:
        payload, content_type = _multipart(filename=filename, body=body, title=title, scopes=scopes)
        answer = (
            self._request(
                f"{self.base}/documents",
                method="PUT",
                payload=payload,
                content_type=content_type,
            )
            or {}
        )
        return UpsertResult(
            id=str(answer.get("id", "")),
            filename=str(answer.get("filename", filename)),
            success=bool(answer.get("success", True)),
            message=str(answer.get("message", "")),
            num_chunks=answer.get("numChunks"),
        )

    def delete_document(self, document_id: str) -> None:
        self._request(
            f"{self.base}/documents/{urllib.parse.quote(document_id)}", method="DELETE"
        )

    def search(
        self, query: str, *, limit: int = DEFAULT_SEARCH_LIMIT, min_score: float = 0.0
    ) -> list[SearchResult]:
        """Semantic search over chunks, across the workspace ancestor chain.

        Documented behaviour worth knowing: disabled documents are excluded, and when
        matching chunks exist at several levels the more local ones rank above inherited
        ones. This is also the cheapest evidence that a parent-level publish is reachable
        from a child.

        Refused at organization level: the org has no search endpoint of its own, and what
        matters is what a workspace sees, org-level chunks included (probed 2026-09-25).
        """
        if self.workspace_id is None:
            raise KnowledgeDocsError(
                "search runs from a workspace, not from the organization level — pass the "
                "workspace to search from"
            )
        params = urllib.parse.urlencode({"query": query, "limit": limit, "minScore": min_score})
        payload = self._request(f"{self.base}/search?{params}") or {}
        return [SearchResult.from_payload(row) for row in payload.get("results") or []]


# --- publish and verify -------------------------------------------------------


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _partition(
    remote: list[RemoteDocument], workspace_id: LevelId
) -> tuple[dict[str, RemoteDocument], list[RemoteDocument], list[RemoteDocument]]:
    """`(ours and local, ours but inherited, foreign)`, keyed by filename."""
    ours: dict[str, RemoteDocument] = {}
    inherited: list[RemoteDocument] = []
    foreign: list[RemoteDocument] = []
    for document in remote:
        if not document.is_ours():
            foreign.append(document)
        elif document.is_local_to(workspace_id):
            ours[document.filename] = document
        else:
            inherited.append(document)
    return ours, inherited, foreign


def publish_corpus(
    api: KnowledgeApi,
    documents: list[CorpusDocument],
    *,
    workspace_id: LevelId,
    target: str = "",
    apply: bool = False,
) -> KnowledgeDocsReport:
    """Upsert every document. A read-only rehearsal unless ``apply`` (ADR 002).

    Idempotency is decided by digest, not by trust: for each document already in the org, the
    raw file is downloaded and hashed. Equal hash means `unchanged` and no write at all.
    That is `compare.py`'s idea, simplified — a layout comes back normalized by the server so
    it needs a server-owned-field allowlist, whereas a file comes back byte-identical to what
    was uploaded.
    """
    report = KnowledgeDocsReport(target=target, workspace_id=workspace_id, applied=apply)

    remote = api.list_documents()
    ours, inherited, foreign = _partition(remote, workspace_id)
    report.foreign_left_alone = tuple(sorted(d.filename for d in foreign))
    report.inherited_ours = tuple(sorted(d.filename for d in inherited))

    for document in sorted(documents, key=lambda d: d.filename):
        existing = ours.get(document.filename)
        before = existing.num_chunks if existing else None

        if existing is not None:
            try:
                current = api.download_document(existing.id)
            except KnowledgeDocsError:
                # An unreadable current version is not proof of difference, but re-upserting
                # is the safe response: the cost is one write, the alternative is skipping a
                # document that may have drifted.
                current = ""
            if _digest(current) == document.digest:
                report.results.append(
                    PublishDocResult(
                        filename=document.filename, action="unchanged", num_chunks=before
                    )
                )
                report.chunk_deltas[document.filename] = (before, before)
                continue

        if not apply:
            report.results.append(
                PublishDocResult(filename=document.filename, action="would-upsert", num_chunks=before)
            )
            continue

        try:
            result = api.upsert_document(
                filename=document.filename,
                body=document.body,
                title=document.title,
                scopes=document.scopes(),
            )
        except KnowledgeDocsError as error:
            report.results.append(
                PublishDocResult(filename=document.filename, action="failed", error=str(error))
            )
            continue

        report.results.append(
            PublishDocResult(
                filename=document.filename,
                action="updated" if existing is not None else "created",
                num_chunks=result.num_chunks,
            )
        )
        report.chunk_deltas[document.filename] = (before, result.num_chunks)

    report.missing_in_org = tuple(
        sorted({d.filename for d in documents} - set(ours)) if not apply else ()
    )
    report.orphaned_in_org = tuple(sorted(set(ours) - {d.filename for d in documents}))
    return report


def verify_corpus(
    api: KnowledgeApi,
    documents: list[CorpusDocument],
    *,
    workspace_id: LevelId,
    target: str = "",
    prune: bool = False,
    apply: bool = False,
) -> KnowledgeDocsReport:
    """Reconcile the repo against the org. Reads only, unless ``prune`` and ``apply``.

    Three buckets, and the third is the one that matters: a document carrying neither our
    filename prefix nor our scope is somebody else's, is left strictly alone, and is not
    reported as ours. The channel is shared with hand-uploaded files, and a reconciler that
    owned the *workspace* rather than its own *documents* would delete them.
    """
    report = KnowledgeDocsReport(target=target, workspace_id=workspace_id, applied=apply and prune)

    remote = api.list_documents()
    ours, inherited, foreign = _partition(remote, workspace_id)
    report.foreign_left_alone = tuple(sorted(d.filename for d in foreign))
    report.inherited_ours = tuple(sorted(d.filename for d in inherited))

    expected = {document.filename: document for document in documents}
    report.missing_in_org = tuple(sorted(set(expected) - set(ours)))
    orphans = sorted(set(ours) - set(expected))
    report.orphaned_in_org = tuple(orphans)

    for filename, document in sorted(expected.items()):
        existing = ours.get(filename)
        if existing is None:
            report.results.append(PublishDocResult(filename=filename, action="would-upsert"))
            continue
        try:
            current = api.download_document(existing.id)
        except KnowledgeDocsError as error:
            report.results.append(
                PublishDocResult(filename=filename, action="failed", error=str(error))
            )
            continue
        drifted = _digest(current) != document.digest
        report.results.append(
            PublishDocResult(
                filename=filename,
                action="would-upsert" if drifted else "unchanged",
                num_chunks=existing.num_chunks,
            )
        )

    if prune and apply:
        pruned: list[str] = []
        for filename in orphans:
            api.delete_document(ours[filename].id)
            pruned.append(filename)
        report.pruned = tuple(pruned)

    return report


# --- scope: which levels a target writes, and which it vacates (ADR 010) ------

ApiFactory = Callable[[LevelId], KnowledgeApi]


def corpus_workspaces(manifest: DomainManifest) -> list[str]:
    """The parent and every domain workspace, in manifest order.

    GlobalMart has no GoodData workspace hierarchy — all thirteen report `parent=None`
    (probed 2026-09-21) — so under the `workspaces` scope each one is written directly, and
    under `organization` each one is a level our old copies may still sit at.
    """
    return [manifest.parent_workspace_id] + [
        manifest.by_key(key).workspace_id
        for key in manifest.keys()  # noqa: SIM118 - DomainManifest.keys() is a method
    ]


@dataclass
class CleanupReport:
    """One level being vacated: what of ours was there, and what became of it."""

    workspace_id: LevelId
    applied: bool
    #: Ours and local to this level: deleted under --apply, only listed otherwise.
    planned: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    failed: tuple[tuple[str, str], ...] = ()
    foreign_left_alone: tuple[str, ...] = ()
    #: The listing answered 404 — no such workspace (yet), so nothing to clean.
    absent: bool = False
    #: A tolerated refusal (D1: a 403 at organization level under the `workspaces` scope).
    skipped: str | None = None
    #: The listing failed for any other reason.
    error: str | None = None

    @property
    def level_label(self) -> str:
        return level_label(self.workspace_id)

    @property
    def incomplete(self) -> bool:
        return bool(self.failed or self.error)

    @property
    def remaining(self) -> tuple[str, ...]:
        """Ours, still present at this level after the run."""
        if not self.applied:
            return self.planned
        return tuple(name for name, _ in self.failed)

    def summary_line(self) -> str:
        label = f"{self.level_label:28s}"
        if self.error:
            return f"{label} FAILED to list — {self.error}"
        if self.absent:
            return f"{label} absent — nothing to clean"
        if self.skipped:
            return f"{label} SKIPPED — {self.skipped}"
        if self.failed:
            return (
                f"{label} FAILED  {len(self.failed)} of {len(self.planned)} — still present: "
                + ", ".join(self.remaining[:5])
            )
        if not self.planned:
            return f"{label} none of ours"
        verb = "deleted" if self.applied else "would delete"
        return f"{label} {verb} {len(self.planned)}"


def remove_ours(
    api: KnowledgeApi,
    *,
    workspace_id: LevelId,
    apply: bool,
    tolerate_forbidden: bool = False,
) -> CleanupReport:
    """Delete every document of ours that is local to one level. Lists only, unless ``apply``.

    *Every* one, not just orphans: this runs on the level a target is vacating, where each copy
    of ours is either a stale leftover or a local copy that would outrank the fresh inherited
    one. Ownership (`is_ours`) and locality (`is_local_to`) both gate a delete, as they do for
    `verify --prune`; a document with neither marker is never touched.
    """
    report = CleanupReport(workspace_id=workspace_id, applied=apply)
    try:
        remote = api.list_documents()
    except KnowledgeDocsError as error:
        if error.status == 404:
            report.absent = True
        elif error.status == 403 and tolerate_forbidden:
            report.skipped = (
                f"token cannot read {level_label(workspace_id)} knowledge (HTTP 403), so it "
                "cannot have written a copy there either"
            )
        else:
            report.error = str(error)
        return report

    local = [document for document in remote if document.is_local_to(workspace_id)]
    ours = sorted((d for d in local if d.is_ours()), key=lambda d: d.filename)
    report.foreign_left_alone = tuple(sorted(d.filename for d in local if not d.is_ours()))
    report.planned = tuple(d.filename for d in ours)

    if apply:
        deleted: list[str] = []
        failed: list[tuple[str, str]] = []
        for document in ours:
            try:
                api.delete_document(document.id)
            except KnowledgeDocsError as error:
                failed.append((document.filename, str(error)))
                continue
            deleted.append(document.filename)
        report.deleted = tuple(deleted)
        report.failed = tuple(failed)
    return report


@dataclass
class ScopedCorpusReport:
    """What `knowledge-docs publish|verify` and the rebuild step print and assert on."""

    target: str
    scope: KnowledgeScope
    applied: bool
    #: One per configured level: thirteen workspaces, one when narrowed, or the organization.
    levels: list[KnowledgeDocsReport] = field(default_factory=list)
    #: The other level(s). On verify these are always rehearsals: listed, never deleted.
    cleanup: list[CleanupReport] = field(default_factory=list)
    cleanup_deferred: str | None = None

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(
            f"{level.level_label}: {name}" for level in self.levels for name in level.failed
        )

    @property
    def cleanup_incomplete(self) -> tuple[str, ...]:
        return tuple(c.level_label for c in self.cleanup if c.incomplete)

    @property
    def other_level_ours(self) -> dict[str, tuple[str, ...]]:
        """Our copies still sitting at a level this target does not publish to."""
        return {c.level_label: c.remaining for c in self.cleanup if c.remaining}

    @property
    def stale(self) -> tuple[str, ...]:
        """Levels that do not match the repo, the other level's leftovers included."""
        labels = [level.level_label for level in self.levels if level.stale]
        labels += list(self.other_level_ours) + list(self.cleanup_incomplete)
        return tuple(dict.fromkeys(labels))

    @property
    def ok(self) -> bool:
        return not self.failed and not self.cleanup_incomplete

    def header_lines(self) -> list[str]:
        return [
            f"knowledge_scope   : {self.scope.value}",
            f"target            : {self.target}",
            f"applied           : {self.applied}",
            f"levels written    : {', '.join(level.level_label for level in self.levels) or '-'}"
            if len(self.levels) <= 3
            else f"levels written    : {len(self.levels)} workspaces",
        ]

    def cleanup_lines(self) -> list[str]:
        if self.cleanup_deferred:
            return [f"cleanup deferred  : {self.cleanup_deferred}"]
        if not self.cleanup:
            return []
        lines = [f"cleanup           : {len(self.cleanup)} level(s) this target does not publish to"]
        lines.extend(f"  {c.summary_line()}" for c in self.cleanup)
        return lines


def check_scope_flags(
    profile: TargetProfile, *, parent_only: bool, workspace_id: str | None
) -> None:
    """Refuse a flag that has no meaning under the target's scope, before any network call."""
    if profile.knowledge_scope is not KnowledgeScope.ORGANIZATION:
        return
    flag = "--parent-only" if parent_only else "--workspace-id" if workspace_id else None
    if flag is None:
        return
    raise KnowledgeScopeError(
        f"target {profile.name!r} has knowledge_scope: organization — {flag} addresses one "
        "workspace and has no meaning at organization level. Remove the flag, or set "
        "knowledge_scope: workspaces in config/targets.yaml."
    )


def _levels(
    profile: TargetProfile, workspaces: Sequence[str]
) -> tuple[list[LevelId], list[LevelId]]:
    """`(levels to write, levels to vacate)` for a target. The one place the scope is read."""
    if profile.knowledge_scope is KnowledgeScope.ORGANIZATION:
        return [None], list(workspaces)
    return list(workspaces), [None]


def _factory(profile: TargetProfile, api_factory: ApiFactory | None) -> ApiFactory:
    if api_factory is not None:
        return api_factory
    return lambda level: HttpKnowledgeApi.for_level(profile, level)


def _tolerates_forbidden(profile: TargetProfile, level: LevelId) -> bool:
    """D1: under the default scope, an unreadable organization level is skipped, not failed."""
    return profile.knowledge_scope is KnowledgeScope.WORKSPACES and level is None


def publish_for_target(
    profile: TargetProfile,
    documents: list[CorpusDocument],
    *,
    workspaces: Sequence[str],
    narrowed: bool = False,
    apply: bool = False,
    api_factory: ApiFactory | None = None,
) -> ScopedCorpusReport:
    """Write the corpus at the target's level(s), then vacate the other level (ADR 010).

    Write first, clean second, and clean only if every write succeeded: the copy being
    removed may be the only working one, so a failed org upsert must never be followed by
    deleting the thirteen workspace copies. A narrowed publish (`--parent-only`,
    `--workspace-id`) never vacates the organization level — removing the org copy after
    writing one workspace would leave twelve with nothing.
    """
    factory = _factory(profile, api_factory)
    write, clean = _levels(profile, workspaces)
    report = ScopedCorpusReport(target=profile.name, scope=profile.knowledge_scope, applied=apply)

    for level in write:
        report.levels.append(
            publish_corpus(factory(level), documents, workspace_id=level, target=profile.name, apply=apply)
        )

    if narrowed:
        report.cleanup_deferred = "narrowed publish — the organization level is left as it is"
        return report
    if report.failed:
        failed_at = sorted({level.level_label for level in report.levels if level.failed})
        report.cleanup_deferred = (
            f"write failed at {', '.join(failed_at)} — copies at the other level are left "
            "as the working ones"
        )
        return report

    for level in clean:
        report.cleanup.append(
            remove_ours(
                factory(level),
                workspace_id=level,
                apply=apply,
                tolerate_forbidden=_tolerates_forbidden(profile, level),
            )
        )
    return report


def verify_for_target(
    profile: TargetProfile,
    documents: list[CorpusDocument],
    *,
    workspaces: Sequence[str],
    narrowed: bool = False,
    prune: bool = False,
    apply: bool = False,
    api_factory: ApiFactory | None = None,
) -> ScopedCorpusReport:
    """Reconcile the target's level(s); report, never delete, our copies at the other level.

    Prune stays at the configured level(s). A leftover at the other level is stale — it
    shadows or duplicates what the target publishes — and the fix is a `publish --apply`,
    which vacates it; `verify` only names it.
    """
    factory = _factory(profile, api_factory)
    write, clean = _levels(profile, workspaces)
    report = ScopedCorpusReport(
        target=profile.name, scope=profile.knowledge_scope, applied=apply and prune
    )
    for level in write:
        report.levels.append(
            verify_corpus(
                factory(level),
                documents,
                workspace_id=level,
                target=profile.name,
                prune=prune,
                apply=apply,
            )
        )
    for level in clean:
        report.cleanup.append(
            remove_ours(
                factory(level),
                workspace_id=level,
                apply=False,
                tolerate_forbidden=_tolerates_forbidden(profile, level),
            )
        )
    return report
