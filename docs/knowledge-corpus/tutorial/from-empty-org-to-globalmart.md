---
kind: tutorial
title: From an empty org to a working GlobalMart
scope: getting-started
owner: analytics-eng
---

# From an empty org to a working GlobalMart

## What you will end up with

A parent workspace holding 227 datasets, 1,091 metrics, 384 visualizations and 32
dashboards, twelve pruned domain workspaces derived from it, a loaded warehouse behind them,
and this documentation corpus searchable by the AI assistant. Nothing is clicked in a UI at
any point.

## Before you start

Add a profile to `config/targets.yaml` naming the host, organization, datasource and
warehouse schema, and put the token in the environment as
`GLOBALMART_TOKEN__<PROFILE_NAME>` — tokens are never read from the YAML file. Then confirm
what the host actually reports, rather than what you assume it reports:

    globalmart targets inspect --target my-org

That prints the organization id, the datasources and the existing workspaces. An
organization id guessed from a hostname is a classic way to publish into the wrong place.

## The whole chain in one command

    globalmart rebuild --target my-org              # rehearsal: prints the step plan
    globalmart rebuild --target my-org --apply       # actually does it

The rehearsal is worth reading first: it lists every step with the single command that
reproduces it alone, which is what you will want when one of them fails. The chain probes
the org for emptiness, verifies the committed data contract, loads the warehouse, publishes
the parent, publishes this documentation corpus, splits the twelve children, publishes them,
and verifies the result by executing every visualization.

If the org already holds these workspaces the chain aborts rather than claiming a cold
rebuild it did not perform. `--allow-existing` overrides that, and the report then records
that the run was not cold.

## Doing it a step at a time

    globalmart data generate --out .cache/globalmart-data --seed 20260920
    globalmart data load --target my-org --apply
    globalmart publish parent --target my-org --apply
    globalmart knowledge-docs publish --target my-org --apply
    globalmart split
    globalmart publish domains --target my-org --apply
    globalmart verify --target my-org

Every command that writes to a live org is a read-only rehearsal without `--apply`. That is
a repository-wide rule, not a per-command choice.

## Checking that it worked

`globalmart verify --target my-org` executes every visualization in the parent and in all
twelve children — 768 of them — and reports failures by cause rather than as a count. A
green run means the semantic layer resolves against the warehouse that was just loaded.

Then ask the assistant something only this corpus answers, such as which date instance the
dashboard filters are bound to. If it answers from the documentation, the knowledge publish
worked; if it hedges, run `globalmart knowledge-docs retrieval --target my-org` to see which
question failed and whether the document was retrieved at all.
