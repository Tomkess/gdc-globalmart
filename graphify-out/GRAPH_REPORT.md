# Graph Report - gdc-globalmart  (2026-09-18)

## Corpus Check
- Large corpus: 1865 files · ~250,500 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder.

## Summary
- 636 nodes · 1329 edges · 38 communities (33 shown, 3 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 75 edges (avg confidence: 0.91)
- Token cost: 393,451 input · 0 output

## Community Hubs (Navigation)
- Backup and Target Profiles
- Placeholder Resolution
- Workspace Publishing
- Datasource Parameterization
- CLI Behaviour Tests
- Target Profile Config Loading
- Deterministic YAML Layout IO
- Model Digest and Diff
- Normalizer Six Passes
- Bootstrap Provenance and CI Gates
- Meridian Research Commands
- Object Counting
- CLI Entry Point
- Round-Trip Acceptance Harness
- Meridian Planning Commands
- ADRs and Fixture Semantic Layer
- Domain Splitter and MAQL Refs
- Warehouse Loading and Cold Rebuild
- Result Value Objects
- Project Steering Principles
- Workspace Capture
- Feature Roadmap FEAT-001..008
- AI Context Scoping and LDM Pruning
- Meridian Breakdown and Tasks
- Shared Interface Contract
- Domain Coverage Enforcement
- Verification and Failure Classification
- Domain Manifest Bootstrap
- SDK Version Floor Tests
- Bonus Cost Metric Duplicates
- Data Archive Fetch
- Sales Amount Metric Duplicates
- Customer Visualizations and Dates
- ADR Document Structure
- Package Root
- NPS Metric

## God Nodes (most connected - your core abstractions)
1. `normalize_workspace()` - 54 edges
2. `read_tree()` - 41 edges
3. `publish_workspace()` - 36 edges
4. `write_tree()` - 28 edges
5. `FakeSdk` - 26 edges
6. `GlobalmartError` - 23 edges
7. `TargetProfile` - 21 edges
8. `load_profile()` - 20 edges
9. `main()` - 19 edges
10. `count_objects()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `build_data_source()` --semantically_similar_to--> `WarehouseLoader protocol`  [INFERRED] [semantically similar]
  src/globalmart/datasource.py → specs/FEAT-005_inrepo_deterministic_data_generator_plus/breakdown.md
- `Placeholder Token Substitution Mechanism` --rationale_for--> `resolve_placeholders()`  [INFERRED]
  specs/FEAT-001_bootstrap_the_parent_globalmart_workspace/breakdown.md → src/globalmart/resolve.py
- `publish_domains` --calls--> `publish_workspace()`  [EXTRACTED]
  specs/FEAT-004_domain_splitter_derive_each_domain/breakdown.md → src/globalmart/publish.py
- `resolve_placeholders()` --references--> `DATASOURCE_SCHEMA_TOKEN`  [EXTRACTED]
  src/globalmart/resolve.py → specs/FEAT-001_bootstrap_the_parent_globalmart_workspace/breakdown.md
- `FEAT-001 Bootstrap Parent GlobalMart Workspace` --implements--> `capture_workspace()`  [EXTRACTED]
  specs/FEAT-001_bootstrap_the_parent_globalmart_workspace/spec.md → src/globalmart/capture.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Meridian planning pipeline: idea → spec → breakdown → tasks** — _claude_commands_meridian_idea_idea_skill, _claude_commands_meridian_spec_spec_skill, _claude_commands_meridian_breakdown_breakdown_skill, _claude_commands_meridian_tasks_tasks_skill, specs_skills_feature_lifecycle [EXTRACTED 1.00]
- **Citation discipline across research skills** — _claude_commands_meridian_ask_ask_skill, _claude_commands_meridian_brief_brief_skill, _claude_commands_meridian_research_research_skill, _claude_commands_meridian_brief_no_cite_summaries, _claude_commands_meridian_brief_citation_rules [EXTRACTED 1.00]
- **Org-agnostic portability mechanism** — specs_steering_portability_contract, specs_contract_placeholder_tokens, specs_contract_target_profile, config_targets_targets_yaml, _github_workflows_ci_normalize_check_gate, docs_bootstrap_provenance_schema_hardcoded_finding [INFERRED 0.85]
- **Parameterized Portability Round-Trip (scrub then resolve through one traversal)** — src_globalmart_normalize_normalize_workspace, src_globalmart_traversal_iter_datasource_slots, src_globalmart_traversal_iter_sql_statements, src_globalmart_resolve_resolve_placeholders, src_globalmart_resolve_assert_fully_resolved, src_globalmart_normalize_datasource_id_token, src_globalmart_normalize_datasource_schema_token [EXTRACTED 1.00]
- **Domain Split Pipeline: manifest to verified child JSON** — src_globalmart_domains_load_domains, src_globalmart_closure_build_closure, src_globalmart_prune_prune_ldm, src_globalmart_ai_context_filter_ai_context, src_globalmart_verify_verify_child, src_globalmart_layout_io_write_model_json, src_globalmart_publish_publish_domains [EXTRACTED 1.00]
- **Cold-Rebuild Chain (goal-01 proof)** — src_globalmart_rebuild_cold_rebuild, src_globalmart_dataload_load_data, src_globalmart_publish_publish_workspace, src_globalmart_split_split_all, src_globalmart_verify_verify_target, src_globalmart_report_render_markdown [EXTRACTED 1.00]
- **Destructive-write safety doctrine across publishes and warehouse loads** — specs_decisions_002_publish_requires_explicit_apply_adr_002, specs_decisions_004_warehouse_load_safety_adr_004, specs_decisions_003_generated_artifacts_committed_vs_regenerated_adr_003, specs_decisions_001_parent_yaml_derived_json_domains_adr_001 [INFERRED 0.85]
- **Sales Order star schema: fact joined to channel, customer and store dimensions** — tests_fixtures_mini_globalmart_ldm_datasets_fact_order_header_fact_order_header, tests_fixtures_mini_globalmart_ldm_datasets_dim_channel_master_dim_channel_master, tests_fixtures_mini_globalmart_ldm_datasets_dim_customer_dim_customer, tests_fixtures_mini_globalmart_ldm_datasets_dim_store_dim_store [EXTRACTED 1.00]
- **Near-duplicate metric fixtures exercising duplicate/variant/copy detection** — tests_fixtures_mini_globalmart_analytics_model_metrics_average_l1_bonus_cost_average_l1_bonus_cost, tests_fixtures_mini_globalmart_analytics_model_metrics_average_l1_bonus_cost_duplicate_average_l1_bonus_cost_duplicate, tests_fixtures_mini_globalmart_analytics_model_metrics_average_total_bonus_cost_variant_average_total_bonus_cost_variant, tests_fixtures_mini_globalmart_analytics_model_metrics_average_total_sales_amount_daily_store_sales_average_total_sales_amount_daily_store_sales, tests_fixtures_mini_globalmart_analytics_model_metrics_average_total_sales_amount_daily_store_sales_copy_average_total_sales_amount_daily_store_sales_copy [INFERRED 0.85]

## Communities (38 total, 3 thin omitted)

### Community 0 - "Backup and Target Profiles"
Cohesion: 0.05
Nodes (73): CatalogDataSourceMotherDuck, CatalogDataSourcePostgres, Exception, backup_workspace(), GoodDataSdk, Path, Snapshot a target workspace before overwriting it.…, Write the target's current layout to a timestamped folder. Returns ``None``… (+65 more)

### Community 1 - "Placeholder Resolution"
Cohesion: 0.06
Nodes (64): NamedTuple, Structured Traversal, Never String Replace, assert_fully_resolved(), audit_resolution(), CatalogDeclarativeWorkspaceModel, Resolve placeholders in a layout for one target, then prove none survived. The…, Find every unresolved placeholder and every foreign datasource id. Returns…, Raise unless every placeholder is gone and every datasource id is the target's.… (+56 more)

### Community 2 - "Workspace Publishing"
Cohesion: 0.09
Nodes (47): publish_workspace(), CatalogDeclarativeWorkspaceModel, GoodDataSdk, Apply the profile's prefix, so several copies can coexist in one org., Publish one workspace. Rehearsal unless ``apply=True``., resolved_workspace_id(), fake_sdk(), FakeSdk (+39 more)

### Community 3 - "Datasource Parameterization"
Cohesion: 0.09
Nodes (45): Placeholder Token Substitution Mechanism, DATASOURCE_ID_TOKEN, DATASOURCE_SCHEMA_TOKEN, normalize_workspace(), Normalize a captured workspace in place and report what changed. ``strict``…, A SQL dataset whose schema could be neither found nor parameterised., UnparameterizedSqlError, as_blob() (+37 more)

### Community 4 - "CLI Behaviour Tests"
Cohesion: 0.14
Nodes (31): CaptureFixture, main(), _normalized_tree(), Any, MonkeyPatch, Path, Task 27 — CLI behaviour, especially the --check gate and the no-write rehearsal., ADR 002's convention: --apply gates remote writes; bootstrap writes local files… (+23 more)

### Community 5 - "Target Profile Config Loading"
Cohesion: 0.11
Nodes (30): config/targets.yaml, load_env(), load_profile(), MissingTokenError, ProfileNotFoundError, Path, Load a target profile by name, with env overrides applied. Raises before any…, Load ``.env`` once, without overriding anything already in the environment.… (+22 more)

### Community 6 - "Deterministic YAML Layout IO"
Cohesion: 0.13
Nodes (29): Byte-Stable Deterministic YAML Tree, _canonicalise(), _prune_empty_dirs(), CatalogDeclarativeWorkspaceModel, Path, Re-dump one YAML file through one fixed configuration, with a trailing newline.…, Write a workspace model as a YAML tree, deterministically, pruning orphans. The…, Remove directories left empty by orphan pruning, deepest first. (+21 more)

### Community 7 - "Model Digest and Diff"
Cohesion: 0.13
Nodes (25): _canonical(), _flatten(), mask_parameters(), model_diff(), model_digest(), Any, CatalogDeclarativeWorkspaceModel, Digest, diff and cross-org comparison of workspace models. ``mask_parameters``… (+17 more)

### Community 8 - "Normalizer Six Passes"
Cohesion: 0.14
Nodes (21): Pattern, _iter_analytics_objects(), _pass_1_strip_user_refs(), _pass_2_parameterize_datasource(), _pass_3_parameterize_schema(), _pass_4_handle_wdf(), _pass_5_stabilise_order(), _pass_6_canonicalise_empties() (+13 more)

### Community 9 - "Bootstrap Provenance and CI Gates"
Cohesion: 0.13
Nodes (19): CI workflow (lint, mypy, pytest), globalmart normalize --check canonical-layout gate, demo-cloud target profile, Env-only tokens (GLOBALMART_TOKEN__<PROFILE>), config/targets.yaml — publish target profiles, Bootstrap provenance record, Captured object counts (225 datasets, 1091 metrics, 384 viz, 32 dashboards), Schema was hardcoded, not templated (+11 more)

### Community 10 - "Meridian Research Commands"
Cohesion: 0.16
Nodes (18): /ask — RAG Q&A over enriched research, meridian search CLI, --prior-art flag (cross-project search), /brief — one-page A4 source brief, Citation rules (project:FEAT-NNN:source#chunk), Never cite summaries/ — synthesis is not evidence, 550-word A4 hard limit, /enrich — ingest annotated screenshot (+10 more)

### Community 11 - "Object Counting"
Cohesion: 0.16
Nodes (15): skipif, _count(), count_objects(), Any, CatalogDeclarativeWorkspaceModel, Object counts for a workspace model. Shared by the bootstrap report, the round-…, Count every object channel in a declarative workspace model. ``model.ldm`` is a…, Deterministic reading and writing of the parent workspace's YAML tree. Two… (+7 more)

### Community 12 - "CLI Entry Point"
Cohesion: 0.23
Nodes (15): ArgumentParser, Namespace, build_parser(), cmd_bootstrap(), cmd_normalize(), cmd_publish_parent(), _counts_lines(), _print_report() (+7 more)

### Community 13 - "Round-Trip Acceptance Harness"
Cohesion: 0.18
Nodes (16): _mask(), Any, CatalogDeclarativeWorkspaceModel, Path, Tasks 28–29 — the acceptance harness. AC #8 requires the round-trip be…, AC #6 end to end: the committed tree must not churn between captures., Drop the keys the normalizer owns, recursively, so the rest can be compared., read -> normalize -> write -> read must produce an identical model. (+8 more)

### Community 14 - "Meridian Planning Commands"
Cohesion: 0.22
Nodes (15): Component effort scale S/M/L/XL, /decision — write an ADR, /goal — manage strategic goals, Six goal validation checks, Appetite scale xs/s/m/l, /idea — capture idea as stub spec, A spec is a decision record, not a design document, /spec — elaborate idea into structured spec (+7 more)

### Community 15 - "ADRs and Fixture Semantic Layer"
Cohesion: 0.24
Nodes (12): ADR 001 — Parent workspace as SDK YAML; domain workspaces derived as JSON, ADR 002 — Publishing requires an explicit --apply, ADR 003 — What under generated/ is committed, and what is regenerated, ADR 004 — Warehouse loads substitute a census and refusal guards for ADR 002's backup, Dashboard: Sales Performance Overview (dashboard_000), Filter Context: Filters — Sales Performance Overview, Dataset: Sales Channel (dim_channel_master), Data Source: globalmart-motherduck (+4 more)

### Community 16 - "Domain Splitter and MAQL Refs"
Cohesion: 0.18
Nodes (12): Dependencies Pulled In, Never Filtered Out, build_closure, SharedSelection, check_pruning, write_model_json, iter_maql_refs, MAQL_REF_RE, iter_dashboard_viz_refs (+4 more)

### Community 17 - "Warehouse Loading and Cold Rebuild"
Cohesion: 0.22
Nodes (11): --apply Write Gate (ADR 002), data_owned Warehouse Ownership Guard (ADR 004), Truncate-Then-Load Idempotency, Cold-Rebuild No-Manual-Step Claim (goal-01), load_data, WarehouseLoader protocol, MotherDuck loader, Postgres loader (+3 more)

### Community 18 - "Result Value Objects"
Cohesion: 0.20
Nodes (7): ObjectCounts, How many of each object a workspace model holds., Only the populated channels — what a human wants to read in a report., NormalizeResult, What the normalizer did, printed by the CLI and asserted by the tests., PublishResult, What a publish did — printed by the CLI, asserted by the tests.

### Community 19 - "Project Steering Principles"
Cohesion: 0.27
Nodes (10): tests/test_sdk_floor.py SDK version pin, globalmart README, goal-01 — GlobalMart rebuildable from source into any domain, AI context travels across orgs, Coverage enforcement — every dashboard lands in a domain, Domain workspaces are derived, never authored, Idempotent publishing, Pruned per-child LDM (dataset-level only) (+2 more)

### Community 20 - "Workspace Capture"
Cohesion: 0.22
Nodes (9): Portability Contract (org-agnostic layout), capture_wdf_list(), capture_workspace(), Any, CatalogDeclarativeWorkspaceModel, GoodDataSdk, Read a workspace layout off a live host, org-agnostically. Why not…, Fetch one workspace's declarative layout (LDM + analytics) from a live host. (+1 more)

### Community 21 - "Feature Roadmap FEAT-001..008"
Cohesion: 0.33
Nodes (9): FEAT-001 Bootstrap Parent GlobalMart Workspace, FEAT-002 Publish Parent Workspace Parameterized, FEAT-003 Explicit domains.yaml Manifest, FEAT-004 Domain Splitter, FEAT-005 Own and Load the GlobalMart Data Artifact, FEAT-006 Rebuild Verification Cold-Rebuild Smoke Test, FEAT-007 Synthetic GlobalMart Data Generator (parked), FEAT-008 Knowledge Ingestion into AI Memory Items (+1 more)

### Community 22 - "AI Context Scoping and LDM Pruning"
Cohesion: 0.22
Nodes (9): Deny-by-Default AI Context Scoping, Dataset-Level Pruning Only, ldm_include Authoring Headroom, filter_ai_context, AiSelection, Domain, build_entity_index, expand_join_ancestors (+1 more)

### Community 23 - "Meridian Breakdown and Tasks"
Cohesion: 0.29
Nodes (8): /breakdown — technical decomposition, Context discipline — pass paths, never contents, Stage-at-a-time agent fan-out, Write-once, no revision pass, Lifecycle guard on status before task generation, Per-task Pre: precondition line, /tasks — atomic task list generator, Feature lifecycle (idea → draft → in-progress → done → in-production)

### Community 24 - "Shared Interface Contract"
Cohesion: 0.29
Nodes (8): Shared Interface Contract (CONTRACT.md), DomainManifest / Domain / AiSelection types, GlobalmartError base exception hierarchy, One module, one owning feature, On-disk path table (layouts/, generated/, config/, data/), Shared test fixture registry, verify.py ownership collision (FEAT-004 vs FEAT-006), Domain glossary (parent, child, split, prune, closure, LI)

### Community 25 - "Domain Coverage Enforcement"
Cohesion: 0.29
Nodes (7): Coverage-or-Explicit-Exclusion Enforcement, coverage.check_coverage, DomainManifest, UnassignedSelection, expect.check_coverage, publish_domains, iter_dashboard_insight_refs

### Community 26 - "Verification and Failure Classification"
Cohesion: 0.33
Nodes (6): classify, FailureCategory, execute_visualization, check_wdf_values, render_markdown, verify_target

### Community 27 - "Domain Manifest Bootstrap"
Cohesion: 0.40
Nodes (5): config/domains.yaml, viz_<domain>_ Prefix Convention (bootstrap-only), bootstrap_manifest, SEED_DOMAINS, load_domains

### Community 28 - "SDK Version Floor Tests"
Cohesion: 0.40
Nodes (3): The SDK version floor is a correctness constraint, not a preference.…, Named separately: this is the one the user explicitly asked for., test_memory_items_are_modelled()

### Community 29 - "Bonus Cost Metric Duplicates"
Cohesion: 0.50
Nodes (4): Metric: Average L1 Bonus Cost, Metric: Average L1 Bonus Cost (Duplicate), Metric: Average Total Bonus Cost, Metric: Average Total Bonus Cost (Variant)

### Community 30 - "Data Archive Fetch"
Cohesion: 0.67
Nodes (3): data/archive-manifest.json, fetch_archive, verify_archive

### Community 31 - "Sales Amount Metric Duplicates"
Cohesion: 0.67
Nodes (3): Metric: Average Sales Amount (Daily Store Sales), Metric: Average Total Sales Amount (Daily Store Sales), Metric: Average Total Sales Amount (Daily Store Sales) Copy

### Community 32 - "Customer Visualizations and Dates"
Cohesion: 0.67
Nodes (3): Visualization: Points Redeemed by Month (viz_customer_0096), Visualization: Event Count by Quarter (viz_customer_0097), Date Instance: Fiscal Date

## Ambiguous Edges - Review These
- `Visualization: Points Redeemed by Month (viz_customer_0096)` → `Date Instance: Fiscal Date`  [AMBIGUOUS]
  tests/fixtures/mini_globalmart/ldm/date_instances/fiscal_date.yaml · relation: conceptually_related_to

## Knowledge Gaps
- **41 isolated node(s):** `globalmart`, `550-word A4 hard limit`, `ADR structure (Decision / Alternatives / Consequences / Revisit Trigger)`, `--latest-screenshot capture mechanism`, `Screenshot sidecar notes file` (+36 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 249 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Visualization: Points Redeemed by Month (viz_customer_0096)` and `Date Instance: Fiscal Date`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `normalize_workspace()` connect `Datasource Parameterization` to `Backup and Target Profiles`, `Placeholder Resolution`, `Workspace Publishing`, `CLI Behaviour Tests`, `Model Digest and Diff`, `Normalizer Six Passes`, `Object Counting`, `CLI Entry Point`, `Round-Trip Acceptance Harness`, `Result Value Objects`, `Feature Roadmap FEAT-001..008`?**
  _High betweenness centrality (0.119) - this node is a cross-community bridge._
- **Why does `publish_workspace()` connect `Workspace Publishing` to `Backup and Target Profiles`, `Placeholder Resolution`, `Model Digest and Diff`, `Object Counting`, `CLI Entry Point`, `Warehouse Loading and Cold Rebuild`, `Result Value Objects`, `Domain Coverage Enforcement`?**
  _High betweenness centrality (0.114) - this node is a cross-community bridge._
- **Why does `read_tree()` connect `Object Counting` to `Backup and Target Profiles`, `Placeholder Resolution`, `Workspace Publishing`, `Datasource Parameterization`, `CLI Behaviour Tests`, `Deterministic YAML Layout IO`, `Model Digest and Diff`, `CLI Entry Point`, `Round-Trip Acceptance Harness`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `publish_workspace()` (e.g. with `TargetProfile` and `test_apply_defaults_to_false()`) actually correct?**
  _`publish_workspace()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `globalmart`, `550-word A4 hard limit`, `ADR structure (Decision / Alternatives / Consequences / Revisit Trigger)` to the rest of the system?**
  _41 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Backup and Target Profiles` be split into smaller, more focused modules?**
  _Cohesion score 0.052393857271906055 - nodes in this community are weakly interconnected._