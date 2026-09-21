---
kind: explanation
title: The twelve domain workspaces
scope: domains
owner: analytics-eng
anchor: true
---

# The twelve domain workspaces

## Parent and children

There is one parent workspace, `globalmart`, holding the whole model, and twelve children
derived from it: `globalmart-sales`, `-customer`, `-product`, `-ecommerce`, `-finance`,
`-marketing`, `-inventory`, `-loyalty`, `-hr`, `-store-ops`, `-risk` and `-real-estate`.
The parent is the editing surface. **A child is never authored** — it is generated, and
hand-editing one is a defect to be fixed in the parent.

## Each child carries only what it needs

A child starts from the dashboards its domain declares, follows every reference — dashboard
to visualization to metric to metric to dataset — and keeps exactly that closure. Its
logical data model is then pruned to the datasets it can actually reach. The spread is wide:

| Workspace | Datasets | Metrics | Visualizations | Dashboards |
|---|---|---|---|---|
| sales | 37 | 346 | 36 | 3 |
| customer | 24 | 186 | 36 | 3 |
| loyalty, marketing | 20 | 50, 49 | 24, 36 | 2, 3 |
| inventory | 19 | 185 | 24 | 2 |
| store-ops | 18 | 63 | 36 | 3 |
| product | 17 | 109 | 36 | 3 |
| finance, hr | 16 | 65, 39 | 36 | 3 |
| ecommerce | 12 | 11 | 24 | 2 |
| real-estate | 10 | 20 | 24 | 2 |
| risk | 9 | 33 | 36 | 3 |

Risk reaches 9 of the parent's 227 datasets; sales reaches 37. Nothing gets the full model,
and a child that did would make the domain boundary meaningless.

## Dependencies are pulled in, never filtered out

The rule is one-directional: an object that travels into a child brings everything it
requires with it. So a sales dashboard whose tile references a loyalty metric pulls that
metric and its datasets into the sales workspace — which is why sales has 37 datasets rather
than the dozen a reader might expect from its name, and why the domain counts do not sum to
227. Pruning is dataset-level only: a retained dataset keeps all of its attributes, labels
and facts.

## Membership is declared, not guessed

`config/domains.yaml` names which dashboards belong to each domain. It is not inferred from
the `viz_<domain>_NNNN` naming convention, because a convention is a habit and a manifest is
a commitment. Coverage is enforced: every dashboard and visualization in the parent must
land in at least one domain or be explicitly excluded with a written reason, and the split
fails loudly otherwise.

## Federation, not joins

Each child has its own semantic model, its own metric vocabulary and its own AI context — 14
memory items each today. A question spanning two domains is answered by asking both
workspaces and combining the answers with attribution. There is no cross-workspace join, and
no aggregate workspace that sees everything: the parent could play that role and is not
published for querying.
