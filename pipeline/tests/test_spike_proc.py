import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from m3_pipeline.stages.lib.proc import run_process


def test_run_process_passes_cwd_and_env_to_the_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("M3_OURS", "set")
    code = (
        "import os; print(os.getcwd()); "
        "print(os.environ.get('M3_PROBE'), os.environ.get('M3_OURS'))"
    )
    result = run_process(
        [sys.executable, "-I", "-c", code], cwd=tmp_path, env={"M3_PROBE": "1"}, timeout_s=30
    )
    cwd, line = result.stdout.strip().split("\n")
    assert Path(cwd).resolve() == tmp_path.resolve()
    assert line == "1 None"  # env replaces ours instead of extending it


def test_run_process_defaults_inherit_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M3_PROBE", "inherited")
    code = "import os; print(os.environ.get('M3_PROBE'))"
    assert run_process([sys.executable, "-I", "-c", code]).stdout.strip() == "inherited"


def test_run_process_captures_stdout_and_stderr_as_text() -> None:
    code = "import sys; print('out'); print('err', file=sys.stderr)"
    result = run_process([sys.executable, "-I", "-c", code])
    assert (result.stdout, result.stderr) == ("out\n", "err\n")
    assert result.args == [sys.executable, "-I", "-c", code]


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


def _gone(pid: int, wait_s: float = 5.0) -> bool:
    """True once no process with `pid` is left (a zombie that nobody reaped counts as left)."""
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_run_process_timeout_kills_the_grandchildren_too(tmp_path: Path) -> None:
    """Blender spawns helpers of its own. Killing only the direct child leaves them running,
    and they keep the output pipes open, so the caller would also hang for as long as they live."""
    pid_file = tmp_path / "grandchild.pid"
    script = f"sleep 30 & echo $! > {pid_file}; wait"
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_process(["sh", "-c", script], timeout_s=1)
    assert time.monotonic() - started < 15  # not the 30 s the grandchild would have held us
    grandchild = int(pid_file.read_text("utf-8"))
    try:
        assert _gone(grandchild), f"grandchild {grandchild} survived the timeout"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(grandchild, signal.SIGKILL)


def test_run_process_starts_the_child_in_its_own_process_group() -> None:
    code = f"import os; print(os.getpgrp() == os.getpid(), os.getpgrp() != {os.getpgrp()})"
    assert run_process([sys.executable, "-I", "-c", code]).stdout.split() == ["True", "True"]


def test_run_process_still_returns_output_from_a_child_that_finishes_in_time() -> None:
    result = run_process(["sh", "-c", "echo done"], timeout_s=30)
    assert (result.returncode, result.stdout) == (0, "done\n")
