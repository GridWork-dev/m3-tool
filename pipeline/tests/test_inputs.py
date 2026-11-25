from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from m3_pipeline.stages.lib import inputs
from m3_pipeline.stages.lib.inputs import (
    Box,
    InputsNotReviewed,
    ensure_reviewed,
    load_redactions,
    prepare_image,
    propose_redactions,
    save_redactions,
    validate_redaction_orientation,
)
from m3_pipeline.stages.lib.viewset_io import ViewRef


def _ref(tmp_path: Path) -> ViewRef:
    path = tmp_path / "original.png"
    Image.new("RGB", (20, 10), (255, 0, 0)).save(path)
    return ViewRef(
        "front",
        "photo-1",
        path,
        None,
        False,
        "All rights reserved",
        None,
        None,
        "https://commons.wikimedia.org/wiki/File:Car.png",
        "lhd",
        None,
        False,
    )


def test_prepare_image_masks_redaction_boxes_with_flat_gray(tmp_path: Path) -> None:
    ref = _ref(tmp_path)
    prepared = prepare_image(ref, tmp_path, tmp_path / "out", [Box(2, 3, 4, 2, "plate")])
    with Image.open(prepared.path) as image:
        assert image.getpixel((2, 3)) == (128, 128, 128)
        assert image.getpixel((5, 4)) == (128, 128, 128)
        assert image.getpixel((6, 4)) == (255, 0, 0)
    assert prepared.redactions == 1
    with Image.open(ref.image_path) as original:
        assert original.getpixel((2, 3)) == (255, 0, 0)


def test_prepare_image_mirrors_when_flagged(tmp_path: Path) -> None:
    ref = replace(_ref(tmp_path), mirrored=True)
    prepared = prepare_image(ref, tmp_path, tmp_path / "out", [Box(0, 0, 2, 10, "person")])
    with Image.open(prepared.path) as image:
        assert image.getpixel((19, 0)) == (128, 128, 128)
        assert image.getpixel((0, 0)) == (255, 0, 0)
    assert prepared.mirrored


def test_prepare_image_strips_exif_and_caps_the_long_side_at_2048(tmp_path: Path) -> None:
    ref = _ref(tmp_path)
    exif = Image.Exif()
    exif[270] = "private location"
    Image.new("RGB", (4096, 2048)).save(ref.image_path, exif=exif)
    prepared = prepare_image(ref, tmp_path, tmp_path / "out", [])
    with Image.open(prepared.path) as image:
        assert image.size == (2048, 1024)
        assert not image.getexif()
        assert not image.info


def test_ensure_reviewed_names_every_unknown_image(tmp_path: Path) -> None:
    prepared = prepare_image(_ref(tmp_path), tmp_path, tmp_path / "out", [])
    with pytest.raises(InputsNotReviewed, match="photo-1"):
        ensure_reviewed([prepared], [])
    ensure_reviewed([prepared], ["photo-1"])


def test_propose_redactions_runs_on_a_commons_photo_whatever_its_license(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _ref(tmp_path)
    calls: list[dict[str, Any]] = []

    def fake(prompt: str, images: list[Path], **kwargs: Any) -> str:
        assert prompt and not prompt.startswith("-")
        assert images == [tmp_path / "scratch/photo-1-upright.png"]
        with Image.open(images[0]) as image:
            assert image.size == (20, 10)
            assert not image.getexif()
        calls.append(kwargs)
        return '[{"x":1,"y":2,"w":3,"h":4,"kind":"plate"}]'

    monkeypatch.setattr(inputs, "run_codex", fake)
    assert propose_redactions(ref, tmp_path, cwd=tmp_path / "scratch") == [Box(1, 2, 3, 4, "plate")]
    assert calls[0]["sandbox"] == "read-only"
    assert calls[0]["last_message"].is_absolute()


@pytest.mark.parametrize(
    "url", [None, "https://example.com/x", "https://commons.wikimedia.org.evil/x"]
)
def test_propose_redactions_refuses_a_photo_that_is_not_on_commons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str | None
) -> None:
    def fake(*args: Any, **kwargs: Any) -> str:
        pytest.fail("private input must not reach Codex")

    monkeypatch.setattr(inputs, "run_codex", fake)
    with pytest.raises(ValueError, match="hand-written"):
        propose_redactions(
            replace(_ref(tmp_path), page_url=url), tmp_path, cwd=tmp_path / "scratch"
        )


@pytest.mark.parametrize("reply", ["No plates found", "{}", '[{"x":false}]'])
def test_propose_redactions_raises_on_a_prose_reply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    def fake(*args: object, **kwargs: object) -> str:
        return reply

    monkeypatch.setattr(inputs, "run_codex", fake)
    with pytest.raises(ValueError):
        propose_redactions(_ref(tmp_path), tmp_path, cwd=tmp_path / "scratch")


def test_redactions_round_trip_through_the_cache(tmp_path: Path) -> None:
    path = tmp_path / "inputs/redactions.json"
    boxes = {"photo-1": [Box(1, 2, 3, 4, "person")], "photo-2": []}
    save_redactions(path, boxes)
    assert load_redactions(path) == boxes
    assert "unknown" not in load_redactions(path)
    assert load_redactions(tmp_path / "missing.json") == {}


