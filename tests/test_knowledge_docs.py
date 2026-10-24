"""Publishing to AI Knowledge, and reconciling what is there.

The test that matters in this feature is
`test_a_publish_never_touches_a_document_it_does_not_own`. AI Knowledge has a UI, so the
channel is shared with files a colleague uploaded by hand, and a reconciler that owned the
*workspace* rather than its own *documents* would delete them. FEAT-008 learned this on the
memory-item channel where the blast radius was one directive; here it is a whole file.

No live host: `FakeKnowledgeApi` satisfies the `KnowledgeApi` protocol structurally.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from globalmart.config import KnowledgeScope, TargetProfile
from globalmart.corpus import CorpusDocument, load_corpus
from globalmart.domains import load_domains
from globalmart.knowledge_docs import (
    DEFAULT_SEARCH_LIMIT,
    OWNER_SCOPE,
    HttpKnowledgeApi,
    KnowledgeDocsError,
    RemoteDocument,
    SearchResult,
    UpsertResult,
    _multipart,
    corpus_workspaces,
    publish_corpus,
    publish_for_target,
    verify_corpus,
    verify_for_target,
)

FIXTURES = Path(__file__).parent / "fixtures" / "corpus"
CORPUS = FIXTURES / "corpus"
WORKSPACE = "globalmart"


@dataclass
class FakeKnowledgeApi:
    """An in-memory org. Records every write, so a rehearsal can be proved silent."""

    documents: dict[str, RemoteDocument] = field(default_factory=dict)
    bodies: dict[str, str] = field(default_factory=dict)
    upserts: list[str] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    downloads: list[str] = field(default_factory=list)
    searches: list[str] = field(default_factory=list)
    search_results: list[SearchResult] = field(default_factory=list)
    pages: int = 1
    fail_download: bool = False
    #: The workspace this fake answers for.
    level: str = WORKSPACE
    #: Raised by `list_documents`, e.g. a 404 for a workspace that does not exist yet.
    list_error: KnowledgeDocsError | None = None
    fail_upsert: bool = False
    #: Filenames whose delete is refused.
    fail_delete: set[str] = field(default_factory=set)

    def seed(
        self,
        filename: str,
        body: str,
        *,
        scopes: tuple[str, ...] = (OWNER_SCOPE,),
        workspace_id: str | None = WORKSPACE,
        num_chunks: int = 3,
    ) -> RemoteDocument:
        document = RemoteDocument(
            id=f"id-{len(self.documents) + 1}",
            filename=filename,
            title=filename,
            scopes=scopes,
            num_chunks=num_chunks,
            workspace_id=workspace_id,
        )
        self.documents[filename] = document
        self.bodies[document.id] = body
        return document

    # --- the protocol ---

    def list_documents(self) -> list[RemoteDocument]:
        if self.list_error is not None:
            raise self.list_error
        return list(self.documents.values())

    def download_document(self, document_id: str) -> str:
        self.downloads.append(document_id)
        if self.fail_download:
            raise KnowledgeDocsError("download refused")
        return self.bodies.get(document_id, "")

    def upsert_document(
        self, *, filename: str, body: str, title: str, scopes: tuple[str, ...]
    ) -> UpsertResult:
        if self.fail_upsert:
            raise KnowledgeDocsError(f"upsert of {filename} refused", status=500)
        self.upserts.append(filename)
        existing = self.documents.get(filename)
        document = RemoteDocument(
            id=existing.id if existing else f"id-{len(self.documents) + 1}",
            filename=filename,
            title=title,
            scopes=scopes,
            num_chunks=len(body) // 500 + 1,
            workspace_id=self.level,
        )
        self.documents[filename] = document
        self.bodies[document.id] = body
        return UpsertResult(
            id=document.id,
            filename=filename,
            success=True,
            message="ok",
            num_chunks=document.num_chunks,
        )

    def delete_document(self, document_id: str) -> None:
        refused = {self.documents[name].id for name in self.fail_delete if name in self.documents}
        if document_id in refused:
            raise KnowledgeDocsError(f"delete of {document_id} refused", status=500)
        self.deletes.append(document_id)
        for filename, document in list(self.documents.items()):
            if document.id == document_id:
                del self.documents[filename]

    def search(
        self, query: str, *, limit: int = DEFAULT_SEARCH_LIMIT, min_score: float = 0.0
    ) -> list[SearchResult]:
        self.searches.append(query)
        return self.search_results[:limit]


@pytest.fixture
def documents() -> list[CorpusDocument]:
    return load_corpus(CORPUS)


# --- ownership ----------------------------------------------------------------


def test_is_ours_accepts_either_marker() -> None:
    """An OR, not an AND: one missing field must not turn our corpus into foreign content."""
    by_prefix = RemoteDocument(id="1", filename="gm-corpus__reference__a.md", scopes=())
    by_scope = RemoteDocument(id="2", filename="handbook.md", scopes=(OWNER_SCOPE,))
    neither = RemoteDocument(id="3", filename="handbook.pdf", scopes=("finance",))

    assert by_prefix.is_ours()
    assert by_scope.is_ours()
    assert not neither.is_ours()


def test_only_a_locally_managed_document_is_local() -> None:
    """An inherited or org-level document is read-only from below — never a prune candidate."""
    local = RemoteDocument(id="1", filename="gm-corpus__reference__a.md", workspace_id=WORKSPACE)
    inherited = RemoteDocument(id="2", filename="gm-corpus__reference__b.md", workspace_id="parent")
    org = RemoteDocument(id="3", filename="gm-corpus__reference__c.md", workspace_id=None)

    assert local.is_local_to(WORKSPACE)
    assert not inherited.is_local_to(WORKSPACE)
    assert not org.is_local_to(WORKSPACE)


def test_remote_documents_parse_from_the_listing_payload() -> None:
    document = RemoteDocument.from_payload(
        {
            "id": "abc",
            "filename": "gm-corpus__reference__a.md",
            "numChunks": 4,
            "scopes": ["globalmart-corpus", "kind/reference"],
            "title": "A",
            "workspaceId": "globalmart",
            "isDisabled": False,
        }
    )
    assert document.num_chunks == 4
    assert document.scopes == ("globalmart-corpus", "kind/reference")


# --- publish ------------------------------------------------------------------


def test_a_rehearsal_issues_no_writes(documents: list[CorpusDocument]) -> None:
    api = FakeKnowledgeApi()
    report = publish_corpus(api, documents, workspace_id=WORKSPACE, apply=False)

    assert api.upserts == []
    assert api.deletes == []
    assert {result.action for result in report.results} == {"would-upsert"}
    assert report.changed


def test_publishing_creates_every_document(documents: list[CorpusDocument]) -> None:
    api = FakeKnowledgeApi()
    report = publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)

    assert len(api.upserts) == len(documents)
    assert {result.action for result in report.results} == {"created"}
    assert report.failed == ()


def test_a_second_publish_with_an_unchanged_repo_reports_no_change(
    documents: list[CorpusDocument],
) -> None:
    """Idempotency by digest, not by trust — the thing FEAT-002 had to fix twice."""
    api = FakeKnowledgeApi()
    publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)
    api.upserts.clear()

    second = publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)

    assert api.upserts == []
    assert {result.action for result in second.results} == {"unchanged"}
    assert not second.changed


def test_an_edited_document_is_updated_not_recreated(documents: list[CorpusDocument]) -> None:
    api = FakeKnowledgeApi()
    publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)

    target = documents[0].filename
    api.bodies[api.documents[target].id] = "something else entirely\n"
    report = publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)

    actions = {result.filename: result.action for result in report.results}
    assert actions[target] == "updated"
    assert set(actions.values()) == {"updated", "unchanged"}


def test_a_publish_never_touches_a_document_it_does_not_own(
    documents: list[CorpusDocument],
) -> None:
    """The one that matters. AI Knowledge has a UI; a hand-uploaded file is legitimate."""
    api = FakeKnowledgeApi()
    foreign = api.seed("finance-handbook.pdf", "not ours", scopes=("finance",))

    report = publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)

    assert report.foreign_left_alone == ("finance-handbook.pdf",)
    assert foreign.filename not in report.orphaned_in_org
    assert foreign.id not in api.deletes
    assert api.documents["finance-handbook.pdf"] is foreign


def test_an_inherited_document_of_ours_is_reported_but_not_orphaned(
    documents: list[CorpusDocument],
) -> None:
    api = FakeKnowledgeApi()
    api.seed(
        "gm-corpus__reference__from-the-parent.md",
        "inherited",
        workspace_id="some-other-workspace",
    )
    report = publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)

    assert report.inherited_ours == ("gm-corpus__reference__from-the-parent.md",)
    assert report.orphaned_in_org == ()


def test_an_unreadable_current_version_is_re_upserted(documents: list[CorpusDocument]) -> None:
    """Not proof of difference, but the safe response: one wasted write beats a skipped one."""
    api = FakeKnowledgeApi()
    publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)
    api.upserts.clear()
    api.fail_download = True

    report = publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)

    assert len(api.upserts) == len(documents)
    assert {result.action for result in report.results} == {"updated"}


def test_a_failed_upsert_is_recorded_and_does_not_stop_the_rest(
    documents: list[CorpusDocument], monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeKnowledgeApi()
    original = api.upsert_document
    calls = {"n": 0}

    def flaky(**kwargs: object) -> UpsertResult:
        calls["n"] += 1
        if calls["n"] == 1:
            raise KnowledgeDocsError("507 insufficient storage")
        return original(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(api, "upsert_document", flaky)
    report = publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)

    assert len(report.failed) == 1
    assert len(report.results) == len(documents)


def test_chunk_counts_are_logged_and_asserted_on_by_nothing(
    documents: list[CorpusDocument],
) -> None:
    """Chunking is the server's business; a count is a diagnostic, never a contract."""
    api = FakeKnowledgeApi()
    publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)

    target = documents[0].filename
    api.documents[target] = RemoteDocument(
        id=api.documents[target].id,
        filename=target,
        num_chunks=99,
        scopes=(OWNER_SCOPE,),
        workspace_id=WORKSPACE,
    )
    api.bodies[api.documents[target].id] = "changed\n"

    report = publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)

    before, after = report.chunk_deltas[target]
    assert before == 99
    assert after != 99


