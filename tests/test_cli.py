"""Task 27 — CLI behaviour, especially the --check gate and the no-write rehearsal."""

from __future__ import annotations

import argparse
import dataclasses
import shutil
from pathlib import Path
from typing import Any

import pytest

from globalmart.cli import build_parser, main
from globalmart.gdcloud_bridge import load_canonical_data_source
from globalmart.layout_io import write_tree
from globalmart.resolve import rewrite_data_source

from .conftest import ENV_CONFIG, MINI, MINI_CANONICAL, committed_mini

FIXTURE = MINI


def _committed_tree(destination: Path) -> Path:
    """The mini capture as gd_data_product holds a tree: gd-store form, the repo's canonical data source."""
    model = committed_mini()
    rewrite_data_source(model, source=MINI_CANONICAL, target=load_canonical_data_source(ENV_CONFIG))
    write_tree(model, destination)
    return destination


def test_retired_commands_are_gone() -> None:
    """ADR 011 Stage B: capture is gd-store, formatting is gd-format-yaml, there is no projection."""
    choices = build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    assert "bootstrap" not in choices
    assert "normalize" not in choices
    gdcloud = choices["gdcloud"]._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    assert "project" not in gdcloud


def test_unknown_profile_exits_one(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["targets", "inspect", "--target", "does-not-exist"]) == 1
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

    tree = _committed_tree(tmp_path / "tree")
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

    tree = _committed_tree(tmp_path / "tree")
    exit_code = main(["publish", "parent", "--target", "demo-cloud", "--source", str(tree), "--apply"])

    assert exit_code == 0
    assert "put_declarative_workspace" in sdk.writes()


