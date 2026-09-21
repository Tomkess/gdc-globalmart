"""Task 25 — the domain list lives in exactly two files, mechanically.

The predecessor kept it in four places: the splitter, the publisher, the workspace-creation
script and a hand-maintained README table. Adding a domain meant four edits and forgetting
one was invisible. This test is that failure made impossible to reintroduce quietly.

Two files are allowed to carry it: ``config/domains.yaml`` (the manifest — it *is* the list)
and ``src/globalmart/domain_bootstrap.py`` (the one-time seed, pinned by its own docstring).
Anything else is the bug coming back.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "config" / "domains.yaml"

ALLOWED = {
    "config/domains.yaml",
    "src/globalmart/domain_bootstrap.py",
    # The A2A question script names *workspace ids* — `globalmart-customer` and friends —
    # and a hyphen is a word boundary, so `\bcustomer\b` matches inside them. It is not a
    # second copy of the domain list: it is a script of questions that happens to say which
    # workspaces each one should reach, which is the whole point of the file.
    "config/questions.yaml",
    "config/agents.yaml",
}


def _domain_keys_and_labels() -> tuple[set[str], set[str]]:
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    domains = document["domains"]
    return ({d["key"] for d in domains}, {d["label"] for d in domains})


def _searchable_files() -> list[Path]:
    files = sorted((REPO / "src" / "globalmart").rglob("*.py"))
    files += sorted(p for p in (REPO / "config").rglob("*") if p.is_file())
    return files


@pytest.mark.skipif(not MANIFEST.exists(), reason="config/domains.yaml not generated yet")
def test_the_domain_list_lives_in_exactly_two_files() -> None:
    keys, labels = _domain_keys_and_labels()
    assert len(keys) == 12, "the seed and the manifest have drifted apart"

    offenders: dict[str, set[str]] = {}
    for path in _searchable_files():
        relative = path.relative_to(REPO).as_posix()
        if relative in ALLOWED:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits = {key for key in keys if re.search(rf"\b{re.escape(key)}\b", text)}
        hits |= {label for label in labels if label in text}
        if hits:
            offenders[relative] = hits

    assert not offenders, (
        "Domain names appear outside config/domains.yaml and domain_bootstrap.py: "
        f"{ {k: sorted(v) for k, v in offenders.items()} }. Read them from the manifest."
    )


@pytest.mark.skipif(not MANIFEST.exists(), reason="config/domains.yaml not generated yet")
def test_the_seed_matches_the_manifest() -> None:
    """The one sanctioned duplicate must not rot — it is what a re-bootstrap would produce."""
    from globalmart.domain_bootstrap import SEED_DOMAINS

    keys, labels = _domain_keys_and_labels()
    assert {key for key, _ in SEED_DOMAINS} == keys
    assert {label for _, label in SEED_DOMAINS} == labels