@pytest.mark.parametrize("image_id", ["../escape", "/absolute", "a/b"])
def test_prepare_rejects_unsafe_image_ids(tmp_path: Path, image_id: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        prepare_image(replace(_ref(tmp_path), image_id=image_id), tmp_path, tmp_path / "out", [])


def test_prepare_refuses_overwriting_original(tmp_path: Path) -> None:
    ref = replace(_ref(tmp_path), image_id="original")
    with pytest.raises(ValueError, match="overwrite"):
        prepare_image(ref, tmp_path, tmp_path, [])


def test_prepare_rejects_work_dir_escape(tmp_path: Path) -> None:
    ref = _ref(tmp_path)
    with pytest.raises(ValueError, match="outside work_dir"):
        prepare_image(ref, tmp_path / "elsewhere", tmp_path / "out", [])


def test_prepare_rejects_a_destination_link_into_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _ref(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(inputs, "_REPO", repo)
    (tmp_path / "out").symlink_to(repo, target_is_directory=True)
    with pytest.raises(ValueError, match="inside the repo"):
        prepare_image(ref, tmp_path, tmp_path / "out", [])


def test_prepared_output_cannot_escape_work_dir_through_symlink(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (work / "out").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside work_dir"):
        prepare_image(_ref(work), work, work / "out", [])
    assert not list(outside.iterdir())


@pytest.mark.parametrize("target", ["cwd", "last_message", "original"])
def test_proposal_paths_cannot_escape_work_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    ref = _ref(work)
    outside = tmp_path / "outside"
    outside.mkdir()
    cwd = work / "scratch"
    if target == "cwd":
        cwd.symlink_to(outside, target_is_directory=True)
    elif target == "last_message":
        cwd.mkdir()
        (cwd / "redaction-proposal.json").symlink_to(outside / "reply.json")
    else:
        original = outside / "original.png"
        ref.image_path.rename(original)
        ref.image_path.symlink_to(original)

    def fake(*args: Any, **kwargs: Any) -> str:
        pytest.fail("escaped paths must never reach Codex")

    monkeypatch.setattr(inputs, "run_codex", fake)
    with pytest.raises(ValueError, match="outside work_dir"):
        propose_redactions(ref, work, cwd=cwd)


@pytest.mark.parametrize("raw", [None, [], {"id": None}, {"id": {}}, {"id": [False]}])
def test_malformed_redaction_cache_is_never_treated_as_reviewed(
    tmp_path: Path, raw: object
) -> None:
    import json

    path = tmp_path / "redactions.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError):
        load_redactions(path)


def _oriented_ref(tmp_path: Path) -> ViewRef:
    ref = _ref(tmp_path)
    # EXIF 6 rotates 90 clockwise: raw top-left plate lands at upright top-right.
    image = Image.new("RGB", (6, 4), "white")
    image.putpixel((0, 0), (255, 0, 0))
    exif = Image.Exif()
    exif[274] = 6
    image.save(ref.image_path, exif=exif)
    return ref


def test_upright_proposal_and_masking_use_identical_exif_pixel_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _oriented_ref(tmp_path)

    def fake(prompt: str, images: list[Path], **kwargs: Any) -> str:
        with Image.open(images[0]) as proposal:
            assert proposal.size == (4, 6)
            assert proposal.getpixel((3, 0)) == (255, 0, 0)
            assert not proposal.getexif()
        return '[{"x":3,"y":0,"w":1,"h":1,"kind":"plate"}]'

    monkeypatch.setattr(inputs, "run_codex", fake)
    boxes = propose_redactions(ref, tmp_path, cwd=tmp_path / "scratch")
    for mirrored in (False, True):
        prepared = prepare_image(
            replace(ref, mirrored=mirrored), tmp_path, tmp_path / f"prepared-{mirrored}", boxes
        )
        with Image.open(prepared.path) as result:
            assert result.size == (4, 6)
            assert result.getpixel((0 if mirrored else 3, 0)) == (128, 128, 128)
            assert (255, 0, 0) not in result.get_flattened_data()
            assert not result.getexif()


def test_legacy_rotated_cache_requires_explicit_upright_review(tmp_path: Path) -> None:
    ref = _oriented_ref(tmp_path)
    path = tmp_path / "redactions.json"
    boxes = {ref.image_id: [Box(3, 0, 1, 1, "plate")]}
    save_redactions(path, boxes)
    with pytest.raises(InputsNotReviewed, match="privacy re-review"):
        validate_redaction_orientation(ref, path)
    save_redactions(path, boxes, upright_ids=[ref.image_id])
    validate_redaction_orientation(ref, path)
    save_redactions(path, {**boxes, "other": []})
    validate_redaction_orientation(ref, path)
    assert load_redactions(path)[ref.image_id] == boxes[ref.image_id]


def test_legacy_unrotated_cache_keeps_its_review(tmp_path: Path) -> None:
    ref = _ref(tmp_path)
    path = tmp_path / "redactions.json"
    save_redactions(path, {ref.image_id: []})
    validate_redaction_orientation(ref, path)
