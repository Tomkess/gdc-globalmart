---
id: goal-01
name: GlobalMart rebuildable from source into any domain
status: active
created: 2026-09-18
horizon: 1-year
measurable_outcome: A clean clone of this repo plus credentials for an empty GoodData org rebuilds the parent workspace and all 12 domain workspaces, with every visualization executing successfully and no manual step.
---

GlobalMart today exists as a live workspace plus a 2.9 MB exported JSON snapshot and a set of
one-off patch scripts, so the live org is the de-facto source of truth and a rebuild from scratch is
not possible. This goal moves the truth into the repo: the parent workspace stored as the
gooddata-python-sdk native YAML layout, the row data produced by code rather than fetched from an
opaque S3 bucket, and the 12 domain workspaces generated deterministically from the parent by a
splitter that prunes each child's LDM to what that domain actually uses. Success is measured by a
cold rebuild into a fresh org — no UI clicks, no live-org reads, no undocumented script ordering.
