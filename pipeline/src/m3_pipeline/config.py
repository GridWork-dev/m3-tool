import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_WORK_DIR = "~/.cache/m3-tool"


@dataclass(frozen=True)
class Settings:
    repo_root: Path
    work_dir: Path


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Resolve settings from `env` (default: the process environment).

    An empty value counts as unset. `repo_root` defaults to the directory three levels
    above this package (`pipeline/src/m3_pipeline/` -> repo root).

    Both paths are expanded (`~`) and resolved (relative against the cwd, `..` and symlinks
    followed), so "is the work dir inside the repo?" compares real locations. A relative
    `M3_WORK_DIR=.m3-work` must not slip past that check.
    """
    env = os.environ if env is None else env
    repo_root = env.get("M3_REPO_ROOT") or str(Path(__file__).resolve().parents[3])
    work_dir = env.get("M3_WORK_DIR") or DEFAULT_WORK_DIR
    return Settings(
        repo_root=Path(repo_root).expanduser().resolve(),
        work_dir=Path(work_dir).expanduser().resolve(),
    )
