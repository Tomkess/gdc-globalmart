"""The cold rebuild: goal-01's "no manual step" clause, executed rather than asserted.

Every other feature owns one link. This chains them, in order, in one process:

    probe the org -> verify the committed data -> load the warehouse
      -> publish the parent -> split into 12 children -> publish each child
      -> verify the result

**In-process calls, not subprocesses.** Each step calls the owning feature's public
function, so `--apply` and exceptions propagate as values rather than as exit codes, and the
whole chain is testable against `FakeSdk`. Every step still records the CLI command a human
would run to reproduce it alone, because "the script did it" is a poor answer when one step
fails.

**`--apply` is threaded through, never re-gated here.** ADR 002 puts the gate on the
operation that writes; a wrapper that made its own decision would be a second place to get it
wrong. Without `--apply` the chain is a rehearsal that prints its plan.

**The empty-org probe is what makes the claim honest.** A cold rebuild that only ever runs
against an already-populated org proves nothing about a cold start, so the org is probed
first and `started_from_empty_org` is recorded. Finding an existing parent workspace aborts
unless `--allow-existing` is passed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from globalmart.config import GlobalmartError, TargetProfile
from globalmart.domains import DomainManifest


class StepStatus(StrEnum):
    OK = "OK"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    PLANNED = "PLANNED"


class RebuildAbortedError(GlobalmartError):
    """The chain stopped: a non-empty org without --allow-existing, or a failed step."""


@dataclass
class RebuildStep:
    name: str
    cli_equivalent: str
    status: StepStatus = StepStatus.PLANNED
    duration_s: float = 0.0
    detail: str = ""
    error: str | None = None

    def line(self) -> str:
        mark = {
            StepStatus.OK: "ok     ",
            StepStatus.FAILED: "FAILED ",
            StepStatus.SKIPPED: "skipped",
            StepStatus.PLANNED: "planned",
        }[self.status]
        suffix = f"  {self.detail}" if self.detail else ""
        return f"{mark} {self.name:32s} {self.duration_s:6.1f}s{suffix}"


@dataclass
class RebuildReport:
    target: str
    applied: bool = False
    started_from_empty_org: bool = False
    allow_existing: bool = False
    steps: list[RebuildStep] = field(default_factory=list)
    passed: bool = True

    def summary_lines(self) -> list[str]:
        lines = [
            f"target            : {self.target}",
            f"applied           : {self.applied}",
            f"started from empty: {self.started_from_empty_org}",
            "",
        ]
        lines.extend(step.line() for step in self.steps)
        return lines


@dataclass
class RebuildOptions:
    layout_path: Path = Path("layouts/workspaces/globalmart")
    generated_path: Path = Path("generated/workspaces")
    domains_path: Path = Path("config/domains.yaml")
    corpus_path: Path = Path("docs/knowledge-corpus")
    skip_data: bool = False
    allow_existing: bool = False
    skip_knowledge_docs: bool = False
    verify: bool = True


def probe_empty_org(sdk: Any, profile: TargetProfile, manifest: DomainManifest) -> bool:
    """True when the org holds none of the workspaces this repo would create."""
    try:
        existing = {str(w.id) for w in sdk.catalog_workspace.list_workspaces()}
    except Exception:  # noqa: BLE001 - an unreadable list is not proof of emptiness
        return False
    ours = {manifest.parent_workspace_id} | {
        manifest.by_key(key).workspace_id
        for key in manifest.keys()  # noqa: SIM118 - DomainManifest.keys() is a method
    }
    return not (existing & ours)


def cold_rebuild(
    sdk: Any,
    profile: TargetProfile,
    manifest: DomainManifest,
    *,
    apply: bool = False,
    options: RebuildOptions | None = None,
) -> RebuildReport:
    """Run the whole chain. Rehearsal unless ``apply``."""
    opts = options or RebuildOptions()
    report = RebuildReport(
        target=profile.name, applied=apply, allow_existing=opts.allow_existing
    )

    report.started_from_empty_org = probe_empty_org(sdk, profile, manifest)
    report.steps.append(
        RebuildStep(
            name="probe-org",
            cli_equivalent=f"globalmart targets inspect --target {profile.name}",
            status=StepStatus.OK,
            detail=f"empty={report.started_from_empty_org}",
        )
    )

    if not report.started_from_empty_org and not opts.allow_existing:
        report.passed = False
        raise RebuildAbortedError(
            f"org {profile.organization_id!r} already holds workspaces this repo would "
            "create, so this would not be a cold rebuild and must not be reported as one. "
            "Pass --allow-existing to rebuild over them anyway."
        )

    steps = _plan(profile, manifest, opts)
    report.steps.extend(steps)

    if not apply:
        return report

    for step in steps:
        # A step planned as SKIPPED carries its reason already and has no runner. Skipping
        # here rather than at plan time keeps the step visible in the report: the gap is
        # named, which is the whole point of having it in the chain.
        if step.status is StepStatus.SKIPPED:
            continue

        started = time.monotonic()
        try:
            step.detail = step_runner(step.name)(sdk, profile, manifest, opts) or step.detail
            step.status = StepStatus.OK
        except Exception as error:  # noqa: BLE001 - recorded, then the chain stops
            step.status = StepStatus.FAILED
            step.error = str(error)
            step.duration_s = time.monotonic() - started
            report.passed = False
            raise RebuildAbortedError(f"step {step.name!r} failed: {error}") from error
        step.duration_s = time.monotonic() - started

    return report


def _plan(
    profile: TargetProfile, manifest: DomainManifest, opts: RebuildOptions
) -> list[RebuildStep]:
    """Every step the chain would run, in order, with the command that reproduces each."""
    steps: list[RebuildStep] = []

    if not opts.skip_data:
        steps.append(
            RebuildStep(
                name="verify-data",
                cli_equivalent="globalmart data verify",
            )
        )
        steps.append(
            RebuildStep(
                name="load-warehouse",
                cli_equivalent=f"globalmart data load --target {profile.name} --apply",
            )
        )

    steps.append(
        RebuildStep(
            name="publish-parent",
            cli_equivalent=f"globalmart publish parent --target {profile.name} --apply",
        )
    )
    # The documentation corpus is not part of the layout tree, so `publish parent` does not
    # carry it — it is written by its own API call. That makes it a real step in the chain
    # rather than a footnote: goal-01's "no manual step" bar has to be met literally, or the
    # omission has to be named. It goes straight after the parent because it writes to the
    # parent workspace and children inherit it at query time, so it does not wait on `split`.
    corpus_step = RebuildStep(
        name="publish-knowledge-docs",
        cli_equivalent=f"globalmart knowledge-docs publish --target {profile.name} --apply",
    )
    if opts.skip_knowledge_docs:
        corpus_step.status = StepStatus.SKIPPED
        corpus_step.detail = "--skip-knowledge-docs"
    elif not Path(opts.corpus_path).exists():
        corpus_step.status = StepStatus.SKIPPED
        corpus_step.detail = f"no {opts.corpus_path} — nothing to publish"
    steps.append(corpus_step)

    steps.append(
        RebuildStep(
            name="split",
            cli_equivalent="globalmart split",
        )
    )
    steps.append(
        RebuildStep(
            name="publish-domains",
            cli_equivalent=f"globalmart publish domains --target {profile.name} --apply",
        )
    )
    if opts.verify:
        steps.append(
            RebuildStep(
                name="verify",
                cli_equivalent=f"globalmart verify --target {profile.name}",
            )
        )
    return steps


def step_runner(name: str) -> Any:
    """The function that performs one step.

    A lookup rather than a chain of ifs so `_plan` and the execution loop cannot drift: a
    planned step with no runner raises here rather than being silently skipped.
    """
    runners = {
        "verify-data": _run_verify_data,
        "load-warehouse": _run_load_warehouse,
        "publish-parent": _run_publish_parent,
        "publish-knowledge-docs": _run_publish_knowledge_docs,
        "split": _run_split,
        "publish-domains": _run_publish_domains,
        "verify": _run_verify,
    }
    runner = runners.get(name)
    if runner is None:
        raise RebuildAbortedError(f"no runner for planned step {name!r}")
    return runner


def _run_verify_data(
    sdk: Any, profile: TargetProfile, manifest: DomainManifest, opts: RebuildOptions
) -> str:
    from globalmart.dataload import verify_data

    result = verify_data()
    if not result.ok():
        raise GlobalmartError("committed data does not match its manifest")
    return f"{result.tables} tables, {result.rows:,} rows"


def _run_load_warehouse(
    sdk: Any, profile: TargetProfile, manifest: DomainManifest, opts: RebuildOptions
) -> str:
    from globalmart.dataload import load_data

    report = load_data(profile, apply=True)
    return f"{report.rows_loaded():,} rows into {report.schema}"


def _run_publish_parent(
    sdk: Any, profile: TargetProfile, manifest: DomainManifest, opts: RebuildOptions
) -> str:
    from globalmart.layout_io import read_tree
    from globalmart.publish import publish_workspace

    model = read_tree(opts.layout_path)
    result = publish_workspace(
        sdk, model, profile, workspace_id=manifest.parent_workspace_id, apply=True
    )
    return f"{result.workspace_id} changed={result.changed}"


def _run_publish_knowledge_docs(
    sdk: Any, profile: TargetProfile, manifest: DomainManifest, opts: RebuildOptions
) -> str:
    """Publish the documentation corpus. A failed upsert stops the chain.

    Not softened to a warning: a rebuild that reports success while the workspace it built
    has no documentation is the kind of "done" this repo exists to stop. The only softening
    is the absent-corpus case, and that is decided in `_plan` and printed as a skip.
    """
    from globalmart.corpus import load_corpus
    from globalmart.knowledge_docs import HttpKnowledgeApi, publish_corpus

    documents = load_corpus(opts.corpus_path)
    api = HttpKnowledgeApi.for_profile(profile, manifest.parent_workspace_id)
    report = publish_corpus(
        api,
        documents,
        workspace_id=manifest.parent_workspace_id,
        target=profile.name,
        apply=True,
    )
    if report.failed:
        raise GlobalmartError(
            f"{len(report.failed)} knowledge document(s) failed to upsert: "
            + ", ".join(report.failed)
        )
    return f"{len(report.results)} documents, changed={report.changed}"


def _run_split(
    sdk: Any, profile: TargetProfile, manifest: DomainManifest, opts: RebuildOptions
) -> str:
    from globalmart.layout_io import read_tree
    from globalmart.split import split_all

    result = split_all(
        read_tree(opts.layout_path), manifest, out=opts.generated_path, write=True
    )
    return f"{len(result.domains)} children"


def _run_publish_domains(
    sdk: Any, profile: TargetProfile, manifest: DomainManifest, opts: RebuildOptions
) -> str:
    from globalmart.layout_io import read_model_json
    from globalmart.publish import publish_domains

    models = {
        key: read_model_json(opts.generated_path / f"{manifest.by_key(key).workspace_id}.json")
        for key in manifest.keys()  # noqa: SIM118 - DomainManifest.keys() is a method
    }
    results = publish_domains(sdk, manifest, profile, models=models, apply=True)
    return f"{len(results)} workspaces"


def _run_verify(
    sdk: Any, profile: TargetProfile, manifest: DomainManifest, opts: RebuildOptions
) -> str:
    from globalmart.verification import VerifyOptions, verify_target

    run = verify_target(
        sdk,
        profile,
        manifest,
        options=VerifyOptions(
            layout_path=opts.layout_path, generated_path=opts.generated_path
        ),
    )
    if not run.passed:
        raise GlobalmartError("; ".join(run.failure_reasons))
    return f"{run.total_ok}/{run.total_viz} visualizations ok"
