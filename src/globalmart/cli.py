"""Command line entry point.

Two subcommands today:

``globalmart bootstrap --target <name>``
    Capture the parent workspace from a live host, normalize it, and write the YAML tree.
    Writes only local files, so per ADR 002's convention it takes ``--dry-run``, never
    ``--apply`` — that flag is reserved for commands that write to a live org.

``globalmart normalize [--check]``
    Re-normalize an existing tree in place. ``--check`` writes nothing and exits 1 if
    normalization would change anything: the CI gate that stops a hand-edited layout file
    from being committed in a non-canonical form.

``globalmart publish parent --target <name> [--apply]``
    Publish the committed tree into a live org. Writes to a **remote** org, so per ADR 002
    it is a read-only rehearsal by default and ``--apply`` is the only path to a write.
    Never takes ``--dry-run``; no command has both.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from globalmart.capture import capture_workspace
from globalmart.config import GlobalmartError, load_profile
from globalmart.counts import count_objects
from globalmart.layout_io import read_tree, write_tree
from globalmart.normalize import WdfPolicy, normalize_workspace
from globalmart.publish import PARENT_WORKSPACE_NAME, publish_workspace
from globalmart.sdk_client import make_sdk

DEFAULT_LAYOUT_PATH = Path("layouts/workspaces/globalmart")


def _print_report(title: str, lines: Sequence[str]) -> None:
    print(title)
    for line in lines:
        print(f"  {line}")


def _counts_lines(model: object) -> list[str]:
    counts = count_objects(model)  # type: ignore[arg-type]
    return [f"{name:32s} {value}" for name, value in counts.non_zero().items()]


def cmd_bootstrap(args: argparse.Namespace) -> int:
    profile = load_profile(args.target)
    workspace_id = args.workspace_id or profile.parent_workspace_id
    destination = Path(args.out)

    print(f"Capturing {workspace_id!r} from {profile.host} (org {profile.organization_id})")
    model = capture_workspace(make_sdk(profile), workspace_id)

    result = normalize_workspace(
        model,
        datasource_schema=profile.datasource_schema,
        wdf_policy=WdfPolicy(args.wdf_policy),
        strict=not args.allow_unparameterized_sql,
    )

    _print_report("\nNormalization", result.summary_lines())
    _print_report("\nObject counts", _counts_lines(result.model))

    if args.dry_run:
        print(f"\nREHEARSAL — nothing written. Re-run without --dry-run to write {destination}.")
        return 0

    written = write_tree(result.model, destination)
    print(f"\nWrote {len(written)} files to {destination}")
    return 0


def cmd_normalize(args: argparse.Namespace) -> int:
    source = Path(args.path)
    if not source.exists():
        raise GlobalmartError(f"No layout tree at {source}")

    before = {path: path.read_text(encoding="utf-8") for path in sorted(source.rglob("*.yaml"))}

    model = read_tree(source)
    result = normalize_workspace(
        model,
        datasource_schema=args.datasource_schema,
        wdf_policy=WdfPolicy(args.wdf_policy),
        strict=not args.allow_unparameterized_sql,
    )

    if args.check:
        # Normalize into a scratch tree so --check never mutates what it inspects.
        with tempfile.TemporaryDirectory(prefix="globalmart-check-") as scratch:
            candidate = Path(scratch) / "tree"
            write_tree(result.model, candidate)
            expected = {
                str(path.relative_to(candidate)): path.read_text(encoding="utf-8")
                for path in sorted(candidate.rglob("*.yaml"))
            }

        actual = {str(path.relative_to(source)): text for path, text in before.items()}

        changed = sorted(k for k in expected.keys() & actual.keys() if expected[k] != actual[k])
        added = sorted(expected.keys() - actual.keys())
        removed = sorted(actual.keys() - expected.keys())

        if changed or added or removed:
            print(f"Layout tree at {source} is NOT canonical:")
            for path in changed:
                print(f"  would change: {path}")
            for path in added:
                print(f"  would add   : {path}")
            for path in removed:
                print(f"  would remove: {path}")
            print("\nRun `globalmart normalize` to fix, then commit the result.")
            return 1

        print(f"Layout tree at {source} is canonical ({len(actual)} files).")
        return 0

    written = write_tree(result.model, source)
    _print_report("Normalization", result.summary_lines())
    print(f"\nRewrote {len(written)} files in {source}")
    return 0


def cmd_publish_parent(args: argparse.Namespace) -> int:
    profile = load_profile(args.target)
    source = Path(args.source)
    if not source.exists():
        raise GlobalmartError(
            f"No layout tree at {source}. Run `globalmart bootstrap --target <name>` first."
        )

    model = read_tree(source)
    workspace_id = args.workspace_id or profile.parent_workspace_id

    result = publish_workspace(
        make_sdk(profile),
        model,
        profile,
        workspace_id=workspace_id,
        workspace_name=args.workspace_name,
        apply=args.apply,
        standalone_copy=args.standalone_copy,
        take_backup=not args.no_backup,
    )

    if not args.apply:
        print("REHEARSAL — no writes. Re-run with --apply to publish.\n")

    _print_report("Publish", result.summary_lines())
    _print_report("\nObject counts", _counts_lines(model))

    if not args.apply and result.diff:
        print("\nWould change:")
        for line in result.diff[:20]:
            print(f"  {line}")
        if len(result.diff) > 20:
            print(f"  ... ({len(result.diff) - 20} more)")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="globalmart", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser(
        "bootstrap", help="capture the parent workspace from a live host into the repo"
    )
    bootstrap.add_argument("--target", required=True, help="profile name from config/targets.yaml")
    bootstrap.add_argument("--workspace-id", default=None, help="override the profile's workspace id")
    bootstrap.add_argument("--out", default=str(DEFAULT_LAYOUT_PATH), help="destination tree")
    bootstrap.add_argument(
        "--dry-run", action="store_true", help="capture and report, write nothing locally"
    )
    bootstrap.add_argument(
        "--wdf-policy", choices=[p.value for p in WdfPolicy], default=WdfPolicy.DROP.value
    )
    bootstrap.add_argument(
        "--allow-unparameterized-sql",
        action="store_true",
        help="report rather than fail when a SQL dataset's schema cannot be parameterised",
    )
    bootstrap.set_defaults(func=cmd_bootstrap)

    normalize = subparsers.add_parser(
        "normalize", help="re-normalize an existing tree, or check that it is canonical"
    )
    normalize.add_argument("--path", default=str(DEFAULT_LAYOUT_PATH))
    normalize.add_argument(
        "--datasource-schema",
        default="globalmart",
        help="the literal schema to parameterise, if any statement still carries one",
    )
    normalize.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if normalization would change the tree; writes nothing (the CI gate)",
    )
    normalize.add_argument(
        "--wdf-policy", choices=[p.value for p in WdfPolicy], default=WdfPolicy.DROP.value
    )
    normalize.add_argument("--allow-unparameterized-sql", action="store_true")
    normalize.set_defaults(func=cmd_normalize)

    publish = subparsers.add_parser("publish", help="publish into a live org")
    publish_targets = publish.add_subparsers(dest="what", required=True)

    parent = publish_targets.add_parser("parent", help="publish the parent workspace")
    parent.add_argument("--target", required=True, help="profile name from config/targets.yaml")
    parent.add_argument("--source", default=str(DEFAULT_LAYOUT_PATH), help="layout tree to publish")
    parent.add_argument("--workspace-id", default=None)
    parent.add_argument("--workspace-name", default=PARENT_WORKSPACE_NAME)
    parent.add_argument(
        "--apply",
        action="store_true",
        help="actually write to the org; without it this is a read-only rehearsal (ADR 002)",
    )
    parent.add_argument(
        "--no-backup",
        action="store_true",
        help="skip the pre-publish backup; requires --apply, and the replaced layout is then unrecoverable",
    )
    parent.add_argument("--standalone-copy", action="store_true")
    parent.set_defaults(func=cmd_publish_parent)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # --no-backup is meaningless in a rehearsal, and someone reaching for it deserves to be
    # told exactly what becomes unrecoverable.
    if getattr(args, "no_backup", False):
        if not getattr(args, "apply", False):
            parser.error("--no-backup requires --apply (a rehearsal writes nothing to back up)")
        print(
            f"WARNING: --no-backup — the current content of workspace "
            f"{getattr(args, 'workspace_id', None) or 'globalmart'!r} will be replaced with no "
            "recoverable copy.",
            file=sys.stderr,
        )

    try:
        exit_code: int = args.func(args)
    except GlobalmartError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
