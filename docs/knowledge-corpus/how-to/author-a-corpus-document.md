---
kind: how_to
title: Add or change a document in this corpus
scope: ai-context
owner: analytics-eng
anchor: true
---

# Add or change a document in this corpus

## Where the file goes

Under `docs/knowledge-corpus/<kind>/<slug>.md`, where the directory is the Diátaxis kind for
readers and the front matter is what the tooling reads. The published name is derived —
`gm-corpus__<kind>__<slug>.md` — so two files with the same stem under different kinds do not
collide, and two with the same stem under the same kind fail the build rather than
overwriting each other in the org.

## The front matter

    ---
    kind: reference        # tutorial | how_to | reference | explanation
    title: Fact tables     # what a reader sees
    scope: data-model      # the topic group
    owner: analytics-eng   # who answers a question about this file
    domains: [finance]     # optional; becomes domain/<key> scopes
    anchor: true           # optional; may a retrieval question cite this document?
    covers:                # optional; which layout objects this documents
      metrics: ["metric_l1_*"]
      datasets: ["fact_order_header"]
    ---

`kind`, `title`, `scope` and `owner` are required. An unknown key fails the build, because a
typo must not silently mean "documents nothing".

## Write one subject, in `##` sections

The server chunks on structure, so the structure is the part an author controls. One `#`
title, then `##` sections each carrying one idea. A section must be at least 120 characters —
a heading with one line under it retrieves as a fragment with no context — and at most
3,000, which is roughly where a section has stopped being one idea. A whole document caps at
24,000 characters; past that it is a topic group and should be split.

## Then run the build

    globalmart knowledge-docs build        # front matter, structure, sizes, question grounding
    globalmart knowledge-docs coverage     # is anything in the workspace now undocumented?

Both are offline and both run in CI. `coverage` is the one that will stop you: if you
renamed an object, the `covers:` pattern that no longer matches anything fails the build and
names the file.

## Publishing

    globalmart knowledge-docs publish --target <profile>            # rehearsal
    globalmart knowledge-docs publish --target <profile> --apply     # write
    globalmart knowledge-docs verify --target <profile>              # repo versus org

Publishing is idempotent: each document's bytes are hashed against what the org holds, and
an unchanged document is not rewritten. A document in the org that is not ours — anything
without the `gm-corpus__` prefix or the `globalmart-corpus` scope — is never touched, because
the channel is shared with files people upload through the UI.

## If you edit an anchored sentence

A document marked `anchor: true` may be cited by `config/corpus-questions.yaml`, and the
build checks that every expected fact still appears in it verbatim. Rewriting such a sentence
fails the build locally with the question id, which is the intended outcome: either restore
the wording or update the question, but do not let a live retrieval check be the thing that
discovers it.
