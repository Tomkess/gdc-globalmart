"""What gdcloud's ``config.yml`` says about GlobalMart's release, for this package's own commands.

gdcloud owns the release (FEAT-019, ADR 011): versions, promotion, the generated CI. The steps it
has no concept of — projecting the parent into ``gd_data_product/``, publishing the knowledge
corpus after a deploy — still need to know which workspace each environment deploys to and which
data source the projection resolves to. This is the only module in the package that reads
``config.yml``, and it reads the YAML directly rather than through gdcloud's config loader. The
one place the package imports ``gdcloud`` is ``gdcloud_project``, for byte parity with its YAML
normalizers.

GlobalMart releases exactly one data product, the parent. The 12 domain workspaces are local
artifacts redeployed on demand with ``publish domains``, so a second catalog entry is a defect
here, not a feature.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from globalmart.config import GlobalmartError

DEFAULT_RELEASE_CONFIG_PATH = Path("config.yml")
DEFAULT_ENV_CONFIG_PATH = Path("gd_data_product/config.env.yml")

#: gdcloud's environment name -> the suffix its master workspace id carries. prod is
#: ``_master`` (MIC's convention), so a suffix is not simply the environment name.
MASTER_SUFFIXES = {"dev": "dev", "test": "test", "preprod": "preprod", "prod": "master"}

#: ``deploy-{env}-{dp}-{version}-{YYYYmmdd-HHMMSS}``, as gdcloud's version_manager writes it.
#: The timestamp carries a hyphen of its own, so the tag is matched whole, never split on "-".
_DEPLOY_TAG = re.compile(
    r"^deploy-(?P<env>dev|test|preprod|prod)-(?P<dp>[a-z0-9_]+)-"
    r"(?P<version>v\d+\.\d+(?:\.\d+)?)-(?P<stamp>\d{8}-\d{6})$"
)
_TAG_STAMP_FORMAT = "%Y%m%d-%H%M%S"


class ReleaseConfigError(GlobalmartError):
    """``config.yml`` does not describe the one-data-product release this repo expects."""


@dataclass(frozen=True)
class ReleaseConfig:
    path: Path
    dp_id: str  # "globalmart", the primary and only data product
    label: str  # "GM"
    datasource_id: str  # canonical id the projection resolves to
    datasource_schema: str  # canonical warehouse schema
    masters: dict[str, str]  # environment -> master workspace id
    hosts: dict[str, str]  # environment -> host
    github_environments: dict[str, str]  # environment -> GitHub Environment name


@dataclass(frozen=True)
class ReleaseScope:
    """One deploy, read back from the tag gdcloud wrote for it."""

    environment: str  # "dev" | "test" | "preprod" | "prod"
    version: str  # "v1.N" or hotfix "v1.N.M"
    workspace_id: str  # that environment's master
    deployed_at: datetime  # UTC, from the tag


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ReleaseConfigError(f"Release config not found: {path}")
    document = yaml.safe_load(path.read_text()) or {}
    if not isinstance(document, dict):
        raise ReleaseConfigError(f"{path} is not a mapping")
    return document


def load_release_config(
    path: Path = DEFAULT_RELEASE_CONFIG_PATH, env_config_path: Path | None = None
) -> ReleaseConfig:
    """Read the release, and fail loudly on anything but one data product in every environment."""
    document = _load_yaml(path)

    catalog = document.get("data_products") or {}
    if len(catalog) != 1:
        raise ReleaseConfigError(
            f"{path}: expected exactly one data product, found {sorted(catalog) or 'none'}. "
            "The domain workspaces are local artifacts, never gdcloud data products (ADR 011)."
        )
    dp_id = next(iter(catalog))
    primary = document.get("primary_data_product")
    if primary != dp_id:
        raise ReleaseConfigError(f"{path}: primary_data_product is {primary!r}, catalog has {dp_id!r}")
    label = str((catalog[dp_id] or {}).get("label") or "")
    if not label:
        raise ReleaseConfigError(f"{path}: data product {dp_id!r} has no label")

    environments = document.get("environments") or {}
    unknown = sorted(set(environments) - set(MASTER_SUFFIXES))
    if unknown:
        raise ReleaseConfigError(f"{path}: unknown environment(s) {unknown}")

    masters: dict[str, str] = {}
    hosts: dict[str, str] = {}
    github_environments: dict[str, str] = {}
    for env, block in environments.items():
        block = block or {}
        deployment = (block.get("data_products") or {}).get(dp_id)
        if not deployment:
            raise ReleaseConfigError(f"{path}: environment {env!r} does not deploy {dp_id!r}")
        master = str(deployment.get("master_workspace_id") or "")
        expected = f"{dp_id}_{MASTER_SUFFIXES[env]}"
        if master != expected:
            raise ReleaseConfigError(
                f"{path}: {env} master is {master!r}, expected {expected!r} (ADR 011 naming)"
            )
        masters[env] = master
        hosts[env] = str(block.get("host") or "").rstrip("/")
        github_environments[env] = str(block.get("github_environment") or "")

    canonical = _load_canonical(env_config_path or path.parent / DEFAULT_ENV_CONFIG_PATH)

    return ReleaseConfig(
        path=path,
        dp_id=dp_id,
        label=label,
        datasource_id=canonical["datasource_id"],
        datasource_schema=canonical["datasource_schema"],
        masters=masters,
        hosts=hosts,
        github_environments=github_environments,
    )


def _load_canonical(path: Path) -> dict[str, str]:
    """The data source the projection resolves to, from ``config.env.yml``'s ``globalmart_canonical``.

    It is config rather than a code constant (STEERING § "Config, not code"). gdcloud ignores the
    key; gdcloud's own settings live under ``env_config``.
    """
    block = (_load_yaml(path).get("globalmart_canonical") or {}) if path.exists() else {}
    missing = [key for key in ("datasource_id", "datasource_schema") if not block.get(key)]
    if missing:
        raise ReleaseConfigError(f"{path}: globalmart_canonical is missing {missing}")
    return {key: str(block[key]) for key in ("datasource_id", "datasource_schema")}


def master_workspace_id(config: ReleaseConfig, environment: str) -> str:
    try:
        return config.masters[environment]
    except KeyError:
        known = ", ".join(sorted(config.masters))
        raise ReleaseConfigError(f"Unknown environment {environment!r}. Known: {known}") from None


def parse_deploy_tag(tag: str) -> tuple[str, str, str, datetime] | None:
    """``(environment, dp_id, version, deployed_at)`` for a gdcloud deploy tag, else ``None``."""
    match = _DEPLOY_TAG.match(tag)
    if not match:
        return None
    stamp = datetime.strptime(match["stamp"], _TAG_STAMP_FORMAT).replace(tzinfo=UTC)
    return match["env"], match["dp"], match["version"], stamp


def release_scope_from_tags(
    config: ReleaseConfig,
    since: datetime,
    *,
    environment: str | None = None,
    tags: list[str] | None = None,
    repo: Path = Path("."),
) -> ReleaseScope | None:
    """The newest deploy of this repo's data product at or after ``since``, or ``None``.

    ``None`` is the normal answer for a TOOLING-only merge, which deploys nothing: the
    post-deploy workflow then has nothing to publish. ``tags`` is injectable for tests; by
    default the repository's tags are listed.
    """
    if since.tzinfo is None:
        raise ReleaseConfigError("since must be timezone-aware")
    if tags is None:
        tags = _list_deploy_tags(repo)

    newest: ReleaseScope | None = None
    for tag in tags:
        parsed = parse_deploy_tag(tag)
        if parsed is None:
            continue
        env, dp_id, version, deployed_at = parsed
        if dp_id != config.dp_id or deployed_at < since.replace(microsecond=0):
            continue
        if environment is not None and env != environment:
            continue
        if newest is None or deployed_at > newest.deployed_at:
            newest = ReleaseScope(
                environment=env,
                version=version,
                workspace_id=master_workspace_id(config, env),
                deployed_at=deployed_at,
            )
    return newest


def _list_deploy_tags(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "tag", "--list", "deploy-*"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
