# 003 — What under `generated/` is committed, and what is regenerated

**Status:** Accepted
**Date:** 2026-09-18
**Context:** feat-004 (domain splitter), feat-005 (data generator); clarifies ADR 001

## Decision

`generated/` holds two kinds of output and they are treated oppositely:

- **`generated/workspaces/*.json` — committed.** The 12 derived domain layouts are reviewable
  semantic content. A diff there says "this metric left the HR child" or "this dataset is no longer
  pruned", which is exactly the review surface ADR 001 was created to produce.
- **`generated/data/**` — gitignored.** Generated warehouse rows are ~900 MB per scale factor and
  have no meaningful git delta between regenerations. Committing them would make the repo unusable
  within a few iterations and would add nothing to recoverability, because the reproducibility
  guarantee for data is *the generator plus the seed*, not the bytes.

What is committed for data instead: the generator source, `data/generation_rules.yaml`,
`data/vocab/*.txt`, the DDL, and a small golden **manifest** (row counts and per-table checksums at
a tiny scale) that CI diffs across platforms. The manifest is a sharper review surface than a CSV
diff nobody reads.

The rule in one line: **commit what a human reviews, regenerate what a machine consumes.**

## Alternatives Considered

| Option | Pros | Cons |
|---|---|---|
| Chosen: split by reviewability — layouts committed, data regenerated + golden manifest | Reviewable diffs where they carry meaning; repo stays small; determinism still provable in CI | Two rules for one directory, which must be documented or it looks inconsistent |
| Commit everything under `generated/` | One simple rule; byte-exact recovery of data without running anything | ~900 MB per scale, unusable history, review noise that trains people to ignore diffs |
| Commit nothing under `generated/` | Smallest repo; one simple rule | Loses ADR 001's whole point — the domain children stop being reviewable artifacts and silent split regressions return |
| Commit data to Git LFS or object storage | Keeps bytes recoverable without repo bloat | Reintroduces an external dependency of exactly the kind goal-01 exists to remove (the S3 bucket problem, renamed) |

## Consequences

- **Positive:** a split regression is visible in review; the repo stays clonable; data reproducibility
  is enforced by a determinism test rather than by storage.
- **Negative / trade-offs:** one directory carries two `.gitignore` rules, which is surprising
  without this ADR; recovering a specific past dataset means re-running the generator at the recorded
  seed and scale rather than checking out bytes.
- **Neutral:** the golden manifest must be regenerated deliberately whenever generation rules change,
  and that diff is the signal that they did.

## Revisit Trigger

If the generated layouts ever grow past the point where their diffs stop being read — or if a domain
child's JSON becomes large enough to dominate review — revisit committing them and lean on FEAT-006's
verification plus the manifest approach instead.
