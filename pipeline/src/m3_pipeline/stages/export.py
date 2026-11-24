"""The `export` stage: turn the cleaned GLB into the file the contract is checked on.

glTF-Transform lives in TypeScript, so this stage shells out to `tools/export-glb.ts`, which
welds, deduplicates, prunes (keeping the anchors) and meshopt-compresses the GLB, and writes
`<id>.proxy.json` next to it for `score`. `<work_dir>/assets/<id>/cleanup/<id>.cleaned.glb` goes
in, and `<work_dir>/assets/<id>/export/<id>.glb` comes out: the path the `validate` stage reads.

The generator markers travel in the sidecar `cleanup/<id>.cleaned.json` that `cleanup` writes next
to the fixed GLB. A car's is `{"candidate", "method", "markers"}` and an interior's is
`{"parts": {"<part>": {"candidate", "markers"}, ...}}`. The stage hands the car's markers, or the
interior's per-part map, to the script in a temp JSON file, and the script copies them into
`asset.extras.sourceAsset`. No sidecar (the wheel) means no markers. A sidecar of any other shape
fails the stage, because dropping it would lose where the model came from.
"""

import contextlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings
from m3_pipeline.stages import StageResult, register
from m3_pipeline.stages.lib.paths import (
    require_outside_repo,
    require_write_target_outside_repo,
    stage_dir,
)
from m3_pipeline.stages.lib.proc import run_process

# Tests replace this to avoid starting node.
_run = run_process

# A 200k-triangle car exports in seconds. This only stops a hung node from hanging the pipeline.
_TIMEOUT_S = 900


class _SidecarError(ValueError):
    pass


@register("export")
def export(asset: AssetSpec, settings: Settings) -> StageResult:
    cleanup = settings.work_dir / "assets" / asset.id / "cleanup"
    cleaned = cleanup / f"{asset.id}.cleaned.glb"
    sidecar = cleanup / f"{asset.id}.cleaned.json"
    try:
        export_dir = stage_dir(settings, asset.id, "export")
        glb = export_dir / f"{asset.id}.glb"
        proxy = export_dir / f"{asset.id}.proxy.json"
        # Every file read and written here must stay out of the repo, links included. The two
        # guards take their arguments in opposite orders, so both are called with keywords.
        require_write_target_outside_repo(dest=glb, repo_root=settings.repo_root)
        require_write_target_outside_repo(dest=proxy, repo_root=settings.repo_root)
        require_outside_repo(repo_root=settings.repo_root, path=cleaned)
        require_outside_repo(repo_root=settings.repo_root, path=sidecar)
    except ValueError as error:
        return StageResult(False, [str(error)], [])

    # Drop an export from an earlier run first, so a failure below can't leave a GLB that
    # `validate` would check as if this run had made it.
    for old in (glb, proxy):
        try:
            old.unlink(missing_ok=True)
        except OSError as error:
            return StageResult(False, [f"could not remove the old export {old}: {error}"], [])

    if not cleaned.is_file():
        return StageResult(False, [f"{cleaned} does not exist; run --stage cleanup first"], [])
    try:
        markers = _read_markers(asset, sidecar)
    except _SidecarError as error:
        return StageResult(False, [str(error)], [])

    script = settings.repo_root / "tools" / "export-glb.ts"
    cmd = ["node", str(script), str(cleaned), str(glb), "--kind", asset.kind]
    with tempfile.TemporaryDirectory(prefix="m3-export-") as temp:
        if markers is not None:
            markers_file = Path(temp) / "markers.json"
            try:
                require_write_target_outside_repo(dest=markers_file, repo_root=settings.repo_root)
                markers_file.write_text(json.dumps(markers), "utf-8")
            except (ValueError, OSError) as error:
                return StageResult(False, [f"could not write the markers file: {error}"], [])
            cmd += ["--markers", str(markers_file)]
        try:
            proc = _run(cmd, timeout_s=_TIMEOUT_S)
        except OSError as error:
            return StageResult(False, [f"could not run node: {error}"], [])
        except subprocess.TimeoutExpired:
            _discard(glb, proxy)
            return StageResult(False, [f"export-glb timed out after {_TIMEOUT_S} s"], [])

    if proc.returncode != 0:
        _discard(glb, proxy)
        detail = proc.stderr.strip() or proc.stdout.strip() or "no output"
        return StageResult(False, [f"export-glb exited {proc.returncode}: {detail}"], [])
    missing = [path for path in (glb, proxy) if not path.is_file()]
    if missing:
        _discard(glb, proxy)
        names = ", ".join(str(path) for path in missing)
        return StageResult(False, [f"export-glb exited 0 but did not write {names}"], [])
    return StageResult(True, [proc.stdout.strip() or f"exported {glb}"], [glb, proxy])


def _discard(*paths: Path) -> None:
    """Remove half-finished outputs. A failure to remove one is not worth hiding the real one."""
    for path in paths:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def _read_markers(asset: AssetSpec, sidecar: Path) -> dict[str, object] | None:
    """The markers to carry into the export, or None when there is no sidecar.

    A car's are the sidecar's `markers`; an interior's are `{part: markers}` from its `parts`.
    Raises _SidecarError, naming the file, for a sidecar that is not that shape.
    """
    if not sidecar.is_file():
        return None
    try:
        data: object = json.loads(sidecar.read_text("utf-8"))
    except (OSError, ValueError) as error:
        raise _SidecarError(f"{sidecar.name} could not be read as JSON: {error}") from error
    fields = _as_object(data)
    if fields is None:
        raise _SidecarError(f"{sidecar.name} must hold a JSON object")

    if asset.kind != "interior":
        markers = _as_object(fields.get("markers"))
        if markers is None:
            raise _SidecarError(f'{sidecar.name} must have a "markers" object')
        return markers

    parts = _as_object(fields.get("parts"))
    if parts is None:
        raise _SidecarError(f'{sidecar.name} must have a "parts" object')
    per_part: dict[str, object] = {}
    for name, part in parts.items():
        part_fields = _as_object(part)
        part_markers = None if part_fields is None else _as_object(part_fields.get("markers"))
        if part_markers is None:
            raise _SidecarError(f'{sidecar.name}: part {name!r} must have a "markers" object')
        per_part[name] = part_markers
    return per_part


def _as_object(value: object) -> dict[str, object] | None:
    return cast("dict[str, object]", value) if isinstance(value, dict) else None
