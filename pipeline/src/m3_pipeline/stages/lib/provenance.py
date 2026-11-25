"""Bind every synthetic-view guard to the bytes it actually reviewed."""

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

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
    images_inspected: bool | None = None

    def __post_init__(self) -> None:
        if self.images_inspected is not None and type(self.images_inspected) is not bool:
            raise ValueError("images_inspected must be boolean or null")
        if not isinstance(cast(object, self.view), str) or self.view not in _VIEWS:
            raise ValueError(f"unknown synthesized view: {self.view}")
        if not self.inputs or any(
            not isinstance(cast(object, i), str) or not i for i in self.inputs
        ):
            raise ValueError("provenance inputs must be nonempty image ids")
        if not isinstance(cast(object, self.prompt_sha256), str) or not _HASH.fullmatch(
            self.prompt_sha256
        ):
            raise ValueError("invalid prompt_sha256")
        if not isinstance(cast(object, self.sha256), str) or not _HASH.fullmatch(self.sha256):
            raise ValueError("invalid view sha256")
        if self.engine not in ("codex", "fal"):
            raise ValueError("invalid synthesis engine")
        if not isinstance(cast(object, self.created_at), str) or not self.created_at:
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
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            raise ValueError("provenance entries must be objects")
        fields = cast(dict[str, object], item)
        if set(fields) not in (keys, keys | {"images_inspected"}):
            raise ValueError("invalid provenance fields")
        inputs = fields["inputs"]
        if not isinstance(inputs, list):
            raise ValueError("provenance inputs must be an array")
        values = cast(list[object], inputs)
        if any(not isinstance(value, str) for value in values):
            raise ValueError("provenance inputs must contain image ids")
        for key in ("view", "prompt_sha256", "engine", "created_at", "sha256"):
            if not isinstance(fields[key], str):
                raise ValueError(f"provenance {key} must be a string")
        critic = fields["critic_ok"]
        if critic is not None and not isinstance(critic, bool):
            raise ValueError("critic_ok must be boolean or null")
        inspected = fields.get("images_inspected")
        if inspected is not None and not isinstance(inspected, bool):
            raise ValueError("images_inspected must be boolean or null")
        engine = fields["engine"]
        if engine not in ("codex", "fal"):
            raise ValueError("invalid synthesis engine")
        result.append(
            ViewProvenance(
                cast(str, fields["view"]),
                tuple(cast(list[str], values)),
                cast(str, fields["prompt_sha256"]),
                engine,
                cast(str, fields["created_at"]),
                cast(str, fields["sha256"]),
                critic,
                inspected,
            )
        )
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
        if names != set(_VIEWS):
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
            if (
                item.critic_ok is not True
                or item.images_inspected is not True
                or digest != item.sha256
            ):
                return False
            hashes[item.view] = digest
        proportion = json.loads((synth_dir / "proportion.json").read_text("utf-8"))
        approved = json.loads((synth_dir / "approved.json").read_text("utf-8"))
        if not isinstance(proportion, dict) or not isinstance(approved, dict):
            return False
        prop = cast(dict[str, object], proportion)
        approval = cast(dict[str, object], approved)
        return (
            prop.get("ok") is True
            and prop.get("side_sha256") == hashes["side"]
            and approval.get("approved_by") == "user"
            and isinstance(approval.get("at"), str)
            and bool(approval["at"])
            and approval.get("views") == hashes
        )
    except OSError, ValueError, TypeError, KeyError:
        return False
