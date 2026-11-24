import hashlib
import json
import re
from pathlib import Path

import pytest
from PIL import Image
from silhouette_helpers import BACKGROUND, add_contact_shadows, draw_car

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
    assert result.messages[0].startswith("proportions ok")
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
    assert result.outputs == [_report(settings)]
    report = _read_report(settings)
    # The messages must carry the numbers of the report: the verdict, and the error that failed.
    assert result.messages[0].startswith("proportions not ok")
    assert f"wheelbase error {_number(report, 'wheelbase_error'):.2%}" in " ".join(result.messages)
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


def test_a_rerun_without_the_dimensions_leaves_no_report_behind(settings: Settings) -> None:
    image, _ = draw_car()
    _put_side(settings, image)
    assert proportion(ASSET, settings).ok
    assert _report(settings).exists()

    # The data file loses its dimensions; the picture is unchanged and would still pass.
    (settings.repo_root / "data" / "generations" / "e46.yaml").write_text("id: e46\n", "utf-8")
    result = proportion(ASSET, settings)
    assert not result.ok
    assert "dimensions" in " ".join(result.messages)
    assert not _report(settings).exists()  # an old `ok: true` must not outlive the data it used


def test_a_rerun_with_a_subject_that_has_no_body_leaves_no_report_behind(
    settings: Settings,
) -> None:
    image, _ = draw_car()
    _put_side(settings, image)
    assert proportion(ASSET, settings).ok
    same_id_wheel = AssetSpec(ASSET.id, "product", "e46", "product-wheel")
    assert not proportion(same_id_wheel, settings).ok
    assert not _report(settings).exists()


def test_the_messages_carry_what_each_wheel_measurement_rests_on(settings: Settings) -> None:
    image, truth = draw_car()
    _put_side(settings, image)
    result = proportion(ASSET, settings)
    for name, expected in (("front", truth.front_center), ("rear", truth.rear_center)):
        [line] = [m for m in result.messages if m.startswith(f"{name} wheel")]
        center = re.search(r"center \((\d+\.\d), (\d+\.\d)\) px", line)
        radius = re.search(r"radius (\d+\.\d) px", line)
        assert center is not None and radius is not None, line
        assert float(center[1]) == pytest.approx(expected[0], abs=0.01 * truth.length_px)
        assert float(center[2]) == pytest.approx(expected[1], abs=0.01 * truth.length_px)
        assert float(radius[1]) == pytest.approx(truth.tire_radius_px, rel=0.03)
        assert re.search(r"bump columns \d+-\d+ \(\d+ wide\)", line)
        assert re.search(r"residual \d+\.\d+% of the radius", line)
        assert re.search(r"coverage \d+%", line) and re.search(r"arc \d+ degrees", line)
    # The report file keeps the plan's keys, whatever the messages say.
    assert set(_read_report(settings)) == set(ProportionReport.__dataclass_fields__) | {
        "side_sha256"
    }


def test_an_unmeasurable_wheel_pair_says_why_in_the_report_and_the_messages(
    settings: Settings,
) -> None:
    image, truth = draw_car(wheelbase_scale=1.06)
    add_contact_shadows(image, truth, inward_px=0)  # a shadow under each whole tire
    _put_side(settings, image)
    result = proportion(ASSET, settings)
    assert not result.ok
    report = _read_report(settings)
    assert set(report) == {"ok", "error", "side_sha256"}
    assert str(report["error"]).startswith("wheels not found")
    assert "residual" in str(report["error"]) or "radius" in str(report["error"])
    assert "a floor or contact shadow may have merged into the silhouette" in str(report["error"])
    assert "wheels not found" in " ".join(result.messages)
