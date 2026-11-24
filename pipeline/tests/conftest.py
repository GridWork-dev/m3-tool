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
