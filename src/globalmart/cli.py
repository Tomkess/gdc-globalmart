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
import json
import sys
import tempfile
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from globalmart.capture import capture_workspace
from globalmart.closure import MetricPolicy
from globalmart.config import GlobalmartError, load_profile
from globalmart.corpus import (
    DEFAULT_CORPUS_DIR,
    DEFAULT_MANIFEST,
    DEFAULT_QUESTIONS,
    build_report,
    load_corpus,
)
from globalmart.corpus_coverage import (
    check_corpus_coverage,
    load_corpus_manifest,
    raise_for_corpus_report,
)
from globalmart.counts import count_objects
from globalmart.coverage import check_coverage, raise_for_report
from globalmart.dataload import DEFAULT_MAX_AGE_DAYS, check_freshness, load_data, verify_contract
from globalmart.datasource import notify_upload
from globalmart.datefilters import bind_date_filters
from globalmart.domain_bootstrap import bootstrap_manifest
from globalmart.domains import dump_domains, load_domains
from globalmart.equivalence import compare_orgs
from globalmart.generate import base_row_counts, generate_dataset, resolve_window
from globalmart.knowledge import DEFAULT_SOURCE_DIR, build_knowledge
from globalmart.knowledge_docs import HttpKnowledgeApi, publish_corpus, verify_corpus
from globalmart.layout_io import read_model_json, read_tree, write_tree
from globalmart.normalize import WdfPolicy, normalize_workspace
from globalmart.publish import PARENT_WORKSPACE_NAME, publish_domains, publish_workspace
from globalmart.rebuild import RebuildOptions, cold_rebuild
from globalmart.registry import (
    DEFAULT_DDL_PATH,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_TABLES_DIR,
    build_registry,
)
from globalmart.report import write_reports
from globalmart.retrieval import (
    assert_questions_grounded,
    load_questions,
    run_retrieval,
)
from globalmart.sdk_client import make_sdk
from globalmart.split import split_all
from globalmart.sqlcheck import check_sql_datasets
from globalmart.verification import VerifyOptions, empty_warnings, verify_target

DEFAULT_LAYOUT_PATH = Path("layouts/workspaces/globalmart")
DEFAULT_DOMAINS_PATH = Path("config/domains.yaml")
DEFAULT_GENERATED_PATH = Path("generated/workspaces")


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


def cmd_domains_validate(args: argparse.Namespace) -> int:
    """Offline coverage gate. Reads the repo, contacts nothing, writes nothing."""
    layout = Path(args.layout)
    if not layout.exists():
        raise GlobalmartError(f"No layout tree at {layout}")

    model = read_tree(layout)
    manifest = load_domains(Path(args.manifest))
    report = check_coverage(model, manifest)

    if args.format == "json":
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        _print_report(f"Coverage — {args.manifest} against {layout}", report.summary_lines())
        print()
        for line in report.table_lines():
            print(f"  {line}")
        if report.multi_homed:
            _print_report(
                "\nMulti-homed (in more than one domain — reported, not an error)",
                [f"{i}: {', '.join(keys)}" for i, keys in report.multi_homed.items()],
            )
        if report.cross_domain_tiles:
            _print_report(
                "\nCross-domain tiles (copied into more than one child)",
                [f"{k}: {len(v)} tile(s)" for k, v in report.cross_domain_tiles.items()],
            )
        if report.redundant_visualizations:
            _print_report(
                "\nRedundant listings (already covered by one of the domain's dashboards)",
                [f"{k}: {', '.join(v)}" for k, v in report.redundant_visualizations.items()],
            )

    try:
        raise_for_report(report, strict=args.strict)
    except GlobalmartError as error:
        print(f"\nerror: {error}", file=sys.stderr)
        return 1

    if args.format != "json":
        print(f"\nCoverage is complete{' (strict)' if args.strict else ''}.")
    return 0


def cmd_domains_bootstrap(args: argparse.Namespace) -> int:
    """Generate the first manifest from the prefix convention. Local file write only."""
    layout = Path(args.layout)
    if not layout.exists():
        raise GlobalmartError(f"No layout tree at {layout}")

    destination = Path(args.out)
    if destination.exists() and not args.force and not args.dry_run:
        raise GlobalmartError(
            f"{destination} already exists. The prefix convention may produce this file once, "
            "never overwrite a reviewed one — pass --force if that is really what you want."
        )

    model = read_tree(layout)
    manifest, report = bootstrap_manifest(model)

    _print_report(f"Bootstrap — {layout}", report.summary_lines())

    if args.dry_run:
        print(f"\nREHEARSAL — nothing written. Re-run without --dry-run to write {destination}.")
        return 0

    dump_domains(manifest, destination)
    print(f"\nWrote {destination}")
    print("Every TODO: reason must be replaced before `domains validate --strict` passes.")
    return 0


def _load_for_split(args: argparse.Namespace) -> tuple[object, object]:
    source = Path(args.source)
    if not source.exists():
        raise GlobalmartError(f"No layout tree at {source}")
    return read_tree(source), load_domains(Path(args.domains_file))


def _split_report(result: object) -> list[str]:
    return list(result.summary_lines())  # type: ignore[attr-defined]


