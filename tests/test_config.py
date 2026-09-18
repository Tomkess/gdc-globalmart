"""Task 4 — profile loading, env precedence, and the no-secrets guarantee."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from globalmart.config import (
    DEFAULT_TARGETS_PATH,
    GlobalmartError,
    MissingTokenError,
    ProfileNotFoundError,
    load_profile,
    token_env_var,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGETS = REPO_ROOT / DEFAULT_TARGETS_PATH


def test_loads_demo_cloud_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD", "tok-specific")
    profile = load_profile("demo-cloud", targets_path=TARGETS)

    assert profile.name == "demo-cloud"
    assert profile.host == "https://petertomko.demo.cloud.gooddata.com"
    assert profile.organization_id == "petertomko"
    assert profile.datasource_id == "globalmart-motherduck"
    assert profile.datasource_schema == "globalmart"
    assert profile.parent_workspace_id == "globalmart"
    assert profile.token == "tok-specific"


def test_per_target_token_beats_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBALMART_TOKEN", "tok-generic")
    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD", "tok-specific")
    assert load_profile("demo-cloud", targets_path=TARGETS).token == "tok-specific"


def test_generic_token_used_when_no_specific(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GLOBALMART_TOKEN__DEMO_CLOUD", raising=False)
    monkeypatch.setenv("GLOBALMART_TOKEN", "tok-generic")
    assert load_profile("demo-cloud", targets_path=TARGETS).token == "tok-generic"


def test_missing_token_names_both_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GLOBALMART_TOKEN__DEMO_CLOUD", raising=False)
    monkeypatch.delenv("GLOBALMART_TOKEN", raising=False)

    with pytest.raises(MissingTokenError) as excinfo:
        load_profile("demo-cloud", targets_path=TARGETS)

    message = str(excinfo.value)
    assert "GLOBALMART_TOKEN__DEMO_CLOUD" in message
    assert "GLOBALMART_TOKEN" in message


def test_unknown_profile_lists_known_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBALMART_TOKEN", "tok")
    with pytest.raises(ProfileNotFoundError) as excinfo:
        load_profile("nope", targets_path=TARGETS)
    assert "demo-cloud" in str(excinfo.value)


def test_env_overrides_host_and_datasource(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBALMART_TOKEN", "tok")
    monkeypatch.setenv("GLOBALMART_HOST", "https://elsewhere.example.com")
    monkeypatch.setenv("GLOBALMART_DATASOURCE_ID", "globalmart-postgres")

    profile = load_profile("demo-cloud", targets_path=TARGETS)
    assert profile.host == "https://elsewhere.example.com"
    assert profile.datasource_id == "globalmart-postgres"


def test_missing_required_key_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLOBALMART_TOKEN", "tok")
    broken = tmp_path / "targets.yaml"
    broken.write_text("targets:\n  partial:\n    host: https://x.example.com\n")

    with pytest.raises(GlobalmartError) as excinfo:
        load_profile("partial", targets_path=broken)

    message = str(excinfo.value)
    assert "organization_id" in message
    assert "datasource_id" in message


def test_targets_file_contains_no_token_at_any_depth() -> None:
    """A secret in this file would be committed. Assert the shape makes that impossible."""
    document = yaml.safe_load(TARGETS.read_text())

    def walk(node: object, path: str = "") -> list[str]:
        found: list[str] = []
        if isinstance(node, dict):
            for key, value in node.items():
                here = f"{path}.{key}" if path else str(key)
                if "token" in str(key).lower() or "password" in str(key).lower():
                    found.append(here)
                found.extend(walk(value, here))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                found.extend(walk(item, f"{path}[{index}]"))
        return found

    assert walk(document) == []


def test_token_env_var_naming() -> None:
    assert token_env_var("demo-cloud") == "GLOBALMART_TOKEN__DEMO_CLOUD"
    assert token_env_var("local-inference") == "GLOBALMART_TOKEN__LOCAL_INFERENCE"


def test_dotenv_is_loaded_but_never_overrides_real_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CI secret or a one-off `VAR=... globalmart ...` must beat the committed-adjacent file."""
    from globalmart.config import load_env

    env_file = tmp_path / ".env"
    env_file.write_text("GLOBALMART_TOKEN__DEMO_CLOUD=from-file\nGLOBALMART_FROM_FILE_ONLY=yes\n")

    monkeypatch.setenv("GLOBALMART_TOKEN__DEMO_CLOUD", "from-real-env")
    monkeypatch.delenv("GLOBALMART_FROM_FILE_ONLY", raising=False)

    load_env(env_file)

    import os

    assert os.environ["GLOBALMART_TOKEN__DEMO_CLOUD"] == "from-real-env"
    assert os.environ["GLOBALMART_FROM_FILE_ONLY"] == "yes"


def test_env_example_documents_every_profile_in_targets() -> None:
    """A new target with no documented token variable is a setup trap. Catch it here."""
    example = (REPO_ROOT / ".env.example").read_text()
    document = yaml.safe_load(TARGETS.read_text())

    for profile_name in document["targets"]:
        assert token_env_var(profile_name) in example, (
            f"{token_env_var(profile_name)} missing from .env.example"
        )
