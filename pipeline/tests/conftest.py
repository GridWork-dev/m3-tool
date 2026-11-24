import socket
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from m3_pipeline.config import Settings

if TYPE_CHECKING:
    from m3_pipeline.refs.store import RefStore


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    original = socket.socket.connect

    def guarded_connect(sock: socket.socket, address: object) -> None:
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise OSError("tests may connect only to loopback")
        original(sock, cast(Any, address))

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    repo = tmp_path / "repo"
    repo.mkdir()
    return Settings(repo_root=repo, work_dir=tmp_path / "work")


@pytest.fixture
def store(settings: Settings) -> RefStore:
    from m3_pipeline.refs.store import RefStore

    return RefStore(settings)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if not any(item.get_closest_marker("browser") for item in items):
        return
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        installed = Path(playwright.chromium.executable_path).exists()
    if not installed:
        skip = pytest.mark.skip(reason="chromium not installed: uv run playwright install chromium")
        for item in items:
            if item.get_closest_marker("browser"):
                item.add_marker(skip)
