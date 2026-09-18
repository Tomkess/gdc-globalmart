"""Target profiles: where GlobalMart is captured from and published to.

Everything that identifies an org lives here or in ``config/targets.yaml`` — never in
code (STEERING § Portability Contract). Tokens are resolved from the environment only
and are never read from the YAML file.

Multi-host credentials
----------------------
One token variable per target, named from the profile: ``demo-cloud`` reads
``GLOBALMART_TOKEN__DEMO_CLOUD``, ``local-inference`` reads
``GLOBALMART_TOKEN__LOCAL_INFERENCE``. That way several orgs coexist in one ``.env``
with nothing to edit between runs, and a mistyped ``--target`` fails with "no token"
rather than quietly authenticating against the wrong org with a shared one.

``.env`` at the repo root is loaded automatically if present (see ``.env.example``).
Real environment variables always win over it, so CI and one-off overrides work without
touching the file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml
from dotenv import load_dotenv

DEFAULT_TARGETS_PATH = Path("config/targets.yaml")
DEFAULT_ENV_PATH = Path(".env")

#: Generic token fallback, used when the per-target variable is unset.
GENERIC_TOKEN_ENV = "GLOBALMART_TOKEN"

_env_loaded = False


def load_env(env_path: Path | None = None) -> None:
    """Load ``.env`` once, without overriding anything already in the environment.

    ``override=False`` is the important part: a real environment variable (CI secret, a
    one-off `GLOBALMART_TOKEN__X=... globalmart ...`) must beat the file, not the reverse.
    """
    global _env_loaded
    if _env_loaded and env_path is None:
        return
    path = env_path or DEFAULT_ENV_PATH
    if path.exists():
        load_dotenv(path, override=False)
    if env_path is None:
        _env_loaded = True


class GlobalmartError(Exception):
    """Base for every error this package raises deliberately."""


class ProfileNotFoundError(GlobalmartError):
    """The named profile does not exist in the targets file."""


class MissingTokenError(GlobalmartError):
    """No API token in the environment for this profile."""


class MissingProfileKeyError(GlobalmartError):
    """A profile lacks a value required for the operation being attempted."""


class WarehouseType(StrEnum):
    """Warehouses this repo can register a datasource for.

    Any other value in the YAML raises at profile-load time rather than at publish time,
    so an unsupported warehouse fails locally instead of halfway through a publish.
    """

    MOTHERDUCK = "motherduck"
    POSTGRES = "postgres"


def token_env_var(profile_name: str) -> str:
    """Per-target token variable, e.g. ``demo-cloud`` -> ``GLOBALMART_TOKEN__DEMO_CLOUD``."""
    suffix = profile_name.upper().replace("-", "_")
    return f"{GENERIC_TOKEN_ENV}__{suffix}"


@dataclass(frozen=True)
class TargetProfile:
    """One org this repo can capture from or publish to.

    ``datasource_id`` and ``datasource_schema`` are read in both directions: on capture
    they say what to scrub out of the layout, on publish what to substitute back in.
    That symmetry is what makes the portability contract testable.
    """

    name: str
    host: str
    token: str
    organization_id: str
    datasource_id: str
    datasource_schema: str
    parent_workspace_id: str = "globalmart"

    # --- publish-side fields (FEAT-002) -----------------------------------
    # Absent for a capture-only profile; validate_for_publish names what is missing.
    warehouse_type: WarehouseType | None = None
    datasource_name: str | None = None
    datasource_url: str | None = None
    datasource_database: str | None = None
    datasource_username: str | None = None
    #: The NAME of the env var holding the warehouse secret, never the value.
    datasource_secret_env: str | None = None
    #: Lets several GlobalMart copies coexist in one org for A/B eval runs.
    workspace_id_prefix: str = ""
    backup_dir: Path = Path("backups")

    def warehouse_secret(self) -> str | None:
        """Read the warehouse secret from the environment named by the profile."""
        if not self.datasource_secret_env:
            return None
        return os.environ.get(self.datasource_secret_env)


def _resolve_token(profile_name: str) -> str:
    specific = token_env_var(profile_name)
    token = os.environ.get(specific) or os.environ.get(GENERIC_TOKEN_ENV)
    if not token:
        raise MissingTokenError(
            f"No API token for profile {profile_name!r}. "
            f"Set {specific} (preferred) or {GENERIC_TOKEN_ENV}."
        )
    return token


def load_profile(name: str, targets_path: Path | None = None) -> TargetProfile:
    """Load a target profile by name, with env overrides applied.

    Raises before any network call when a required value is missing, so a typo fails
    locally rather than against a host.
    """
    load_env()

    path = targets_path or DEFAULT_TARGETS_PATH
    if not path.exists():
        raise ProfileNotFoundError(f"Targets file not found: {path}")

    document = yaml.safe_load(path.read_text()) or {}
    targets = document.get("targets") or {}
    if name not in targets:
        known = ", ".join(sorted(targets)) or "(none)"
        raise ProfileNotFoundError(f"Unknown profile {name!r}. Known profiles: {known}")

    entry = dict(targets[name] or {})

    # Env overrides, so a one-off run can point elsewhere without editing the file.
    def field(key: str, env: str) -> str:
        return str(os.environ.get(env) or entry.get(key) or "")

    host = field("host", "GLOBALMART_HOST")
    organization_id = field("organization_id", "GLOBALMART_ORG")
    datasource_id = field("datasource_id", "GLOBALMART_DATASOURCE_ID")
    datasource_schema = field("datasource_schema", "GLOBALMART_DATASOURCE_SCHEMA")
    parent_workspace_id = field("parent_workspace_id", "GLOBALMART_PARENT_WORKSPACE_ID") or "globalmart"

    missing = [
        key
        for key, value in (
            ("host", host),
            ("organization_id", organization_id),
            ("datasource_id", datasource_id),
            ("datasource_schema", datasource_schema),
        )
        if not value
    ]
    if missing:
        raise GlobalmartError(
            f"Profile {name!r} is missing required key(s): {', '.join(missing)}"
        )

    raw_warehouse = field("warehouse_type", "GLOBALMART_WAREHOUSE_TYPE")
    try:
        warehouse_type = WarehouseType(raw_warehouse) if raw_warehouse else None
    except ValueError as error:
        supported = ", ".join(w.value for w in WarehouseType)
        raise GlobalmartError(
            f"Profile {name!r} has unsupported warehouse_type {raw_warehouse!r}. "
            f"Supported: {supported}."
        ) from error

    backup_dir = field("backup_dir", "GLOBALMART_BACKUP_DIR") or "backups"

    return TargetProfile(
        name=name,
        host=host.rstrip("/"),
        token=_resolve_token(name),
        organization_id=organization_id,
        datasource_id=datasource_id,
        datasource_schema=datasource_schema,
        parent_workspace_id=parent_workspace_id,
        warehouse_type=warehouse_type,
        datasource_name=field("datasource_name", "GLOBALMART_DATASOURCE_NAME") or None,
        datasource_url=field("datasource_url", "GLOBALMART_DATASOURCE_URL") or None,
        datasource_database=field("datasource_database", "GLOBALMART_DATASOURCE_DATABASE") or None,
        datasource_username=field("datasource_username", "GLOBALMART_DATASOURCE_USERNAME") or None,
        datasource_secret_env=entry.get("datasource_secret_env") or None,
        workspace_id_prefix=field("workspace_id_prefix", "GLOBALMART_WORKSPACE_ID_PREFIX"),
        backup_dir=Path(backup_dir),
    )


def validate_for_publish(profile: TargetProfile) -> list[str]:
    """Names of every value required to publish that this profile lacks.

    Returned rather than raised so the caller can report them all at once, and checked
    before an SDK client is built — AC #7 requires a publish to fail before contacting the
    host when the profile is incomplete.
    """
    missing: list[str] = []

    if profile.warehouse_type is None:
        missing.append("warehouse_type")
    if not profile.datasource_name:
        missing.append("datasource_name")
    if not profile.datasource_url:
        missing.append("datasource_url")
    if not profile.datasource_secret_env:
        missing.append("datasource_secret_env")
    elif profile.warehouse_secret() is None:
        missing.append(f"{profile.datasource_secret_env} (env var is unset)")

    if profile.warehouse_type is WarehouseType.POSTGRES and not profile.datasource_username:
        missing.append("datasource_username (required for postgres)")

    return missing
