---
kind: explanation
title: Why there are 1,091 metrics
scope: metrics
owner: analytics-eng
anchor: true
---

# Why there are 1,091 metrics

## Five levels, each built on the one below

GlobalMart's metrics are generated in a deliberate five-level hierarchy, and the level is in
the identifier:

| Level | Count | Shape | Built from |
|---|---|---|---|
| L1 | 122 | `SELECT SUM({fact/…})` | a fact column |
| L2 | 122 | `SELECT {L1} / {L1}` | two L1 metrics |
| L3 | 366 | `SELECT {L1} WHERE {label} IN (…)` | one L1 plus a filter |
| L4 | 400 | `SELECT {L3} - (SELECT {L3} FOR PREVIOUS (…))` | one L3 plus a period shift |
| L5 | 61 | `SELECT {L4} + ({L1} / {L1})` | an L4 plus a ratio |

The remaining 20 metrics are hand-named rather than generated, and have their own document.

## The point of the shape

A workspace with 1,091 metrics is not pretending that a retailer needs 1,091 metrics. The
hierarchy exists so that anything reasoning over this workspace — a person, an AI
assistant, a routing agent — meets the problem a real semantic layer poses: metrics that
reference other metrics, several layers deep, where understanding one means resolving a
chain. A flat list of fifty clean metrics would not pose that problem.

## What this means for retrieval and for answers

Depth is the difficulty. Asked about `metric_l5_0001`, the honest answer requires unwinding
an L4, which unwinds an L3, which unwinds an L1, which lands on a fact column — five hops
to reach a definition. Anything that answers such a question from the title alone is
guessing, because the titles are generated from the structure and describe the arithmetic
rather than the meaning.

## Titles describe arithmetic, not intent

`metric_l2_cross_0000` is titled "Order Count per Net Revenue". That is a truthful
description of what it computes and a poor description of why anyone would want it — orders
divided by revenue is the reciprocal of average order value, which is not a figure anybody
asks for. The L2 metrics pair L1 metrics combinatorially, so many of them are arithmetically
valid and analytically meaningless. Treat an L2 metric's existence as evidence about the
generator, not as evidence that the ratio is used.