def test_no_backup_without_apply_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Meaningless in a rehearsal — and a real foot-gun if silently accepted."""
    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD", "tok")
    tree = _committed_tree(tmp_path / "tree")

    with pytest.raises(SystemExit) as excinfo:
        main(["publish", "parent", "--target", "demo-cloud", "--source", str(tree), "--no-backup"])
    assert excinfo.value.code == 2


def test_publish_without_a_tree_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD", "tok")

    assert main(["publish", "parent", "--target", "demo-cloud", "--source", "does/not/exist"]) == 1


# --- domains (FEAT-003 task 24) ----------------------------------------------

DOMAIN_FIXTURES = Path(__file__).parent / "fixtures" / "domains"


def test_domains_validate_passes_and_prints_the_table(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [
            "domains",
            "validate",
            "--manifest",
            str(DOMAIN_FIXTURES / "valid.yaml"),
            "--layout",
            str(FIXTURE),
            "--strict",
        ]
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "viz(via dash)" in out
    assert "Coverage is complete (strict)" in out


def test_domains_validate_names_the_uncovered_dashboard(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "domains",
            "validate",
            "--manifest",
            str(DOMAIN_FIXTURES / "missing_coverage.yaml"),
            "--layout",
            str(FIXTURE),
        ]
    )

    assert exit_code == 1
    assert "dashboard_mixed" in capsys.readouterr().err


def test_domains_validate_json_is_parseable(capsys: pytest.CaptureFixture[str]) -> None:
    import json

    main(
        [
            "domains",
            "validate",
            "--manifest",
            str(DOMAIN_FIXTURES / "valid.yaml"),
            "--layout",
            str(FIXTURE),
            "--format",
            "json",
        ]
    )

    report = json.loads(capsys.readouterr().out)
    assert report["dashboards_total"] == 2
    assert report["per_domain"]["sales"]["ldm_include"] == 1


def test_domains_bootstrap_dry_run_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    destination = tmp_path / "domains.yaml"

    exit_code = main(
        ["domains", "bootstrap", "--layout", str(FIXTURE), "--out", str(destination), "--dry-run"]
    )

    assert exit_code == 0
    assert not destination.exists()
    assert "REHEARSAL" in capsys.readouterr().out


def test_domains_bootstrap_refuses_to_overwrite_a_reviewed_manifest(tmp_path: Path) -> None:
    """The prefix convention may produce this file once, never overwrite a reviewed one."""
    destination = tmp_path / "domains.yaml"
    destination.write_text("version: 1\n", encoding="utf-8")

    exit_code = main(["domains", "bootstrap", "--layout", str(FIXTURE), "--out", str(destination)])

    assert exit_code == 1
    assert destination.read_text(encoding="utf-8") == "version: 1\n"


def test_domains_bootstrap_force_overwrites(tmp_path: Path) -> None:
    destination = tmp_path / "domains.yaml"
    destination.write_text("version: 1\n", encoding="utf-8")

    exit_code = main(["domains", "bootstrap", "--layout", str(FIXTURE), "--out", str(destination), "--force"])

    assert exit_code == 0
    assert "parent_workspace_id" in destination.read_text(encoding="utf-8")


def test_domains_commands_take_no_apply_flag() -> None:
    """Offline and local-file-only, so ADR 002 gives them --dry-run, never --apply."""
    choices = build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    actions = choices["domains"]._subparsers._group_actions[0].choices  # type: ignore[union-attr]

    assert "apply" not in {a.dest for a in actions["validate"]._actions}
    assert "apply" not in {a.dest for a in actions["bootstrap"]._actions}
    assert "dry_run" in {a.dest for a in actions["bootstrap"]._actions}


# --- data (FEAT-005) ---------------------------------------------------------


def test_data_verify_passes_on_the_committed_data(capsys: pytest.CaptureFixture[str]) -> None:
    repo = Path(__file__).resolve().parents[1]
    if not (repo / "data" / "tables").exists():
        pytest.skip("committed data not present")

    assert main(["data", "verify"]) == 0
    out = capsys.readouterr().out
    assert "215" in out
    assert "every SQL dataset resolves" in out


def test_data_load_has_apply_and_no_dry_run() -> None:
    """Writes to a live warehouse, so ADR 002 gives it --apply and no --dry-run."""
    choices = build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    actions = choices["data"]._subparsers._group_actions[0].choices  # type: ignore[union-attr]

    dests = {a.dest for a in actions["load"]._actions}
    assert "apply" in dests
    assert "dry_run" not in dests
    assert "apply" not in {a.dest for a in actions["verify"]._actions}


def test_data_load_refuses_a_profile_that_does_not_own_its_data(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """demo-cloud is the live schema both orgs query; it must not be loadable."""
    repo = Path(__file__).resolve().parents[1]
    if not (repo / "data" / "tables").exists():
        pytest.skip("committed data not present")

    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD", "tok")
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "secret")

    assert main(["data", "load", "--target", "demo-cloud", "--apply"]) == 1
    assert "data_owned" in capsys.readouterr().err


# --- verify / rebuild (FEAT-006) ---------------------------------------------


def test_verify_takes_no_apply_and_no_dry_run() -> None:
    """Read-only, so ADR 002 gives it neither gate. --list-only is the no-execution form."""
    choices = build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    dests = {a.dest for a in choices["verify"]._actions}

    assert "apply" not in dests
    assert "dry_run" not in dests
    assert "list_only" in dests
    assert "fail_on_empty" in dests


def test_rebuild_takes_apply_and_no_dry_run() -> None:
    choices = build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    dests = {a.dest for a in choices["rebuild"]._actions}

    assert "apply" in dests
    assert "dry_run" not in dests
    assert "allow_existing" in dests


def test_verify_equivalence_is_a_subcommand() -> None:
    choices = build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    actions = choices["verify"]._subparsers._group_actions[0].choices  # type: ignore[union-attr]

    dests = {a.dest for a in actions["equivalence"]._actions}
    assert {"target_a", "target_b", "workspace_id"} <= dests


# --- knowledge (FEAT-008) ----------------------------------------------------


def test_knowledge_build_has_check_and_no_apply() -> None:
    """A local-file writer, so ADR 002 gives it --check and never --apply."""
    choices = build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    actions = choices["knowledge"]._subparsers._group_actions[0].choices  # type: ignore[union-attr]

    dests = {a.dest for a in actions["build"]._actions}
    assert "check" in dests
    assert "apply" not in dests


def test_knowledge_build_writes_items(tmp_path: Path) -> None:

    tree = tmp_path / "tree"
    shutil.copytree(FIXTURE, tree)
    source = Path(__file__).parent / "fixtures" / "knowledge_ok"

    assert main(["knowledge", "build", "--source", str(source), "--layout", str(tree)]) == 0
    written = sorted(p.stem for p in (tree / "analytics_model" / "memory_items").glob("*.yaml"))
    assert "net_revenue_gross_revenue" in written


def test_knowledge_check_exits_one_on_drift(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:

    tree = tmp_path / "tree"
    shutil.copytree(FIXTURE, tree)
    source = Path(__file__).parent / "fixtures" / "knowledge_ok"

    assert main(["knowledge", "build", "--source", str(source), "--layout", str(tree), "--check"]) == 1
    assert "does not match" in capsys.readouterr().err
    # --check writes nothing: the fixture's own captured memory item is all that is there.
    written = sorted(p.stem for p in (tree / "analytics_model" / "memory_items").glob("*.yaml"))
    assert written == ["mem_sales_definitions"]


def test_knowledge_check_exits_zero_once_current(tmp_path: Path) -> None:

    tree = tmp_path / "tree"
    shutil.copytree(FIXTURE, tree)
    source = Path(__file__).parent / "fixtures" / "knowledge_ok"

    main(["knowledge", "build", "--source", str(source), "--layout", str(tree)])
    assert main(["knowledge", "build", "--source", str(source), "--layout", str(tree), "--check"]) == 0


# --- data generate (FEAT-007) ------------------------------------------------


def test_data_generate_writes_into_the_given_directory(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    if not (repo / "data" / "ddl" / "globalmart.sql").exists():
        pytest.skip("DDL not present")

    out = tmp_path / "gen"
    assert main(["data", "generate", "--out", str(out), "--seed", "3", "--scale", "0.01"]) == 0
    assert (out / "table-manifest.json").exists()
    assert len(list((out / "tables").glob("*.csv.gz"))) == 215


def test_data_generate_refuses_the_committed_archive(capsys: pytest.CaptureFixture[str]) -> None:
    repo = Path(__file__).resolve().parents[1]
    if not (repo / "data" / "ddl" / "globalmart.sql").exists():
        pytest.skip("DDL not present")

    assert main(["data", "generate", "--out", str(repo / "data")]) == 1
    assert "committed archive" in capsys.readouterr().err


def test_data_generate_has_no_apply() -> None:
    """A local-file writer; the loading is a separate, gated step."""
    choices = build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    actions = choices["data"]._subparsers._group_actions[0].choices  # type: ignore[union-attr]

    assert "apply" not in {a.dest for a in actions["generate"]._actions}
    assert "tables_dir" in {a.dest for a in actions["load"]._actions}


def _leaf_parsers(
    parser: argparse.ArgumentParser, path: tuple[str, ...] = ()
) -> dict[str, argparse.ArgumentParser]:
    """Every runnable command in the tree, keyed by its words, e.g. "gdcloud scope"."""
    subparsers = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    if not subparsers:
        return {" ".join(path): parser}
    leaves: dict[str, argparse.ArgumentParser] = {}
    for name, child in subparsers[0].choices.items():
        leaves.update(_leaf_parsers(child, (*path, name)))
    if not subparsers[0].required:
        leaves[" ".join(path)] = parser
    return leaves


def _dests(command: str) -> set[str]:
    return {a.dest for a in _leaf_parsers(build_parser())[command]._actions}


def test_no_command_has_both_apply_and_dry_run() -> None:
    """STEERING's binding convention, checked across the whole tree rather than per command."""
    both = [
        name
        for name, parser in _leaf_parsers(build_parser()).items()
        if {"apply", "dry_run"} <= {a.dest for a in parser._actions}
    ]
    assert both == []


