# `config/domains.yaml` — the domain membership manifest

The one place in the repo that says which dashboards, visualizations and AI-context objects
belong to each domain, what each child workspace is called, and what is deliberately in no
domain and why.

**The `viz_<domain>_` prefix convention is dead.** It ran once, in
`src/globalmart/domain_bootstrap.py`, to produce the first version of this file. Nothing
reads it at runtime, and `tests/test_single_source_of_domains.py` asserts the domain list
appears in no source file but that one seed module.

## Commands

```bash
globalmart domains validate --strict          # the CI gate: coverage must be complete
globalmart domains validate --format json     # the same report, machine-readable
globalmart domains bootstrap --dry-run        # regenerate from prefixes (one-time; refuses to overwrite)
```

`validate` is offline. It reads `layouts/workspaces/globalmart/` and this file, contacts no
host and writes nothing.

## Schema (version 1)

| Key | Type | Required | Meaning |
|---|---|---|---|
| `version` | int | yes | `1`. Anything else is refused rather than guessed at. |
| `parent_workspace_id` | str | yes | The source workspace, `globalmart`. |
| `workspace_id_template` | str | yes | `globalmart-{key_kebab}`. `{key_kebab}` is the key with `_` → `-`. |
| `workspace_name_template` | str | yes | `GlobalMart — {label}`. What FEAT-004 passes to `publish_workspace(..., workspace_name=...)`. |
| `domains` | list | yes | Sorted by `key`. |
| `shared` | mapping | no | Objects that belong in **every** child. Counts as coverage. |
| `unassigned` | mapping | no | Reasoned exclusions. Counts as coverage. |

Each domain:

| Key | Type | Required | Meaning |
|---|---|---|---|
| `key` | str | yes | snake_case, `^[a-z][a-z0-9_]*$`, unique. |
| `label` | str | yes | Human label, e.g. `Sales`. Feeds the name template. Unique. |
| `description` | str | yes | One sentence. |
| `workspace_id` | str | yes | Written out even though derivable — the validator asserts it equals the template's output, so the file stays greppable and the convention stays honest. |
| `workspace_name` | str | no | Per-domain override of the rendered template. |
| `dashboards` | list[str] | yes | Analytical dashboard ids. |
| `visualizations` | list[str] | no | Visualizations that belong here but sit on **no** listed dashboard. |
| `ai` | mapping | no | `memory_item_ids`, `memory_item_tags`, `parameter_ids`, `agent_ids`, `knowledge_ids`. |
| `ldm_include` | list[str] | no | See below. |

`unassigned` entries are `{id, reason}`. Under `--strict` a reason that is empty, whitespace,
`TODO`/`TBD`/`n/a`/`none`, or that starts with `TODO:`, fails.

## The rules that are not obvious

**Membership is many-to-many.** A dashboard serving two domains is listed under both keys, and
is copied into both children. Coverage requires *at least* one domain, never exactly one.
Requiring exclusivity would recreate the behaviour this file exists to kill: the predecessor
assigned a dashboard to a domain only when *every* tile matched that domain's prefix, so a
mixed dashboard matched nothing and was dropped without a word.

**A dashboard covers the visualizations it shows.** You do not list them. Coverage walks
`iter_dashboard_insight_refs`, a generic walk of the dashboard `content` blob that finds
references in nested layouts, drill targets and rich-text widgets — not an assumed
`sections[].items[].widget` shape. The per-domain `visualizations:` list is only for
visualizations that belong to a domain and sit on no dashboard. Listing one that a dashboard
already covers is reported as redundant (a warning, not an error).

**Everything is accounted for, or the command fails.** Every dashboard, visualization and
AI object must be assigned, `shared`, or `unassigned` with a reason. There is no fourth
option and no silent drop. This runs in CI, so a PR that adds a dashboard to the parent
without assigning it fails, naming the dashboard.

**AI context is deny-by-default.** A memory item, parameter, agent personality or knowledge
object reaches a child only if that domain names it, one of its `memory_item_tags` matches,
or `shared.ai` declares it. Nothing is inherited. The failure mode that matters for AI
context is leakage, not absence — an unclassified AI object is uncovered and fatal rather
than quietly copied everywhere.

`memory_item_tags` is the only *rule* in the manifest rather than a list of ids. AI memory is
expected to grow, and requiring an id edit per new item would guarantee this file falls
behind.

**`ldm_include` is headroom, not membership.** It names dataset ids to put in a child's LDM
*beyond* what the split's closure reaches, so new metrics and visualizations can be authored
in that child on tables today's dashboards do not touch. Every id must exist in the parent's
`ldm.datasets`. It never covers a dashboard, visualization or AI object; it does not satisfy
the "a domain needs at least one object" rule; and it is not `shared:` — `shared:` declares
analytics that belong in every child, `ldm_include` declares tables one child wants room on.
FEAT-004 adds them to its closure seed and reports them apart from the closure-reached ones.

**An object may appear under both `shared.ai` and a domain's own `ai`.** Union semantics make
that harmless and idempotent, so it is allowed and never an error. `multi_homed` reports it.

## Adding a domain

One file, one edit:

1. Add an entry to `domains:` with a `key`, `label`, `description`, and a `workspace_id`
   matching `workspace_id_template` (the validator checks this).
2. List its `dashboards` — and its `visualizations`, if any sit on no dashboard.
3. Move the objects it takes over out of whatever domain held them, or list them under both
   if they genuinely serve both.
4. `globalmart domains validate --strict`.

Nothing else in the repo needs to change. That is the point.

## What the parent actually looks like

Measured against the tree committed 2026-09-18:

```
dashboards        : 32/32 assigned
visualizations    : 384/384 assigned
ai objects        : 0/0 assigned
shared            : 0
excluded          : 0
multi-homed       : 0
```

Every visualization is referenced by exactly one dashboard, and every dashboard draws from a
single domain — 12 domains, 24 or 36 visualizations each. So `shared:` and `unassigned:` are
both empty today, and the many-to-many rule costs nothing. It exists so that the first
genuinely cross-domain dashboard is a one-line edit instead of a silent disappearance.

The parent carries no memory items or parameters yet. When it does, the `ai:` blocks are
where they get scoped, and `uncovered_ai` makes forgetting impossible.
