"""Bind every synthetic-view guard to the bytes it actually reviewed."""

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from m3_pipeline.stages.lib.paths import require_write_target_outside_repo
from m3_pipeline.stages.lib.viewset_io import SpikeViewSet

_VIEWS = frozenset({"front", "side", "rear", "front_34", "rear_34"})
_HASH = re.compile(r"^[0-9a-f]{64}$")
_REPO = Path(__file__).resolve().parents[5]


@dataclass(frozen=True)
class ViewProvenance:
    view: str
    inputs: tuple[str, ...]
    prompt_sha256: str
    engine: Literal["codex", "fal"]
    created_at: str
    sha256: str
    critic_ok: bool | None

    def __post_init__(self) -> None:
        if not isinstance(self.view, str) or self.view not in _VIEWS:
            raise ValueError(f"unknown synthesized view: {self.view}")
        if not self.inputs or any(not isinstance(i, str) or not i for i in self.inputs):
            raise ValueError("provenance inputs must be nonempty image ids")
        if not isinstance(self.prompt_sha256, str) or not _HASH.fullmatch(self.prompt_sha256):
            raise ValueError("invalid prompt_sha256")
        if not isinstance(self.sha256, str) or not _HASH.fullmatch(self.sha256):
            raise ValueError("invalid view sha256")
        if self.engine not in ("codex", "fal"):
            raise ValueError("invalid synthesis engine")
        if not isinstance(self.created_at, str) or not self.created_at:
            raise ValueError("created_at is required")
        if self.critic_ok is not None and type(self.critic_ok) is not bool:
            raise ValueError("critic_ok must be boolean or null")


def _unique(items: Sequence[ViewProvenance]) -> None:
    if len({item.view for item in items}) != len(items):
        raise ValueError("duplicate provenance views")


def write_provenance(path: Path, items: Sequence[ViewProvenance]) -> None:
    _unique(items)
    require_write_target_outside_repo(dest=path, repo_root=_REPO)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(item) for item in items], indent=2) + "\n", "utf-8")


def load_provenance(path: Path) -> list[ViewProvenance]:
    raw = json.loads(path.read_text("utf-8"))
    if not isinstance(raw, list):
        raise ValueError("provenance must be an array")
    result: list[ViewProvenance] = []
    keys = {"view", "inputs", "prompt_sha256", "engine", "created_at", "sha256", "critic_ok"}
    for item in raw:
        if not isinstance(item, dict) or set(item) != keys:
            raise ValueError("invalid provenance fields")
        if not isinstance(item["inputs"], list):
            raise ValueError("provenance inputs must be an array")
        result.append(ViewProvenance(**{**item, "inputs": tuple(item["inputs"])}))
    _unique(result)
    return result


def check_provenance(items: Sequence[ViewProvenance], viewset: SpikeViewSet) -> None:
    _unique(items)
    known = {ref.image_id for ref in viewset.entries()}
    for item in items:
        unknown = set(item.inputs) - known
        if unknown:
            raise ValueError(
                f"{item.view}: unknown provenance input(s): {', '.join(sorted(unknown))}"
            )


def synth_set_usable(synth_dir: Path) -> bool:
    """Fail closed on absent, malformed or stale guards; no cached verdict survives new bytes."""
    try:
        root = synth_dir.resolve()
        # Guard documents are private artifacts too: never follow a link out of this set.
        for name in ("provenance.json", "proportion.json", "approved.json", "views"):
            path = synth_dir / name
            if not path.resolve().is_relative_to(root):
                return False
        items = load_provenance(synth_dir / "provenance.json")
        names = {item.view for item in items}
        if names != _VIEWS:
            return False
        view_dir = synth_dir / "views"
        if {path.stem for path in view_dir.glob("*.png")} != names:
            return False
        hashes: dict[str, str] = {}
        for item in items:
            path = view_dir / f"{item.view}.png"
            if path.is_symlink() or not path.resolve().is_relative_to(synth_dir.resolve()):
                return False
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if item.critic_ok is not True or digest != item.sha256:
                return False
            hashes[item.view] = digest
        proportion = json.loads((synth_dir / "proportion.json").read_text("utf-8"))
        approved = json.loads((synth_dir / "approved.json").read_text("utf-8"))
        return (
            isinstance(proportion, dict)
            and proportion.get("ok") is True
            and proportion.get("side_sha256") == hashes["side"]
            and isinstance(approved, dict)
            and approved.get("approved_by") == "user"
            and isinstance(approved.get("at"), str)
            and bool(approved["at"])
            and approved.get("views") == hashes
        )
    except OSError, ValueError, TypeError, KeyError:
        return False