def test_gdcloud_bootstrap_writes_only_under_apply() -> None:
    assert {"apply", "no_backup", "environment"} <= _dests("gdcloud bootstrap")
    assert "dry_run" not in _dests("gdcloud bootstrap")


def test_gdcloud_scope_is_read_only() -> None:
    assert not {"apply", "dry_run"} & _dests("gdcloud scope")


def test_data_ensure_check_is_the_ci_form() -> None:
    assert {"apply", "check"} <= _dests("data ensure")


def test_data_notify_writes_only_under_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    from globalmart import cli as cli_module

    assert "apply" in _dests("data notify") and "dry_run" not in _dests("data notify")
    sent: list[str] = []
    monkeypatch.setattr(
        cli_module, "load_profile", lambda name: type("P", (), {"datasource_id": "ds", "host": "h"})()
    )
    monkeypatch.setattr(cli_module, "make_sdk", lambda profile: object())
    monkeypatch.setattr(cli_module, "check_organization", lambda sdk, profile: None)
    monkeypatch.setattr(cli_module, "notify_upload", lambda sdk, profile: sent.append(profile.datasource_id))

    assert main(["data", "notify", "--target", "gdcloud-prod"]) == 0
    assert sent == []
    assert main(["data", "notify", "--target", "gdcloud-prod", "--apply"]) == 0
    assert sent == ["ds"]