# --- verify and prune ---------------------------------------------------------


def test_verify_on_a_matching_org_is_clean(documents: list[CorpusDocument]) -> None:
    api = FakeKnowledgeApi()
    publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)

    report = verify_corpus(api, documents, workspace_id=WORKSPACE)

    assert report.missing_in_org == ()
    assert report.orphaned_in_org == ()
    assert not report.changed


def test_verify_separates_missing_orphaned_and_foreign(documents: list[CorpusDocument]) -> None:
    api = FakeKnowledgeApi()
    publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)

    # one of ours deleted from the org, one of ours left behind, one file that is not ours
    dropped = documents[0].filename
    del api.documents[dropped]
    api.seed("gm-corpus__reference__deleted-last-month.md", "stale")
    api.seed("quarterly-review.pdf", "not ours", scopes=())

    report = verify_corpus(api, documents, workspace_id=WORKSPACE)

    assert report.missing_in_org == (dropped,)
    assert report.orphaned_in_org == ("gm-corpus__reference__deleted-last-month.md",)
    assert report.foreign_left_alone == ("quarterly-review.pdf",)


def test_a_drifted_document_is_reported_as_needing_an_upsert(
    documents: list[CorpusDocument],
) -> None:
    api = FakeKnowledgeApi()
    publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)
    target = documents[0].filename
    api.bodies[api.documents[target].id] = "someone edited this in the UI\n"

    report = verify_corpus(api, documents, workspace_id=WORKSPACE)

    actions = {result.filename: result.action for result in report.results}
    assert actions[target] == "would-upsert"
    assert report.changed


