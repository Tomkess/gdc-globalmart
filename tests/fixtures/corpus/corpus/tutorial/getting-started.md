---
kind: tutorial
title: Reading this fixture corpus
scope: getting-started
owner: analytics-eng
---

# Reading this fixture corpus

## What this corpus is for

This is the miniature corpus the offline tests parse. It documents the objects in
`tests/fixtures/mini_globalmart`, and it exists so that every validator can be exercised
against real prose rather than against strings assembled in a test body.

## Why it covers nothing

A tutorial documents a path through the product rather than a particular metric or dataset,
so this document carries no `covers:` block at all. That is legitimate, and the coverage
report lists it under documents-covering-nothing rather than failing the build.
