---
kind: explanation
title: The AI context channels
scope: ai-context
owner: analytics-eng
anchor: true
---

# The AI context channels

## Four channels, and what each is for

An assistant working over GlobalMart draws on four separate things, and confusing them is
the usual reason a fact fails to reach an answer.

1. **The semantic layer itself** — object titles and descriptions. Always available,
   structural, and silent about meaning.
2. **AI memory items** — short directives, capped at 255 characters. Compiled from
   `docs/knowledge/*.md`, carried inside the workspace layout, copied into each child
   workspace, and retrieved on relevance or injected always. 14 per workspace today.
3. **AI Knowledge documents** — this corpus. Whole Markdown documents, published through
   their own API, chunked by the server, and searched semantically.
4. **Agent personalities** — how the assistant behaves, which is organization-scoped rather
   than part of the workspace layout.

## Memory items versus documents

This is the distinction worth internalising. A **memory item** is a rule the assistant should
obey: "net revenue excludes intra-company transfers" is a directive, it fits in 255
characters, and it should apply whether or not anybody searched for it. A **document** is
something to look up: the fact-table reference, the five metric levels, what a dashboard
actually shows. It is too long to be a directive and too specific to inject into every
prompt.

A fact belongs in exactly one channel. Restating a memory item inside a document duplicates
maintenance and guarantees the two eventually disagree.

## They reach children differently

Memory items are **copied** into each child workspace by the splitter, filtered by domain
tag, so a finance memory item does not appear in the HR workspace. Knowledge documents are
**inherited at read time**: they are written once to the parent, the children hold no copy,
and a search from a child workspace reaches up the ancestor chain. More local knowledge
ranks above inherited knowledge when both match.

The practical consequence: publishing a document to the parent makes it available in all
twelve children immediately, with no split and no republish of the children.

## Per-domain grouping

A document's front matter can name `domains:`, which becomes a `domain/<key>` scope on the
published document. Scopes are filterable through the search API, so a caller can narrow to
one domain's documentation — though the assistant's own knowledge tool does not currently
filter by scope, so in practice a document reaches whoever searches the workspace it was
published to.

## What is deliberately not wired

The domain manifest has a `knowledge_ids` field and the layout model has a knowledge channel
stub. Both are dormant and stay that way: they model an in-layout object the splitter would
copy, and knowledge documents are neither in the layout nor copied. Wiring them would make
the coverage check demand membership for objects that are not in the layout at all.
