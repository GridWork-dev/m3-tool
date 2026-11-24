import subprocess
from pathlib import Path

import pytest

import m3_pipeline.stages.lib.blender as blender_mod
from m3_pipeline.stages.lib.blender import blender_binary, build_argv, run_blender


def _executable(path: Path) -> Path:
    path.write_text("#!/bin/sh\n", "utf-8")
    path.chmod(0o755)
    return path


def test_build_argv_runs_headless_with_factory_startup_and_double_dash() -> None:
    argv = build_argv(
        Path("/opt/blender"),
        Path("/repo/pipeline/blender/prepare_car.py"),
        [
            "--plan",
            "/work/plan.json",
        ],
    )
    assert argv == [
        "/opt/blender",
        "-b",
        "--factory-startup",
        "-P",
        "/repo/pipeline/blender/prepare_car.py",
        "--",
        "--plan",
        "/work/plan.json",
    ]


def test_build_argv_with_no_arguments_still_ends_in_the_double_dash() -> None:
    argv = build_argv(Path("/opt/blender"), Path("/s.py"), [])
    assert argv[-2:] == ["/s.py", "--"]


def test_blender_binary_prefers_the_env_override(tmp_path: Path) -> None:
    override = _executable(tmp_path / "custom-blender")
    on_path = tmp_path / "bin"
    on_path.mkdir()
    _executable(on_path / "blender")
    env = {"M3_BLENDER": str(override), "PATH": str(on_path)}
    assert blender_binary(env) == override


def test_blender_binary_falls_back_to_blender_on_path(tmp_path: Path) -> None:
    on_path = tmp_path / "bin"
    on_path.mkdir()
    found = _executable(on_path / "blender")
    assert blender_binary({"PATH": str(on_path)}) == found
    # An empty override counts as unset, as it does in config.
    assert blender_binary({"M3_BLENDER": "", "PATH": str(on_path)}) == found


def test_blender_binary_missing_raises_file_not_found_naming_m3_blender(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="M3_BLENDER"):
        blender_binary({"PATH": str(tmp_path)})
    with pytest.raises(FileNotFoundError, match="M3_BLENDER"):
        blender_binary({})


def test_run_blender_goes_through_the_replaceable_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = _executable(tmp_path / "blender")
    monkeypatch.setenv("M3_BLENDER", str(binary))
    seen: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, "ok", "")

    monkeypatch.setattr(blender_mod, "_run", fake_run)
    result = run_blender(Path("/s.py"), ["--plan", "p.json"], timeout_s=60)
    assert result.stdout == "ok"
    cmd, kwargs = seen[0]
    assert cmd == [str(binary), "-b", "--factory-startup", "-P", "/s.py", "--", "--plan", "p.json"]
    assert kwargs["timeout_s"] == 60
    assert kwargs["stdin_devnull"] is True


def test_run_blender_default_timeout_is_30_minutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("M3_BLENDER", str(_executable(tmp_path / "blender")))
    seen: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(blender_mod, "_run", fake_run)
    run_blender(Path("/s.py"), [])
    assert seen["timeout_s"] == 1800


def test_run_blender_with_no_binary_raises_before_starting_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("M3_BLENDER", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    started: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        started.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(blender_mod, "_run", fake_run)
    with pytest.raises(FileNotFoundError, match="M3_BLENDER"):
        run_blender(Path("/s.py"), [])
    assert started == []
