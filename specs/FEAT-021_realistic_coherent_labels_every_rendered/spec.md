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
id: feat-021
links: []
name: 'Realistic, coherent labels: every rendered text attribute (channel, currency,
  store format, company entity, country, region, city, store, product, customer) gets
  a realistic value from a config vocabulary, and geography is coherent — a row''s
  references agree with the references of the rows they point at'
sources: []
status: done
tags: []
updated: '2026-10-23'
---

## Summary
Every text attribute a GlobalMart visualization renders is a placeholder: `City Name 0005`,
`Country Name 0000`, `Product Name 0011`, `Customer Name 0014`, `Store Name 0001`,
`channel_type_00003`, `currency_code_00002`, `store_format_00010`. That is 12 columns, measured
2026-10-23 across the parent's analytics. Every chart axis and filter list in a prospect demo shows
them. The generator (FEAT-007/013) names a column after itself plus a row index, by design: it names
no table and no column, so a table added to the DDL generates without an edit.

Underneath, the geography is incoherent. A row's references are drawn independently, so 54 of 100
cities sit in a different country from their own region, and 11 of 20 stores disagree with their
city's country. Realistic names would make that visible: Toronto, in a US region, in Canada.

This feature fixes both, without naming a table or column in code:
1. **Coherence.** When a row references A, and A's row references B, the row's own reference to B
   is taken from A. The rule is general and follows the LDM's references (FEAT-020).
2. **Vocabulary.** A config file, `config/vocabulary.yaml`, gives realistic values per column.
   Values are lists, paired columns (code and name), parent-scoped lists (regions within a country,
   cities within a region), templates (a store named after its city) and composed names (customers,
   products). Columns it does not mention keep today's behaviour.

## Appetite
`s` — 1–3 days

## Acceptance Criteria
- [ ] Given a generated dataset, when every row's references are checked transitively, then no row
      disagrees with the row it references: a city's country is its region's country, and a store's
      region and country are its city's. 0 violations across every pair the LDM implies
- [ ] Given `config/vocabulary.yaml`, when the dataset is generated, then all 12 rendered text
      columns hold realistic values. Paired columns agree within a row (`USD` with `US Dollar`).
      A region's name belongs to its country, and a city's name to its region
- [ ] Given a table whose key identifies an entity (a dimension), when names are assigned, then
      names are distinct within that table, with a deterministic suffix only if a vocabulary runs
      out
- [ ] Given the same seed, scale, window and vocabulary, when generating twice, then the output is
      byte-identical
- [ ] Given generation without a vocabulary file, or a column it does not mention, then the
      column's values are exactly what they are today. A test pins this
- [ ] Given the change, when the warehouse is force-reloaded, then `verify --target gdcloud-dev
      --fail-on-empty` passes, and the dashboards' axes and filters show the realistic labels

## Scope
- `generate.py`: key spaces remember each minted row's references and text values. A coherence
  pass derives references transitively. A vocabulary pass replaces text values. Both are
  table-agnostic
- `vocabulary.py` (new): the strict loader and the value resolution for lists, pairs, parent-scoped
  lists, templates and composition
- `config/vocabulary.yaml` (new): the realistic values for the 12 rendered columns
- One forced warehouse reload and verification

## Out of Scope
- The tenant and region filter layer (`wdf__tenant_id`, `wdf__region`). It is assigned
  independently of geography and stays as it is
- Text columns that no visualization renders. They may be added to the vocabulary later; nothing
  is required
- Changing row counts, numeric shaping (`plausible.py`) or the LDM

## Key Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The coherence pass rewrites references broadly, and dashboards' numbers shift | Certain | Low | That is the point: the old splits were incoherent. Verify after the reload |
| Two references could each derive the same target differently | Low | Medium | The first anchor in plan order wins, deterministically. A test asserts 0 transitive violations |
| A vocabulary smaller than a dimension's row count repeats names | Medium | Low | Deterministic suffix (`Boston 2`). Composed names for the large dimensions |
| The determinism oracle fixture changes | Certain | Low | It is generated without a model or vocabulary, so the no-vocabulary path stays byte-identical |

## Dependencies
- **Depends on:** FEAT-020 (LDM-derived foreign keys, which the coherence pass follows)
- **Enables:** demo dashboards that read as retail

## Related Research
- Measured 2026-10-23: 26 text columns are planned as opaque codes and 68 as generated names. Of
  those, 12 are rendered by a visualization. 54 of 100 cities and 11 of 20 stores are
  geographically incoherent
- `generate._value` (the NAME and CODE formats), `generate._assign_filters` (precedent:
  inheritance from a referenced row), `WDF_VOCABULARY` (precedent: a readable fixed vocabulary)
- No knowledge document, question set or test quotes a placeholder label (checked)

## Open Questions
- None blocking. Vocabulary content (which countries, cities and product words) is a demo-taste
  choice, kept in config so it can change without code

## Outcome (2026-10-23)
- PR #11: coherence pass plus `config/vocabulary.yaml`. 897 tests pass.
- Forced reload (run 39982585680, commit 0d24055): 174,372 rows. Both orgs' caches invalidated.
- Warehouse: 0 placeholder labels across the 12 rendered columns, 0 incoherent cities (was 54/100),
  0 incoherent stores (was 11/20). United States pays in USD, Canada in CAD. Orders split by real
  channel names.
- `verify --target gdcloud-dev --fail-on-empty`: 384/384 ok, 0 empty.
- Observed, not changed: Canada gets 5 of the 8 regions by draw, so most cities and stores, and
  ~70% of orders, are Canadian. If the demo should read as US-led, weight the country draw (or pin
  regions by record) in the vocabulary; it is content, not code.
