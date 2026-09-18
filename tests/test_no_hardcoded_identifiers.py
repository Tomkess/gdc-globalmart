"""Task 38 — no org, host, workspace or datasource identifier may live in code.

STEERING § Portability Contract, mechanized so it cannot rot. The predecessor kept the
domain list in four places and hardcoded hosts throughout; that is the failure mode this
test exists to make impossible.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "globalmart"

#: Identifiers that belong in config/targets.yaml or .env, never in a module.
FORBIDDEN = (
    "petertomko",
    "gm-ddebmti",
    "usecases-ai",
    "demo.cloud.gooddata.com",
    "globalmart-motherduck",
    "globalmart-postgres",
    "gd_demo",
)

#: Lines that legitimately mention an identifier while explaining why it is forbidden.
_COMMENT = re.compile(r"^\s*(#|\"\"\"|'''|\*)")


def _offending_lines() -> list[str]:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        in_docstring = False
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.count('"""') == 1:
                in_docstring = not in_docstring
                continue
            if in_docstring or _COMMENT.match(line):
                continue
            for needle in FORBIDDEN:
                if needle in line:
                    offenders.append(f"{path.relative_to(SRC.parent.parent)}:{number}: {stripped}")
    return offenders


def test_no_identifier_appears_in_executable_code() -> None:
    offenders = _offending_lines()
    assert offenders == [], (
        "org/host/datasource identifiers must come from config, not code:\n"
        + "\n".join(offenders)
    )


def test_the_scan_actually_looks_at_something() -> None:
    """Guard: a scan over zero files would pass vacuously."""
    assert list(SRC.rglob("*.py")), "no source files found to scan"
    assert len(list(SRC.rglob("*.py"))) >= 10
