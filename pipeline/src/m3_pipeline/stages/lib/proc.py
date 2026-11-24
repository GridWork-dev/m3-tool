"""The one subprocess runner.

Every module that starts a process binds `run_process` as a module variable `_run`, so a test
replaces one name per module and no test starts Blender, node or Codex.
"""

import contextlib
import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path


def run_process(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout_s: int | None = None,
    stdin_devnull: bool = False,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `cmd` and capture its text output. A nonzero exit is returned, not raised.

    `env` replaces the child's environment (pass `{**os.environ, ...}` to extend it); None
    inherits ours. `stdin_devnull` closes the child's stdin, for tools that would otherwise wait
    for input. A program that can't start raises OSError, and a run past `timeout_s` raises
    `subprocess.TimeoutExpired`: both are the caller's to handle.

    The child leads a session of its own, so everything it starts (Blender spawns helpers) is in
    its process group. On a timeout, or any other interruption of the wait, the whole group is
    killed and the child reaped before the exception propagates: killing only the child would
    leave its helpers running, holding the output pipes open.
    """
    with subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        stdin=subprocess.DEVNULL if stdin_devnull else None,
        env=None if env is None else dict(env),
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout_s)
        except BaseException:  # TimeoutExpired, KeyboardInterrupt: never leave a group behind
            _kill_group(process)
            raise
        return subprocess.CompletedProcess(list(cmd), process.returncode, stdout, stderr)


def _kill_group(process: subprocess.Popen[str]) -> None:
    """SIGKILL the child's process group, then reap the child."""
    try:
        # start_new_session made the child a session leader, so its group id is its pid.
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError, PermissionError:
        # The group is already gone, or (macOS) holds only a zombie: kill the child itself.
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    process.wait()
