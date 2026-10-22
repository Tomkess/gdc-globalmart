"""FEAT-019 task 18 — `data ensure --check`, the PR gate that keeps data ahead of the workspace."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from globalmart import cli


@dataclass(frozen=True)
class _Freshness:
    is_stale: bool

    def stale(self) -> bool:
        return self.is_stale

    def summary_lines(self) -> list[str]:
        return [f"stale: {self.is_stale}"]


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """No profile, warehouse or generator is reached; any attempt to load is recorded."""
    calls: list[str] = []
    monkeypatch.setattr(cli, "load_profile", lambda name: object())
    monkeypatch.setattr(cli, "build_registry", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "generate_dataset", lambda *a, **k: calls.append("generate"))
    monkeypatch.setattr(cli, "load_data", lambda *a, **k: calls.append("load"))
    return calls


def _freshness(monkeypatch: pytest.MonkeyPatch, *, stale: bool) -> None:
    monkeypatch.setattr(cli, "check_freshness", lambda *a, **k: _Freshness(stale))


def test_current_data_passes(monkeypatch: pytest.MonkeyPatch, offline: list[str]) -> None:
    _freshness(monkeypatch, stale=False)
    assert cli.main(["data", "ensure", "--target", "demo-cloud", "--check"]) == 0
    assert offline == []


def test_stale_data_exits_3_and_writes_nothing(monkeypatch: pytest.MonkeyPatch, offline: list[str]) -> None:
    _freshness(monkeypatch, stale=True)
    assert cli.main(["data", "ensure", "--target", "demo-cloud", "--check"]) == 3
    assert offline == []


def test_forced_regeneration_counts_as_a_planned_write(
    monkeypatch: pytest.MonkeyPatch, offline: list[str]
) -> None:
    _freshness(monkeypatch, stale=False)
    assert cli.main(["data", "ensure", "--target", "demo-cloud", "--check", "--force"]) == 3
    assert offline == []


def test_check_and_apply_are_exclusive(offline: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["data", "ensure", "--target", "demo-cloud", "--check", "--apply"])
    assert exit_info.value.code == 2
