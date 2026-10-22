"""FEAT-019 tasks 9–11 — what config.yml says about the release, and reading deploys back from tags."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from globalmart.gdcloud_bridge import (
    DEFAULT_ENV_CONFIG_PATH,
    DEFAULT_RELEASE_CONFIG_PATH,
    ReleaseConfig,
    ReleaseConfigError,
    load_release_config,
    master_workspace_id,
    parse_deploy_tag,
    release_scope_from_tags,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / DEFAULT_RELEASE_CONFIG_PATH
ENV_CONFIG = REPO_ROOT / DEFAULT_ENV_CONFIG_PATH


@pytest.fixture
def release() -> ReleaseConfig:
    return load_release_config(CONFIG)


def _write_variant(tmp_path: Path, mutate) -> Path:  # type: ignore[no-untyped-def]
    document = yaml.safe_load(CONFIG.read_text())
    mutate(document)
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(document))
    (tmp_path / "gd_data_product").mkdir()
    (tmp_path / DEFAULT_ENV_CONFIG_PATH).write_text(ENV_CONFIG.read_text())
    return path


# --- the committed config ------------------------------------------------------------------


def test_committed_config_releases_one_data_product(release: ReleaseConfig) -> None:
    assert release.dp_id == "globalmart"
    assert release.label == "GM"


def test_masters_follow_the_naming_scheme(release: ReleaseConfig) -> None:
    assert release.masters == {
        "dev": "globalmart_dev",
        "test": "globalmart_test",
        "preprod": "globalmart_preprod",
        "prod": "globalmart_master",
    }


def test_two_environments_per_org(release: ReleaseConfig) -> None:
    assert release.hosts["dev"] == release.hosts["test"] == "https://petertomko.demo.cloud.gooddata.com"
    assert release.hosts["preprod"] == release.hosts["prod"] == "https://usecases-ai.demo.cloud.gooddata.com"


def test_only_prod_is_protected() -> None:
    environments = yaml.safe_load(CONFIG.read_text())["environments"]
    assert {env for env, block in environments.items() if block.get("protected")} == {"prod"}


def test_org_level_release_is_off() -> None:
    automation = yaml.safe_load(CONFIG.read_text())["automation"]
    assert automation["org_release"]["enabled"] is False
    assert automation["organization_snapshot"]["enabled"] is False


def test_canonical_data_source_comes_from_config_env(release: ReleaseConfig) -> None:
    assert release.datasource_id == "gdc_ds_globalmart_motherduck"
    assert release.datasource_schema == "globalmart"


def test_github_environments(release: ReleaseConfig) -> None:
    assert release.github_environments == {
        "dev": "develop",
        "test": "staging",
        "preprod": "preprod",
        "prod": "production",
    }


def test_unknown_environment_raises(release: ReleaseConfig) -> None:
    with pytest.raises(ReleaseConfigError, match="Unknown environment 'staging'"):
        master_workspace_id(release, "staging")


# --- config shapes that must be refused ----------------------------------------------------


def test_a_second_data_product_is_refused(tmp_path: Path) -> None:
    def add_domain(document: dict) -> None:  # type: ignore[type-arg]
        document["data_products"]["globalmart_sales"] = {"label": "GM_SALES"}

    with pytest.raises(ReleaseConfigError, match="exactly one data product"):
        load_release_config(_write_variant(tmp_path, add_domain))


def test_an_environment_without_the_data_product_is_refused(tmp_path: Path) -> None:
    def drop(document: dict) -> None:  # type: ignore[type-arg]
        document["environments"]["test"]["data_products"] = {}

    with pytest.raises(ReleaseConfigError, match="'test' does not deploy"):
        load_release_config(_write_variant(tmp_path, drop))


def test_a_master_off_the_naming_scheme_is_refused(tmp_path: Path) -> None:
    def rename(document: dict) -> None:  # type: ignore[type-arg]
        document["environments"]["prod"]["data_products"]["globalmart"]["master_workspace_id"] = "globalmart"

    with pytest.raises(ReleaseConfigError, match="expected 'globalmart_master'"):
        load_release_config(_write_variant(tmp_path, rename))


def test_missing_canonical_block_is_refused(tmp_path: Path) -> None:
    path = _write_variant(tmp_path, lambda document: None)
    (tmp_path / DEFAULT_ENV_CONFIG_PATH).write_text("env_config: {}\n")
    with pytest.raises(ReleaseConfigError, match="globalmart_canonical is missing"):
        load_release_config(path)


# --- deploy tags ---------------------------------------------------------------------------


def test_parses_gdclouds_tag_format() -> None:
    # The timestamp has a hyphen of its own — splitting on "-" would get this wrong.
    assert parse_deploy_tag("deploy-dev-globalmart-v1.7-20261022-101500") == (
        "dev",
        "globalmart",
        "v1.7",
        datetime(2026, 10, 22, 10, 15, 0, tzinfo=UTC),
    )


def test_parses_a_hotfix_version() -> None:
    parsed = parse_deploy_tag("deploy-prod-globalmart-v1.7.1-20261023-090000")
    assert parsed is not None and parsed[2] == "v1.7.1"


@pytest.mark.parametrize(
    "tag", ["v1.7", "deploy-qa-globalmart-v1.7-20261022-101500", "deploy-dev-globalmart-v1.7"]
)
def test_non_deploy_tags_are_ignored(tag: str) -> None:
    assert parse_deploy_tag(tag) is None


SINCE = datetime(2026, 10, 22, 10, 0, 0, tzinfo=UTC)
TAGS = [
    "v1.6",
    "deploy-dev-globalmart-v1.6-20261021-120000",   # before `since`
    "deploy-dev-globalmart-v1.7-20261022-101500",
    "deploy-test-globalmart-v1.7-20261022-111500",
    "deploy-dev-ecommerce_demo-v1.9-20261022-120000",  # another data product
]


def test_scope_is_the_newest_deploy_since(release: ReleaseConfig) -> None:
    scope = release_scope_from_tags(release, SINCE, tags=TAGS)
    assert scope is not None
    assert (scope.environment, scope.version, scope.workspace_id) == ("test", "v1.7", "globalmart_test")


def test_scope_can_be_narrowed_to_one_environment(release: ReleaseConfig) -> None:
    scope = release_scope_from_tags(release, SINCE, environment="dev", tags=TAGS)
    assert scope is not None and scope.workspace_id == "globalmart_dev"


def test_no_deploy_since_means_no_scope(release: ReleaseConfig) -> None:
    # A TOOLING-only merge deploys nothing; the post-deploy workflow must have nothing to do.
    later = datetime(2026, 10, 23, tzinfo=UTC)
    assert release_scope_from_tags(release, later, tags=TAGS) is None


def test_naive_since_is_refused(release: ReleaseConfig) -> None:
    with pytest.raises(ReleaseConfigError, match="timezone-aware"):
        release_scope_from_tags(release, datetime(2026, 10, 22), tags=TAGS)