def cmd_split(args: argparse.Namespace) -> int:
    """Derive every domain child from the parent. Writes local files only (ADR 002)."""
    model, manifest = _load_for_split(args)
    only = set(args.only.split(",")) if args.only else None
    out = Path(args.out)

    result = split_all(
        model,
        manifest,  # type: ignore[arg-type]
        only=only,
        out=out,
        write=False,
        metric_policy=MetricPolicy(args.metric_policy),
    )

    _print_report(f"Split — {args.source} + {args.domains_file}", _split_report(result))

    if args.dry_run:
        print(f"\nREHEARSAL — nothing written. Re-run without --dry-run to write {out}.")
        return 0

    with tempfile.TemporaryDirectory(prefix="globalmart-split-") as scratch:
        staged = Path(scratch)
        split_all(
            model,
            manifest,  # type: ignore[arg-type]
            only=only,
            out=staged,
            write=True,
            metric_policy=MetricPolicy(args.metric_policy),
        )
        produced = {path.name: path.read_text(encoding="utf-8") for path in staged.glob("*.json")}

    if args.check:
        committed = {path.name: path.read_text(encoding="utf-8") for path in sorted(out.glob("*.json"))}
        changed = sorted(k for k in produced.keys() & committed.keys() if produced[k] != committed[k])
        added = sorted(produced.keys() - committed.keys())
        removed = sorted(committed.keys() - produced.keys())
        if changed or added or removed:
            print(f"\n{out} is NOT current:")
            for name in changed:
                print(f"  would change: {name}")
            for name in added:
                print(f"  would add   : {name}")
            for name in removed:
                print(f"  would remove: {name}")
            print("\nRun `globalmart split` and commit the result.")
            return 1
        print(f"\n{out} is current ({len(committed)} files).")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    for name, text in sorted(produced.items()):
        (out / name).write_text(text, encoding="utf-8")
    # A domain removed from the manifest must lose its file, or a stale child gets published.
    for stale in sorted(set(p.name for p in out.glob("*.json")) - set(produced)):
        if only is None:
            (out / stale).unlink()
    print(f"\nWrote {len(produced)} files to {out}")
    return 0


def cmd_publish_domains(args: argparse.Namespace) -> int:
    profile = load_profile(args.target)
    manifest = load_domains(Path(args.domains_file))
    source = Path(args.source)
    only = set(args.only.split(",")) if args.only else None

    models = {}
    for key in manifest.keys():  # noqa: SIM118 - DomainManifest.keys() is a method, not a mapping
        if only is not None and key not in only:
            continue
        path = source / f"{manifest.by_key(key).workspace_id}.json"
        if not path.exists():
            raise GlobalmartError(f"No generated workspace at {path}. Run `globalmart split`.")
        models[key] = read_model_json(path)

    results = publish_domains(
        make_sdk(profile),
        manifest,
        profile,
        models=models,
        only=only,
        apply=args.apply,
        take_backup=not args.no_backup,
        standalone_copy=args.standalone_copy,
        keep_going=args.keep_going,
    )

    if not args.apply:
        print("REHEARSAL — no writes. Re-run with --apply to publish.\n")

    for result in results:
        print(f"{result.workspace_id:28s} [{result.workspace_name}]  changed={result.changed}")
    print(f"\n{len(results)} workspace(s) {'published' if args.apply else 'rehearsed'}")
    return 0


def cmd_data_verify(args: argparse.Namespace) -> int:
    """Check the committed data against the manifest, and the SQL datasets against the DDL.

    Entirely offline. The data lives in the repo, so there is nothing to download and no
    credentials to hold — which is the whole point of taking custody.
    """
    model = read_tree(Path(args.layout)) if Path(args.layout).exists() else None
    registry = build_registry(Path(args.ddl), model=model)

    result = verify_contract(registry)
    _print_report("Contract", result.summary_lines())
    print(f"\nDDL               : {len(registry.tables)} tables in {args.ddl}")

    if model is not None:
        report = check_sql_datasets(model, registry, schema=args.schema)
        _print_report("\nSQL datasets", report.summary_lines())
        if not report.ok():
            print("\nerror: SQL-backed datasets reference tables that do not exist", file=sys.stderr)
            return 1

    if not result.ok():
        print("\nerror: the committed contract disagrees with the DDL", file=sys.stderr)
        return 1

    print("\nThe contract agrees with the DDL and every SQL dataset resolves.")
    return 0


def cmd_data_generate(args: argparse.Namespace) -> int:
    """Produce a synthetic dataset in FEAT-005's format. Local files only, so no --apply."""
    model = read_tree(Path(args.layout)) if Path(args.layout).exists() else None
    registry = build_registry(Path(args.ddl), model=model)

    counts = base_row_counts(Path(args.manifest))
    window = resolve_window(
        date.fromisoformat(args.start_date) if args.start_date else None,
        date.fromisoformat(args.end_date) if args.end_date else None,
    )

    report = generate_dataset(
        registry,
        out_dir=Path(args.out),
        seed=args.seed,
        scale=args.scale,
        base_counts=counts,
        window=window,
    )

    _print_report("Generate", report.summary_lines())
    print(
        f"\nLoad it with: globalmart data load --target <profile> "
        f"--tables-dir {Path(args.out) / 'tables'} "
        f"--manifest {Path(args.out) / 'table-manifest.json'} --apply"
    )
    return 0


