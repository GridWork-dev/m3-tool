"""The `proportion` stage: does the synthesized side view have the real car's proportions?

Spec 9.1a guard 1. The side view `synth` makes is `<work_dir>/assets/<id>/synth/views/side.png`.
This stage cuts the car out of it, measures its length, height and wheelbase (the wheels by a
circle fit), and compares wheelbase/length and height/length with the data's dimensions in
`data/generations/<generation>.yaml`. Each relative error must be at most 2%. Ratios, because the
scale of a generated picture is unknown.

It writes `<synth>/proportion.json`: the `ProportionReport` fields (`ok` among them) and
`side_sha256`, the sha256 of the bytes it measured. `synth_set_usable` accepts the report only
while that digest equals the picture's, so a replaced image never inherits an old result. A picture
that can't be measured (`SilhouetteError`, or a file that doesn't decode) gets `{"ok": false,
"error": ..., "side_sha256": ...}` instead of the ratios. A report of an earlier run is removed
before the new one is made, so a failure can't leave an old `ok: true` next to a new picture.
"""

import hashlib
import io
import json
from dataclasses import asdict
from pathlib import Path

from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings
from m3_pipeline.stages import StageResult, register
from m3_pipeline.stages.lib.dims import Dimensions, load_dimensions
from m3_pipeline.stages.lib.paths import (
    require_outside_repo,
    require_write_target_outside_repo,
    stage_dir,
    subject_body,
)
from m3_pipeline.stages.lib.silhouette import (
    ProportionReport,
    SilhouetteError,
    check_proportions,
    mask_from_image,
    measure_side,
)

# spec 9.1a guard 1: wheelbase/length and height/length within 2% of the data's.
_TOLERANCE = 0.02


@register("proportion")
def proportion(asset: AssetSpec, settings: Settings) -> StageResult:
    try:
        dims = load_dimensions(settings.repo_root, asset.generation, subject_body(asset.subject))
        synth = stage_dir(settings, asset.id, "synth")
        side = synth / "views" / "side.png"
        report_path = synth / "proportion.json"
        # The two guards take their arguments in opposite orders, so both get keywords.
        require_outside_repo(repo_root=settings.repo_root, path=side)
        require_write_target_outside_repo(dest=report_path, repo_root=settings.repo_root)
    except ValueError as error:  # DimensionsError and the path guards are ValueErrors
        return StageResult(False, [str(error)], [])

    # An earlier report describes an earlier picture: drop it first, so no failure below leaves
    # an `ok: true` that `synth_set_usable` could weigh against a new image.
    try:
        report_path.unlink(missing_ok=True)
    except OSError as error:
        return StageResult(False, [f"could not remove the old report {report_path}: {error}"], [])

    try:
        data = side.read_bytes()
    except FileNotFoundError:
        return StageResult(False, [f"{side} does not exist; run --stage synth first"], [])
    except OSError as error:
        return StageResult(False, [f"could not read {side}: {error}"], [])
    digest = hashlib.sha256(data).hexdigest()

    try:
        report = _measure(data, dims)
    except SilhouetteError as error:
        body: dict[str, object] = {"ok": False, "error": str(error), "side_sha256": digest}
        message = f"the side view cannot be measured: {error}"
        return _finish(False, [message], report_path, body)

    body = {**asdict(report), "side_sha256": digest}
    return _finish(report.ok, _messages(report), report_path, body)


def _measure(data: bytes, dims: Dimensions) -> ProportionReport:
    """Measure the picture in `data`. Anything wrong with the picture is a SilhouetteError."""
    from PIL import Image  # kept out of the module's imports: see silhouette.py

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        raise SilhouetteError(f"could not decode the image: {error}") from error
    measure = measure_side(mask_from_image(image))
    return check_proportions(measure, dims, _TOLERANCE)


def _messages(report: ProportionReport) -> list[str]:
    """One line per ratio, so a failure says which one is off and by how much."""
    verdict = "ok" if report.ok else "not ok"
    return [
        f"proportions {verdict} (each error must be at most {_TOLERANCE:.0%})",
        (
            f"wheelbase/length {report.wheelbase_over_length:.4f}, expected "
            f"{report.expected_wheelbase_over_length:.4f}: wheelbase error "
            f"{report.wheelbase_error:.2%}"
        ),
        (
            f"height/length {report.height_over_length:.4f}, expected "
            f"{report.expected_height_over_length:.4f}: height error {report.height_error:.2%}"
        ),
    ]


def _finish(ok: bool, messages: list[str], path: Path, body: dict[str, object]) -> StageResult:
    try:
        path.write_text(json.dumps(body, indent=2) + "\n", "utf-8")
    except OSError as error:
        return StageResult(False, [f"could not write {path}: {error}"], [])
    return StageResult(ok, messages, [path])
