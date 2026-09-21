---
kind: explanation
title: Where GlobalMart's data comes from
scope: warehouse
owner: analytics-eng
anchor: true
---

# Where GlobalMart's data comes from

## It is synthetic, and that is the first thing to say

No row in GlobalMart describes a real customer, employee, store or transaction. Every value
is produced by a seeded generator in this repository. The model is realistic — 227 datasets,
proper grains, conformed dimensions — and the *behaviour* in the numbers is not: trends,
seasonality, funnel drop-off and correlations between subject areas are artefacts of the
generator rather than findings about retail.

This matters when answering questions. "Why did online orders fall in March?" has no
answer here beyond the generator's randomness, and the honest response says so rather than
inventing a merchandising explanation.

## Why it is generated rather than stored

GlobalMart inherited its data from an S3 bucket nobody in the project controlled, which
became inaccessible. The replacement was to commit the rows; that was then replaced again by
generating them. What is committed now is the contract — the DDL and a manifest of columns
and row counts — because that is what a human can review in a diff. A 2.3 MB blob of
gzipped CSVs cannot be reviewed, only trusted.

The consequence worth knowing: a clone of this repository has no rows in it. The data exists
after `globalmart data generate`, and a workspace published against an unloaded warehouse
has a correct semantic layer over nothing.

## Determinism is the property that makes it useful

The same seed and scale produce byte-identical output. That is what lets two evaluation runs
be compared, lets a bug be reproduced, and lets the row counts be asserted in CI. It also
means "the data changed" is always attributable to a seed change, a scale change or a date
window change — never to drift.

## One table is synthesised differently

`fact_search_event` has no counterpart in the original inherited dataset; it was synthesised
when custody of the data moved into this repository, to support search-behaviour questions.
It is generated like everything else, but it is the one table with no inherited ancestry.

## The window moves, the history does not

Regenerating with a later end date produces a *new* two-year window, not an extension of the
old one. Nothing accumulates: there is no historical archive, and a figure quoted from last
month's generation will not be reproducible from this month's unless the seed and dates are
given too.
