"""One-shot: probe the organization-level AI Knowledge endpoint before FEAT-017 relies on it.

**This is not part of the runtime CLI.** ADR 010 assumes five things about the organization
level that were read from documentation and never exercised against a real org. This script
checks them, prints a findings block, and that block is what ADR 010 and the
`knowledge_docs.py` docstring cite.

    P1  /api/v1/ai/organization/knowledge/documents exists, and lists like the workspace one
    P2  what `workspaceId` an org-level document reports, in an org and a workspace listing
    P3  whether an org listing includes workspace-level documents
    P4  whether a workspace-level search returns org-level chunks
    P5  what the endpoint answers when the token may not read it (403 vs 404)

By default it issues ``GET`` requests only. P4 is answered read-only when an org-level document
already exists; otherwise it needs ``--apply``, which uploads one document at organization
level, searches for it from ``--workspace-id``, and deletes it in a ``finally``. An
organization-level document is visible from **every** workspace in the org, so ``--apply``
belongs on an org that holds only GlobalMart — never on a shared one (ADR 009). The probe
document is named ``gm-probe__…`` and carries no ``globalmart-corpus`` scope, so no corpus
reconcile can ever adopt it as its own.

Usage:

    uv run python scripts/probe_org_knowledge.py --target demo-cloud
    uv run python scripts/probe_org_knowledge.py --target <dedicated-org> --apply
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.parse
import uuid
from typing import Any

from globalmart.config import load_env, load_profile
from globalmart.knowledge_docs import (
    ORGANIZATION_BASE,
    HttpKnowledgeApi,
    KnowledgeDocsError,
    _multipart,
)

PROBE_FILENAME = "gm-probe__org-level.md"
#: Seconds to wait for chunking before searching. Upsert answers once the document is stored;
#: whether it is searchable at that instant is not documented, so the search is retried.
SEARCH_RETRIES = 6
SEARCH_INTERVAL = 5.0


def _get(api: HttpKnowledgeApi, path: str) -> tuple[int | None, Any, str]:
    """`(status, payload, error)`. Status is None when the call succeeded."""
    try:
        return None, api._request(path), ""
    except KnowledgeDocsError as error:
        return error.status or -1, None, str(error)


def _rows(payload: Any) -> list[dict[str, Any]]:
    return list((payload or {}).get("documents") or [])


def _describe(rows: list[dict[str, Any]]) -> list[str]:
    return [
        f"    {row.get('filename')!s:55s} workspaceId={row.get('workspaceId')!r} "
        f"scopes={row.get('scopes')!r}"
        for row in rows[:15]
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--target", required=True)
    parser.add_argument("--workspace-id", help="workspace to list and search from (default: parent)")
    parser.add_argument("--apply", action="store_true", help="P4 write half — dedicated org only")
    args = parser.parse_args(argv)

    load_env()
    profile = load_profile(args.target)
    workspace = HttpKnowledgeApi.for_profile(profile, args.workspace_id)
    findings: list[str] = [
        f"probe             : {time.strftime('%Y-%m-%d')} target={profile.name} "
        f"org={profile.organization_id} workspace={workspace.workspace_id}"
    ]

    # P1 / P5 — the org listing.
    query = urllib.parse.urlencode({"size": 200, "metaInclude": "page"})
    status, org_payload, error = _get(workspace, f"{ORGANIZATION_BASE}/documents?{query}")
    if status is not None:
        findings.append(f"P1 org listing    : HTTP {status} — {error[:300]}")
        findings.append("P5 access         : see P1 status (403 = token may not read org level)")
    else:
        org_rows = _rows(org_payload)
        findings.append(
            f"P1 org listing    : OK, {len(org_rows)} document(s), "
            f"keys={sorted((org_payload or {}).keys())}"
        )
        findings.extend(_describe(org_rows))
        findings.append("P5 access         : readable with this token")
        ws_ids = {row.get("workspaceId") for row in org_rows}
        findings.append(f"P3 workspaceIds   : in org listing = {sorted(map(repr, ws_ids))}")

    # P2 — the workspace listing, and which rows it reports as not local.
    status, ws_payload, error = _get(workspace, f"{workspace.base}/documents?{query}")
    if status is not None:
        findings.append(f"P2 ws listing     : HTTP {status} — {error[:300]}")
        ws_rows = []
    else:
        ws_rows = _rows(ws_payload)
        not_local = [r for r in ws_rows if r.get("workspaceId") != workspace.workspace_id]
        findings.append(
            f"P2 ws listing     : {len(ws_rows)} document(s), {len(not_local)} not local "
            f"(workspaceId values: {sorted({repr(r.get('workspaceId')) for r in ws_rows})})"
        )
        findings.extend(_describe(not_local))

    # P4 — read-only when an org-level document already exists.
    org_level = [r for r in ws_rows if r.get("workspaceId") in (None, "")]
    if org_level and not args.apply:
        title = str(org_level[0].get("title") or org_level[0].get("filename"))
        hits = workspace.search(title, limit=10)
        from_org = [h for h in hits if h.workspace_id in (None, "")]
        findings.append(
            f"P4 search (ro)    : query={title!r}: {len(hits)} hit(s), {len(from_org)} org-level"
        )
    elif not args.apply:
        findings.append("P4 search         : not answered — no org-level document exists; needs --apply")
    else:
        findings.extend(_probe_write(workspace))

    print("\n".join(findings))
    return 0


def _probe_write(workspace: HttpKnowledgeApi) -> list[str]:
    """Upload one org-level document, search for it from a workspace, delete it."""
    sentinel = f"globalmart-probe-{uuid.uuid4().hex[:12]}"
    body = (
        "# GlobalMart organization-level probe\n\n"
        f"This document exists only to test inheritance. The sentinel phrase is {sentinel}. "
        "It is deleted by the script that created it.\n"
    )
    org = HttpKnowledgeApi(host=workspace.host, token=workspace.token, workspace_id=None)
    out: list[str] = []
    document_id = ""
    try:
        payload, content_type = _multipart(
            filename=PROBE_FILENAME, body=body, title="GlobalMart org-level probe", scopes=()
        )
        answer = org._request(
            f"{org.base}/documents", method="PUT", payload=payload, content_type=content_type
        ) or {}
        document_id = str(answer.get("id", ""))
        out.append(f"P4 org upsert     : {answer!r}")

        # P2 / P3 while the document exists: how each listing reports it.
        _, org_listing, _ = _get(org, f"{ORGANIZATION_BASE}/documents?size=200")
        probe_rows = [r for r in _rows(org_listing) if r.get("filename") == PROBE_FILENAME]
        out.append(f"P3 org listing    : {len(_rows(org_listing))} document(s); probe row:")
        out.extend(_describe(probe_rows))
        _, ws_listing, _ = _get(workspace, f"{workspace.base}/documents?size=200")
        ws_probe = [r for r in _rows(ws_listing) if r.get("filename") == PROBE_FILENAME]
        out.append(
            f"P2 ws listing     : {len(_rows(ws_listing))} document(s); probe row "
            f"{'present' if ws_probe else 'ABSENT'}:"
        )
        out.extend(_describe(ws_probe))

        for attempt in range(1, SEARCH_RETRIES + 1):
            hits = workspace.search(sentinel, limit=10)
            ours = [h for h in hits if h.filename == PROBE_FILENAME]
            if ours:
                out.append(
                    f"P4 search         : found after {attempt} attempt(s); "
                    f"workspaceId={ours[0].workspace_id!r} score={ours[0].score:.3f}"
                )
                break
            time.sleep(SEARCH_INTERVAL)
        else:
            out.append(
                f"P4 search         : NOT FOUND from {workspace.workspace_id} "
                f"after {SEARCH_RETRIES} tries"
            )
    except KnowledgeDocsError as error:
        out.append(f"P4 write          : FAILED — {error}")
    finally:
        if not document_id:
            _, listing, _ = _get(org, f"{ORGANIZATION_BASE}/documents?size=200")
            document_id = next(
                (str(r["id"]) for r in _rows(listing) if r.get("filename") == PROBE_FILENAME), ""
            )
        if document_id:
            try:
                org.delete_document(document_id)
                out.append(f"P4 cleanup        : deleted {document_id}")
            except KnowledgeDocsError as error:
                out.append(f"P4 cleanup        : DELETE FAILED — remove {PROBE_FILENAME} by hand: {error}")
    return out


if __name__ == "__main__":
    sys.exit(main())
