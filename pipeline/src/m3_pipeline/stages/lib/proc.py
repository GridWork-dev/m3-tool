"""The one subprocess runner.

Every module that starts a process binds `run_process` as a module variable `_run`, so a test
replaces one name per module and no test starts Blender, node or Codex.
"""

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
    """
    return subprocess.run(
        list(cmd),
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        timeout=timeout_s,
        stdin=subprocess.DEVNULL if stdin_devnull else None,
        env=None if env is None else dict(env),
    )