def test_an_unknown_only_domain_fails_rather_than_selecting_less() -> None:
    """`--only store-ops` (the key is `store_ops`) used to publish the other three and exit 0."""
    from globalmart.cli import _only_domains
    from globalmart.config import GlobalmartError
    from globalmart.domains import load_domains

    manifest = load_domains(Path("config/domains.yaml"))
    args = argparse.Namespace(only="customer,store-ops")
    with pytest.raises(GlobalmartError, match="store-ops"):
        _only_domains(args, manifest)
    assert _only_domains(argparse.Namespace(only="customer,store_ops"), manifest) == {"customer", "store_ops"}
    assert _only_domains(argparse.Namespace(only=None), manifest) is None


# --- ADR 011 Stage B: one authoring tree -------------------------------------


def test_every_reader_defaults_to_the_gd_data_product_tree() -> None:
    """Every command that reads the parent reads gd_data_product/globalmart/ unless told otherwise."""
    import inspect

    from globalmart.knowledge import build_knowledge
    from globalmart.layout_io import DEFAULT_LAYOUT_PATH
    from globalmart.rebuild import RebuildOptions
    from globalmart.verification import VerifyOptions

    assert Path("gd_data_product/globalmart") == DEFAULT_LAYOUT_PATH

    readers = {
        name: {a.dest: a.default for a in parser._actions}
        for name, parser in _leaf_parsers(build_parser()).items()
    }
    layout_readers = {name for name, defaults in readers.items() if "layout" in defaults}
    assert {
        "domains validate",
        "domains bootstrap",
        "data verify",
        "data generate",
        "data load",
        "data ensure",
        "verify",
        "rebuild",
        "knowledge build",
        "knowledge-docs coverage",
        "datefilters bind",
    } <= layout_readers
    for name in layout_readers:
        assert readers[name]["layout"] == str(DEFAULT_LAYOUT_PATH), name
    assert readers["split"]["source"] == str(DEFAULT_LAYOUT_PATH)
    assert readers["publish parent"]["source"] == str(DEFAULT_LAYOUT_PATH)

    assert RebuildOptions().layout_path == DEFAULT_LAYOUT_PATH
    assert VerifyOptions().layout_path == DEFAULT_LAYOUT_PATH
    assert inspect.signature(build_knowledge).parameters["layout_path"].default == DEFAULT_LAYOUT_PATH

    stale = [
        f"{name} {dest}"
        for name, defaults in readers.items()
        for dest, default in defaults.items()
        if isinstance(default, str) and default.startswith("layouts/")
    ]
    assert stale == []


def test_publish_rehearsal_shows_the_data_source_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """demo-cloud-rebuild has a data source of its own; the plan must say what it rewrites to."""
    import globalmart.cli as cli

    from .conftest import FakeSdk

    sdk = FakeSdk(organization_id="gm-ddebmti")
    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD_REBUILD", "tok")
    monkeypatch.setenv("MOTHERDUCK_TOKEN", "s")
    monkeypatch.setattr(cli, "make_sdk", lambda profile: sdk)
    monkeypatch.setattr(cli, "load_profile", lambda name: _rebuild_profile(name))

    tree = _committed_tree(tmp_path / "tree")
    assert main(["publish", "parent", "--target", "demo-cloud-rebuild", "--source", str(tree)]) == 0

    out = capsys.readouterr().out
    canonical = load_canonical_data_source(ENV_CONFIG)
    rewrite = f"{canonical.datasource_id} / {canonical.datasource_schema}"
    assert f"{rewrite} -> globalmart-motherduck / globalmart_rebuild" in out
    assert sdk.writes() == []


def _rebuild_profile(name: str):  # type: ignore[no-untyped-def]
    from globalmart.config import load_profile

    profile = load_profile(name)
    return dataclasses.replace(profile, organization_id="gm-ddebmti")
