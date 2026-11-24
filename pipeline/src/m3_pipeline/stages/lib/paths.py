"""Where a stage keeps its files, and how a subject id names its car body."""

import os
import re
from pathlib import Path

from m3_pipeline.config import Settings

# The subject shapes of the photo lane's `parse_subject` that name a car: `<gen>-<body>` and
# `<gen>-<body>-interior`. Product subjects (`product-<part>`) have no body.
_SUBJECT = re.compile(r"^[a-z0-9]+-(?P<body>coupe|convertible|sedan)(?:-interior)?$")


def is_inside_repo(repo_root: Path, path: Path) -> bool:
    """True if `path` is the repo or inside it, wherever its spelling and links lead.

    `path` need not exist. It is resolved first (symlinks followed, `..` folded), so a link
    in the middle of the path shows where the file would really go. A name comparison alone
    is not enough on a volume that ignores case (the macOS default): `/users/x/Repo` and
    `/Users/x/repo` are one folder, and resolve() keeps whichever spelling it was given. So
    the folders on the way up are also compared by identity (`samefile`).
    """
    resolved = path.resolve()
    root = repo_root.resolve()
    if resolved.is_relative_to(root):
        return True
    for folder in (resolved, *resolved.parents):
        try:
            if os.path.samefile(folder, root):
                return True
        except OSError:
            continue  # this ancestor, or the repo itself, does not exist (yet)
    return False


def require_outside_repo(repo_root: Path, path: Path) -> None:
    """Raise ValueError if writing at `path` would put a file in the repo.

    Photos, generator output and renders never enter the repo (docs/standards/legal.md). Call
    it with the full destination of every write and every directory creation, not only with
    the work dir: a child folder of a work dir outside the repo can be a link into it.
    """
    if is_inside_repo(repo_root, path):
        raise ValueError(
            f"{path} resolves to {path.resolve()}, inside the repo {repo_root}; photos, "
            "generator output and renders never enter the repo (set M3_WORK_DIR to a folder "
            "outside it and remove links into the repo)"
        )


def require_write_target_outside_repo(dest: Path, repo_root: Path) -> None:
    """Raise ValueError unless a file written at `dest` stays out of the repo, both ways.

    Two places matter. Following every link in `dest` shows where the bytes would end up, and
    that must be outside the repo. But a safe write creates a temp file in the folder of `dest`
    and renames it over `dest`, which replaces a final link instead of following it, so the
    place it really lands is the resolved folder plus the file name, and that folder must be
    outside the repo too. A name that links out of a repo folder passes the first check and
    fails the second. Call it for every file write, before any of them happens.
    """
    require_outside_repo(repo_root, dest)
    landing = dest.parent.resolve() / dest.name
    if is_inside_repo(repo_root, dest.parent):
        raise ValueError(
            f"{dest} would be written at {landing}, inside the repo {repo_root}; photos, "
            "generator output and renders never enter the repo (remove the link into the repo)"
        )


def require_work_dir_outside_repo(settings: Settings) -> None:
    """Raise ValueError if `settings.work_dir` is the repo or inside it."""
    require_outside_repo(settings.repo_root, settings.work_dir)


def stage_dir(settings: Settings, asset_id: str, stage: str) -> Path:
    """`<work_dir>/assets/<asset_id>/<stage>`, created if absent.

    Raises ValueError for a destination inside the repo (the work dir itself, or a link
    anywhere along the way), and for an id or stage name that is not a single path segment (so
    it can't point outside its folder). Nothing is created when it raises.
    """
    require_work_dir_outside_repo(settings)
    for label, name in (("asset id", asset_id), ("stage", stage)):
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError(f"{label} {name!r} is not a single path segment")
    path = settings.work_dir / "assets" / asset_id / stage
    require_write_target_outside_repo(path, settings.repo_root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def subject_body(subject: str) -> str:
    """The body token of a car subject: `e46-coupe` and `e46-coupe-interior` both give `coupe`.

    Raises ValueError for any other shape, product subjects included.
    """
    match = _SUBJECT.match(subject)
    if match is None:
        raise ValueError(
            f"subject {subject!r} is not <generation>-<body> or <generation>-<body>-interior"
        )
    return match["body"]
