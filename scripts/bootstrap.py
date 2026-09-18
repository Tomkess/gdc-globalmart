#!/usr/bin/env python
"""Shim for `uv run scripts/bootstrap.py ...` — the console script is `globalmart`."""

from globalmart.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
