"""FEAT-016 — the guard that the README cannot drift away from the repo.

The README is a projection of six other sources: two argparse surfaces, the domain manifest,
the table manifest, the docs tree and the specs tree. Every one of them moves independently,
and a front door that documents commands which no longer exist is worse than no front door.

Same shape as `test_counts.py`, which pins `docs/bootstrap-provenance.md` for the same reason:
parse the committed document, compare it against what the repo actually holds, fail loudly.
Nothing here executes a command — the parsers are introspected, never run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"

#: Prose is the thing the budget is about — a table row or a command is not prose, and the
#: acceptance criterion counts them out explicitly. Slack is deliberate: an honest paragraph
#: should not turn the build red.
PROSE_BUDGET = 150


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _lines_outside_fences(text: str) -> list[str]:
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return out


def _fenced_blocks(text: str, language: str) -> list[str]:
    return re.findall(rf"^```{language}\n(.*?)^```", text, re.MULTILINE | re.DOTALL)


def _subcommands(parser: object, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    found: set[tuple[str, ...]] = set()
    for action in getattr(parser, "_actions", []):
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            for name, sub in choices.items():
                found.add((*prefix, name))
                found |= _subcommands(sub, (*prefix, name))
    return found


def _known_subcommands(entry_point: str) -> set[tuple[str, ...]]:
    """Every registered subcommand path, without running one.

    `globalmart.cli` exposes `build_parser()`. `gd_agents.cli` builds its parser inside
    `main()` and exposes nothing, so the parser is reached through the registered
    `set_defaults(func=...)` callbacks by constructing it the same way `main` does — still
    pure argparse construction, no command body is entered.
    """
    if entry_point == "globalmart":
        from globalmart.cli import build_parser

        return _subcommands(build_parser())

    import contextlib
    import io

    from gd_agents import cli as agents_cli

    # `main(["--help"])` builds the parser, prints usage and raises SystemExit before doing
    # any work. The usage line carries the registered choices, which is what is being checked.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.suppress(SystemExit):
        agents_cli.main(["--help"])
    match = re.search(r"\{([a-z0-9,\-]+)\}", buffer.getvalue())
    assert match, "could not read gd-agents subcommands from its usage line"
    return {(name,) for name in match.group(1).split(",")}


def test_every_relative_link_resolves() -> None:
    """A dead link in the front door is the failure mode this file exists to prevent."""
    broken = [
        target
        for target in re.findall(r"\]\(([^)]+)\)", _readme())
        if not target.startswith(("http://", "https://", "#"))
        and not (REPO_ROOT / target).exists()
    ]
    assert not broken, f"README links to paths that do not exist: {broken}"


def test_the_counts_match_their_sources() -> None:
    """Every number the README prints has a committed file behind it."""
    text = _readme()

    manifest = json.loads((REPO_ROOT / "data" / "table-manifest.json").read_text())
    tables = manifest["tables"]
    rows = sum(t["rows"] for t in tables.values())
    assert f"{len(tables)} tables" in text, f"README should state {len(tables)} tables"
    assert f"{rows:,} rows" in text, f"README should state {rows:,} rows"

    domains = yaml.safe_load((REPO_ROOT / "config" / "domains.yaml").read_text())["domains"]
    count = len(domains)
    children = sorted((REPO_ROOT / "generated" / "workspaces").glob("globalmart-*.json"))
    assert count == len(children), (
        f"{count} domains declared but {len(children)} children generated — run `globalmart split`"
    )
    assert f"{count} domain workspaces" in text or f"{count} derived children" in text, (
        f"README should state the domain count as {count}"
    )


@pytest.mark.parametrize("entry_point", ["globalmart", "gd-agents"])
def test_every_command_shown_is_a_real_subcommand(entry_point: str) -> None:
    """Each command in a bash block is a subcommand path that actually exists.

    Introspects the registered subparsers rather than executing anything: running the real
    commands would need credentials, and half of them write.
    """
    known = _known_subcommands(entry_point)
    shown: set[tuple[str, ...]] = set()
    for block in _fenced_blocks(_readme(), "bash"):
        for line in block.splitlines():
            line = line.split("#", 1)[0].strip().rstrip("\\").strip()
            if not line.startswith(f"{entry_point} "):
                continue
            words = [w for w in line.split()[1:] if not w.startswith("-")]
            for depth in (2, 1):
                if tuple(words[:depth]) in known:
                    shown.add(tuple(words[:depth]))
                    break
            else:
                if words:
                    shown.add((words[0],))

    unknown = sorted(" ".join(c) for c in shown - known)
    assert not unknown, f"README shows {entry_point} commands that do not exist: {unknown}"


def test_the_prose_budget_holds() -> None:
    """Comprehensive means well-organized and linked, not long."""
    prose = [
        line
        for line in _lines_outside_fences(_readme())
        if line.strip() and not line.strip().startswith(("|", "#"))
    ]
    assert len(prose) <= PROSE_BUDGET, (
        f"README prose is {len(prose)} lines, over the {PROSE_BUDGET}-line budget — "
        "cut a paragraph into a link rather than raising the ceiling"
    )


def test_the_mermaid_diagram_is_present_and_balanced() -> None:
    """A diagram that does not parse renders as a grey box on GitHub, silently."""
    blocks = _fenced_blocks(_readme(), "mermaid")
    assert len(blocks) == 1, f"expected exactly one mermaid block, found {len(blocks)}"
    diagram = blocks[0]
    assert diagram.lstrip().startswith("flowchart"), "mermaid block should declare a flowchart"
    assert diagram.count("subgraph") == diagram.count("end"), (
        "mermaid subgraph/end mismatch — the diagram will not render"
    )
    assert "-->" in diagram, "a flowchart with no edges is a list"