def test_prune_without_apply_deletes_nothing(documents: list[CorpusDocument]) -> None:
    api = FakeKnowledgeApi()
    publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)
    api.seed("gm-corpus__reference__orphan.md", "stale")

    report = verify_corpus(api, documents, workspace_id=WORKSPACE, prune=True, apply=False)

    assert api.deletes == []
    assert report.orphaned_in_org == ("gm-corpus__reference__orphan.md",)
    assert report.pruned == ()


def test_prune_deletes_exactly_the_orphans(documents: list[CorpusDocument]) -> None:
    api = FakeKnowledgeApi()
    publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)
    orphan = api.seed("gm-corpus__reference__orphan.md", "stale")
    foreign = api.seed("handbook.pdf", "not ours", scopes=())
    inherited = api.seed("gm-corpus__reference__inherited.md", "upstream", workspace_id="other-workspace")

    report = verify_corpus(api, documents, workspace_id=WORKSPACE, prune=True, apply=True)

    assert api.deletes == [orphan.id]
    assert report.pruned == ("gm-corpus__reference__orphan.md",)
    assert foreign.filename in api.documents
    assert inherited.filename in api.documents


# --- the wire format ----------------------------------------------------------


def test_the_multipart_body_repeats_the_scopes_field() -> None:
    """The documented curl form, and what the FastAPI-shaped endpoint parses into a list.

    The generated TypeScript client comma-joins instead; that would arrive as a single scope
    with commas in it, so it is deliberately not followed.
    """
    payload, content_type = _multipart(
        filename="gm-corpus__reference__a.md",
        body="# hello\n",
        title="A",
        scopes=("globalmart-corpus", "kind/reference"),
    )
    text = payload.decode()

    assert content_type.startswith("multipart/form-data; boundary=")
    assert text.count('name="scopes"') == 2
    assert "globalmart-corpus,kind/reference" not in text
    assert 'filename="gm-corpus__reference__a.md"' in text
    assert "Content-Type: text/markdown" in text
    assert "# hello" in text


