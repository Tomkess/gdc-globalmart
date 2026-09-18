## Tasks — FEAT-003: Explicit domains.yaml manifest describing which dashboards and visualizations belong to each of the 12 domains, bootstrapped from the existing viz-prefix convention and coverage-checked

> Appetite: `s`  ·  Generated: 2026-09-18

- [ ] 1. Create `src/globalmart/domains.py` with the frozen dataclasses `AiSelection` (`memory_item_ids`, `memory_item_tags`, `parameter_ids`, `agent_ids`, `knowledge_ids`, all `tuple[str, ...]` — AI knowledge is one of the four channels STEERING requires to be filtered per domain, so it is selected here like the other three), `Exclusion` (`id`, `reason`), `Domain` (`key`, `label`, `description`, `workspace_id`, `workspace_name`, `dashboards`, `visualizations`, `ai`, `ldm_include: tuple[str, ...]` defaulting to `()` — dataset ids this child's LDM gets beyond closure reach, so new metrics and visualizations can be authored there; an LDM concern only, never coverage and not the `shared:` block), `SharedSelection`, `UnassignedSelection` and `DomainManifest` (`version`, `parent_workspace_id`, `workspace_id_template`, `workspace_name_template`, `domains`, `shared`, `unassigned`, `path`). Add `DomainManifestError(GlobalmartError)`. List fields are tuples so a loaded manifest cannot be mutated.
       Pre: FEAT-002 task 6 complete (`GlobalmartError` in `config.py`)
       AC: #1

- [ ] 2. Write `tests/fixtures/domains/valid.yaml` by hand at fixture scale (2 domains — `sales` and `store_ops` — matching `tests/fixtures/mini_globalmart/` object ids), exercising every schema key: `version`, `parent_workspace_id`, both templates, per-domain `dashboards`/`visualizations`/`ai` (including `memory_item_tags` and `knowledge_ids`), a `shared.dashboards` entry, a `shared.visualizations` entry and a `shared.ai.parameter_ids` entry, an `ldm_include` list on one domain naming a dataset that domain's analytics do not reach, and one `unassigned` entry of each kind with a real sentence as its `reason`.
       Pre: task 1 complete (schema fields fixed by the dataclasses); FEAT-001 task 11 complete (`tests/fixtures/mini_globalmart/` ids to reference)
       AC: #1

- [ ] 3. Implement `load_domains(path: Path) -> DomainManifest` in `domains.py`: parse with `yaml.safe_load`, reject `version != 1`, and parse **strictly** — any mapping key not in the schema raises `DomainManifestError` naming the key and its dotted path (`domains[3].dashboard`). A typo'd key must never be silently ignored into "no dashboards".
       Pre: task 2 complete (a valid document to parse)
       AC: #1, #4

- [ ] 4. Add manifest-level validation to `load_domains`: `key` matches `^[a-z][a-z0-9_]*$`; `key`, `label` and `workspace_id` each unique across domains; no `workspace_id` equal to `parent_workspace_id`; each `workspace_id` equals `workspace_id_template.format(key_kebab=key.replace("_", "-"))` unless explicitly overridden; every domain has at least one entry across `dashboards` + `visualizations`. Each failure raises `DomainManifestError` naming the offending domain key.
       Pre: task 3 complete (`load_domains` parses)
       AC: #1, #11

- [ ] 4a. Parse and validate the optional per-domain `ldm_include` in `load_domains`: a list of dataset ids, loaded into `Domain.ldm_include` as a sorted `tuple[str, ...]` (absent key → `()`), rejecting duplicates within a domain and non-string entries with `DomainManifestError` naming the domain key and the dotted path. Existence against the parent's `ldm.datasets` is checked in `check_coverage` (task 13a), not here — `load_domains` never reads the parent tree. Document in the same place that `ldm_include` widens only the child's LDM: it is not coverage of any dashboard, visualization or AI object, it does not satisfy the "at least one entry across `dashboards` + `visualizations`" rule from task 4, and it is not the `shared:` block.
       Pre: task 4 complete (manifest-level validation in place)
       AC: #12

- [ ] 5. Implement `dump_domains(manifest, path)` plus `resolve_workspace_id(manifest, domain)` and `resolve_workspace_name(manifest, domain)` in `domains.py`. `dump_domains` writes canonical YAML — domains sorted by `key`, every id list sorted lexically, fixed top-down key order, `yaml.safe_dump(sort_keys=False, default_flow_style=False, allow_unicode=True, width=100, indent=2)` with a trailing newline — so a one-dashboard change is a one-line diff.
       Pre: task 4 complete (validated manifest model)
       AC: #9, #11

- [ ] 5a. Add the consumer accessors to `DomainManifest` in `domains.py` — the ergonomics FEAT-004 consumes, owned here so no consumer re-derives manifest truth: `by_key(key) -> Domain` (raising `DomainManifestError` naming the key when absent), `keys() -> tuple[str, ...]` in canonical `key`-sorted order, `resolve_workspace_name(domain) -> str` (the method form: `domain.workspace_name` when set, otherwise `workspace_name_template` rendered with `label` — the only sanctioned producer of the string FEAT-004 passes to `publish_workspace(..., workspace_name=...)`), and `unassigned_ids() -> frozenset[str]` flattening every `Exclusion.id` across `unassigned.dashboards`, `unassigned.visualizations` and `unassigned.ai` for callers that need membership only.
       Pre: task 5 complete (`resolve_workspace_name` helper and the loaded manifest model)
       AC: #1, #11

- [ ] 6. Write `tests/test_domains.py`: `load_domains(valid.yaml)` returns the expected domains with tuple-typed lists; `load_domains → dump_domains → load_domains` round-trips equal and re-dumps byte-identically; `version: 2` raises; duplicate `key`/`label`/`workspace_id` and a `workspace_id` equal to `parent_workspace_id` each raise; `store_ops` resolves to `globalmart-store-ops`; `manifest.resolve_workspace_name(domain)` on `label: Sales` with the default template yields exactly `GlobalMart — Sales` (the string FEAT-002's `--workspace-name` expects) and a per-domain `workspace_name` overrides it; `by_key("sales")` returns that domain while `by_key` on an unknown key raises `DomainManifestError` naming it; `keys()` is canonically sorted; `unassigned_ids()` is a `frozenset` equal to the flattened ids of all three `unassigned` lists; and a loaded `AiSelection` carries `knowledge_ids` alongside the other three id lists and `memory_item_tags`.
       Pre: task 5a complete (loader, dumper, template helpers and the consumer accessors)
       AC: #1, #9, #11

- [ ] 7. Add `tests/fixtures/domains/unknown_key.yaml` (a domain carrying `dashboard:` instead of `dashboards:`) and a test in `tests/test_domains.py` asserting `DomainManifestError` names both the key and its dotted path.
       Pre: task 6 complete (test module exists)
       AC: #4

- [ ] 8. Extend `src/globalmart/traversal.py` with `iter_dashboard_insight_refs(model) -> Iterator[tuple[str, str]]` and `dashboard_visualization_ids(model, dashboard_id) -> set[str]`. Implement as a generic recursive walk of each `CatalogDeclarativeAnalyticalDashboard.content`, collecting every `{"identifier": {"id": ..., "type": "visualizationObject"}}` — never an assumed `sections[].items[].widget` shape — so nested layouts, drill targets and rich-text widgets are all found. FEAT-002's existing generators and their tests stay untouched.
       Pre: FEAT-002 task 2 complete (`traversal.py` with its three generators)
       AC: #2

- [ ] 9. Extend `tests/test_traversal.py`: `iter_dashboard_insight_refs` yields the fixture's known `(dashboard_id, viz_id)` pairs; a reference planted in a nested layout and one planted in a drill definition are both found; a dashboard with no visualization references yields nothing and does not raise.
       Pre: task 8 complete (`iter_dashboard_insight_refs` implemented)
       AC: #2

- [ ] 10. Extend `tests/fixtures/mini_globalmart/` with the four shapes every coverage rule needs: a dashboard whose tiles reference both a `viz_sales_*` and a `viz_finance_*` object, a visualization referenced by no dashboard, a visualization whose id matches no `viz_<domain>_` prefix, and one `memoryItems` entry. Re-run FEAT-001's `normalize --check` so the fixture stays canonical.
       Pre: task 9 complete (extractor proven against the current fixture); FEAT-001 task 31a complete (AI-context objects captured and normalized)
       AC: #3, #6

- [ ] 11. Create `src/globalmart/coverage.py` with the `DomainCounts` and `CoverageReport` dataclasses (fields exactly as listed in the breakdown's Data Model) and `CoverageError(GlobalmartError)` carrying the report. No logic yet — the shape is what the following tasks fill in.
       Pre: task 1 complete (`DomainManifest`), FEAT-001 task 7 complete (`ObjectCounts` conventions to mirror)
       AC: #2

- [ ] 12. Implement `check_coverage(model, manifest) -> CoverageReport` part 1 — classification: for every dashboard id in `model.analytics.analytical_dashboards` and every visualization id in `model.analytics.visualization_objects`, record which domain keys cover it (a dashboard by direct listing; a visualization by direct listing **or** via `dashboard_visualization_ids` of any dashboard that domain lists), fold in `shared`, fold in `unassigned` as `excluded`, and put everything left over into `uncovered_dashboards` / `uncovered_visualizations`.
       Pre: task 11 complete (`CoverageReport`), task 8 complete (`dashboard_visualization_ids`)
       AC: #2, #3

- [ ] 13. Implement `check_coverage` part 2 — integrity and secondary reports: `unknown_ids` (every manifest id, with its dotted manifest path, that does not exist in the parent), `multi_homed` (any object with ≥2 domain keys — reported, never an error), `redundant_visualizations`, `cross_domain_tiles` (visualizations a listed dashboard references but that domain does not cover), and `per_domain` counts.
       Pre: task 12 complete (classification pass)
       AC: #3, #4

- [ ] 13a. Extend `check_coverage` with `ldm_include` handling: for every domain, check each `ldm_include` id against `model.ldm.datasets[*].id` and record a miss in `unknown_ids` under its `domains[i].ldm_include[j]` path (fatal, like any other unknown id); count the valid ones into `DomainCounts.ldm_include` so declared LDM widening is visible in the report. Assert by construction that no `ldm_include` id changes any dashboard, visualization or AI coverage outcome — it widens the child's LDM, it does not declare membership. Add the matching cases to `tests/test_coverage.py`: an unknown declared dataset is fatal and named with its path; a valid one is counted and leaves `assigned_*` / `uncovered_*` byte-identical to the same manifest without it.
       Pre: task 13 complete (`check_coverage` integrity pass), task 4a complete (`Domain.ldm_include` parsed)
       AC: #12

- [ ] 14. Implement AI-context coverage in `check_coverage`: enumerate the parent's `memoryItems`, parameters, agent personalities and AI-knowledge objects; a domain covers one when its `ai.memory_item_ids` / `parameter_ids` / `agent_ids` / `knowledge_ids` names it **or** its `ai.memory_item_tags` intersects the item's tags. Fold in `shared.ai` and `unassigned.ai`; anything left lands in `uncovered_ai`. Deny-by-default: nothing is inherited implicitly, so cross-domain AI memory cannot reach a child by omission.
       Pre: task 13 complete (`check_coverage` structure), task 10 complete (fixture carries a memory item)
       AC: #6

- [ ] 15. Implement `raise_for_report(report, *, strict: bool) -> None` in `coverage.py`: raise `CoverageError` when `uncovered_dashboards`, `uncovered_visualizations`, `uncovered_ai` or `unknown_ids` is non-empty, listing every id (and manifest path for unknowns); additionally, when `strict`, raise on `placeholder_reasons` — any `unassigned` reason that is empty, whitespace, case-insensitively `TODO`/`TBD`/`n/a`/`none`, or that starts with `TODO:`.
       Pre: task 14 complete (all report fields populated)
       AC: #2, #5

- [ ] 16. Write `tests/test_coverage.py` part 1 — **the predecessor-bug test**: a dashboard whose tiles span `sales` and `finance`, listed under both domain keys (fixture `tests/fixtures/domains/mixed_domain_dashboard.yaml`). Assert coverage passes, `multi_homed` contains the dashboard with both keys, and neither it nor any of its tiles appears in `uncovered_*`. Add the inverse: the same dashboard listed under neither domain is fatal and named in the error.
       Pre: task 15 complete (`check_coverage` + `raise_for_report`), task 10 complete (mixed-tile fixture dashboard)
       AC: #2, #3

- [ ] 17. Write `tests/test_coverage.py` part 2 with fixtures `missing_coverage.yaml`, `unknown_id.yaml` and `empty_reason.yaml`: a visualization reachable only through a listed dashboard is covered without being listed; a visualization on no dashboard and in no list is fatal; a manifest id absent from the parent lands in `unknown_ids` with its path and is fatal; `reason: "TODO: classify"` passes plain validation and fails under `strict=True` while a real sentence passes both.
       Pre: task 16 complete (part 1 harness and fixture conventions)
       AC: #2, #4, #5

- [ ] 18. Write `tests/test_coverage.py` part 3 — AI scoping and secondary reports: a memory item matched only by `memory_item_tags` is covered and appears under exactly one domain, with domain B's `per_domain.memory_items` containing zero of domain A's items (the no-leak assertion); an AI object in no domain, no `shared.ai` and no `unassigned.ai` is fatal; `cross_domain_tiles` is populated when a listed dashboard references a visualization assigned only elsewhere and empty for the clean fixture; `redundant_visualizations` flags a viz listed under a domain that already covers it via a dashboard.
       Pre: task 17 complete (fixture set established), task 14 complete (AI coverage)
       AC: #3, #6

- [ ] 19. Create `src/globalmart/domain_bootstrap.py` with `SEED_DOMAINS: tuple[tuple[str, str], ...]` — the 12 `(key, label)` pairs `sales/Sales`, `ecommerce/E-commerce`, `product/Products`, `customer/Customers`, `loyalty/Loyalty`, `inventory/Inventory & Supply Chain`, `marketing/Marketing`, `finance/Finance`, `store_ops/Store Operations`, `hr/HR`, `risk/Risk & Compliance`, `real_estate/Real Estate & Facilities` — and `domain_for_visualization_id(viz_id, seed) -> str | None`, matching `viz_<key>_` longest key first so `store_ops` wins over any shorter key that is also a prefix. Module docstring: this is one-time seed data; no runtime code may import `SEED_DOMAINS`.
       Pre: task 1 complete (`Domain` shape)
       AC: #7, #10

- [ ] 20. Implement `bootstrap_manifest(model, *, seed=SEED_DOMAINS) -> tuple[DomainManifest, BootstrapReport]` and the `BootstrapReport` dataclass: assign each visualization by prefix; assign each dashboard to **every** domain any of its `dashboard_visualization_ids` belongs to (ANY, never ALL — the predecessor's rule is the bug); put prefix-matched visualizations that no listed dashboard references into that domain's `visualizations` list; park every unmatched visualization, unreferenced dashboard and AI-context object under `unassigned` with a `TODO:`-prefixed reason. Populate descriptions with a `TODO:` placeholder for human editing.
       Pre: task 19 complete (seed and prefix matcher), task 8 complete (`dashboard_visualization_ids`), task 5 complete (`dump_domains`)
       AC: #7

- [ ] 21. Write `tests/test_domain_bootstrap.py`: `bootstrap_manifest(fixture_model)` dumped equals the committed `tests/fixtures/domains/bootstrap_golden.yaml` byte-for-byte and is identical across two runs into two paths; `viz_store_ops_headcount` is assigned to `store_ops`; a mixed-tile dashboard appears under **both** its domains (the ALL rule would leave it unassigned); every unmatched object appears under `unassigned` with a `TODO:` reason and the counts match `BootstrapReport`; and the generated manifest passes `check_coverage` with `strict=False` but **fails** with `strict=True`.
       Pre: task 20 complete (`bootstrap_manifest`), task 15 complete (`raise_for_report`)
       AC: #7, #9

- [ ] 22. Extend `src/globalmart/cli.py` with the `domains` group and `domains validate [--manifest config/domains.yaml] [--layout layouts/workspaces/globalmart] [--strict] [--format table|json]`: `read_tree` → `load_domains` → `check_coverage` → render the `CoverageReport` (totals, per-domain table, multi-homed, cross-domain tiles, exclusions) → `raise_for_report`; exit 1 with the offending ids printed on any failure. Read-only and offline — no `--apply`, no host contact.
       Pre: task 15 complete (`check_coverage`, `raise_for_report`), FEAT-002 task 30 complete (`cli.py` subcommand-group structure)
       AC: #2, #4, #5, #6

- [ ] 23. Add `domains bootstrap [--layout ...] [--out config/domains.yaml] [--dry-run] [--force]` to `cli.py`: print the `BootstrapReport` first, write the manifest with `dump_domains`, refuse with exit 1 when `--out` exists and `--force` is absent, and write nothing under `--dry-run`. `--dry-run` (not `--apply`) is correct per ADR 002 — the only write is a local file.
       Pre: task 22 complete (`domains` group wired), task 20 complete (`bootstrap_manifest`)
       AC: #7, #8

- [ ] 24. Extend `tests/test_cli.py`: `domains validate` on `valid.yaml` + fixture tree exits 0 and prints the per-domain table; on `missing_coverage.yaml` exits 1 naming the uncovered dashboard; `--format json` emits a parseable report dict; `domains bootstrap --dry-run` writes no file and prints the report; `domains bootstrap` over an existing manifest without `--force` exits 1 without writing, and with `--force` overwrites.
       Pre: task 23 complete (both subcommands wired)
       AC: #2, #7, #8

- [ ] 25. Write `tests/test_single_source_of_domains.py`: walk `src/globalmart/**/*.py` and `config/**` for each of the 12 keys and 12 labels and assert the only files containing them are `config/domains.yaml` and `src/globalmart/domain_bootstrap.py`. Mechanizes "the predecessor had the domain list in four places" so it cannot come back.
       Pre: task 23 complete (all FEAT-003 source modules written)
       AC: #10

- [ ] 26. Run `uv run globalmart domains bootstrap --layout layouts/workspaces/globalmart --dry-run` against the committed parent tree and record the `BootstrapReport`: how many of the 384 visualizations matched a prefix, how many are referenced by no dashboard, how many dashboards got multi-homed, and how many AI objects were parked. Offline — reads only the repo tree, contacts no host.
       Pre: task 23 complete (CLI proven on the fixture); FEAT-001 task 31 complete (real tree committed)
       AC: #7

- [ ] 27. `[DECISION NEEDED: the residue from task 26 — visualizations reachable from no dashboard and matching no prefix — must be classified by the user as (a) real content that needs a domain, (b) eval/LLM artifacts to exclude with a reason, or (c) content to delete from the parent in a separate reviewable change. The manifest expresses all three; which applies per object cannot be decided without seeing the actual list.]** Walk the residue with the user and record the outcome as per-domain `visualizations` entries or `unassigned` entries with real reasons.
       Pre: task 26 complete (residue enumerated)
       AC: #2, #5

- [ ] 28. Generate and hand-edit the real `config/domains.yaml`: run `domains bootstrap` for real, then replace every `TODO:` description with a real sentence, every `TODO:` exclusion reason with the decision from task 27, and assign the 12 labels and `workspace_id`s. Commit the file and review it as a diff.
       Pre: task 27 complete (residue decisions made)
       AC: #1, #5, #11

- [ ] 29. Assign AI context per domain in `config/domains.yaml`: for each of the parent's memory items, parameters, agent personalities and AI-knowledge objects, list it under the domains it belongs to (`ai.memory_item_ids` / `memory_item_tags` / `parameter_ids` / `agent_ids` / `knowledge_ids`), under `shared.ai` if it is genuinely domain-neutral, or under `unassigned.ai` with a reason. Then run `domains validate --strict` and confirm `uncovered_ai` is empty and no domain's `per_domain.memory_items` includes another domain's items.
       Pre: task 28 complete (manifest committed), task 14 complete (AI coverage implemented)
       AC: #5, #6

- [ ] 30. Write `tests/test_domains_real.py`: skipped cleanly until both `layouts/workspaces/globalmart/` and `config/domains.yaml` exist, then asserts 12 domains with exactly the expected key set, `check_coverage` clean under `strict=True`, `dashboards_total == 32`, `visualizations_total == 384`, and the 12 child workspace ids equal to the expected set including `globalmart-store-ops` and `globalmart-real-estate`.
       Pre: task 29 complete (real manifest complete and strict-clean)
       AC: #1, #2, #11

- [ ] 31. Add the CI job running `uv run globalmart domains validate --strict` alongside FEAT-001's `normalize --check`, so a PR that adds a dashboard to the parent without assigning it to a domain fails. Offline, no credentials.
       Pre: task 30 complete (real manifest validates clean)
       AC: #2

- [ ] 32. Write `docs/domains.md`: the schema field by field, the many-to-many rule and why exclusivity was rejected, the deny-by-default AI rule, how a dashboard reachable from two domains is expressed, `ldm_include` — what it is for (headroom to author new metrics and visualizations on tables today's dashboards do not touch), that it widens only the LDM and is neither coverage nor `shared:`, and that FEAT-004 reports declared datasets separately from closure-reached ones — how to add a domain (one file, one edit), where the child workspace id and display name come from (and that the name feeds FEAT-002's `--workspace-name`), and the statement that the `viz_<domain>_` prefix convention is dead after bootstrap.
       Pre: task 28 complete (the real manifest shows what the doc must describe)
       AC: #1, #10, #11

- [ ] 33. Write `specs/decisions/003-explicit-domain-membership.md` recording the three non-obvious choices per STEERING § AI Behavior: many-to-many membership with coverage requiring ≥1 domain; coverage-or-explicit-reasoned-exclusion with no silent drop; deny-by-default AI-context scoping with an explicit `shared.ai`. Include the rejected alternatives (exclusive membership, warn-don't-fail coverage, inherit-all AI context) and their consequences for FEAT-004.
       Pre: task 29 complete (all three rules exercised against the real content)
       AC: #2, #3, #6
