"""Run a Blender script headless.

Blender 5.2.3 LTS, `blender -b -P script.py -- args`. The binary comes from env `M3_BLENDER`,
else `blender` on PATH. The scripts live in `pipeline/blender/` and take a plan file; Python
writes the plan and reads what the script leaves in its output directory.
"""

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from m3_pipeline.stages.lib.proc import run_process

# Tests replace this to avoid starting Blender.
_run: Callable[..., subprocess.CompletedProcess[str]] = run_process


def blender_binary(env: Mapping[str, str] | None = None) -> Path:
    """`M3_BLENDER` if set (an empty value counts as unset), else `blender` on PATH.

    Raises FileNotFoundError, naming M3_BLENDER, when neither gives a binary.
    """
    env = os.environ if env is None else env
    override = env.get("M3_BLENDER")
    if override:
        return Path(override)
    found = shutil.which("blender", path=env.get("PATH", ""))
    if found is None:
        raise FileNotFoundError(
            "Blender not found: set M3_BLENDER to the Blender binary, or put `blender` on PATH"
        )
    return Path(found)


def build_argv(binary: Path, script: Path, args: Sequence[str]) -> list[str]:
    """Headless, with factory settings so a user's add-ons and preferences can't change a run.
    Everything after `--` is for the script."""
    return [str(binary), "-b", "--factory-startup", "-P", str(script), "--", *args]


def run_blender(
    script: Path, args: Sequence[str], *, timeout_s: int = 1800
) -> subprocess.CompletedProcess[str]:
    """Run `script` in Blender with `args`. A nonzero exit is returned, not raised.

    A missing binary raises FileNotFoundError, a Blender that can't start raises OSError, and a
    run past `timeout_s` raises `subprocess.TimeoutExpired` with Blender's whole process group
    killed. Every script in `pipeline/blender/` exits nonzero when it fails.
    """
    argv = build_argv(blender_binary(), script, args)
    return _run(argv, timeout_s=timeout_s, stdin_devnull=True)