def test_the_body_uploaded_is_the_body_digested(documents: list[CorpusDocument]) -> None:
    """Idempotency depends on this: what we hash must be exactly what we send."""
    api = FakeKnowledgeApi()
    publish_corpus(api, documents, workspace_id=WORKSPACE, apply=True)

    document = documents[0]
    stored = api.bodies[api.documents[document.filename].id]
    assert hashlib.sha256(stored.encode()).hexdigest() == document.digest


# --- per target: the given workspaces, and no other level ---------------------

WORKSPACES = ("globalmart", "globalmart-finance", "globalmart-risk")


def scoped_profile() -> TargetProfile:
    return TargetProfile(
        name="dedicated",
        host="https://example.gooddata.com",
        token="tok",
        organization_id="org",
        datasource_id="ds",
        datasource_schema="globalmart",
        knowledge_scope=KnowledgeScope.WORKSPACES,
    )


@dataclass
class FakeOrg:
    """One `FakeKnowledgeApi` per workspace; calling it is the `api_factory`.

    Records every level the factory is asked for, so a test can prove the organization level
    (anything that is not one of the given workspaces) is never addressed.
    """

    levels: dict[str, FakeKnowledgeApi] = field(default_factory=dict)
    requested: list[object] = field(default_factory=list)

    def __call__(self, level: str) -> FakeKnowledgeApi:
        self.requested.append(level)
        return self.at(level)

    def at(self, level: str) -> FakeKnowledgeApi:
        return self.levels.setdefault(level, FakeKnowledgeApi(level=level))

    def seed_corpus(self, level: str, documents: list[CorpusDocument]) -> None:
        for document in documents:
            self.at(level).seed(document.filename, document.body, workspace_id=level)


