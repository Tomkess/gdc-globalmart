"""Warehouse adapters. One module per warehouse, one small protocol in `base`."""

from __future__ import annotations

from globalmart.config import GlobalmartError, TargetProfile, WarehouseType
from globalmart.loaders.base import LoadError, LoadReport, TableLoad, WarehouseLoader

__all__ = [
    "LoadError",
    "LoadReport",
    "TableLoad",
    "WarehouseLoader",
    "make_loader",
]


def make_loader(profile: TargetProfile) -> WarehouseLoader:
    """The adapter for this profile's warehouse.

    An unsupported warehouse fails here, loudly, naming what is supported — rather than
    being discovered halfway through a load.
    """
    if profile.warehouse_type is WarehouseType.MOTHERDUCK:
        from globalmart.loaders.motherduck import MotherDuckLoader

        return MotherDuckLoader(profile)
    if profile.warehouse_type is WarehouseType.POSTGRES:
        from globalmart.loaders.postgres import PostgresLoader

        return PostgresLoader(profile)
    supported = ", ".join(w.value for w in WarehouseType)
    raise GlobalmartError(
        f"Profile {profile.name!r} has warehouse_type {profile.warehouse_type!r}; "
        f"loading supports: {supported}"
    )
