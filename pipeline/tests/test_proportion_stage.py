import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image
from silhouette_helpers import BACKGROUND, draw_car

from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings
from m3_pipeline.stages import REGISTRY
from m3_pipeline.stages.lib.silhouette import ProportionReport
from m3_pipeline.stages.proportion import proportion

ASSET = AssetSpec("e46-coupe-body", "base-car", "e46", "e46-coupe")

GENERATION_YAML = """\
id: e46
dimensions:
  coupe:
    lengthMm: 4492
    widthMm: 1780
    heightMm: 1372
    wheelbaseMm: 2731
    trackFrontMm: 1508
    trackRearMm: 1525
    sources: []
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    repo = tmp_path / "repo"
    (repo / "data" / "generations").mkdir(parents=True)
    (repo / "data" / "generations" / "e46.yaml").write_text(GENERATION_YAML, "utf-8")
    return Settings(repo_root=repo, work_dir=tmp_path / "work")


def _synth(settings: Settings) -> Path:
    return settings.work_dir / "assets" / ASSET.id / "synth"


def _side(settings: Settings) -> Path:
    return _synth(settings) / "views" / "side.png"


def _report(settings: Settings) -> Path:
    return _synth(settings) / "proportion.json"


def _put_side(settings: Settings, image: Image.Image) -> Path:
    path = _side(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _read_report(settings: Settings) -> dict[str, object]:
    data: dict[str, object] = json.loads(_report(settings).read_text("utf-8"))
    return data


def _number(report: dict[str, object], key: str) -> float:
    value = report[key]
    assert isinstance(value, float), f"{key} is {value!r}"
    return value


def test_proportion_is_registered() -> None:
    assert "proportion" in REGISTRY


def test_proportion_stage_writes_the_report_and_is_ok_for_a_good_side_view(
    settings: Settings,
) -> None:
    image, _ = draw_car()
    _put_side(settings, image)
    result = proportion(ASSET, settings)
    assert result.ok, result.messages
    assert result.outputs == [_report(settings)]
    report = _read_report(settings)
    assert report["ok"] is True
    assert set(ProportionReport.__dataclass_fields__) | {"side_sha256"} == set(report)
    assert report["expected_wheelbase_over_length"] == pytest.approx(2731 / 4492)
    assert report["expected_height_over_length"] == pytest.approx(1372 / 4492)
    assert report["wheelbase_over_length"] == pytest.approx(2731 / 4492, rel=0.02)
    assert report["height_over_length"] == pytest.approx(1372 / 4492, rel=0.02)
    assert _number(report, "wheelbase_error") <= 0.02
    assert _number(report, "height_error") <= 0.02


def test_proportion_stage_is_not_ok_on_failure_and_still_writes_the_report(
    settings: Settings,
) -> None:
    image, _ = draw_car(wheelbase_scale=1.06)
    _put_side(settings, image)
    result = proportion(ASSET, settings)
    assert not result.ok
    assert any("wheelbase" in message for message in result.messages), result.messages
    assert result.outputs == [_report(settings)]
    report = _read_report(settings)
    assert report["ok"] is False
    assert _number(report, "wheelbase_error") > 0.02
    assert "error" not in report


def test_proportion_stage_records_the_sha256_of_the_measured_image(settings: Settings) -> None:
    image, _ = draw_car()
    side = _put_side(settings, image)
    assert proportion(ASSET, settings).ok
    assert _read_report(settings)["side_sha256"] == hashlib.sha256(side.read_bytes()).hexdigest()

    # A different picture gives a different digest, so a stale report can't pass for the new one.
    replacement, _ = draw_car(1.5, wheelbase_scale=1.08)
    side = _put_side(settings, replacement)
    assert not proportion(ASSET, settings).ok
    assert _read_report(settings)["side_sha256"] == hashlib.sha256(side.read_bytes()).hexdigest()


def test_proportion_stage_writes_ok_false_and_the_error_when_the_silhouette_is_unusable(
    settings: Settings,
) -> None:
    side = _put_side(settings, Image.new("RGB", (400, 300), BACKGROUND))
    result = proportion(ASSET, settings)
    assert not result.ok
    assert any("empty" in message for message in result.messages), result.messages
    report = _read_report(settings)
    assert report == {
        "ok": False,
        "error": "empty",
        "side_sha256": hashlib.sha256(side.read_bytes()).hexdigest(),
    }


def test_proportion_stage_reports_a_picture_it_cannot_decode_as_unusable(
    settings: Settings,
) -> None:
    side = _side(settings)
    side.parent.mkdir(parents=True)
    side.write_bytes(b"this is not a png")
    result = proportion(ASSET, settings)
    assert not result.ok
    report = _read_report(settings)
    assert report["ok"] is False
    assert "decode" in str(report["error"])
    assert report["side_sha256"] == hashlib.sha256(b"this is not a png").hexdigest()


def test_proportion_stage_needs_the_side_view(settings: Settings) -> None:
    result = proportion(ASSET, settings)
    assert not result.ok
    assert any("side.png" in message and "synth" in message for message in result.messages)
    assert not _report(settings).exists()


def test_a_missing_side_view_removes_the_report_of_an_earlier_run(settings: Settings) -> None:
    image, _ = draw_car()
    side = _put_side(settings, image)
    assert proportion(ASSET, settings).ok
    side.unlink()
    assert not proportion(ASSET, settings).ok
    assert not _report(settings).exists()  # an old `ok: true` must not outlive its image


def test_proportion_stage_refuses_a_work_dir_inside_the_repo(settings: Settings) -> None:
    inside = Settings(repo_root=settings.repo_root, work_dir=settings.repo_root / "work")
    image, _ = draw_car()
    _put_side(inside, image)
    result = proportion(ASSET, inside)
    assert not result.ok
    assert "inside the repo" in " ".join(result.messages)
    assert not _report(inside).exists()


def test_proportion_stage_names_the_data_file_when_the_generation_is_unknown(
    settings: Settings,
) -> None:
    result = proportion(AssetSpec("e90-coupe-body", "base-car", "e90", "e90-coupe"), settings)
    assert not result.ok
    assert "e90.yaml" in " ".join(result.messages)


def test_proportion_stage_rejects_a_subject_that_names_no_car_body(settings: Settings) -> None:
    result = proportion(AssetSpec("wheel", "product", "e46", "product-wheel"), settings)
    assert not result.ok
    assert "product-wheel" in " ".join(result.messages)