def test_the_live_api_addresses_only_a_workspace_endpoint() -> None:
    api = HttpKnowledgeApi.for_profile(scoped_profile(), "globalmart-risk")
    assert api.base == "/api/v1/ai/workspaces/globalmart-risk/knowledge"
    assert HttpKnowledgeApi.for_profile(scoped_profile()).workspace_id == "globalmart"
    assert not hasattr(HttpKnowledgeApi, "for_organization")


def test_corpus_workspaces_is_the_parent_and_every_domain() -> None:
    manifest = load_domains(Path(__file__).resolve().parents[1] / "config" / "domains.yaml")
    workspaces = corpus_workspaces(manifest)
    assert workspaces[0] == manifest.parent_workspace_id
    assert len(workspaces) == 13
    assert len(set(workspaces)) == 13


def test_publish_for_target_writes_every_given_workspace(documents: list[CorpusDocument]) -> None:
    org = FakeOrg()
    report = publish_for_target(
        scoped_profile(), documents, workspaces=WORKSPACES, apply=True, api_factory=org
    )

    assert report.ok
    assert [level.workspace_id for level in report.levels] == list(WORKSPACES)
    for workspace in WORKSPACES:
        assert len(org.at(workspace).upserts) == len(documents)


@pytest.mark.parametrize("apply", [False, True])
def test_publish_for_target_never_addresses_the_organization_level(
    documents: list[CorpusDocument], apply: bool
) -> None:
    """Org level belongs to the org repo: no call, no listing, no cleanup — ever."""
    org = FakeOrg()
    for workspace in WORKSPACES:
        org.seed_corpus(workspace, documents)

    report = publish_for_target(
        scoped_profile(), documents, workspaces=WORKSPACES, apply=apply, api_factory=org
    )

    assert org.requested == list(WORKSPACES)
    assert None not in org.levels
    assert all(api.deletes == [] for api in org.levels.values())
    assert not hasattr(report, "cleanup")
    assert not any("cleanup" in line or "organization" in line for line in report.header_lines())


def test_a_narrowed_publish_addresses_only_that_workspace(documents: list[CorpusDocument]) -> None:
    org = FakeOrg()
    publish_for_target(scoped_profile(), documents, workspaces=["globalmart"], apply=True, api_factory=org)
    assert org.requested == ["globalmart"]


def test_verify_prune_never_deletes_an_org_level_or_another_workspaces_document(
    documents: list[CorpusDocument],
) -> None:
    """A `workspaceId: null` document is org level, owned by the org repo; never ours to delete."""
    org = FakeOrg()
    org.seed_corpus("globalmart", documents)
    here = org.at("globalmart")
    orphan = here.seed("gm-corpus__reference__orphan.md", "stale")
    org_level = here.seed("gm-corpus__reference__org-copy.md", "org repo's", workspace_id=None)
    elsewhere = here.seed("gm-corpus__reference__elsewhere.md", "upstream", workspace_id="other")

    report = verify_for_target(
        scoped_profile(),
        documents,
        workspaces=["globalmart"],
        prune=True,
        apply=True,
        api_factory=org,
    )

    assert here.deletes == [orphan.id]
    assert org_level.filename in here.documents
    assert elsewhere.filename in here.documents
    assert report.levels[0].pruned == (orphan.filename,)
    assert set(report.levels[0].inherited_ours) == {org_level.filename, elsewhere.filename}
    assert org.requested == ["globalmart"]


def test_verify_on_a_matching_target_is_clean(documents: list[CorpusDocument]) -> None:
    org = FakeOrg()
    for workspace in WORKSPACES:
        org.seed_corpus(workspace, documents)

    report = verify_for_target(scoped_profile(), documents, workspaces=WORKSPACES, api_factory=org)

    assert report.stale == ()
    assert report.ok
    assert org.requested == list(WORKSPACES)


def test_verify_names_the_stale_workspace(documents: list[CorpusDocument]) -> None:
    org = FakeOrg()
    org.seed_corpus("globalmart", documents)

    report = verify_for_target(scoped_profile(), documents, workspaces=WORKSPACES, api_factory=org)

    assert report.stale == ("globalmart-finance", "globalmart-risk")
