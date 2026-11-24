import shutil
from pathlib import Path

import pytest

from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings
from m3_pipeline.refs.description import DescriptionError, build_description

BODY = AssetSpec("e46-coupe-body", "base-car", "e46", "e46-coupe")


@pytest.fixture
def repo(tmp_path: Path) -> Settings:
    root = tmp_path / "repo-fixture"
    shutil.copytree(Path(__file__).parent / "fixtures/refs", root)
    return Settings(repo_root=root, work_dir=tmp_path / "work")


def test_base_car_description_has_prompt_dimensions_and_checklist(repo: Settings) -> None:
    d = build_description(BODY, repo)
    assert all(
        s in d
        for s in (
            "## Generator prompt",
            "## Critic checklist",
            "E46 M3",
            "coupe",
            "2001",
            "S54",
            "4500 mm",
            "4.500 m",
            "2700 mm",
            "1500 mm",
        )
    )
    assert "- [ ] No manufacturer badges, logos or roundels" in d and "left-hand drive" in d
    assert "within 1%" in d and "placeholders" in d


def test_interior_description_lists_components_and_left_hand_drive(repo: Settings) -> None:
    d = build_description(AssetSpec("interior", "interior", "e46", "e46-coupe-interior"), repo)
    assert all(
        s in d
        for s in (
            "dash with gauge cluster",
            "steering wheel",
            "seats",
            "door cards",
            "center console",
            "left-hand",
            "no roundel on the steering wheel or gauges",
        )
    )


def test_product_description_comes_from_part_yaml(repo: Settings) -> None:
    # Product prompts must not need or borrow generation data.
    (repo.repo_root / "data/generations/e46.yaml").unlink()
    d = build_description(AssetSpec("wheel", "product", "e46", "product-wheel-a"), repo)
    assert all(
        s in d for s in ("Fixture Wheel A", "Fixture Co", "wheels", "spokes: 7", "finish: silver")
    )
    assert "- [ ] Small diameter" in d and "- [ ] Large diameter" in d


def test_hand_written_notes_are_appended_verbatim(repo: Settings) -> None:
    assert "## Notes (hand-written)" not in build_description(BODY, repo)
    notes = repo.repo_root / "pipeline/descriptions/e46-coupe.md"
    notes.parent.mkdir(parents=True)
    text = "Keep this exactly.\n\n*Original notes.*\n"
    notes.write_text(text)
    assert build_description(BODY, repo).endswith("## Notes (hand-written)\n\n" + text)


def test_missing_generation_body_or_part_raises_description_error_naming_the_file(
    repo: Settings,
) -> None:
    with pytest.raises(DescriptionError, match=r"e46.yaml.*convertible"):
        build_description(AssetSpec("x", "base-car", "e46", "e46-convertible"), repo)
    with pytest.raises(DescriptionError, match=r"generations/e36.yaml"):
        build_description(AssetSpec("x", "base-car", "e36", "e36-coupe"), repo)
    with pytest.raises(DescriptionError, match=r"parts/e46/missing.yaml"):
        build_description(AssetSpec("x", "product", "e46", "product-missing"), repo)
    path = repo.repo_root / "data/generations/e46.yaml"
    path.write_text(path.read_text().replace("name: E46 M3\n", ""))
    with pytest.raises(DescriptionError, match=r"e46.yaml.*name"):
        build_description(BODY, repo)


def test_engine_extras_render_as_sorted_key_value_pairs(repo: Settings) -> None:
    d = build_description(BODY, repo)
    assert "S54 (displacement 3.2 L)" in d
    path = repo.repo_root / "data/generations/e46.yaml"
    path.write_text(
        path.read_text().replace("    displacement: 3.2 L", "    z: last\n    a: first")
    )
    assert "S54 (a first, z last)" in build_description(BODY, repo)


def test_product_option_without_attributes_is_valid(repo: Settings) -> None:
    path = repo.repo_root / "data/parts/e46/wheel-a.yaml"
    path.write_text(path.read_text().replace("    attributes:\n      diameterIn: 18\n", ""))
    description = build_description(AssetSpec("wheel", "product", "e46", "product-wheel-a"), repo)
    assert "- [ ] Small diameter\n" in description
    assert "- [ ] Large diameter: diameterIn: 19" in description
