# Knowledge

GlobalMart's assistant knows only what the semantic layer names. Nothing tells it which of
two similarly named revenue metrics an analyst means, or that "last quarter" means a fiscal
quarter. This is the path from a document into the workspace.

```bash
globalmart knowledge build            # compile docs/knowledge/*.md into the layout tree
globalmart knowledge build --check    # CI gate: exit 1 if the tree is out of date
```

Then publish as usual — the items are part of the layout, so `publish parent` carries them.

## Superseded: there *is* a document-upload API

This document originally stated that no knowledge-document API existed — "checked against
the GoodData API client and gdc-nas on 2026-09-18: no knowledge-document model, no file
ingestion". That was true of the Python SDK's surface and false of the platform. The AI
Knowledge document API shipped 2026-03-26 and was re-verified on 2026-09-21:
`PUT /api/v1/ai/workspaces/{id}/knowledge/documents` accepts whole Markdown files.

FEAT-015 uses it, and the two channels now live side by side — see
[ADR 009](../specs/decisions/009-two-ai-knowledge-channels.md) and
`docs/knowledge-corpus/`:

| | this page (memory items) | the corpus (knowledge documents) |
|---|---|---|
| Unit | a paragraph, ≤ 255 chars | a whole document |
| Source | `docs/knowledge/*.md` | `docs/knowledge-corpus/<kind>/*.md` |
| Command | `globalmart knowledge build` | `globalmart knowledge-docs publish` |
| Travels by | the layout tree, copied per domain | its own API call, inherited at read time |

Write a standing directive here. Write documentation to look up there. Do not write both.

Memory items live under `analytics`, not `ldm` — knowledge is analytics-layer content, so
none of this touches the semantic model.

## Write short directives, not prose

**The API caps `instruction` at 255 characters.** A memory item is a short directive, not a
document, and that single fact shapes everything here.

So the unit of compilation is a **paragraph**, not a section. Write one idea per paragraph,
separated by a blank line, and each becomes its own retrievable item. A paragraph over 255
characters fails the build, naming the file, the heading and the paragraph's opening words.

A bullet list is kept whole, because its items are one thought — splitting a list into five
unrelated directives loses the thing that made it a list. Keep lists short enough to fit.

```markdown
---
domains: [finance]        # optional; omit for universal knowledge
keywords: [margin]        # optional; added to the ones derived from the heading
strategy: AUTO            # AUTO (retrieved on relevance) or ALWAYS (every prompt)
---

# Document title

## A heading

One idea, under 255 characters. This becomes a memory item.

A second idea. This becomes a second memory item, with the same title and keywords.
```

| Markdown | Memory item |
|---|---|
| `##` heading | `title`, and the source of derived `keywords` |
| one paragraph | `instruction` (≤ 255 chars) |
| document + heading + path | `description` — provenance, so the item is traceable back |
| `domains:` front matter | `domain/<key>` tags, which FEAT-004 filters on |
| no `domains:` | `knowledge/shared` tag — reaches every child |
| `strategy:` front matter | `strategy`, defaulting to `AUTO` |

Ids are `<file-stem>_<heading-slug>`, with a two-digit suffix when a section holds several
paragraphs. Index-based, so fixing a typo shows as an *update* rather than a delete plus a
create; the cost is that inserting a paragraph shifts the ids after it.

## Universal versus per-domain

A document that lists `domains:` is tagged `domain/finance`, `domain/sales` and so on, and
the splitter gives it only to those children.

A document that lists none is **universal** — metric naming conventions apply everywhere —
and is tagged `knowledge/shared`. `config/domains.yaml` selects that tag under `shared.ai`,
so every child gets it.

Both are explicit. "No domains" deliberately does not mean "no domain", because that would
leave the item uncovered and fail `domains validate --strict` — which is the right outcome
for an item nobody classified, and the wrong one for a deliberately universal one.

## Ownership: marked, not positional

Every compiled item carries the reserved tag **`knowledge`**. A build reconciles only
against items carrying it: it creates, updates and removes within that set, and leaves every
other memory item alone.

This matters because the channel is shared. A capture pulls back whatever the org holds, and
hand-authored items are legitimate. A build that owned *the directory* rather than *the
objects* would delete them the first time it ran.

## Run it after capture, not before

`bootstrap` and `knowledge build` both write the same tree, and the writer prunes orphans.

- **bootstrap → knowledge build → publish.** This is the order.
- A `bootstrap` *after* a build, against an org that lacks the items, removes them from the
  tree. That is correct — the tree mirrors the org — but it surprises, so it is worth
  saying out loud.
- Once the items have been published, the cycle converges: a capture returns them and the
  next build re-emits them identically. `test_the_capture_then_build_cycle_converges` proves
  that without a host.

## Verified live, 2026-09-20

14 items compiled from `docs/knowledge/metric-hierarchy.md`, published to `demo-cloud`, and
read back from the org:

```
GET /api/v1/entities/workspaces/globalmart/memoryItems  ->  14 items
second publish                                          ->  changed: False
every one of the 12 domain children                     ->  14 items
```

That second publish exposed a real bug in `compare.py`: the server stores `keywords` as a
**set** and returns its own order, so every publish reported `changed: True` forever — the
same failure the audit fields caused during FEAT-002, in a different field. `keywords` is
now compared order-insensitively.

## What is still unknown

Whether the assistant actually *retrieves* these items well. The spec says this cannot be
settled by building more, only by asking it a question only the document answers. The items
are live and the question is now cheap to ask; if paragraph granularity proves wrong,
`split_level` already exists and the documents are the only thing that would change.
