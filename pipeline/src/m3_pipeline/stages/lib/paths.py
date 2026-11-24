"""Where a stage keeps its files, and how a subject id names its car body."""

import re
from pathlib import Path

from m3_pipeline.config import Settings

# The subject shapes of the photo lane's `parse_subject` that name a car: `<gen>-<body>` and
# `<gen>-<body>-interior`. Product subjects (`product-<part>`) have no body.
_SUBJECT = re.compile(r"^[a-z0-9]+-(?P<body>coupe|convertible|sedan)(?:-interior)?$")


def require_work_dir_outside_repo(settings: Settings) -> None:
    """Raise ValueError if `settings.work_dir` is the repo or inside it.

    Photos, generator output and renders never enter the repo (docs/standards/legal.md). Both
    paths are resolved first, so a symlink or `..` can't hide the overlap.
    """
    if settings.work_dir.resolve().is_relative_to(settings.repo_root.resolve()):
        raise ValueError(
            f"work_dir {settings.work_dir} is inside the repo {settings.repo_root}; "
            "set M3_WORK_DIR to a folder outside it"
        )


def stage_dir(settings: Settings, asset_id: str, stage: str) -> Path:
    """`<work_dir>/assets/<asset_id>/<stage>`, created if absent.

    Raises ValueError for a work_dir inside the repo, and for an id or stage name that is not a
    single path segment (so it can't point outside its folder).
    """
    require_work_dir_outside_repo(settings)
    for label, name in (("asset id", asset_id), ("stage", stage)):
        if not name or name in {".", ".."} or "/" in name or "\\" in name:
            raise ValueError(f"{label} {name!r} is not a single path segment")
    path = settings.work_dir / "assets" / asset_id / stage
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
