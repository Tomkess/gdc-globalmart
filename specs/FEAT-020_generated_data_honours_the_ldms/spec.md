---
abandoned_at: null
abandoned_reason: null
appetite: s
blocked_at: null
blocked_by: null
confidence: high
created: '2026-10-23'
cycle: null
depends_on: []
enables: []
goal: goal-01
id: feat-020
links: []
name: 'Generated data honours the LDM''s foreign keys: the generator takes table relationships
  from the LDM''s dataset references instead of guessing from column names, so 36
  of 184 references (19%, 32 datasets — channel, country, city, company entity) stop
  pointing at keys that do not exist'
sources: []
status: draft
tags: []
updated: '2026-10-23'
---

## Summary
The generator (FEAT-007/013) fills every foreign-key column by drawing from the key space of the
table it references. Which table that is, it **guesses from the column name**:
`registry.foreign_key_target` maps `<base>_id` to `dim_<base>`, `<base>` or `fact_<base>`, because the
DDL declares no foreign keys. When the guess finds no table, the column is treated as a local
identifier and filled with unique values that match nothing.

The LDM states every relationship explicitly. `fact_order_header` references `dim_channel_master`
through `channel_id`, and the layout under `layouts/` holds that fact. The generator never reads it
for this decision. The registry already reads the LDM's references for **load order**
(`_dependency_edges`), but not for **which key a column draws from**.

Measured 2026-10-23 against the committed layout and DDL: the naming rule misses **36 of 184
table-backed LDM references (19%) across 32 datasets**. The most-missed targets are
`dim_company_entity` (11), `dim_geography_country` (7), `dim_channel_master` (3) and
`dim_geography_city` (3). In the warehouse, `fact_order_header.channel_id` holds 35,872 distinct
values on 35,872 orders and matches none of `dim_channel_master`'s 6 ids. So every breakdown by
channel, country, city or company entity joins to nothing and comes back empty, and the dashboards
that use those breakdowns show blank series. It surfaced through `sql_blended_daily_revenue` in the
FEAT-019 PR (commit 8765232).

This is the same class of defect as 8c11ef8 ("generate in reference order, so foreign keys are not
silently empty"). That fix corrected the *order*; this one corrects the *target*.

## Appetite
`s` — 1–3 days

## Acceptance Criteria
- [ ] Given the committed layout, when the registry is built with the model, then every column a
      dataset reference names maps to the referenced table and that table's key column from the
      reference's `target` attribute, for all 184 table-backed references. The naming rule applies
      only to `_id` columns that no reference names
- [ ] Given a reference whose target key column differs from the source column, when generating,
      then the source column draws from the target's actual key column
- [ ] Given the regenerated dataset, when every table-backed LDM reference is checked, then 0 of
      184 have a source value that is not in the target's key column. Nullable references may be
      empty, but never dangling
- [ ] Given `fact_order_header`, when joined to `dim_channel_master` on `channel_id`, then every
      order matches one of the channels. `sql_blended_daily_revenue` returns its intended grain:
      rows per (date, store, channel), not per order
- [ ] Given generation without a model (`data generate` with no layout), when run, then behaviour is
      unchanged and the naming rule still applies. A test pins this
- [ ] Given the same seed, scale and window, when generating twice, then the output is
      byte-identical (determinism, FEAT-007)
- [ ] Given the fix, when `data ensure --force --apply` reloads the warehouse, then
      `globalmart verify --target gdcloud-dev` passes with no empty results. The channel, country
      and city breakdowns are non-empty, and the AI Usecases cache is invalidated by the
      `notify-ai-usecases` job (FEAT-019)

## Scope
- `registry.py`: derive a column-level foreign-key map
  (`table.column -> (target_table, target_column)`) from the LDM references, using the existing
  `build_entity_index` / reference data. `plan_columns` consults it before `foreign_key_target`
- A regression test over the committed layout: the 184-reference audit above, as an assertion
- One forced regeneration and reload of the shared `globalmart` schema, which `data-currency`
  would otherwise only do when the data is stale

## Out of Scope
- Declaring foreign keys in the DDL. The LDM is the source of truth for relationships, and adding
  them to the DDL would create a second copy that can drift
- Changing the LDM, or row counts and distributions beyond what correct keys imply
- Domain workspaces: they are derived, local-only and unaffected (ADR 011)

## Key Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| A reference whose target column has a different name from the source column (`entity_id` → `dim_company_entity.company_entity_id`) is mis-mapped | Medium | Medium | Take the target column from the reference's `target` attribute's `sourceColumn`, never from the source column name. The 184-reference audit asserts it |
| Reference cycles in the LDM leave a column unfilled | Low | Low | The only cycle (dim_department ↔ dim_employee) was removed in FEAT-019. `GenerationReport.unresolved` already reports leftovers |
| Correct keys change dashboard numbers people have seen | Certain | Low | That is the fix: the numbers were empty. Note it in the release that ships the reload |
| The reload truncates the schema all four environments read | Medium | Medium | `data_owned: true` (ADR 004/008). The reload takes minutes. Run it off-hours via `data-currency` `force=true`, which then invalidates both orgs' caches |

## Dependencies
- **Depends on:** nothing open. FEAT-019 provides `data notify` and the two-org cache invalidation
  used after the reload
- **Enables:** correct channel, geography and entity breakdowns in every environment

## Related Research
- `registry.foreign_key_target` (naming inference) and `registry._dependency_edges` (LDM edges, used
  for order only); `generate.plan_columns` and `generation_order`
- 8c11ef8: the order fix for the same family of defects
- 8765232: the `sql_blended_daily_revenue` LDM fix, whose commit message first recorded this data
  defect
- The audit numbers come from a script run against `layouts/` and `data/ddl/globalmart.sql`.
  The acceptance criteria above turn it into a test

## Open Questions
- Should nullable references (optional relationships) be filled at a realistic rate, or always?
  The current generator fills always; keep that unless the LDM marks a column optional
