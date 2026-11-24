import subprocess
import sys
from pathlib import Path

import pytest

from m3_pipeline.stages.lib.proc import run_process


def test_run_process_passes_cwd_timeout_env_and_devnull_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = cmd
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "out", "err")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_process(
        ("tool", "--flag"), cwd=tmp_path, timeout_s=30, stdin_devnull=True, env={"A": "1"}
    )
    assert result.stdout == "out"
    assert seen["cmd"] == ["tool", "--flag"]
    assert seen["cwd"] == tmp_path
    assert seen["timeout"] == 30
    assert seen["env"] == {"A": "1"}
    assert seen["stdin"] == subprocess.DEVNULL
    assert seen["text"] is True and seen["capture_output"] is True and seen["check"] is False


def test_run_process_defaults_leave_the_environment_and_stdin_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_process(["tool"])
    assert seen["cwd"] is None and seen["timeout"] is None
    assert seen["env"] is None and seen["stdin"] is None


def test_run_process_does_not_raise_on_a_nonzero_exit() -> None:
    result = run_process([sys.executable, "-I", "-c", "import sys; print('hi'); sys.exit(3)"])
    assert result.returncode == 3
    assert result.stdout.strip() == "hi"


def test_run_process_reads_no_stdin_when_asked_not_to() -> None:
    code = "import sys; print(repr(sys.stdin.read()))"
    result = run_process([sys.executable, "-I", "-c", code], stdin_devnull=True, timeout_s=30)
    assert result.stdout.strip() == "''"


def test_run_process_lets_a_missing_program_raise_oserror() -> None:
    # Callers already catch OSError ("could not run node"), so it must not be swallowed here.
    with pytest.raises(OSError):
        run_process(["m3-tool-no-such-program"])