def cmd_data_load(args: argparse.Namespace) -> int:
    """Load the committed rows into a warehouse. Writes to a live warehouse, so --apply."""
    profile = load_profile(args.target)
    model = read_tree(Path(args.layout)) if Path(args.layout).exists() else None
    only = set(args.only.split(",")) if args.only else None

    report = load_data(
        profile,
        apply=args.apply,
        only=only,
        ddl_path=Path(args.ddl),
        tables_dir=Path(args.tables_dir),
        manifest_path=Path(args.manifest),
        model=model,
        recreate_drifted=args.recreate_drifted,
    )

    if not args.apply:
        print("REHEARSAL — no writes. Re-run with --apply to load.\n")

    _print_report("Load", report.summary_lines())

    if args.apply:
        changed = [e for e in report.tables if e.rows_before != e.rows_after]
        print(f"\n{len(changed)} table(s) changed row count")

        # The load is not finished until GoodData knows about it. Cached results survive a
        # warehouse change, so without this the new rows are invisible in every dashboard.
        notify_upload(make_sdk(profile), profile)
        print("Upload notification sent — cached results invalidated.")
    return 0


def cmd_datefilters_bind(args: argparse.Namespace) -> int:
    """Bind every dashboard date filter to the date dataset its own content uses.

    Offline: reads and rewrites the committed layout, never a live host. `--check` is the CI
    gate — a dashboard added without a bound filter fails the pull request that added it,
    instead of being discovered two years later by someone moving a slider.
    """
    source = Path(args.layout)
    model = read_tree(source)
    report = bind_date_filters(model, overrides=_date_overrides(args.overrides))

    _print_report("Date filters", report.summary_lines())

    if not report.ok():
        print(
            "\nerror: some dashboards do not resolve to exactly one date dataset. "
            "Add an override rather than guessing — a filter bound to the wrong date is "
            "worse than one that is obviously unbound.",
            file=sys.stderr,
        )
        return 1

    if args.check:
        if report.bound:
            print(
                f"\nerror: {len(report.bound)} dashboard(s) would change. "
                "Run `globalmart datefilters bind` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print("\nEvery dashboard date filter is already bound.")
        return 0

    if report.bound:
        write_tree(model, source)
        print(f"\n{len(report.bound)} filter context(s) updated in {source}")
    else:
        print("\nNothing to do.")
    return 0


def _date_overrides(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    pairs = {}
    for chunk in raw.split(","):
        dashboard, _, dataset = chunk.partition("=")
        if not dashboard.strip() or not dataset.strip():
            raise GlobalmartError(f"bad --overrides entry {chunk!r}; expected dashboard=dataset")
        pairs[dashboard.strip()] = dataset.strip()
    return pairs


def cmd_data_ensure(args: argparse.Namespace) -> int:
    """Make sure the warehouse holds current data, generating and loading only if it does not.

    What the scheduled workflow runs. ADR 008 moved the rows out of the repository, so
    something has to keep the warehouse populated — and it has to be safe to run repeatedly,
    which means asking before acting. A run that finds current data does nothing and says so.
    """
    import tempfile
    from datetime import date

    profile = load_profile(args.target)
    model = read_tree(Path(args.layout)) if Path(args.layout).exists() else None
    registry = build_registry(Path(args.ddl), model=model)

    freshness = check_freshness(
        profile,
        registry=registry,
        manifest_path=Path(args.manifest),
        max_age_days=args.max_age_days,
    )
    _print_report("Freshness", freshness.summary_lines())

    if not freshness.stale() and not args.force:
        print("\nNothing to do — the warehouse holds current data.")
        return 0

    reason = "forced" if args.force and not freshness.stale() else "stale or empty"
    print(f"\nRegenerating ({reason}).")

    if not args.apply:
        print("REHEARSAL — no writes. Re-run with --apply to generate and load.")
        return 0

    with tempfile.TemporaryDirectory(prefix="globalmart-ensure-") as tmp:
        out = Path(tmp)
        window = resolve_window(
            date.fromisoformat(args.start_date) if args.start_date else None,
            date.fromisoformat(args.end_date) if args.end_date else None,
        )
        generated = generate_dataset(
            registry,
            out_dir=out,
            seed=args.seed,
            scale=args.scale,
            base_counts=base_row_counts(Path(args.manifest)),
            window=window,
        )
        _print_report("\nGenerate", generated.summary_lines())
        print(f"window            : {window[0]} .. {window[1]}")

        report = load_data(
            profile,
            apply=True,
            ddl_path=Path(args.ddl),
            tables_dir=out / "tables",
            manifest_path=out / "table-manifest.json",
            model=model,
            registry=registry,
            recreate_drifted=args.recreate_drifted,
        )
        _print_report("\nLoad", report.summary_lines())

    print("\nWarehouse is current.")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Read-only, so no --apply and no --dry-run. --list-only names objects without running."""
    profile = load_profile(args.target)
    manifest = load_domains(Path(args.domains_file))

    run = verify_target(
        make_sdk(profile),
        profile,
        manifest,
        options=VerifyOptions(
            max_workers=args.max_workers,
            viz_timeout=args.viz_timeout,
            max_retries=args.max_retries,
            fail_on_empty=args.fail_on_empty,
            list_only=args.list_only,
            layout_path=Path(args.layout),
            generated_path=Path(args.generated),
            workspaces=tuple(args.workspace or ()),
        ),
    )

    _print_report("Verification", run.summary_lines())

    for warning in empty_warnings(run):
        print(f"\nwarning: {warning}", file=sys.stderr)

    json_path, markdown_path = write_reports(run, Path(args.output_dir))
    print(f"\nreports: {json_path}  {markdown_path}")

    if not run.passed:
        print("\nerror: verification failed", file=sys.stderr)
        for reason in run.failure_reasons:
            print(f"  - {reason}", file=sys.stderr)
        return 1

    print("\nEverything the repo claims about this target holds.")
    return 0


def cmd_verify_equivalence(args: argparse.Namespace) -> int:
    profile_a = load_profile(args.target_a)
    profile_b = load_profile(args.target_b)

    report = compare_orgs(
        make_sdk(profile_a),
        profile_a,
        make_sdk(profile_b),
        profile_b,
        args.workspace_id,
    )

    _print_report("Equivalence", report.summary_lines())

    if not report.equivalent:
        print("\nerror: the two orgs differ outside the parameterized values", file=sys.stderr)
        return 1

    print("\nIdentical except for the parameterized values.")
    return 0


def cmd_rebuild(args: argparse.Namespace) -> int:
    """Chains every other command. --apply is threaded into each step, never re-gated here."""
    profile = load_profile(args.target)
    manifest = load_domains(Path(args.domains_file))

    report = cold_rebuild(
        make_sdk(profile),
        profile,
        manifest,
        apply=args.apply,
        options=RebuildOptions(
            layout_path=Path(args.layout),
            generated_path=Path(args.generated),
            domains_path=Path(args.domains_file),
            corpus_path=Path(args.corpus),
            skip_data=args.skip_data,
            allow_existing=args.allow_existing,
            skip_knowledge_docs=args.skip_knowledge_docs,
        ),
    )

    if not args.apply:
        print("REHEARSAL — no writes. Re-run with --apply to rebuild.\n")

    _print_report("Rebuild", report.summary_lines())

    if not args.apply:
        print("\nReproduce any single step by hand:")
        for step in report.steps:
            print(f"  {step.name:24s} {step.cli_equivalent}")

    return 0 if report.passed else 1


def cmd_knowledge_build(args: argparse.Namespace) -> int:
    """Compile docs/knowledge/*.md into memory items in the layout tree.

    Writes local files only, so per ADR 002 it takes --check (the CI-gate form) and never
    --apply. Run it *after* `bootstrap`: both write the tree, and a capture reflects the
    org, so a build before a capture is a build the capture discards.
    """
    report = build_knowledge(
        source_dir=Path(args.source),
        layout_path=Path(args.layout),
        check=args.check,
    )

    _print_report(f"Knowledge — {args.source}", report.summary_lines())

    if args.check:
        if report.changed:
            print(
                f"\n{args.layout} does not match {args.source}. "
                "Run `globalmart knowledge build` and commit the result.",
                file=sys.stderr,
            )
            return 1
        print("\nThe tree is current with the authored documents.")
        return 0

    print(f"\nWrote {report.items} memory item(s) into {args.layout}")
    return 0


def cmd_knowledge_docs_build(args: argparse.Namespace) -> int:
    """Validate the authored corpus and the question set's grounding in it.

    Produces no artifact, so it has neither --apply nor --check: the build *is* the check.
    There is nothing on disk that could be stale relative to the documents, because the
    documents are the source and the API is the only sink.
    """
    documents = load_corpus(Path(args.corpus))
    report = build_report(documents)
    _print_report(f"Corpus — {args.corpus}", report.summary_lines())

    questions = load_questions(Path(args.questions))
    if questions:
        assert_questions_grounded(questions, documents)
        print(f"\n{len(questions)} retrieval question(s) still grounded in the corpus.")
    else:
        print(f"\nNo question set at {args.questions} — retrieval is unasserted.")

    print(f"{report.documents} document(s) valid.")
    return 0


def cmd_knowledge_docs_coverage(args: argparse.Namespace) -> int:
    """Is every object in the parent documented, or excluded with a reason?

    Reads the committed layout tree, never a live org: the repo is the source of truth, so
    this needs no --target and no network.
    """
    model = read_tree(Path(args.layout))
    documents = load_corpus(Path(args.corpus))
    manifest = load_corpus_manifest(Path(args.manifest))

    report = check_corpus_coverage(model, documents, manifest)

    if args.format == "json":
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        _print_report("Corpus coverage", report.summary_lines())
        print()
        for line in report.table_lines():
            print(f"  {line}")

    if args.report_only:
        if not report.is_clean(strict=args.strict):
            print(
                f"\nREPORT ONLY — {report.uncovered_total()} object(s) undocumented. "
                "Drop --report-only to make this fatal.",
                file=sys.stderr,
            )
        return 0

    raise_for_corpus_report(report, strict=args.strict)
    print("\nEvery object is documented or explicitly excluded.")
    return 0


def _corpus_workspaces(args: argparse.Namespace, profile: object) -> list[str]:
    """Which workspaces to write to: the parent **and every domain workspace**.

    The API inherits knowledge documents down the workspace *hierarchy*, and GlobalMart has
    no hierarchy — probed against demo-cloud on 2026-09-21, all 13 workspaces report
    `parent=None`. "Parent" and "child" here name a derivation relationship in this
    repository, not a GoodData one: the splitter emits twelve independent workspaces (ADR
    001), which is what makes them publishable into any org on their own.

    So a parent-only publish leaves all twelve domain workspaces undocumented, and those are
    exactly where an assistant or an A2A lane is asked its questions. Writing to each is the
    only thing that works; `--parent-only` restricts it for the case where someone wants the
    parent alone.
    """
    parent = args.workspace_id or getattr(profile, "parent_workspace_id", "globalmart")
    if getattr(args, "parent_only", False):
        return [parent]
    manifest = load_domains(Path(args.domains_file))
    return [parent] + [
        manifest.by_key(key).workspace_id
        for key in manifest.keys()  # noqa: SIM118 - DomainManifest.keys() is a method
    ]


def cmd_knowledge_docs_publish(args: argparse.Namespace) -> int:
    """Upsert the corpus into AI Knowledge. Rehearsal unless --apply (ADR 002)."""
    profile = load_profile(args.target)
    documents = load_corpus(Path(args.corpus))

    failed = False
    for workspace_id in _corpus_workspaces(args, profile):
        api = HttpKnowledgeApi.for_profile(profile, workspace_id)
        report = publish_corpus(
            api,
            documents,
            workspace_id=workspace_id,
            target=profile.name,
            apply=args.apply,
        )
        if not args.apply:
            print("REHEARSAL — no writes. Re-run with --apply to publish.\n")
        _print_report(f"Knowledge documents — {workspace_id}", report.summary_lines())
        if report.failed:
            failed = True
            print(f"\n{len(report.failed)} document(s) failed to upsert.", file=sys.stderr)

    return 1 if failed else 0


def cmd_knowledge_docs_verify(args: argparse.Namespace) -> int:
    """Reconcile the repo against the org, and optionally prune our orphans.

    Checks every workspace the publish writes to, because a corpus that is current in the
    parent and stale in the twelve domain workspaces is exactly the drift this feature is
    supposed to catch.
    """
    profile = load_profile(args.target)
    documents = load_corpus(Path(args.corpus))

    if args.prune and not args.apply:
        print("REHEARSAL — nothing deleted. Re-run with --prune --apply to remove orphans.\n")

    stale: list[str] = []
    for workspace_id in _corpus_workspaces(args, profile):
        api = HttpKnowledgeApi.for_profile(profile, workspace_id)
        report = verify_corpus(
            api,
            documents,
            workspace_id=workspace_id,
            target=profile.name,
            prune=args.prune,
            apply=args.apply,
        )
        _print_report(f"Knowledge documents — {workspace_id}", report.summary_lines())
        if report.missing_in_org or report.orphaned_in_org or report.changed:
            stale.append(workspace_id)

    if stale:
        print(
            f"\n{len(stale)} workspace(s) do not match the repo: {', '.join(stale)}. Run "
            f"`globalmart knowledge-docs publish --target {profile.name} --apply`.",
            file=sys.stderr,
        )
        return 1
    print("\nThe published corpus matches the repo.")
    return 0


def cmd_knowledge_docs_retrieval(args: argparse.Namespace) -> int:
    """Ask the live knowledge search the questions only the corpus answers.

    Reads only: this asserts on retrieved chunks, not on generated prose, so there is no
    model in the loop and nothing to gate behind --apply.
    """
    profile = load_profile(args.target)
    documents = load_corpus(Path(args.corpus))
    questions = load_questions(Path(args.questions))

    if not questions:
        print(f"No question set at {args.questions} — nothing to assert.", file=sys.stderr)
        return 1

    assert_questions_grounded(questions, documents)

    workspace_id = args.workspace_id or profile.parent_workspace_id
    api = HttpKnowledgeApi.for_profile(profile, workspace_id)
    report = run_retrieval(
        api,
        questions,
        workspace_id=workspace_id,
        target=profile.name,
        limit=args.limit,
        min_score=args.min_score,
    )

    _print_report("Retrieval", report.summary_lines())
    if not report.passed:
        print(f"\n{len(report.failures)} question(s) failed.", file=sys.stderr)
        return 1
    print("\nEvery question retrieves its document and its facts.")
    return 0


def cmd_targets_inspect(args: argparse.Namespace) -> int:
    """Discover what a host reports, so a new profile can be filled in from fact.

    Adding an org means knowing its organization id and its datasources — neither is
    guessable, and guessing them is how `organization_id: petertomko` (inferred from a
    hostname, actually `gm-ddebmti`) got into config during development.
    """
    profile = load_profile(args.target)
    sdk = make_sdk(profile)

    organization = sdk.catalog_organization.get_organization()
    actual_org = getattr(organization, "id", None)

    print(f"host                : {profile.host}")
    print(f"organization_id     : {actual_org}")
    if actual_org != profile.organization_id:
        print(f"  MISMATCH — config/targets.yaml says {profile.organization_id!r}")

    print("\ndatasources:")
    for data_source in sdk.catalog_data_source.list_data_sources():
        print(f"  id              : {data_source.id}")
        print(f"    type          : {getattr(data_source, 'type', None)}")
        print(f"    schema        : {getattr(data_source, 'schema', None)}")
        print(f"    url           : {getattr(data_source, 'url', None)}")

    print("\nworkspaces:")
    for workspace in sdk.catalog_workspace.list_workspaces():
        print(f"  {workspace.id}  [{workspace.name}]")

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
    bootstrap.add_argument("--dry-run", action="store_true", help="capture and report, write nothing locally")
    bootstrap.add_argument("--wdf-policy", choices=[p.value for p in WdfPolicy], default=WdfPolicy.DROP.value)
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
    normalize.add_argument("--wdf-policy", choices=[p.value for p in WdfPolicy], default=WdfPolicy.DROP.value)
    normalize.add_argument("--allow-unparameterized-sql", action="store_true")
    normalize.set_defaults(func=cmd_normalize)

    domains = subparsers.add_parser("domains", help="the domain membership manifest")
    domains_actions = domains.add_subparsers(dest="action", required=True)

    validate = domains_actions.add_parser(
        "validate", help="check the manifest accounts for everything in the parent"
    )
    validate.add_argument("--manifest", default=str(DEFAULT_DOMAINS_PATH))
    validate.add_argument("--layout", default=str(DEFAULT_LAYOUT_PATH))
    validate.add_argument(
        "--strict",
        action="store_true",
        help="also fail on placeholder exclusion reasons (the CI gate)",
    )
    validate.add_argument("--format", choices=["table", "json"], default="table")
    validate.set_defaults(func=cmd_domains_validate)

    domains_bootstrap = domains_actions.add_parser(
        "bootstrap", help="generate the first manifest from the viz_<domain>_ prefix convention"
    )
    domains_bootstrap.add_argument("--layout", default=str(DEFAULT_LAYOUT_PATH))
    domains_bootstrap.add_argument("--out", default=str(DEFAULT_DOMAINS_PATH))
    domains_bootstrap.add_argument("--dry-run", action="store_true", help="report only; write no file")
    domains_bootstrap.add_argument("--force", action="store_true", help="overwrite an existing manifest")
    domains_bootstrap.set_defaults(func=cmd_domains_bootstrap)

    split = subparsers.add_parser("split", help="derive every domain workspace from the parent")
    split.add_argument("--domains-file", default=str(DEFAULT_DOMAINS_PATH))
    split.add_argument("--source", "--from", dest="source", default=str(DEFAULT_LAYOUT_PATH))
    split.add_argument("--out", default=str(DEFAULT_GENERATED_PATH))
    split.add_argument("--only", default=None, help="comma-separated domain keys")
    split.add_argument(
        "--metric-policy",
        choices=[policy.value for policy in MetricPolicy],
        default=MetricPolicy.DATASET_FIT.value,
        help=(
            "dataset-fit keeps every metric whose tables are already in the child "
            "(adds no datasets); reachable keeps only metrics a retained visualization uses"
        ),
    )
    split.add_argument("--dry-run", action="store_true", help="report only; write no file")
    split.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the committed children differ from what would be generated (the CI gate)",
    )
    split.set_defaults(func=cmd_split)

    data = subparsers.add_parser("data", help="the committed row data")
    data_actions = data.add_subparsers(dest="action", required=True)

    data_verify = data_actions.add_parser(
        "verify", help="check the committed data and that every SQL dataset resolves"
    )
    data_verify.add_argument("--ddl", default=str(DEFAULT_DDL_PATH))
    data_verify.add_argument("--layout", default=str(DEFAULT_LAYOUT_PATH))
    data_verify.add_argument(
        "--schema", default="globalmart", help="the schema SQL statements are checked against"
    )
    data_verify.set_defaults(func=cmd_data_verify)

    data_load = data_actions.add_parser("load", help="truncate-then-load the committed rows into a warehouse")
    data_load.add_argument("--target", required=True)
    data_load.add_argument("--ddl", default=str(DEFAULT_DDL_PATH))
    data_load.add_argument("--layout", default=str(DEFAULT_LAYOUT_PATH))
    data_load.add_argument("--only", default=None, help="comma-separated table names")
    data_load.add_argument(
        "--tables-dir",
        default=str(DEFAULT_TABLES_DIR),
        help="where the gzipped CSVs live; point at a generated set to load that instead",
    )
    data_load.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    data_load.add_argument(
        "--recreate-drifted",
        action="store_true",
        help="drop and rebuild tables whose columns the DDL has outgrown (requires --apply)",
    )
    data_load.add_argument(
        "--apply",
        action="store_true",
        help="actually truncate and load; without it this is a read-only rehearsal (ADR 002/004)",
    )
    data_load.set_defaults(func=cmd_data_load)

    verify = subparsers.add_parser("verify", help="execute every visualization and check the repo's claims")
    verify_actions = verify.add_subparsers(dest="action", required=False)

    verify.add_argument("--target", required=False)
    verify.add_argument("--domains-file", default=str(DEFAULT_DOMAINS_PATH))
    verify.add_argument("--layout", default=str(DEFAULT_LAYOUT_PATH))
    verify.add_argument("--generated", default=str(DEFAULT_GENERATED_PATH))
    verify.add_argument("--workspace", action="append", help="verify only these workspace ids")
    verify.add_argument("--max-workers", type=int, default=8)
    verify.add_argument("--viz-timeout", type=int, default=180)
    verify.add_argument("--max-retries", type=int, default=2)
    verify.add_argument(
        "--fail-on-empty",
        action="store_true",
        help="treat a zero-row result as a failure (off by default: empty slices exist)",
    )
    verify.add_argument("--list-only", action="store_true", help="name what would run, execute nothing")
    verify.add_argument("--output-dir", default="reports")
    verify.set_defaults(func=cmd_verify)

    equivalence = verify_actions.add_parser(
        "equivalence", help="compare two orgs outside the parameterized values"
    )
    equivalence.add_argument("--target-a", required=True)
    equivalence.add_argument("--target-b", required=True)
    equivalence.add_argument("--workspace-id", default="globalmart")
    equivalence.set_defaults(func=cmd_verify_equivalence)

    rebuild = subparsers.add_parser("rebuild", help="the whole chain: data, parent, children, verification")
    rebuild.add_argument("--target", required=True)
    rebuild.add_argument("--domains-file", default=str(DEFAULT_DOMAINS_PATH))
    rebuild.add_argument("--layout", default=str(DEFAULT_LAYOUT_PATH))
    rebuild.add_argument("--generated", default=str(DEFAULT_GENERATED_PATH))
    rebuild.add_argument("--skip-data", action="store_true")
    rebuild.add_argument("--corpus", default=str(DEFAULT_CORPUS_DIR))
    rebuild.add_argument(
        "--skip-knowledge-docs",
        action="store_true",
        help="leave the documentation corpus unpublished; the report names the skip either way",
    )
    rebuild.add_argument(
        "--allow-existing",
        action="store_true",
        help="rebuild over an org that already holds these workspaces (it is then not cold)",
    )
    rebuild.add_argument(
        "--apply",
        action="store_true",
        help="actually write; without it this prints the step plan (ADR 002)",
    )
    rebuild.set_defaults(func=cmd_rebuild)

    knowledge = subparsers.add_parser("knowledge", help="compile authored Markdown into AI memory items")
    knowledge_actions = knowledge.add_subparsers(dest="action", required=True)

    knowledge_build = knowledge_actions.add_parser(
        "build", help="compile docs/knowledge/*.md into the layout tree"
    )
    knowledge_build.add_argument("--source", default=str(DEFAULT_SOURCE_DIR))
    knowledge_build.add_argument("--layout", default=str(DEFAULT_LAYOUT_PATH))
    knowledge_build.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the tree would change; writes nothing (the CI gate)",
    )
    knowledge_build.set_defaults(func=cmd_knowledge_build)

    knowledge_docs = subparsers.add_parser(
        "knowledge-docs",
        help="the authored documentation corpus: validate, publish to AI Knowledge, reconcile",
    )
    kd_actions = knowledge_docs.add_subparsers(dest="action", required=True)

    kd_build = kd_actions.add_parser(
        "build", help="validate the corpus and the question set's grounding in it"
    )
    kd_build.add_argument("--corpus", default=str(DEFAULT_CORPUS_DIR))
    kd_build.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    kd_build.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    kd_build.set_defaults(func=cmd_knowledge_docs_build)

    kd_coverage = kd_actions.add_parser(
        "coverage", help="every object documented or excluded with a reason (the CI gate)"
    )
    kd_coverage.add_argument("--corpus", default=str(DEFAULT_CORPUS_DIR))
    kd_coverage.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    kd_coverage.add_argument("--layout", default=str(DEFAULT_LAYOUT_PATH))
    kd_coverage.add_argument(
        "--strict",
        action="store_true",
        help="also fail on a placeholder exclusion reason ('TODO', 'n/a')",
    )
    kd_coverage.add_argument(
        "--report-only",
        action="store_true",
        help="print the gap and exit 0 — for sizing the authoring job before the gate is live",
    )
    kd_coverage.add_argument("--format", choices=["text", "json"], default="text")
    kd_coverage.set_defaults(func=cmd_knowledge_docs_coverage)

    kd_publish = kd_actions.add_parser("publish", help="upsert the corpus into AI Knowledge")
    kd_publish.add_argument("--target", required=True)
    kd_publish.add_argument("--corpus", default=str(DEFAULT_CORPUS_DIR))
    kd_publish.add_argument("--workspace-id", default=None)
    kd_publish.add_argument("--domains-file", default=str(DEFAULT_DOMAINS_PATH))
    kd_publish.add_argument(
        "--parent-only",
        action="store_true",
        help="write only to the parent; the domain workspaces then carry no documentation",
    )
    kd_publish.add_argument(
        "--apply",
        action="store_true",
        help="actually write to the org; without it this is a read-only rehearsal (ADR 002)",
    )
    kd_publish.set_defaults(func=cmd_knowledge_docs_publish)

    kd_verify = kd_actions.add_parser(
        "verify", help="reconcile the repo against the org; never touches a foreign document"
    )
    kd_verify.add_argument("--target", required=True)
    kd_verify.add_argument("--corpus", default=str(DEFAULT_CORPUS_DIR))
    kd_verify.add_argument("--workspace-id", default=None)
    kd_verify.add_argument("--domains-file", default=str(DEFAULT_DOMAINS_PATH))
    kd_verify.add_argument(
        "--parent-only", action="store_true", help="check only the parent workspace"
    )
    kd_verify.add_argument(
        "--prune", action="store_true", help="delete our orphaned documents (requires --apply)"
    )
    kd_verify.add_argument(
        "--apply", action="store_true", help="actually delete; without it --prune only reports"
    )
    kd_verify.set_defaults(func=cmd_knowledge_docs_verify)

    kd_retrieval = kd_actions.add_parser(
        "retrieval", help="ask the live knowledge search the questions only the corpus answers"
    )
    kd_retrieval.add_argument("--target", required=True)
    kd_retrieval.add_argument("--corpus", default=str(DEFAULT_CORPUS_DIR))
    kd_retrieval.add_argument("--questions", default=str(DEFAULT_QUESTIONS))
    kd_retrieval.add_argument("--workspace-id", default=None)
    kd_retrieval.add_argument("--limit", type=int, default=10)
    kd_retrieval.add_argument("--min-score", type=float, default=0.0)
    kd_retrieval.set_defaults(func=cmd_knowledge_docs_retrieval)

    data_generate = data_actions.add_parser(
        "generate", help="produce a synthetic dataset at a chosen seed and scale"
    )
    data_generate.add_argument("--out", required=True, help="destination directory (never data/)")
    data_generate.add_argument("--seed", type=int, default=20260920)
    data_generate.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="facts scale linearly, dimensions by sqrt; 1.0 reproduces the real row counts",
    )
    data_generate.add_argument("--ddl", default=str(DEFAULT_DDL_PATH))
    data_generate.add_argument("--layout", default=str(DEFAULT_LAYOUT_PATH))
    data_generate.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    data_generate.add_argument(
        "--start-date",
        help="first date in the generated window (default: --end-date minus two years)",
    )
    data_generate.add_argument(
        "--end-date",
        help="last date in the generated window (default: today, which is the point)",
    )
    data_generate.set_defaults(func=cmd_data_generate)

    data_ensure = data_actions.add_parser(
        "ensure",
        help="generate and load only if the warehouse is empty or stale (what CI runs)",
    )
    data_ensure.add_argument("--target", required=True, help="target profile to check and load")
    data_ensure.add_argument("--apply", action="store_true", help="required to generate and load")
    data_ensure.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help="how stale the loaded data may be before it is regenerated",
    )
    data_ensure.add_argument(
        "--force", action="store_true", help="regenerate even when the data is current"
    )
    data_ensure.add_argument(
        "--recreate-drifted",
        action="store_true",
        help="drop and rebuild tables whose columns the DDL has outgrown (requires --apply)",
    )
    data_ensure.add_argument("--seed", type=int, default=20260920)
    data_ensure.add_argument("--scale", type=float, default=1.0)
    data_ensure.add_argument("--start-date")
    data_ensure.add_argument("--end-date")
    data_ensure.add_argument("--ddl", default=str(DEFAULT_DDL_PATH))
    data_ensure.add_argument("--layout", default=str(DEFAULT_LAYOUT_PATH))
    data_ensure.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH))
    data_ensure.set_defaults(func=cmd_data_ensure)

    datefilters = subparsers.add_parser(
        "datefilters", help="bind dashboard date filters to the date dataset they depend on"
    )
    datefilters_actions = datefilters.add_subparsers(dest="action", required=True)
    df_bind = datefilters_actions.add_parser("bind", help="write dataSet into every date filter")
    df_bind.add_argument("--layout", default=str(DEFAULT_LAYOUT_PATH))
    df_bind.add_argument(
        "--check", action="store_true", help="exit 1 if anything would change (the CI gate)"
    )
    df_bind.add_argument(
        "--overrides",
        help="dashboard=dataset pairs for dashboards that resolve to more than one date",
    )
    df_bind.set_defaults(func=cmd_datefilters_bind)

    targets = subparsers.add_parser("targets", help="inspect configured targets")
    targets_actions = targets.add_subparsers(dest="action", required=True)
    inspect = targets_actions.add_parser(
        "inspect", help="report what a host actually says — org id, datasources, workspaces"
    )
    inspect.add_argument("--target", required=True)
    inspect.set_defaults(func=cmd_targets_inspect)

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

    domains_publish = publish_targets.add_parser("domains", help="publish the derived domain workspaces")
    domains_publish.add_argument("--target", required=True)
    domains_publish.add_argument("--domains-file", default=str(DEFAULT_DOMAINS_PATH))
    domains_publish.add_argument("--source", "--in", dest="source", default=str(DEFAULT_GENERATED_PATH))
    domains_publish.add_argument("--only", default=None, help="comma-separated domain keys")
    domains_publish.add_argument(
        "--apply",
        action="store_true",
        help="actually write to the org; without it this is a read-only rehearsal (ADR 002)",
    )
    domains_publish.add_argument("--no-backup", action="store_true")
    domains_publish.add_argument("--standalone-copy", action="store_true")
    domains_publish.add_argument(
        "--keep-going",
        action="store_true",
        help="continue past a failing domain; the exit code is still non-zero",
    )
    domains_publish.set_defaults(func=cmd_publish_domains)

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
