"""Warehouse adapters: build and upsert the datasource a workspace reads through.

One small adapter per warehouse type. An unknown type fails loudly, naming it — the
predecessor exited silently on an unsupported warehouse, which is indistinguishable from
success until a visualization fails to compute much later.

The warehouse secret is read from the environment variable the profile *names*; the value
never appears in the profile, the report, or an exception. A test asserts that.
"""

from __future__ import annotations

from enum import StrEnum

from gooddata_sdk import (
    BasicCredentials,
    CatalogDataSourceMotherDuck,
    CatalogDataSourcePostgres,
    GoodDataSdk,
    MotherDuckAttributes,
    PostgresAttributes,
    TokenCredentialsFromEnvVar,
)

from globalmart.config import GlobalmartError, TargetProfile, WarehouseType


class UnsupportedWarehouseError(GlobalmartError):
    """A profile names a warehouse this repo has no adapter for."""


class DataSourceOutcome(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    SKIPPED_NO_APPLY = "skipped (no --apply)"


def build_data_source(
    profile: TargetProfile,
) -> CatalogDataSourceMotherDuck | CatalogDataSourcePostgres:
    """Build the SDK datasource object for a profile, without contacting anything."""
    if profile.warehouse_type is WarehouseType.MOTHERDUCK:
        if not profile.datasource_secret_env:
            raise GlobalmartError(
                f"Profile {profile.name!r} needs datasource_secret_env naming the env var "
                "that holds the MotherDuck token."
            )
        return CatalogDataSourceMotherDuck(
            id=profile.datasource_id,
            name=profile.datasource_name or profile.datasource_id,
            schema=profile.datasource_schema,
            url=profile.datasource_url,
            credentials=TokenCredentialsFromEnvVar(env_var_name=profile.datasource_secret_env),
            db_specific_attributes=MotherDuckAttributes(
                db_name=profile.datasource_database or ""
            ),
        )

    if profile.warehouse_type is WarehouseType.POSTGRES:
        secret = profile.warehouse_secret()
        if secret is None:
            raise GlobalmartError(
                f"Profile {profile.name!r} names {profile.datasource_secret_env!r} for its "
                "Postgres password, but that environment variable is unset."
            )
        return CatalogDataSourcePostgres(
            id=profile.datasource_id,
            name=profile.datasource_name or profile.datasource_id,
            schema=profile.datasource_schema,
            url=profile.datasource_url,
            credentials=BasicCredentials(
                username=profile.datasource_username or "",
                password=secret,
            ),
            db_specific_attributes=PostgresAttributes(
                host="", db_name=profile.datasource_database or "", port="5432"
            )
            if profile.datasource_database
            else None,
        )

    raise UnsupportedWarehouseError(
        f"Profile {profile.name!r} has warehouse_type {profile.warehouse_type!r}, which has "
        f"no adapter. Supported: {', '.join(w.value for w in WarehouseType)}."
    )


def ensure_data_source(
    sdk: GoodDataSdk, profile: TargetProfile, *, apply: bool = False
) -> DataSourceOutcome:
    """Create or update the datasource, reporting which it was.

    The probe is a read, so it runs even in a rehearsal; only the write is gated.
    """
    existed = True
    try:
        sdk.catalog_data_source.get_data_source(profile.datasource_id)
    except Exception:
        existed = False

    if not apply:
        return DataSourceOutcome.SKIPPED_NO_APPLY

    sdk.catalog_data_source.create_or_update_data_source(build_data_source(profile))
    return DataSourceOutcome.UPDATED if existed else DataSourceOutcome.CREATED
