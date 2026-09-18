"""Task 27 — CLI behaviour, especially the --check gate and the no-write rehearsal."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from globalmart.cli import build_parser, main
from globalmart.layout_io import read_tree, write_tree
from globalmart.normalize import normalize_workspace

FIXTURE = Path(__file__).parent / "fixtures" / "mini_globalmart"
SCHEMA = "globalmart"


def _normalized_tree(destination: Path) -> Path:
    model = read_tree(FIXTURE)
    normalize_workspace(model, datasource_schema=SCHEMA)
    write_tree(model, destination)
    return destination


def test_check_passes_on_a_normalized_tree(tmp_path: Path) -> None:
    tree = _normalized_tree(tmp_path / "tree")
    assert main(["normalize", "--path", str(tree), "--check", "--datasource-schema", SCHEMA]) == 0


def test_check_fails_on_the_raw_fixture(tmp_path: Path) -> None:
    """The committed fixture keeps its audit fields on purpose, so it is not canonical."""
    copy = tmp_path / "raw"
    shutil.copytree(FIXTURE, copy)
    assert main(["normalize", "--path", str(copy), "--check", "--datasource-schema", SCHEMA]) == 1


def test_check_writes_nothing(tmp_path: Path) -> None:
    """--check must never mutate the tree it inspects, even when it reports differences."""
    copy = tmp_path / "raw"
    shutil.copytree(FIXTURE, copy)
    before = {p: p.read_text(encoding="utf-8") for p in sorted(copy.rglob("*.yaml"))}

    main(["normalize", "--path", str(copy), "--check", "--datasource-schema", SCHEMA])

    after = {p: p.read_text(encoding="utf-8") for p in sorted(copy.rglob("*.yaml"))}
    assert after == before


def test_check_detects_a_hand_edited_file(tmp_path: Path) -> None:
    """The reason the gate exists: STEERING calls hand-editing a generated file a defect."""
    tree = _normalized_tree(tmp_path / "tree")
    victim = next(iter(sorted(tree.rglob("analytics_model/metrics/*.yaml"))))
    victim.write_text(victim.read_text(encoding="utf-8") + "\nhandEdited: true\n", encoding="utf-8")

    assert main(["normalize", "--path", str(tree), "--check", "--datasource-schema", SCHEMA]) == 1


def test_check_detects_a_reintroduced_user_reference(tmp_path: Path) -> None:
    tree = _normalized_tree(tmp_path / "tree")
    victim = next(iter(sorted(tree.rglob("analytics_model/metrics/*.yaml"))))
    text = victim.read_text(encoding="utf-8")
    victim.write_text("createdBy:\n  id: someone\n  type: user\n" + text, encoding="utf-8")

    assert main(["normalize", "--path", str(tree), "--check", "--datasource-schema", SCHEMA]) == 1


def test_normalize_without_check_rewrites_in_place(tmp_path: Path) -> None:
    copy = tmp_path / "raw"
    shutil.copytree(FIXTURE, copy)

    assert main(["normalize", "--path", str(copy), "--datasource-schema", SCHEMA]) == 0
    assert main(["normalize", "--path", str(copy), "--check", "--datasource-schema", SCHEMA]) == 0


def test_bootstrap_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A rehearsal must reach the host but leave the filesystem untouched."""
    import globalmart.cli as cli

    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD", "tok")
    monkeypatch.setattr(cli, "make_sdk", lambda profile: object())
    monkeypatch.setattr(cli, "capture_workspace", lambda sdk, workspace_id: read_tree(FIXTURE))

    destination = tmp_path / "out"
    exit_code = main(["bootstrap", "--target", "demo-cloud", "--out", str(destination), "--dry-run"])

    assert exit_code == 0
    assert not destination.exists()
    assert "REHEARSAL" in capsys.readouterr().out


def test_bootstrap_writes_a_normalized_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import globalmart.cli as cli

    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD", "tok")
    monkeypatch.setattr(cli, "make_sdk", lambda profile: object())
    monkeypatch.setattr(cli, "capture_workspace", lambda sdk, workspace_id: read_tree(FIXTURE))

    destination = tmp_path / "out"
    assert main(["bootstrap", "--target", "demo-cloud", "--out", str(destination)]) == 0

    blob = "\n".join(p.read_text(encoding="utf-8") for p in destination.rglob("*.yaml"))
    assert "createdBy" not in blob
    assert "globalmart-motherduck" not in blob
    assert main(["normalize", "--path", str(destination), "--check", "--datasource-schema", SCHEMA]) == 0


def test_bootstrap_has_no_apply_flag() -> None:
    """ADR 002's convention: --apply gates remote writes; bootstrap writes local files only."""
    actions = {a.dest for a in build_parser()._subparsers._group_actions[0].choices["bootstrap"]._actions}  # type: ignore[union-attr]
    assert "apply" not in actions
    assert "dry_run" in actions


def test_normalize_has_no_apply_flag() -> None:
    actions = {a.dest for a in build_parser()._subparsers._group_actions[0].choices["normalize"]._actions}  # type: ignore[union-attr]
    assert "apply" not in actions


def test_unknown_profile_exits_one(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["bootstrap", "--target", "does-not-exist"]) == 1
    assert "error:" in capsys.readouterr().err


def _unused(*_: Any) -> None:  # pragma: no cover - keeps the import list honest
    pass


# --- publish (FEAT-002 task 34) ---------------------------------------------


def test_publish_has_apply_and_no_dry_run() -> None:
    """ADR 002's convention, pinned: --apply gates remote writes, and no command has both."""
    choices = build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    parent = choices["publish"]._subparsers._group_actions[0].choices["parent"]  # type: ignore[union-attr]
    dests = {a.dest for a in parent._actions}

    assert "apply" in dests
    assert "dry_run" not in dests


def test_publish_rehearsal_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import globalmart.cli as cli

    from .conftest import FakeSdk

    sdk = FakeSdk()
    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD", "tok")
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "s")
    monkeypatch.setattr(cli, "make_sdk", lambda profile: sdk)

    tree = _normalized_tree(tmp_path / "tree")
    exit_code = main(["publish", "parent", "--target", "demo-cloud", "--source", str(tree)])

    assert exit_code == 0
    assert sdk.writes() == []
    assert "REHEARSAL" in capsys.readouterr().out


def test_publish_apply_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import globalmart.cli as cli

    from .conftest import FakeSdk

    sdk = FakeSdk()
    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD", "tok")
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "s")
    monkeypatch.setattr(cli, "make_sdk", lambda profile: sdk)

    tree = _normalized_tree(tmp_path / "tree")
    exit_code = main(
        ["publish", "parent", "--target", "demo-cloud", "--source", str(tree), "--apply"]
    )

    assert exit_code == 0
    assert "put_declarative_workspace" in sdk.writes()


def test_no_backup_without_apply_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Meaningless in a rehearsal — and a real foot-gun if silently accepted."""
    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD", "tok")
    tree = _normalized_tree(tmp_path / "tree")

    with pytest.raises(SystemExit) as excinfo:
        main(["publish", "parent", "--target", "demo-cloud", "--source", str(tree), "--no-backup"])
    assert excinfo.value.code == 2


def test_publish_without_a_tree_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD", "tok")

    assert main(["publish", "parent", "--target", "demo-cloud", "--source", "does/not/exist"]) == 1
