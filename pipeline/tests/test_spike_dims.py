from pathlib import Path

import pytest

from m3_pipeline.stages.lib.dims import (
    DimensionsError,
    load_dimensions,
    load_eye_point_m,
    load_stock_tires,
    tire_radius_m,
    tire_width_m,
)

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
driverEyePoint:
  xMm: -370
  yMm: 1100
  zMm: 0
  basis: estimated
fitment:
  front:
    stock: {diameterIn: 18, tire: 225/45ZR18}
  rear:
    stock: {diameterIn: 18, tire: 255/40ZR18}
"""


def _repo(tmp_path: Path, text: str = GENERATION_YAML) -> Path:
    path = tmp_path / "data/generations/e46.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(text, "utf-8")
    return tmp_path


def test_load_dimensions_reads_a_generation_body(tmp_path: Path) -> None:
    dims = load_dimensions(_repo(tmp_path), "e46", "coupe")
    assert (dims.length_mm, dims.width_mm, dims.height_mm) == (4492, 1780, 1372)
    assert (dims.wheelbase_mm, dims.track_front_mm, dims.track_rear_mm) == (2731, 1508, 1525)
    assert isinstance(dims.length_mm, float)


def test_load_dimensions_unknown_body_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(DimensionsError, match=r"e46\.yaml.*convertible"):
        load_dimensions(_repo(tmp_path), "e46", "convertible")


def test_load_dimensions_missing_generation_names_the_file(tmp_path: Path) -> None:
    with pytest.raises(DimensionsError, match=r"e90\.yaml"):
        load_dimensions(tmp_path, "e90", "coupe")


def test_load_dimensions_missing_key_names_the_file_and_key(tmp_path: Path) -> None:
    repo = _repo(tmp_path, GENERATION_YAML.replace("    wheelbaseMm: 2731\n", ""))
    with pytest.raises(DimensionsError, match=r"e46\.yaml.*wheelbaseMm"):
        load_dimensions(repo, "e46", "coupe")


def test_load_dimensions_rejects_a_value_that_is_not_a_number(tmp_path: Path) -> None:
    repo = _repo(tmp_path, GENERATION_YAML.replace("lengthMm: 4492", 'lengthMm: "4492"'))
    with pytest.raises(DimensionsError, match=r"e46\.yaml.*lengthMm"):
        load_dimensions(repo, "e46", "coupe")


def test_load_dimensions_rejects_yaml_that_is_not_a_mapping(tmp_path: Path) -> None:
    with pytest.raises(DimensionsError, match=r"e46\.yaml"):
        load_dimensions(_repo(tmp_path, "- just\n- a list\n"), "e46", "coupe")


@pytest.mark.parametrize("generation", ["../e46", "E46", "e46/x", ""])
def test_load_dimensions_refuses_a_generation_that_could_leave_the_data_folder(
    tmp_path: Path, generation: str
) -> None:
    with pytest.raises(DimensionsError, match="generation"):
        load_dimensions(_repo(tmp_path), generation, "coupe")


def test_load_eye_point_converts_mm_to_m(tmp_path: Path) -> None:
    assert load_eye_point_m(_repo(tmp_path), "e46") == pytest.approx((-0.37, 1.1, 0.0))


def test_load_eye_point_missing_key_names_the_file_and_key(tmp_path: Path) -> None:
    repo = _repo(tmp_path, GENERATION_YAML.replace("  yMm: 1100\n", ""))
    with pytest.raises(DimensionsError, match=r"e46\.yaml.*yMm"):
        load_eye_point_m(repo, "e46")


def test_load_stock_tires_reads_both_axles(tmp_path: Path) -> None:
    assert load_stock_tires(_repo(tmp_path), "e46") == {
        "front": "225/45ZR18",
        "rear": "255/40ZR18",
    }


def test_load_stock_tires_missing_tire_names_the_file_and_key(tmp_path: Path) -> None:
    repo = _repo(tmp_path, GENERATION_YAML.replace(", tire: 255/40ZR18", ""))
    with pytest.raises(DimensionsError, match=r"e46\.yaml.*fitment\.rear\.stock\.tire"):
        load_stock_tires(repo, "e46")


def test_the_real_e46_file_loads() -> None:
    # Guards the field names this module reads against a schema change in data/.
    repo = Path(__file__).resolve().parents[2]
    assert load_dimensions(repo, "e46", "coupe").wheelbase_mm == 2731
    assert load_stock_tires(repo, "e46")["front"] == "225/45ZR18"
    assert len(load_eye_point_m(repo, "e46")) == 3


def test_tire_radius_from_the_code() -> None:
    assert tire_radius_m("225/45ZR18") == pytest.approx(0.32985, abs=1e-5)
    assert tire_radius_m("255/40ZR18") == pytest.approx(0.3306, abs=1e-5)


def test_tire_width_from_the_code() -> None:
    assert tire_width_m("225/45ZR18") == pytest.approx(0.225)
    assert tire_width_m("255/40ZR18") == pytest.approx(0.255)


@pytest.mark.parametrize("code", ["225/45R18", "225/45 ZR 18"])
def test_tire_codes_without_the_z_or_with_spaces_parse_the_same(code: str) -> None:
    assert tire_radius_m(code) == pytest.approx(0.32985, abs=1e-5)


@pytest.mark.parametrize("code", ["", "225", "225/45-18", "P225/45ZR18x", "abc/de/fgh"])
def test_a_tire_code_that_does_not_parse_raises(code: str) -> None:
    with pytest.raises(ValueError, match="tire"):
        tire_radius_m(code)
    with pytest.raises(ValueError, match="tire"):
        tire_width_m(code)
